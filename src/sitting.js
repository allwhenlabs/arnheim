// Office hours' sitting (docs/connect.md, "Office hours"; connect/deputy.py): everything that waited for you, one
// thing at a time, full screen on a computer and a phone, "3 of 7". The questions agents asked, with their choices as
// buttons and a box for your own words; permissions waiting now, with Allow, Deny and Later (A, D and L) and how
// careful to be; what waited while you were away; then what the floors' leads answered for you, to glance at, with
// Undo; then ready tasks, where the building has them. By voice too, through Talk: "next", "skip", "allow", "deny",
// "the first one", or your own words. A short summary at the end.
//
// The rules (what you said, the order, the alert, the summary) are plain functions, so tests/test_office_hours.py runs
// them under Node. createSitting(env) draws it, and takes:
//   control       control.js's, or a function giving it (a stand-in for the made-up company)
//   state()       what control's state says, or the made-up company's
//   beside        beside-page.js's (its questionParts: a question's choices and your own words)
//   item(kind, id) the page's waiting item for a live question ('question') or permission ('permission'), or null
//   answerAsk(i, behavior)  answers a permission, as Needs you does (a promise)
//   label(p)      a floor's name
//   risk(i)       how careful to be with a permission: { word, mood, line } (risk.js)
//   leadPick(i)   with the brain on, the floor's lead's pick for a question (a promise of words), or null
//   voiceOn()     whether Answering by voice is switched on (features.js's 'answers'); missing counts as off
//   learn()       the "Remember my answer" and "Always ask me this" ticks, as [elements, () => fields]
//   changed()     the sitting opened or closed: draw the page again

import { icon } from './icons.js';
import { ALLOW, DENY } from './control.js';

const CSS = new URL('./sitting.css', import.meta.url).href;
const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const clip = (text, most = 300) => { const t = String(text || '').replace(/\s+/g, ' ').trim(); return t.length > most ? `${t.slice(0, most - 1)}…` : t; };

// About two things a minute.
export function aboutMinutes(n) {
  return Math.max(1, Math.round((Number(n) || 0) / 2));
}

// The desktop alert at an office hour: "Office hours: 7 things, about 4 minutes."
export function officeAlert(n, tag = 'arnheim-office') {
  return { title: 'Arnheim', body: `Office hours: ${count(n, 'thing', 'things')}, about ${count(aboutMinutes(n), 'minute', 'minutes')}.`, tag };
}

// "13:00, 18:00" as up to four times a day, in order. Throws, in words, for anything else.
export function parseTimes(text) {
  const parts = String(text || '').split(/[\s,;]+/).filter(Boolean);
  const out = [];
  for (const p of parts) {
    const m = /^([01]?\d|2[0-3]):([0-5]\d)$/.exec(p);
    if (!m) throw new Error(`"${clip(p, 20)}" isn't a time of day. Write it as 13:00.`);
    out.push(`${m[1].padStart(2, '0')}:${m[2]}`);
  }
  const times = [...new Set(out)].sort();
  if (!times.length || times.length > 4) throw new Error('Choose from one to four times a day, such as 13:00, 18:00.');
  return times;
}

// The office hour that began in the last half hour and hasn't alerted yet on this page: its "YYYY-MM-DD HH:MM", or null.
export function dueOffice(times, now = Date.now() / 1000, alerted = new Set()) {
  for (const back of [0, 1]) {
    for (const t of Array.isArray(times) ? times : []) {
      const m = /^(\d\d):(\d\d)$/.exec(String(t));
      if (!m) continue;
      const d = new Date(now * 1000);
      d.setDate(d.getDate() - back);
      d.setHours(Number(m[1]), Number(m[2]), 0, 0);
      const start = d.getTime() / 1000;
      const slot = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${t}`;
      if (now >= start && now < start + 1800 && !alerted.has(slot)) return slot;
    }
  }
  return null;
}

// Everything for a sitting, in order: questions, permissions, what waited while you were away, answered for you (not
// yet undone or glanced at), ready tasks. Each { kind, id, row }.
export function sittingItems({ questions = [], asks = [], parked = [], answered = [], ready = null } = {}) {
  const out = [];
  const live = new Set(['waiting', 'open', 'window']);
  for (const q of questions || []) if (q?.id && live.has(q.state || 'open')) out.push({ kind: 'question', id: q.id, row: q });
  for (const a of asks || []) if (a?.id) out.push({ kind: 'permission', id: a.id, row: a });
  for (const p of parked || []) if (p?.id && !p.seen) out.push({ kind: 'parked', id: p.id, row: p });
  for (const a of answered || []) if (a?.id && !a.undone && !a.seen) out.push({ kind: 'answered', id: a.id, row: a });
  if (Array.isArray(ready)) for (const r of ready) if (r?.id) out.push({ kind: 'ready', id: r.id, row: r });
  return out;
}

const NEXT = /^(?:next|skip|skip it|skip this|pass|move on|go on|fine|ok|okay|that's fine|keep it|looks good)[.!]?$/i;
const LATER = /^(?:later|not now|leave it|put it off|come back to it|ask me later)[.!]?$/i;
const UNDO = /^(?:undo|undo it|undo that|take it back|change it)[.!]?$/i;
const START = /^(?:start|start it|start that|go ahead|do it)[.!]?$/i;
const ORDINALS = { first: 0, one: 0, second: 1, two: 1, third: 2, three: 2, fourth: 3, four: 3, fifth: 4, five: 4, last: -1 };
const ORDINAL = /^(?:the\s+)?(first|second|third|fourth|fifth|last)(?:\s+one)?[.!]?$|^(?:option|number)\s+(one|two|three|four|five|\d)[.!]?$/i;
const bare = (text) => String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();

// What you said in a sitting, for the item in front of you ({ kind, options }): { do: 'next' | 'later' | 'allow' |
// 'deny' | 'pick' | 'words' | 'undo' | 'start', option?, words? }, or null when it isn't for the sitting.
export function sittingHeard(text, item) {
  const said = String(text || '').trim();
  if (!said || !item) return null;
  if (NEXT.test(said)) return { do: 'next' };
  if (LATER.test(said)) return { do: 'later' };
  if (item.kind === 'permission') {
    if (ALLOW.test(said)) return { do: 'allow' };
    if (DENY.test(said)) return { do: 'deny' };
    return null;
  }
  if (item.kind === 'answered') return UNDO.test(said) ? { do: 'undo' } : null;
  if (item.kind === 'ready') return START.test(said) ? { do: 'start' } : null;
  if (item.kind === 'question') {
    const options = Array.isArray(item.options) ? item.options : [];
    const m = ORDINAL.exec(said);
    if (m && options.length) {
      const word = (m[1] || m[2]).toLowerCase();
      const at = /^\d$/.test(word) ? Number(word) - 1 : ORDINALS[word];
      const option = at === -1 ? options[options.length - 1] : options[at];
      if (option) return { do: 'pick', option };
    }
    const named = options.find((o) => bare(o) && bare(o) === bare(said));
    if (named) return { do: 'pick', option: named };
    return { do: 'words', words: said };
  }
  return null;
}

// A permission answered out loud follows the same rule as everywhere else (leads.js, voiceAnswer): never by voice when
// it may touch something private ("Look first"), nor with Answering by voice switched off. Typed or tapped, it goes.
export const LOOK_SAID = 'That one may touch something private, so I won\'t answer it by voice: answer it on the screen.';
export const OFF_SAID = 'Answering by voice is switched off. Answer it on the screen.';
export function voiceRefused({ spoken = false, on = false, risk = null } = {}) {
  return !!spoken && (risk === 'Look first' || !on);
}

// The building learns from your corrections (connect/deputy.py): after an Undo it asks once, "Should the leads stop
// answering this kind of question for you?", and after Show me's Not quite, "Should Show me ask you before calling this
// kind of change done?". A yes or a no, said or typed while it asks: 'yes', 'no', or null for anything else.
const LEARN_YES = /^(?:yes|yeah|yep|yes please|please do|do that|go ahead|stop answering(?: it| them)?|ask me(?: first)?)[.!]?$/i;
const LEARN_NO = /^(?:no|nope|no thanks|no thank you|keep answering(?: it| them)?|leave it)[.!]?$/i;
const PUT_BACK = /^(?:undo|undo it|undo that|put it back)[.!]?$/i;
export function learnHeard(text) {
  const said = String(text || '').trim();
  return LEARN_YES.test(said) ? 'yes' : LEARN_NO.test(said) ? 'no' : null;
}

// The question with Yes and No, where the correction was made: Needs you's Answered for you, the sitting, a Show me
// card. yes() and no() are what each does.
export function learnAsk(ask, { yes, no } = {}) {
  styled();
  return h('div.learn-ask', { role: 'group', 'aria-label': 'Learn from this' },
    h('p.learn-q', ask),
    h('div.learn-do', btn('Yes', () => yes?.(), '.primary'), btn('No', () => no?.())));
}

// A decision set aside after two Undos, said where the second was made, with Undo.
export function asideNote(said, undo) {
  styled();
  return h('div.learn-ask.learn-aside', { role: 'status' }, h('p.learn-q', said), h('div.learn-do', btn('Undo', () => undo?.(), '.quiet')));
}

// The summary at the end, in a sentence or two.
export function summaryOf(done = {}) {
  const parts = [];
  if (done.answered) parts.push(`answered ${done.answered}`);
  if (done.allowed) parts.push(`allowed ${done.allowed}`);
  if (done.denied) parts.push(`denied ${done.denied}`);
  if (done.started) parts.push(`started ${done.started}`);
  if (done.later) parts.push(`left ${done.later} for later`);
  const list = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0];
  const undone = done.undone ? ` ${count(done.undone, 'answer for you was', 'answers for you were')} undone.` : '';
  if (!list) return undone ? `Done.${undone}` : 'Done. Nothing needed you.';
  return `Done. You ${list}.${undone}`;
}

/* ---------- on the page ---------- */

function styled() {
  if (typeof document === 'undefined' || document.querySelector('link[data-arnheim-sitting]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS;
  link.dataset.arnheimSitting = '';
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
const btn = (label, onclick, cls = '', key = null) => h(`button.btn${cls}`, { type: 'button', onclick }, label, key && h('span.kbd', key));
const clockOf = (at) => new Date(Number(at) * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

export function createSitting(env) {
  styled(); // its styles serve Needs you and Settings too (Answered for you, office hours)
  const C = () => (typeof env.control === 'function' ? env.control() : env.control) || {}; // control.js's, or the made-up company's stand-in
  let el = null;
  let queue = []; // [{ kind, id }] in the order they come up
  let pos = 0;
  let done = {};
  let note = '';
  let picks = new Map(); // question id -> the lead's pick, or 'asking'
  let busy = false;
  let asking = null; // after an Undo: { id, ask } or { id, aside: said }, shown above the next card until answered
  let lastSig = '';
  let unwatch = null;

  const state = () => (env.state ? env.state() || {} : C().on ? C().state() : {});
  const now = () => sittingItems({ ...state(), ready: Array.isArray(state().ready) ? state().ready : null });
  const find = (q) => now().find((x) => x.kind === q.kind && x.id === q.id) || null;
  const current = () => {
    while (pos < queue.length && !find(queue[pos])) pos += 1; // answered elsewhere, or it moved on: the next one
    return pos < queue.length ? find(queue[pos]) : null;
  };

  // New things that came during the sitting go at the end.
  function catchUp() {
    const known = new Set(queue.map((q) => `${q.kind}:${q.id}`));
    for (const x of now()) if (!known.has(`${x.kind}:${x.id}`)) queue.push({ kind: x.kind, id: x.id });
  }

  function seen(x) {
    if ((x.kind === 'parked' || x.kind === 'answered') && typeof C().setOffice === 'function') C().setOffice({ seen: [x.id] }).catch(() => {});
  }
  function next(why = null) {
    const x = current();
    if (x) seen(x);
    if (why) done[why] = (done[why] || 0) + 1;
    pos += 1;
    draw();
  }
  async function act(promise, why, said) {
    if (busy) return;
    busy = true;
    current();
    const was = queue[pos]; // the one answered: the page may move past it by itself before the answer comes back
    try {
      const out = await promise;
      note = typeof said === 'function' ? said(out) : said || '';
      if (why) done[why] = (done[why] || 0) + 1;
      if (was) seen(was);
      if (queue[pos] === was) pos += 1;
    } catch (error) {
      note = error?.message || 'That didn\'t go through.';
    } finally {
      busy = false;
      draw();
    }
  }

  /* ---------- each kind ---------- */

  function head(kicker, title, sub) {
    return [h('p.sit-kicker', kicker), h('h3.sit-title', title), sub && h('p.sit-sub', sub)];
  }
  const where = (row) => [env.label(row.project) || row.project, row.agent].filter(Boolean).join(', ');

  function leadPart(i) {
    if (!env.leadPick) return null;
    const got = picks.get(i.id);
    if (got && got !== 'asking') return h('p.sit-pick', h('b', 'The lead: '), got);
    if (got === 'asking') return h('p.sit-pick.muted', 'Asking the lead which they would pick…');
    const asked = env.leadPick(i);
    if (!asked) return null;
    picks.set(i.id, 'asking');
    Promise.resolve(asked).then((said) => { picks.set(i.id, clip(said, 400) || 'The lead has no pick.'); draw(); },
      () => { picks.set(i.id, 'The lead couldn\'t answer just now.'); draw(); });
    return h('p.sit-pick.muted', 'Asking the lead which they would pick…');
  }

  function questionCard(x) {
    const i = env.item('question', x.id);
    const q = x.row;
    const [ticks, fields] = env.learn();
    const parts = i ? env.beside.questionParts(i, { more: fields }) : [];
    return [
      ...head(q.urgent ? `Urgent: ${q.urgent}` : 'A question', `${q.title || 'An agent'} asks you`, where(q)),
      h('p.sit-what', `"${clip(q.text, 400)}"`),
      leadPart({ id: `q:${q.id}`, project: q.project, what: q.text, q }),
      ticks,
      h('div.sit-answer', parts),
      h('div.sit-do', btn('Later', () => next('later'), '.quiet', 'L')),
    ];
  }

  function permissionCard(x) {
    const i = env.item('permission', x.id);
    const a = x.row;
    const risk = i ? env.risk(i) : null;
    return [
      ...head('A permission', `${i?.title || 'An agent'} wants your permission`, where({ project: i?.project, agent: null })),
      h('div.what-code.sit-code', clip(a.what, 400)),
      risk && h('p.risk', h(`b.risk-${risk.mood}`, `${risk.word}. `), risk.line),
      h('div.sit-do',
        btn('Allow', () => i && act(env.answerAsk(i, 'allow'), 'allowed', 'Allowed, just this once.'), '.primary', 'A'),
        btn('Deny', () => i && act(env.answerAsk(i, 'deny'), 'denied', 'Denied.'), '', 'D'),
        btn('Later', () => next('later'), '.quiet', 'L')),
    ];
  }

  function parkedCard(x) {
    const p = x.row;
    const at = clockOf(p.at);
    if (p.kind === 'permission') {
      const risk = env.risk({ kind: 'permission', tool: p.tool, what: p.what, ask: { what: p.what } });
      return [
        ...head(p.urgent ? `Urgent: ${p.urgent}` : 'While you were away', `${p.title || 'An agent'} asked for permission at ${at}`, where(p)),
        h('div.what-code.sit-code', clip(p.what, 400)),
        risk && h('p.risk', h(`b.risk-${risk.mood}`, `${risk.word}. `), risk.line),
        h('p.sit-sub', p.state === 'moved on' ? 'It was answered in its own window, and went on.' : 'It asks in its own window: answer it there.'),
        h('div.sit-do', btn('Next', () => next(), '.primary', 'N')),
      ];
    }
    const one = (Array.isArray(p.questions) ? p.questions : [])[0];
    const [ticks, fields] = env.learn();
    const send = (given) => act(C().replyQuestion(p.id, { ...given, ...(fields() || {}) }), 'answered', 'Sent. It reads it at its next step.');
    const own = (event) => {
      event.preventDefault();
      const text = event.currentTarget.elements.text.value.trim();
      if (text) send({ text });
    };
    return [
      ...head('While you were away', `${p.title || 'An agent'} asked at ${at}`, where(p)),
      h('p.sit-what', `"${clip(p.text, 400)}"`),
      h('p.sit-sub', 'It was told you were away, so it took a safe choice it could change later, or put this aside.'),
      leadPart({ id: `p:${p.id}`, project: p.project, what: p.text, q: { questions: p.questions } }),
      ticks,
      one && Array.isArray(one.options) && (Array.isArray(p.questions) ? p.questions.length : 0) === 1 && !one.multiSelect
        && h('div.control-row.sit-options', one.options.filter((o) => o?.label).map((o, k) => h(`button.btn${k === 0 ? '.primary' : ''}.bs-option`,
          { type: 'button', onclick: () => send({ answers: { [one.question]: o.label } }) }, h('b', o.label), o.description ? h('span.small', o.description) : null))),
      h('form.control-say.sit-own', { onsubmit: own },
        h('input', { name: 'text', type: 'text', maxlength: 2000, autocomplete: 'off', placeholder: 'Answer in your own words', 'aria-label': 'Your answer' }),
        h('button.btn', { type: 'submit' }, 'Send')),
      h('div.sit-do', btn('Later', () => next('later'), '.quiet', 'L')),
    ];
  }

  // What the building asks after an Undo, or says when it set the decision aside: answered here, once.
  function learned(out, id) {
    const l = out?.learn;
    asking = l?.ask ? { id, ask: l.ask } : l?.set_aside ? { id, aside: l.said } : null;
  }
  function learnAnswer(yes) {
    const was = asking;
    asking = null;
    const call = !was ? null : was.aside ? (yes ? C().learnUndo?.(was.id) : null) : (yes ? C().learnYes : C().learnNo)?.({ id: was.id });
    if (!call) { draw(); return Promise.resolve(''); }
    return Promise.resolve(call).then((r) => { note = r?.reply || ''; draw(); return r?.reply || ''; },
      (error) => { note = error?.message || 'That didn\'t go through.'; draw(); return note; });
  }
  function learnPart() {
    if (!asking) return null;
    if (asking.aside) return asideNote(asking.aside, () => learnAnswer(true));
    return learnAsk(asking.ask, { yes: () => learnAnswer(true), no: () => learnAnswer(false) });
  }

  function answeredCard(x) {
    const a = x.row;
    const undo = (event) => {
      event?.preventDefault?.();
      const words = el.querySelector('input[name="instead"]')?.value.trim() || null;
      act(C().undoAnswer(a.id, words).then((r) => { learned(r, a.id); return r; }), 'undone',
        (r) => r?.note || 'Undone. It hears that you changed it before its next step.');
    };
    return [
      ...head('Answered for you', `${a.title || 'An agent'} asked: "${clip(a.question, 300)}"`, where(a)),
      h('p.sit-what', h('b', 'The lead answered: '), clip(a.answer, 300)),
      h('p.sit-sub', `From ${a.from}${/[.!?]['"”’]?$/.test(a.from || '') ? '' : '.'}`),
      h('form.control-say.sit-own', { onsubmit: undo },
        h('input', { name: 'instead', type: 'text', maxlength: 1500, autocomplete: 'off', placeholder: 'What it should do instead (optional)', 'aria-label': 'What it should do instead' }),
        h('button.btn', { type: 'submit' }, 'Undo')),
      h('div.sit-do', btn('Fine', () => next(), '.primary', 'N')),
    ];
  }

  function readyCard(x) {
    const r = x.row;
    const can = typeof C().startReady === 'function';
    return [
      ...head('Ready to start', clip(r.title, 200), where(r)),
      r.done_when && h('p.sit-sub', h('b', 'Done when: '), r.done_when),
      r.proven_by && h('p.sit-sub', h('b', 'Proven by: '), r.proven_by),
      h('div.sit-do',
        can && btn('Start', () => act(C().startReady(r.id), 'started', (out) => out?.reply || 'Started.'), '.primary'), // queued, it says why
        btn('Later', () => next('later'), '.quiet', 'L')),
    ];
  }

  /* ---------- drawing ---------- */

  function draw() {
    if (!el) return;
    catchUp();
    const x = current();
    const total = queue.length;
    const body = !x
      ? [h('p.sit-kicker', 'Office hours'), h('h3.sit-title', summaryOf(done)), h('div.sit-do', btn('Close', () => close(), '.primary'))]
      : x.kind === 'question' ? questionCard(x)
        : x.kind === 'permission' ? permissionCard(x)
          : x.kind === 'parked' ? parkedCard(x)
            : x.kind === 'answered' ? answeredCard(x) : readyCard(x);
    el.replaceChildren(h('div.sit-box', { role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'sit-count' },
      h('div.sit-top',
        h('span.sit-count', { id: 'sit-count' }, x ? `${Math.min(pos + 1, total)} of ${total}` : 'The sitting'),
        h('button.btn.quiet.sit-close', { type: 'button', onclick: () => close(), 'aria-label': 'Close the sitting' }, icon('x', 16), 'Close')),
      note && h('p.small.note.sit-note', { role: 'status' }, note),
      learnPart(),
      h('div.sit-card', body)));
    note = '';
  }

  function onKey(event) {
    if (!el) return;
    if (event.key === 'Escape') { event.preventDefault(); close(); return; }
    if (event.target.matches?.('input, textarea, select, [contenteditable]') || event.metaKey || event.ctrlKey || event.altKey || event.repeat) return;
    const x = current();
    if (!x) return;
    const k = event.key.toLowerCase();
    if (k === 'l' && x.kind !== 'answered') { event.preventDefault(); next('later'); return; }
    if ((k === 'n' || event.key === 'ArrowRight') && (x.kind !== 'permission' && x.kind !== 'question')) { event.preventDefault(); next(); return; }
    if (x.kind === 'permission' && (k === 'a' || k === 'd')) {
      const i = env.item('permission', x.id);
      if (!i) return;
      event.preventDefault();
      act(env.answerAsk(i, k === 'a' ? 'allow' : 'deny'), k === 'a' ? 'allowed' : 'denied', k === 'a' ? 'Allowed, just this once.' : 'Denied.');
    }
  }

  function open() {
    if (el) return;
    styled();
    queue = now().map((x) => ({ kind: x.kind, id: x.id }));
    pos = 0;
    done = {};
    note = '';
    asking = null;
    picks = new Map();
    el = h('div.sit', { 'aria-label': 'Office hours' });
    document.body.append(el);
    document.body.classList.add('sit-open');
    document.addEventListener('keydown', onKey, true);
    if (typeof C().setOffice === 'function') C().setOffice({ open: true }).catch(() => {});
    unwatch = C().watch?.((s) => {
      const sig = JSON.stringify([(s.questions || []).map((q) => q.id), (s.asks || []).map((a) => a.id), (s.parked || []).map((p) => p.id),
        (s.answered || []).map((a) => [a.id, a.undone]), Array.isArray(s.ready) ? s.ready.map((r) => r.id) : null]);
      if (sig !== lastSig) { lastSig = sig; draw(); }
    }) || null;
    draw();
    el.querySelector('.sit-box button.primary, .sit-box button')?.focus();
    env.changed?.();
  }

  function close() {
    if (!el) return;
    el.remove();
    el = null;
    document.body.classList.remove('sit-open');
    document.removeEventListener('keydown', onKey, true);
    unwatch?.();
    unwatch = null;
    if (typeof C().setOffice === 'function') C().setOffice({ open: false }).catch(() => {});
    env.changed?.();
  }

  // Spoken or typed in Talk while the sitting is open: what it did, in words, or null for Talk to answer as usual.
  // { spoken }: said out loud, so a permission follows the voice rule (voiceRefused).
  function heard(text, { spoken = false } = {}) {
    if (asking) { // what the building asked after an Undo, answered out loud
      const said = learnHeard(text);
      if (asking.aside && PUT_BACK.test(String(text || '').trim())) return learnAnswer(true).then((r) => r || 'Put back.');
      if (said && !asking.aside) return learnAnswer(said === 'yes').then((r) => r || 'Fine.');
    }
    const x = current();
    if (!x) return null;
    const one = x.kind === 'parked' && x.row.kind === 'question' ? (x.row.questions || [])[0] : x.kind === 'question' ? (x.row.questions || [])[0] : null;
    const shape = { kind: x.kind === 'parked' ? (x.row.kind === 'question' ? 'question' : 'parked') : x.kind,
      options: (one?.options || []).map((o) => o?.label).filter(Boolean) };
    const got = sittingHeard(text, shape);
    if (!got) return null;
    const then = () => { const y = current(); return y ? ` Next: ${sayItem(y)}` : ` ${summaryOf(done)}`; };
    const run = (promise, why, said) => act(promise, why, said).then(() => `${said}${then()}`);
    if (got.do === 'next') { next(); return `Next.${then()}`; }
    if (got.do === 'later') { next('later'); return `Later.${then()}`; }
    if (got.do === 'allow' || got.do === 'deny') {
      const i = env.item('permission', x.id);
      if (!i) return null;
      const on = !!env.voiceOn?.();
      if (voiceRefused({ spoken, on, risk: env.risk?.(i)?.word || null })) return on ? LOOK_SAID : OFF_SAID; // nothing is answered
      return run(env.answerAsk(i, got.do), got.do === 'allow' ? 'allowed' : 'denied', got.do === 'allow' ? 'Allowed.' : 'Denied.');
    }
    if (got.do === 'undo') {
      return act(C().undoAnswer(x.id, null).then((r) => { learned(r, x.id); return r; }), 'undone', 'Undone.')
        .then(() => (asking?.ask ? `Undone. ${asking.ask}` : asking?.aside ? `Undone. ${asking.aside} Say undo to put it back.` : `Undone.${then()}`));
    }
    if (got.do === 'start' && typeof C().startReady === 'function') {
      let reply = 'Started.'; // or the front door's own words: queued, and why
      return act(C().startReady(x.id).then((out) => { reply = out?.reply || reply; return out; }), 'started', () => reply).then(() => `${reply}${then()}`);
    }
    if (got.do === 'pick' || got.do === 'words') {
      const questions = x.kind === 'question' ? x.row.questions || [] : x.row.questions || [];
      const answer = got.do === 'pick' && questions.length === 1 ? { answers: { [questions[0].question]: got.option } } : { text: got.do === 'pick' ? got.option : got.words };
      return run(C().replyQuestion(x.id, answer), 'answered', 'Sent.');
    }
    return null;
  }

  function sayItem(x) {
    const r = x.row;
    if (x.kind === 'question') return `${r.title || 'An agent'} asks: ${clip(r.text, 200)}`;
    if (x.kind === 'permission') return `${env.item('permission', x.id)?.title || 'An agent'} wants your permission: ${clip(r.what, 160)}`;
    if (x.kind === 'parked') return `${r.title || 'An agent'} asked while you were away: ${clip(r.text, 200)}`;
    if (x.kind === 'answered') return `The lead answered "${clip(r.question, 160)}" for you with ${clip(r.answer, 120)}. Say undo, or next.`;
    return `Ready to start: ${clip(r.title, 160)}. Say start it, or later.`;
  }

  return {
    open, close, heard,
    get isOpen() { return !!el; },
    count: () => now().length,
    refresh: draw,
  };
}
