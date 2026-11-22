// The week on one page (connect/week.py; docs/connect.md, "The week on one page"). On Sundays it comes up on Needs you,
// and Activity has it any time: for each floor, what finished and was proven, what was undone, and what waits for you
// now; then where the week's allowance went (the daily plans, the night shift, work Show me sent back with Not quite,
// and your own conversations) as shares of what Arnheim counted. A day with no readings is said plainly. The
// receptionist answers "how did the week go?" from it.
//
// Your own company's week comes through control (`week`): on this computer, or a paired phone that may control agents.
// It only reads. The made-up company's comes from sample/week.json ("page"), and says it is made up. With its switch
// off, or control off, the page shows nothing of it, and the weekly report (weekly.js) answers as before.
//
// The words are plain functions, so tests/test_week.py runs them under Node. createWeek(env) takes:
//   control         control.js's
//   where()         'here' (this computer), 'phone' (a paired phone allowed to control agents), 'sample' or 'none'
//   changed()       draw the page again
//   href(project)   a floor's place on the page, or null
//   switchOn(name)  the switch as Settings has it, or null when it isn't known (then it is on, its default)
//   sampleUrl()     where the made-up week is

import { icon } from './icons.js';
import { tokensSaid } from './budget.js';
import { WEEKLY_ASKED } from './weekly.js';

const CSS = new URL('./week.css', import.meta.url).href;
const SEEN = 'arnheim-week-seen'; // this browser's last week put away on Needs you, so a Sunday's comes once
const EVERY = 60000; // ms: the week is read again at most this often
const DAY_NAMES = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
export const PARTS = [['plans', 'the daily plans', 'The daily plans'], ['night', 'the night shift', 'The night shift'],
  ['show', 'work Show me sent back', 'Show me, sent back'], ['own', 'your own conversations', 'Your own conversations']];

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const andList = (words, last = 'and') => {
  const list = words.filter(Boolean);
  return list.length < 2 ? list.join('') : `${list.slice(0, -1).join(', ')} ${last} ${list[list.length - 1]}`;
};

/* ---------- the words ---------- */

// "How did the week go?", "where did the allowance go?", "what did this week cost?"
export const WEEK_ASKED = /\b(?:where (?:did|has|does) (?:the|my|our|this week's) (?:allowance|usage|use|tokens?|plan) go|what did (?:the|this|last) week cost|(?:the )?week on one page|how much (?:did|has) (?:the night shift|the plans?|show me) (?:use|used|spend|spent))\b/i;
const SPENT_ASKED = /\b(?:allowance|usage|tokens?|cost|spend|spent)\b/i;
export const weekIntent = (text) => WEEKLY_ASKED.test(String(text || '')) || WEEK_ASKED.test(String(text || ''));

// A floor's week in a line, as connect/week.py's floor_words has it.
export function floorWords(f) {
  const n = f.finished || 0;
  const p = f.proven || 0;
  const x = f.failed || 0;
  const u = n - p - x;
  let words;
  if (!n) words = 'Nothing finished.';
  else if (p === n) words = `${n} finished, ${n > 1 ? 'all ' : ''}proven.`;
  else if (!p && !x) words = `${n} finished, not checked.`;
  else words = `${n} finished: ${andList([p ? `${p} proven` : '', x ? `${x} not proven` : '', u ? `${u} not checked` : ''])}.`;
  if (f.undone) words += ` ${f.undone} undone.`;
  if (f.waits) words += ` ${plural(f.waits, 'thing waits', 'things wait')} for you.`;
  return words;
}

// Whole percentages that add up to 100: the largest remainders round up.
export function sharesOf(parts) {
  const whole = parts.reduce((t, [, n]) => t + n, 0);
  if (!whole) return Object.fromEntries(parts.map(([name]) => [name, 0]));
  const exact = parts.map(([name, n]) => [name, (100 * n) / whole]);
  const out = Object.fromEntries(exact.map(([name, v]) => [name, Math.floor(v)]));
  const short = 100 - Object.values(out).reduce((t, v) => t + v, 0);
  [...exact].sort((a, b) => (b[1] - Math.floor(b[1])) - (a[1] - Math.floor(a[1]))).slice(0, short).forEach(([name]) => { out[name] += 1; });
  return out;
}

export function missingWords(names) {
  if (!names.length) return '';
  if (names.length >= 7) return "No readings all week: the hook wrote nothing, so your own conversations aren't counted.";
  return `No readings ${andList(names, 'or')}, so your own conversations then aren't counted.`;
}

// Where the allowance went, in words, as connect/week.py's allowance_words has it.
export function allowanceWords(a) {
  const ranked = [...(a?.parts || [])].filter((p) => p.tokens).sort((x, y) => y.tokens - x.tokens);
  const said = a?.tokens
    ? `Of the ${tokensSaid(a.tokens)} new tokens counted this week: ${andList(ranked.map((p) => `${p.label} ${p.share}%`))}.`
    : "No spending was counted this week, so where the allowance went isn't known.";
  return `${said} ${allowanceMore(a)}`;
}
// What follows the shares: work sent back that couldn't be counted, Show me's pictures, and your plan's weekly limits.
function allowanceMore(a) {
  const unseen = (a?.sent_back || 0) - (a?.sent_counted || 0);
  return [unseen > 0 ? `What ${plural(unseen, 'piece', 'pieces')} of work sent back with Not quite spent couldn't be counted, so it is in your own conversations.` : '',
    "Show me's pictures are taken on this computer and use none of it.", ...(a?.limits || []).map((l) => l.words)].filter(Boolean).join(' ');
}

// The week's first line: "9 pieces of work finished, 6 proven. 1 undone. 4 things wait for you."
export function headWords(v) {
  const t = (k) => (v?.floors || []).reduce((n, f) => n + (f[k] || 0), 0);
  const n = t('finished');
  const p = t('proven');
  let said = n ? `${plural(n, 'piece of work', 'pieces of work')} finished, ${p === n ? 'all proven' : p ? `${p} proven` : 'none proven'}.`
    : 'Nothing finished this week, as far as the building knows.';
  if (t('undone')) said += ` ${t('undone')} undone.`;
  if (t('waits')) said += ` ${plural(t('waits'), 'thing waits', 'things wait')} for you.`;
  return said;
}

// What the receptionist says, as connect/week.py's week_words has it.
export function sayWeekPage(v) {
  if (!v) return '';
  const floors = v.floors || [];
  const n = floors.reduce((t, f) => t + (f.finished || 0), 0);
  const p = floors.reduce((t, f) => t + (f.proven || 0), 0);
  const u = floors.reduce((t, f) => t + (f.undone || 0), 0);
  const w = floors.reduce((t, f) => t + (f.waits || 0), 0);
  let said = n
    ? `This week, ${plural(n, 'piece of work', 'pieces of work')} finished on ${plural(floors.filter((f) => f.finished).length, 'floor', 'floors')}, ${p === n ? 'all proven.' : !p ? 'none proven.' : `${p} proven.`}`
    : 'Nothing finished this week, as far as the building knows.';
  if (u) said += ` ${u} undone.`;
  if (w) said += ` ${plural(w, 'thing waits', 'things wait')} for you.`;
  const busiest = [...floors].sort((a, b) => (b.finished - a.finished) || (b.proven - a.proven))[0];
  if (busiest?.finished) said += ` ${busiest.label}: ${busiest.line || floorWords(busiest)}`;
  const ranked = [...(v.allowance?.parts || [])].filter((x) => x.tokens).sort((a, b) => b.tokens - a.tokens);
  said += ranked.length ? ` The allowance went to ${andList(ranked.slice(0, 3).map((x) => `${x.label}, ${x.share}%`))}.` : ' No spending was counted.';
  if (v.missing) said += ` ${v.missing}`;
  return `${v.sample ? 'This week is made up, like the rest of the company. ' : ''}${said}`;
}

// The made-up week: sample/week.json's "page", with the days it has no readings for said as such.
export function sampleWeek(raw, now = Date.now() / 1000) {
  const page = raw?.page && typeof raw.page === 'object' ? raw.page : {};
  const today = new Date(now * 1000);
  const back = (n) => { const d = new Date(today); d.setDate(d.getDate() - n); return d; };
  const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const kept = new Set([0, ...(Array.isArray(raw?.days) ? raw.days : []).map((d) => Number(d?.back) || 0)]); // today is the page's own
  const days = [6, 5, 4, 3, 2, 1, 0].map((n) => ({ date: iso(back(n)), name: DAY_NAMES[back(n).getDay()], read: kept.has(n) }));
  const floors = (Array.isArray(page.floors) ? page.floors : []).map((f) => {
    const finished = Array.isArray(f.finished) ? f.finished : [];
    const row = {
      project: f.project, label: f.label || f.project,
      finished: finished.length, proven: finished.filter((i) => i.proof === 'proven').length, failed: finished.filter((i) => i.proof === 'failed').length,
      undone: (f.undone || []).length, waits: (f.waits || []).length,
      items: { finished, undone: Array.isArray(f.undone) ? f.undone : [], waits: Array.isArray(f.waits) ? f.waits : [] },
    };
    return { ...row, line: floorWords(row) };
  });
  const given = page.allowance && typeof page.allowance === 'object' ? page.allowance : {};
  const raws = PARTS.map(([name]) => [name, Number.isFinite(given[name]) && given[name] > 0 ? Math.round(given[name]) : 0]);
  const shares = sharesOf(raws);
  const total = raws.reduce((t, [, n]) => t + n, 0);
  const limits = (Array.isArray(page.limits) ? page.limits : []).map((l) => {
    const resets = new Date(today);
    resets.setDate(resets.getDate() + (Number(l.resets_in_days) || 0));
    return { source: l.source, used: l.used, words: `Made up: ${l.source} says ${Math.round(l.used)}% of its weekly limit is used, and it starts again on ${DAY_NAMES[resets.getDay()]}.` };
  });
  const allowance = {
    known: total > 0, tokens: total, sent_back: Number(given.sent_back) || 0, sent_counted: Number(given.sent_back) || 0, limits,
    parts: raws.map(([name, n]) => ({ name, label: PARTS.find((p) => p[0] === name)[1], tokens: n, share: shares[name] })),
  };
  allowance.words = allowanceWords(allowance);
  const v = {
    on: true, sample: true, id: `week-${iso(today)}`, from: days[0].date, to: days[6].date, sunday: today.getDay() === 0, days,
    missing: missingWords(days.filter((d) => !d.read).map((d) => d.name)), floors, allowance,
  };
  v.words = sayWeekPage(v);
  return v;
}

/* ---------- the page ---------- */

function styled() {
  if (typeof document === 'undefined' || document.querySelector('link[data-arnheim-week]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS;
  link.dataset.arnheimWeek = '';
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
const sectHead = (glyph, text) => h('div.sect-head', icon(glyph, 18), h('h3.sect-title', text));
const store = () => { try { return window.localStorage; } catch { return null; } };
const PROOF = { proven: ['Proven', 'ok'], failed: ['Not proven', 'failed'], unchecked: ['Not checked', 'quiet'] };
const HOW = { plan: 'from the plan', night: 'on the night shift', 'night shift': 'a night shift run', you: 'by you' };

export function createWeek(env) {
  if (env.styled !== false) styled();
  const where = () => { try { return env.where(); } catch { return 'none'; } };
  const switchedOn = () => { try { return env.switchOn?.('week') !== false; } catch { return true; } };
  let sample = null; // the made-up week, once read
  let sampleAsked = false;
  let real = null; // your own company's, as control last gave it
  let readAt = 0;
  let reading = false;
  let note = '';
  let putAway = ''; // this tab's, when the browser keeps nothing
  const opened = new Set(); // the floors whose lists are open, so the page drawn again keeps them open

  function ensure() {
    const w = where();
    if (w === 'sample') {
      if (sampleAsked) return;
      sampleAsked = true;
      fetch(env.sampleUrl(), { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((raw) => {
        if (raw?.page) { sample = sampleWeek(raw); env.changed(); }
      }).catch(() => { /* no made-up week: the sample shows none */ });
      return;
    }
    if ((w !== 'here' && w !== 'phone') || !env.control?.on || !env.control.week || reading || Date.now() - readAt < EVERY) return;
    reading = true;
    env.control.week().then((v) => { real = v?.on ? v : null; note = ''; }, (error) => { note = error.message; })
      .finally(() => { reading = false; readAt = Date.now(); env.changed(); });
  }

  // The week as it is now, or null where there is none to show (switched off, control off, or not read yet).
  function current() {
    const w = where();
    if (w === 'sample') return switchedOn() ? sample : null;
    if ((w !== 'here' && w !== 'phone') || !env.control?.on) return null;
    return real;
  }

  const seenId = () => { let got = null; try { got = store()?.getItem(SEEN); } catch { /* a private window */ } return got || putAway; };
  function seen(v) {
    putAway = v.id;
    try { store()?.setItem(SEEN, v.id); } catch { /* a private window: this tab remembers */ }
    env.changed();
  }

  function finishedItem(i) {
    const [word, mood] = PROOF[i.proof] || PROOF.unchecked;
    return h('li', h('div.week-item', h('span.week-title', i.title), h(`span.state.week-chip.k-${mood}`, word)),
      HOW[i.how] && h('span.small.muted', HOW[i.how]));
  }

  function floorItem(f) {
    const href = env.href ? env.href(f.project) : null;
    const items = f.items || {};
    const any = (items.finished || []).length + (items.undone || []).length + (items.waits || []).length;
    return h('li.week-floor',
      href ? h('a.week-name', { href }, f.label) : h('span.week-name', f.label),
      h('span.small', f.line || floorWords(f)),
      any > 0 && h('details.week-more',
        { open: opened.has(f.project), ontoggle: (event) => { if (event.currentTarget.open) opened.add(f.project); else opened.delete(f.project); } },
        h('summary', 'What finished, was undone and waits'),
        (items.finished || []).length > 0 && [h('h4.week-sub', 'Finished'), h('ul.week-list', items.finished.map(finishedItem))],
        (items.undone || []).length > 0 && [h('h4.week-sub', 'Undone'),
          h('ul.week-list', items.undone.map((u) => h('li', h('span.week-title', u.title), HOW[u.how] && h('span.small.muted', HOW[u.how]))))],
        (items.waits || []).length > 0 && [h('h4.week-sub', 'Waits for you'),
          h('ul.week-list', items.waits.map((x) => h('li', h('span.week-title', x.title), h('span.small.muted', x.why))))]));
  }

  function partItem(p) {
    const title = PARTS.find((x) => x[0] === p.name)?.[2] || p.label;
    return h('li.week-part',
      h('span.week-part-name', title),
      h('span.week-share', `${p.share}%`),
      h('meter.week-meter', { min: 0, max: 100, value: p.share, 'aria-label': `${title}: ${p.share}%` }),
      h('span.small.muted.week-part-tokens', p.tokens ? `${tokensSaid(p.tokens)} new tokens` : 'None counted'));
  }

  function card(v, home = false) {
    const a = v.allowance || {};
    return h('section.panel-card.week-card', { 'aria-label': 'This week', id: home ? null : 'week' },
      sectHead('calendar-days', 'This week'),
      h('p.week-words', h('strong', headWords(v))),
      v.sample && h('p.small.muted', 'A made-up week, like the rest of the sample. With your own company, this is what your agents did these seven days.'),
      (v.floors || []).length ? h('ul.week-floors', v.floors.map(floorItem))
        : h('p.small.muted', 'Nothing finished, was undone or waits on any floor this week.'),
      h('h4.week-sub', 'Where the allowance went'),
      a.known ? h('ul.week-parts', (a.parts || []).map(partItem)) : null,
      h('p.small.muted.week-note', a.known
        ? `Shares of the ${tokensSaid(a.tokens)} new tokens Arnheim counted, the same measure as a floor's budget. ${allowanceMore(a)}`
        : allowanceWords(a)),
      v.missing && h('p.small.week-missing', v.missing),
      note && h('p.small.note', { role: 'status' }, note),
      home && h('div.control-row.week-done', btn('Got it', () => seen(v), '.primary', 'check')));
  }

  return {
    on: () => !!current(),
    // Needs you, on Sundays: the week, until you've put it away.
    home() {
      ensure();
      const v = current();
      return v?.sunday && seenId() !== v.id ? card(v, true) : null;
    },
    // Activity, any time.
    activity() {
      ensure();
      const v = current();
      return v ? card(v) : null;
    },
    // What the receptionist says to words about the week: a string, or null for the weekly report to answer.
    heard(text) {
      if (!weekIntent(text)) return null;
      ensure();
      const v = current();
      if (!v) return null;
      // "where did the allowance go?" is answered with the shares first; "how did the week go?" with the whole week
      if (SPENT_ASKED.test(String(text))) return `${v.sample ? 'Made up, like the rest of the company. ' : ''}${allowanceWords(v.allowance)}${v.missing ? ` ${v.missing}` : ''}`;
      return sayWeekPage(v);
    },
  };
}
