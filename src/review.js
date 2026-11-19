// The review line (connect/review.py): on a floor that asks for one, an agent's changes are checked before
// they reach you, and sent back with the reason when they aren't ready. No imports, so
// tests/test_review_words.py can run it under Node.
//
// A conversation in a feed may carry `review`: { state: reviewing | passed | sent back | failed | error, by,
// said?, why?, times?, most?, at?, until?, reviewer?, writer? }. `reviewer` is the agent that reads the work
// (Codex or Claude Code), and `by` who decided: the reviewer, or the floor's check when that failed first.

const first = (text) => String(text || '').split('\n')[0].trim();
const end = (text) => (/[.?!]$/.test(text) ? text : `${text}.`);
const timesSaid = (n) => (n === 1 ? 'once' : n === 2 ? 'twice' : `${n} times`);
const NTH = { 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth' };
// The agent that decided, by name, when one did (older results said only "The reader", and a failed check isn't one).
const readerOf = (r) => (r.reviewer && r.by === r.reviewer ? String(r.reviewer) : null);

// What to show: { state, word, line }, or null when its floor has no review line (or it changed nothing).
export function reviewOf(c, now = Date.now() / 1000) {
  const r = c?.review && typeof c.review === 'object' ? c.review : null;
  if (!r) return null;
  const by = String(r.by || 'The review line');
  const times = Number(r.times) || 0;
  const reader = readerOf(r);
  if (r.state === 'reviewing') {
    const until = Number(r.until) || 0;
    if (until && now > until + 60) return { state: 'error', word: 'Not reviewed', line: 'The review line was cut short, so this work reached you unchecked.' };
    if (r.reviewer) {
      const line = c.proof?.state === 'checking' ? `Its check runs first, then ${r.reviewer} reviews it before it reaches you.` : `${r.reviewer} is reviewing its work before it reaches you.`;
      return { state: 'reviewing', word: 'In review', line };
    }
    return { state: 'reviewing', word: 'In review', line: 'The review line is checking its work before it reaches you.' };
  }
  if (r.state === 'passed') {
    const after = times ? `, after it was sent back ${timesSaid(times)}` : '';
    const said = r.said ? ` ${end(String(r.said))}` : reader ? ` ${reader} reviewed it.` : by !== 'The reader' && by !== 'The review line' ? ` ${by} passed.` : '';
    return { state: 'passed', word: 'Passed review', line: `It passed the review line${after}.${said}` };
  }
  if (r.state === 'sent back') {
    return { state: 'sent back', word: 'Sent back', line: end(`${reader || 'The review line'} sent it back${NTH[times] ? ` a ${NTH[times]} time` : ''}, so it is fixing it: ${first(r.why) || 'it wasn\'t ready'}`) };
  }
  if (r.state === 'failed') {
    const what = reader ? `${reader}'s review` : 'the review line';
    return { state: 'failed', word: 'Failed review', line: end(`It ${times ? `still failed ${what} after being sent back ${timesSaid(times)}` : `failed ${what}`}, so it reached you anyway: ${first(r.why) || 'it wasn\'t ready'}`) };
  }
  if (r.state === 'error') return { state: 'error', word: 'Not reviewed', line: end(`The review line couldn't finish, so this work reached you unchecked. ${first(r.said)}`.trim()) };
  return null;
}

// The same, as the agent says it of its own work on a walk.
export function reviewSaid(c, now = Date.now() / 1000) {
  const rv = reviewOf(c, now);
  if (!rv) return null;
  const r = c.review;
  const times = Number(r.times) || 0;
  const why = first(r.why) || "it wasn't ready";
  const reader = readerOf(r);
  if (rv.state === 'reviewing') return r.reviewer ? `${r.reviewer} is reviewing my work now, before it reaches you.` : 'The review line is checking my work now, before it reaches you.';
  if (rv.state === 'passed') return rv.line.replace(/^It passed/, 'My work passed');
  if (rv.state === 'sent back') return end(`${reader || 'The review line'} sent my work back${NTH[times] ? ` a ${NTH[times]} time` : ''}, so I'm fixing it: ${why}`);
  const what = reader ? `${reader}'s review` : 'the review line';
  if (rv.state === 'failed') return end(`My work ${times ? `still failed ${what} after being sent back ${timesSaid(times)}` : `failed ${what}`}, so it reached you anyway: ${why}`);
  return "The review line couldn't finish, so my work reached you unchecked.";
}

// The mood a list or the building shows it in.
export const reviewMood = (rv) => (rv?.state === 'passed' ? 'ok' : rv?.state === 'failed' ? 'failed' : null);

// Who reads the work on a floor, from data/company.json's "review" as connect/review.py reads it:
// { choice: other | claude | codex | none, line }, or null when the floor has no review line.
export function reviewerOf(floor) {
  let given = floor?.review;
  if (given === true) given = {};
  if (!given || typeof given !== 'object') return null;
  if (given.read === false) return { choice: 'none', line: 'No agent reads the work here: only its check decides.' };
  const word = String(given.reviewer || '').replace(/[\s_-]+/g, ' ').trim().toLowerCase();
  const choice = { claude: 'claude', 'claude code': 'claude', codex: 'codex' }[word] || 'other';
  const line = {
    other: "The other agent reviews: Codex reads Claude Code's work, and Claude Code reads Codex's. If the other one isn't installed, the same agent reads it.",
    claude: "Claude Code reviews every agent's work here, Codex's too.",
    codex: "Codex reviews every agent's work here, Claude Code's too.",
  }[choice];
  return { choice, line };
}

// The floors with a review line and who reads on each, in one sentence for Settings, or null when none has one.
export function reviewersSaid(floors) {
  const SHORT = { other: 'the other agent reviews', claude: 'Claude Code reviews', codex: 'Codex reviews', none: 'only the check decides' };
  const groups = new Map();
  for (const f of floors || []) {
    const rv = reviewerOf(f);
    if (rv) groups.set(rv.choice, [...(groups.get(rv.choice) || []), f.label || f.project]);
  }
  if (!groups.size) return null;
  const and = (names) => (names.length > 1 ? `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}` : names[0]);
  return `${[...groups].map(([choice, names]) => `On ${and(names)}, ${SHORT[choice]}`).join('. ')}.`;
}
