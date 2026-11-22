// The daily cycle on the page (connect/day.py; docs/connect.md, "The daily cycle"). Today's plan on Needs you, each
// floor's part as its lead proposed it, with Approve the day, a floor at a time, and a box to change it in words; the
// evening close (what was proven, what is stuck and why, what needs you tomorrow, what today cost); both in Activity;
// the plan's and the close's times under its switch in Settings; a desktop alert when each is made; and what the
// receptionist and the leads say about it ("what's the plan?", "approve the day", "how did today go?").
//
// Your own company's day comes through control: on this computer, or a paired phone that may control agents. The
// made-up company's comes from sample/day.json, says it is made up, and changes only on this page. While the daily
// cycle is switched off, the page shows nothing of it, and the receptionist and the leads answer as before.
//
// createDay(env) takes:
//   control         control.js's
//   where()         'here' (this computer), 'phone' (a paired phone allowed to control agents), 'sample' or 'none'
//   switchOn(name)  whether one of this computer's switches is on, or null where it can't tell
//   alerts          alerts.js's, for desktop alerts on this computer
//   changed()       draw the page again
//   go(href)        go to a place on the page, when an alert is clicked
//   sampleUrl()     where the made-up day is

import { icon } from './icons.js';
import { closeAlert, dayIntent, floorIn, itemMood, itemWord, planAlert, planCount, sampleApprove, sampleChange, sampleDay, sayClose, sayPlan } from './day.js';

const CSS = new URL('./day.css', import.meta.url).href;
const BACKGROUND = 60000; // with desktop alerts on and the page hidden, the day is read this often, to alert

function styled() {
  if (typeof document === 'undefined' || document.querySelector('link[data-arnheim-day]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS;
  link.dataset.arnheimDay = '';
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
const clock = (t) => new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
const today = (hhmm) => { const d = new Date(); const [hh, mm] = String(hhmm || '00:00').split(':'); d.setHours(Number(hh) || 0, Number(mm) || 0, 0, 0); return d.getTime() / 1000; };
const live = (f) => (Array.isArray(f?.items) ? f.items.filter((i) => i && i.state !== 'dropped') : []);
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

export function createDay(env) {
  styled();
  const control = env.control;
  const where = () => { try { return env.where(); } catch { return 'none'; } };
  let sample = null; // the made-up day, once read
  let sampleAsked = false;
  let fresh = null; // the day as the last read in the background had it
  let note = ''; // what came of the last thing done here, shown on the card
  let busy = false;
  let timesNote = '';
  const told = { plan: null, close: null, primed: false };

  function ensure() {
    if (where() !== 'sample' || sampleAsked) return;
    sampleAsked = true;
    fetch(env.sampleUrl(), { cache: 'no-store' }).then((r) => (r.ok ? r.json() : null)).then((raw) => {
      if (raw) { sample = sampleDay(raw); env.changed(); }
    }).catch(() => { /* no made-up day: the sample shows none */ });
  }

  // Today's day, or null where there is none to show (switched off, control off, or not read yet).
  function current() {
    const w = where();
    if (w === 'sample') return sample;
    if ((w !== 'here' && w !== 'phone') || !control.on) return null;
    return control.dayNow() || fresh;
  }

  // Desktop alerts at plan and close time, on this computer only: never for what was there when the page opened, and
  // never while the page is in front (the card is there to see).
  function notify(a) {
    if (!env.alerts?.on?.() || typeof window === 'undefined' || typeof window.Notification !== 'function') return;
    try {
      const shown = new window.Notification(a.title, { body: a.body, tag: a.tag });
      shown.onclick = () => {
        try { window.focus?.(); } catch { /* the browser brings it forward itself */ }
        try { env.go('#/'); } finally { shown.close?.(); }
      };
    } catch { /* a browser that only shows them from a service worker: the card still shows */ }
  }
  function check(day) {
    if (!day || where() !== 'here') return;
    const plan = day.made && planCount(day).items ? `${day.date}:${day.made}` : null;
    const close = day.close?.at ? `${day.date}:${day.close.at}` : null;
    if (!told.primed) { told.primed = true; told.plan = plan; told.close = close; return; }
    const away = document.hidden || !document.hasFocus();
    if (plan && plan !== told.plan && away) notify(planAlert(day));
    if (close && close !== told.close && away) notify(closeAlert(day));
    told.plan = plan || told.plan;
    told.close = close || told.close;
  }

  // What of the day shows on the page: when it changes (the plan made at its time by the server, approved or changed from
  // a phone, an item started or finished, the close), the page is drawn again. The page's own watch (demo.js) follows
  // only the agents and their questions, so a plan made at 09:00 used to wait for something else to change.
  let drawn = null;

  function start() {
    ensure();
    control.watch((state) => {
      const day = state?.day || null;
      const now = JSON.stringify(day);
      if (drawn !== null && now !== drawn) env.changed();
      drawn = now;
      check(day);
    });
    setInterval(() => {
      if (where() !== 'here' || !control.on || !control.dayNow() || !document.hidden || !env.alerts?.on?.()) return;
      control.day().then((day) => { fresh = day; check(day); }).catch(() => { /* away for now: next time */ });
    }, BACKGROUND);
  }

  // Doing something from a button or the box: its words show on the card when done.
  function run(work) {
    busy = true;
    env.changed();
    Promise.resolve(work).then((said) => { note = String(said || ''); }, (error) => { note = error.message; })
      .finally(() => { busy = false; env.changed(); });
  }

  function approve(floors) {
    if (current()?.sample) {
      sample = sampleApprove(sample, floors);
      return floors?.length ? `Approved ${floors.join(' and ')}. The company is made up, so nothing starts.`
        : 'Approved the day. The company is made up, so nothing starts. With your own, the first thing on each floor would start now.';
    }
    return control.approveDay(floors).then((r) => r.said);
  }
  function change(floor, words) {
    if (current()?.sample) {
      const got = sampleChange(sample, floor, words);
      sample = got.day;
      return got.said;
    }
    return control.changeDay(floor, words).then((r) => r.said);
  }
  const makePlan = () => control.planDay().then((r) => r.said);
  const makeClose = () => control.closeDay().then((r) => r.said);
  const canAct = (v) => v.sample || control.on;

  function floorPart(v, f) {
    const items = live(f);
    return h('div.day-floor',
      h('div.day-floor-head',
        h('h4', f.label),
        h('span.small.muted', f.lead ? `Proposed by ${f.lead}, the lead` : "Proposed by the floor's lead"),
        f.approved ? h('span.state.k-working', 'Approved')
          : items.length > 0 && canAct(v) && btn(`Approve ${f.label}`, () => run(approve([f.floor || f.label])), '.quiet.day-floor-go', null, { disabled: busy })),
      f.note && h('p.small.day-note', f.note),
      items.length > 0 && h('ol.day-items', items.map((it) => h('li.day-item',
        h('span.day-item-main',
          h('span.day-item-title', it.title),
          h('span.small.muted', [it.why, it.cost].filter(Boolean).join(' ')),
          it.waiting && h('span.small.day-waiting', it.waiting)),
        h(`span.state.day-chip.k-${itemMood(it)}`, itemWord(it))))),
      f.later > 0 && h('p.small.muted', `${plural(f.later, 'more thing waits', 'more things wait')} for another day.`));
  }

  function changeBox(v) {
    const go = (event) => {
      event.preventDefault();
      const input = event.currentTarget.elements.words;
      const words = input.value.trim();
      if (!words) return;
      input.value = '';
      run(change(null, words));
    };
    return h('form.control-say.day-change', { onsubmit: go },
      h('input', { name: 'words', maxlength: 2000, autocomplete: 'off', placeholder: 'Drop the second one on Tidepool, or add: tidy the README',
        'aria-label': "Change today's plan in words" }),
      h('button.btn', { type: 'submit', disabled: busy }, 'Change'));
  }

  function planCard(v) {
    const { items, floors } = planCount(v);
    const started = v.plan.flatMap(live).filter((i) => i.state === 'started').length;
    const finished = v.plan.flatMap(live).filter((i) => i.state === 'done').length;
    const head = !items ? "Nothing is planned for today: no floor has anything to do."
      : v.approved ? `Approved. ${plural(items, 'thing', 'things')} on ${plural(floors, 'floor', 'floors')}: ${started} at work, ${finished} done. Each floor goes one thing at a time.`
        : `${plural(items, 'thing', 'things')} on ${plural(floors, 'floor', 'floors')}, proposed by each floor's lead at ${clock(v.made)}.`;
    return h('section.panel-card.day-card', { 'aria-label': "Today's plan" },
      sectHead('sun', "Today's plan"),
      h('p', head),
      v.night && h('p.small.day-night', v.night), // how last night's night shift went (connect/night.py)
      v.allowance?.words && h('p.small.muted.day-allowance', v.allowance.words),
      v.plan.filter((f) => live(f).length || f.note).map((f) => floorPart(v, f)),
      canAct(v) && items > 0 && !v.approved && h('div.control-row.day-do', btn('Approve the day', () => run(approve(null)), '.primary', null, { disabled: busy }),
        !v.sample && btn('Make it again', () => run(makePlan()), '.quiet', 'rotate-ccw', { disabled: busy })),
      canAct(v) && items > 0 && changeBox(v),
      note && h('p.small.note', { role: 'status' }, note),
      v.sample ? h('p.small.muted', 'Made up, like the rest of the sample. With your own company and control on, approved items start real agents, one at a time on each floor.')
        : !control.on && h('p.small.muted', 'Approving and changing it need Answer agents from the building, in Settings.'));
  }

  function closeCard(v) {
    const c = v.close;
    const part = (title, rows, none, sub) => [h('h4.day-sub', title), rows?.length
      ? h('ul.day-list', rows.map((r) => h('li', h('span.day-item-title', r.title), h('span.small.muted', sub(r)))))
      : h('p.small.muted', none)];
    return h('section.panel-card.day-card.day-close', { 'aria-label': 'How today went' },
      sectHead('moon', 'How today went'),
      h('p', c.words),
      part('Proven today', c.proven, 'Nothing was proven today.', (r) => r.floor),
      part('Stuck, and why', c.stuck, 'Nothing is stuck.', (r) => `${r.floor}: ${r.why}`),
      part('Needs you tomorrow', c.tomorrow, 'Nothing waits on you.', (r) => `${r.floor}: ${r.why}`),
      h('h4.day-sub', 'What today cost'),
      h('p.small', c.cost?.words || 'No spending was counted today.'),
      v.sample ? h('p.small.muted', 'A made-up day, like the rest of the sample.')
        : control.on && h('div.control-row', btn('Make it again now', () => run(makeClose()), '.quiet', 'rotate-ccw', { disabled: busy })),
      c.at && !v.sample && h('p.small.muted', `Made at ${clock(c.at)}.`));
  }

  function waitingCard(v) {
    return h('section.panel-card.day-card', { 'aria-label': "Today's plan" },
      sectHead('sun', "Today's plan"),
      h('p', `Today's plan comes at ${v.plan_at}, and the close at ${v.close_at}.`),
      control.on && h('div.control-row', btn('Make it now', () => run(makePlan()), '.quiet', null, { disabled: busy }),
        btn('Make the close now', () => run(makeClose()), '.quiet', null, { disabled: busy })),
      note && h('p.small.note', { role: 'status' }, note));
  }

  return {
    start,
    // Today's day as this page has it (the made-up one, or control's), or null; and approving it or changing it in
    // words, as the plan card's buttons do, for the morning briefing (morning.js): what to say, or a promise of it.
    now: () => current(),
    approve(floors = null) {
      const got = approve(floors);
      env.changed();
      return got;
    },
    change(words, floor = null) {
      const got = change(floor, words);
      env.changed();
      return got;
    },
    // Needs you: the plan while the day is on, the close once it is made in the evening.
    home() {
      ensure();
      const v = current();
      if (!v) return null;
      if (v.close && Date.now() / 1000 >= today(v.close_at)) return closeCard(v);
      return v.made && planCount(v).items ? planCard(v) : null;
    },
    // Activity: the plan (or when it comes) and the close.
    activity() {
      ensure();
      const v = current();
      if (!v) {
        const off = where() === 'here' && env.switchOn('daily_cycle') === true && !control.on;
        return off ? h('section.panel-card.day-card', sectHead('sun', "Today's plan"),
          h('p.small', 'The daily cycle is on, and it needs Answer agents from the building, in Settings, to plan the day and start its work.')) : null;
      }
      return [v.made ? planCard(v) : waitingCard(v), v.close && closeCard(v)];
    },
    // Settings, under the daily cycle's switch: its two times.
    times() {
      if (where() !== 'here') return null;
      if (!control.on) return h('p.small.muted.day-times', 'Its times can be set while Answer agents from the building is on.');
      const v = control.dayNow();
      if (!v) return null;
      const save = (event) => {
        event.preventDefault();
        const form = event.currentTarget.elements;
        control.dayTimes(form.plan.value, form.close.value).then((r) => { timesNote = r.said; }, (error) => { timesNote = error.message; })
          .finally(() => env.changed());
      };
      return h('form.day-times', { onsubmit: save },
        h('label.small', 'Plan at', h('input', { type: 'time', name: 'plan', value: v.plan_at, required: true })),
        h('label.small', 'Close at', h('input', { type: 'time', name: 'close', value: v.close_at, required: true })),
        h('button.btn.quiet', { type: 'submit' }, 'Save the times'),
        timesNote && h('span.small', { role: 'status' }, timesNote));
    },
    // What the receptionist (floor null) or a floor's lead ({ project, label }) says to words about the day: a string or
    // a promise of one, or null when they weren't about the day, or the day isn't on here.
    heard(text, floor = null) {
      const intent = dayIntent(text);
      if (!intent) return null;
      ensure();
      const v = current();
      if (!v) return null;
      const fail = (error) => error.message;
      if (intent.kind === 'plan') return sayPlan(v, floor);
      if (intent.kind === 'make') return v.sample ? sayPlan(v, floor) : control.planDay().then((r) => `${r.said} ${sayPlan(r.day, floor)}`, fail);
      if (intent.kind === 'approve') {
        const named = floor ? [floor.project] : floorIn(text, v.plan) ? [floorIn(text, v.plan)] : null;
        const got = approve(named);
        env.changed();
        return typeof got === 'string' ? got : got.catch(fail);
      }
      if (intent.kind === 'close') {
        if (v.sample) return sayClose(v.close, true);
        if (v.close && Date.now() / 1000 >= today(v.close_at)) return sayClose(v.close);
        return control.closeDay().then((r) => sayClose(r.day.close), fail);
      }
      const got = change(floor?.project || null, text);
      env.changed();
      return typeof got === 'string' ? got : got.catch(fail);
    },
  };
}
