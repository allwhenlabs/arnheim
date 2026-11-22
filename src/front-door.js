// One front door (connect/intake.py; docs/connect.md, "One front door"). Anything you say or type that is work becomes a
// ready task for a floor: a short title, "Done when", "Proven by", its agent, and an estimate only when the floor's own
// finished work gives one. The receptionist, a floor's lead and Talk read it back and ask "Start it?"; the "What needs
// doing?" box on Needs you and in a floor's Work room makes one too; the "Ready to start" cards have Start, Change and
// Drop, and say what is next on each floor. A paired phone does all of it through control. The made-up company shows
// its own sample tasks (sample/work.json, "ready"), and nothing real starts.
//
// The rules for what is work (workSaid), the queue line and the estimate in words are plain functions, so
// tests/test_front_door.py can run them under Node.js. createFrontDoor(env) takes:
//   control      control.js's: on, intake, startReady, dropReady, changeReady, ready(), state(), watch
//   on()         whether the front door shows: its switch, and control on (or the made-up company)
//   madeUp()     the made-up company: nothing real starts
//   floors()     the floors work can go to: [{ id, project, label }]
//   sample()     the made-up company's ready tasks
//   phone()      whether this page is on a paired phone (the task says it came from there)
//   done(promise, said)  what the page does with what a button did: show `said(result)`, or the error
//   changed()    draw the page again

import { handedOut } from './control.js';
import { icon } from './icons.js';

const CSS = new URL('./front-door.css', import.meta.url).href;

/* ---------- what is work ---------- */

// A question or a word to the building, not work: questions, greetings, and what the receptionist and the leads
// answer themselves (the round, what's new, take me to, stop, remember, remind me).
const ASKING = /^(?:what|what's|whats|how|how's|hows|whether|where|when|why|who|who's|whom|which|is|isn't|are|aren't|am|was|wasn't|were|weren't|do|don't|does|doesn't|did|didn't|has|hasn't|have|haven't|had|shall|may|might|should|shouldn't|will|won't|tell|show|give|take|remind|remember|forget|thanks|thank|hi|hello|hey|bye|good|yes|yeah|no|nope|ok|okay|sure|stop|start|pause|resume|allow|deny|go|open|read|walk|hold|carry)\b/i;
const LEAD = /^(?:(?:please|ok|okay|so|right|and|also)[,\s]+)*(?:(?:can|could|would|will)\s+(?:you|someone|somebody|an?\s+agent)\s+(?:please\s+)?|let'?s\s+|we\s+(?:need|have)\s+to\s+|i\s+(?:need|want)\s+(?:you\s+|someone\s+)?to\s+|(?:someone|somebody|we)\s+should\s+|please\s+)?/i;
const VERBS = 'fix|add|make|build|write|update|change|remove|rename|refactor|tidy|clean(?: up)?|speed up|improve|move|create|set up|implement|investigate|look into|find out why|figure out|debug|bump|upgrade|translate|document|redesign|rewrite|replace|port|migrate|optimi[sz]e|sort out|get rid of|delete|merge|deploy|publish|release|ship|turn (?:on|off)|enable|disable|support|polish|simplify|split|combine|swap|resize|test';
const VERB = new RegExp(`${LEAD.source}(?:${VERBS})\\b`, 'i');
const ASKED_TO = /^(?:(?:please|so|and)[,\s]+)*(?:can|could|would|will)\s+(?:you|someone|somebody|an?\s+agent)\b/i;
const WANT = /^(?:(?:please|so|and|also)[,\s]+)*(?:we need|we want|i want|i'd like|i would like|it would be nice|it'd be nice|someone should|we should)\b/i;
const PROBLEM = new RegExp([
  String.raw`\b(?:is|are|feels?|seems?|looks?|keeps?|gets?|got|went|has been|have been)\s+(?:(?:too|so|really|very|a bit|kind of|still|getting)\s+)*(?:slow|broken|wrong|off|ugly|confusing|flaky|failing|crashing|stuck|missing|out of date|outdated|laggy|janky|clunky|buggy|blank|empty|cut off|misaligned|unreadable|down|stale)\b`,
  String.raw`\b(?:doesn'?t|does not|don'?t|do not|won'?t|will not|can'?t|cannot|isn'?t|is not)\s+(?:work|load|open|save|show|start|sync|build|compile|pass|respond|scroll|fit|send|update)\w*\b`,
  String.raw`\b(?:does|do)\s+nothing\b`,
  String.raw`\b(?:there'?s|there is|we have|i found|found)\s+(?:a|an|another)\s+(?:bug|typo|problem|glitch|crash|error|issue|regression)\b`,
  String.raw`\b(?:crashes|breaks|hangs|freezes|fails)\b`,
].join('|'), 'i');

// Whether words are work to hand out ("the login feels slow on Tidepool", "fix the footer", "we need a dark mode",
// "get someone to ..."), not a question or a word to the building. `floors` is [{ project, label }].
export function workSaid(text, floors = []) {
  const said = String(text || '').trim();
  if (said.length < 6) return false;
  const asked = ASKED_TO.test(said);
  if (/\?$/.test(said) && !asked) return false;
  const list = floors.map((f) => ({ project: f.project, label: f.label }));
  const handed = handedOut(said, list);
  if (ASKING.test(said) && !handed && !VERB.test(said)) return false;
  return !!handed || VERB.test(said) || WANT.test(said) || PROBLEM.test(said);
}

// "Yes" to "Start it?", and "no".
export const START_IT = /^(?:(?:yes|yeah|yep|sure|ok|okay|please|go ahead|do it|start it|start|go)[,.!]?\s*)+(?:now|please)?[.!]?$/i;
export const NOT_NOW = /^(?:no|nope|not now|not yet|later|leave it|don'?t|cancel|never ?mind)\b/i;

// The floor someone names when asked which: "Tidepool", "on Tidepool", "the Tidepool floor", "tide".
export function floorPicked(text, floors) {
  const asked = String(text || '').trim().toLowerCase().replace(/^(?:it's\s+|its\s+|on\s+|for\s+|in\s+)/, '').replace(/^the\s+/, '')
    .replace(/\s+(?:floor|project)$/, '').replace(/[.!?]+$/, '');
  if (!asked) return null;
  return floors.find((f) => f.label.toLowerCase() === asked || f.project.toLowerCase() === asked)
    || (asked.length > 2 ? floors.find((f) => f.label.toLowerCase().startsWith(asked)) : null) || null;
}

/* ---------- words for the page ---------- */

const tokensSaid = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(1).replace(/\.0$/, '')} million` : n >= 1000 ? `${Math.round(n / 1000)} thousand` : String(n));

// The estimate, from the floor's own finished work (connect/intake.py, estimate), or null when there is none.
export function estimateWords(e) {
  if (!e || !Number.isFinite(e.minutes)) return null;
  const time = e.minutes >= 90 ? `${Math.round(e.minutes / 6) / 10} hours` : `${e.minutes} minute${e.minutes === 1 ? '' : 's'}`;
  return `About ${time}${Number.isFinite(e.tokens) && e.tokens > 0 ? ` and ${tokensSaid(e.tokens)} tokens` : ''}, going by ${e.from} finished jobs here.`;
}

// What starts next on each floor with something queued: ['Next on Tidepool: "Fix the footer", then 1 more.'].
export function queueLine(tasks, label = (p) => p) {
  const by = new Map();
  for (const t of tasks || []) if (t?.state === 'queued') by.set(t.project, [...(by.get(t.project) || []), t]);
  return [...by.entries()].map(([p, list]) => `Next on ${label(p)}: "${list[0].title}"${list.length > 1 ? `, then ${list.length - 1} more` : ''}.`);
}

/* ---------- the page ---------- */

function styled() {
  if (typeof document === 'undefined' || document.querySelector('link[data-arnheim-door]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS;
  link.dataset.arnheimDoor = '';
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
const btn = (label, onclick, cls = '', glyph = null) => h(`button.btn${cls}`, { type: 'button', onclick }, glyph && icon(glyph, 15), label);

export function createFrontDoor(env) {
  if (env.styled !== false) styled();
  const control = env.control;
  const on = () => { try { return !!env.on(); } catch { return false; } };
  const madeUp = () => { try { return !!env.madeUp?.(); } catch { return false; } };
  const floors = () => { try { return env.floors() || []; } catch { return []; } };
  const labelOf = (p) => floors().find((f) => f.project === p)?.label || p;
  const changed = () => { try { env.changed?.(); } catch { /* the page draws itself next time */ } };
  const done = (promise, said) => (env.done ? env.done(promise, said) : promise.then(changed, changed));
  const local = []; // the made-up company's tasks typed here: this tab only
  const hidden = new Set(); // its tasks dropped in this tab
  const notes = new Map(); // a box's last answer, by where it is: { said, which: { text, floors } }
  const editing = new Set(); // the tasks being changed
  let seen = '';
  // the cards follow control: drawn again when the ready tasks change
  control?.watch?.((s) => {
    const sig = JSON.stringify([(s.ready || []).map((t) => [t.id, t.state, t.why, t.title, t.done_when]), s.door]);
    if (sig !== seen) { const first = !seen; seen = sig; if (!first) changed(); }
  });

  const tasks = () => (madeUp()
    ? [...(env.sample?.() || []), ...local].filter((t) => t && !hidden.has(t.id)).map((t) => ({ ...t, label: t.label || labelOf(t.project) }))
    : (control?.ready?.() || []));

  /* ----- talking: the receptionist, a lead, Talk ----- */

  // Your words to the server, as a ready task: { pending, reply }. `pending` waits for your word, and is filled in as
  // the server answers: { door: 'start', id, label, title } for "Start it?", { door: 'which', text } for "Which floor?".
  function ask(text, floor, via) {
    const pending = { door: 'wait', text, via };
    const reply = control.intake(text, floor, via).then((r) => {
      if (r.task) Object.assign(pending, { door: r.task.state === 'ready' ? 'start' : 'done', id: r.task.id, label: r.task.label || labelOf(r.task.project), title: r.task.title });
      else if (Array.isArray(r.floors)) Object.assign(pending, { door: 'which', floors: r.floors });
      else pending.door = 'done';
      return r.reply;
    }, (error) => { pending.door = 'done'; return error.message; });
    return { pending, reply };
  }

  const viaOf = (via) => (env.phone?.() ? 'phone' : via);

  // Work said to the receptionist, a lead or in Talk: a ready task, read back with "Start it?". Null when it isn't work,
  // or the front door is off. `floor`: the floor you are on (a lead's own), or null.
  function take(text, { floor = null, via = 'talk' } = {}) {
    const said = String(text || '').trim();
    if (!on() || !workSaid(said, floors())) return null;
    if (madeUp()) {
      const f = floors().find((x) => new RegExp(`\\b${x.label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(said)) || floors().find((x) => x.project === floor || x.id === floor);
      return { pending: null, reply: `This company is made up, so nothing real starts. With your own company connected, I'd make that a ready task${f ? ` on ${f.label}` : ''}, with Done when and Proven by, and you'd say "start it" or tap Start.` };
    }
    if (!control?.on) return null;
    return ask(said, floor, viaOf(via));
  }

  const start = (id) => control.startReady(id).then((r) => r.reply, (error) => error.message);

  // The answer to what it asked last: "Start it?" or "Which floor?". { pending, reply }, or null when what you said
  // isn't an answer to it (the question still waits).
  function answer(pending, text, { via = 'talk' } = {}) {
    if (!pending || !on() || !control?.on) return null;
    const said = String(text || '').trim();
    if (pending.door === 'start') {
      if (START_IT.test(said)) return { pending: null, reply: start(pending.id) };
      if (NOT_NOW.test(said)) return { pending: null, reply: `All right, it stays ready. It's on Needs you and in ${pending.label}'s Work room when you want it.` };
      return null;
    }
    if (pending.door === 'wait' && (START_IT.test(said) || NOT_NOW.test(said))) return { pending, reply: "One moment: I'm still writing it down." };
    if (pending.door === 'which') {
      if (NOT_NOW.test(said)) return { pending: null, reply: "All right, I won't write it down." };
      const f = floorPicked(said, floors());
      return f ? ask(pending.text, f.project, pending.via || viaOf(via)) : null;
    }
    return null;
  }

  // The card's buttons while "Start it?" waits: Start and Not now. `clear()` forgets the question.
  function controls(pending, clear = () => {}) {
    if (pending?.door !== 'start' || !on()) return null;
    return {
      note: `Ready on ${pending.label}: ${pending.title}`,
      buttons: [
        { label: 'Start', run: () => { clear(); return start(pending.id); } },
        { label: 'Not now', run: () => { clear(); return 'All right, it stays ready.'; } },
      ],
    };
  }

  /* ----- the box: "What needs doing?" ----- */

  function send(where, text, floor) {
    const note = { said: 'Writing it down…' };
    notes.set(where, note);
    changed();
    if (madeUp()) {
      const f = floors().find((x) => x.project === floor) || floors().find((x) => new RegExp(`\\b${x.label}\\b`, 'i').test(text)) || floors()[0];
      const title = sampleTitle(text, f?.label);
      local.push({ id: `rd-${Date.now().toString(16).slice(-10).padStart(10, '0')}`, project: f?.project, label: f?.label, title,
        done_when: 'What you asked for is done, and you have looked at it.', proven_by: 'You look at it', agent: 'Claude Code', estimate: null, state: 'ready', local: true });
      note.said = `Ready on ${f?.label}: "${title}". This company is made up, so it stays in this tab and nothing real starts.`;
      changed();
      return;
    }
    control.intake(text, floor, viaOf('box')).then((r) => {
      if (r.task) note.said = String(r.reply || '').replace(/ Start it\?$/, ' Start it below when you want.');
      else if (Array.isArray(r.floors)) Object.assign(note, { said: r.reply, which: { text, floors: r.floors } });
      else note.said = r.reply || '';
      changed();
    }, (error) => { note.said = error.message; changed(); });
  }

  // The box on Needs you (no floor) or in a floor's Work room ({ floor }: its project and label).
  function box({ floor = null } = {}) {
    if (!on() || (floor && !madeUp() && !floors().some((f) => f.project === floor.project))) return null; // a floor with no folder here
    const where = floor?.project || 'home';
    const note = notes.get(where);
    const go = (event) => {
      event.preventDefault();
      const input = event.currentTarget.elements.text;
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      input.blur();
      send(where, text, floor?.project || null);
    };
    return h('form.panel-card.door-box', { onsubmit: go },
      h('div.sect-head.door-head', icon('inbox', 18), h('h3.sect-title', 'What needs doing?')),
      h('textarea', { name: 'text', rows: 2, maxlength: 2000, 'aria-label': floor ? `What needs doing on ${floor.label}` : 'What needs doing',
        placeholder: floor ? `Say what needs doing on ${floor.label}, in your own words.` : 'Say what needs doing, in your own words, such as "the login feels slow on Tidepool".' }),
      h('div.control-row', h('button.btn.primary', { type: 'submit' }, 'Make it a ready task')),
      note?.said && h('p.small.door-said', { role: 'status' }, note.said),
      note?.which && h('div.control-row.door-floors', note.which.floors.map((label) => btn(label, () => {
        const f = floors().find((x) => x.label === label);
        send(where, note.which.text, f?.project || label);
      }, '.quiet'))),
      !note?.said && h('p.small.muted', floor
        ? `It becomes a ready task on ${floor.label}: a short title, Done when and Proven by. Nothing starts until you tap Start.`
        : 'It becomes a ready task on the floor your words name: a short title, Done when and Proven by. Nothing starts until you tap Start.'));
  }

  /* ----- the cards: "Ready to start" ----- */

  function act(task, kind) {
    if (madeUp() || task.local) {
      if (kind === 'drop') { hidden.add(task.id); changed(); return; }
      done(Promise.resolve(), () => 'This company is made up, so nothing real starts. With your own company, its agent would start now with your words, Done when and Proven by.');
      return;
    }
    if (kind === 'start') done(control.startReady(task.id), (r) => r.reply);
    if (kind === 'drop') done(control.dropReady(task.id), (r) => r.reply);
  }

  function change(task) {
    const save = (event) => {
      event.preventDefault();
      const els = event.currentTarget.elements;
      const fields = { title: els.title.value.trim(), done_when: els.done_when.value.trim() };
      editing.delete(task.id);
      if (madeUp() || task.local) { changed(); return; }
      done(control.changeReady(task.id, fields), (r) => r.reply);
    };
    return h('form.door-edit', { onsubmit: save },
      h('label.small', 'Title', h('input', { name: 'title', value: task.title || '', maxlength: 80, required: true })),
      h('label.small', 'Done when', h('textarea', { name: 'done_when', rows: 2, maxlength: 240, required: true }, task.done_when || '')),
      h('div.control-row', h('button.btn.primary', { type: 'submit' }, 'Save'), btn('Cancel', () => { editing.delete(task.id); changed(); }, '.quiet')));
  }

  function card(task, { floor = null } = {}) {
    const est = estimateWords(task.estimate);
    const waits = task.state === 'queued';
    return h('li.door-item',
      h('div.door-top', h(`span.pill${waits ? '.k-working' : '.k-needs'}`, waits ? 'Queued' : 'Ready'),
        !floor && h('span.small.muted', task.label || labelOf(task.project)), h('span.small.muted', task.agent || 'Claude Code')),
      h('h4.door-title', task.title),
      editing.has(task.id) ? change(task) : [
        h('dl.door-facts', h('dt', 'Done when'), h('dd', task.done_when), h('dt', 'Proven by'), h('dd', task.proven_by),
          est && h('dt', 'Estimate'), est && h('dd', est)),
        (task.why || task.held) && h('p.small.door-why', task.why || task.held),
        h('div.control-row',
          !waits && btn('Start', () => act(task, 'start'), '.primary', 'zap'),
          btn('Change', () => { editing.add(task.id); changed(); }, '.quiet'),
          btn('Drop', () => act(task, 'drop'), '.quiet', 'x')),
      ]);
  }

  // The ready and queued tasks: every floor's on Needs you, one floor's in its Work room ({ floor }).
  function cards({ floor = null } = {}) {
    if (!on()) return null;
    const rows = tasks().filter((t) => !floor || t.project === floor.project);
    if (!rows.length) return null;
    const next = queueLine(rows, labelOf);
    return h('section.panel-card.door-cards',
      h('div.sect-head.door-head', icon('list-checks', 18), h('h3.sect-title', `Ready to start (${rows.length})`)),
      next.map((line) => h('p.small.door-next', line)),
      madeUp() && h('p.small.muted', 'Made up, like the rest of this company: nothing real starts.'),
      h('ul.door-list', rows.map((t) => card(t, { floor }))));
  }

  return { on, take, answer, controls, box, cards, tasks };
}

// A title by rule, for the made-up company only (your own company's are written by connect/intake.py).
function sampleTitle(text, label) {
  let words = String(text || '').trim().replace(/^(?:(?:please|can you|could you)\s+)+/i, '');
  if (label) words = words.replace(new RegExp(`\\s+(?:on|for|in)\\s+(?:the\\s+)?${label}(?:\\s+floor)?[.!?]*$`, 'i'), '');
  words = words.replace(/[\s.!?]+$/, '');
  words = words[0] ? words[0].toUpperCase() + words.slice(1) : 'A task';
  return words.length > 60 ? `${words.slice(0, 59).replace(/\s+\S*$/, '')}…` : words;
}
