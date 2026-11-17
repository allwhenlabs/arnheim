// Each project's lead: one person on every project floor who knows that project in depth, like a product
// manager. Ask them where it stands and they say it in a few sentences. Tell them what you want done and they
// pass it to the agent working on it, or offer to start one. Ask what's new and they tell you what changed
// since you last asked, and how the agents answered what you passed on.
//
// Also the words anyone in the building understands when you talk instead of tapping: going somewhere
// ("take me to Lantern"), being put through to a lead ("how's Tidepool doing?"), and answering a permission
// request out loud, which is always read back first and never done by voice for anything that may be private.
//
// Plain module, so tests/test_leads.py can run it under Node: the page hands it plain data.

import { ALLOW, DENY } from './control.js';
import { riskOf } from './risk.js';
import { proofOf } from './proof.js';

/* ---------- words ---------- */

const norm = (text) => ` ${String(text ?? '').toLowerCase().replace(/['’]/g, '').replace(/[^a-z0-9]+/g, ' ').trim()} `;
// A name in what was said, as words, or run together or split apart as speech recognition may write it
// ("tide pool" for Tidepool, "headoffice" for Head office); a short name only as words.
const squash = (text) => norm(text).replace(/ /g, '');
// whole words in a row that, run together, are the name: "tide pool" for Tidepool, never "that last" for Atlas
const joined = (said, name) => {
  const want = squash(name);
  if (want.length < 5) return false;
  const w = norm(said).trim().split(' ');
  for (let i = 0; i < w.length; i++) {
    let run = '';
    for (let j = i; j < w.length && run.length < want.length; j++) { run += w[j]; if (run === want) return true; }
  }
  return false;
};
const hasName = (said, name) => !!name && (norm(said).includes(norm(name)) || joined(said, name));
const sameName = (said, name) => !!name && (norm(said) === norm(name) || (squash(name).length >= 5 && squash(said) === squash(name)));
const clip = (text, most) => {
  const t = String(text ?? '').replace(/\s+/g, ' ').trim();
  return t.length <= most ? t : `${t.slice(0, most - 1).replace(/\s+\S*$/, '')}…`;
};
const sentence = (text, most = 170) => {
  const t = String(text ?? '').replace(/\s+/g, ' ').trim();
  const m = /^.+?[.!?](?=\s|$)/.exec(t);
  return clip(m ? m[0] : t, most);
};
const end = (t) => (/[.?!"…]$/.test(t) ? t : `${t}.`);
const q = (t) => `"${clip(t, 90)}"`;
const cap = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);
const lower = (t) => (t && !/^(?:I\b|I'|[A-Z]{2})/.test(t) ? t[0].toLowerCase() + t.slice(1) : t);
const many = (k, one, more) => (k === 1 ? one : `${k} ${more}`);
const seconds = (at) => { const n = Number(at) || 0; return n > 1e12 ? n / 1000 : n; };
const STOPWORDS = new Set(['the', 'and', 'for', 'with', 'from', 'that', 'this', 'into', 'onto', 'about', 'agent', 'agents', 'conversation', 'work', 'working', 'one', 'some', 'them', 'they', 'what', 'when', 'have', 'make', 'just', 'please']);
const words = (text) => norm(text).trim().split(' ').filter((w) => w.length >= 3 && !STOPWORDS.has(w));

/* ---------- who they are ---------- */

// A project floor has a lead unless its company.json entry says "lead": false.
export const hasLead = (floor) => !!floor && !!floor.project && floor.lead !== false;
export const leadHref = (floor) => `#/${floor.id}/lead`;
export const isLeadHref = (href) => /^#\/[^/]+\/lead$/.test(String(href || ''));

// The lead as the building's talk knows people: { href, title, name, lead (the floor's id), project, voice, look }.
// A floor's "lead" in company.json can give a name, a voice and a look, as the receptionist's does.
export function leadOf(floor) {
  const own = floor?.lead && typeof floor.lead === 'object' ? floor.lead : {};
  const name = clip(own.name, 40) || null;
  return {
    href: leadHref(floor), lead: floor.id, project: floor.project, name,
    title: name ? `${name}, ${floor.label}'s lead` : `${floor.label}'s lead`,
    voice: typeof own.voice === 'string' ? own.voice : null,
    look: own.look && typeof own.look === 'object' ? own.look : null,
  };
}

/* ---------- where it stands ---------- */

const waitPhrase = (i) => ({
  permission: () => `${q(i.title)} wants your permission ${i.what}`,
  question: () => (plain(i.what) ? `${q(i.title)} asks: ${clip(plain(i.what), 140).replace(/[.?!]$/, '')}` : `${q(i.title)} asks you something, on the screen`),
  task: () => `your task ${q(i.title)}`,
  turn: () => `${q(i.title)} has finished${i.proof?.state === 'proven' ? ', proven' : i.proof?.state === 'failed' || i.review?.state === 'failed' ? ', not proven' : ''}`,
})[i.kind]?.() || q(i.title);

// Where the project stands, in a few spoken sentences. v: { label, conversations (this floor's), waiting
// (queue.js items for this floor), goals, tasks (open), prs, health (health.js), spend (budget.js), clashes }.
// What an agent says, unless it is markup a message brought in (a helper's report, another session's
// message), which is never read out.
const MARKUP = /<\/?[a-z][\w-]*(?:\s[^>]*)?>/i;
const plain = (text) => (MARKUP.test(String(text || '')) ? '' : String(text || ''));
const says = (c) => plain(c?.says?.now);

export function leadUpdate(v) {
  const out = [];
  const convos = v.conversations || [];
  const working = convos.filter((c) => c.working);
  if (working.length) {
    out.push(`On ${v.label}, ${working.length === 1 ? 'one agent is' : `${working.length} agents are`} at work.`);
    for (const c of working.slice(0, 3)) out.push(says(c) ? end(`The one on ${q(c.title)} says: ${sentence(says(c))}`) : `One is on ${q(c.title)}.`);
    if (working.length > 3) out.push(`And ${working.length - 3} more.`);
  } else {
    const last = [...convos].sort((a, b) => seconds(b.at) - seconds(a.at))[0];
    out.push(`Nobody is working on ${v.label} right now.${last ? ` The last one was on ${q(last.title)}${says(last) ? `, and said: ${end(sentence(says(last)))}` : '.'}` : ''}`);
  }
  const w = v.waiting || [];
  if (w.length) out.push(`${w.length === 1 ? 'One thing waits' : `${w.length} things wait`} on you: ${w.slice(0, 2).map(waitPhrase).join('; ')}${w.length > 2 ? `; and ${w.length - 2} more` : ''}.`);
  else out.push('Nothing here waits on you.');
  const problems = (v.health?.problems || []).filter((p) => p.kind !== 'pr');
  for (const p of problems.slice(0, 2)) out.push(end(p.line));
  if (v.clashes?.length) out.push(`Careful: ${v.clashes.length === 1 ? 'two agents have changed the same files' : `${v.clashes.length} pairs of agents have changed the same files`}.`);
  const goals = (v.goals || []).filter((g) => g.status !== 'reached');
  if (goals.length) out.push(`${goals.length === 1 ? 'The goal is' : 'The goals are'} ${goals.slice(0, 2).map((g) => q(g.title)).join(' and ')}${goals.length > 2 ? `, and ${goals.length - 2} more` : ''}.`);
  const open = (v.tasks || []).filter((t) => t.status !== 'needs_you').length;
  const prs = (v.prs || []).length;
  const stale = (v.health?.problems || []).filter((p) => p.kind === 'pr').length;
  const opened = [open && many(open, 'one task', 'tasks'), prs && many(prs, 'one pull request', 'pull requests')].filter(Boolean);
  if (opened.length) out.push(`Open: ${opened.join(' and ')}${stale ? `, ${stale === 1 ? 'one of them' : `${stale} of them`} waiting over a week` : ''}.`);
  if (v.spend) out.push(`Spent: ${v.spend.text}.`);
  return out.join(' ');
}

/* ---------- what came of what you asked ---------- */

// Seconds with no word back from an agent that isn't working before its lead says it may be stuck.
export const STUCK_AFTER = 20 * 60;

// What came of an instruction you had a lead pass on, p: { at, key, title, text, working (whether the agent was
// at work when it went) }, from what happened since. ctx: { moments, conversations, waiting, agents, now }.
// Gives { state, final, line }. A final state is one a lead tells you without being asked, once each (a new
// state, such as its checks passing after it said it was done, is told again):
//   needs:<id>        it waits on you: a permission or a question
//   done:<proof>      it finished; proof: proven, failed, checking, claimed or none (proof.js)
//   stopped           it stopped
//   stuck             no word back for a while, and it isn't working
// and the rest only when you ask what's new: working, unread (it wasn't at work, and hasn't started since),
// waiting (no word back yet), gone (its conversation is no longer in the building). Its turn has ended (done) on a finished moment, a turn waiting on you, or, where
// that day's moments aren't at hand, once it did something after you asked and isn't working now.
export function reportOf(p, { moments = [], conversations = [], waiting = [], agents = [], now = Date.now() / 1000 } = {}) {
  const at = Number(p.at) || 0;
  const c = conversations.find((x) => x.id === p.key) || null;
  const working = !!(c?.working || agents.find((x) => x.id === p.key)?.working);
  const found = moments.filter((m) => m && m.key === p.key && Number(m.at) > at && m.kind !== 'left').sort((x, y) => y.at - x.at)[0] || null;
  const after = found && { ...found, what: plain(found.what) }; // never markup a message brought in
  const known = !!(c || agents.some((x) => x.id === p.key));
  const asked = `You asked the one on ${q(p.title)} to ${lower(clip(p.text, 120)).replace(/[.!?]$/, '')}.`;
  const say = (state, final, words) => ({ state, final, line: `${asked} ${words}` });
  const needs = waiting.find((i) => i.key === p.key && (i.kind === 'permission' || i.kind === 'question'));
  if (needs) {
    return say(`needs:${needs.id || needs.ask?.id || needs.kind}`, true, end(needs.kind === 'permission'
      ? `It needs you: it wants your permission ${needs.what}` : plain(needs.what) ? `It needs you. It asks: ${clip(plain(needs.what), 140).replace(/[.?!]$/, '')}` : 'It needs you: it asks you something, on the screen'));
  }
  const turn = waiting.find((i) => i.key === p.key && i.kind === 'turn' && Number(i.at) > at);
  // its turn ended after what you asked: a finished moment, a turn waiting on you, or (where moments from that
  // day aren't at hand) it did something after and isn't working now
  const last = Math.max(after ? Number(after.at) : 0, c ? seconds(c.at) : 0);
  const ended = after?.kind === 'finished' || turn || (!working && after?.kind !== 'stopped' && after?.kind !== 'asked' && last > at + 2);
  if (ended) {
    const proof = turn?.proof || (c ? proofOf(c, now) : null);
    const said = after?.kind === 'finished' && after.what ? after.what : says(c);
    const what = said ? `: ${sentence(said)}` : '.';
    const words = !proof ? `It's done${what}`
      : proof.state === 'proven' ? `It's done, and proven: ${lower(proof.line)}`
        : proof.state === 'failed' ? `It says it's done, but it isn't proven: ${lower(proof.line)}`
          : proof.state === 'checking' ? `It's done. ${proof.line}` : `It says it's done. ${proof.line}`;
    return say(`done:${proof?.state || 'none'}`, true, end(words));
  }
  if (after?.kind === 'stopped') return say('stopped', true, end(`It stopped${after.what ? `: ${sentence(after.what)}` : ' before saying it was done'}`));
  if (after?.kind === 'asked') return say('working', false, after.what ? end(`It asked you: ${clip(after.what, 140)}`) : 'It asked you something, on the screen.');
  if (working) {
    return say('working', false, after ? end(after.kind === 'changed' ? `It is on it, and changed ${after.what}` : `It is on it${after.what ? `: ${sentence(after.what)}` : ''}`)
      : c && seconds(c.at) > at && says(c) ? `It says: ${end(sentence(says(c)))}` : 'It is on it. No word back yet.');
  }
  // gone from the building (its conversation ended long ago): nothing more can be told of it
  if (!known && !after) return say('gone', false, "It isn't in the building any more, so I can't tell what came of it.");
  if (p.working === false) return say('unread', false, "It wasn't at work, and hasn't started since, so it hasn't read it yet.");
  const quiet = now - at;
  if (quiet >= STUCK_AFTER) {
    const mins = Math.round(quiet / 60);
    return say('stuck', true, `No word back for ${mins >= 120 ? `${Math.round(mins / 60)} hours` : `${mins} minutes`}, and it isn't working: it may be stuck.`);
  }
  return say('waiting', false, 'No word back yet.');
}

// What changed on the floor since `since` (seconds): its moments (replay.js), and what came of what you passed
// on (reportOf). v: { label, moments (this floor's), since, now, conversations, waiting, agents, passed:
// [{ at, key, title, text }], from (words such as "since 14:05"), said(p, report) (optional: told of each report
// it gives, so only those are marked as told) }.
export function leadNews(v) {
  const since = Number(v.since) || 0;
  const now = Number(v.now) || Date.now() / 1000;
  const talks = new Map((v.conversations || []).map((c) => [c.id, c]));
  const ctx = { moments: v.moments || [], conversations: v.conversations || [], waiting: v.waiting || [], agents: v.agents || [], now };
  const out = [];
  for (const p of (v.passed || []).filter((x) => now - x.at < 86400).slice(-3)) {
    const after = (v.moments || []).filter((m) => m.key === p.key && m.at > p.at).sort((a, b) => b.at - a.at)[0];
    if (!(p.at > since || (after && after.at > since))) continue;
    const r = reportOf(p, ctx);
    v.said?.(p, r);
    out.push(r.line);
  }
  const inside = (v.moments || []).filter((m) => m && m.key && m.at > since && m.at <= now).sort((a, b) => a.at - b.at);
  const last = new Map();
  const files = new Map();
  for (const m of inside) {
    if (m.kind !== 'left') last.set(m.key, m);
    if (m.kind === 'changed') files.set(m.key, new Set([...(files.get(m.key) || []), m.what]));
  }
  const told = new Set((v.passed || []).map((p) => p.key));
  const each = [...last.values()].filter((m) => !told.has(m.key)).sort((a, b) => b.at - a.at);
  for (const m of each.slice(0, 4)) {
    const who = q(talks.get(m.key)?.title || m.title || 'A conversation');
    const changed = files.get(m.key)?.size || 0;
    const what = plain(m.what);
    if (m.kind === 'finished') out.push(end(`${who} finished${what ? `: ${sentence(what)}` : ''}`));
    else if (m.kind === 'asked') out.push(end(`${who} asked you: ${what ? clip(what, 140) : 'a question, on the screen'}`));
    else if (m.kind === 'stopped') out.push(`${who} stopped.`);
    else out.push(`${who} worked${changed ? `, and changed ${changed === 1 ? [...files.get(m.key)][0] : `${changed} files`}` : ''}.`);
  }
  if (each.length > 4) out.push(`And ${each.length - 4} more conversations moved.`);
  const from = v.from || 'since you last asked';
  if (!out.length) return `Nothing new on ${v.label} ${from}.`;
  return `${cap(from)}, on ${v.label}: ${out.join(' ')}`;
}

/* ---------- the round: every lead in turn, a line each ---------- */

// "Give me the round", "morning round", "do the rounds", "update on every project", "check in with all the leads".
// ("How are the projects doing?" stays the building's health, health.js; "a round of tests" is never the round.)
const BEFORE = String.raw`^(?:(?:ok|okay|right|so|please|hi|hello|now|can you|could you|let's|lets)[,\s]+)*`;
export const ROUND_ASKED = new RegExp([
  // "give me the round", "do the rounds", "morning round", "the round", "round up please"
  String.raw`^(?:(?:ok|okay|right|so|please|can you|could you|can i have|can i get|i'd like|id like)[,\s]+)*(?:(?:give me|do|start|run|time for|lets do|let's do|let's have|lets have|go round|go around)\s+)?(?:the |a |my |our )?(?:morning |daily |evening |quick )?(?:rounds?|round\s?-?\s?up)(?:\s+(?:please|now|for me|of (?:the )?(?:leads|projects|floors|building)))?$`,
  // "update on every project", "give me the news from all the leads"
  String.raw`${BEFORE}(?:give me |get me |i want |i'd like |id like |can i have |can i get |what's the |whats the )?(?:an |a |the |my )?(?:update|updates|news|status|word|briefing) (?:on|from|across) (?:everything|every (?:project|floor|lead)|all (?:the |my )?(?:projects|floors|leads))(?:\s+please)?$`,
  // "what's happening everywhere?"
  String.raw`${BEFORE}what(?:'s| is) (?:new|happening|going on) (?:everywhere|on every (?:floor|project)|across (?:the |all )?(?:projects|floors|building))$`,
  // "check in with all the leads", "ask every lead" (never "tell them to ask all the leads")
  String.raw`${BEFORE}(?:check (?:in )?(?:on|with)|hear from|ask) (?:everything|every (?:project|lead)|all (?:the )?(?:projects|leads)|each lead)(?:\s+please)?$`,
].join('|'), 'i');
// "How's everything?", only as the whole of what was said, and only to the receptionist or the assistant: to a
// lead it means their own floor, and "how's everything going on Tidepool?" is Tidepool's.
export const EVERYTHING_ASKED = /^(?:(?:ok|okay|right|so|and|then|hi|hello)[,\s]+)*how(?:'s| is)\s+everything(?:\s+(?:going|doing|looking))?(?:\s+(?:today|now|then|this morning))?$/i;
export const roundAsked = (text, { loose = true } = {}) => {
  const t = String(text || '').trim().replace(/[.!?\s]+$/, '');
  return ROUND_ASKED.test(t) || (loose && EVERYTHING_ASKED.test(t));
};

// One lead's line in the round: what came of what you asked (reports, from reportOf), what finished since,
// who is at work, and what waits on you. v: { label, conversations, waiting, moments, since, now, reports:
// [lines], reported: [keys the reports were about] }. Gives { text, quiet, waits }.
export function leadRoundLine(v) {
  const since = Number(v.since) || 0;
  const now = Number(v.now) || Date.now() / 1000;
  const convos = v.conversations || [];
  const talks = new Map(convos.map((c) => [c.id, c]));
  const told = new Set(v.reported || []);
  const parts = (v.reports || []).slice(0, 2).map(end);
  const last = new Map();
  for (const m of (v.moments || []).filter((x) => x && x.key && x.at > since && x.at <= now && x.kind !== 'left').sort((a, b) => a.at - b.at)) last.set(m.key, m);
  const done = [...last.values()].filter((m) => m.kind === 'finished' && !told.has(m.key));
  const bits = [];
  if (done.length === 1) {
    const c = talks.get(done[0].key);
    const proof = c ? proofOf(c, now) : null;
    bits.push(`${q(c?.title || done[0].title || 'A conversation')} finished${proof?.state === 'proven' ? ', proven' : proof?.state === 'failed' ? ', not proven' : ''}`);
  } else if (done.length > 1) bits.push(`${done.length} conversations finished`);
  const working = convos.filter((c) => c.working).length;
  if (working) bits.push(`${working === 1 ? 'one agent is' : `${working} agents are`} at work`);
  if (bits.length) parts.push(end(cap(bits.join(', and '))));
  const w = (v.waiting || []).filter((i) => !i.key || !told.has(i.key));
  if (w.length === 1) parts.push(end(`One thing waits on you: ${waitPhrase(w[0])}`));
  else if (w.length > 1) parts.push(end(`${w.length} things wait on you. First, ${waitPhrase(w[0])}`));
  return { text: parts.join(' '), quiet: !parts.length, waits: w.length };
}

// "More on Tidepool", "tell me more about Tidepool", "what about Tidepool", any time; and just "Tidepool" where
// `bare` (after the round, when a lone name can't be the answer to another question). Gives the floor named
// ({ id, label, project, lead }) or null.
const MORE_ON = /^(?:(?:and|so|ok|okay|right|then|now)[,\s]+)*(?:(?:tell me |i(?:'d| would) like |give me )?more (?:on|about|from)|what about|how about|over to)\s+(?:the\s+)?(.+?)[.!?]*$/i;
export function floorNamed(text, floors, { bare = true } = {}) {
  const said = String(text || '').trim();
  const m = MORE_ON.exec(said);
  if (!m && !bare) return null;
  const asked = norm((m ? m[1] : said).replace(/['’]s\b/gi, '').replace(/\b(?:the|floor|project|please|lead)\b/gi, ''));
  if (!m && asked.trim().split(' ').length > 3) return null;
  return floors.find((f) => [f.label, f.project, f.lead?.name].some((n) => sameName(asked, n))) || null;
}

/* ---------- what you say to a lead ---------- */

export const NEWS_ASKED = /\b(?:any ?(?:thing)? ?new|any news|news|what(?:'s| has| have)? changed|what(?:'s| is) new|since (?:i|we) (?:last )?(?:spoke|talked|asked|checked)|anything (?:happen(?:ed)?|change(?:d)?)|did (?:they|the agents?|it) (?:answer|reply|say|do it)|what did (?:they|the agents?) (?:say|do))\b/i;
export const UPDATE_ASKED = /\b(?:where (?:are we|do we stand|are things|is it|are you|is (?:it|this|that) at)|how(?:'s| is| are)(?:\s+[\w' -]{1,40}?)? (?:going|doing|looking|coming along|getting on)|status|update|progress|state of (?:play|things)|sum (?:it )?up|overview|what(?:'s| is) (?:going on|happening|the latest|the situation|the plan)|current position|position|tell me (?:about it|everything|where)|brief me|catch me up)\b/i;
// "Tell me more", "more detail", on their own: where it stands, in full. With more after them, a question.
export const MORE_ALONE = /^(?:(?:ok|okay|right|so|and|please)[,\s]+)*(?:tell me more|more|more detail|more details|in detail|the details|full update|go into detail)(?:\s+please)?[.!?]*$/i;
export const WHO_ASKED = /\b(?:who(?:'s| is)? (?:working|on it|at work|here|busy)|which agents?|what are (?:the )?agents (?:doing|working on|up to)|whos working)\b/i;
export const HELP_ASKED = /^(?:help|what can (?:you|i) (?:do|say|ask)|how does this work|what do you do)\b/i;
const YES = /^(?:yes|yeah|yep|ok|okay|sure|go ahead|do it|please do|send it|go on)\b[\s,.!]*(?:please|now|thanks)?[.!]?$/i;
const NO = /^(?:no|nope|cancel|never ?mind|don'?t|leave it|not now)\b/i;

// An instruction for the agents: "tell them to test it on the spare laptop", "ask the agent on the bookmark
// fix to write the release note", "get them to stop after this step", "pass on that the key is in the vault".
// Gives { text, hint } (hint: who it names, such as "the agent on the bookmark fix") or null.
const PASS_TO = /^(?:(?:please|ok|okay|right|so|and)[,\s]+)*(?:(?:can|could|would|will) you\s+)?(?:please\s+)?(?:tell|ask|get|have|let|make|remind|instruct)\s+(them|it|everyone|everybody|the\s+team|the\s+agents?|whoever(?:'s|\s+is)\s+(?:on it|working)|the\s+(?:one|agent)\s+(?:on|working on|doing|for)\s+.+?)\s+(?:to\s+|that\s+|know\s+(?:that\s+)?|(?=(?:what|how|why|when|where|whether|if|who|which)\b))(.+)$/i;
const PASS_ON = /^(?:(?:please|ok|okay|right|so)[,\s]+)*(?:(?:can|could|would|will) you\s+)?(?:please\s+)?pass\s+(?:it\s+|this\s+|that\s+)?on(?:\s+to\s+(?:them|the\s+agents?|the\s+team|it))?\s*(?:that\s+|:|,|-)?\s*(.+)$/i;
const WANT = /^(?:i\s+(?:want|need|would like)|id\s+like)\s+(them|the\s+agents?|the\s+team|it|the\s+(?:one|agent)\s+(?:on|working on|doing)\s+.+?)\s+to\s+(.+)$/i;
const ASKS_A_QUESTION = /\?\s*$|^(?:ask|tell)\s+(?:them|it)\s+(?:what|how|why|when|where|whether|if|who)\b/i;

export function passAsked(text) {
  const said = String(text || '').trim().replace(/\s+/g, ' ');
  if (!said || said.length > 1200) return null;
  let m = PASS_TO.exec(said);
  if (m) return { text: tidy(m[2]), hint: /^the\s+(?:one|agent)/i.test(m[1]) ? m[1] : '', question: ASKS_A_QUESTION.test(said) };
  m = WANT.exec(said);
  if (m) return { text: tidy(m[2]), hint: /^the\s+(?:one|agent)/i.test(m[1]) ? m[1] : '', question: false };
  m = PASS_ON.exec(said);
  if (m && m[1].trim().length > 2) return { text: tidy(m[1]), hint: '', question: false };
  return null;
}
const tidy = (t) => cap(String(t).trim().replace(/\s+/g, ' ').replace(/[.!]+$/, '')) + (/\?$/.test(t) ? '' : '.');

// Some instructions can't be taken back once an agent acts on them, so they are read back first and go only
// on "send it": shipping, merging, publishing, deleting, paying, signing in, sending something to someone.
const FINAL = / (merge|merging|publish|release (?:it|this|that|the app|v?\d)|cut a release|ship|deploy|push|delete|remove|drop|wipe|erase|reset|force|pay|buy|purchase|transfer|sign in|log in|login|password|email|tweet|post (?:it|this|that|on|to)|send (?:it|this|that|an?|the|them)) /;
export const needsSaying = (text) => FINAL.test(norm(text));

// Who an instruction is for, among this floor's agents ([{ id, title, working }]): { to } one agent,
// { which } several working to choose from, or { none } when nobody is working here.
export function passTarget(said, agents, hint = '') {
  const named = agentNamed(hint || said, agents);
  if (named) return { to: named };
  const working = agents.filter((a) => a.working);
  if (working.length === 1) return { to: working[0] };
  if (working.length > 1) return { which: working };
  return { none: true };
}

// The agent whose title the words name best ("the bookmark fix", "the one on the wind sensor"), if one does.
export function agentNamed(said, agents) {
  const asked = new Set(words(said));
  if (!asked.size) return null;
  let best = null;
  let score = 0;
  let tie = false;
  for (const a of agents) {
    const s = words(a.title).filter((w) => asked.has(w) || asked.has(w.replace(/s$/, '')) || asked.has(`${w}s`)).length;
    if (s > score) { best = a; score = s; tie = false; } else if (s && s === score) tie = true;
  }
  return score && !tie ? best : null;
}

// "The first one", "the second", "both", "all of them", or a title's words, after "which one?".
export function pickFrom(said, choices) {
  const t = norm(said);
  if (/ (?:both|all|all of them|everyone|every one|each) /.test(t)) return choices;
  const at = [' first ', ' second ', ' third ', ' fourth '].findIndex((w) => t.includes(w));
  if (at >= 0 && choices[at]) return [choices[at]];
  if (/ (?:last|last one) /.test(t)) return [choices[choices.length - 1]];
  const named = agentNamed(said, choices);
  return named ? [named] : null;
}

// What a lead understood: { kind, ... } or null. Kinds: update, news, who, help, pass.
export function leadAsked(text) {
  const said = String(text || '').trim();
  const pass = passAsked(said);
  if (pass) return { kind: 'pass', ...pass };
  if (HELP_ASKED.test(said)) return { kind: 'help' };
  if (NEWS_ASKED.test(said)) return { kind: 'news' };
  if (WHO_ASKED.test(said)) return { kind: 'who' };
  if (UPDATE_ASKED.test(said) || MORE_ALONE.test(said)) return { kind: 'update' };
  return null;
}

export const leadHelp = (label) => `Ask me where ${label} stands, or what's new since you last asked. Tell me what you want done, such as "tell them to test it on the spare laptop", and I'll pass it to the agent on it, or start one. I can read you what waits on you here, and you can say allow or deny.`;

// The working agents, one line each, for "who's working?".
export function leadWho(label, agents) {
  const working = agents.filter((a) => a.working);
  if (!working.length) return `Nobody is working on ${label} right now.`;
  return `${working.length === 1 ? 'One agent is' : `${working.length} agents are`} working on ${label}: ${working.slice(0, 4).map((a) => `the one on ${q(a.title)}`).join(', ')}${working.length > 4 ? `, and ${working.length - 4} more` : ''}.`;
}

/* ---------- going somewhere, and being put through ---------- */

const GO_TO = /^(?:(?:ok|okay|right|so|please|and)[,\s]+)*(?:(?:can|could|would) you\s+)?(?:please\s+)?(?:take me (?:back )?(?:to|up to|down to)|go (?:back )?(?:to|up to|down to)|show me|open(?: up)?|bring up|jump to|switch to|lets (?:go to|see|look at)|let's (?:go to|see|look at)|navigate to|head to)\s+(?:the\s+)?(.+?)[.!?]*$/i;
const HOME = /^(?:(?:go|take me)\s+)?(?:back\s+)?(?:home|to the (?:start|overview)|(?:the\s+)?overview|start page)[.!]?$/i;
const BACK = /^(?:go\s+)?back(?: please)?[.!]?$/i;

// places: [{ href, label, names: [words that mean it], floor? }], most specific first (rooms before floors).
// Gives { href, label } for "take me to Lantern", "show me the work room on Tidepool", "home", "back", or null.
export function goAsked(text, places) {
  const said = String(text || '').trim();
  if (HOME.test(said)) return { href: '#/', label: 'the overview' };
  if (BACK.test(said)) return { back: true, label: 'back' };
  const m = GO_TO.exec(said);
  if (!m) return null;
  const asked = norm(m[1].replace(/['\u2019]s\b/gi, 's').replace(/\b(?:floor|project|page|room|please)\b/gi, ''));
  let best = null;
  for (const p of places) {
    const hit = p.names.filter((n) => hasName(asked, n)).reduce((a, n) => Math.max(a, norm(n).length), 0);
    if (hit && (!best || hit > best.hit || (hit === best.hit && p.room && !best.place.room))) best = { place: p, hit };
  }
  return best ? { href: best.place.href, label: best.place.label } : { unknown: m[1] };
}

// "Talk to Lantern's lead", "put me through to Juno", "Lantern lead": the floor whose lead is meant. And
// "how's Tidepool doing?", "what's new on Kitefield?": the floor and the question, for its lead to answer.
// floors: [{ id, label, project, lead (leadOf) }]. Gives { floor, then } (then: the question, or null) or null.
const PUT_THROUGH = /^(?:(?:ok|okay|right|so|please)[,\s]+)*(?:(?:can|could) (?:i|you)\s+)?(?:please\s+)?(?:(?:talk|speak) (?:to|with)|put me through to|get me|connect me (?:to|with)|i(?:'d| would) like (?:to talk to|a word with)|let me (?:talk|speak) (?:to|with))\s+(.+?)[.!?]*$/i;
export function throughAsked(text, floors) {
  const said = String(text || '').trim();
  const bare = (t) => norm(String(t).replace(/['\u2019]s\b/gi, '')); // "Lantern's lead" names Lantern
  const named = (t) => {
    const n = bare(t);
    return floors.find((f) => hasName(n, f.lead?.name) || hasName(n, f.label) || hasName(n, f.project)) || null;
  };
  const m = PUT_THROUGH.exec(said);
  if (m) {
    const f = named(m[1]);
    if (f && (/\blead\b|\bmanager\b|\bpm\b/i.test(m[1]) || (f.lead?.name && bare(m[1]).includes(norm(f.lead.name))))) return { floor: f, then: null };
  }
  if (/^\s*(?:the\s+)?[\w' -]{2,40}?(?:'s)?\s+(?:lead|manager|pm)[.!?]*\s*$/i.test(said)) {
    const f = named(said);
    if (f) return { floor: f, then: null };
  }
  if (UPDATE_ASKED.test(said) || NEWS_ASKED.test(said) || WHO_ASKED.test(said) || /\bhow(?:'s| is)\b/i.test(said)) {
    const hits = floors.filter((f) => hasName(bare(said), f.label) || hasName(bare(said), f.project) || hasName(bare(said), f.lead?.name));
    if (hits.length === 1) return { floor: hits[0], then: said };
  }
  return null;
}

/* ---------- answering a permission out loud ---------- */

// The request read back, before any answer by voice: who wants what, and how careful to be.
export function readBack(item, label = (p) => p) {
  const risk = riskOf(item);
  const who = `${q(item.title)}${item.project ? ` on ${label(item.project)}` : ''}`;
  if (risk?.word === 'Look first') return `${who} wants your permission ${item.what}. That may touch something private, so I won't answer it by voice: it's on the screen for you.`;
  return `${who} wants your permission ${item.what}. ${risk ? `${risk.word}: ${sentence(risk.line, 140)}` : ''} Say "allow" to let it, once, or "deny".`.replace(/\s+/g, ' ');
}

// Allow or deny by voice, always in two steps: the first "allow" (or "what's waiting for permission?")
// reads the request back, and only then does "allow" or "deny" answer it, and only that one, within a
// minute. Gives null when the words weren't about answering, else { reply, pending, act?, show? }:
// act { id, behavior, item } is for the page to do; show is an item to open on screen.
// items: queue.js items (permissions only are used); pending: { id, at } from last time; opts: { now (ms),
// spoken, on (voice answers switched on), label }.
const READ_ASKED = /^(?:(?:what|which)(?:'s| is| are)? (?:waiting|asking) (?:for|on) (?:my |your )?(?:permission|approval)s?|read (?:it|that|them|the requests?|me the requests?) (?:out|again|back)?|what (?:does|did) (?:it|that one) want|(?:go|move) on|next(?: one)?|skip(?: it)?)[.?!]?$/i;
const NEXT = /^(?:next(?: one)?|skip(?: it)?|(?:go|move) on)[.!]?$/i;
export const VOICE_HOLD_MS = 60_000;
export function voiceAnswer(text, items, pending, { now = Date.now(), spoken = true, on = true, label = (p) => p } = {}) {
  const said = String(text || '').trim();
  const asks = (items || []).filter((i) => i.kind === 'permission' && i.ask?.id);
  const allow = ALLOW.test(said);
  const deny = DENY.test(said);
  const read = READ_ASKED.test(said);
  const held = pending && now - pending.at < VOICE_HOLD_MS ? asks.find((i) => i.ask.id === pending.id) : null;
  // a bare "no" with nothing read back answers whoever asked a question, never a request
  if (deny && !held && /^(?:no|nope|don'?t|do not)[.!]?$/i.test(said)) return null;
  if (!allow && !deny && !read) {
    if (held && YES.test(said)) return { reply: 'Say "allow" to let it, or "deny".', pending };
    if (held && NO.test(said) && !deny) return { reply: 'All right, I\'ll leave it waiting.', pending: null };
    return null;
  }
  if (!asks.length) return { reply: 'Nothing is waiting for your permission.', pending: null };
  if (spoken && !on && (allow || deny)) return { reply: 'Answering by voice is switched off. Answer it on the screen.', pending: null, show: asks[0] };
  if (read || !held) {
    let next = asks[0];
    if (NEXT.test(said) && held) next = asks[(asks.indexOf(held) + 1) % asks.length];
    else if (held && read && !NEXT.test(said)) next = held;
    const risk = riskOf(next);
    const more = asks.length > 1 && next === asks[0] ? ` ${asks.length - 1 === 1 ? 'One more waits' : `${asks.length - 1} more wait`} after it.` : '';
    if (risk?.word === 'Look first') return { reply: readBack(next, label) + more, pending: null, show: next };
    return { reply: readBack(next, label) + more, pending: { id: next.ask.id, at: now } };
  }
  if (spoken && riskOf(held)?.word === 'Look first') return { reply: readBack(held, label), pending: null, show: held };
  return { reply: null, pending: null, act: { id: held.ask.id, behavior: allow ? 'allow' : 'deny', item: held } };
}

// Yes or no to something the lead offered to do (start an agent, send an instruction that can't be taken back).
export const yesSaid = (text) => YES.test(String(text || '').trim());
export const noSaid = (text) => NO.test(String(text || '').trim());
