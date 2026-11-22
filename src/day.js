// The daily cycle on the page (connect/day.py; docs/connect.md, "The daily cycle"): a plan in the morning, a close in
// the evening. Its words, what someone said about it to the receptionist or a floor's lead, its desktop alerts, and the
// made-up company's own day (sample/day.json), which changes only on this page. No DOM: tests/test_daily_cycle.py runs
// it under Node.
//
// A day, as control's "day" read gives it (and the sample's, shaped the same): { on, date, plan_at, close_at, made,
// plan: [{ floor, label, id, lead, approved, note?, later?, items: [{ id, title, why, cost?, state, waiting?, key?,
// source }] }], approved, allowance: { known, tight, words }, close: { at, proven, stuck, tomorrow, cost, words } | null }.

const FILLER = /^(?:(?:ok|okay|right|so|and|then|yes|yeah|please|hey|hi|good|great|fine|now)[,.!\s]+)+/i;
const PLAN_ASKED = /\b(?:what(?:'s| is| are)\s+(?:the|today's|our|my|this morning's)\s+plans?|today's plan|the plan (?:for|today)|plans? for (?:the day|today)|what(?:'s| is) on (?:for )?today|what (?:are|will) (?:we|they|the agents?) (?:doing|working on|do) today|what(?:'s| is) (?:the )?plan)\b/i;
const MAKE_ASKED = /^(?:(?:can|could|would) you\s+)?(?:make|draw up|put together|do|redo)\s+(?:the|today's|a|our)\s+plan(?:\s+(?:now|again|for today))?[.!?]*$|^plan (?:the|my|our) day[.!?]*$/i;
const APPROVE_ASKED = /^(?:i\s+)?approve\s+(?:(?:the|today's|this|our|all of the|the whole)\s+)?(?:day|plan)\b|^approve\s+[\w' -]{1,40}?'s?\s+(?:day|plan)\b|^approve\s+the\s+(?:day|plan)\s+(?:on|for)\s+|^(?:let's\s+)?go (?:ahead )?with (?:the|today's) plan\b|^(?:the\s+)?plan(?:'s| is)? approved\b/i;
const CLOSE_ASKED = /\bhow (?:did|was|has|is|'s) (?:today|the day|it today|our day|my day)(?: go(?:ne)?| been| going)?\b|\bhow did (?:we|they|the agents?) do today\b|\bwhat got done today\b|\b(?:the |today's |evening )?close (?:of|for) (?:the )?(?:day|today)\b|\b(?:the |today's )?evening close\b|\bwrap up (?:the day|today)\b|\bclose (?:the|out the) day\b/i;
const CHANGE_SAID = [
  /^(?:drop|remove|skip|cut|scrap|take out|leave out)\s+(?:the\s+)?(?:first|second|third|fourth|fifth|sixth|last|\d{1,2}(?:st|nd|rd|th)?)\b/i,
  /^(?:drop|remove|skip|cut|scrap|take out|leave out)\s+(?:item|number)\s*\d/i,
  /^add\s*:/i,
  /^add\s+to\s+(?:the|today's)\s+(?:plan|day)\b/i,
  /^(?:add|also)\b.+\bto\s+(?:the|today's)\s+(?:plan|day)[.!]?$/i,
  /^(?:do|put|move|start with)\s+(?:the\s+)?(?:second|third|fourth|fifth|sixth|last|\d{1,2}(?:st|nd|rd|th)?)(?:\s+(?:one|item|thing|task))?\s+first[.!]?$/i,
];

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const join = (list) => (list.length < 2 ? list.join('') : `${list.slice(0, -1).join(', ')} and ${list[list.length - 1]}`);
const lower = (t) => (t && !/^(?:I\b|[A-Z]{2})/.test(t) ? t[0].toLowerCase() + t.slice(1) : t);
const live = (f) => (Array.isArray(f?.items) ? f.items.filter((i) => i && i.state !== 'dropped') : []);

// What someone said about the day: { kind: 'plan' | 'make' | 'approve' | 'close' | 'change' }, or null for anything else.
export function dayIntent(text) {
  const said = String(text || '').trim().replace(FILLER, '').replace(/^please\s+/i, '');
  if (!said) return null;
  if (CHANGE_SAID.some((re) => re.test(said))) return { kind: 'change' };
  if (MAKE_ASKED.test(said)) return { kind: 'make' };
  if (APPROVE_ASKED.test(said)) return { kind: 'approve' };
  if (CLOSE_ASKED.test(said)) return { kind: 'close' };
  if (PLAN_ASKED.test(said)) return { kind: 'plan' };
  return null;
}

// The plan's floor named in the words ("on Tidepool", "Kitefield's day"), as its label; or null.
export function floorIn(text, plan) {
  const said = String(text || '').toLowerCase();
  for (const f of Array.isArray(plan) ? plan : []) {
    const names = [f.label, f.floor, f.id].filter(Boolean).map((n) => String(n).toLowerCase());
    for (const n of names) {
      const at = said.lastIndexOf(n);
      if (at < 0) continue;
      const before = said.slice(0, at);
      const after = said.slice(at + n.length);
      if (/(?:^|\s)(?:on|for|in|approve)\s+(?:the\s+)?$/.test(before) || /^'s?\s+(?:day|plan)/.test(after)) return f.label;
    }
  }
  return null;
}

export const planCount = (day) => {
  const floors = (day?.plan || []).filter((f) => live(f).length);
  return { items: floors.reduce((n, f) => n + live(f).length, 0), floors: floors.length };
};

// An item's state in a word or two, for its chip.
export function itemWord(item) {
  if (item.state === 'approved') return item.waiting ? 'Waiting' : 'Approved';
  return { proposed: 'Proposed', started: 'At work', done: 'Done', failed: 'Ended with an error', stopped: 'Stopped' }[item.state] || item.state;
}
export const itemMood = (item) => ({ started: 'working', done: 'ok', failed: 'failed', stopped: 'failed' }[item.state] || (item.state === 'approved' && item.waiting ? 'needs' : 'quiet'));

// The plan said out loud: the whole company's, or one floor's (`floor` is { project, label }) for its lead.
export function sayPlan(day, floor = null) {
  if (!day?.made) return `Today's plan isn't made yet. It comes at ${day?.plan_at || '09:00'}. Say "make the plan" to make it now.`;
  const made = day.sample ? ' This day is made up, like the rest of the company.' : '';
  if (floor) {
    const f = (day.plan || []).find((x) => x.floor === floor.project || x.label === floor.label);
    const items = live(f);
    if (!items.length) return `${floor.label} has nothing on today's plan.${f?.note ? ` ${f.note}` : ''}${made}`;
    const list = items.map((i, n) => `${n + 1}. ${i.title}${i.state === 'proposed' || i.state === 'approved' ? '' : ` (${lower(itemWord(i))})`}.`).join(' ');
    return `Here's ${f.label}'s plan for today: ${list}${f.note ? ` ${f.note}` : ''} ${f.approved ? "It's approved." : 'Approve it, or tell me what to change.'}${made}`;
  }
  const { head, floors } = planLines(day);
  if (!floors.length) return `${head}${made}`;
  const next = day.approved ? "It's approved, and the work goes one thing at a time on each floor." : 'Say "approve the day", or tell a floor\'s lead what to change.';
  return `${[head, ...floors].join(' ')} ${next}${made}`;
}

// The whole company's plan in words, without what to do about it: { head, floors }, a line for each floor with
// something to do. sayPlan adds what to do; the morning briefing (morning.js) asks it its own way.
export function planLines(day) {
  const { items, floors } = planCount(day);
  if (!items) return { head: "Today's plan is empty: no floor has anything to do.", floors: [] };
  return {
    head: `Today's plan: ${plural(items, 'thing', 'things')} on ${plural(floors, 'floor', 'floors')}.`,
    floors: (day.plan || []).filter((f) => live(f).length).map((f) => `${f.label}: ${live(f).map((i) => i.title).join('; then ')}.`),
  };
}

// The close said out loud: its summing up, then what was proven, what is stuck and why, what needs you tomorrow, and
// what today cost.
export function sayClose(close, made = false) {
  if (!close) return "Today's close isn't made yet.";
  const proven = (close.proven || []).slice(0, 3).map((p) => `"${p.title}" on ${p.floor}`);
  const stuck = (close.stuck || []).slice(0, 3).map((s) => `"${s.title}" on ${s.floor}: ${lower(s.why)}`);
  const tomorrow = (close.tomorrow || []).slice(0, 3).map((t) => `"${t.title}" on ${t.floor}`);
  return [
    close.words,
    proven.length && `Proven: ${join(proven)}.`,
    stuck.length && `Stuck: ${stuck.join(' ')}`,
    tomorrow.length && `Tomorrow you're needed for ${join(tomorrow)}${close.tomorrow.length > 3 ? `, and ${close.tomorrow.length - 3} more` : ''}.`,
    close.cost?.words,
    made && 'Made up, like the rest of the company.',
  ].filter(Boolean).join(' ').replace(/\.\./g, '.');
}

// The desktop alerts: { title, body, tag }, each tagged so it never comes twice.
export function planAlert(day) {
  const { items, floors } = planCount(day);
  return { title: 'Arnheim', body: `Today's plan is ready: ${plural(items, 'thing', 'things')} on ${plural(floors, 'floor', 'floors')}.`, tag: `day-plan-${day.date}` };
}
export function closeAlert(day) {
  return { title: 'Arnheim', body: `The day's close is ready. ${day.close?.words || ''}`.trim(), tag: `day-close-${day.date}` };
}

/* ---------- the made-up company's day (sample/day.json), which changes on this page only ---------- */

const pad = (n) => String(n).padStart(2, '0');
const dayOf = (now) => { const d = new Date(now * 1000); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; };
const at = (clock, now) => { const d = new Date(now * 1000); const [h, m] = String(clock || '09:00').split(':'); d.setHours(Number(h) || 0, Number(m) || 0, 0, 0); return d.getTime() / 1000; };

// The sample's day, shaped as control gives one, made today at its plan time; its close at its close time.
export function sampleDay(raw, now = Date.now() / 1000) {
  const plan = (Array.isArray(raw?.plan) ? raw.plan : []).map((f) => ({
    ...f, approved: false,
    items: (Array.isArray(f.items) ? f.items : []).map((i, n) => ({ ...i, id: i.id || `s-${f.id}-${n}`, state: i.state || 'proposed' })),
  }));
  return {
    on: true, sample: true, date: dayOf(now), plan_at: raw?.plan_at || '09:00', close_at: raw?.close_at || '18:00',
    made: Math.min(now, at(raw?.plan_at, now)), plan, approved: false, allowance: raw?.allowance || null,
    close: raw?.close ? { ...raw.close, at: at(raw?.close_at, now) } : null,
    night: raw?.night || null, // how last night's night shift went, in a line (night.js)
  };
}

const copy = (day) => ({ ...day, plan: day.plan.map((f) => ({ ...f, items: f.items.map((i) => ({ ...i })) })) });
const settle = (day) => { const withItems = day.plan.filter((f) => live(f).length); day.approved = withItems.length > 0 && withItems.every((f) => f.approved); return day; };

// Approves the sample's day, or the floors named (labels): a new day.
export function sampleApprove(day, floors) {
  const out = copy(day);
  for (const f of out.plan) {
    if (floors?.length && !floors.includes(f.label) && !floors.includes(f.floor)) continue;
    if (!live(f).length) continue;
    f.approved = true;
    for (const i of f.items) if (i.state === 'proposed') i.state = 'approved';
  }
  return settle(out);
}

const ORD = { first: 1, second: 2, third: 3, fourth: 4, fifth: 5, sixth: 6, last: -1 };
const nth = (word, count) => { const w = String(word).toLowerCase(); let n = ORD[w] ?? parseInt(w, 10); if (n === -1) n = count; return n >= 1 && n <= count ? n : null; };

// Changes the sample's day in words, as connect/day.py does yours: { said, day }.
export function sampleChange(day, floor, words) {
  const out = copy(day);
  let said = String(words || '').trim().replace(/[.!]+$/, '');
  let label = null;
  const named = [...said.matchAll(/[\s,]+(?:on|for|in)\s+(?:the\s+)?/gi)].reverse()
    .map((m) => ({ m, f: out.plan.find((x) => [x.label, x.floor, x.id].some((n) => String(n).toLowerCase() === said.slice(m.index + m[0].length).toLowerCase().replace(/\s+(?:floor|project)$/, ''))) }))
    .find((x) => x.f);
  if (named) { label = named.f.label; said = said.slice(0, named.m.index).trim(); }
  label = label || (floor ? out.plan.find((x) => x.label === floor || x.floor === floor)?.label : null);
  const withItems = out.plan.filter((f) => live(f).length);
  if (!label && withItems.length === 1) label = withItems[0].label;
  if (!label) return { said: `On which floor? Say it with the floor, such as "${said} on ${withItems[0]?.label || 'a floor'}".`, day };
  const f = out.plan.find((x) => x.label === label);
  const items = live(f);
  let m = /^(?:please\s+)?(?:drop|remove|skip|cut|scrap|take out|leave out)\s+(?:the\s+)?(first|second|third|fourth|fifth|sixth|last|\d{1,2})(?:st|nd|rd|th)?\b/i.exec(said);
  if (m) {
    const n = nth(m[1], items.length);
    if (!n) return { said: `${label}'s plan has ${plural(items.length, 'thing', 'things')}.`, day };
    items[n - 1].state = 'dropped';
    return { said: `Dropped "${items[n - 1].title}" from ${label}'s plan. The company is made up, so this changes only this page.`, day: settle(out) };
  }
  m = /^(?:please\s+)?(?:do|put|move|start with)\s+(?:the\s+)?(second|third|fourth|fifth|sixth|last|\d{1,2})(?:st|nd|rd|th)?(?:\s+(?:one|item|thing|task))?\s+first$/i.exec(said);
  if (m) {
    const n = nth(m[1], items.length);
    if (!n) return { said: `${label}'s plan has ${plural(items.length, 'thing', 'things')}.`, day };
    const it = items[n - 1];
    f.items = [it, ...f.items.filter((x) => x !== it)];
    return { said: `"${it.title}" is first on ${label} now.`, day: settle(out) };
  }
  m = /^(?:please\s+)?(?:add|also)\b(?:\s+to\s+(?:the|today's)\s+(?:plan|day))?\s*[:,]?\s*(.+?)(?:\s+to\s+(?:the|today's)\s+(?:plan|day))?$/i.exec(said);
  if (m && m[1].trim().length > 2) {
    const title = m[1].trim().replace(/^["']|["']$/g, '');
    f.items.push({ id: `s-added-${f.items.length}`, title: title[0].toUpperCase() + title.slice(1), why: 'You added it.', state: f.approved ? 'approved' : 'proposed', source: 'added' });
    return { said: `Added "${title[0].toUpperCase() + title.slice(1)}" to ${label}'s plan. The company is made up, so this changes only this page.`, day: settle(out) };
  }
  return { said: 'I can drop one ("drop the second one"), add one ("add: tidy the README"), or move one up ("do the third one first").', day };
}
