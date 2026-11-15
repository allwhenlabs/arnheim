// What a waiting item asks of you, in plain words: how careful to be with a permission, and what each kind of
// request means, for someone who has never seen a terminal. No imports, so tests/test_risk.py can run it under
// Node. The kinds and fields are queue.js's.

// A permission's tool, as one of four levels: low (only looks), files (changes files, which a restore point can
// take back), web (reaches the internet), look (a command, or a read of something that may be private).
const LEVEL = { Read: 'low', NotebookRead: 'low', Glob: 'low', Grep: 'low', LS: 'low',
  Edit: 'files', MultiEdit: 'files', Write: 'files', NotebookEdit: 'files', WebFetch: 'web', WebSearch: 'web', Bash: 'look' };

const SAY = {
  low: { word: 'Low risk', mood: 'ok', line: 'It only looks. Nothing is changed or sent anywhere.' },
  search: { word: 'Low risk', mood: 'ok', line: 'It only looks, but a search can reach across whole folders.' },
  private: { word: 'Look first', mood: 'failed', line: 'It wants to read something that may be private, such as a key, a login or a hidden file.' },
  files: { word: 'Changes files', mood: 'needs', line: 'It changes files in the project. A restore point keeps the way back.' },
  web: { word: 'Goes online', mood: 'needs', line: 'It opens a page or searches the internet. Only the address or the search words leave your computer.' },
  look: { word: 'Read it first', mood: 'needs', line: 'It runs a command on your computer. Most are harmless, like running tests, but a command can change or delete things.' },
  other: { word: 'Read it first', mood: 'needs', line: 'It uses a tool this page doesn\'t know. Allow it only if you know what it does.' },
};

// { word, mood, line } for a permission item, or null for anything else.
export function riskOf(item) {
  if (!item || item.kind !== 'permission') return null;
  const level = LEVEL[item.tool];
  if (level === 'low') return SAY[item.read === false && (item.tool === 'Read' || item.tool === 'NotebookRead') ? 'private' : item.tool === 'Read' || item.tool === 'NotebookRead' ? 'low' : 'search'];
  return SAY[level] || SAY.other;
}

// The exact thing a permission would do, when there is one to show: the command, the file or the address.
export function exactOf(item) {
  const what = String(item?.ask?.what || '');
  const tool = String(item?.tool || '');
  const bare = tool && what.startsWith(`${tool}: `) ? what.slice(tool.length + 2) : what === tool ? '' : what;
  return bare.trim() || null;
}

// What each kind of request means, for "What does this mean?".
export function meaningOf(item) {
  switch (item?.kind) {
    case 'permission': return 'An agent stops and asks before it does something on your computer that you haven\'t allowed. Allow lets it do this one thing, once. Deny says no, and it tries another way or tells you why it can\'t.';
    case 'question': return 'The agent stopped because it needs a decision only you can make. Your answer goes straight to it, and it carries on.';
    case 'turn': return 'The agent has finished. Proven means the project\'s own check ran on its last change and passed; not proven means it failed, with what went wrong. Look at the work, then give it its next step or leave it.';
    case 'task': return 'A task in your own list, marked as needing you. Open it to see what it needs.';
    default: return null;
  }
}

// The label for a waiting item's kind.
export function kindWord(item) {
  if (item?.kind === 'permission') return { word: 'Wants permission', mood: 'needs' };
  if (item?.kind === 'question') return { word: 'Asks you', mood: 'needs' };
  if (item?.kind === 'task') return { word: 'Your task', mood: 'needs' };
  const state = item?.review?.state === 'failed' || item?.proof?.state === 'failed' ? 'failed' : item?.proof?.state === 'proven' ? 'proven' : null;
  return state === 'proven' ? { word: 'Finished, proven', mood: 'ok' } : state === 'failed' ? { word: 'Finished, not proven', mood: 'failed' } : { word: 'Finished', mood: 'quiet' };
}
