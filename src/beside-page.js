// Working beside your agents, on the page (docs/connect.md, "Work beside your agents"). Each agent's live screen: what
// it is doing now and for how long, its to-do list ticking off, its last steps and the lines it has changed, red and
// green. A reply straight away when you say something to it, with your message marked queued, then read, then
// answered. Its questions, with their choices as buttons. Walk me through it, a note on one changed line, and Looks
// good. Hold on and carry on. Each part follows its switch (connect/switches.py), and the page shows nothing of a part
// that is off.
//
// Where the screens come from: on this computer, data/live/ (connect/live.py writes it), read every two seconds while
// the page is in view; on a paired phone that may control agents, only through /control/ (state every five seconds,
// one screen every twenty); on this computer from a page with its own server that keeps the data elsewhere, also
// through /control/, a screen every two seconds; anywhere else (--lan, a view-only link) nowhere, quietly. The made-up company has a made-up
// agent at work (sample/live.json), and says so.
//
// createBeside(env) takes:
//   control       control.js's
//   where()       'here' (this computer), 'control' (this computer, through control only), 'phone' (a paired
//                 phone allowed to control agents), 'sample' or 'none'
//   part(name)    whether a part's switch is on
//   convo(key)    the conversation as the page knows it ({ id, title, project, agent, working, review, says })
//   label(p)      a floor's name; check(p) its check's name or null; reviewer(p) whether it has a review line
//   href(key)     a conversation's page
//   done(promise, said)  what the page does with an answer from a button: show `said(result)`, or the error
//   changed()     the screens changed: draw the page again
//   talkTo(key)   open Talk with that agent
//   sampleUrl     where the made-up screens are

import { icon } from './icons.js';
import { ALLOW, DENY, STOP } from './control.js';
import {
  besideAsked, changeTotals, clip, filesOf, forWords, goodSaid, holdEndedSaid, holdEndedWords, holdWords, hunkKind, messageIn,
  messageStatus, monitorLine, nowOf, optionPicked, plainReply, pointAsked, pointSaid, questionSaid, questionWait, replyFlow,
  resolvePoint, signWord, stateMood, stateWord, stepLine, target, todoOf, totalsWords, whenWords,
} from './beside.js';

const CSS = new URL('./beside.css', import.meta.url).href;
const FILE_KEY = /^cc-[A-Za-z0-9]{1,12}$/; // the only keys a file is ever asked for
const EVERY = 2000;
const PHONE_SCREEN = 20000; // with state every five seconds, 15 of a phone's 20 requests a minute: room to act
const WANTED_FOR = 6000; // a screen is read while something showed it in the last few seconds
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
const nowS = () => Date.now() / 1000;

function styled() {
  if (document.querySelector('link[data-arnheim-beside]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS;
  link.dataset.arnheimBeside = '';
  document.head.append(link);
}

function h(tag, props, ...kids) {
  const [name, ...classes] = tag.split('.');
  const el = document.createElement(name || 'div');
  if (classes.length) el.className = classes.join(' ');
  const isProps = props && typeof props === 'object' && !(props instanceof Node) && !Array.isArray(props);
  if (!isProps) kids.unshift(props);
  for (const [key, v] of Object.entries(isProps ? props : {})) {
    if (v == null || v === false) continue;
    if (key.startsWith('on')) el.addEventListener(key.slice(2), v);
    else el.setAttribute(key, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}
const btn = (label, onclick, cls = '', glyph = null, more = {}) => h(`button.btn${cls}`, { type: 'button', onclick, ...more }, glyph && icon(glyph, 15), label);

export function createBeside(env) {
  styled();
  const control = env.control;
  const part = (name) => { try { return env.part(name) !== false; } catch { return true; } };
  let lines = {}; // each conversation's line (data/live/index.json's conversations)
  const docs = new Map(); // key -> its screen (data/live/<key>.json), or null
  const read = new Map(); // key -> when its screen was last read (ms)
  const wanted = new Map(); // key -> when something last showed it (ms)
  const mine = new Map(); // id -> { key, text, reply, when, sent, at, via }: what was sent from this page
  const told = new Set(); // what has been said out loud already: "<id>:taken", "<id>:answered", "q:<id>", ...
  const aims = new Map(); // key -> the line pointed at, waiting for what you want done with it
  const walks = new Map(); // key -> { id, at }: a walk-through asked for from here
  const gits = new Map(); // key -> what /control/changes said, or { loading } or { error }
  const holdAsked = new Set(); // keys held from here, to say once it is holding
  let indexMissing = 0; // after a 404, the index is asked for less often
  let nextIndex = 0;
  let timer = 0;
  let running = false;
  let sig = '';
  let sample = null; // the made-up screens: { screens: { key: doc } }
  const sampleHolds = new Map();

  /* ---------- reading the screens ---------- */

  const where = () => { try { return env.where(); } catch { return 'none'; } };
  const want = (key) => { if (key) wanted.set(key, Date.now()); };

  async function getJson(url) {
    try {
      const r = await fetch(url, { cache: 'no-store', credentials: 'same-origin' });
      if (r.status === 404) return 404;
      if (!r.ok) return null; // 403 over --lan or a view-only link: nothing, quietly
      return await r.json();
    } catch {
      return null;
    }
  }

  async function loadSample() {
    const url = typeof env.sampleUrl === 'function' ? env.sampleUrl() : env.sampleUrl;
    if (sample || !url) return;
    const got = await getJson(url);
    const opened = nowS();
    const shift = (doc) => JSON.parse(JSON.stringify(doc || {}), (k, v) => ((k === 'at' || k === 'started_at' || k === 'taken_at' || k === 'answered_at') && typeof v === 'number' && v <= 0 ? opened + v : v));
    sample = { screens: Object.fromEntries(Object.entries(got?.screens || {}).map(([k, d]) => [k, { ...shift(d), sample: true }])), walk: got?.walk || {}, cycle: got?.cycle || {} };
  }

  // The made-up agent's step, on a loop, so it is always doing something.
  function sampleScreen(key) {
    const base = sample?.screens?.[key];
    if (!base) return null;
    const c = env.convo(key);
    const doc = { ...base, hold: sampleHolds.get(key) || null };
    const cycle = sample.cycle?.[key];
    if (!c?.working) return { ...doc, state: 'finished', now: null };
    if (doc.hold?.state === 'held') return { ...doc, state: 'held', now: { kind: 'held', words: 'Holding, as you asked', started_at: doc.hold.since } };
    if (Array.isArray(cycle) && cycle.length) {
      const total = cycle.reduce((s, x) => s + (Number(x.lasts) || 20), 0);
      let t = (nowS() - (sample.opened ||= nowS())) % total;
      for (const step of cycle) {
        const lasts = Number(step.lasts) || 20;
        if (t < lasts) return { ...doc, now: { kind: step.kind, words: step.words, started_at: nowS() - t } };
        t -= lasts;
      }
    }
    return doc;
  }

  async function poll() {
    clearTimeout(timer);
    if (!running) return;
    if (!document.hidden) {
      const how = where();
      const t = Date.now();
      for (const el of document.querySelectorAll('[data-bs-key]')) want(el.dataset.bsKey); // a screen in view stays read
      const keys = [...wanted].filter(([, at]) => t - at < WANTED_FOR).map(([k]) => k);
      if (how === 'here') {
        if (t >= nextIndex) {
          const got = await getJson('data/live/index.json');
          if (got === 404 || !got) { lines = {}; indexMissing += 1; nextIndex = t + (indexMissing > 1 ? 10000 : EVERY); }
          else { lines = got.conversations && typeof got.conversations === 'object' ? got.conversations : {}; indexMissing = 0; nextIndex = t + EVERY; }
        }
        for (const key of keys.filter((k) => FILE_KEY.test(k)).slice(0, 4)) {
          const got = await getJson(`data/live/${key}.json`);
          docs.set(key, got && got !== 404 ? got : null);
          read.set(key, t);
        }
      } else if (how === 'phone' || how === 'control') {
        lines = control.on ? control.lines() : {};
        const near = how === 'control';
        const most = keys.sort((a, b) => wanted.get(b) - wanted.get(a)).slice(0, near ? 4 : 1);
        for (const key of most) {
          if (!control.on || t - (read.get(key) || 0) < (near ? EVERY : PHONE_SCREEN)) continue;
          read.set(key, t);
          try { docs.set(key, (await control.live(key)).live || null); } catch { /* 403 or 429: next time */ }
        }
      } else if (how === 'sample') {
        await loadSample();
        lines = Object.fromEntries(Object.keys(sample?.screens || {}).map((k) => [k, sampleScreen(k)]).filter(([, d]) => d));
        for (const k of Object.keys(lines)) docs.set(k, lines[k]);
      } else {
        lines = {};
        docs.clear();
      }
      const next = JSON.stringify([Object.entries(lines).map(([k, r]) => [k, r?.at, r?.state, r?.hold?.state]), [...docs].map(([k, d]) => [k, d?.at, d?.n, d?.state])]);
      if (next !== sig) {
        sig = next;
        drawMinis();
        try { env.changed(); } catch (error) { console.warn('Arnheim: a screen redraw failed.', error); }
      }
    }
    if (running) timer = setTimeout(poll, EVERY);
  }

  const lineOf = (key) => (part('live') || part('replies') ? lines[key] || null : null);
  const screenOf = (key) => { want(key); return docs.get(key) || null; };
  const questionsOf = (key) => (part('questions') && control?.on && where() !== 'sample' ? control.questions(key) : []);
  const holdOf = (key) => {
    if (where() === 'sample') return sampleHolds.get(key) || null;
    const h0 = control?.on ? control.holdOf(key) : null;
    return h0 || docs.get(key)?.hold || lines[key]?.hold || null;
  };
  // Whether what you say or press here reaches the agent: with control on (this computer, or a phone it lets
  // control agents), to a conversation control can reach; or the made-up agent, where nothing real happens.
  const reachable = (key) => {
    const how = where();
    if (how === 'sample') return !!sample?.screens?.[key];
    if (how === 'none' || !control?.on) return false;
    return FILE_KEY.test(key) || !!control.run(key);
  };
  const isSample = () => where() === 'sample';
  const working = (key) => {
    const c = env.convo(key);
    const st = (docs.get(key) || lines[key])?.state;
    return !!c?.working || control?.run?.(key)?.state === 'working' || ['working', 'waiting', 'asking', 'held'].includes(st);
  };
  const hasScreen = (key) => !!(docs.get(key) || lines[key]);
  const changesOf = (key) => (part('live') ? (docs.get(key)?.changes || []) : []);

  /* ---------- doing things: each gives what the agent says back ---------- */

  const MADE_UP = 'This company is made up, so no real agent is at work.';
  function remember(key, sent, text, via = 'message') {
    if (sent?.id) mine.set(sent.id, { key, text, reply: sent.reply || null, when: sent.when || null, sent: sent.sent, at: nowS(), via });
    return sent;
  }
  // The answer to a message seen another way: an agent started here says it in its run, any other in its feed.
  const answeredElse = (key, id) => () => {
    const run = control?.run?.(key);
    if (run?.answered === id) return run.said || "I've done that.";
    const c = env.convo(key);
    return c?.answered === id ? c.says?.now || "I've done that." : null;
  };
  function follow(key, sent) {
    const c = env.convo(key);
    const given = sent.reply ? sent : { ...sent, reply: plainReply(sent, working(key), c?.agent || 'Claude Code'), when: sent.sent === 'resumed' || working(key) ? sent.when : 'next_turn' };
    return replyFlow({
      sent: given, sleep: pause, answered: answeredElse(key, sent.id),
      find: (id) => messageIn(screenOf(key), id),
      taken: (id, what) => told.add(`${id}:${what}`),
    });
  }
  const failed = (error) => error?.message || 'That did not reach it.';

  // Anything you say to it: its reply straight away, then that it has it, then its answer.
  function relay(key, text) {
    if (isSample()) return `Got it. ${MADE_UP} With your own agents, this reaches the one doing the work.`;
    return (async function* reply() {
      let sent;
      try { sent = remember(key, await control.say(key, text), text); } catch (error) { yield failed(error); return; }
      env.changed();
      yield* follow(key, sent);
    })();
  }

  function hold(key) {
    if (isSample()) {
      sampleHolds.set(key, { state: 'held', since: nowS(), until: nowS() + 600 });
      poll();
      return `Okay, I'm holding. ${MADE_UP}`;
    }
    holdAsked.add(key);
    return control.hold(key).then((r) => { env.changed(); return r.reply || 'Okay, I\'ll hold at my next step.'; }, failed);
  }
  function goOn(key) {
    if (isSample()) {
      sampleHolds.delete(key);
      poll();
      return 'Okay, carrying on.';
    }
    return control.goOn(key).then((r) => { env.changed(); return r.reply || 'Okay, carrying on.'; }, failed);
  }
  function walk(key) {
    if (isSample()) {
      walks.set(key, { id: null, at: nowS(), sample: true });
      env.changed();
      const said = sample?.walk?.[key];
      return said ? `${said} ${MADE_UP}` : `I'd walk you through my changes here. ${MADE_UP}`;
    }
    return (async function* explain() {
      let sent;
      try { sent = remember(key, await control.walkThrough(key), 'Walk me through your changes.', 'walk'); } catch (error) { yield failed(error); return; }
      walks.set(key, { id: sent.id, at: nowS() });
      loadGit(key);
      env.changed();
      yield* follow(key, sent);
    })();
  }
  function good(key) {
    const c = env.convo(key);
    const reviewer = !!env.reviewer?.(c?.project);
    if (isSample()) return `Thanks. With your own agents, this runs the floor's check on my work. ${MADE_UP}`;
    const review = env.reviewSaid?.(c) || null;
    return control.prove(key).then((r) => goodSaid({ check: r.check, review, reviewer }),
      (error) => (/no check/i.test(error.message) ? goodSaid({ check: null, review, reviewer }) : failed(error)));
  }
  function comment(key, t, words) {
    if (isSample()) return `Got it, about ${t.file}${t.line ? `, line ${t.line}` : ''}. ${MADE_UP}`;
    const body = { key, file: t.file, line: t.line ?? null, text: t.text, words };
    if (t.side === 'old') body.side = 'old';
    return (async function* noted() {
      let sent;
      try { sent = remember(key, await control.comment(body), words, 'comment'); } catch (error) { yield failed(error); return; }
      aims.delete(key);
      env.changed();
      yield* follow(key, sent);
    })();
  }
  function answer(q, given) {
    told.add(`q:${q.id}`);
    return (async function* answered() {
      let r;
      try { r = await control.replyQuestion(q.id, given); } catch (error) { yield failed(error); return; }
      env.changed();
      if (r.sent === 'now') { yield r.reply || "Thanks, that's what I needed. I'm carrying on with it now."; return; }
      remember(q.key, r, given.text || Object.values(given.answers || {}).flat().join(', '), 'answer');
      yield* follow(q.key, r);
    })();
  }
  // A generator's words, joined, for a button that shows one note.
  async function whole(out) {
    const got = await out;
    if (got == null || typeof got === 'string') return got;
    if (typeof got[Symbol.asyncIterator] !== 'function') return String(got);
    for await (const piece of got) return String(piece).trim(); // the reply straight away; the rest shows on the screen
    return null;
  }

  // What you said to an agent, if it is for this: holding, carrying on, walking through, looks good, pointing at a
  // change or a line, what you want done with one you pointed at, or the answer to its question. Null for anything
  // else, which goes to it as a message (relay).
  function heard(key, text, { permission = false } = {}) {
    const words = String(text || '').trim();
    if (!words || !reachable(key)) return null;
    const act = besideAsked(words);
    if (STOP.test(words) && !(act === 'hold' && part('hold'))) return null; // "stop" still stops it; "stop there" holds
    if (permission && (ALLOW.test(words) || DENY.test(words))) return null;
    const held = holdOf(key);
    if (act === 'hold' && part('hold')) return working(key) || isSample() ? hold(key) : "I'm not working on anything right now, so there's nothing to hold.";
    if (act === 'carry' && part('hold') && held && ['asked', 'held'].includes(held.state)) return goOn(key);
    // A question it waits on comes first: "looks good" or "ship it" then answers it, rather than running the check.
    const q = questionsOf(key)[0];
    if (q) return answer(q, optionPicked(words, q) || { text: words });
    // "No changes" only from a screen it has seen; otherwise the agent itself is asked.
    const seen = part('live') && hasScreen(key);
    if (act === 'walk' && part('review_together')) return changesOf(key).length || isSample() || !seen ? walk(key) : "I haven't changed any lines yet, so there's nothing to walk through.";
    if (act === 'good' && part('review_together')) return good(key);
    if (part('review_together') && part('live')) {
      const point = seen ? pointAsked(words) : null;
      if (point) {
        const t = resolvePoint(point, changesOf(key));
        if (!t) {
          const n = changesOf(key).length;
          if (point.change != null) return n ? `I've made ${n === 1 ? 'one change' : `${n} changes`} so far, so there's no change ${point.change}.` : "I haven't changed anything yet.";
          return `I haven't changed line ${point.line}${point.file ? ` in ${point.file}` : ''}.`;
        }
        if (point.rest) return comment(key, t, point.rest);
        aims.set(key, { ...t, at: Date.now() });
        env.changed();
        return pointSaid(t);
      }
      const aim = aims.get(key);
      if (aim && Date.now() - aim.at < 5 * 60000) return comment(key, aim, words);
    }
    return null;
  }

  // What an agent you are with says unasked, once each: a question it has for you, that it has your note, its answer
  // to something you sent from here, that it is holding, or why its hold ended.
  function speakUp(key) {
    const q = questionsOf(key).find((x) => !told.has(`q:${x.id}`));
    if (q) { told.add(`q:${q.id}`); return questionSaid(q); }
    const doc = docs.get(key);
    for (const [id, m] of mine) {
      if (m.key !== key) continue;
      const got = messageIn(doc, id);
      if (got?.state === 'taken' && !told.has(`${id}:taken`) && m.sent !== 'resumed') { told.add(`${id}:taken`); return got.taken_words || null; }
      if (got?.state === 'answered' && !told.has(`${id}:answered`)) { told.add(`${id}:taken`); told.add(`${id}:answered`); if (got.answer) return got.answer; }
    }
    const held = holdOf(key);
    if (held?.state === 'held' && holdAsked.has(key) && !told.has(`held:${key}:${held.since}`)) {
      told.add(`held:${key}:${held.since}`);
      return "I'm holding now, keeping what I've done. What would you like?";
    }
    const ended = doc?.hold_ended;
    if (ended?.at && nowS() - ended.at < 60 && !told.has(`ended:${key}:${ended.at}`)) {
      told.add(`ended:${key}:${ended.at}`);
      return holdEndedSaid(ended);
    }
    return null;
  }

  // The buttons on its card on a walk and in Talk: answer its question, hold or carry on, walk through, looks good.
  function buttons(key) {
    if (!reachable(key)) return [];
    const out = [];
    const held = holdOf(key);
    if (part('hold')) {
      if (held && ['asked', 'held'].includes(held.state)) out.push({ label: 'Carry on', run: () => goOn(key) });
      else if (working(key)) out.push({ label: 'Hold on', run: () => hold(key) });
    }
    if (part('review_together') && (changesOf(key).length || (isSample() && sample?.walk?.[key]))) {
      out.push({ label: 'Walk me through it', run: () => whole(walk(key)) });
      out.push({ label: 'Looks good', run: () => good(key) });
    }
    return out;
  }
  // Its question's choices as buttons, while it asks: { note, buttons } or null.
  function questionButtons(key) {
    const q = questionsOf(key)[0];
    if (!q) return null;
    const list = Array.isArray(q.questions) ? q.questions : [];
    const one = q.kind === 'choices' && list.length === 1 && !list[0].multiSelect ? list[0] : null;
    return {
      note: `It asks: ${clip(q.text || list[0]?.question || 'a question', 140)}`,
      buttons: one ? (one.options || []).filter((o) => o?.label).slice(0, 8).map((o) => ({ label: o.label, run: () => whole(answer(q, { answers: { [one.question]: o.label } })) })) : [],
    };
  }

  /* ---------- Changes so far: everything not yet committed in the floor's folder ---------- */

  function loadGit(key) {
    if (!control?.on || isSample() || !part('live')) return;
    gits.set(key, { loading: true });
    env.changed();
    control.changes(key).then((r) => { gits.set(key, r); env.changed(); }, (error) => { gits.set(key, { error: failed(error) }); env.changed(); });
  }

  /* ---------- drawing ---------- */

  const since = (at) => h('span.bs-since', { 'data-bs-since': at }, forWords(nowS() - at));
  const holdLine = (held) => {
    const w = holdWords(held);
    if (!w) return null;
    return h('p.bs-hold', { role: 'status' }, h('b', `${w.word}. `), h('span', w.state === 'held' && held.until ? { 'data-bs-hold': held.until } : {}, w.line));
  };
  const endedLine = (doc) => {
    const said = holdEndedWords(doc?.hold_ended);
    return said ? h('p.small.muted.bs-ended', said) : null;
  };
  function nowBlock(key, doc, { small = false } = {}) {
    const doing = nowOf(doc);
    const st = doc?.state || 'working';
    const mood = stateMood(st);
    return h(small ? 'p.bs-now.small' : 'p.bs-now',
      h(`span.bs-dot.k-${mood}`, { 'aria-hidden': 'true' }),
      h('span.bs-now-words', h('b', doing ? doing.words : stateWord(st)), doing?.since != null ? h('span.bs-for.muted', since(nowS() - doing.since), ' so far') : null));
  }
  function todoBlock(doc, most = 12) {
    const t = todoOf(doc);
    if (!t.all) return null;
    const mark = { done: 'check', working: 'zap' };
    return h('div.bs-todo',
      h('h4', `Its to-do list: ${t.done} of ${t.all} done`),
      h('ol', t.rows.slice(0, most).map((r) => h(`li.bs-t-${r.state || 'open'}`,
        mark[r.state] ? icon(mark[r.state], 14) : h('span.bs-box', { 'aria-hidden': 'true' }),
        h('span.offscreen', r.state === 'done' ? 'Done: ' : r.state === 'working' ? 'Working on it: ' : 'To do: '),
        h('span', r.title)))),
      t.rows.length > most ? h('p.small.muted', `And ${t.rows.length - most} more.`) : null);
  }
  function stepsBlock(doc, most = 6) {
    const steps = Array.isArray(doc?.steps) ? doc.steps.slice(-most).reverse() : [];
    if (!steps.length) return null;
    return h('div.bs-steps',
      h('h4', 'What it did last'),
      h('ol', steps.map((s) => h(`li${s.failed ? '.bs-failed' : ''}`, h(`span.bs-k.k-${s.kind || 'other'}`, { 'aria-hidden': 'true' }), h('span', stepLine(s)),
        s.at ? h('span.muted.small', ` ${forWords(nowS() - s.at)} ago`) : null))));
  }
  // What you said to it from here and where it is: waiting for it to read, read, answered.
  function messagesBlock(key, doc, most = 4) {
    if (!part('replies')) return null;
    const list = (Array.isArray(doc?.messages) ? doc.messages : []).filter((m) => m && m.id);
    const seen = new Set(list.map((m) => m.id));
    for (const [id, m] of mine) if (m.key === key && !seen.has(id)) list.push({ id, text: m.text, at: m.at, state: 'queued', reply: m.reply, via: m.via, when: m.when });
    const shown = list.slice(-most);
    if (!shown.length) return null;
    return h('div.bs-said',
      h('h4', 'What you said to it'),
      h('ol', shown.map((m) => {
        const st = messageStatus(m);
        const own = mine.get(m.id);
        return h(`li.bs-m-${st.state}`,
          h('p.bs-you', h('span.muted', m.via === 'walk' ? 'You asked: ' : m.via === 'comment' ? 'Your note: ' : m.via === 'answer' ? 'Your answer: ' : 'You: '), m.via === 'walk' ? 'Walk me through it' : m.text || ''),
          h('p.bs-status', h(`span.pill.k-${st.state === 'answered' ? 'ok' : st.state === 'taken' ? 'working' : 'quiet'}`, st.word),
            st.state === 'queued' && own?.when ? h('span.small.muted', ` ${whenWords(own.when)}`) : null),
          st.line ? h('p.bs-it', h('span.muted', 'It: '), st.line) : null);
      })));
  }

  // One change, numbered on the page, its lines red and green with their numbers. With Review together on and the
  // agent in reach, each changed line is a button: tap it, then say what you want, and it goes to the agent tied
  // to that line.
  function hunkBlock(key, file, row, { tappable = false, gitStyle = false } = {}) {
    const { n, hunk, lines: rows } = row;
    const kind = hunkKind(hunk);
    const aim = aims.get(key);
    const label = `${gitStyle ? 'A change' : `Change ${n}`} in ${file}: ${hunk.added || 0} put in, ${hunk.removed || 0} taken out${kind ? `. ${kind}` : ''}`;
    const items = rows.map((l, i) => {
      const num = l.sign === '-' ? l.old : l.new;
      const words = `${l.sign === ' ' ? '' : `${signWord(l.sign)}: `}${l.text}`;
      const gutter = h('span.bs-ln', { 'aria-hidden': 'true' }, num != null ? String(num) : '');
      const sign = h('span.bs-sign', { 'aria-hidden': 'true' }, l.sign === ' ' ? '' : l.sign === '+' ? '+' : '−');
      const text = h('span.bs-code', l.text || ' ');
      const cls = l.sign === '+' ? 'bs-add' : l.sign === '-' ? 'bs-del' : 'bs-ctx';
      const t = target(hunk, l);
      const aimed = aim && aim.file === t.file && aim.line === t.line && aim.side === t.side && aim.text === t.text;
      const id = `bs-${key}-${String(hunk.step || '')}-${n}-${i}`.replace(/[^\w-]/g, '_');
      const read = `${num != null ? `Line ${num}, ` : ''}${words}`;
      const lineEl = tappable && l.sign !== ' '
        ? h(`button.bs-line.${cls}${aimed ? '.bs-aimed' : ''}`, { type: 'button', id, 'aria-label': `${read}. Tap to say what you want here`, 'aria-pressed': aimed ? 'true' : 'false',
          onclick: () => { aims.set(key, { ...t, n, at: Date.now() }); env.changed(); setTimeout(() => document.getElementById(`${id}-say`)?.focus(), 0); } }, gutter, sign, text)
        : h(`div.bs-line.${cls}`, h('span.offscreen', read), h('span.bs-contents', { 'aria-hidden': 'true' }, gutter, sign, text));
      return h('li', lineEl, aimed && tappable ? commentForm(key, aim, `${id}-say`) : null);
    });
    return h('div.bs-hunk',
      h('p.bs-hunk-head', h('b', gitStyle ? file : `Change ${n}`), kind ? h('span.muted', ` ${kind}`) : null,
        h('span.bs-count', h('span.bs-plus', `+${hunk.added || 0}`), ' ', h('span.bs-minus', `−${hunk.removed || 0}`))),
      rows.length ? h('ol.bs-lines', { 'aria-label': label }, items) : h('p.small.muted', hunk.kind === 'delete' ? 'The file was deleted.' : 'No lines to show.'),
      hunk.cut ? h('p.small.muted', 'Cut short: the change is longer than this.') : null,
      hunk.more ? h('p.small.muted', `And ${hunk.more} more changes in this step.`) : null);
  }
  function commentForm(key, aim, id) {
    const send = (event) => {
      event.preventDefault();
      const input = event.currentTarget.elements.words;
      const words = input.value.trim();
      if (!words) return;
      input.value = '';
      input.blur();
      env.done(whole(comment(key, aim, words)), (said) => said || 'Sent.');
    };
    return h('form.bs-comment', { onsubmit: send },
      h('label.offscreen', { for: id }, `What should change at ${aim.file}${aim.line ? `, line ${aim.line}` : ''}`),
      h('input', { id, name: 'words', type: 'text', maxlength: 2000, autocomplete: 'off', placeholder: 'What would you like here?' }),
      h('button.btn', { type: 'submit' }, 'Send'),
      h('button.btn.quiet', { type: 'button', onclick: () => { aims.delete(key); env.changed(); } }, 'Cancel'));
  }
  function changesBlock(key, doc, { tappable }) {
    const files = filesOf(doc?.changes);
    if (!files.length) return null;
    const totals = changeTotals(doc.changes);
    return h('div.bs-changes',
      h('h4', 'Changes'),
      h('p.small.muted', `${totalsWords(totals)} ${tappable ? 'Tap a line, or say "the second change" or "line 42", then say what you want.' : ''}`.trim()),
      files.map((f) => h('section.bs-file', { 'aria-label': `${f.file}: ${f.added} put in, ${f.removed} taken out` },
        h('p.bs-file-head', icon('box', 14), h('b', f.file), h('span.bs-count', h('span.bs-plus', `+${f.added}`), ' ', h('span.bs-minus', `−${f.removed}`))),
        f.hunks.map((row) => hunkBlock(key, f.file, row, { tappable })))));
  }
  function gitBlock(key) {
    const g = gits.get(key);
    if (!g) return null;
    if (g.loading) return h('p.small.muted', { role: 'status' }, 'Looking at everything not yet committed here.');
    if (g.error) return h('p.small.note', { role: 'status' }, g.error);
    return (g.git || []).map((one) => h('div.bs-git',
      h('h4', one.label || 'Everything not yet committed here'),
      one.note ? h('p.small.muted', one.note) : null,
      one.cut ? h('p.small.note', 'Too big to show it all.') : null,
      (one.files || []).map((f) => h('section.bs-file', { 'aria-label': `${f.file}: ${f.added} put in, ${f.removed} taken out` },
        (f.hunks || []).map((hk, i) => hunkBlock(key, f.file, { n: i + 1, hunk: { ...hk, file: f.file }, lines: numberedOf({ ...hk, file: f.file }) }, { gitStyle: true })))),
      one.untracked?.length ? h('p.small', h('b', 'New files git does not track yet: '), one.untracked.join(', '), one.untracked_more ? `, and ${one.untracked_more} more` : '') : null,
      !one.files?.length && !one.untracked?.length && !one.note ? h('p.small.muted', 'Nothing here that is not committed.') : null));
  }
  const numberedOf = (hk) => filesOf([hk])[0]?.hunks[0]?.lines || [];
  // The walk-through asked for here: where it stands, and what it said.
  function walkBlock(key, doc) {
    const w = walks.get(key);
    if (!w || !part('review_together')) return null;
    if (w.sample) return h('div.bs-walk', h('h4', 'It walks you through it'), h('p', sample?.walk?.[key] || ''), h('p.small.muted', MADE_UP));
    const m = messageIn(doc, w.id);
    const st = m ? messageStatus(m) : { state: 'queued', word: 'Waiting for it to read this', line: '' };
    return h('div.bs-walk', { role: 'status' },
      h('h4', 'It walks you through it'),
      st.state === 'answered' ? h('p', st.line) : h('p.muted', st.state === 'taken' ? `${st.line} Its explanation shows here when it has one.` : 'Asked. It explains its changes file by file at its next step, and its words show here.'));
  }

  // The whole screen, on its conversation's page.
  function page(c) {
    const key = c.id;
    want(key);
    const doc = screenOf(key);
    const held = part('hold') ? holdOf(key) : null;
    const ours = [...mine.values()].some((m) => m.key === key);
    if (!doc && !lineOf(key) && !held && !ours) return null; // nothing seen of it yet: nothing to show
    const live = part('live');
    const can = reachable(key);
    const tappable = can && part('review_together') && live;
    const hasChanges = live && (doc?.changes?.length || 0) > 0;
    const doBtns = [];
    if (can && part('hold')) {
      if (held && ['asked', 'held'].includes(held.state)) doBtns.push(btn('Carry on', () => env.done(Promise.resolve(goOn(key)), (s) => s), '.primary'));
      else if (working(key)) doBtns.push(btn('Hold on', () => env.done(Promise.resolve(hold(key)), (s) => s), '', 'pause'));
    }
    if (can && part('review_together') && (hasChanges || isSample())) {
      doBtns.push(btn('Walk me through it', () => (env.walkAloud?.(key) ? null : env.done(whole(walk(key)), (s) => s || 'Asked.')), '', 'messages-square'));
      doBtns.push(btn('Looks good', () => env.done(Promise.resolve(good(key)), (s) => s), '', 'check'));
    }
    if (can && live && control?.on && !isSample() && !gits.has(key)) doBtns.push(btn('Everything not yet committed here', () => loadGit(key), '.quiet', 'git-pull-request'));
    return h('section.panel-card.bs-page', { 'aria-label': 'Over its shoulder', 'data-bs-key': key },
      h('div.sect-head', icon('monitor', 18), h('h3.sect-title', 'Over its shoulder')),
      isSample() ? h('p.small.muted', `Made up, like the rest of this company: no real agent is at work, and nothing you do here reaches one.`) : null,
      live && doc ? h('div.bs-grid',
        h('div.bs-main',
          nowBlock(key, doc),
          held ? holdLine(held) : endedLine(doc),
          todoBlock(doc)),
        stepsBlock(doc)) : null,
      !live || !doc ? (held ? holdLine(held) : null) : null,
      doBtns.length ? h('div.control-row.bs-do', doBtns) : null,
      walkBlock(key, doc),
      messagesBlock(key, doc),
      live ? changesBlock(key, doc, { tappable }) : null,
      live ? gitBlock(key) : null);
  }

  // The small screen on its card, on a walk and in Talk: kept up to date in place.
  const minis = new Map(); // key -> { el, sig }
  function drawMini(key, m) {
    const doc = docs.get(key) || lines[key] || null;
    const live = part('live');
    const held = part('hold') ? holdOf(key) : null;
    const q = questionsOf(key)[0] || null;
    const last = part('replies') ? [...mine.entries()].filter(([, x]) => x.key === key).pop() : null;
    const lastMsg = last ? messageIn(docs.get(key), last[0]) || { state: 'queued', reply: last[1].reply } : null;
    const changes = live ? docs.get(key)?.changes || [] : [];
    const glimpse = changes.length ? changes[changes.length - 1] : null;
    const walking = walks.get(key);
    const next = JSON.stringify([doc?.at, doc?.state, doc?.now?.words, doc?.now?.started_at, held, q?.id, q?.state, lastMsg?.state, lastMsg?.answer, changes.length, glimpse?.at, walking?.id, live, part('review_together')]);
    if (next === m.sig) return;
    m.sig = next;
    const t = doc?.todos ? (Array.isArray(doc.todos) ? todoOf(doc) : doc.todos) : null;
    const lastRows = glimpse ? filesOf([glimpse])[0].hunks[0].lines.filter((l) => l.sign !== ' ').slice(0, 4) : [];
    m.el.replaceChildren(...[
      live && doc ? nowBlock(key, doc, { small: true }) : null,
      live && t?.all ? h('p.small', `${t.done} of ${t.all} done${t.working ? `. Now: ${t.working}` : ''}`) : null,
      held ? holdLine(held) : live ? endedLine(doc) : null,
      q ? h('p.small.bs-q', h('b', 'It asks you: '), clip(q.text || '', 160), ' ', h('span', q.state === 'waiting' ? { 'data-bs-q': q.until } : {}, questionWait(q))) : null,
      lastMsg ? h('p.small', h('span.muted', 'Your last note: '), messageStatus(lastMsg).word) : null,
      walking && !walking.sample ? (() => { const wm = messageIn(docs.get(key), walking.id); return wm?.state === 'answered' ? null : h('p.small.muted', 'It walks you through its changes at its next step.'); })() : null,
      glimpse ? h('div.bs-glimpse', { 'aria-label': `Its latest change, in ${glimpse.file}` },
        h('p.small', h('b', glimpse.file), ' ', h('span.muted', totalsWords(changeTotals(changes)))),
        lastRows.length ? h('ol.bs-lines', lastRows.map((l) => h('li', h(`div.bs-line.${l.sign === '+' ? 'bs-add' : 'bs-del'}`,
          h('span.offscreen', `${(l.sign === '-' ? l.old : l.new) != null ? `Line ${l.sign === '-' ? l.old : l.new}, ` : ''}${signWord(l.sign)}: ${l.text}`),
          h('span.bs-contents', { 'aria-hidden': 'true' }, h('span.bs-ln', String((l.sign === '-' ? l.old : l.new) ?? '')), h('span.bs-sign', l.sign === '+' ? '+' : '−'), h('span.bs-code', l.text || ' ')))))) : null) : null,
      env.href?.(key) ? h('p.small', h('a', { href: env.href(key) }, live ? 'All of it, on its page' : 'Its page')) : null,
    ].filter(Boolean));
  }
  function mini(key) {
    if (!key || (!part('live') && !part('hold') && !part('questions'))) return null;
    want(key);
    if (!hasScreen(key) && !holdOf(key) && !questionsOf(key).length) return null;
    let m = minis.get(key);
    if (!m) { m = { el: h('div.bs-mini', { role: 'group', 'aria-label': 'Its screen', 'data-bs-key': key }), sig: '' }; minis.set(key, m); }
    drawMini(key, m);
    return m.el;
  }
  function drawMinis() { for (const [key, m] of minis) if (m.el.isConnected) drawMini(key, m); }

  // In Talk with someone else: the questions agents are asking you, each with a way to answer it.
  let bannerEl = null;
  let bannerSig = '';
  function banner() {
    if (!part('questions') || !control?.on) return null;
    const qs = control.questions();
    if (!qs.length) return null;
    const next = JSON.stringify(qs.map((q) => [q.id, q.state]));
    if (!bannerEl) bannerEl = h('div.bs-mini.bs-banner', { role: 'status' });
    if (next !== bannerSig) {
      bannerSig = next;
      bannerEl.replaceChildren(...qs.slice(0, 3).map((q) => h('p.small',
        h('b', `${env.convo(q.key)?.title || q.title || 'An agent'} asks you: `), clip(q.text || '', 120), ' ',
        h('button.btn', { type: 'button', onclick: () => env.talkTo?.(q.key) }, 'Talk to it'))));
    }
    return bannerEl;
  }

  // A question on Needs you and its conversation's page: how long it waits, its choices as buttons, and a box for
  // your own words.
  function questionParts(i) {
    const q = i.q;
    if (!q) return [];
    const out = [h('p.small.bs-qwait.waiting-do', q.state === 'waiting' ? { 'data-bs-q': q.until } : {}, questionWait(q))];
    const list = Array.isArray(q.questions) ? q.questions.filter((x) => x && x.question) : [];
    const send = (given) => env.done(whole(answer(q, given)), (said) => said || 'Answered.');
    if (q.kind === 'choices' && list.length === 1 && !list[0].multiSelect) {
      const one = list[0];
      out.push(h('div.control-row.waiting-do.bs-options', { role: 'group', 'aria-label': one.question },
        (one.options || []).filter((o) => o?.label).map((o, k) => h(`button.btn${k === 0 ? '.primary' : ''}.bs-option`, { type: 'button', onclick: () => send({ answers: { [one.question]: o.label } }) },
          h('b', o.label), o.description ? h('span.small', o.description) : null))));
    } else if (q.kind === 'choices' && list.length) {
      const pick = (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const answers = {};
        for (const [k, one] of list.entries()) {
          const ticked = [...form.querySelectorAll(`input[name="q${k}"]:checked`)].map((x) => x.value);
          if (!ticked.length) { form.querySelector(`input[name="q${k}"]`)?.focus(); return; }
          answers[one.question] = one.multiSelect ? ticked : ticked[0];
        }
        send({ answers });
      };
      out.push(h('form.bs-choices.waiting-do', { onsubmit: pick },
        list.map((one, k) => h('fieldset', h('legend', one.header ? `${one.header}: ${one.question}` : one.question),
          (one.options || []).filter((o) => o?.label).map((o) => h('label', h('input', { type: one.multiSelect ? 'checkbox' : 'radio', name: `q${k}`, value: o.label }),
            h('span', h('b', o.label), o.description ? h('span.small.muted', ` ${o.description}`) : null))))),
        h('div.control-row', h('button.btn.primary', { type: 'submit' }, 'Send my answers'))));
    }
    if (q.said) out.push(h('details.explain.waiting-do', h('summary', 'What it said before asking'), h('p', clip(q.said, 1200))));
    const own = (event) => {
      event.preventDefault();
      const input = event.currentTarget.elements.text;
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      input.blur();
      send({ text });
    };
    out.push(h('form.control-say.waiting-do', { onsubmit: own },
      h('input', { name: 'text', type: 'text', maxlength: 2000, autocomplete: 'off', placeholder: q.kind === 'choices' ? 'Or answer in your own words' : 'Answer it', 'aria-label': `Your answer to ${i.title}` }),
      h('button.btn', { type: 'submit' }, 'Send')));
    return out;
  }

  // Counting down and counting up, every second, where they show.
  function tick() {
    const n = nowS();
    for (const el of document.querySelectorAll('[data-bs-since]')) el.textContent = forWords(n - Number(el.dataset.bsSince));
    for (const el of document.querySelectorAll('[data-bs-hold]')) el.textContent = holdWords({ state: 'held', until: Number(el.dataset.bsHold) }, n)?.line || '';
    for (const el of document.querySelectorAll('[data-bs-q]')) el.textContent = questionWait({ state: 'waiting', until: Number(el.dataset.bsQ) }, n);
  }
  setInterval(tick, 1000);

  return {
    start() { if (!running) { running = true; poll(); } return this; },
    stop() { running = false; clearTimeout(timer); },
    refresh: poll,
    want,
    lines: () => lines,
    hasScreen,
    reachable,
    working,
    // the walk's desk monitor: what it is doing now, in a line
    monitor: (key) => (part('live') && lines[key] ? monitorLine(lines[key]) : null),
    page,
    mini,
    banner,
    questionParts,
    heard,
    relay,
    speakUp,
    buttons,
    questionButtons,
    hold, goOn, walk, good, answer,
    whole,
    madeUp: isSample,
  };
}
