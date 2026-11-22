// A morning briefing out loud (docs/connect.md, "A morning briefing out loud"). The first time you open the building
// each day, once today's plan is made (the daily cycle, day.js) and before the evening close, the receptionist says in
// a few sentences what the night shift finished overnight and what of it is proven (night.js), then today's plan floor
// by floor, and asks "Approve the day?". "Yes" approves it, "change" and what to change changes it (and she asks
// again), "not now" leaves it. She says it out loud only while this device's voice is on and the browser lets the page
// make sound; otherwise the same words are a card at the top of Needs you, with the same answers as buttons. Once a day
// on each device: the day it was given is kept in this browser. With the daily cycle off and the night shift on, she
// says how the night went.
//
// Your own company's day and night come through control (on this computer, or a paired phone that may control agents).
// The made-up company's are made up, and the briefing says so: approving or changing its day changes only the page.
//
// The words are plain functions, so tests/test_morning.py runs them under Node. createMorning(env) takes:
//   company()       the company's name, for what this browser remembers
//   day()           today's day as day-page.js has it (its now()), or null
//   night()         the night as night.js has it (its now()), or null
//   known()         whether both have been read, so that null means switched off rather than not read yet
//   switchOn()      the "morning" switch: true or false; null where it can't be read (a phone, the sample), which counts
//                   as on; undefined while it hasn't been read yet
//   approve()       approves the whole day, as its plan card does: what to say, or a promise of it
//   change(words)   changes the plan in words, as its plan card does: what to say, or a promise of it
//   speakable()     whether the receptionist may say it out loud now: the voice on, sound allowed, Talk on, and nothing
//                   in the way (the walk, the tour)
//   speak(again)    puts you with the receptionist, whose greeting is greeting() and then unasked(); gives whether it
//                   did. again: from the card's "Say it out loud", so she greets you even if you talked before
//   voiceOn()       whether the card may offer "Say it out loud" (the voice on, Talk on)
//   ready()         whether her voice can be heard now (its server is ready)
//   changed()       draw the page again
//   done(promise)   optional: the page's own note for what came of a button
//   storage         optional: where the day it was given is kept (this browser's localStorage unless given)
//   now()           optional: the time, in seconds

import { icon } from './icons.js';
import { dayIntent, floorIn, planCount, planLines } from './day.js';

const CSS = new URL('./morning.css', import.meta.url).href;
const KEY = 'arnheim-morning'; // the day it was given on this device, and how: { date, how: 'said' | 'shown' | 'done' }
const WAIT = 30; // seconds: a voice not ready by then has the rest shown in Talk anyway
const ASKING = 10 * 60; // seconds "Approve the day?" waits for your word
const SAMPLE = 'This company is made up, and so is its morning: nothing real ran, and approving starts nothing.';

const pad = (n) => String(n).padStart(2, '0');
export const dateOf = (now) => { const d = new Date(now * 1000); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const at = (clock, now) => { const d = new Date(now * 1000); const [hh, mm] = String(clock || '00:00').split(':'); d.setHours(Number(hh) || 0, Number(mm) || 0, 0, 0); return d.getTime() / 1000; };
const join = (list) => (list.length < 2 ? list.join('') : `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}`);
const quoted = (text) => `"${String(text || '').replace(/"/g, "'")}"`;
const lowerFirst = (text) => String(text || '').replace(/^[A-Z](?=[a-z])/, (c) => c.toLowerCase());
const then = (got, fn, fail = (error) => error.message) => (got && typeof got.then === 'function' ? got.then(fn, fail) : fn(got));

/* ---------- the words ---------- */

export function helloOf(now) {
  const hr = new Date(now * 1000).getHours();
  return hr >= 5 && hr < 12 ? 'Good morning' : hr >= 12 && hr < 18 ? 'Good afternoon' : hr >= 18 && hr < 23 ? 'Good evening' : 'Hello';
}

// Whether a night's report is last night's: made in the last 18 hours, or (the made-up one, which has no time) for the
// night before today.
export function freshReport(report, now) {
  if (!report) return false;
  if (report.at) return now - Number(report.at) < 18 * 3600;
  const d = new Date(now * 1000);
  d.setDate(d.getDate() - 1);
  return report.night === dateOf(d.getTime() / 1000);
}

// What the night shift did, in a sentence or two: its report's line, and what of it is proven. With no report of its
// own to read, the plan's line about the night (connect/night.py's morning_line), or null.
export function nightSaid(night, day, now) {
  const r = night?.report;
  if (r && !night.quiet_now && freshReport(r, now)) {
    const proven = (r.items || []).filter((i) => i && i.state === 'done' && i.proof?.state === 'proven');
    const named = proven.slice(0, 3).map((i) => `${quoted(i.title)} on ${i.label}`);
    return [`From the night shift: ${lowerFirst(r.words)}`,
      named.length ? `Proven: ${join(named)}${proven.length > 3 ? `, and ${proven.length - 3} more` : ''}.` : ''].filter(Boolean).join(' ');
  }
  return day?.night ? String(day.night) : null;
}

// The briefing in parts: { hello, sample, night, plan, floors, approved, ask }. plan is the plan's first line and floors
// a line for each floor; approved says the plan is approved already; ask is true while there is a plan to approve.
export function morningParts({ day = null, night = null, now = Date.now() / 1000 } = {}) {
  const lines = day?.made ? planLines(day) : null;
  const items = day?.made ? planCount(day).items : 0;
  return {
    hello: helloOf(now),
    sample: !!(day?.sample || night?.sample),
    night: nightSaid(night, day, now),
    plan: lines ? lines.head : null,
    floors: lines ? lines.floors : [],
    approved: items > 0 && day.approved ? "It's approved, and the work goes one thing at a time on each floor." : null,
    ask: items > 0 && !day.approved,
  };
}

// The briefing as one string, as the receptionist says it and the card shows it.
export function sayMorning(parts, { hello = true } = {}) {
  return [hello && `${parts.hello}.`, parts.sample && SAMPLE, parts.night, parts.plan, ...(parts.floors || []), parts.approved,
    parts.ask && 'Approve the day?'].filter(Boolean).join(' ');
}

// Whether the briefing is due now: 'day' (today's plan, and the night's report if there is one) or 'night' (the
// night's alone, with the daily cycle off), or null. given: the date it was last given on this device. on: the switch
// (undefined while it hasn't been read). known: whether the day and the night have been read.
export function morningDue(given = {}) {
  const { day = null, night = null, now = Date.now() / 1000, known = true } = given;
  const on = 'on' in given ? given.on : true;
  if (on === false || on === undefined || !known) return null;
  const today = dateOf(now);
  if (given.given === today) return null;
  if (day) {
    if (!day.made || (day.date && day.date !== today)) return null;
    if (now < at(day.plan_at || '09:00', now) || (day.close_at && now >= at(day.close_at, now))) return null;
    return planCount(day).items > 0 || nightSaid(night, day, now) ? 'day' : null;
  }
  const r = night?.report;
  return r && !r.seen && !night.quiet_now && freshReport(r, now) ? 'night' : null;
}

// Your answer to "Approve the day?": { kind: 'yes' | 'later' | 'which' } or { kind: 'change', words }, or null for
// anything else. A floor named ("approve Lantern's plan") is left to the daily cycle's own words (day-page.js). Only a
// clear yes approves: a bare "okay", "fine" or "sure" is as often an answer to something else, so it is left alone.
const LEAD_IN = /^(?:(?:ok|okay|right|so|well|um|erm|hmm)[,.!]?\s+)+/i;
const YES = /^(?:yes|yeah|yep|yup|go ahead|go for it|do it|please do|let's go|sounds good|looks good|approved?(?:\s+(?:it|that|the day|the plan|today's plan|all of it|the lot))?)(?:[,\s]+(?:please|thanks|thank you|go ahead))*[.!]*$/i;
const LATER = /^(?:not now|not yet|not today|later|maybe later|no|nope|no thanks|no thank you|leave it|leave it for now|skip it|nothing yet|hold off)\b(?![,\s]+(?:drop|remove|skip|cut|add|also|do|put|move|start|change)\b)/i;
const CHANGE = /^(?:(?:no|yes|yeah)[,.!]?\s+)?(?:please\s+)?(?:change|i(?:'d| would) like to change|i want to change|let's change|can we change|could you change)\b(?:\s+(?:it|that|this|the plan|today's plan|the day|something|one thing|a thing))?\s*[:,.-]?\s*(.*)$/i;

export function morningAnswer(text, plan = null) {
  const said = String(text || '').trim().replace(/\s+/g, ' ').replace(LEAD_IN, '');
  if (!said) return null;
  const m = CHANGE.exec(said);
  if (m) {
    const words = m[1].trim().replace(/[.!?]+$/, '');
    return words ? { kind: 'change', words } : { kind: 'which' };
  }
  const bare = said.replace(/^(?:no|yes|yeah)[,.!]?\s+/i, '');
  const intent = dayIntent(bare);
  if (intent?.kind === 'change') return { kind: 'change', words: bare };
  if (intent?.kind === 'approve') return floorIn(bare, plan) ? null : { kind: 'yes' };
  if (YES.test(said)) return { kind: 'yes' };
  if (LATER.test(said)) return { kind: 'later' };
  return null;
}

/* ---------- the page ---------- */

// Whether this browser lets the page make sound now, before anyone touches it: once someone has, or where its own
// policy says so, or else a silent probe (closed at once) that the browser starts or holds back.
export function soundAllowed() {
  try {
    if (navigator.userActivation?.hasBeenActive) return true;
    if (typeof navigator.getAutoplayPolicy === 'function') return navigator.getAutoplayPolicy('audiocontext') === 'allowed';
    const Context = window.AudioContext || window.webkitAudioContext;
    if (typeof Context !== 'function') return false;
    const probe = new Context();
    const running = probe.state === 'running';
    probe.close?.()?.catch?.(() => {});
    return running;
  } catch {
    return false;
  }
}

function styled() {
  if (typeof document === 'undefined' || document.querySelector('link[data-arnheim-morning]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS;
  link.dataset.arnheimMorning = '';
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
    else if (key === 'value') el.value = v;
    else el.setAttribute(key, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}
const btn = (label, onclick, cls = '', glyph = null, more = {}) => h(`button.btn${cls}`, { type: 'button', onclick, ...more }, glyph && icon(glyph, 15), label);
const sectHead = (glyph, text) => h('div.sect-head', icon(glyph, 18), h('h3.sect-title', text));

export function createMorning(env) {
  if (env.styled !== false) styled();
  const now = () => (env.now ? env.now() : Date.now() / 1000);
  const ask = (name, ...args) => { try { return env[name]?.(...args); } catch { return undefined; } };
  const storage = () => { if (env.storage !== undefined) return env.storage; try { return window.localStorage; } catch { return null; } };
  const key = () => { const c = String(ask('company') || ''); return c ? `${KEY}:${c}` : KEY; };
  let memo = null; // the day it was given, as this page knows it (all there is in a private window)
  let toSay = null; // { words, at }: what the receptionist is to say once her voice can be heard
  let asking = 0; // when she asked "Approve the day?", while it waits for your word
  let note = ''; // what came of a change made on the card
  let busy = false;
  let timer = 0;

  function stored() {
    let got = null;
    try { got = JSON.parse(storage()?.getItem(key()) || 'null'); } catch { got = null; }
    return got && typeof got === 'object' && typeof got.date === 'string' ? got : null;
  }
  function kept() {
    const s = stored();
    if (!memo || !s) return memo || s;
    return s.date > memo.date ? s : memo;
  }
  function keep(how, t = now()) {
    memo = { date: dateOf(t), how };
    try { storage()?.setItem(key(), JSON.stringify(memo)); } catch { /* a private window: once while this page is open */ }
  }

  const read = () => ({ day: ask('day') || null, night: ask('night') || null });
  function due(t = now()) {
    if (memo?.date === dateOf(t)) return null; // given already from this page
    const s = env.switchOn ? ask('switchOn') : null;
    if (s === undefined) return null; // not read yet
    const known = env.known ? !!ask('known') : true;
    return morningDue({ ...read(), now: t, given: kept()?.date || null, on: s === null ? true : s, known });
  }
  const partsNow = (t = now()) => morningParts({ ...read(), now: t });
  const visible = () => (env.visible ? !!ask('visible') : typeof document === 'undefined' || document.visibilityState !== 'hidden');

  // The receptionist says it: you are put with her, and her greeting (or, once her voice can be heard, what she says
  // unasked) is the briefing. Gives whether she did.
  function sayIt(t = now(), again = false) {
    const parts = partsNow(t);
    toSay = { words: sayMorning(parts, { hello: false }), at: t, ask: parts.ask };
    if (!ask('speak', again)) { toSay = null; return false; }
    keep('said', t);
    return true;
  }
  function told(t) {
    const w = toSay;
    toSay = null;
    if (w.ask) asking = t;
    return w.words;
  }

  // Looked at every few seconds, and as the page comes back into view: the briefing, once it is due, out loud or as
  // the card. Gives 'said', 'shown' or null.
  function check() {
    const t = now();
    if (!due(t) || !visible()) return null;
    let how = ask('speakable') ? 'said' : 'shown';
    if (how === 'said' && !sayIt(t)) how = 'shown';
    if (how === 'shown') keep('shown', t);
    ask('changed');
    return how;
  }

  // Her greeting while she has the briefing to say: all of it when her voice can be heard now; otherwise just hello,
  // with the rest said as soon as it can be heard (unasked).
  function greeting() {
    if (!toSay) return null;
    const t = now();
    const hello = `${helloOf(t)}.`;
    return ask('ready') ? `${hello} ${told(t)}` : hello;
  }
  function unasked() {
    if (!toSay) return null;
    const t = now();
    if (!ask('ready') && t - toSay.at < WAIT) return null;
    return told(t);
  }

  // What she says to your answer while "Approve the day?" waits for it: a string or a promise of one, or null for
  // anything else (the question ends, and the words are answered as usual).
  function heard(text) {
    if (!asking) return null;
    const t = now();
    if (t - asking > ASKING) { asking = 0; return null; }
    const { day } = read();
    const a = morningAnswer(text, day?.plan);
    if (!a) { asking = 0; return null; }
    if (a.kind === 'which') {
      const floor = (day?.plan || []).find((f) => (f.items || []).some((i) => i && i.state !== 'dropped'))?.label || 'a floor';
      return `What should change? Say it like "drop the second one on ${floor}", "add: tidy the README on ${floor}" or "do the third one first on ${floor}".`;
    }
    if (a.kind === 'later') {
      asking = 0;
      keep('done', t);
      return 'All right, it waits. Today\'s plan is on Needs you whenever you want it, or say "approve the day".';
    }
    if (a.kind === 'yes') {
      asking = 0;
      keep('done', t);
      return then(ask('approve'), (said) => String(said || 'Approved.'));
    }
    asking = t;
    return then(ask('change', a.words), (said) => `${String(said || '').trim()} Approve the day?`.trim(), (error) => { asking = 0; return error.message; });
  }

  /* the card, when it isn't said out loud */

  function run(work, after = null) {
    busy = true;
    ask('changed');
    Promise.resolve(work).then((said) => { note = String(said || ''); if (after) after(note); }, (error) => { note = error.message; })
      .finally(() => { busy = false; ask('changed'); });
  }
  function finish(said) {
    note = '';
    if (env.done && said) ask('done', Promise.resolve(said));
  }
  function approveIt() {
    asking = 0;
    run(ask('approve'), (said) => { keep('done'); finish(said); });
  }
  function notNow(words) {
    asking = 0;
    keep('done');
    finish(words);
    ask('changed');
  }
  function outLoud() {
    if (sayIt(now(), true)) ask('changed');
    else { note = 'Talk is switched off or the walk is open, so she can\'t say it now. The words are all here.'; ask('changed'); }
  }

  function card(p) {
    const change = (event) => {
      event.preventDefault();
      const input = event.currentTarget.elements.words;
      const words = input.value.trim();
      if (!words) return;
      input.value = '';
      input.blur(); // the page holds back drawing while you type in it: what came of it shows at once
      run(ask('change', words));
    };
    return h('section.panel-card.morning-card', { 'aria-label': 'This morning' },
      sectHead('sun', 'This morning'),
      h('p.morning-hello', h('strong', `${p.hello}.`), p.sample ? ` ${SAMPLE}` : ''),
      p.night && h('p.morning-night', p.night),
      p.plan && h('p.morning-plan', p.plan),
      p.floors.length > 0 && h('ul.morning-floors', p.floors.map((line) => h('li', line))),
      p.approved && h('p.morning-plan', p.approved),
      p.ask && h('p.morning-ask', h('strong', 'Approve the day?')),
      note && h('p.small.note', { role: 'status' }, note),
      h('div.control-row.morning-do',
        p.ask && btn('Approve the day', approveIt, '.primary', 'check', { disabled: busy }),
        p.ask ? btn('Not now', () => notNow('Not now: today\'s plan waits below, under Today\'s plan, whenever you want it.'), '.quiet', null, { disabled: busy })
          : btn('Got it', () => notNow(''), '.quiet', 'check', { disabled: busy }),
        ask('voiceOn') && btn('Say it out loud', outLoud, '.quiet', 'mic', { disabled: busy })),
      p.ask && h('form.control-say.morning-change', { onsubmit: change },
        h('input', { name: 'words', maxlength: 2000, autocomplete: 'off', placeholder: 'Change it: drop the second one on a floor, or add: tidy the README',
          'aria-label': "What to change in today's plan" }),
        h('button.btn', { type: 'submit', disabled: busy }, 'Change')));
  }

  return {
    start() {
      check();
      timer = setInterval(check, env.every || 2000);
      if (typeof document !== 'undefined') document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
    },
    stop: () => clearInterval(timer),
    check,
    due: () => due(),
    words: () => sayMorning(partsNow()),
    // Needs you: the card, while it was shown and not yet answered today, until the evening close.
    home() {
      const t = now();
      const k = kept();
      if (!k || k.date !== dateOf(t) || k.how !== 'shown') return null;
      const { day } = read();
      if (day?.close_at && t >= at(day.close_at, t)) return null;
      const p = partsNow(t);
      return p.night || p.plan ? card(p) : null;
    },
    greeting,
    unasked,
    heard,
    asking: () => !!asking,
    // Something else took the conversation (office hours' sitting): "Approve the day?" stops waiting, so a "yes" meant
    // for that is never taken as approving the day. Today's plan stays on Needs you.
    drop() { asking = 0; },
  };
}
