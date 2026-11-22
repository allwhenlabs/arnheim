// The night shift on the page (connect/night.py; docs/connect.md, "The night shift"). Your Claude Code and Codex
// allowances start again on a timer, and what you don't use is lost. During your quiet hours the night shift runs work
// you approved for it (a ready task ticked Tonight, the day's approved plan) on allowance that would otherwise go
// unused. In the morning, its report on Needs you: "4 things finished overnight, 3 proven, 1 not", each with its proof,
// its Show me card and Undo. Activity has what it would run tonight and why; Settings, under its switch, the quiet hours
// and the share; the front door's cards a Tonight tick; a desktop alert says how the night went when the page next
// opens; and the receptionist answers "how did the night go?" and "what's on tonight?".
//
// Your own company's night comes through control: on this computer, or a paired phone that may control agents. The
// made-up company's comes from sample/night.json, says it is made up, and changes only on this page. While the night
// shift is switched off, the page shows nothing of it.
//
// The words are plain functions, so tests/test_night_shift.py runs them under Node. createNight(env) takes:
//   control         control.js's
//   where()         'here' (this computer), 'phone' (a paired phone allowed to control agents), 'sample' or 'none'
//   alerts          alerts.js's, for the desktop alert
//   changed()       draw the page again
//   go(href)        go to a place on the page, when the alert is clicked
//   href(key)       a conversation's page, where its Show me card is, or null
//   sampleUrl()     where the made-up night is

import { icon } from './icons.js';

const CSS = new URL('./night.css', import.meta.url).href;
const TOLD = 'arnheim-night-told'; // this browser's last report alerted, so each comes once

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

/* ---------- the words ---------- */

// What a question is about: 'report' for how last night went, 'tonight' for what it would run, or null.
const ASKED = /^(?:so\s+|and\s+|hey[,\s]+)?(?:what|what's|whats|how|how's|hows|did|tell me|show me|give me|any news)\b/i;
export function nightIntent(text) {
  const said = String(text || '').trim();
  if (!ASKED.test(said)) return null;
  if (/\b(?:overnight|last night|in the night|the night go|the night went|did the night shift|the night shift's report|the night's report)\b/i.test(said)
    || /\bhow (?:did|was) (?:the |last )?night\b/i.test(said)) return 'report';
  if (/\b(?:tonight|the night shift)\b/i.test(said)) return 'tonight';
  return null;
}

// An item's chip: its word and the mood it shows in.
export function itemMood(i) {
  if (i?.state === 'undone') return 'quiet';
  if (i?.state === 'working') return 'working';
  if (i?.state === 'braked' || i?.state === 'failed' || i?.state === 'stopped') return 'needs';
  return i?.proof?.state === 'proven' ? 'ok' : i?.proof?.state === 'failed' ? 'failed' : 'quiet';
}
export const itemWord = (i) => (i?.state === 'undone' ? 'Undone' : i?.state === 'done' ? (i.proof?.word || 'Finished') : i?.word || 'Finished');
const quoted = (text) => `"${String(text || '').replace(/"/g, "'")}"`; // their words stay one quote, whatever they hold
const lowerFirst = (text) => String(text || '').replace(/^[A-Z](?=[a-z])/, (c) => c.toLowerCase());

// How a run ended, undone or not (connect/night.py's how_it_ended): one stopped before the limit and then undone
// never counts as finished.
const howItEnded = (i) => (i.state === 'undone' ? i.ended || 'done' : i.state);

// The report in one line, as connect/night.py's report_words has it.
export function reportWords(items, waiting = 0, said = '') {
  const list = Array.isArray(items) ? items : [];
  if (!list.length) return `Nothing ran overnight.${said ? ` ${said}` : ''}`;
  const finished = list.filter((i) => howItEnded(i) === 'done');
  const proven = finished.filter((i) => i.proof?.state === 'proven').length;
  const n = finished.length;
  let words = n ? `${plural(n, 'thing', 'things')} finished overnight, ${proven === n ? 'all proven.' : !proven ? 'none proven.' : `${proven} proven, ${n - proven} not.`}`
    : 'Nothing finished overnight.';
  const braked = list.filter((i) => howItEnded(i) === 'braked').length;
  const failed = list.filter((i) => ['failed', 'stopped'].includes(howItEnded(i))).length;
  const working = list.filter((i) => howItEnded(i) === 'working').length;
  if (braked) words += ` ${braked} stopped before the limit.`;
  if (failed) words += ` ${failed} ended without finishing.`;
  if (working) words += ` ${working} still at work.`;
  if (waiting) words += ` ${plural(waiting, 'thing waits', 'things wait')} for another night.`;
  return words;
}

// What the receptionist says about last night: the line, and the first few with their proof.
export function sayReport(report) {
  if (!report) return 'The night shift has no report yet: it reports the morning after a night it ran something.';
  const items = (report.items || []).slice(0, 3).map((i) => `${quoted(i.title)} on ${i.label}: ${itemWord(i).toLowerCase()}.`);
  return [report.sample ? 'This night is made up, like the rest of the company.' : '', report.words, ...items,
    (report.items || []).length > 3 ? `The rest are on Needs you.` : ''].filter(Boolean).join(' ');
}

// What it would run tonight, in words.
export function sayTonight(v) {
  if (!v) return 'The night shift is switched off.';
  const go = (v.queued || []).filter((e) => !e.why);
  const wait = (v.queued || []).filter((e) => e.why);
  const head = go.length
    ? `${plural(go.length, 'thing is', 'things are')} approved for tonight, from ${v.quiet?.from} to ${v.quiet?.to}: ${go.slice(0, 3).map((e) => `${quoted(e.title)} on ${e.label}`).join('; ')}.`
    : `Nothing is approved for tonight. Tick Tonight on a ready task, or say "do it tonight".`;
  return [v.sample ? 'Made up, like the rest of the company.' : '', head,
    wait.length ? `${plural(wait.length, 'waits', 'wait')} for you: ${lowerFirst(wait[0].why)}` : '', v.window?.words || ''].filter(Boolean).join(' ');
}

// The desktop alert for a report: { title, body, tag }.
export const reportAlert = (report) => ({ title: 'The night shift', body: String(report?.words || ''), tag: `arnheim-${report?.id || 'night'}` });

// The made-up night: last night's report, what would run tonight, and the window, all said to be made up.
export function sampleNight(raw, now = Date.now() / 1000) {
  const d = new Date(now * 1000);
  d.setDate(d.getDate() - 1);
  const night = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  const items = (Array.isArray(raw?.report?.items) ? raw.report.items : []).map((i, n) => ({ ...i, id: i.id || `n-sample${n}`, sample: true }));
  const queued = Array.isArray(raw?.queued) ? raw.queued : [];
  const waiting = queued.filter((e) => !e.why).length;
  return {
    on: true, sample: true, quiet: raw?.quiet || { from: '23:00', to: '07:00' }, share: raw?.share || 80, margin: raw?.margin || 10,
    quiet_now: false, from: raw?.quiet?.from || '23:00', back: raw?.quiet?.to || '07:00',
    window: raw?.window || { known: false, open: false, words: '' }, queued, ticked: queued.filter((e) => e.kind === 'ready').map((e) => e.id),
    ran: items, said: null,
    report: { night, id: `night-${night}`, sample: true, seen: false, items, waiting, words: reportWords(items, waiting) },
  };
}

/* ---------- the page ---------- */

function styled() {
  if (typeof document === 'undefined' || document.querySelector('link[data-arnheim-night]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS;
  link.dataset.arnheimNight = '';
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
const store = () => { try { return window.localStorage; } catch { return null; } };

export function createNight(env) {
  if (env.styled !== false) styled();
  const control = env.control;
  const where = () => { try { return env.where(); } catch { return 'none'; } };
  let sample = null; // the made-up night, once read
  let sampleAsked = false;
  const sampleTicks = new Set(); // the made-up company's Tonight ticks: this tab only
  let note = ''; // what came of the last thing done here
  let settingsNote = '';
  let busy = false;

  function ensure() {
    if (where() !== 'sample' || sampleAsked) return;
    sampleAsked = true;
    fetch(env.sampleUrl(), { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((raw) => {
      if (raw) { sample = sampleNight(raw); env.changed(); }
    }).catch(() => { /* no made-up night: the sample shows none */ });
  }

  // The night as it is now, or null where there is none to show (switched off, control off, or not read yet).
  function current() {
    const w = where();
    if (w === 'sample') return sample;
    if ((w !== 'here' && w !== 'phone') || !control.on) return null;
    return control.nightNow?.() || null;
  }

  // The desktop alert, once for each report, when the page next opens on this computer.
  function alertFor(v) {
    const r = v?.report;
    if (!r || r.seen || where() !== 'here' || !env.alerts?.on?.()) return;
    const kept = store();
    let told = null;
    try { told = kept?.getItem(TOLD); } catch { /* a private window: it may come again */ }
    if (told === r.id) return;
    try { kept?.setItem(TOLD, r.id); } catch { /* as above */ }
    env.alerts.notify(reportAlert(r), () => env.go('#/'));
  }

  // What of the night shows on the page: when it changes (a tick, a run, the morning's report, Got it, Undo, the
  // settings), the page is drawn again. The page's own watch (demo.js) follows only the agents and their questions, so a
  // Tonight tick used to stay unticked on the card until something else changed.
  const shown = (v) => JSON.stringify(v && [v.quiet, v.share, v.quiet_now, v.ticked, v.said, v.window?.known, v.window?.open,
    (v.ran || []).map((r) => [r.id, r.state, r.undo, r.proof?.state]), (v.queued || []).map((q) => [q.id, q.why]),
    v.report && [v.report.id, v.report.seen, v.report.words, (v.report.items || []).map((i) => [i.id, i.state, i.undo])]]);
  let drawn = null;

  function start() {
    ensure();
    control.watch?.((state) => {
      const v = state?.night || null;
      if (v) alertFor(v);
      const now = shown(v);
      if (drawn !== null && now !== drawn) env.changed();
      drawn = now;
    });
  }

  function run(work) {
    busy = true;
    env.changed();
    Promise.resolve(work).then((said) => { note = String(said || ''); }, (error) => { note = error.message; })
      .finally(() => { busy = false; env.changed(); });
  }

  const madeUp = (v) => !!v?.sample;
  function undo(v, i) {
    if (madeUp(v)) {
      i.state = 'undone';
      i.undo = false;
      return 'This night is made up, so nothing was put back. With your own company, its files go back as they were before it ran.';
    }
    return control.undoNight(i.id).then((r) => r.said);
  }
  function seen(v) {
    if (madeUp(v)) { v.report.seen = true; return ''; }
    return control.setNight({ seen: v.report.id }).then(() => '');
  }

  function item(v, i) {
    const href = i.key && env.href ? env.href(i.key) : null;
    return h('li.night-item',
      h('div.night-top',
        h('span.night-title', i.title),
        h(`span.state.night-chip.k-${itemMood(i)}`, itemWord(i))),
      h('span.small.muted', [i.label, i.agent].filter(Boolean).join(', ')),
      i.proof?.line && i.state !== 'working' && h('p.small.night-line', i.proof.line),
      i.proof?.tail && h('p.small.muted.night-tail', i.proof.tail),
      i.why && h('p.small.night-why', i.why),
      (i.show || i.undo) && h('div.control-row.night-do',
        i.show && (madeUp(v) ? btn('Show me', () => run('This night is made up, so there are no pictures. With your own company, its Show me card is on its conversation\'s page.'), '.quiet')
          : href && h('a.btn.quiet', { href }, 'Show me')),
        i.undo && btn('Undo', () => run(undo(v, i)), '.quiet', 'rotate-ccw', { disabled: busy })),
      i.undo && i.undo_note && h('p.small.muted', i.undo_note),
      !i.undo && i.no_undo && i.state !== 'undone' && h('p.small.muted', i.no_undo));
  }

  function reportCard(v) {
    const r = v.report;
    return h('section.panel-card.night-card', { 'aria-label': 'The night shift' },
      sectHead('moon', 'The night shift'),
      h('p.night-words', h('strong', r.words)),
      r.sample && h('p.small.muted', 'A made-up night, like the rest of the sample. With your own company, this is what ran while you were away.'),
      r.items?.length > 0 && h('ul.night-list', r.items.map((i) => item(v, i))),
      !r.items?.length && r.said && h('p.small.muted', r.said),
      note && h('p.small.note', { role: 'status' }, note),
      h('div.control-row.night-done', btn('Got it', () => run(seen(v)), '.primary', 'check', { disabled: busy })));
  }

  // Activity: what it would run tonight, the window and why, and the last runs.
  function tonightCard(v) {
    const go = (v.queued || []).filter((e) => !e.why);
    const wait = (v.queued || []).filter((e) => e.why);
    return h('section.panel-card.night-card', { 'aria-label': 'The night shift tonight' },
      sectHead('moon', 'The night shift'),
      h('p', v.quiet_now ? `Quiet hours now, until ${v.back}.` : `Quiet hours ${v.quiet.from} to ${v.quiet.to}.`,
        ` It may use ${v.share}% of what would go unused, keeping ${v.margin} points of each limit in hand.`),
      v.window?.words && h('p.small.muted.night-window', v.window.words),
      h('h4.night-sub', go.length ? `Approved for tonight (${go.length})` : 'Approved for tonight'),
      go.length ? h('ul.night-plain', go.map((e) => h('li', h('span.night-title', e.title), h('span.small.muted', `${e.label}, ${e.agent}${e.kind === 'day' ? ', from the plan' : ''}`))))
        : h('p.small.muted', 'Nothing yet. Tick Tonight on a ready task, or say "do it tonight" to the receptionist.'),
      wait.length > 0 && [h('h4.night-sub', `Waiting for you (${wait.length})`),
        h('ul.night-plain', wait.map((e) => h('li', h('span.night-title', e.title), h('span.small.muted', `${e.label}: ${e.why}`))))],
      v.said && h('p.small.night-said', v.said),
      v.ran?.length > 0 && [h('h4.night-sub', v.quiet_now ? 'Tonight so far' : 'Last night'), h('ul.night-list', v.ran.map((i) => item(v, i)))],
      v.sample && h('p.small.muted', 'Made up, like the rest of the sample: nothing real runs.'));
  }

  // Settings, under its switch: the quiet hours and the share.
  function settings() {
    if (where() !== 'here') return null;
    if (!control.on) return h('p.small.muted.night-times', 'Its quiet hours can be set while Answer agents from the building is on.');
    const v = control.nightNow?.();
    if (!v) return null;
    const save = (event) => {
      event.preventDefault();
      const form = event.currentTarget.elements;
      control.setNight({ quiet: { from: form.from.value, to: form.to.value }, share: Number(form.share.value) })
        .then((r) => { settingsNote = r.said; }, (error) => { settingsNote = error.message; }).finally(() => env.changed());
    };
    return h('form.night-times', { onsubmit: save },
      h('label.small', 'Quiet from', h('input', { type: 'time', name: 'from', value: v.quiet.from, required: true })),
      h('label.small', 'until', h('input', { type: 'time', name: 'to', value: v.quiet.to, required: true })),
      h('label.small', 'Use up to', h('input', { type: 'number', name: 'share', min: 10, max: 100, step: 5, value: v.share, required: true }), '% of what would go unused'),
      h('button.btn.quiet', { type: 'submit' }, 'Save'),
      settingsNote && h('span.small', { role: 'status' }, settingsNote));
  }

  // Ticking a ready task for tonight, or taking the tick off. Gives what to say.
  function tick(id, on = true) {
    const v = current();
    if (!v) return Promise.resolve('The night shift is switched off. Switch it on in Settings, under Switches.');
    if (madeUp(v)) {
      if (on) sampleTicks.add(id); else sampleTicks.delete(id);
      env.changed();
      return Promise.resolve(on ? 'Ticked for tonight. This company is made up, so nothing real runs.' : 'Not tonight: it stays ready.');
    }
    return control.tickTonight(id, on).then((r) => r.said);
  }
  const ticked = (id) => { const v = current(); return !!v && (madeUp(v) ? sampleTicks.has(id) : (v.ticked || []).includes(id)); };

  return {
    start,
    on: () => !!current(),
    // Needs you: the morning's report, until you've seen it.
    home() {
      ensure();
      const v = current();
      return v?.report && !v.report.seen ? reportCard(v) : null;
    },
    activity() {
      ensure();
      const v = current();
      return v ? tonightCard(v) : null;
    },
    settings,
    tick,
    ticked,
    // The front door's card: a Tonight tick for a ready task, while the night shift is on.
    tonightButton(task) {
      const v = current();
      if (!v || !task?.id || task.state === 'started') return null;
      const on = ticked(task.id);
      const go = () => {
        const said = Promise.resolve(tick(task.id, !on));
        if (env.done) env.done(said, (words) => words); // the page's own note, as for any button
        else said.then((words) => { note = words; env.changed(); });
      };
      return btn(on ? 'Tonight: on' : 'Tonight', go, on ? '.quiet.night-tick.on' : '.quiet.night-tick', 'moon',
        { 'aria-pressed': on ? 'true' : 'false', title: 'Run it on the night shift, if allowance would otherwise go unused' });
    },
    // What the receptionist says to words about the night: a string or a promise of one, or null.
    heard(text) {
      const intent = nightIntent(text);
      if (!intent) return null;
      ensure();
      const v = current();
      if (!v) return null;
      if (intent === 'report') return v.report ? sayReport(v.report) : `Nothing to report yet. ${sayTonight(v)}`;
      return sayTonight(v);
    },
  };
}
