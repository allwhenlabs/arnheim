/* Each floor's lead, at work on a page (leads.js has the rules): what they say and in what order, what waits
   for your word, their card's buttons, putting you through to them, and going where you ask. A page hands it
   what it knows, so Arnheim's own page and any page that embeds the building have the same leads.

   const leads = createLeadDesk({
     company,                  // a name (or a function giving it) for what this browser remembers
     floors(),                 // every floor: { id, label, project, lead }
     label(project),           // the floor a project is on, by its label
     view(floor),              // where the floor stands, in leads.js leadUpdate's shape
     agents(floor),            // its agents, as [{ id, title, working }]
     moments(floor),           // what happened there today (replay.js moments)
     waiting(),                // everything that waits on you (queue.js items)
     canAnswer(item),          // whether a request can be answered from here
     answer(act),              // answers one: { id, behavior, item } -> what to say, or a promise of it
     show(item),               // puts something that must be answered on the screen
     control,                  // control.js, or null: on, say, halt, projects
     places(), go(href), back(), walking(),   // "take me to ..."
     think(floor, said),       // optional: Claude's answer from the floor's facts, an async iterable, or null
     prime(floor),             // optional: Claude reads the floor's facts as you walk up
     features,                 // features.js: leads and answers can be switched off
     madeUp(), notConnected(), // why nothing real can be done here, when it can't
   });

   leads.lead(floorId), leads.who(floor), leads.floorOf(who), leads.greet(floor, who), leads.says(floor, text,
   { spoken }), leads.controls(floor), leads.update(floor), leads.passed(floor), leads.through(who, text, desk),
   leads.go(text): what talk.js asks of a page (docs/embed.md), for the leads. And:
   leads.round(text)        "give me the round": every lead in turn, a line each ({ turns }, voice.js), or null
   leads.speakUp(floor)     what a lead (or, with null, the front desk) tells you unasked: what came of what you
                            asked them to pass on, once it is done, stuck or needs you; or null
   leads.remember(floor, { key, text })   an instruction the brain passed on, so it is reported back too (floor:
                            null for the assistant's, whose agent may be on any floor) */

import { deskControls, deskStart, handedOut } from './control.js';
import { floorNamed, goAsked, hasLead, isLeadHref, leadAsked, leadHelp, leadNews, leadOf, leadRoundLine, leadUpdate, leadWho, needsSaying, noSaid, passTarget, pickFrom, reportOf, roundAsked, throughAsked, voiceAnswer, yesSaid } from './leads.js';
import { sayWaiting } from './queue.js';
import { sinceSaid } from './brief.js';
import { riskOf } from './risk.js';

export const WAITING = /\b(?:wait(?:s|ing)? (?:on|for) (?:me|you)|needs? me|need anything from me|my queue|what(?:'s| is) (?:on|in) my (?:plate|queue))\b/i;
export const BACK_TO_DESK = /^(?:(?:ok|okay|right|so|please)[,\s]+)*(?:(?:talk|speak) (?:to|with)|back to|put me (?:back )?through to|get me|take me back to)\s+(?:the\s+)?(?:receptionist|front desk|reception)[.!?]*$/i;
const STOP_THEM = /^(?:(?:ok|okay|right|so|please)[,\s]+)*stop\s+(them|it|everyone|everybody|all of them|the agents?|work(?:ing)?|the\s+(?:one|agent)\s+(?:on|working on|doing)\s+.+?)[.!]*$/i;
const ORDINAL = ['first', 'second', 'third', 'fourth'];
const lowerFirst = (t) => (t && !/^(?:I\b|I'|[A-Z]{2})/.test(t) ? t[0].toLowerCase() + t.slice(1) : t);
const targetsSaid = (list) => (list.length === 1 ? `the one on "${list[0].title}"` : `all ${list.length} of them`);

const stored = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback; } catch { return fallback; } };
const store = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* a private window: it lasts this visit */ } };

export function createLeadDesk(env) {
  const on = () => !!env.control?.on;
  const leadsOn = () => env.features?.get('leads') !== false;
  const answersOn = () => env.features?.get('answers') !== false;
  const reportingOn = () => env.features?.get('reports') !== false;
  const floorsWith = () => env.floors().filter(hasLead);
  const whoOf = (floor) => ({ ...leadOf(floor), sub: `${floor.label}'s lead` });
  const floorOf = (who) => (isLeadHref(who?.href) && leadsOn() ? floorsWith().find((f) => leadOf(f).href === who.href) || null : null);
  const mem = new Map(); // floor id -> what waits for your word: one of { voice, start, send, which, stop }
  const memOf = (id) => { if (!mem.has(id)) mem.set(id, {}); return mem.get(id); };
  // Only the last question waits for your word: a new one ends any before it, so a "yes", "no" or "cancel"
  // always answers the question just asked, never an older one still waiting.
  const waitFor = (m, what, value) => {
    for (const k of ['voice', 'start', 'send', 'which', 'stop']) m[k] = null;
    m[what] = value;
  };

  // What each lead has passed on for you, and when you last heard their news, in this browser.
  const company = () => (typeof env.company === 'function' ? env.company() : env.company) || '';
  const PASSED = () => `arnheim-passed:${company()}`;
  const SEEN = () => `arnheim-lead-seen:${company()}`;
  const ROUND = () => `arnheim-round:${company()}`;
  let passedMem = null;
  let passedKey = null;
  const passedAll = () => {
    if (passedKey !== PASSED()) { passedKey = PASSED(); passedMem = Array.isArray(stored(passedKey, [])) ? stored(passedKey, []) : []; }
    return passedMem;
  };
  function rememberPassed(entry) {
    const now = Date.now() / 1000;
    passedMem = [...passedAll().filter((p) => now - p.at < 2 * 86400), entry].slice(-40);
    store(passedKey, passedMem);
  }
  const passedOn = (floor) => { const now = Date.now() / 1000; return passedAll().filter((p) => p.project === floor.project && now - p.at < 2 * 86400); };
  const keepPassed = () => store(passedKey, passedMem);

  // What came of each instruction passed on from this floor (leads.js reportOf), and those a lead hasn't told
  // you yet: done, stuck or needing you. Telling one marks it, so each is said once (a new one is told, such as
  // its checks passing after it said it was done; one already told is not told again).
  function reportsOn(floor) {
    const mine = passedOn(floor);
    if (!mine.length) return [];
    const now = Date.now() / 1000;
    const ctx = { moments: env.moments(floor), conversations: env.view(floor).conversations, waiting: waitingOn(floor), agents: env.agents(floor), now };
    return mine.map((p) => ({ p, r: reportOf(p, ctx) }));
  }
  // Only instructions passed on since this was built are told unasked (they carry `told`); once one was told it
  // is done or stopped, only news of its checks follows (done, then proven), never a "stuck" or a "needs you" for
  // work that already ended. What needs you comes first, then what may be stuck, then the rest.
  const FIRST = (state) => (state.startsWith('needs') ? 0 : state === 'stuck' ? 1 : state === 'stopped' ? 2 : 3);
  const ended = (p) => p.told.some((t) => t.startsWith('done') || t === 'stopped');
  const untold = (floor) => (reportsOn(floor) || [])
    .filter(({ p, r }) => Array.isArray(p.told) && r.final && !p.told.includes(r.state) && (!ended(p) || r.state.startsWith('done')))
    .sort((a, b) => FIRST(a.r.state) - FIRST(b.r.state) || a.p.at - b.p.at);
  // Marks as told only what was said.
  function told(list) {
    if (!list.length) return;
    for (const { p, r } of list) p.told = [...p.told, r.state].slice(-8);
    keepPassed();
  }
  const seenAt = (floor) => Number(stored(SEEN(), {})?.[floor.id]) || 0;
  const seenNow = (floor) => store(SEEN(), { ...(stored(SEEN(), {}) || {}), [floor.id]: Math.round(Date.now() / 1000) });
  const waitingOn = (floor) => env.waiting().filter((i) => i.project === floor.project);

  function greet(floor, who) {
    env.prime?.(floor);
    const v = env.view(floor);
    const at = v.conversations.filter((c) => c.working).length;
    const head = `${floor.label}: ${at ? `${at === 1 ? 'one agent' : `${at} agents`} at work` : 'nobody at work right now'}${v.waiting.length ? `, and ${v.waiting.length === 1 ? 'one thing waits' : `${v.waiting.length} things wait`} on you` : ''}.`;
    // what came of what you asked, first, without being asked (the rest the next time, or when you ask what's new)
    const news = reportingOn() ? untold(floor).slice(0, 3) : [];
    told(news);
    const first = news.length ? ` ${news.map(({ r }) => r.line).join(' ')}` : '';
    return `Hi. I'm ${who?.name ? `${who.name}, ` : ''}${floor.label}'s lead.${first} ${head} Ask me where we are or what's new, or tell me what you want done.`;
  }

  // The round: each lead with something to say, a line each in their own voice, those with something waiting on
  // you first; the quiet ones in one line at the end. Since the last round (within a day), or the last 12 hours.
  let roundAt = 0; // when the last round ended, so a lone floor name just after it puts you through
  function round(text, { loose = true } = {}) {
    if (!roundAsked(text, { loose })) return null;
    if (!leadsOn()) return 'The leads are switched off, so there is no round. Switch them on under Talking.';
    const all = floorsWith();
    if (!all.length) return 'There are no project floors with a lead, so there is no round.';
    const now = Date.now() / 1000;
    const last = Number(stored(ROUND(), 0)) || 0;
    const since = last && now - last < 86400 ? last : now - 12 * 3600;
    store(ROUND(), Math.round(now));
    const lines = all.map((floor) => {
      const news = reportingOn() ? untold(floor).slice(0, 2) : []; // two each; the rest when you talk to that lead
      const v = env.view(floor);
      const line = leadRoundLine({ ...v, label: floor.label, moments: env.moments(floor), since, now,
        reports: news.map(({ r }) => r.line), reported: news.map(({ p }) => p.key) });
      return { floor, news, line };
    });
    const needsYou = (x) => x.line.waits + x.news.filter(({ r }) => r.state.startsWith('needs')).length > 0;
    const said = lines.filter((x) => !x.line.quiet).sort((a, b) => needsYou(b) - needsYou(a) || b.news.length - a.news.length);
    const quiet = lines.filter((x) => x.line.quiet).map((x) => x.floor.label);
    const from = lowerFirst(sinceSaid(since, now));
    const and = (names) => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`);
    roundAt = Date.now();
    if (!said.length) return `Here's the round: all quiet. Nothing new on ${and(quiet)} ${from}, and nothing waits on you.`;
    return { turns: [
      { who: null, text: `Here's the round, ${from}.` },
      // each lead's news is marked as told once their line is heard (voice.js calls `heard`), so news you cut
      // in before is told again the next time
      ...said.map((x) => ({ who: whoOf(x.floor), text: `${x.floor.label}. ${x.line.text}`, heard: () => told(x.news) })),
      { who: null, text: `${quiet.length ? `Nothing new on ${and(quiet)}. ` : ''}${env.walking() ? 'Take the lift to a floor to talk to its lead.' : "Say a project's name to talk to its lead."}` },
    ] };
  }

  // What a lead tells you without being asked, while you are with them: what came of what you asked, once it is
  // done, stuck or needs you. With no floor, the front desk tells you each lead's, with whose it is.
  function speakUp(floor) {
    if (!leadsOn() || !reportingOn()) return null;
    if (floor) {
      const news = untold(floor).slice(0, 3);
      told(news);
      return news.length ? news.map(({ r }) => r.line).join(' ') : null;
    }
    // the front desk: up to three, what needs you first, whichever floor; the rest next time
    const all = floorsWith().flatMap((f) => untold(f).map((n) => ({ ...n, f })))
      .sort((a, b) => FIRST(a.r.state) - FIRST(b.r.state) || a.p.at - b.p.at).slice(0, 3);
    told(all);
    return all.length ? all.map(({ f, r }) => `News from ${f.label}'s lead. ${r.line}`).join(' ') : null;
  }

  // What a lead says. In order: answering a request out loud; what waits for your word from last time; going
  // somewhere; passing something on; stopping someone; an update, the news since you last asked, who is
  // working, what waits on you; starting someone new; then Claude with this floor's facts, if the page has it.
  function says(floor, text, { spoken = false } = {}) {
    const m = memOf(floor.id);
    const said = String(text || '').trim();
    const items = waitingOn(floor);
    const v = voiceAnswer(said, items.filter(env.canAnswer), m.voice, { spoken, on: answersOn(), label: env.label });
    if (v) {
      if (v.pending) waitFor(m, 'voice', v.pending);
      else m.voice = null;
      if (v.show) env.show(v.show);
      return v.act ? env.answer(v.act) : v.reply;
    }
    if (m.start) {
      const s = deskStart(env.control, said, m.start);
      if (s && s.reply != null) { m.start = s.pending; return s.reply; }
    }
    if (m.send) {
      if (yesSaid(said)) { const go = m.send; m.send = null; return sendOn(floor, go.text, go.to); }
      if (noSaid(said)) { m.send = null; return "All right, I won't send it."; }
    }
    if (m.which) {
      const picked = pickFrom(said, m.which.choices);
      if (picked) { const go = m.which; m.which = null; return passOn(floor, go.text, picked); }
      if (noSaid(said)) { m.which = null; return "All right, I won't pass it on."; }
    }
    if (m.stop) {
      if (yesSaid(said)) { const go = m.stop; m.stop = null; return halt(go); }
      if (noSaid(said)) { m.stop = null; return 'All right, they carry on.'; }
    }
    const went = go(said);
    if (went) return went;
    const asked = leadAsked(said);
    if (asked?.kind === 'pass') return passFor(floor, asked);
    const theRound = round(said, { loose: false }); // "how's everything?" to a lead is about their own floor
    if (theRound) return theRound;
    // just this floor's name ("Tidepool", "more on Tidepool"), as after the round: where it stands
    if (floorNamed(said, [{ ...floor, lead: leadOf(floor) }])) return leadUpdate(env.view(floor));
    const stopping = STOP_THEM.exec(said);
    if (stopping) return stopFor(floor, stopping[1]);
    if (asked?.kind === 'help') return leadHelp(floor.label);
    if (asked?.kind === 'news') return newsOf(floor);
    if (asked?.kind === 'who') return leadWho(floor.label, env.agents(floor));
    if (asked?.kind === 'update') return leadUpdate(env.view(floor));
    if (WAITING.test(said)) return sayWaiting(items, env.label);
    const handed = handedOut(said, on() ? env.control.projects() : []);
    if (handed && handed.job.trim().length > 2) {
      if (!on()) return env.madeUp() ? `This company is made up, so I can't start a real agent. With your own company connected, I'd start one on ${floor.label} with your words as its brief.` : env.notConnected();
      const s = handed.project ? deskStart(env.control, said, null) : deskStart(env.control, `start an agent on ${floor.label} to ${handed.job.trim()}`, null);
      if (s) { waitFor(m, 'start', s.pending); if (s.reply != null) return s.reply; }
    }
    const thought = env.think?.(floor, said);
    if (thought) return thought;
    return `I'm not sure what you mean. ${leadHelp(floor.label)}`;
  }

  function passFor(floor, asked) {
    if (!on()) {
      return env.madeUp() ? `This company is made up, so there's no real agent to tell. With your own agents connected, I'd pass that to the one working on ${floor.label}, and tell you how it answered.` : env.notConnected();
    }
    const t = passTarget(asked.text, env.agents(floor), asked.hint);
    if (t.to) return passOn(floor, asked.text, [t.to]);
    if (t.which) {
      waitFor(memOf(floor.id), 'which', { text: asked.text, choices: t.which });
      return `${t.which.length} agents are at work here: ${t.which.slice(0, 4).map((a, i) => `${ORDINAL[i] ? `the ${ORDINAL[i]}, ` : ''}on "${a.title}"`).join('; ')}. Which one, or all of them?`;
    }
    const s = deskStart(env.control, `start an agent on ${floor.label} to ${lowerFirst(asked.text).replace(/[.!]$/, '')}`, null);
    if (s?.pending) { waitFor(memOf(floor.id), 'start', s.pending); return `Nobody is working on ${floor.label} right now. ${s.reply}`; }
    return `Nobody is working on ${floor.label} right now. ${s?.reply || "And I can't start anyone here."}`;
  }

  // Instructions that can't be taken back (merge, publish, delete, pay and the like) are read back first.
  function passOn(floor, text, targets) {
    if (needsSaying(text)) {
      waitFor(memOf(floor.id), 'send', { text, to: targets });
      return `That can't be taken back once it's done, so first: I'll tell ${targetsSaid(targets)}, "${text}" Say "send it", or "cancel".`;
    }
    return sendOn(floor, text, targets);
  }

  function sendOn(floor, text, targets) {
    // only ever this floor's own agents, as they are now
    const here = new Set(env.agents(floor).map((a) => a.id));
    const to = targets.filter((a) => here.has(a.id));
    if (!to.length) return `That agent isn't on ${floor.label} any more, so I haven't passed it on.`;
    return Promise.all(to.map((a) => env.control.say(a.id, text).then((r) => ({ a, r })))).then((sent) => {
      const at = Date.now() / 1000;
      for (const { a } of sent) rememberPassed({ at, key: a.id, title: a.title, text, project: floor.project, working: !!a.working, told: [] });
      const when = sent.some(({ r }) => r?.sent === 'resumed') ? 'It is answering now.' : sent.some(({ a }) => a.working) ? 'It reads it at its next step.' : 'It reads it the next time it starts.';
      return `Passed on to ${targetsSaid(to)}: "${text}" ${when} Ask me what's new and I'll tell you how it answered.`;
    }, (error) => `I couldn't pass it on: ${error.message}`);
  }

  const halt = (go) => Promise.all(go.map((a) => env.control.halt(a.id))).then(() => `Stopping ${targetsSaid(go)}. ${go.length === 1 ? 'It stops' : 'They stop'} at the next step.`, (error) => error.message);

  function stopFor(floor, named) {
    if (!on()) return env.madeUp() ? 'This company is made up, so there is no real agent to stop.' : env.notConnected();
    const working = env.agents(floor).filter((a) => a.working);
    if (!working.length) return `Nobody is working on ${floor.label} right now.`;
    const one = /^the\s+(?:one|agent)/i.test(named) ? pickFrom(named, working) : null;
    const go = one || working;
    waitFor(memOf(floor.id), 'stop', go);
    return `Stop ${targetsSaid(go)}? Say "yes" to stop ${go.length === 1 ? 'it' : 'them'}, or "no".`;
  }

  function newsOf(floor) {
    const now = Date.now() / 1000;
    const seen = seenAt(floor);
    const since = seen && now - seen < 86400 ? seen : now - 12 * 3600;
    const given = [];
    const said = leadNews({
      label: floor.label, moments: env.moments(floor), since, now, passed: passedOn(floor),
      conversations: env.view(floor).conversations, waiting: waitingOn(floor), agents: env.agents(floor), from: lowerFirst(sinceSaid(since, now)),
      said: (p, r) => given.push({ p, r }),
    });
    seenNow(floor);
    // what it said is told now, so not again unasked; anything it left out is still told later
    told(given.filter(({ p, r }) => Array.isArray(p.told) && r.final && !p.told.includes(r.state)));
    return said;
  }

  // "Take me to ...", from anyone, except mid-walk, where the walk takes you.
  function go(text) {
    if (env.walking()) return null;
    const asked = goAsked(text, env.places());
    if (!asked) return null;
    if (asked.back) { env.back(); return 'Going back.'; }
    if (asked.unknown) return `I don't know a place called "${asked.unknown}". Say a floor's name, such as ${env.floors()[0]?.label || 'a project'}, or "Activity".`;
    env.go(asked.href);
    return `Here's ${asked.label}.`;
  }

  // A lead's card while you stand with them or talk to them: what waits for your word, or this floor's first
  // request, so a tap can answer it too.
  function controls(floor) {
    const m = memOf(floor.id);
    if (m.start?.project && on()) {
      return deskControls(m.start, () => {
        const s = deskStart(env.control, 'start it', m.start);
        m.start = s?.pending || null;
        return s?.reply;
      }, () => { m.start = null; return "All right, I won't start it."; });
    }
    if (m.send) {
      return { note: `For ${targetsSaid(m.send.to)}: ${m.send.text}`, buttons: [
        { label: 'Send it', run: () => { const g = m.send; m.send = null; return g ? sendOn(floor, g.text, g.to) : null; } },
        { label: 'Cancel', run: () => { m.send = null; return "All right, I won't send it."; } }] };
    }
    if (m.stop) {
      return { note: `Stop ${targetsSaid(m.stop)}?`, buttons: [
        { label: 'Stop', run: () => { const g = m.stop; m.stop = null; return g ? halt(g) : null; } },
        { label: 'Cancel', run: () => { m.stop = null; return 'All right, they carry on.'; } }] };
    }
    const ask = waitingOn(floor).find(env.canAnswer);
    if (!ask) return null;
    return { note: `"${ask.title}" wants your permission ${ask.what}. ${riskOf(ask)?.word || ''}`.trim(), buttons: [
      { label: 'Allow', run: () => env.answer({ id: ask.ask.id, behavior: 'allow', item: ask }) },
      { label: 'Deny', run: () => env.answer({ id: ask.ask.id, behavior: 'deny', item: ask }) }] };
  }

  // Someone a question is meant for, for the Talk panel: back to the desk, or a floor's lead by name or floor.
  function through(who, text, desk) {
    const said = String(text || '').trim();
    if (desk && who?.href !== desk.href && BACK_TO_DESK.test(said)) return { who: desk, then: null };
    if (!leadsOn()) return null;
    const named = floorsWith().map((f) => ({ id: f.id, label: f.label, project: f.project, lead: leadOf(f) }));
    // "more on Tidepool", any time; a lone "Tidepool" only just after the round, so it never takes the answer to
    // another question ("which floor?")
    const more = floorNamed(said, named, { bare: Date.now() - roundAt < 2 * 60_000 });
    const to = more ? { floor: more, then: said } : throughAsked(said, named);
    const floor = to && env.floors().find((f) => f.id === to.floor.id);
    return floor ? { who: whoOf(floor), then: to.then } : null;
  }

  return {
    floors: floorsWith,
    who: whoOf,
    floorOf,
    lead(floorId) {
      if (!leadsOn()) return null;
      const floor = env.floors().find((f) => f.id === floorId);
      return floor && hasLead(floor) ? whoOf(floor) : null;
    },
    greet,
    says,
    controls,
    update: (floor) => leadUpdate(env.view(floor)),
    passed: passedOn,
    through,
    go,
    round,
    speakUp,
    // An instruction the brain passed on (connect/brain.py), so its lead reports back on it too: a lead's only to
    // its own floor's agents; the assistant's (floor null) to whichever floor's agent it went to.
    remember(floor, sent) {
      if (!sent?.key || !sent.text) return;
      for (const f of floor ? [floor] : floorsWith()) {
        const a = env.agents(f).find((x) => x.id === sent.key);
        if (!a) continue;
        rememberPassed({ at: Date.now() / 1000, key: a.id, title: a.title, text: String(sent.text).slice(0, 300), project: f.project, working: !!a.working, told: [] });
        return;
      }
    },
  };
}
