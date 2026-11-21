// Working beside your agents (docs/connect.md, "Work beside your agents"): the words and the reckoning the page needs
// to look over an agent's shoulder, hear it answer at once, answer its questions, review its changes together and
// hold it on a step. What was said, in plain words: "hold on", "carry on", "walk me through it", "looks good", "the
// second change", "line 42". How long something has been going, how a message stands, and a change's lines with their
// numbers. Plain module, with no page in sight, so tests/test_beside_words.py can run it under Node.

export const PARTS = ['live', 'replies', 'questions', 'review_together', 'hold'];

/* ---------- time, in words ---------- */

const n0 = (x) => Math.max(0, Math.round(Number(x) || 0));
const seconds = (at) => { const n = Number(at) || 0; return n > 1e12 ? n / 1000 : n; };
const plural = (k, one, many = `${one}s`) => `${k} ${k === 1 ? one : many}`;

// How long something has been going: "a few seconds", "40 seconds", "a minute", "3 minutes", "an hour and 5 minutes".
export function forWords(secs) {
  const s = n0(secs);
  if (s < 5) return 'a few seconds';
  if (s < 60) return `${s} seconds`;
  const m = Math.floor(s / 60);
  if (m < 60) return m === 1 ? 'a minute' : `${m} minutes`;
  const hr = Math.floor(m / 60);
  const r = m % 60;
  return `${hr === 1 ? 'an hour' : `${hr} hours`}${r ? ` and ${plural(r, 'minute')}` : ''}`;
}

// How long is left: "40 more seconds", "95 more seconds", "4 more minutes": in seconds under two minutes, so a short
// wait is never said as longer than it is.
export function leftWords(secs) {
  const s = Math.max(0, Math.ceil(Number(secs) || 0));
  if (s < 120) return s <= 1 ? 'a second more' : `${s} more seconds`;
  return `${Math.round(s / 60)} more minutes`;
}

const twoDigits = (k) => String(k).padStart(2, '0');
export const clockOf = (at) => { const d = new Date(seconds(at) * 1000); return `${twoDigits(d.getHours())}:${twoDigits(d.getMinutes())}`; };

/* ---------- what it is doing ---------- */

const STATE_WORD = {
  working: 'At work', waiting: 'Waiting', asking: 'Asking you', held: 'Held', finished: 'Finished', stopped: 'Stopped', ended: 'Ended',
};
export const stateWord = (state) => STATE_WORD[state] || 'Quiet';
// A screen's state as a mood for the page's colours.
export const stateMood = (state) => ({ working: 'working', waiting: 'needs', asking: 'needs', held: 'needs', stopped: 'failed' })[state] || 'quiet';

// What it is doing now, as { words, since (seconds, or null), kind, state }, or null with nothing seen yet.
export function nowOf(screen, now = Date.now() / 1000) {
  if (!screen || typeof screen !== 'object') return null;
  const step = screen.now && typeof screen.now === 'object' ? screen.now : null;
  const state = screen.state || 'working';
  if (step?.words) {
    const started = Number(step.started_at);
    return { words: String(step.words), since: Number.isFinite(started) && started > 0 ? Math.max(0, now - started) : null, kind: step.kind || 'other', state };
  }
  const last = screen.last || (Array.isArray(screen.steps) && screen.steps.length ? screen.steps[screen.steps.length - 1] : null);
  if (state === 'finished' || state === 'stopped' || state === 'ended') {
    return { words: last?.words ? `${stateWord(state)}. Last, it ${lowerFirst(String(last.words))}` : `${stateWord(state)}.`, since: null, kind: 'done', state };
  }
  return last?.words ? { words: `Last, it ${lowerFirst(String(last.words))}`, since: null, kind: 'thinking', state } : null;
}
const lowerFirst = (t) => (t && !/^(?:I\b|I'|[A-Z]{2})/.test(t) ? t[0].toLowerCase() + t.slice(1) : t);

// The line under a desk on a walk, or at the top of its screen: "Running npm test" and "40 seconds".
export function monitorLine(row, now = Date.now() / 1000) {
  if (!row) return null;
  const doing = nowOf(row, now);
  if (!doing) return null;
  const todo = Array.isArray(row.todos) ? todoOf(row) : row.todos || null;
  const parts = [doing.since != null ? forWords(doing.since) : null, todo?.all ? `${todo.done} of ${todo.all} done` : null].filter(Boolean);
  if (row.asking) return { title: 'Asking you', sub: clip(row.asking.text || 'It has a question for you.', 70), kind: 'needs' };
  if (row.hold?.state === 'held' || row.state === 'held') return { title: 'Held, as you asked', sub: parts.slice(1).join(', ') || 'Waiting for you', kind: 'needs' };
  return { title: clip(doing.words, 60), sub: parts.join(', '), kind: stateMood(doing.state) };
}

export function clip(text, most) {
  const t = String(text ?? '').replace(/\s+/g, ' ').trim();
  if (t.length <= most) return t;
  const cut = t.slice(0, most - 1);
  const at = cut.lastIndexOf(' ');
  return `${(at > most / 2 ? cut.slice(0, at) : cut).replace(/[\s.,;:]+$/, '')}…`;
}

// A finished step's line: its words, how long it took, and whether it worked.
export function stepLine(step) {
  if (!step) return '';
  const took = Number(step.took);
  const how = step.failed ? "it didn't work" : Number.isFinite(took) && took >= 5 ? `took ${forWords(took)}` : '';
  return [String(step.words || 'A step'), how].filter(Boolean).join(', ');
}

// Its to-do list, as it ticks: { done, all, working, rows }.
export function todoOf(screen) {
  const rows = Array.isArray(screen?.todos) ? screen.todos.filter((t) => t && typeof t === 'object') : [];
  return { done: rows.filter((t) => t.state === 'done').length, all: rows.length, working: rows.find((t) => t.state === 'working')?.title || null, rows };
}

/* ---------- a message you sent it: queued, taken, answered ---------- */

// When it reads what you said, from `say`'s answer.
const WHEN = {
  now: 'It gets this now.',
  next_step: 'It reads this at its next step.',
  after_permission: 'It reads this once the permission it waits on is answered.',
  as_answer: 'This answers the question it asked you.',
  when_resumed: 'It reads this once you resume your agents.',
  next_turn: 'It reads this the next time you send it something in its own window.',
};
export const whenWords = (when) => WHEN[when] || '';

// How a message stands: { state, word, line }. `word` is the short mark; `line` what to show beside it.
export function messageStatus(m, clock = clockOf) {
  if (!m || typeof m !== 'object') return null;
  if (m.state === 'answered') {
    return { state: 'answered', word: m.answered_at ? `Answered at ${clock(m.answered_at)}` : 'Answered', line: m.answer ? String(m.answer) : 'It answered in its own window.' };
  }
  if (m.state === 'taken') {
    return { state: 'taken', word: m.taken_at ? `Read at ${clock(m.taken_at)}` : 'Read', line: String(m.taken_words || "I've got your note and I'm on it.") };
  }
  return { state: 'queued', word: 'Waiting for it to read this', line: m.reply ? String(m.reply) : '' };
}

// The message to follow after `say`: from the screen's list, by id.
export const messageIn = (screen, id) => (Array.isArray(screen?.messages) ? screen.messages.find((m) => m && m.id === id) || null : null);

// What an agent says once you have sent it something, as it happens: its reply straight away (from `say`), then, once
// the hook hands your message over, that it has it, and then its answer. `find(id)` gives the message as the page last
// read it, `sleep(ms)` waits, `taken(id, what)` notes each moment as said (so it is never said again elsewhere), and
// `answered()` gives an answer seen another way (its run's or its feed's), or null. Yields strings.
export async function* replyFlow({ sent, find, sleep, taken = () => {}, answered = () => null, most = 180000, every = 1500, clock = Date.now }) {
  if (!sent) return;
  if (sent.reply) yield sent.reply;
  // finished with no way to start it again, or every agent paused: nothing will happen until you act
  if (sent.when === 'next_turn' || sent.when === 'when_resumed') return;
  let saidTaken = sent.sent === 'resumed';
  const until = clock() + most;
  while (clock() < until) {
    await sleep(every);
    const m = find(sent.id);
    if (m?.state === 'taken' && !saidTaken) {
      saidTaken = true;
      taken(sent.id, 'taken');
      if (m.taken_words) yield ` ${m.taken_words}`;
    }
    if (m?.state === 'answered') {
      if (!saidTaken) taken(sent.id, 'taken');
      taken(sent.id, 'answered');
      yield ` ${m.answer || "I've answered in my own window."}`;
      return;
    }
    const other = answered();
    if (other) { taken(sent.id, 'answered'); yield ` ${other}`; return; }
  }
  yield " I'm still on it. My answer will show on my page.";
}

/* ---------- holding ---------- */

// How a hold stands: { state, word, line, left } or null. Honest about how long it can last: until `until`, ten minutes
// at most, and two minutes after nobody uses the building.
export function holdWords(hold, now = Date.now() / 1000) {
  if (!hold || typeof hold !== 'object' || !['asked', 'held'].includes(hold.state)) return null;
  if (hold.state === 'asked') {
    return { state: 'asked', word: 'Holding at its next step', line: 'It finishes the step it is on, then waits for you. What you say reaches it there.', left: null };
  }
  const left = Number(hold.until) ? Math.max(0, Number(hold.until) - now) : null;
  const most = left == null ? 'for up to ten minutes' : left > 0 ? `for ${leftWords(left)} at most` : 'only a moment more';
  return {
    state: 'held', word: 'Held', left,
    line: `It's waiting for you, keeping what it has done. It can stay held ${most}, or until 2 minutes after nobody is using the building. What you say reaches it straight away.`,
  };
}

const ENDED = {
  'carry on': 'It carried on, as you said.',
  'ten minutes': 'It carried on: a hold lasts ten minutes at most.',
  nobody: 'It carried on: nobody was using the building for 2 minutes.',
  off: 'It carried on: Hold on and carry on was switched off.',
  stopped: 'It stopped while it was held.',
};
// The last hold's end, said once it is told: null when there is none, or it was long ago.
export function holdEndedWords(ended, now = Date.now() / 1000, within = 120) {
  if (!ended || typeof ended !== 'object') return null;
  if (Number(ended.at) && now - Number(ended.at) > within) return null;
  return ENDED[ended.why] || 'It carried on.';
}

/* ---------- questions ---------- */

// How long it waits for your answer here, honestly.
export function questionWait(q, now = Date.now() / 1000) {
  if (!q) return '';
  if (q.state === 'waiting') {
    const left = Number(q.until) - now;
    if (left > 0) return `It's waiting for you here for ${leftWords(left)}, then it asks in its own window.`;
    return 'Its wait here is over, so it asks in its own window now. You can still answer here.';
  }
  if (q.state === 'window') return 'It asked in its own window instead. You can still answer here: it gets your answer as a message.';
  return 'Its turn ended on this question. Answer here and it gets your answer as a message.';
}

const QS = (q) => (Array.isArray(q?.questions) ? q.questions.filter((x) => x && typeof x.question === 'string') : []);
const labelsOf = (one) => (Array.isArray(one?.options) ? one.options.map((o) => String(o?.label || '')).filter(Boolean) : []);
const orList = (list) => (list.length <= 1 ? list.join('') : `${list.slice(0, -1).join(', ')}, or ${list[list.length - 1]}`);

// A question as its agent says it out loud: the question, then the choices.
export function questionSaid(q) {
  if (!q) return '';
  const list = QS(q);
  if (q.kind === 'choices' && list.length) {
    const first = list[0];
    const opts = labelsOf(first);
    const ask = `${String(first.question).replace(/\s+$/, '')}${/[?.!]$/.test(first.question) ? '' : '?'}`;
    const choose = opts.length ? ` ${orList(opts)}${first.multiSelect ? ', as many as you like' : ''}.` : '';
    const more = list.length > 1 ? ` I have ${plural(list.length - 1, 'more question')} on the screen.` : '';
    return `I have a question. ${ask}${choose}${more} Say one, or tell me in your own words.`;
  }
  const text = String(q.text || '').trim();
  return text ? `I have a question: ${text}${/[?.!]$/.test(text) ? '' : '?'}` : 'I have a question for you. It is on the screen.';
}

const ORDINAL = { first: 1, second: 2, third: 3, fourth: 4, fifth: 5, sixth: 6, seventh: 7, eighth: 8, ninth: 9, tenth: 10, last: -1 };
const NUMBER = { one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10 };
const plainWords = (t) => String(t ?? '').toLowerCase().replace(/['’]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
const whichOf = (word) => {
  const w = String(word || '').toLowerCase();
  if (ORDINAL[w] != null) return ORDINAL[w];
  if (NUMBER[w] != null) return NUMBER[w];
  const m = /^(\d{1,3})(?:st|nd|rd|th)?$/.exec(w);
  return m ? Number(m[1]) : null;
};

// What you said, if it picks one of a question's choices: { answers } to send, or null for your own words. Only for
// a question with one part; "blue", "Blue please", "the first one", "option 2", "the last one".
export function optionPicked(said, q) {
  const list = QS(q);
  if (q?.kind !== 'choices' || list.length !== 1) return null;
  const opts = labelsOf(list[0]);
  if (!opts.length) return null;
  const t = plainWords(said).replace(/^(?:(?:ok|okay|um|uh|so|yes|yeah|i think|lets go with|go with|use|pick|choose|i choose|i pick|i want|i(?:d| would) like)\s+)+/, '').replace(/\s+(?:please|thanks|thank you|one)$/, '').trim();
  const one = (label) => ({ answers: { [list[0].question]: list[0].multiSelect ? [label] : label } });
  const pick = (i) => (i >= 1 && i <= opts.length ? one(opts[i - 1]) : i === -1 ? one(opts[opts.length - 1]) : null);
  const hit = opts.findIndex((o) => plainWords(o) === t || plainWords(o) === t.replace(/^the\s+/, ''));
  if (hit >= 0) return pick(hit + 1);
  // by its place: "the first", "option 2", "number two", "the last"
  const pos = /^(?:the\s+)?(?:(?:option|choice|number)\s+(\w+)|(\w+)(?:\s+(?:option|choice))?)$/.exec(t);
  const k = pos ? whichOf(pos[1] || pos[2]) : null;
  return k != null ? pick(k) : null;
}

/* ---------- what was said ---------- */

const LEAD = String.raw`^(?:(?:ok|okay|right|hey|please|actually|sorry|so|um|uh|oh|no)[,.!\s]+)*`;
const TAIL = String.raw`(?:[,.!\s]+(?:please|thanks|thank you|a (?:moment|second|sec|minute|bit)|for (?:a )?(?:moment|second|sec|minute|bit)|there|then|now|for me))*[.!]*$`;
// "hold on", "wait", "stop there", "hang on", "one moment": hold it. "stop" alone still means stop (control.js).
export const HOLD_ASKED = new RegExp(`${LEAD}(?:hold on|hold it|hold up|hang on|wait|wait up|stop there|stop right there|hold there|just a (?:moment|second|sec|minute)|one (?:moment|second|sec))${TAIL}`, 'i');
// "carry on", "go on", "keep going", "continue": let it go on (only while it is held).
export const CARRY_ASKED = new RegExp(`${LEAD}(?:(?:you can|ok(?:ay)?|right)\\s+)?(?:carry on|go on|keep going|continue|resume|go ahead|on you go|off you go)${TAIL}`, 'i');
// "walk me through it", "talk me through your changes", "explain your changes", "what did you change?"
export const WALK_ASKED = new RegExp(`${LEAD}(?:(?:can|could|would|will) you\\s+)?(?:(?:walk|talk|take) me through (?:it|this|that|them|everything|(?:the|your|all your|what you(?:ve| have)?) ?(?:changes?|changed|work|code|edits|diff|done)?)|explain (?:it|this|your changes|the changes|what you(?:ve| have)? (?:changed|done))|what (?:did|have) you changed?|show me (?:the|your) changes)[?.!]*${TAIL}`, 'i');
// "looks good", "that looks great to me", "LGTM", "ship it", "all good, thanks"
export const GOOD_ASKED = /^(?:(?:ok|okay|right|great|nice|yes|yeah|yep|thanks|thank you|perfect|lovely|brilliant)[,.!\s]+)*(?:(?:that|this|it|everything|all that)(?:'s| is)?\s+)?(?:looks? (?:good|great|fine|right|perfect)(?: to me)?|lgtm|all good|ship it|good work|nice work|well done)(?:[,.!\s]+(?:thanks|thank you|well done|good work|nice work|ship it))*[.!]*$/i;

// What was said to an agent, if it is one of these: 'hold', 'carry', 'walk' or 'good'; null for anything else.
export function besideAsked(text) {
  const t = String(text || '').trim();
  if (!t) return null;
  if (HOLD_ASKED.test(t)) return 'hold';
  if (CARRY_ASKED.test(t)) return 'carry';
  if (WALK_ASKED.test(t)) return 'walk';
  if (GOOD_ASKED.test(t)) return 'good';
  return null;
}

// "the second change", "change 3", "the last change", "line 42", "line 42 in login.js", each with what you want after
// it ("the second change: use a helper"). Gives { change } (1 up, or -1 for the last) or { line, file }, with `rest`,
// what you want, which may be empty; null when it points at nothing.
const POINT_LEAD = String.raw`^(?:(?:ok|okay|right|so|and|now|then|um|uh)[,.!\s]+)*(?:(?:about|on|in|at|for|look at|see)\s+)?`;
const AFTER = String.raw`(?:[\s,:;.!?-]+(.*))?$`;
const CHANGE_A = new RegExp(`${POINT_LEAD}(?:the\\s+)?(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last|\\d{1,3}(?:st|nd|rd|th))\\s+(?:change|hunk|edit)\\b${AFTER}`, 'i');
const CHANGE_B = new RegExp(`${POINT_LEAD}(?:the\\s+)?(?:change|hunk|edit)\\s+(?:number\\s+)?(\\d{1,3}|one|two|three|four|five|six|seven|eight|nine|ten)\\b${AFTER}`, 'i');
const LINE = new RegExp(`${POINT_LEAD}(?:the\\s+)?line\\s+(?:number\\s+)?(\\d{1,7})(?:\\s+(?:in|of|on)\\s+(?:the\\s+file\\s+)?([\\w./@+-]*\\w\\.[A-Za-z0-9]+|[\\w-]+\\.[A-Za-z0-9]+))?\\b${AFTER}`, 'i');
export function pointAsked(text) {
  const t = String(text || '').trim();
  const rest = (m) => String(m || '').trim().replace(/^(?:please\s+)?/i, '');
  let m = CHANGE_A.exec(t) || CHANGE_B.exec(t);
  if (m) {
    const k = whichOf(m[1]);
    if (k == null || k === 0) return null;
    return { change: k, rest: rest(m[2]) };
  }
  m = LINE.exec(t);
  if (m) return { line: Number(m[1]), file: m[2] || null, rest: rest(m[3]) };
  return null;
}

/* ---------- its changes, as lines ---------- */

// A change's lines with their numbers (docs: the contract, section 3): [{ sign, text, old, new }]. A " " line has both
// numbers, a "+" line the new file's, a "-" line the old file's; either is null when it isn't known.
export function numberLines(hunk) {
  const lines = Array.isArray(hunk?.lines) ? hunk.lines : [];
  let n = Number.isFinite(Number(hunk?.start)) && hunk?.start != null ? Number(hunk.start) : null;
  let o = Number.isFinite(Number(hunk?.old_start)) && hunk?.old_start != null ? Number(hunk.old_start) : null;
  return lines.filter((l) => Array.isArray(l) && ['+', '-', ' '].includes(l[0])).map(([sign, text]) => {
    const row = { sign, text: String(text ?? ''), old: null, new: null };
    if (sign !== '+' && o != null) row.old = o++;
    if (sign !== '-' && n != null) row.new = n++;
    return row;
  });
}

// The words for a line's kind, for a screen reader and for the line's note.
export const signWord = (sign) => ({ '+': 'put in', '-': 'taken out' })[sign] || 'unchanged';

// A change's own heading beside its file: a new file, written whole, a notebook cell, renamed.
export function hunkKind(h) {
  if (!h) return '';
  if (h.kind === 'add') return 'A new file';
  if (h.kind === 'delete') return 'Deleted';
  if (h.kind === 'whole') return 'Written whole: the file as it was could not be read';
  if (h.kind === 'notebook') return `A notebook cell${h.cell != null ? ` (${h.cell})` : ''}${h.mode && h.mode !== 'replace' ? `, ${h.mode === 'insert' ? 'put in' : 'taken out'}` : ''}`;
  if (h.to) return `Renamed to ${h.to}`;
  return '';
}

// Its changes, numbered in order on the page (the first change is 1), grouped by file in the order each was first
// changed: [{ file, added, removed, hunks: [{ n, hunk, lines }] }].
export function filesOf(changes) {
  const files = new Map();
  (Array.isArray(changes) ? changes : []).filter((h) => h && h.file).forEach((h, i) => {
    const row = files.get(h.file) || { file: h.file, added: 0, removed: 0, hunks: [] };
    row.added += Number(h.added) || 0;
    row.removed += Number(h.removed) || 0;
    row.hunks.push({ n: i + 1, hunk: h, lines: numberLines(h) });
    files.set(h.file, row);
  });
  return [...files.values()];
}

export function changeTotals(changes) {
  const list = (Array.isArray(changes) ? changes : []).filter((h) => h && h.file);
  return { files: new Set(list.map((h) => h.file)).size, added: list.reduce((s, h) => s + (Number(h.added) || 0), 0),
    removed: list.reduce((s, h) => s + (Number(h.removed) || 0), 0), hunks: list.length };
}
export function totalsWords(t) {
  if (!t?.hunks) return 'No changes yet.';
  return `${plural(t.files, 'file')}: ${plural(t.added, 'line')} put in, ${t.removed} taken out.`;
}

// The line a comment is about, in a change: its first line put in or taken out, or else its first line.
export function pointOf(hunk) {
  const lines = numberLines(hunk);
  const line = lines.find((l) => l.sign !== ' ') || lines[0] || null;
  return line ? target(hunk, line) : { file: hunk?.file || '', line: null, text: '', side: null };
}
// What `comment` takes for one line of a change: { file, line, text, side }.
export function target(hunk, line) {
  const old = line.sign === '-';
  return { file: String(hunk?.file || ''), line: (old ? line.old : line.new) ?? null, text: line.text, side: old ? 'old' : null };
}

// What "the second change" or "line 42" points at, in a screen's changes: a target for `comment`, with `n`, which
// change it is, or null when there is no such change or line.
export function resolvePoint(point, changes) {
  const list = (Array.isArray(changes) ? changes : []).filter((h) => h && h.file);
  if (!point || !list.length) return null;
  if (point.change != null) {
    const i = point.change === -1 ? list.length - 1 : point.change - 1;
    return list[i] ? { ...pointOf(list[i]), n: i + 1 } : null;
  }
  const want = String(point.file || '').toLowerCase().replace(/^\.?\//, '');
  const fits = (f) => !want || f.toLowerCase() === want || f.toLowerCase().endsWith(`/${want}`);
  for (const side of ['new', 'old']) { // newest change first: the line as the file stands now
    for (let i = list.length - 1; i >= 0; i--) {
      if (!fits(list[i].file)) continue;
      const hit = numberLines(list[i]).find((l) => l[side] === point.line && (side === 'new' || l.sign === '-'));
      if (hit) return { ...target(list[i], hit), n: i + 1 };
    }
  }
  return null;
}

// What the agent says once you point at a change or a line: where it is, and what it says there.
export function pointSaid(t) {
  if (!t) return '';
  const where = `${t.n ? `That's change ${t.n}, in ` : 'That is in '}${t.file}${t.line ? `, line ${t.line}${t.side === 'old' ? ' as it was' : ''}` : ''}`;
  const says = t.text && t.text.trim() ? `: "${clip(t.text.trim(), 80)}"` : '';
  return `${where}${says}. What would you like me to do with it?`;
}

/* ---------- what it says back ---------- */

// The last hold's end, as the agent says it on a walk or in Talk. Null when you said carry on (it said so then) or
// it was stopped.
const ENDED_SAID = {
  'ten minutes': "I've carried on: a hold lasts ten minutes at most.",
  nobody: "I've carried on: nobody was using the building for 2 minutes.",
  off: "I've carried on: holding was switched off.",
};
export const holdEndedSaid = (ended) => (ended && typeof ended === 'object' ? ENDED_SAID[ended.why] || null : null);

// "Looks good": what happens next. `check` is the floor's check's name (null for none), `review` what the review line
// said of the work in its own words (review.js), `reviewer` whether the floor has a review line at all.
export function goodSaid({ check = null, review = null, reviewer = false } = {}) {
  const name = check ? (/^[A-Z][a-z]/.test(check) ? check[0].toLowerCase() + check.slice(1) : check) : null;
  const first = name
    ? `Thanks. I'm running ${name} on my work now, and my page shows whether it passes.`
    : 'Thanks. My floor has no check to run, so nothing more runs on it from here. A check can be given to the floor in data/company.json.';
  const then = review || (reviewer ? 'The review line reads my work as my turn ends, before it reaches you.' : '');
  return [first, then].filter(Boolean).join(' ');
}

// What to say straight away when `say` gave no reply of its own (Replies straight away is off): as before.
export function plainReply(sent, working, agent = 'Claude Code') {
  if (sent?.sent === 'resumed') return 'On it.';
  if (working) return "Got it. I'll read that at my next step.";
  return `I'm waiting for you in ${agent}, so I'll see this the next time you send me something there.`;
}
