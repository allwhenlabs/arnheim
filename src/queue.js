// Everything waiting on you, from every agent and the work, as one list, most urgent first: permissions an
// agent is asking for now, questions an agent stopped to ask, your own tasks marked as needing you, and agents
// that finished and wait for your next word. The panel lists it with an answer beside each, and the
// receptionist reads it out and can answer the safe ones together ("allow all the reads"). Plain modules
// only, so tests/test_queue.py can run it under Node.

import { proofOf } from './proof.js';
import { reviewOf } from './review.js';

// Reading one file. Reads inside a project's folder never ask, so the ones that do reach outside it: "allow all
// the reads" lets them go ahead together, but never a search (Grep, Glob, LS can sweep whole folders) and never
// a read of anything that looks like a key, a password, a token or a credentials file (SECRET), or that sits in
// a hidden folder or file, the system's Library or AppData, where most keys and logins live (HIDDEN). Those,
// like commands and changes, each need their own answer.
export const READS = new Set(['Read', 'NotebookRead']);
export const HIDDEN = /(?:^|[\\/\s])\.(?![.\\/\s]|$)|(?:^|[\\/\s])(?:Library|AppData)(?:[\\/]|$)/i;
export const SECRET = /(?:^|[\\/\s~])(?:[^\\/\s]*\.env\w*|\.ssh|\.aws|\.gnupg|\.netrc|\.npmrc|\.pypirc|\.pgpass|\.docker|\.kube|\.git-credentials|\.config[\\/]gh|keychains?|id_(?:rsa|dsa|ecdsa|ed25519)|[^\\/\s]*\.(?:pem|key|p8|p12|pfx|keystore|jks|ppk|gpg|asc|kdbx|ovpn)\b|login data|cookies(?![\w.-])|[^\\/\s]*(?:credential|secret|password|passwd|token|api[_-]?key|service[_-]?account)|[^\\/\s]*_history\b)/i;
const RANK = { permission: 0, question: 1, task: 2, turn: 3 };
// An agent whose needs are only "Nothing yet.", "Not yet." or "None." isn't asking anything. Anything more is
// kept: "Not yet. Please add the key." and "No, but should it be gold?" still ask.
const NOTHING = /^\s*(?:nothing(?:\s+yet)?|not\s+yet|none)\s*[.!]?\s*$/i;
const asksNothing = (text) => NOTHING.test(text);
const HUSH = 600; // seconds: how long an answered request's conversation waits to say something new before it shows again
const RECENT = 2 * 3600; // seconds: an agent that finished longer ago than this is no longer waiting on you

// What a permission is for, in plain words: "to read notes.md", "to run npm test".
const DOES = { Read: 'to read', NotebookRead: 'to read', Glob: 'to look for', Grep: 'to search for', LS: 'to list',
  Bash: 'to run', Edit: 'to change', MultiEdit: 'to change', Write: 'to write', NotebookEdit: 'to change',
  WebFetch: 'to open', WebSearch: 'to search the web for' };
export function wantsTo(tool, what) {
  // control.py describes a request as "Read: notes.md", or just "Read" when it names nothing
  if (tool && typeof what === 'string') what = what === tool ? '' : what.startsWith(`${tool}: `) ? what.slice(tool.length + 2) : what;
  const does = DOES[tool] || (tool ? `to use ${tool} on` : 'to use a tool on');
  return what ? `${does} ${what}` : (tool ? `to use ${tool}` : 'to use a tool');
}

const seconds = (at) => {
  const n = Number(at) || 0;
  return n > 1e12 ? n / 1000 : n; // a time in milliseconds or in seconds
};

// asks and runs: the permissions waiting and the agents started from the page (control state), conversations
// and tasks: as the page reads them (feeds included). A run names an agent whose conversation isn't in a feed
// yet. questions: those agents asked you in the building (control state). Each item: { kind, id, key?, title,
// project?, what, at, until?, read?, ask?, task?, proof?, review?, q? }.
export function waitingOnYou({ asks = [], runs = [], conversations = [], tasks = [], questions = [], now = Date.now() / 1000, recent = RECENT, hushed = new Map() } = {}) {
  const items = [];
  const talks = new Map(conversations.filter((c) => c && c.id).map((c) => [c.id, c]));
  const started = new Map(runs.filter((r) => r && r.key).map((r) => [r.key, r]));
  const asking = new Set();
  for (const a of asks) {
    if (!a || !a.id) continue;
    const c = talks.get(a.key) || started.get(a.key);
    asking.add(a.key);
    items.push({ kind: 'permission', id: `ask:${a.id}`, key: a.key, title: c?.title || 'An agent', project: c?.project,
      what: wantsTo(a.tool, a.what), tool: a.tool, read: READS.has(a.tool) && !SECRET.test(String(a.what || '')) && !HIDDEN.test(String(a.what || '')), at: seconds(a.at), until: seconds(a.until), ask: a });
  }
  // A question an agent asked you in the building (connect/control.py): one its hook waits on now comes first, with
  // the permissions, since the agent is held up until you answer or its wait runs out.
  for (const q of questions) {
    if (!q || !q.id || !q.key) continue;
    const c = talks.get(q.key) || started.get(q.key);
    asking.add(q.key);
    const first = Array.isArray(q.questions) ? q.questions.find((x) => x && x.question)?.question : null;
    items.push({ kind: 'question', id: `q:${q.id}`, key: q.key, title: c?.title || q.title || 'An agent', project: c?.project || q.project,
      what: String(q.text || first || 'It has a question for you.'), at: seconds(q.at), until: q.state === 'waiting' ? seconds(q.until) : 0, q, urgent: q.state === 'waiting' });
  }
  for (const c of talks.values()) {
    if (asking.has(c.id) || c.working) continue;
    // its request was just answered here: what it said while asking is that request, until it says something new
    const hush = hushed.get(c.id);
    if (hush && Math.max(seconds(c.at), seconds(c.stopped)) <= hush && now - hush < HUSH) continue;
    if (c.says?.needs && !asksNothing(c.says.needs)) {
      items.push({ kind: 'question', id: `talk:${c.id}`, key: c.id, title: c.title, project: c.project, what: c.says.needs, at: seconds(c.at) });
    } else if (c.check && now - seconds(c.stopped || c.at) < recent) {
      items.push({ kind: 'turn', id: `turn:${c.id}`, key: c.id, title: c.title, project: c.project, what: c.says?.now || 'It has finished for now.',
        at: seconds(c.stopped || c.at), proof: proofOf(c, now), review: reviewOf(c, now) });
    }
  }
  for (const t of tasks) {
    // a conversation's own "needs you" task is its question, listed above
    if (!t || t.status !== 'needs_you' || (t.session && talks.has(t.session))) continue;
    items.push({ kind: 'task', id: `task:${t.id}`, title: t.title, project: t.project, what: t.note || '', at: seconds(t.at), task: t });
  }
  const rank = (i) => (i.urgent ? RANK.permission : RANK[i.kind]);
  return items.sort((a, b) => rank(a) - rank(b)
    || (rank(a) === RANK.permission ? a.until - b.until : 0) // the one whose wait runs out first
    || (a.kind === 'turn' ? b.at - a.at : a.at - b.at)); // the newest finished; otherwise the longest waiting
}

// The answers that can be given to several at once: every waiting read. Null when there are fewer than two.
export function together(items) {
  const reads = items.filter((i) => i.kind === 'permission' && i.read);
  return reads.length >= 2 ? { label: `Allow all ${reads.length} reads`, ids: reads.map((i) => i.ask.id) } : null;
}

// The list in words, for the receptionist: how many, and the first few, most urgent first.
export function sayWaiting(items, label = (p) => p, most = 4) {
  if (!items.length) return 'Nothing is waiting on you right now.';
  const kinds = {
    permission: (i) => `${i.title}${i.project ? ` on ${label(i.project)}` : ''} wants your permission ${i.what}`,
    question: (i) => `${i.title}${i.project ? ` on ${label(i.project)}` : ''} is asking: ${i.what}`,
    task: (i) => `your task "${i.title}"${i.project ? ` on ${label(i.project)}` : ''}`,
    turn: (i) => `${i.title}${i.project ? ` on ${label(i.project)}` : ''} has finished and waits for your next step${i.review ? `. ${i.review.line}` : i.proof ? `. ${i.proof.line}` : ''}`,
  };
  const lines = items.slice(0, most).map((i) => kinds[i.kind](i));
  const more = items.length > most ? ` And ${items.length - most} more in the panel.` : '';
  const n = items.length === 1 ? 'One thing is' : `${items.length} things are`;
  const reads = together(items);
  return `${n} waiting on you. ${lines.map((l) => `${l[0].toUpperCase()}${l.slice(1)}${/[.?!]$/.test(l) ? '' : '.'}`).join(' ')}${more}${reads ? ` Say "allow all the reads" to let the ${reads.ids.length} that only read go ahead.` : ''}`;
}

// What you said to the receptionist, if it was to allow every waiting read: the ids to allow. Null otherwise.
const ALL_READS = /^(?:please\s+)?(?:allow|approve)\s+(?:all|every)(?:\s+of)?\s+(?:the\s+)?(?:reads?|reading|read requests?)(?:\s+please)?[.!]?$/i;
export function allowReadsAsked(text, items) {
  if (!ALL_READS.test(String(text || '').trim())) return null;
  return items.filter((i) => i.kind === 'permission' && i.read).map((i) => i.ask.id);
}
