// What a waiting item asks of you, in plain words: how careful to be with a permission, and what each kind of
// request means, for someone who has never seen a terminal. Plain modules only, so tests/test_risk.py can run it
// under Node. The kinds and fields are queue.js's.

import { HIDDEN, SECRET } from './queue.js';

// A permission's tool, as a level. Reads and searches inside a project's folder never ask, so every one that
// does reaches outside it: what it finds goes to the AI service, and none of them is ever called safe. A request
// that touches a hidden or private-looking path (queue.js's HIDDEN and SECRET) always says look first.
const LEVEL = { Read: 'read', NotebookRead: 'read', Glob: 'search', Grep: 'search', LS: 'search',
  Edit: 'files', MultiEdit: 'files', Write: 'files', NotebookEdit: 'files', WebFetch: 'web', WebSearch: 'web', Bash: 'look' };

const SAY = {
  read: { word: 'Reads outside', mood: 'needs', line: 'It reads a file outside the project. It changes nothing, but what it reads goes to the AI service.' },
  search: { word: 'Searches outside', mood: 'needs', line: 'It looks through folders outside the project. It changes nothing, but it can sweep whole folders, and what it finds goes to the AI service.' },
  private: { word: 'Look first', mood: 'failed', line: 'It reaches something that may be private, such as a key, a login or a hidden file. Allow it only if you meant it to.' },
  files: { word: 'Changes files', mood: 'needs', line: 'It changes a file. Inside a project git keeps, a restore point keeps the way back; anywhere else, nothing here can undo it.' },
  web: { word: 'Goes online', mood: 'needs', line: 'It opens a page or searches the internet. What it sends can include things it has read, and a page can carry instructions meant for the agent.' },
  look: { word: 'Read it first', mood: 'needs', line: 'It runs a command on your computer. Running tests is usually fine, but a command can change or delete files, install software or send files online.' },
  other: { word: 'Read it first', mood: 'needs', line: 'It uses a tool this page doesn\'t know. Allow it only if you know what it does.' },
};

// { word, mood, line } for a permission item, or null for anything else.
export function riskOf(item) {
  if (!item || item.kind !== 'permission') return null;
  const where = String(item.ask?.what || item.what || '');
  const level = Object.prototype.hasOwnProperty.call(LEVEL, item.tool) ? LEVEL[item.tool] : null;
  if (level && level !== 'web' && (SECRET.test(where) || HIDDEN.test(where) || item.read === false && level === 'read')) return SAY.private;
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
