// The Arnheim page: a company shown as a building, with a panel to look around it and the
// receptionist at the front desk. It shows your own company from data/ (company.json, work.json and notes.json) when
// data/company.json is there, and otherwise the sample, a company that is made up (sample/). The
// sample's work moves on a loop (the story at the end of its work.json), so there is always
// something to see. Nothing is saved anywhere: a reload reads the files again.
import { createBrain } from './brain.js';
import { agentControls, agentQuick, agentReply, createControl, deskControls, deskStart } from './control.js';
import { FEATURES, createFeatures } from './features.js';
import { createTalkDock } from './talk-dock.js';
import { hasLead, isLeadHref, leadUpdate, voiceAnswer } from './leads.js';
import { WAITING, createLeadDesk } from './lead-desk.js';
import { allowReadsAsked, sayWaiting, together, waitingOnYou } from './queue.js';
import { inner, proofMood, proofOf } from './proof.js';
import { reviewMood, reviewOf, reviewSaid } from './review.js';
import { ROUTINES_ASKED, routineNow, sayRoutines, timesOf } from './routines.js';
import { HEALTH_ASKED, healthChip, healthOf, sayHealth } from './health.js';
import { BRIEF_ASKED, briefOf, sayBrief, sinceOf, sinceSaid } from './brief.js';
import { MEMORY_ASKED, decidedFor, rememberAsked, sayMemory } from './memory.js';
import { floorSpend, localDay, tokensSaid } from './budget.js';
import { clashesOf, sayClash, waitWords } from './clashes.js';
import { MOMENT_MOOD, conversationsAt, momentsBefore, sayMoment, touchedBy } from './replay.js';
import { RESTORE_ASKED, pointsOf, sayPoint, sayRestore, wentBack } from './restore.js';
import { HISTORY_ASKED, historyAsked, sayHistory } from './history.js';
import { LONG, WAITED_ASKED, meter, sayWaited, waitFor, waitMood, waitedSum, waitingLine, waits } from './waiting.js';
import { WEEKLY_ASKED, floorLine, sayWeek, weekReport, weekText } from './weekly.js';
import { blocks, howtoFor, howtosOf, runs, sayShelf, shelfAsked } from './howto.js';
import { icon } from './icons.js';
import { exactOf, kindWord, meaningOf, riskOf } from './risk.js';
import { createPoe, has, insertAfter, needWord, norm, poeBadge } from './poe-desk.js';
import { createGoalStand, isStandHref, standFloor, standHref } from './goal-stand.js';
import { forecastOf, pressing, usageLine, usageWords } from './usage.js';
import { CONNECTED, FIRST, UNDONE, answeringWords, codexLine, connectRequest, connectStart, firstMoment, floorFolders, updateLine } from './welcome.js';
import { TOUR as TOUR_SEEN, createTour, tourWanted } from './tour.js';
import { createAlerts, freshAlerts } from './alerts.js';
import { setVoiceSaved, voiceSaved, voiceWanted } from './voice.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const enc = encodeURIComponent;
const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

const STATUS = { needs_you: 'Needs you', working: 'In progress', waiting: 'Waiting', open: 'Open', done: 'Done', dropped: 'Dropped' };
const CLOSED = new Set(['done', 'dropped']);
const PRESENCE_TYPE_OF = { websites: 'website', email: 'email', social: 'social', domains: 'domain' };
const COMPANY_SECTIONS = ['Money', 'Legal', 'Subscriptions', 'Key dates'];
const SCENE_NAMES = { all: 'Everything', needs: 'Needs you', working: 'Working' };
const SCENE_ICON = { all: 'layers', needs: 'bell-ring', working: 'zap' };
const ROOM_ICON = {
  goals: 'target', work: 'list-checks', conversations: 'messages-square', code: 'git-pull-request', company: 'briefcase',
  library: 'library', machine: 'server', websites: 'globe', email: 'mail', social: 'at-sign', domains: 'link', lounge: 'shapes',
};
const DESK = '#/front-desk'; // the receptionist's page: a tap on them in the building, or the ... menu
const TOP_ROUTES = new Set([undefined, 'activity', 'company', 'front-desk']);
const TAB_KEYS = { 1: '#/', 2: '#/activity', 3: '#/company' };
const CODEX = 'arnheim-codex'; // whether connecting from the page put Arnheim's hooks into Codex too
const WELCOMED = 'arnheim-welcomed'; // the sample's welcome card was answered in this browser
const LIST_ONLY = 'arnheim-list-only'; // Hide the building: the list alone, on this device
// The receptionist's name, from the company map (receptionist in company.json). With none, they
// are just the receptionist.
const deskName = () => org?.receptionist?.name?.trim() || '';
const deskAsk = () => (deskName() ? `Ask ${deskName()}, the receptionist` : 'Ask the receptionist');

let org = null; // the company map: floors and rooms
let work = null; // what is going on in it
let dir = 'sample'; // where they came from: data (your own company) or sample (made up)
let firstRun = false; // no data/company.json yet: Needs you and Settings show the one step to see your own work
let feeds = []; // files in data/ that tools keep up to date (docs/connect.md)
// Control of your Claude Code agents, with serve.py --control and your own company (control.js).
const control = createControl({ busy: () => !!building?.walking?.() });
// The receptionist's and the assistant's brain, with serve.py --brain: they answer with Claude,
// through Claude Code on the computer that serves the page (brain.js). Off otherwise.
const brain = createBrain();
const features = createFeatures(); // talking from any screen, the floors' leads, answering by voice (features.js)
// This browser's own small memories (localStorage, or sessionStorage for this tab), none of which may stop the page.
const kept = (key, where = 'localStorage') => { try { return window[where].getItem(key); } catch { return null; } };
const keep = (key, value, where = 'localStorage') => { try { window[where].setItem(key, value); } catch { /* a private window: it lasts this visit */ } };
const unkeep = (key, where = 'localStorage') => { try { window[where].removeItem(key); } catch { /* nothing kept */ } };
const keptJson = (key, where) => { try { return JSON.parse(kept(key, where) || 'null'); } catch { return null; } };
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
// Desktop alerts when an agent needs you, this browser's own choice (alerts.js), and the first tour (tour.js).
const alerts = createAlerts({ win: window, storage: (() => { try { return window.localStorage; } catch { return null; } })() });
const tour = createTour();
let dock = null; // the Talk panel (talk-dock.js)
let starting = null; // an agent the receptionist was asked to start, waiting for your word
let controlNote = ''; // what came of the last thing done from the panel
let noteUsed = false; // it shows once a page, in the first place that has room for it (render resets this)
let noteFresh = false; // a note just made: render brings it into view
const noteOnce = (cls = '') => {
  if (!controlNote || noteUsed) return null;
  noteUsed = true;
  return h(`p.small.muted.control-note${cls}${cls && /^Allowed/.test(controlNote) ? '.ok' : ''}`, { role: 'status' }, controlNote);
};
const lastFeed = new Map();
let workSig = ''; // the work as last read, to tell when it has changed
const mine = []; // tasks the receptionist took down in this tab, kept through each fresh read
const dropped = new Set(); // and the ones dropped in it
const mineMemory = []; // decisions remembered in this tab, for a made-up company
const forgotten = new Set(); // and the ones forgotten in it
const FOLLOW_MS = 4000;
let poe = null;
let building = null;
let route = {};
let sceneId = 'all';
let playing = true;
let storyAt = 0;
let pending = false;
let added = 0;
const happened = []; // newest first: { line, at }

/* ---------- small helpers ---------- */

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

const count = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const title = (text) => h('h2', { id: 'view-title', tabindex: -1 }, text);
const dot = (mood) => h(`span.dot.s-${mood || 'quiet'}`, { 'aria-hidden': 'true' });
const row = (href, main, sub, mood) => h('li', h(href ? 'a.row' : 'div.row', href ? { href } : {},
  dot(mood), h('span.row-main', h('span.row-title', main), sub && h('span.row-sub', sub))));
const btn = (label, onclick, cls = '', glyph = null) => h(`button.btn${cls}`, { type: 'button', onclick }, glyph && icon(glyph, 15), label);
const sectHead = (glyph, text) => h('div.sect-head', icon(glyph, 18), h('h3.sect-title', text));
const chip = (line) => h(`span.state.k-${line.kind}`, line.text);
const empty = (text) => h('p.muted.small', text);

function agoText(at) {
  const s = Math.max(0, Math.round((Date.now() - at) / 1000));
  if (s < 10) return 'just now';
  if (s < 60) return `${s} seconds ago`;
  return s < 120 ? 'a minute ago' : `${Math.round(s / 60)} minutes ago`;
}

/* ---------- reading the company ---------- */

// A company map with "sample" in it is made up, and the page says so wherever it shows it.
const madeUp = () => !!org.sample;
// Opened from another device (serve.py --lan or --share): control, the brain and the voice stay on the computer it runs on.
const fromAway = () => !['127.0.0.1', 'localhost', '[::1]', '::1'].includes(location.hostname);
const sampleLine = () => (typeof org.sample === 'string' ? org.sample : `${org.company} is made up.`);
const hasStory = () => work.story.length > 0;
const floors = () => [...org.floors, org.lobby, org.basement].filter(Boolean);
const roomsOf = (floor) => [...(floor.rooms || org.rooms), ...(floor.extraRooms || [])];
const floorOf = (project) => org.floors.find((f) => f.project === project);
const rank = (project) => { const i = org.floors.findIndex((f) => f.project === project); return i < 0 ? 99 : i; };
const byProject = (list) => [...list].sort((a, b) => rank(a.project) - rank(b.project));
const openTasks = () => byProject(work.tasks.filter((t) => !CLOSED.has(t.status)));
const kindOf = (floor, room) => room.kind || (floor === org.basement ? (room.id === 'library' ? 'library' : 'machine') : room.id);
const machineLabel = (id) => org.basement?.rooms.find((r) => r.id === id)?.label || id;
// Everything waiting on you, from every agent and the work, most urgent first (queue.js).
// What a floor's agents have spent today against its budget (budget.js), as far as control has let them go.
const spendOf = (floor) => (floor?.project ? floorSpend(org, floor, work.conversations, control.on ? control.timesAllowed(floor.project) : 1, localDay(), work.ended || []) : null);
// The brief: what happened since your last visit. Your own company's last visit is kept in this browser
// (the sample's story is the same every time, so it always starts twelve hours back).
const SEEN = 'arnheim-seen';
let lastSeen = null;
try { lastSeen = Number(localStorage.getItem(SEEN)) || null; } catch { lastSeen = null; }
const markSeen = () => { try { localStorage.setItem(SEEN, String(Math.round(Date.now() / 1000))); } catch { /* the next brief starts twelve hours back */ } };
addEventListener('pagehide', markSeen);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'hidden') markSeen(); });
let briefTold = false; // on a walk, the receptionist greets you with it once a visit
const briefNow = () => briefOf({ moments: [...yesterday.moments, ...history], conversations: work.conversations, routines: routinesNow(),
  waiting: waitingNow(), since: sinceOf(dir === 'data' ? lastSeen : null) });

const waitingNow = () => {
  const { asks, runs } = control.on ? control.state() : { asks: work.asks || [], runs: [] };
  // a floor's budget question goes as soon as it is under budget again, without waiting for the hook
  const tasks = openTasks().filter((t) => !t.budget || spendOf(floorOf(t.budget))?.over !== false);
  return waitingOnYou({ asks: asks.filter((a) => !answered.has(a.id)), runs, conversations: work.conversations, tasks, hushed: answeredKeys });
};
// Permissions answered here, left out of the list before the next look at control catches up, and their
// conversations' keys with the time, so the count drops at once instead of the request coming back as its question.
const answered = new Set();
const answeredKeys = new Map();
const markAnswered = (id) => {
  answered.add(id);
  const a = [...(control.on ? control.state().asks : []), ...(work.asks || [])].find((x) => x.id === id);
  if (a?.key) answeredKeys.set(a.key, Date.now() / 1000);
  return () => { answered.delete(id); if (a?.key) answeredKeys.delete(a.key); };
};
const answerAsk = (id, behavior) => {
  const undo = markAnswered(id);
  // the sample's own requests are answered here: the company is made up, so nothing runs
  if ((work.asks || []).some((a) => a.id === id && a.sample)) return Promise.resolve({ sample: true });
  return control.answer(id, behavior).catch((error) => { undo(); throw error; });
};
const canAnswer = (i) => i.kind === 'permission' && (control.on || !!i.ask?.sample);
// One answer per request: a quick second press, before the list has redrawn, never answers it again, and the
// next key waits a second, as when the first item changes.
const answerOnce = (i, behavior) => {
  if (answered.has(i.ask.id)) return;
  focusSince = Date.now();
  controlDone(answerAsk(i.ask.id, behavior), answeredSaid(behavior, i));
};
const answeredSaid = (behavior, i) => (r) => `${behavior === 'allow' ? 'Allowed' : 'Denied'}: ${i ? `${i.title}, ${i.what}` : 'that'}${behavior === 'allow' ? ', just this once' : ''}.${r?.sample ? ' The company is made up, so nothing really ran.' : ''}`;
const moodOf = (t) => (t.status === 'needs_you' ? 'needs' : t.status === 'working' ? 'working' : 'quiet');
const taskHref = (t) => `#/${floorOf(t.project)?.id}/work/${enc(t.id)}`;
const goalHref = (g) => `#/${floorOf(g.project)?.id}/goals/${enc(g.id)}`;
const convoHref = (c) => `#/${floorOf(c.project)?.id}/conversations/${enc(c.id)}`;
const presenceRoom = (type) => Object.keys(PRESENCE_TYPE_OF).find((id) => PRESENCE_TYPE_OF[id] === type) || 'websites';
const presenceHref = (e) => `#/${org.lobby?.id}/${presenceRoom(e.type)}/${enc(e.id)}`;
const isDown = (e) => !!e.link && e.up === false;

// One room's live data, the same plain shape any page gives the building through setLive().
function roomModel(floor, room) {
  const kind = kindOf(floor, room);
  const base = `#/${floor.id}/${room.id}`;
  const project = floor.project;
  if (floor === org.lobby) {
    const list = work.presence.filter((e) => e.type === PRESENCE_TYPE_OF[room.id]);
    const down = list.filter(isDown).length;
    return {
      state: down ? 'failed' : 'quiet', big: list.length || null, detail: list.length ? (down ? `listed, ${down} not answering` : 'listed') : 'None yet',
      items: list.map((e) => ({ id: e.id, title: e.name, sub: e.status, href: presenceHref(e), live: e.status === 'Live', up: !!e.link && !!e.up, mood: isDown(e) ? 'failed' : undefined })),
    };
  }
  if (kind === 'library') {
    const shelf = howtosOf(org).map((x) => ({ id: `howto:${x.id}`, title: x.title, sub: `How-to${x.project ? `, for ${floorOf(x.project)?.label || x.project}` : ''}`, status: 'How-to', href: howtoHref(x) }));
    const n = work.library.length + shelf.length;
    return { state: 'quiet', big: n || null, detail: n ? 'on the shelves' : 'Nothing on the shelves yet',
      items: [...shelf, ...work.library.map((b) => ({ id: b.id, title: b.name, sub: b.status, status: b.status, href: `${base}/${enc(b.id)}` }))] };
  }
  if (kind === 'machine') {
    const m = work.machines.find((x) => x.id === room.id) || {};
    const running = work.jobs.filter((j) => j.machine === room.id && j.state === 'running').length;
    const info = running ? { state: 'working', big: 'Running', detail: count(running, 'job', 'jobs'), working: true }
      : m.online ? { state: 'quiet', big: 'Online', detail: 'Idle' } : { state: 'quiet', big: 'Offline', detail: 'Switched off' };
    return { ...info, running, online: !!m.online, title: room.label, sub: `${info.big}. ${info.detail}`, href: base };
  }
  if (kind === 'goals') {
    const list = work.goals.filter((g) => g.project === project);
    const open = list.filter((g) => g.status !== 'reached').length;
    const reached = list.length - open;
    return {
      state: 'quiet', big: list.length ? open : null, detail: list.length ? (reached ? `open, ${reached} reached` : 'open') : 'None set yet',
      items: list.map((g) => ({ id: g.id, title: g.title, reached: g.status === 'reached', sub: g.status === 'reached' ? 'Reached' : 'Open', href: goalHref(g) })),
      // none yet: a flagpole to set one where you stand (goal-stand.js)
      add: list.length ? null : { title: `No goal yet for ${floor.label}`, sub: 'Say it, or tap to type it', href: standHref(floor.id) },
    };
  }
  if (kind === 'work') {
    const list = openTasks().filter((t) => t.project === project).sort((a, b) => Number(b.status === 'needs_you') - Number(a.status === 'needs_you'));
    const needs = list.filter((t) => t.status === 'needs_you').length;
    return {
      state: needs ? 'needs' : 'quiet', big: list.length, detail: needs ? `open, ${needs === 1 ? '1 needs you' : `${needs} need you`}` : 'open',
      items: list.map((t) => ({ id: t.id, title: t.title, sub: STATUS[t.status], href: taskHref(t), mood: moodOf(t) })),
    };
  }
  if (kind === 'conversations') {
    const list = work.conversations.filter((c) => c.project === project).sort((a, b) => (!!b.working - !!a.working) || (!!b.check - !!a.check) || ((b.at || 0) - (a.at || 0)));
    const working = list.filter((c) => c.working).length;
    const checks = list.filter((c) => c.check);
    const proofs = new Map(list.map((c) => [c.id, proofOf(c)]));
    const reviews = new Map(list.map((c) => [c.id, reviewOf(c)]));
    const failed = list.filter((c) => !c.working && (proofs.get(c.id)?.state === 'failed' || reviews.get(c.id)?.state === 'failed')).length;
    const proven = checks.filter((c) => proofs.get(c.id)?.state === 'proven' || (reviews.get(c.id)?.state === 'passed' && proofs.get(c.id)?.state !== 'failed')).length;
    // Its light: amber while an agent there waits on your answer, red while any work failed its check, plain once
    // what's finished is checked (the list marks it), blue while one works.
    const asking = waitingNow().some((i) => i.project === project && (i.kind === 'permission' || i.kind === 'question'));
    const state = asking ? 'needs' : failed ? 'failed' : checks.length ? (proven === checks.length ? 'ok' : 'check') : working ? 'working' : 'quiet';
    return {
      state, big: list.length, working: working > 0,
      detail: [checks.length ? `open, ${checks.length} to check` : 'open', failed && `${failed} not proven`].filter(Boolean).join(', '),
      items: list.map((c) => {
        const pr = proofs.get(c.id);
        const rv = reviews.get(c.id);
        const now = [c.working ? (rv?.state === 'reviewing' ? 'In the review line' : rv?.state === 'sent back' ? 'Sent back, fixing it' : 'Working now') : c.check ? 'To check' : 'Quiet', c.agent].filter(Boolean).join('. ');
        const word = c.working ? null : rv?.word || pr?.word;
        return { id: c.id, title: c.title, working: !!c.working, check: !!c.check, proof: pr?.state || null, sub: word ? `${now}. ${word}` : now,
          mood: c.working ? 'working' : reviewMood(rv) || proofMood(pr) || undefined, href: convoHref(c) };
      }),
    };
  }
  if (kind === 'code') {
    const prs = work.pullRequests.filter((p) => p.project === project);
    const copies = work.copies.filter((c) => c.project === project);
    return {
      state: 'quiet', big: null, detail: `${count(prs.length, 'pull request', 'pull requests')}, ${copies.length ? `${copies.length} unsaved` : 'all saved'}`,
      prs: prs.map((p) => ({ id: p.number, title: `#${p.number} ${p.title}`, draft: !!p.draft, sub: p.draft ? 'Draft' : 'Ready for review', href: `${base}/pr/${p.number}` })),
      copies: copies.map((c) => ({ id: c.id, title: c.name, sub: count(c.changes, 'unsaved change', 'unsaved changes'), href: `${base}/copy/${enc(c.id)}` })),
      empty: prs.length || copies.length ? null : { title: 'Nothing to review', sub: 'No pull requests, and all the work is saved', href: base },
    };
  }
  if (kind === 'company') {
    const n = work.company.length;
    return {
      state: 'quiet', big: n || null, detail: n ? (n === 1 ? 'note' : 'notes') : 'Nothing filed yet',
      sections: COMPANY_SECTIONS.map((name) => {
        const k = work.company.filter((e) => e.section === name).length;
        return { id: name, title: name, count: k, sub: k ? count(k, 'note', 'notes') : 'Nothing here yet', href: `${base}/section/${enc(name)}` };
      }),
    };
  }
  return { state: 'quiet', big: null, detail: '' };
}

function floorLines(floor) {
  if (floor === org.basement) {
    const running = work.jobs.filter((j) => j.state === 'running').length;
    const waiting = work.jobs.filter((j) => j.state === 'queued').length;
    if (!running && !waiting) return [{ text: 'Queue is empty', kind: 'quiet' }];
    return [{ text: `Queue: ${[running && `${running} running`, waiting && `${waiting} waiting`].filter(Boolean).join(', ')}`, kind: running ? 'working' : 'quiet' }];
  }
  if (floor === org.lobby) {
    const down = work.presence.filter(isDown).length;
    return [down ? { text: `${down} not answering`, kind: 'failed' } : { text: `${count(work.presence.length, 'place', 'places')} listed`, kind: 'quiet' }];
  }
  const lines = [];
  const health = healthChip(healthOf(floor.project, work));
  if (health) lines.push(health);
  if (openTasks().some((t) => t.project === floor.project && t.status === 'needs_you') || waitingNow().some((i) => i.project === floor.project && (i.kind === 'permission' || i.kind === 'question'))) lines.push({ text: 'Needs you', kind: 'needs' });
  if (work.conversations.some((c) => c.project === floor.project && c.working)) lines.push({ text: 'Working now', kind: 'working' });
  if (clashesOf(work.conversations).some((c) => c.project === floor.project)) lines.push({ text: 'Two agents on the same files', kind: 'failed' });
  const spend = spendOf(floor);
  if (spend) lines.push({ text: spend.text[0].toUpperCase() + spend.text.slice(1), kind: spend.over ? 'failed' : 'quiet' });
  return lines.length ? lines : [{ text: 'Quiet', kind: 'quiet' }];
}

// A floor's label on the building: at most two short words, the most pressing first. The whole line is in Activity.
const SHORT = [
  [(l) => l.kind === 'needs', () => 'Needs you'],
  [(l) => l.kind === 'failed' && /budget/i.test(l.text), () => 'Over budget'],
  [(l) => l.kind === 'failed' && /same files/i.test(l.text), () => 'Two agents, one file'],
  [(l) => l.kind === 'failed', (l) => (/to fix/i.test(l.text) ? l.text : 'Something to fix')],
  [(l) => l.kind === 'working' && /^Working now$/.test(l.text), () => 'Working'],
];
function floorShort(lines) {
  const words = [];
  let kind = null;
  for (const [is, say] of SHORT) {
    const l = lines.find(is);
    if (!l || words.length >= 2) continue;
    const w = say(l);
    if (!words.includes(w)) { words.push(w); kind = kind || l.kind; }
  }
  if (words.length) return { label: words.join(' · '), kind };
  const only = lines.find((l) => !/tokens today$/i.test(l.text)) || { text: 'Quiet', kind: 'quiet' };
  return { label: only.text, kind: only.kind };
}

function liveModel() {
  const model = {};
  for (const floor of floors()) {
    const lines = floorLines(floor);
    model[`floor:${floor.id}`] = { lines, ...floorShort(lines) };
    for (const room of roomsOf(floor)) model[`${floor.id}/${room.id}`] = roomModel(floor, room);
  }
  return model;
}

/* ---------- the receptionist: plain facts from the company's files, no AI ---------- */

function poeFacts() {
  const open = openTasks();
  const link = (t) => ({ title: t.title, sub: t.project, href: taskHref(t) });
  const convo = (c) => ({ title: c.title, sub: c.project, href: convoHref(c) });
  const needs = waitingNow(); // the one list: permissions, questions, your tasks and agents just finished
  const finished = new Set(needs.filter((i) => i.kind === 'turn').map((i) => i.key)); // already in it
  const machines = org.basement ? org.basement.rooms.filter((r) => kindOf(org.basement, r) === 'machine').map((r) => ({ id: r.id, label: r.label, ...roomModel(org.basement, r) })) : [];
  return {
    needs: needs.map(waitingLink),
    needsBy: Object.fromEntries(org.floors.map((f) => [f.project, needs.filter((i) => i.project === f.project).length])),
    openBy: Object.fromEntries(org.floors.map((f) => [f.project, open.filter((t) => t.project === f.project).length])),
    later: 0,
    toCheck: byProject(work.conversations.filter((c) => c.check && !finished.has(c.id))).map(convo),
    withHelper: [],
    waiting: open.filter((t) => t.status === 'waiting').map(link),
    tasks: open.map(link),
    working: byProject(work.conversations.filter((c) => c.working)).map(convo),
    queue: {
      ok: true,
      running: work.jobs.filter((j) => j.state === 'running').map((j) => ({ title: j.name, sub: machineLabel(j.machine) })),
      waiting: work.jobs.filter((j) => j.state === 'queued').length,
    },
    machines,
    presence: work.presence.map((e) => ({ name: e.name, type: e.type, link: e.link, status: e.status, project: e.project, href: presenceHref(e) })),
    goals: work.goals.filter((g) => g.status !== 'reached').map((g) => ({ title: g.title, sub: g.project, project: g.project, href: goalHref(g) })),
    prs: Object.fromEntries(org.floors.filter((f) => work.pullRequests.some((p) => p.project === f.project)).map((f) => [f.project, work.pullRequests.filter((p) => p.project === f.project).length])),
  };
}

// A goal set at a Goals room's flagpole (goal-stand.js), in this tab only, like the receptionist's tasks.
const myGoals = [];
const stands = new Map(); // each floor's flagpole conversation
function addGoal(project, title) {
  const goal = { id: `mine${myGoals.length + 1}`, project, title, status: 'open', note: 'Set at the Goals room\'s flagpole. It lives in this tab only: nothing is saved.' };
  myGoals.push(goal);
  work.goals.push(goal);
  refresh();
  return goal;
}
function standOf(who) {
  const floor = org.floors.find((f) => f.id === standFloor(who?.href));
  if (!floor?.project) return null;
  if (!stands.has(floor.id)) stands.set(floor.id, createGoalStand({ label: floor.label, save: (title) => { addGoal(floor.project, title); }, kept: 'It lasts while this tab is open.' }));
  return stands.get(floor.id);
}

// The receptionist can add a task and drop it again, in this tab only.
async function addTask({ project, title: text }) {
  added += 1;
  const task = { id: `new${added}`, project, title: text, status: 'needs_you', note: `Taken down by ${deskName() || 'the receptionist'} when you asked. It lives in this tab only: nothing is saved.` };
  mine.push(task);
  work.tasks.push(task);
  refresh();
  return { ok: true, task };
}

async function dropTask(id) {
  const task = work.tasks.find((t) => t.id === id);
  if (!task) return { ok: false, error: 'that task is not here any more' };
  task.status = 'dropped';
  dropped.add(id);
  refresh();
  return { ok: true };
}

// What the rules answer even with the brain on: at once, and nothing Claude could be talked into
// instead. A refusal stays a refusal.
const RULED = new Set(['refuse', 'greeting', 'tour', 'waiting', 'memory', 'routines', 'health', 'brief', 'waited', 'weekly', 'history', 'restore', 'usage']);
const ruledBy = (t) => (RULED.has(t.id) ? { ...t, answer: (c) => { const a = t.answer(c); return a && { ...a, ruled: t.id }; } } : t);

function setupDesk() {
  const called = deskName() || 'The receptionist';
  // "What's waiting on me?", "what needs me?" for the whole building: the one list, said as on a walk.
  // For one floor, the rules' own answer, from the same list.
  // "What have we decided?": the company's memory.
  const memory = {
    id: 'memory',
    answer: (c) => MEMORY_ASKED.test(c.text) && { lines: [sayMemory(memoryNow())], go: c.go('#/company', 'Show me') },
  };
  const brief = {
    id: 'brief',
    answer: (c) => !c.floor && BRIEF_ASKED.test(c.text) && { lines: [sayBrief(briefNow(), (p) => floorOf(p)?.label || p)], go: c.go('#/', 'Show me') },
  };
  const health = {
    id: 'health',
    answer: (c) => !c.floor && HEALTH_ASKED.test(c.text) && { lines: [sayHealth(org.floors, work)], go: c.go('#/activity', 'Show me') },
  };
  // "How much usage is left?", "when will I hit my limit?": the plan's limits, from Claude Code and Codex (usage.js).
  const usage = {
    id: 'usage',
    answer: (c) => USAGE_ASKED.test(c.text) && { lines: [sayUsage()], go: c.go('#/activity', 'Show me') },
  };
  const label = (p) => floorOf(p)?.label || p;
  const waited = {
    id: 'waited',
    answer: (c) => WAITED_ASKED.test(c.text) && {
      lines: [sayWaited(waits(history, Date.now() / 1000, heldNow()), waitingNow(), label)],
      go: c.go('#/activity', 'Show me'),
    },
  };
  const weekly = {
    id: 'weekly',
    answer: (c) => !c.floor && WEEKLY_ASKED.test(c.text) && { lines: [sayWeek(weekReport(weekDays(), Date.now() / 1000, heldNow()), label)], go: c.go('#/activity', 'Show me') },
  };
  const shelf = {
    id: 'howto',
    answer: (c) => {
      const all = howtosOf(org);
      if (shelfAsked(c.text)) return { lines: [sayShelf(all, label)] };
      const x = howtoFor(c.text, c.floor ? howtosOf(org, c.floor.project) : all);
      return x && { lines: [`There's a how-to for that: "${x.title}", on the shelf in the Library. Every agent${x.project ? ` on ${label(x.project)}` : ''} is told it as it starts.`], go: c.go(howtoHref(x), 'Open it') };
    },
  };
  const past = {
    id: 'history',
    answer: (c) => HISTORY_ASKED.test(c.text) && { lines: [sayHistory(weekMoments(), historyAsked(c.text, new Date(), c.floor?.project), label, clockOf)] },
  };
  const restorePoints = {
    id: 'restore',
    answer: (c) => RESTORE_ASKED.test(c.text) && { lines: [sayRestore(work.restore, (p) => floorOf(p)?.label || p, clockOf)] },
  };
  const routines = {
    id: 'routines',
    answer: (c) => ROUTINES_ASKED.test(c.text) && { lines: [sayRoutines(routinesNow(), (p) => floorOf(p)?.label || p)], go: c.go('#/activity', 'Show me') },
  };
  const waiting = {
    id: 'waiting',
    answer: (c) => !c.floor && WAITING.test(c.text) && {
      lines: [sayWaiting(waitingNow(), (p) => floorOf(p)?.label || p)],
      go: c.go('#/', 'Show me the list'),
    },
  };
  const real = {
    id: 'sample',
    answer: (c) => has(c.q, ['real', 'made up', 'fake', 'sample', 'demo', 'invented', 'pretend']) && {
      lines: !madeUp() ? [`This is ${org.company}'s own building, drawn from its own files. I only say what they hold.`]
        : [sampleLine(), hasStory() && 'The work you see moving is a short story on a loop, so the building has something to show. Pause the sample, in the ... menu at the top, stops it.'].filter(Boolean),
    },
  };
  const howTo = {
    id: 'how-to',
    answer: (c) => has(c.q, ['task', 'goal']) && has(c.q, ['add', 'new', 'set', 'write', 'make', 'create']) && {
      lines: ['Tell me "remind me to ..." and I will add it as a task, in this tab only.', dir === 'data'
        ? 'Goals and everything else come from the company\'s own files, data/company.json and data/work.json, and from any tools connected to it. A change to the work shows within a few seconds.'
        : 'Goals and everything else come from the sample files, sample/company.json and sample/work.json. To make the building your own, run python3 connect/setup.py in Arnheim\'s folder.'],
    },
  };
  poe = createPoe({
    h, btn, title, row, taskHref, addTask, dropTask,
    org: () => org,
    facts: poeFacts,
    focusModel: (floorId) => (floorId ? building?.focus({ floor: floorId }) : focusBuilding()),
    reduced: reducedMotion,
    words: {
      place: `This is Arnheim, showing ${org.company}${madeUp() ? ', a company that is made up' : ''}. Each floor is a project and each room holds one kind of thing. The light shows what is happening.`,
      hints: ['What is Arnheim?', 'What needs me?', "What's running?", 'Who runs this company?', 'Where is the website?', 'Is this real?', 'What do the colours mean?'],
      role: brain.on ? 'Receptionist. Answers with Claude, through Claude Code on this computer.'
        : madeUp() ? 'Receptionist. Every answer comes from the sample company.' : `Receptionist. Every answer comes from ${org.company}'s own files.`,
      me: brain.on ? [
        `I'm ${deskName() ? `${deskName()}, the receptionist` : 'the receptionist'}. I answer with Claude, through Claude Code on this computer, and about ${org.company} I only say what this building shows.`,
        'I can also take a message: say "remind me to ..." and I will add it as a task.',
      ] : undefined,
      unknown: `I don't know that, and I won't guess. I only know what ${madeUp() ? 'the sample company holds' : `${org.company}'s files hold`}.`,
      note: `${brain.on ? `${called} answers with Claude, through Claude Code on this computer and on your own Claude plan: your questions go there, with the building's facts. Greetings, refusals and tasks stay with the building's own rules. ` : ''}${called} can add a task and undo it, in this tab only. ${dir === 'data' ? `What you ask ${called} to remember is kept for every agent while control is on. ` : 'Nothing is saved. '}${called} never merges, publishes, runs jobs or signs in.`,
      added: 'It is in the Work room now, in this tab only.',
      keys: `1 Needs you, 2 Activity, 3 Settings. Esc goes back. Arrow keys turn the building, plus and minus zoom. They do nothing while you are typing.`,
    },
    topics: (list) => {
      const all = insertAfter(insertAfter(list, 'thanks', [real]), 'tour', [howTo]);
      // "How long have they been waiting on me?" before "what's waiting on me?".
      all.splice(Math.max(0, all.findIndex((t) => t.id === 'needs')), 0, waited, waiting, memory, routines, restorePoints);
      // Before "what's happening" and "what's running", which would take "catch me up" and "how are the
      // projects doing?" for themselves.
      all.splice(Math.max(0, all.findIndex((t) => t.id === 'happening')), 0, brief, weekly, health, usage, past);
      // Before the receptionist's own "how do I ..." answers about the building, a how-to of the company's that fits.
      all.splice(Math.max(0, all.findIndex((t) => t.id === 'how-to' || t.id === 'handoff')), 0, shelf);
      return brain.on ? all.map(ruledBy) : all;
    },
    // A typed question at the desk: Claude's answer as it comes, with the brain on.
    // "Allow all the reads", with control on: done, then said.
    think: (text, a) => {
      const reads = control.on ? allowReadsAsked(text, waitingNow()) : null;
      if (reads) return (async function* allowed() { yield await allowReads(reads); })();
      const decision = rememberAsked(text);
      if (decision) return (async function* remembered() { yield await rememberIt(decision); })();
      // Work handed out in words: "get someone to fix the login bug on Lantern", then "start it".
      const start = control.on ? deskStart(control, text, starting) : null;
      if (start && start.reply != null) {
        starting = start.pending;
        return (async function* started() {
          const said = await start.reply;
          if (start.started) watchStart(start.started);
          yield said;
        })();
      }
      return brain.on && !a.ruled && !a.offer ? claudeSays('receptionist', text) : null;
    },
  });
}

/* ---------- the brain: Claude answers for the receptionist and the assistant (brain.js) ---------- */

const BRAIN_LIST = 25; // at most this many of anything in one section, then how many more

// What the building knows, for Claude, in named sections: whichever company it shows (the sample,
// or yours from data/ with its feeds, such as your Claude Code conversations) and, with control on,
// the agents started from here and what waits for your permission. The server sends every section
// with the first question and then only those that changed, so any time in them is a clock time,
// never "a minute ago", which would change every minute.
function brainFacts() {
  const out = [];
  const add = (name, lines) => {
    const text = [lines].flat(Infinity).filter((x) => x != null && x !== false && x !== '').join('\n');
    if (text) out.push([name, text]);
  };
  const clock = (at) => new Date(at < 1e12 ? at * 1000 : at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const some = (list, line) => [...list.slice(0, BRAIN_LIST).map(line), list.length > BRAIN_LIST && `And ${list.length - BRAIN_LIST} more.`];
  const q = (text) => `"${text}"`;
  const label = (project) => floorOf(project)?.label || project;
  const asks = control.on ? control.state().asks : [];
  const runs = control.on ? control.state().runs.filter((r) => !work.conversations.some((c) => c.id === r.key)) : [];
  const needs = openTasks().filter((t) => t.status === 'needs_you');
  const checks = byProject(work.conversations.filter((c) => c.check));
  const waiting = openTasks().filter((t) => t.status === 'waiting');
  const talking = byProject(work.conversations.filter((c) => c.working));
  const jobs = work.jobs.filter((j) => j.state === 'running');

  add('Company', [
    `${org.company}.${org.about ? ` ${org.about}` : ''}`,
    madeUp() ? [sampleLine(), hasStory() && 'Its work moves on a short loop, a story told over and over so the building has something to show.']
      : `This is ${org.company}'s own building, drawn from its own files.`,
    org.mission && `Its mission, in its founder's words: ${q(org.mission)}.`,
    org.founder?.name && `Its founder: ${org.founder.name}${org.founder.title ? `, ${org.founder.title}` : ''}.`,
    `The receptionist, at the front desk${org.lobby ? ` in ${org.lobby.label}` : ''}: ${deskName() || 'not named'}.`,
    org.assistant?.name && `The founder's assistant, in the founder's office at the top: ${org.assistant.name}${org.assistant.title ? `, ${org.assistant.title}` : ''}.`,
    `Today is ${new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}.`,
  ]);
  add('The building', [
    'Arnheim shows the company as a building you can turn and walk through: each project is a floor, each kind of work a room, and the people at work are its agents. The light shows what is happening: amber needs you, blue is working now, red means something is wrong, and plain is quiet.',
    'Arnheim is free and open, and named after Edgar Allan Poe\'s story "The Domain of Arnheim", about a man who shapes a landscape into a world of its own.',
    `Floors, top to bottom: ${[org.founder && "the founder's office", ...org.floors.map((f) => f.label)].filter(Boolean).join(', ')}${org.lobby ? `, then ${org.lobby.label} (the lobby)` : ''}${org.basement ? `, and ${org.basement.label} (the basement)` : ''}. A lift joins them.`,
  ]);
  add('Waiting on you, as one list (agents and tasks)', [sayWaiting(waitingNow(), label)]);
  add('Company memory: what every agent is told as it starts', memoryNow().length ? memoryNow().map((r) => `- ${r.text}`) : ['Nothing is remembered yet.']);
  add('Today, moment by moment (newest first)', momentsBefore(history, Date.now() / 1000, 25).map((m) => `- At ${clock(m.at)}, on ${label(m.project)}: ${sayMoment(m)}`));
  add('Agents on the same files', clashesOf(work.conversations).map((x) => `- ${sayClash(x)} On ${label(x.project)}.`));
  add("Spent today, in new tokens, against each floor's budget", org.floors.map((f) => [f, spendOf(f)]).filter(([, s]) => s).map(([f, s]) => `- ${f.label}: ${s.text}.`));
  if (control.on && control.paused()) add('Every agent', ['Paused from the building, until it resumes them.']);
  add('Needs you', [
    needs.length ? [`${needWord(needs.length)}, in this order:`, some(needs, (t) => `- ${q(t.title)}, on ${label(t.project)}`)] : 'Nothing needs you right now.',
    checks.length > 0 && [`${count(checks.length, 'conversation has', 'conversations have')} something for you to check:`, some(checks, (c) => `- ${q(c.title)}, on ${label(c.project)}`)],
    waiting.length > 0 && [`${count(waiting.length, 'task is', 'tasks are')} waiting on something else:`, some(waiting, (t) => `- ${q(t.title)}, on ${label(t.project)}`)],
    asks.length > 0 && ['Waiting for your permission:', asks.map((a) => `- ${a.what}`)],
  ]);
  add('Working now', [
    !talking.length && !jobs.length && 'Nothing is working right now.',
    talking.length > 0 && [`${count(talking.length, 'conversation is', 'conversations are')} working:`, some(talking, (c) => `- ${q(c.title)}, on ${label(c.project)}`)],
    jobs.length > 0 && [`${count(jobs.length, 'job is', 'jobs are')} running:`, some(jobs, (j) => `- ${q(j.name)}, on the ${machineLabel(j.machine)}`)],
  ]);
  for (const floor of org.floors) {
    const p = floor.project;
    const tasks = openTasks().filter((t) => t.project === p);
    const goals = work.goals.filter((g) => g.project === p);
    const prs = work.pullRequests.filter((x) => x.project === p);
    const copies = work.copies.filter((c) => c.project === p);
    add(`Floor: ${floor.label}`, [
      `${floor.label}${p !== floor.label ? ` (the project ${p})` : ''}: ${floor.about || 'nothing is written about it yet.'}`,
      floor.story,
      `Rooms: ${roomsOf(floor).map((r) => r.label).join(', ')}.`,
      tasks.length ? ['Open tasks:', some(tasks, (t) => `- ${q(t.title)}: ${(STATUS[t.status] || t.status || 'open').toLowerCase()}`)] : 'No open tasks.',
      goals.length ? ['Goals:', some(goals, (g) => `- ${q(g.title)}: ${g.status === 'reached' ? 'reached' : 'open'}`)] : 'No goals written yet.',
      prs.length > 0 && ['Open pull requests:', some(prs, (x) => `- #${x.number} ${q(x.title)}${x.draft ? ', a draft' : ''}`)],
      copies.length > 0 && ['Working copies with unsaved changes:', some(copies, (c) => `- ${c.name}: ${count(c.changes, 'change', 'changes')}`)],
    ]);
    // The people at work on this floor: each conversation's agent, and agents started from here.
    const convos = work.conversations.filter((c) => c.project === p);
    const started = runs.filter((r) => r.project === p);
    add(`Agents on ${floor.label}`, [
      convos.length + started.length === 0 && 'No agents here.',
      some(convos, (c) => {
        const ask = asks.find((a) => a.key === c.id);
        const says = c.says || {};
        const now = [c.working && 'working now', (ask || says.needs) && 'waiting for you', c.check && 'finished, with something for you to check'].filter(Boolean).join(', ') || 'quiet';
        return [
          `- The ${p} agent on ${q(c.title)}${control.on ? ` (conversation ${c.id})` : ''}: ${now}.`,
          ask && `  Waiting for your permission: ${ask.what}.`,
          says.needs && `  It needs: ${says.needs}`,
          says.now && `  It last said: ${q(says.now)}`,
          says.next && `  Next: ${says.next}`,
          says.when && `  When: ${says.when}`,
          c.at && `  Last heard from at ${clock(c.at)}.`,
          proofOf(c) && `  Its work: ${proofOf(c).word.toLowerCase()}. ${proofOf(c).line}`,
          reviewOf(c) && `  The review line: ${reviewOf(c).line}`,
        ];
      }),
      some(started, (r) => [
        `- An agent started from the building, on ${q(r.title)} (conversation ${r.key}): ${{ working: 'working now', stopped: 'stopped, as you asked', failed: 'stopped with an error' }[r.state] || 'finished'}.`,
        r.said && `  It last said: ${q(r.said)}`,
      ]),
    ]);
  }
  if (org.lobby) {
    add(`${org.lobby.label} (the lobby)`, [
      `Rooms: ${roomsOf(org.lobby).map((r) => r.label).join(', ')}.`,
      work.presence.length ? some(work.presence, (e) => `- ${e.name} (${e.type}${e.project ? `, ${e.project}` : ''}): ${e.status || 'no status'}${e.link ? `, at ${e.link}${isDown(e) ? ', not answering' : e.up ? ', answering' : ''}` : ', no address written down'}.`)
        : 'Nothing is written down here yet.',
    ]);
  }
  if (org.basement) {
    const machines = org.basement.rooms.filter((r) => kindOf(org.basement, r) === 'machine');
    add(`${org.basement.label} (the basement)`, [
      machines.length > 0 && ['Machines:', machines.map((r) => { const m = roomModel(org.basement, r); return `- ${r.label}: ${m.big}, ${String(m.detail).toLowerCase()}.`; })],
      work.jobs.length > 0 && ['Jobs:', some(work.jobs, (j) => `- ${q(j.name)}, on the ${machineLabel(j.machine)}: ${{ running: 'running', queued: 'waiting in the queue' }[j.state] || j.state}.`)],
      work.library.length > 0 && ['On the library shelves:', some(work.library, (b) => `- ${b.name}${b.status ? `: ${b.status}` : ''}`)],
    ]);
  }
  if (work.company.length) add('Company notes', ['Filed in the Company room:', some(work.company, (e) => `- ${e.section}: ${e.name}${e.note ? `. ${e.note}` : ''}`)]);
  if (hasStory() && happened.length) add('Just now', ['What happened lately, newest first:', happened.map((e) => `- At ${clock(e.at)}: ${e.line}`)]);
  return out;
}

const brainWho = (role) => ({ role, name: role === 'assistant' ? org.assistant?.name || '' : deskName(), company: org.company });

// Claude's answer for the receptionist or the assistant, a piece at a time. It throws if there is
// none, so the rules can answer instead.
async function* claudeSays(role, text) {
  try {
    // what the assistant passes on to an agent is remembered, so that floor's lead reports back on it
    yield* brain.ask(brainWho(role), text, brainFacts(), { passed: (sent) => leads.remember(null, sent) });
  } catch (error) {
    console.warn('Arnheim: no answer from Claude.', error.message);
    throw error;
  }
}

// Reads Claude the facts as someone steps up to the receptionist or the assistant, so their first
// answer comes sooner. The server does nothing if they know them all already.
const primed = {};
function primeBrain(role) {
  if (!brain.on || Date.now() - (primed[role] || 0) < 3000) return;
  primed[role] = Date.now();
  brain.prime(brainWho(role), brainFacts());
}

/* ---------- talking in the walk (voice.js) ---------- */

// The receptionist answers as at the desk. The people at work answer from their own lines in work.json ("says"),
// with no AI, unless the brain is on (below); in the sample they are made up, and so is what they say. With
// control on, what you tell an agent reaches the agent doing the work.
const talkItem = (who) => work.conversations.find((c) => convoHref(c) === who.href) || work.tasks.find((t) => taskHref(t) === who.href) || null;
const isConvo = (item) => work.conversations.includes(item);
const convoNow = (id) => work.conversations.find((c) => c.id === id) || null;

// With the brain on (serve.py --brain), someone at work answers through Claude, in the first person, like an
// employee about their own work: from what the building knows of it, and of their floor. With control on, an
// agent's conversation can also pass an instruction about its work to its own working session, and the floor's
// lead reports back on it as on their own.
const agentBrainWho = (item) => ({
  role: 'agent', company: org.company, floor: floorOf(item.project)?.label || item.project, title: item.title,
  key: control.on && isConvo(item) ? item.id : '',
});
function agentFacts(item) {
  const floor = floorOf(item.project);
  const label = floor?.label || item.project;
  const keep = new Set(['Company', 'The building', `Floor: ${label}`, `Agents on ${label}`, 'Company memory: what every agent is told as it starts']);
  const out = brainFacts().filter(([name]) => keep.has(name));
  const clock = (at) => new Date(at < 1e12 ? at * 1000 : at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const convo = isConvo(item);
  const now = (convo ? convoNow(item.id) : work.tasks.find((t) => t.id === item.id)) || item;
  const says = now.says || {};
  const ask = convo && control.on ? control.state().asks.find((a) => a.key === item.id) : null;
  const proof = convo ? proofOf(now) : null;
  const review = convo ? reviewOf(now) : null;
  const state = convo
    ? [now.working ? 'You are working right now.' : 'You are not working right now.', now.check && 'You have finished, with something for the person to check.']
    : [`This is a task in ${label}'s Work room, and you are the one doing it. Its status: ${(STATUS[now.status] || now.status || 'open').toLowerCase()}.`, now.note && `Its note: ${now.note}`];
  const lines = [
    `You are the ${item.project} agent on "${item.title}"${convo && control.on ? ` (your conversation is ${item.id})` : ''}.`,
    ...state,
    ask && `You are waiting for the person's permission: ${ask.what}. They answer it on your card, or by saying allow or deny.`,
    says.needs && `What you need from the person: ${says.needs}`,
    says.now && `What you last said: "${says.now}"`,
    says.next && `What is next: ${says.next}`,
    says.when && `When: ${says.when}`,
    now.at && `Last heard from you at ${clock(now.at)}.`,
    proof && `Your work: ${proof.word.toLowerCase()}. ${proof.line}`,
    review && `The review line on your work: ${review.line}`,
    now.spent?.tokens && `You have used ${Math.round(now.spent.tokens).toLocaleString()} tokens.`,
  ].filter(Boolean);
  out.unshift(['You', lines.join('\n')]);
  const asked = floor ? leads.passed(floor).filter((x) => x.key === item.id) : [];
  if (asked.length) out.push(['What the person asked you to do from here', asked.map((x) => `- At ${clock(x.at)}: ${x.text}`).join('\n')]);
  return out;
}
function primeAgent(item) {
  const id = `agent:${item.id}`;
  if (!brain.on || Date.now() - (primed[id] || 0) < 3000) return;
  primed[id] = Date.now();
  brain.prime(agentBrainWho(item), agentFacts(item));
}
// Their answer through Claude, or if Claude gives none at all, the building's own (`otherwise`).
function agentThinks(item, said, otherwise) {
  return (async function* thought() {
    let given = false;
    try {
      const floor = floorOf(item.project) || null;
      for await (const piece of brain.ask(agentBrainWho(item), said, agentFacts(item), { passed: (sent) => leads.remember(floor, sent) })) {
        given = true;
        yield piece;
      }
    } catch (error) {
      if (given) throw error; // voice.js says the answer was cut off
      console.warn('Arnheim: no answer from Claude for an agent.', error.message);
      const plain = otherwise();
      if (plain && typeof plain[Symbol.asyncIterator] === 'function') yield* plain;
      else yield await plain;
    }
  })();
}

const TOUR = ['tour', 'show me round', 'show me around', 'look around'];

function poeSays(text) {
  if (has(norm(text), TOUR)) return 'I can show you round once you leave the walk: ask me again then.';
  const a = poe.answer(text);
  if (a.offer) return `I can add "${a.offer.title}" as a task from my desk, where you pick its project: leave the walk and tap me at the front desk.`;
  const lines = [...a.lines];
  // The things an answer links to belong to its first line, so they are said right after it.
  if (a.links?.length && a.links.length <= 4) lines.splice(1, 0, `${a.links.map((x) => (x.sub ? `${x.title}, on ${x.sub}` : x.title)).join('. ')}.`);
  return lines.join(' ');
}

// What the receptionist or the assistant says on a walk. With the brain on, Claude answers, a piece at
// a time, except for what the rules keep (a greeting, a refusal, a message to take down, a tour).
// If Claude has no answer at all, the rules answer instead.
function deskSays(role, text) {
  if (!brain.on || has(norm(text), TOUR)) return poeSays(text);
  const a = poe.answer(text);
  if (a.ruled || a.offer) return poeSays(text);
  return (async function* thought() {
    let given = false;
    try {
      for await (const piece of claudeSays(role, text)) {
        given = true;
        yield piece;
      }
    } catch (error) {
      if (given) throw error; // voice.js says the answer was cut off
      yield poeSays(text);
    }
  })();
}

function sampleReply(item, text) {
  const q = norm(text);
  const says = item.says || {};
  const on = (words) => has(q, words);
  if (on(['thank', 'cheers', 'great', 'nice one', 'well done', 'good job'])) return "Thanks. I'll keep going.";
  if (on(['bye', 'see you', 'talk later'])) return 'Bye for now.';
  if (on(['who are you', 'your name', 'what are you'])) return `I'm the ${item.project} agent on "${item.title}".${madeUp() ? ' This company is a sample, so I am made up too.' : ''}`;
  if (on(['next', 'after that', 'plan', 'left', 'remaining', 'then what'])) return says.next || "I'll know what's next when this step is done.";
  if (on(['you should', 'instead', 'stop ', 'switch to', 'focus on', 'do this', 'can you', 'could you', 'i want you', 'please '])) {
    return madeUp() ? "I'm a made-up agent in a sample, so I can't take new work. With real agents, what you say here goes to the agent doing the work."
      : "I can only tell you what the company's files say, so I can't take new work from here. With real agents, what you say here goes to the agent doing the work.";
  }
  if (on(['pass', 'proven', 'proof', 'review', 'checked', 'check it', 'tests', 'failed', 'fail ', 'broken', 'does it work', 'did it work'])) {
    const pr = proofOf(item);
    const own = (line) => line.replace(/\bits\b/g, 'my').replace(/^It\b/, 'I');
    return reviewSaid(item) || (pr && own(pr.line)) || (item.changed ? "I changed files, and nothing has checked them: my floor has no check or review line." : "I haven't changed any files, so there's nothing to check yet.");
  }
  if (on(['need me', 'need from me', 'want from me', 'need anything', 'need you', 'stuck', 'blocked', 'help', 'problem', 'decide', 'decision'])) {
    return says.needs || (item.review?.state === 'failed' ? `Please look at my work. ${reviewSaid(item)}` : 'Nothing from you right now. I will ask if I need you.');
  }
  if (on(['how long', 'when will', 'when did', 'started', 'finish', 'done by'])) return says.when || "I can't say exactly. I'll say when it's done.";
  return [says.now, says.next].filter(Boolean).join(' ') || `I'm working on "${item.title}".`;
}

// The founder's assistant (org.assistant), in their office: in the sample they answer as the receptionist does.
// "What's waiting on me?", "what needs me?": the receptionist reads out the one list (queue.js).
const isAide = (who) => !!org.assistant && who.href === (org.assistant.href || '#/assistant');

const talk = {
  placeholder: (who) => (isStandHref(who?.href) ? `Type the goal for ${org.floors.find((f) => f.id === standFloor(who.href))?.label || 'this project'}` : null),
  name(who) {
    if (isStandHref(who.href)) return 'Goals room';
    if (who.href === DESK) return deskName() || 'Receptionist';
    if (isLeadHref(who.href)) return who.name || who.title;
    if (isAide(who)) return org.assistant.name;
    const item = talkItem(who);
    return item ? `${item.project} agent` : null;
  },
  greet(who) {
    if (who.href === DESK || isAide(who)) primeBrain(who.href === DESK ? 'receptionist' : 'assistant'); // walked up to: read Claude the facts now
    const lead = leads.floorOf(who);
    if (lead) return leads.greet(lead, who);
    const stand = standOf(who);
    if (stand) return stand.greet();
    if (who.href === DESK) {
      const hr = new Date().getHours();
      const hello = hr >= 5 && hr < 12 ? 'Good morning' : hr >= 12 && hr < 18 ? 'Good afternoon' : hr >= 18 && hr < 23 ? 'Good evening' : 'Hello';
      const b = briefTold ? null : briefNow();
      briefTold = true;
      if (b && !b.quiet) return `${hello}. ${sayBrief(b, (p) => floorOf(p)?.label || p)}`;
      return `${hello}. Ask me what's happening, or anything ${brain.on ? 'at all' : 'about the building'}.${control.on ? ' I can start an agent on a project too.' : ''}`;
    }
    if (isAide(who)) {
      const hello = `Hello. I'm ${org.assistant.name}, ${org.founder?.name || 'the founder'}'s assistant.`;
      return madeUp() ? `${hello} This company is made up, and so am I. Ask me anything${brain.on ? '' : ' about it'}.` : `${hello} Ask me anything${brain.on ? '' : ` about ${org.company}`}.`;
    }
    const item = talkItem(who);
    if (item) primeAgent(item); // walked up to: read Claude their facts now
    return item ? `Hi. I'm on "${item.title}". Ask me how it's going${brain.on ? ', or anything about it' : ''}.` : null;
  },
  answer(who, text, _before, { spoken = false } = {}) {
    const lead = leads.floorOf(who);
    if (lead) return leads.says(lead, text, { spoken });
    const stand = standOf(who);
    if (stand) return stand.answer(text);
    if (who.href === DESK || isAide(who)) {
      const round = leads.round(text); // "give me the round": every lead in turn, a line each
      if (round) { deskVoice = null; starting = null; return round; }
    }
    if (who.href === DESK) {
      const waiting = waitingNow();
      // a permission, answered out loud: read back first, then "allow" or "deny" (leads.js)
      const v = voiceAnswer(text, waiting.filter(canAnswer), deskVoice, { spoken, on: features.get('answers'), label: floorLabel });
      if (v) {
        deskVoice = v.pending;
        if (v.pending) starting = null; // only the last question waits for your word
        if (v.show) showWaiting(v.show);
        return v.act ? answerSaid(v.act) : v.reply;
      }
      const went = leads.go(text);
      if (went) return went;
      const reads = control.on ? allowReadsAsked(text, waiting) : null;
      if (reads) return allowReads(reads);
      if (WAITING.test(String(text || ''))) return sayWaiting(waiting, (p) => floorOf(p)?.label || p);
      const decision = rememberAsked(text);
      if (decision) return rememberIt(decision);
      if (MEMORY_ASKED.test(String(text || ''))) return sayMemory(memoryNow());
      if (ROUTINES_ASKED.test(String(text || ''))) return sayRoutines(routinesNow(), (p) => floorOf(p)?.label || p);
      if (BRIEF_ASKED.test(String(text || ''))) return sayBrief(briefNow(), (p) => floorOf(p)?.label || p);
      if (HEALTH_ASKED.test(String(text || ''))) return sayHealth(org.floors, work);
      const start = deskStart(control, text, starting);
      if (start) {
        starting = start.pending;
        if (start.pending) deskVoice = null;
        if (start.reply != null) return start.reply;
      }
    }
    if (who.href === DESK || isAide(who)) return deskSays(who.href === DESK ? 'receptionist' : 'assistant', text);
    const item = talkItem(who);
    if (item && spoken) {
      // in an agent's ring, out loud, as anywhere: read back first, never when it is switched off, and never for
      // anything that may be private (its card's buttons answer at once)
      const asks = waitingNow().filter((i) => i.key === item.id && canAnswer(i));
      const v = asks.length ? voiceAnswer(text, asks, ringVoice.get(item.id) || null, { spoken, on: features.get('answers'), label: floorLabel }) : null;
      if (v) {
        ringVoice.set(item.id, v.pending);
        return v.act ? answerSaid(v.act) : v.reply;
      }
    }
    if (item && control.on && isConvo(item)) {
      // allow, deny and stop at once; anything else through their brain, if it is on, or straight to the agent
      const quick = agentQuick(control, item, text, () => convoNow(item.id));
      if (quick != null) return quick;
      const relay = () => agentReply(control, item, text, () => convoNow(item.id));
      return brain.on ? agentThinks(item, text, relay) : relay();
    }
    if (item && brain.on) return agentThinks(item, text, () => sampleReply(item, text));
    return item ? sampleReply(item, text) : "I've finished here, so there's nothing new to tell.";
  },
  // What waits on you, for the walk's "Needs you": each item's conversation (key) or title, and its kind.
  waiting() {
    return waitingNow().map((i) => ({ key: i.key || null, title: i.title, kind: i.kind }));
  },
  // The receptionist, a floor's lead (a question for one of them goes to them: "how's Tidepool doing?"), for
  // the Talk panel (talk-dock.js).
  through: (who, text) => (isStandHref(who?.href) ? null : leads.through(who, text, deskWho())), // a goal said at a flagpole stays a goal, whatever floor it names
  get desk() { return deskWho(); },
  // The lead by the lift on a floor, for the walk: null where there is none, or leads are switched off.
  lead: (floorId) => leads.lead(floorId),
  // Unasked: a lead says what came of what you asked them to pass on, once it is done, stuck or needs you; the
  // receptionist and the assistant say it for whichever lead it is.
  speakUp(who) {
    const lead = leads.floorOf(who);
    if (lead) return leads.speakUp(lead);
    return who.href === DESK || isAide(who) ? leads.speakUp(null) : null;
  },
  cutIn: () => features.get('cutin'),
  // With control on: Allow and Deny, or Stop, on an agent's card; Start at the front desk. A lead's card has
  // what waits for your word (a start, an instruction to send, a stop) or this floor's first permission request.
  controls(who) {
    const lead = leads.floorOf(who);
    if (lead) return leads.controls(lead);
    if (!control.on) return null;
    if (who.href === DESK) {
      return deskControls(starting, () => {
        const start = deskStart(control, 'start it', starting);
        starting = start?.pending || null;
        return start?.reply;
      }, () => { starting = null; return "All right, I won't start it."; });
    }
    const item = talkItem(who);
    return item && isConvo(item) ? agentControls(control, item) : null;
  },
};

/* ---------- the floors' leads (lead-desk.js), and talking from any screen (talk-dock.js) ---------- */

const floorLabel = (p) => floorOf(p)?.label || p;
const deskWho = () => ({ href: DESK, title: deskName() || 'Receptionist', sub: org.receptionist?.title || 'Receptionist', voice: org.receptionist?.voice || null });
const aideWho = () => (org.assistant?.name ? { href: org.assistant.href || '#/assistant', title: org.assistant.name, sub: org.assistant.title || 'Assistant', voice: org.assistant.voice || null } : null);
let deskVoice = null; // the receptionist's request read back, waiting for "allow" or "deny"
const ringVoice = new Map(); // an agent's own request read back in its ring, by its conversation

// The floor as its lead sees it.
function floorView(floor) {
  const p = floor.project;
  return {
    label: floor.label,
    conversations: work.conversations.filter((c) => c.project === p),
    waiting: waitingNow().filter((i) => i.project === p),
    goals: work.goals.filter((g) => g.project === p),
    tasks: openTasks().filter((t) => t.project === p),
    prs: work.pullRequests.filter((x) => x.project === p),
    health: healthOf(p, work),
    spend: spendOf(floor),
    clashes: clashesOf(work.conversations).filter((c) => c.project === p),
  };
}
// The floor's agents, as [{ id, title, working }]: its conversations, and agents started from the building.
function floorAgents(floor) {
  const p = floor.project;
  const runs = control.on ? control.state().runs.filter((r) => r.project === p && !work.conversations.some((c) => c.id === r.key)) : [];
  return [
    ...work.conversations.filter((c) => c.project === p).map((c) => ({ id: c.id, title: c.title, working: !!c.working || control.run?.(c.id)?.state === 'working' })),
    ...runs.map((r) => ({ id: r.key, title: r.title, working: r.state === 'working' })),
  ];
}
const momentsOn = (floor) => [...yesterday.moments, ...history].filter((m) => m && m.project === floor.project);
const notConnected = () => (fromAway() && phoneMe?.phone ? phoneControlOff : "I can't do that here: this building isn't connected to your agents. On your own company, switch on Answer agents from the building, in Settings, or start Arnheim with serve.py --control.");

// A permission answered by voice, once it was read back.
function answerSaid(act) {
  if (answered.has(act.id)) return 'That one is answered already.';
  focusSince = Date.now();
  return answerAsk(act.id, act.behavior).then((r) => { render(); return answeredSaid(act.behavior, act.item)(r); }, (error) => error.message);
}
// Something that must be answered on the screen: its page, unless you are walking.
function showWaiting(item) {
  const href = waitingHref(item);
  if (href && !walkOn()) goTo(href);
}

// Where "take me to ..." can go: every room, every floor, the three tabs and the front desk.
function places() {
  const out = [];
  for (const floor of floors()) {
    for (const room of roomsOf(floor)) {
      out.push({ href: `#/${floor.id}/${room.id}`, label: `${room.label} on ${floor.label}`, room: true,
        names: [`${room.label} on ${floor.label}`, `${room.label} room on ${floor.label}`, `${floor.label} ${room.label}`, `${floor.label}s ${room.label}`, `${room.label} on the ${floor.label}`] });
    }
    out.push({ href: `#/${floor.id}`, label: floor.label, names: [floor.label, floor.project, floor === org.lobby && 'lobby', floor === org.basement && 'basement'].filter(Boolean) });
  }
  out.push({ href: '#/', label: 'what needs you', names: ['needs you', 'what needs me', 'the list', 'queue'] });
  out.push({ href: '#/activity', label: 'Activity', names: ['activity', 'company page', 'company', 'projects', org.company] });
  out.push({ href: '#/company', label: 'Settings', names: ['settings', 'switches', 'connect'] });
  out.push({ href: DESK, label: 'the front desk', names: ['front desk', 'reception', deskName()].filter(Boolean) });
  return out;
}

const leads = createLeadDesk({
  company: () => org?.company,
  floors: () => org.floors,
  label: floorLabel,
  view: floorView,
  agents: floorAgents,
  moments: momentsOn,
  waiting: () => waitingNow(),
  canAnswer,
  answer: answerSaid,
  show: showWaiting,
  control,
  places,
  go: (href) => goTo(href),
  back: () => window.history.back(),
  walking: () => walkOn(),
  think: (floor, said) => (brain.on ? leadThinks(floor, said) : null),
  prime: (floor) => primeLead(floor),
  features,
  madeUp,
  notConnected,
});

// With the brain on (serve.py --brain), a lead answers anything else through Claude, from this floor's facts
// alone, and with control on can pass an instruction to an agent at work here.
function leadFacts(floor) {
  const keep = new Set(['Company', 'The building', `Floor: ${floor.label}`, `Agents on ${floor.label}`, 'Company memory: what every agent is told as it starts']);
  const out = brainFacts().filter(([name]) => keep.has(name));
  const clock = (at) => new Date(at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  out.push(['Where it stands, in brief', leadUpdate(floorView(floor))]);
  out.push(['Waiting on the person here', sayWaiting(waitingNow().filter((i) => i.project === floor.project), floorLabel, 8)]);
  const today = momentsBefore(momentsOn(floor), Date.now() / 1000, 30);
  out.push([`Today on ${floor.label}, newest first`, today.length ? today.map((m) => `- At ${clock(m.at)}: ${sayMoment(m)}`).join('\n') : 'Nothing has happened here today.']);
  const passed = leads.passed(floor);
  if (passed.length) out.push(['What the person asked you to pass on', passed.map((x) => `- At ${clock(x.at)}, to the agent on "${x.title}": ${x.text}`).join('\n')]);
  return out;
}
const leadBrainWho = (floor) => ({ role: 'lead', name: leads.who(floor).name || '', company: org.company, floor: floor.label });
function primeLead(floor) {
  if (!brain.on || Date.now() - (primed[`lead:${floor.id}`] || 0) < 3000) return;
  primed[`lead:${floor.id}`] = Date.now();
  brain.prime(leadBrainWho(floor), leadFacts(floor));
}
function leadThinks(floor, said) {
  return (async function* thought() {
    let given = false;
    try {
      // what the brain passes on to an agent here is remembered, so this lead reports back on it too
      for await (const piece of brain.ask(leadBrainWho(floor), said, leadFacts(floor), { passed: (sent) => leads.remember(floor, sent) })) {
        given = true;
        yield piece;
      }
    } catch (error) {
      if (given) throw error;
      yield `I'm not sure what you mean. Ask me where we are, what's new, or who's working on ${floor.label}.`;
    }
  })();
}

// The lead's card at the top of their floor's page: where it stands, and Talk.
function leadCard(floor) {
  if (!features.get('leads') || !hasLead(floor)) return null;
  const who = leads.who(floor);
  return h('section.panel-card.lead-card',
    h('div.lead-head', poeBadge(22, who.look), h('div', h('h3.lead-name', who.title), h('p.small.muted', 'Where it stands'))),
    h('p.lead-says', leads.update(floor)),
    features.get('talk') && dock ? h('div.control-row', btn(`Talk to ${who.name || 'the lead'}`, () => dock.open(who), '.primary', 'mic')) : null);
}

// Using it from a phone (serve.py --remote): how, and the phones paired with it. Filled in by remote below.
function phoneCard() { const card = remoteCard(); return card ? [h('h4.switch-group', 'Your phone'), card] : null; }

// Every feature, on or off, on this computer's own page (serve.py's /switches, connect/switches.py): kept for every
// start in data/serve.json. A word serve.py started with holds its switch for that start. Elsewhere (the made-up
// company, a phone) only the talking switches show, which are this device's own (features.js).
let switchBoard = null; // { token, switches: [{ name, group, label, about, on, set_by }] }
let switchNote = '';
async function readSwitches() {
  if (dir !== 'data' || madeUp() || fromAway()) return null;
  try {
    const r = await fetch('switches', { cache: 'no-store', credentials: 'same-origin' });
    switchBoard = r.ok ? await r.json() : null;
  } catch { switchBoard = null; }
  return switchBoard;
}
async function flip(name, on, again = false) {
  let data = {};
  let ok = false;
  try {
    const r = await fetch('switches', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Arnheim-Switches': switchBoard?.token || '' },
      body: JSON.stringify({ name, on }),
    });
    if (r.status === 403 && !again && await readSwitches()) return flip(name, on, true); // Arnheim started again: a new token
    data = await r.json().catch(() => ({}));
    ok = r.ok;
  } catch { data = { error: 'Arnheim didn\'t answer. Is it still running?' }; }
  if (Array.isArray(data.switches)) switchBoard = { token: data.token || switchBoard?.token, switches: data.switches };
  switchNote = ok ? data.note || '' : data.error || 'That switch didn\'t change.';
  if (ok && name === 'control') control.restart();
  if (ok && name === 'brain') brain.recheck().then(() => render());
  render();
  return ok;
}
// Whether a switch is on, as this computer's page last heard; `otherwise` where there are none (HQ, a phone).
const switchOn = (name, otherwise = true) => {
  const s = switchBoard?.switches?.find((x) => x.name === name);
  return s ? !!s.on : otherwise;
};
// The switches in the groups a person thinks in, each one line (the rest of its words on hover or focus).
const SWITCH_SETS = [
  ['Answering your agents', ['control', 'always']],
  ['Guardrails', ['checks', 'review', 'budget', 'restore', 'clash']],
  ['What every agent is told', ['handovers', 'memory', 'howtos']],
  ['While Arnheim runs', ['brain', 'routines', 'pings', 'git', 'updates']],
  ['On this page', ['forecast']],
];
// The words sit outside the label, so tapping them to read them all (a phone has no pointing) never flips the switch.
const aboutLine = (text) => h('span.small.muted.switch-about', text); // in full: rows that open on a hover move under the pointer
function switchRow(s) {
  return h('li.switch-row', h('label.switch',
    h('input', { type: 'checkbox', checked: !!s.on, disabled: !!s.set_by, onchange: (event) => flip(s.name, event.currentTarget.checked) }),
    h('span', h('b', s.label), s.set_by && h('span.small', ` Set by ${s.set_by} for this start.`))), aboutLine(s.about));
}
// Speaking out loud on this device: the same as the Voice button in Talk, here too, where a person looks for it.
window.addEventListener('arnheim-voice', () => { if (document.querySelector('#content .switch-list')) render(); });
function voiceRow() {
  if (!voiceWanted()) return h('li.switch-row', h('span.small', h('b', 'Speak out loud: off.'), ' This device keeps the voice off, so everything is written.'));
  return h('li.switch-row', h('label.switch',
    h('input', { type: 'checkbox', checked: voiceSaved(), onchange: (event) => setVoiceSaved(event.currentTarget.checked) }),
    h('span', h('b', 'Speak out loud'))),
  aboutLine('On: whoever you talk to answers out loud, and listens when you speak. Off: everything is written and nothing is said aloud on this device. The Voice button in Talk does the same.'));
}
// These two only work out loud: while the voice is off they wait, and say so, so no ticked box reads as speaking.
const VOICE_ONLY = new Set(['answers', 'cutin']);
const talkRows = () => {
  const quiet = !voiceSaved();
  return [voiceRow(), ...FEATURES.map((f) => {
    const waits = quiet && VOICE_ONLY.has(f.id);
    return h(waits ? 'li.switch-row.needs-voice' : 'li.switch-row', h('label.switch',
      h('input', { type: 'checkbox', checked: features.get(f.id), onchange: (event) => features.set(f.id, event.currentTarget.checked) }),
      h('span', h('b', f.label))), aboutLine(waits ? `${f.about} Only while Speak out loud is on.` : f.about));
  })];
};
// The switches Arnheim comes with on that are now off (answering your agents stays as you chose it). Ones that
// come off, such as the brain or routines, are yours to add and are left alone.
const offRecommended = (rows) => rows.filter((s) => s.name !== 'control' && !s.set_by && s.default === true && !s.on);
let resetting = false;
async function useRecommended() {
  resetting = true;
  render();
  const back = [];
  let failed = false;
  for (const s of offRecommended(switchBoard?.switches || [])) { // one at a time: each saves the file
    if (await flip(s.name, true)) back.push(s.label);
    else { failed = true; break; } // flip's own words say what went wrong; keep them
  }
  resetting = false;
  if (!failed) switchNote = `Back on: ${back.join(', ')}.`;
  render();
}
function switchesCard() {
  const rows = switchBoard?.switches;
  if (!Array.isArray(rows)) return talkingCard();
  const named = new Set(SWITCH_SETS.flatMap(([, names]) => names));
  const sets = [...SWITCH_SETS.map(([label, names]) => [label, names.map((n) => rows.find((s) => s.name === n)).filter(Boolean)]),
    ['Other', rows.filter((s) => !named.has(s.name))]].filter(([, list]) => list.length);
  const off = offRecommended(rows);
  return h('section.panel-card.talking-card.switches-card',
    sectHead('sliders-horizontal', 'Switches'),
    h('p.small.muted', 'Each feature on or off, at once and for every start.'),
    switchNote && h('p.small.note', { role: 'status' }, switchNote),
    off.length > 0 && h('div.control-row', btn(resetting ? 'Changing...' : 'Use the recommended settings', resetting ? null : useRecommended, '.quiet', 'rotate-ccw'),
      h('span.small.muted', `Turns back on ${off.length === 1 ? off[0].label : `${off.length} switches`} that Arnheim comes with on.`)),
    ...sets.flatMap(([label, list], i) => [h('h4.switch-group', label), h('ul.switch-list', [...list.map(switchRow), i === 0 && alertRow()].filter(Boolean))]),
    h('h4.switch-group', 'Talking, on this device'),
    h('ul.switch-list', talkRows()),
    phoneCard());
}

/* ---------- desktop alerts when an agent needs you (alerts.js) ---------- */

// Your own company only. What was waiting when the page opened never alerts: the list is noted first (at the start,
// and again when control's first answer arrives), and each item after that alerts once, only while the page is in the
// background.
let alertKnown = null; // ids of what needed you, seen on this page
let alertsNote = '';
let alertOfferGone = kept('arnheim-alerts-offer') === 'no';
const ownCompany = () => dir === 'data' && !madeUp();
function checkAlerts() {
  if (!ownCompany()) return;
  const items = waitingNow();
  if (!alertKnown) { alertKnown = new Set(); freshAlerts(items, alertKnown); return; }
  const fresh = freshAlerts(items, alertKnown);
  if (!fresh.length || !alerts.on() || (!document.hidden && document.hasFocus())) return;
  for (const i of fresh) alerts.show(i, floorOf(i.project)?.label || i.project, () => { location.hash = waitingHref(i) || '#/'; });
}
async function setAlerts(on) {
  const said = await alerts.set(on);
  alertsNote = said;
  render();
  if (alerts.on() || !on) setTimeout(() => { if (alertsNote === said) { alertsNote = ''; render(); } }, 10000); // done: said for a moment
}
function alertRow() {
  const about = 'One alert for each permission request or question that comes while this page is in the background. Clicking it opens what is asked. This browser only.';
  return h('li.switch-row', h('label.switch',
    h('input', { type: 'checkbox', checked: alerts.on(), onchange: (event) => setAlerts(event.currentTarget.checked) }),
    h('span', h('b', 'Desktop alerts when an agent needs you'), alertsNote && h('span.small.note', { role: 'status' }, alertsNote))),
  aboutLine(about));
}
// Offered under the first card on Needs you, on this computer's own company, until it is on or turned down here.
function alertOffer() {
  if (ownCompany() && alerts.on() && alertsNote) return h('p.small.note.alert-offer', { role: 'status' }, alertsNote);
  if (!ownCompany() || alerts.on() || alertOfferGone || alerts.state() === 'none') return null;
  return h('div.alert-offer',
    h('p.small', 'Get a desktop alert when an agent needs you, while this page is in the background.'),
    h('div.control-row',
      btn('Turn on alerts', () => setAlerts(true), '', 'bell'),
      btn('No thanks', () => { alertOfferGone = true; keep('arnheim-alerts-offer', 'no'); render(); }, '.quiet')),
    alertsNote && h('p.small.note', { role: 'status' }, alertsNote));
}

// The talking switches alone, where Talk can always be switched back on.
function talkingCard() {
  return h('section.panel-card.talking-card',
    sectHead('mic', 'Talking'),
    h('ul.switch-list', talkRows()),
    phoneCard());
}

/* ---------- your phone (serve.py --remote, connect/remote.py; docs/phone.md) ---------- */

let remoteNow = null; // on this computer: what /remote/status said
let remoteCode = null; // on this computer: the pairing code just made, { code, url, until }
let phoneMe = null; // on a paired phone: what /remote/me said
let remoteAsked = false;
async function readRemote() {
  remoteAsked = true;
  const get = (name) => fetch(`remote/${name}`, { cache: 'no-store', credentials: 'same-origin' }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (fromAway()) phoneMe = await get('me');
  else remoteNow = (await get('status')) || { on: false };
}
const remotePost = (name, body = {}) => fetch(`remote/${name}`, {
  method: 'POST', cache: 'no-store', credentials: 'same-origin',
  headers: { 'Content-Type': 'application/json', 'X-Arnheim-Remote': '1' }, body: JSON.stringify(body),
}).then((r) => r.json());
const remoteRedraw = () => readRemote().then(() => { render(); dock?.refresh(); });
const phoneControlOff = 'Answering and instructing agents from this phone is off. Switch it on for this phone on your computer, in Settings.';

function remoteCard() {
  if (fromAway()) {
    if (!phoneMe?.phone) return null;
    return h('div.phone-card',
      h('p.small', `This ${phoneMe.label} is paired. ${phoneMe.control ? `It can answer and instruct agents until ${clockOf(phoneMe.control)}.` : phoneControlOff}`),
      h('div.control-row', btn('Unpair this phone', () => fetch('remote/leave', { method: 'POST', credentials: 'same-origin' }).then(() => location.reload()))));
  }
  if (!remoteAsked) { remoteRedraw(); return null; }
  if (!remoteNow?.on) {
    return h('div.phone-card', h('p.small.muted', 'Use all of this from your phone too, by voice as well: start Arnheim with --remote and a private way in such as Tailscale, which is free for personal use. docs/phone.md says how.'));
  }
  const phones = remoteNow.phones || [];
  const code = remoteCode && Date.now() < remoteCode.until ? remoteCode : null;
  return h('div.phone-card',
    h('p.small', h('strong', 'Your phone: '), `on, at ${remoteNow.url}`),
    code ? h('p.phone-code', `On your phone, open ${code.url} and type `, h('strong', code.code), '. It works once, for 5 minutes.') : null,
    h('div.control-row', btn('Pair a phone', () => remotePost('code').then((c) => { remoteCode = { ...c, until: Date.now() + c.seconds * 1000 }; return remoteRedraw(); }), '', 'smartphone')),
    phones.length ? h('ul.phone-list', phones.map((p) => h('li',
      h('span.phone-name', h('b', p.label), h('span.small.muted', p.control ? ` Can answer and instruct agents until ${clockOf(p.control)}.` : ` Paired ${agoText(p.paired)}. Can look and talk.`)),
      h('span.control-row',
        btn(p.control ? 'Stop control' : 'Control for 15 minutes', () => remotePost('grant', { id: p.id, minutes: p.control ? 0 : 15 }).then(remoteRedraw)),
        btn('Remove', () => remotePost('remove', { id: p.id }).then(remoteRedraw)))))) : h('p.small.muted', 'No phone is paired yet.'));
}

/* ---------- control in the panel (control.js) ---------- */

function controlDone(promise, said) {
  // refresh, not just render: the building's amber goes with the answer too, even while the sample is paused
  promise.then((out) => { controlNote = said(out); noteFresh = true; refresh(); }, (error) => { controlNote = error.message; noteFresh = true; render(); });
}

// A conversation's page: its permission request with Allow and Deny, a box to say something to
// it, and Stop while it works.
function convoControls(c, { noAsk = false } = {}) {
  const ask = noAsk ? null : control.askFor(c.id);
  const run = control.run(c.id);
  const working = c.working || run?.state === 'working';
  const send = (event) => {
    event.preventDefault();
    const input = event.currentTarget.elements.text;
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.blur();
    controlDone(control.say(c.id, text), (r) => (r.sent === 'resumed' ? 'Sent. It is answering now.'
      : working ? 'Sent. It reads it at its next step, and its answer shows above.'
        : waitsIn(c.id)));
  };
  return h('div.control',
    ask && h('div.control-ask',
      h('p', `Waiting for your permission: ${ask.what}`),
      h('div.control-row',
        btn('Allow', () => controlDone(control.answer(ask.id, 'allow'), () => 'Allowed, just this once.'), '.primary'),
        btn('Deny', () => controlDone(control.answer(ask.id, 'deny'), () => 'Denied.')))),
    h('form.control-say', { onsubmit: send },
      h('input', { name: 'text', type: 'text', maxlength: 2000, autocomplete: 'off', placeholder: 'Say something to it', 'aria-label': `A message for ${c.title}` }),
      h('button.btn', { type: 'submit' }, 'Send')),
    working && h('div.control-row', btn('Stop', () => controlDone(control.halt(c.id), () => 'Stopping. It stops at its next step.'))),
    noteOnce());
}

// Restore points (restore.js): the files as they were before an agent changed them, and with control on, a
// way back to one. On a floor (titles) each says whose it was.
function restoreCard(points, { titles = false } = {}) {
  if (!points.length) return null;
  const canGo = control.on && dir === 'data';
  const go = (p) => {
    const where = floorOf(p.project)?.label || p.project;
    if (!window.confirm(`Put ${where}'s files back as they were at ${clockOf(p.at)}? How they are now is kept as a restore point first, so you can undo this.`)) return;
    controlDone(control.restore(p.id), wentBack);
  };
  return h('section.panel-card',
    sectHead('rotate-ccw', 'Restore points'),
    h('ul.list', points.slice(0, 5).map((p) => {
      const li = row(null, sayPoint(p, clockOf), [titles && (p.by === 'you' ? 'You, from the building' : p.title), dayWord(p.at)].filter(Boolean).join('. '), 'quiet');
      if (canGo) li.append(h('div.control-row', btn('Go back to here', () => go(p))));
      return li;
    })),
    h('p.small.muted', canGo ? "Going back puts the floor's files as they were then. Files that weren't there then stay where they are."
      : dir === 'data' ? 'With control on, you can put the files back to one of these.'
        : 'Made up, like the rest of the sample. With your own company and control on, you can put the files back to one of these.'),
    canGo && noteOnce());
}

// Collision warnings (clashes.js): two agents changing the same files, and, with control on, a way to make
// one wait for the other.
function clashCard() {
  const list = clashesOf(work.conversations);
  if (!list.length) return null;
  const canTell = (c) => control.on && (REACHABLE.test(c.id) || control.run(c.id));
  return h('section.panel-card',
    sectHead('shield-check', 'Two agents on the same files'),
    h('ul.list', list.map((x) => {
      const li = row(convoHref(x.a), sayClash(x), [floorOf(x.project)?.label || x.project, x.working ? 'One is at work now' : null].filter(Boolean).join('. '), 'failed');
      const buttons = [x.a, x.b].filter(canTell).map((who) => btn(`Make "${who.title}" wait`, () => controlDone(control.say(who.id, waitWords(x, who)),
        () => `Told "${who.title}" to wait. It reads it at its next step.`)));
      if (buttons.length) li.append(h('div.control-row.waiting-do', buttons));
      return li;
    })),
    h('p.small.muted', 'Each was told as it changed the file. Look at both before either goes on.'),
    noteOnce());
}

// Every agent at once: paused from here until you resume them (connect/budget.py), with control on.
function pauseCard() {
  if (!control.on || dir !== 'data') return null;
  const paused = control.paused();
  return h(`section.panel-card.pause${paused ? '.paused' : ''}`, { 'aria-live': 'polite' },
    paused ? h('p', h('strong', 'Every agent is paused.'), ` Since ${new Date(paused * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}. Each stopped at its next step, and a message sent to one in Claude Code waits until you resume.`)
      : h('p.small.muted', 'Pause every agent at once: each stops at its next step, until you resume them.'),
    h('div.control-row', paused ? btn('Resume everyone', () => controlDone(control.resumeAll(), () => ''), '.primary', 'rotate-ccw')
      : btn('Pause everyone', () => controlDone(control.pauseAll(), () => ''), '', 'clock')));
}

// Replay the day (replay.js): the building's conversations as they were at a moment today. While it
// replays, the real ones wait in realTalks, and a banner on the building says so.
let replayAt = null;
let realTalks = null;
const clockOf = (at) => new Date(at * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
// Which day a time was: "Today", "Yesterday", or the day's name within the week.
const dayWord = (at) => {
  const day = localDay(new Date(at * 1000));
  return day === localDay() ? 'Today' : day === dayBefore(1) ? 'Yesterday' : new Date(at * 1000).toLocaleDateString([], { weekday: 'long' });
};
function replayed() {
  realTalks = work.conversations;
  work.conversations = conversationsAt(history, replayAt);
}
function showAt(t) {
  const now = Date.now() / 1000;
  if (t == null || t >= now - 30) {
    if (realTalks) work.conversations = realTalks;
    replayAt = realTalks = null;
  } else {
    if (realTalks) work.conversations = realTalks;
    replayAt = t;
    replayed();
  }
  replayBanner();
  refresh();
}
function replayBanner() {
  let el = $('replay-banner');
  if (replayAt == null) { el?.remove(); return; }
  if (!el) {
    el = h('div', { id: 'replay-banner', role: 'status' }, h('span'), btn('Back to now', () => showAt(null), '.primary'));
    $('stage').append(el);
  }
  el.firstChild.textContent = `Replaying the day at ${clockOf(replayAt)}`;
}

function replayCard() {
  if (!history.length) return null;
  const now = Date.now() / 1000;
  const first = Math.floor(Math.min(...history.map((m) => m.at)) - 60);
  const at = replayAt ?? now;
  const real = realTalks || work.conversations;
  const label = h('span.replay-at', replayAt == null ? 'Now' : clockOf(at));
  const list = h('ul.list.replay-moments');
  const fill = (t) => {
    const ms = momentsBefore(history, t);
    list.replaceChildren(...(ms.length ? ms.map((m) => {
      const c = real.find((x) => x.id === m.key);
      const files = m.kind === 'finished' ? touchedBy(history, m.key, t) : [];
      return row(c ? convoHref(c) : null, sayMoment(m), [clockOf(m.at), floorOf(m.project)?.label || m.project, files.length ? `Changed ${files.slice(0, 3).join(', ')}${files.length > 3 ? ` and ${files.length - 3} more` : ''}` : null].filter(Boolean).join('. '), MOMENT_MOOD[m.kind]);
    }) : [h('li', empty('Nothing had happened yet.'))]));
  };
  fill(at);
  const slider = h('input.replay-slider', { type: 'range', min: first, max: Math.ceil(now), step: 60, value: Math.round(at), 'aria-label': 'When in the day to show',
    oninput: (event) => { const t = Number(event.currentTarget.value); label.textContent = t >= now - 30 ? 'Now' : clockOf(t); fill(t); showAt(t); } });
  return h('section.panel-card.replay',
    sectHead('history', 'Replay the day'),
    h('p.small.muted', 'Drag back through today to see who was at work, and on what. Tap a moment to read that conversation.'),
    h('div.replay-row', slider, label),
    list,
    replayAt != null && h('div.control-row', btn('Back to now', () => showAt(null))));
}

// The weekly report (weekly.js): the last seven days floor by floor, and the whole of it as text to copy.
let weekNote = '';
function weekCard() {
  const report = weekReport(weekDays(), Date.now() / 1000, heldNow());
  if (!report.total.talks) return null;
  const label = (p) => floorOf(p)?.label || p;
  const copy = () => {
    const text = weekText(report, label, org.company);
    const done = (said) => { weekNote = said; render(); };
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(text).then(() => done('Copied. Paste it into a message or a document.'), () => done("This browser wouldn't copy it."));
    else done("This browser can't copy from here.");
  };
  return h('section.panel-card',
    sectHead('calendar-days', 'This week'),
    h('p', sayWeek(report, label)),
    h('ul.list', report.floors.map((f) => row(floorOf(f.project) ? `#/${floorOf(f.project).id}` : null, label(f.project) || 'No floor', floorLine(f), 'quiet'))),
    h('div.control-row', btn('Copy the report', copy)),
    weekNote && h('p.small.muted', { role: 'status' }, weekNote),
    madeUp() && h('p.small.muted', 'A made-up week, like the rest of the sample.'));
}

// What each floor's agents have spent today, against its budget.
// Your plan's limits (usage.js): how much is used, and whether at this pace you reach a limit before it starts
// again, with the floor spending most today and, with control on, a way to pause every agent.
const USAGE_ASKED = /\b(?:usage|limits?|quota|rate.?limit|my plan(?:'s)?)\b.*\b(?:left|used|hit|reach|run(?:ning)? out|when|much)\b|\b(?:how much|when)\b.*\b(?:usage|limit|quota)\b|\brun(?:ning)? out of (?:usage|tokens|quota)\b/i;
const forecastNow = () => forecastOf(work.usage, Date.now() / 1000);
function busiestFloor() {
  const list = org.floors.map((f) => [f, spentOfFloor(f)]).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1]);
  return list[0]?.[0] || null;
}
function sayUsage() {
  const list = forecastNow();
  if (!list.length) return 'Claude Code and Codex haven\'t said how much of your plan is used yet. Claude Code says so through its status line, and Codex as it works (connect/setup.py sets both up).';
  const top = busiestFloor();
  return [...list.slice(0, 3).map((f) => usageWords(f)), pressing(list) && top ? `${top.label}'s agents have used the most today.` : null].filter(Boolean).join(' ');
}
function usageCard() {
  const list = forecastNow();
  if (!list.length || !switchOn('forecast')) return null;
  const urgent = pressing(list);
  const top = urgent ? busiestFloor() : null;
  return h(`section.panel-card.usage${urgent ? '.pressing' : ''}`,
    sectHead('gauge', 'Your plan'),
    h('ul.list', list.map((f) => h('li', h('div.row', dot(f.reaches === 'now' ? 'failed' : f.reaches === 'before' ? 'needs' : 'quiet'),
      h('span.row-main', h('span.row-title', `${f.source}: ${Math.round(f.used)}% of the ${f.label}`), h('span.row-sub', usageLine(f)),
        h('span.meter', { 'aria-hidden': 'true' }, h(`span.meter-fill.s-${f.reaches === 'now' ? 'failed' : f.reaches === 'before' ? 'needs' : 'working'}`, { style: `width: ${Math.min(100, Math.max(2, f.used))}%` }))))))),
    top && h('p.small', `${top.label}'s agents have used the most today.`),
    urgent && control.on && dir === 'data' && !control.paused() && h('div.control-row', btn('Pause everyone', () => controlDone(control.pauseAll(), () => 'Every agent stops at its next step, until you resume them.'), '', 'clock')),
    h('p.small.muted', dir === 'data' ? 'As Claude Code and Codex report it. A 5-hour limit goes by the last hour\'s pace, a weekly one by its average.' : 'Made up, like the rest of the company.'));
}

function spendCard() {
  const list = org.floors.map((f) => [f, spendOf(f)]).filter(([, s]) => s);
  if (!list.length) return null;
  const total = list.reduce((n, [, s]) => n + (s.spent || 0), 0);
  const over = list.filter(([, s]) => s.over).length;
  return h('section.panel-card',
    sectHead('gauge', 'Spent today'),
    h('p.spend-total', h('b', `${tokensSaid(total)} tokens`), ` in all today${over ? `, ${count(over, 'floor', 'floors')} over budget` : ''}.`),
    h('p.small.muted', `Tokens measure AI work: the words it reads and writes. Arnheim counts them, not money: a plan costs the same each month and has limits${switchOn('forecast') && forecastNow().length ? ' (Your plan, above, shows how close they are)' : ''}, and an API key is billed by the token.`),
    h('ul.list', list.map(([f, s]) => h('li', h('a.row.spend-row', { href: `#/${f.id}` }, dot(s.over ? 'failed' : 'quiet'),
      h('span.row-main', h('span.row-title', f.label), h('span.row-sub', s.text[0].toUpperCase() + s.text.slice(1)),
        s.share != null && h('span.spend-bar', { 'aria-hidden': 'true' }, h(`span${s.over ? '.over' : ''}`, { style: `width: ${Math.round(s.share * 100)}%` }))))))),
    h('p.small.muted', 'Counted: what was read fresh and written. Reading the same thing again is left out.'));
}

// Project health (health.js): what is wrong on each floor, each with a button that sends an agent to fix it
// when control is on for your own company. Needs you lists every floor that needs looking at; a floor's
// page lists its own.
function healthItems(floor, hh) {
  const WHAT = { pr: 'Waiting too long', routine: 'A routine', review: 'The review line', quiet: 'Gone quiet', worn: 'Running long' };
  return hh.problems.map((p) => {
    const li = row(p.key ? convoHref({ id: p.key, project: floor.project }) : null, p.line, WHAT[p.kind] || 'A check',
      ['pr', 'quiet', 'worn'].includes(p.kind) ? 'needs' : 'failed');
    if (control.on && dir === 'data') {
      const send = (label, done) => btn(label, () => {
        controlDone(control.begin(floor.project, p.job), () => done);
        watchStart({ project: floor.project });
      });
      if (p.kind === 'quiet' && REACHABLE.test(p.key || '')) {
        li.append(h('div.control-row.waiting-do', btn('Stop it', () => controlDone(control.halt(p.key), () => 'Stopping it at its next step. If it is stuck in a command, stop it where it runs.'))));
      } else if (p.kind === 'worn') {
        li.append(h('div.control-row.waiting-do', send('Start fresh with a hand-over',
          `A new agent on ${floor.label} picks up where it left off, handed what it was doing. Stop the old one when the new one has it.`)));
      } else if (p.job) {
        li.append(h('div.control-row.waiting-do', send('Send an agent', `An agent is on its way to ${floor.label} to see to it. Watch it sit down in the Conversations room.`)));
      }
    }
    return li;
  });
}
function briefCard() {
  const now = Date.now() / 1000;
  const b = briefNow();
  if (b.quiet) return null;
  const label = (p) => floorOf(p)?.label || p;
  const done = [...b.finished.map((f) => ({ ...f, said: f.proof ? `Finished, ${f.proof}` : 'Finished', mood: f.proof === 'proven' ? 'ok' : f.proof ? 'failed' : 'check' })),
    ...b.stopped.map((f) => ({ ...f, said: 'Stopped', mood: 'failed' }))];
  return h('section.panel-card',
    sectHead('sun', 'Since you were last here'),
    h('p', sayBrief({ ...b, finished: [], stopped: [] }, label, now).replace(/ Ask me .*$/, '')),
    done.length ? h('ul.list', done.map((f) => {
      const c = work.conversations.find((x) => x.id === f.key);
      return row(c ? convoHref(c) : null, f.title, `${f.project ? `${label(f.project)}. ` : ''}${f.said}`, f.mood);
    })) : null,
    dir === 'data' ? null : h('p.small.muted', `${sinceSaid(b.since, now)}: the sample always starts twelve hours back. With your own company, it starts at your last visit in this browser.`));
}
function healthCard() {
  const each = org.floors.map((f) => ({ f, h: healthOf(f.project, work) }));
  const unwell = each.filter((x) => x.h.state !== 'good');
  const well = each.filter((x) => x.h.state === 'good').map((x) => x.f.label);
  return h('section.panel-card',
    sectHead('heart-pulse', 'Project health'),
    unwell.length ? unwell.map(({ f, h: hh }) => [h('p.health-floor', h('a', { href: `#/${f.id}` }, f.label)), h('ul.list', healthItems(f, hh))]) : empty('Every floor looks healthy.'),
    unwell.length && well.length ? h('p.small.muted', `Healthy: ${well.join(', ')}.`) : null);
}
function floorHealth(floor) {
  const hh = healthOf(floor.project, work);
  if (hh.state === 'good') return null;
  return h('section.panel-card', sectHead('heart-pulse', 'Health'), h('ul.list', healthItems(floor, hh)));
}

// Routines (routines.js): each, its schedule and what its last run came to, with "Run it now" when control is
// on. Ones that need you are in "Waiting on you" too, as tasks.
const routinesNow = () => work.routines.filter((r) => r && r.id && r.label);
function routinesCard() {
  const list = routinesNow();
  if (!list.length) return null;
  const mood = { running: 'working', clear: 'ok', needs: 'failed', waiting: 'quiet' };
  return h('section.panel-card',
    sectHead('clock', 'Routines'),
    h('ul.list', list.map((r) => {
      const now = routineNow(r);
      const li = row(`#/${floorOf(r.project)?.id || ''}`, r.label, `${floorOf(r.project)?.label || r.project}. ${r.when || ''}. ${now.line}`, mood[now.state]);
      if (control.on && dir === 'data' && now.state !== 'running') {
        li.append(h('div.control-row.waiting-do', btn('Run it now', () => controlDone(control.runRoutine(r.id), (x) => `"${x.routine}" is running now.`))));
      }
      return li;
    })),
    h('p.small.muted', 'You only hear about a routine when it needs you.'));
}

// Done means proven (proof.js): the check's last lines when it didn't pass, and, with control on and a check
// on its floor, a way to run it again.
function proofPart(c, pr) {
  if (!pr) return null;
  const check = control.on ? control.checkOf(c.project) : null;
  return h('div.proof',
    pr.tail && h('pre.proof-tail', { 'aria-label': 'What the check printed last' }, pr.tail),
    check && pr.state !== 'checking' && h('div.control-row',
      btn('Check it again', () => controlDone(control.prove(c.id), (r) => `Running ${inner(r.check)} on its work now.`), '', 'rotate-ccw')));
}

// The agents held up waiting on you now (a permission or a question), by conversation.
const heldNow = (items = waitingNow()) => new Set(items.filter((i) => i.kind === 'permission' || i.kind === 'question').map((i) => i.key).filter(Boolean));

// The waiting-time meter (waiting.js): it fills as the longest an agent has been held up grows, amber past five
// minutes and red past fifteen, and under it how long agents waited on you today. tick() keeps it moving.
function waitMeter(items) {
  const now = Date.now() / 1000;
  const m = meter(items, now);
  const sum = waitedSum(waits(history, now, heldNow(items)));
  if (!m && !sum.count) return null;
  return h('div.wait-meter',
    m && h('div.meter', { role: 'meter', 'aria-label': 'How long the longest wait on you has been, in minutes', 'aria-valuemin': 0, 'aria-valuemax': LONG / 60,
      'aria-valuenow': Math.floor(Math.min(LONG, m.seconds) / 60) },
    h(`span.meter-fill.s-${m.mood}`, { 'data-meter': m.item.at, style: `width: ${Math.max(4, Math.round(m.share * 100))}%` })),
    m && h('p.small', 'The longest has waited ', h('span', { 'data-waited': m.item.at }, waitFor(m.seconds)), `: ${waitingHead(m.item)}.`),
    sum.count > 0 && h('p.small.muted', `Today, agents waited on you ${waitFor(sum.total)} in all, ${sum.count === 1 ? 'once' : `${sum.count} times`}. `
      + `The longest wait was ${waitFor(sum.longest.seconds)}.`));
}

// A conversation control can pass a message to: one the Claude Code feed names (connect/control.py, KEY).
const REACHABLE = /^cc-[A-Za-z0-9]{1,12}$/;
// Sent to a conversation that waits for your next message: where it waits, Claude Code or the agent the feed names.
const waitsIn = (key) => `Sent. It is waiting for you in ${work.conversations.find((c) => c.id === key)?.agent || 'Claude Code'}, so it sees this the next time you send it something there.`;
const waitingHead = (i) => ({ permission: `${i.title} wants your permission`, question: `${i.title} is asking`, task: i.title, turn: `${i.title} has finished` })[i.kind];
const waitingHref = (i) => (i.key && i.project ? convoHref({ id: i.key, project: i.project }) : i.task ? taskHref(i.task) : null);
const waitingLink = (i) => ({ title: waitingHead(i), sub: i.project, href: waitingHref(i), mood: i.kind === 'turn' ? 'check' : 'needs' });

// The company's memory as it stands in this tab, and adding to it or taking from it: through control for
// your own company, in this tab only for a made-up one.
const memoryNow = () => [...(work.memory || []).filter((r) => !forgotten.has(r.id)), ...mineMemory];
const memoryWrites = () => dir === 'data' && control.on;
async function rememberIt(text) {
  if (dir === 'data' && !control.on) return "I can't keep that from here while control is off. Add it to data/memory.json, or start Arnheim with --control.";
  if (memoryNow().some((r) => r.text.toLowerCase() === text.toLowerCase())) return `That's remembered already: ${text}`;
  if (memoryWrites()) {
    try {
      const row = await control.remember(text);
      noMemoryUntil = 0; // the file is there now
      work.memory = [...(work.memory || []), row];
      refresh();
      return `Remembered: ${row.text} Every agent hears it as it starts, and those at work with your next message to them.`;
    } catch (error) {
      return error.message;
    }
  }
  mineMemory.push({ id: `tab-${mineMemory.length + 1}`, text, at: Date.now() / 1000 });
  refresh();
  return `Remembered, in this tab only, since this company is made up: ${text} With your own company, every agent would hear it as it starts.`;
}
function forgetIt(r) {
  const i = mineMemory.indexOf(r);
  if (i >= 0) { mineMemory.splice(i, 1); refresh(); return; }
  if (!memoryWrites()) return;
  controlDone(control.forget(r.id).then((out) => { forgotten.add(r.id); return out; }), () => 'Forgotten. Agents that start from now won\'t be told it.');
}

// After an agent is started from the panel: the building turns to the room where it sits down.
function watchStart(p) {
  const floor = org.floors.find((f) => f.project === p.project);
  const room = floor && roomsOf(floor).find((r) => kindOf(floor, r) === 'conversations');
  if (room && !building?.walking?.() && !walkOn()) location.hash = `#/${floor.id}/${room.id}`;
}

// Allows every waiting read at once ("allow all the reads"): what to say when it's done.
const allowReads = (ids) => (!ids.length ? Promise.resolve('Nothing is waiting to read right now.')
  : Promise.allSettled(ids.map((id) => answerAsk(id, 'allow'))).then((out) => {
    const done = out.filter((o) => o.status === 'fulfilled').length;
    if (!done) return out[0].reason?.message || "They couldn't be allowed.";
    const gone = ids.length - done ? ` ${ids.length - done} of them had stopped waiting.` : '';
    return `Allowed ${count(done, 'read', 'reads')}, just this once.${gone} They carry on now.`;
  }));

function waitingItem(i) {
  const agent = i.key ? work.conversations.find((c) => c.id === i.key)?.agent : null; // another agent than Claude Code
  const where = [i.project ? (floorOf(i.project)?.label || i.project) : '', agent].filter(Boolean).join('. ');
  const href = waitingHref(i);
  const head = waitingHead(i);
  const marked = i.review || i.proof;
  const what = i.kind === 'task' ? null : i.kind === 'permission' ? `It wants ${i.what}` : marked ? `${marked.word}. ${i.what}` : i.what;
  const sub = [what, where].filter(Boolean).map((part, n, all) => (n < all.length - 1 && !/[.?!]$/.test(part) ? `${part}.` : part)).join(' ');
  const li = row(href, head, sub, i.kind === 'turn' ? reviewMood(i.review) || proofMood(i.proof) || 'check' : 'needs');
  const waited = waitingLine(i);
  if (waited) li.querySelector('.row-main')?.append(h('span.row-sub.wait-time', { 'data-wait': i.at }, waited));
  li.append(...waitingActions(i));
  return li;
}

// The answers a waiting item takes, where it is: Allow and Deny, run a routine again, let a floor go on,
// send a decision made before, or a reply. The home view shows the same under the one it puts first.
function waitingActions(i, { keys = false } = {}) {
  const out = [];
  if (canAnswer(i)) {
    // never green: every request that asks reaches outside the project or changes something, so yes is never the easy reflex
    const label = (text, key) => (keys ? [text, h('span.kbd', key)] : text);
    out.push(h('div.control-row.waiting-do',
      h('button.btn.primary', { type: 'button', onclick: () => answerOnce(i, 'allow') }, label('Allow', 'A')),
      h('button.btn', { type: 'button', onclick: () => answerOnce(i, 'deny') }, label('Deny', 'D'))));
    const before = Number(i.ask?.before) || 0;
    if (i.ask?.standable && before >= 2 && control.on && !i.ask?.sample) {
      // the same exact command, allowed twice already on this floor: offer to stop asking (connect/standing.py)
      const floor = floorOf(i.ask.project)?.label || i.ask.project || 'this floor';
      out.push(h('div.waiting-do.always-offer',
        h('p.small', `You've allowed this ${before} times on ${floor} lately. Always allow this exact command there, for every agent?`),
        h('div.control-row', btn('Always allow here', () => {
          if (answered.has(i.ask.id)) return;
          markAnswered(i.ask.id);
          controlDone(control.always(i.ask.id), () => `Allowed, and from now on on ${floor} without asking. Settings lists it, to take back.`);
        }))));
    }
  }
  if (i.kind === 'task' && i.task?.routine && control.on && dir === 'data') {
    out.push(h('div.control-row.waiting-do',
      btn('Run it again', () => controlDone(control.runRoutine(i.task.routine), (r) => `"${r.routine}" is running again.`), '.primary')));
  }
  if (i.kind === 'task' && i.task?.budget && control.on && dir === 'data') {
    out.push(h('div.control-row.waiting-do',
      btn('Let them go on', () => controlDone(control.allowMore(i.task.budget), (r) => `${i.task.budget}'s agents may spend as much again today. Tell them to go on.`), '.primary')));
  }
  const decided = i.kind === 'question' ? decidedFor(i.what, memoryNow()) : [];
  const reachable = control.on && (REACHABLE.test(i.key) || control.run(i.key));
  if (decided.length) {
    out.push(h('div.waiting-do.decided',
      h('p.small', h('span.muted', 'You decided before: '), decided.map((r) => r.text).join(' ')),
      reachable && h('div.control-row', btn('Send it that', () => controlDone(control.say(i.key, `You decided this before: ${decided.map((r) => r.text).join(' ')}`),
        () => waitsIn(i.key)), '.primary'))));
  }
  if ((i.kind === 'question' || i.kind === 'turn') && reachable) {
    const send = (event) => {
      event.preventDefault();
      const input = event.currentTarget.elements.text;
      const text = input.value.trim();
      if (!text) return;
      input.value = '';
      input.blur();
      controlDone(control.say(i.key, text), (r) => (r.sent === 'resumed' ? 'Sent. It is answering now.'
        : waitsIn(i.key)));
    };
    out.push(h('form.control-say.waiting-do', { onsubmit: send },
      h('input', { name: 'text', type: 'text', maxlength: 2000, autocomplete: 'off', placeholder: i.kind === 'question' ? 'Answer it' : 'What next?', 'aria-label': `A reply to ${i.title}` }),
      h('button.btn', { type: 'submit' }, 'Send')));
  }
  if (!control.on && dir === 'data' && (i.kind === 'permission' || i.kind === 'question') && REACHABLE.test(i.key || '')) {
    // your own agents, with control off: say where the answer goes instead of leaving no way to give it
    const agent = work.conversations.find((c) => c.id === i.key)?.agent || 'Claude Code';
    out.push(h('p.small.muted.answer-where.waiting-do', `Answer it in ${agent}, where it runs. To answer here too, start Arnheim with `,
      h('code', 'python3 serve.py --control'), '.'));
  }
  return out;
}

// A floor's Conversations room: start an agent on its project, in its folder.
function startForm(floor) {
  const p = control.projects().find((x) => x.project === floor.project);
  if (!p) return null;
  const go = (event) => {
    event.preventDefault();
    const input = event.currentTarget.elements.text;
    const text = input.value.trim();
    if (!text) return;
    input.value = '';
    input.blur();
    controlDone(control.begin(p.project, text), () => `Started. It shows here once it begins.`);
  };
  return h('form.control.control-start', { onsubmit: go },
    h('h3', 'Start an agent here'),
    h('textarea', { name: 'text', rows: 3, maxlength: 2000, placeholder: `What should it do on ${floor.label}?`, 'aria-label': `What a new agent on ${floor.label} should do` }),
    h('div.control-row', h('button.btn.primary', { type: 'submit' }, 'Start')),
    h('p.small.muted', 'It runs in this project\'s folder with your own Claude Code settings, as if you had started it there.'),
    noteOnce());
}

/* ---------- the panel ---------- */

function crumbsFor(floor, room, last) {
  const list = [[org.company, '#/activity']];
  if (floor) list.push([floor.label, `#/${floor.id}`]);
  if (room) list.push([room.label, `#/${floor.id}/${room.id}`]);
  if (last) list.push([last]);
  return list;
}

// The one waiting item the home view puts first, with everything needed to answer it where it is: what it
// wants exactly, how careful to be, what it means in plain words, and its answers.
const later = new Set(); // items put off with Later, for this visit: they go to the end of the list
let focusNow = null; // the item the home view shows first, for the A, D and L keys (null on any other view)
let focusId = null; // which item that was, across renders
let focusSince = 0; // when it became first: keys wait a second after it changes, so a press meant for one never answers the next
function focusCard(i, { open = true } = {}) {
  const k = kindWord(i);
  const risk = riskOf(i);
  const exact = i.kind === 'permission' ? exactOf(i) : null;
  const agent = i.key ? work.conversations.find((c) => c.id === i.key)?.agent || (REACHABLE.test(i.key) ? 'Claude Code' : null) : null;
  const where = [i.project ? (floorOf(i.project)?.label || i.project) : '', agent, waitingLine(i)].filter(Boolean).join(' · ');
  const verb = exact && i.what.endsWith(exact) ? i.what.slice(0, -exact.length).trim() : i.what;
  const heading = { permission: `${i.title} wants your permission`, question: `${i.title} asks you`, turn: `${i.title} has finished`, task: i.title }[i.kind];
  const marked = i.review || i.proof;
  const what = i.kind === 'permission' ? `It wants ${verb}${exact ? ':' : '.'}`
    : i.kind === 'question' ? `"${i.what}"` : i.kind === 'turn' ? [marked && `${marked.word}. ${marked.line}`, i.what].filter(Boolean).join(' ') : i.what || i.task?.says?.now || '';
  const href = waitingHref(i);
  const meaning = meaningOf(i);
  return h('section.focus', { 'aria-label': `First: ${heading}` },
    h('div.focus-top', h(`span.pill.k-${k.mood}`, k.word), where && h('span', where), i.ask?.sample && h('span.practice', 'Practice: nothing real runs')),
    h('h3.focus-title', heading),
    what && h('p.focus-what', what),
    exact && h('div.what-code', exact),
    risk && h('p.risk', h(`b.risk-${risk.mood}`, `${risk.word}. `), risk.line),
    meaning && h('details.explain', h('summary', 'What does this mean?'), h('p', meaning)),
    h('div.focus-do',
      ...waitingActions(i, { keys: open }),
      open && href && h('a.btn.quiet', { href }, 'Open'),
      open && h('button.btn.quiet', { type: 'button', onclick: () => { later.add(i.id); render(); }, title: 'Put it at the end of the list (L)' }, 'Later', h('span.kbd', 'L')),
));
}

function viewOverview() {
  const all = waitingNow();
  const waiting = [...all.filter((i) => !later.has(i.id)), ...all.filter((i) => later.has(i.id))];
  const talking = byProject(work.conversations.filter((c) => c.working));
  const jobs = work.jobs.filter((j) => j.state === 'running');
  const first = waiting[0] || null;
  if ((first?.id ?? null) !== focusId) { focusId = first?.id ?? null; focusSince = Date.now(); }
  focusNow = first;
  const rest = waiting.slice(1);
  const agentsRest = rest.filter((i) => i.kind !== 'task');
  const yours = rest.filter((i) => i.kind === 'task');
  const now = Date.now() / 1000;
  const blocked = waiting.filter((i) => (i.kind === 'permission' || i.kind === 'question') && i.at > 0);
  const oldest = blocked.length ? Math.max(...blocked.map((i) => now - i.at)) : 0;
  const moving = talking.length + jobs.length;
  const heading = waiting.length ? count(waiting.length, 'thing needs you', 'things need you') : 'Nothing needs you';
  const sub = waiting.length
    ? (oldest > 0 ? `The longest an agent has waited is ${waitFor(oldest)}.` : 'The first is below, with its answer.')
    : 'All quiet. Anything that stops for you shows here first.';
  const reads = control.on ? together(waiting) : null;
  return {
    top: true,
    crumbs: [],
    body: [
      h('div.home-head', h('h2', { id: 'view-title', tabindex: '-1' }, heading), h('p', sub), noteOnce('.done-note')),
      fromAway() && !phoneMe?.phone && h('p.small', h('strong', 'View only. '), 'You are looking from another device: you can look round and walk in, but nothing here changes anything.'),
      pausedCard(),
      firstRun && (flow ? setupCard() : welcomeCard()),
      connectedCard(),
      firstCard(),
      updateCard(),
      first && focusCard(first),
      clashCard(),
      agentsRest.length > 0 && h('section.panel-card.home-more',
        sectHead('bell', `More agents waiting (${agentsRest.length})`),
        reads && h('div.control-row', { style: 'margin-bottom: 8px' }, btn(reads.label, () => controlDone(allowReads(reads.ids), (said) => said), '.primary')),
        h('ul.list', agentsRest.map(waitingItem))),
      yours.length > 0 && h('section.panel-card.home-more',
        sectHead('list-checks', `Your to-dos (${yours.length})`),
        h('ul.list', yours.map(waitingItem))),
      h('section.panel-card',
        sectHead('zap', moving ? `Working now (${moving})` : 'Working now'),
        moving
          ? h('ul.list', [
            ...talking.map((c) => row(convoHref(c), c.title, [floorOf(c.project)?.label || c.project, c.agent, c.says?.now].filter(Boolean).join(' · '), 'working')),
            ...jobs.map((j) => row(`#/${org.basement?.id}/${j.machine}`, j.name, `On the ${machineLabel(j.machine)}`, 'working')),
          ])
          : empty('Nothing is working right now.')),
      briefCard(),
      alertOffer(),
    ],
  };
}

// Activity: what each project is doing, what it has cost, how the day and the week went. Everything that isn't
// waiting on you lives here, so the Needs you tab stays short.
function viewActivity() {
  const all = waitingNow();
  return {
    top: true,
    crumbs: [],
    body: [
      title('Activity'),
      h('p.muted', 'What each project is doing, what it has cost, and how the day went.'),
      h('section.panel-card', sectHead('layers', 'Floors'), h('ul.list', floors().map((f) => {
        const lines = floorLines(f);
        return row(`#/${f.id}`, f.label, lines.map((l) => l.text).join(' · '), lines[0]?.kind || 'quiet');
      }))),
      usageCard(),
      spendCard(),
      healthCard(),
      waitMeter(all) && h('section.panel-card', waitMeter(all)),
      routinesCard(),
      weekCard(),
      replayCard(),
      hasStory() && h('section.panel-card',
        sectHead('history', 'Just now'),
        happened.length
          ? h('ul.list.happened', happened.map((e) => h('li', h('div.row', dot('quiet'), h('span.row-main', h('span.row-title', e.line), h('span.row-sub', { 'data-at': e.at }, agoText(e.at)))))))
          : empty(playing ? 'The work starts moving in a few seconds.' : 'Paused. Choose Resume the sample, in the ... menu at the top, to let the work move.')),
      h('div.intro-small',
        h('p', h('strong', madeUp() ? `${org.company} is made up. ` : `${org.company}. `), madeUp() ? sampleLine() : org.about || ''),
        h('p', `Each floor of the building is a project and each room holds one kind of thing. Tap a floor to bring it out. Press Walk to go in and talk to the people at work, and to ${deskName() || 'the receptionist'} at the front desk.`),
        h('p', dir === 'data'
          ? 'Everything here comes from data/company.json (the building), and from data/work.json and any tools connected to it (what is going on in it). A change to the work shows within a few seconds; reload after changing the building.'
          : 'Everything here comes from two files: sample/company.json (the building) and sample/work.json (what is going on in it).')),
    ],
  };
}

// While every agent is paused (Pause all, at the top): say so, with the way to let them go on.
function pausedCard() {
  if (!control.on || dir !== 'data' || !control.paused()) return null;
  const since = new Date(control.paused() * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  return h('section.panel-card.pause.paused', { 'aria-live': 'polite' },
    h('p', h('strong', 'Every agent is paused.'), ` Since ${since}. Each stopped at its next step, and a message sent to one in Claude Code waits until you resume.`),
    h('div.control-row', btn('Resume all', () => controlDone(control.resumeAll(), () => ''), '.primary', 'rotate-ccw')));
}

// The sample's first moment: what it is, and the two ways on, before anything else asks for an answer.
function welcomeCard() {
  if (!madeUp() || fromAway() || kept(WELCOMED) === '1') return null;
  if (!setupAsked) { // whether Claude Code is here, so Connect can open here
    setupAsked = true;
    setupGet('here').then((got) => { setupHere = got; render(); });
  }
  const connect = () => {
    keep(WELCOMED, '1');
    if (setupHere?.claude) openFlow();
    else goTo('#/company');
  };
  const look = () => {
    keep(WELCOMED, '1');
    keep(TOUR_SEEN, '1');
    render();
    if (!walkOn()) tour.open();
  };
  return h('section.panel-card.welcome-card', { 'aria-label': 'Welcome' },
    h('p.welcome-title', 'Welcome to Arnheim'),
    h('p', `Arnheim shows your AI agents' work as a building: a floor for each project, lit when an agent works or needs you. ${org.company} is a made-up company, so you can try everything here: answer its agents, walk in, ask ${deskName() ? `${deskName()}, the receptionist,` : 'the receptionist'} a question. Nothing you press changes anything real.`),
    h('div.control-row',
      h('button.btn.primary', { id: 'welcome-connect', type: 'button', onclick: connect }, icon('zap', 15), 'Connect my agents'),
      h('button.btn', { id: 'welcome-look', type: 'button', onclick: look }, 'Look around first')));
}

// With no data/ yet: the one step from the made-up company to your own projects and agents. On this computer's own
// page, Connect my agents does it here (serve.py's /setup/, which runs connect/setup.py); elsewhere, or without Claude
// Code, the command for a terminal, with what it touches and what it never does.
let setupNote = '';
let setupHere = null; // what /setup/here said: { token, claude, install, company }, or null where there is none
let setupAsked = false;
let flow = null; // Connect my agents while it is open: { step, plan, ticked, typed, control, error } (welcome.js)
let undoneNote = keptJson(UNDONE, 'sessionStorage'); // what Undo did, said once on the made-up company it went back to
const setupGet = (name) => fetch(`setup/${name}`, { cache: 'no-store', credentials: 'same-origin' })
  .then((r) => (r.ok ? r.json() : null)).catch(() => null);
async function setupPost(name, body, again = false) {
  let r;
  try {
    r = await fetch(`setup/${name}`, {
      method: 'POST', cache: 'no-store', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Arnheim-Switches': setupHere?.token || '' }, body: JSON.stringify(body),
    });
  } catch { return { error: 'Arnheim didn\'t answer. Is it still running?' }; }
  if (r.status === 403 && !again) { // Arnheim started again, with a new token
    setupHere = await setupGet('here');
    if (setupHere) return setupPost(name, body, true);
  }
  const data = await r.json().catch(() => ({}));
  return r.ok ? data : { ...data, error: data.error || `Arnheim answered ${r.status}.` };
}
// What setup said it did, in its own words, kept open across the panel's redraws once opened.
let logOpen = false;
const doneLog = (lines) => h('details.connect-log', { open: logOpen, ontoggle: (event) => { logOpen = event.currentTarget.open; } },
  h('summary', 'What was done'), h('pre.connect-lines', lines.join('\n')));
// Back to Needs you, freshly loaded: your own company once it is there, or the made-up one again.
const reloadHome = () => {
  window.history.replaceState(null, '', location.pathname + location.search);
  try { window.history.scrollRestoration = 'manual'; } catch { /* the top anyway */ }
  window.scrollTo(0, 0); // on a phone the page itself scrolls: start at the top, where the news is
  location.reload();
};

async function openFlow() {
  flow = { step: 'loading' };
  render();
  const plan = await setupGet('plan');
  if (!flow) return; // closed meanwhile
  if (!plan) { flow = { step: 'failed' }; render(); return; }
  if (plan.token) setupHere = { ...(setupHere || {}), token: plan.token };
  flow = connectStart(plan);
  render();
  $('connect-flow')?.focus({ preventScroll: true });
}
async function connectNow() {
  if (!flow || flow.step !== 'form') return;
  const typed = $('connect-typed');
  if (typed) flow.typed = typed.value;
  if ($('content').contains(document.activeElement)) document.activeElement.blur(); // pressed Enter in the box: the panel redraws now
  flow.step = 'working';
  flow.error = '';
  render();
  const out = await setupPost('connect', connectRequest(flow));
  if (out.error) {
    flow.step = 'form';
    flow.error = out.error;
    render();
    $('connect-error')?.focus({ preventScroll: true });
    return;
  }
  keep(CONNECTED, JSON.stringify({ lines: out.lines || [], note: out.note || '', control: out.control ?? null, at: Date.now() }));
  keep(CODEX, flow.plan?.codex?.hooks ? '1' : '0'); // the first card names Codex only if its hooks went in
  unkeep(FIRST); // your own company's first agent: waited for afresh
  reloadHome();
}
function connectFlow() {
  const f = flow;
  const head = sectHead('zap', 'Connect my agents');
  const closeFlow = () => { flow = null; render(); };
  if (f.step === 'loading') return [head, h('p', { role: 'status' }, 'Looking for the projects you have worked on with Claude Code or Codex...')];
  if (f.step === 'failed') {
    return [head, h('p.banner.fail', { role: 'alert' }, 'Arnheim couldn\'t look for your projects. Is it still running? Reload the page to try again.'),
      h('div.control-row', btn('Close', closeFlow))];
  }
  const plan = f.plan;
  const working = f.step === 'working';
  const projects = plan.projects;
  const tick = (folder) => (event) => { if (event.currentTarget.checked) f.ticked.add(folder); else f.ticked.delete(folder); };
  return [head,
    h('form.connect-form', { onsubmit: (event) => { event.preventDefault(); connectNow(); }, 'aria-busy': working ? 'true' : null },
      h('fieldset.connect-set',
        h('legend', projects.length ? 'Give each of these a floor' : 'Your projects'),
        projects.length
          ? h('ul.switch-list', projects.map((p) => h('li', h('label.switch',
            h('input', { type: 'checkbox', name: 'folder', value: p.folder, checked: f.ticked.has(p.folder), disabled: working, onchange: tick(p.folder) }),
            h('span', h('b', p.label), h('span.small.muted', `${p.folder}, ${p.when}`))))))
          : h('p.small.muted', 'Found none: no recent Claude Code or Codex conversation ran in a project folder that is still there. Type a project\'s folder below.')),
      h('label.connect-typed', h('span.small', projects.length ? 'Add another project\'s folder (optional)' : 'A project\'s folder'),
        h('input', { id: 'connect-typed', type: 'text', name: 'typed', value: f.typed, placeholder: '~/code/my-project', autocomplete: 'off',
          autocapitalize: 'off', spellcheck: 'false', disabled: working, oninput: (event) => { f.typed = event.currentTarget.value; } })),
      h('fieldset.connect-set',
        h('legend', 'Answer your agents from the building too?'),
        h('label.switch', h('input', { type: 'radio', name: 'control', value: 'yes', checked: f.control, disabled: working, onchange: () => { f.control = true; } }),
          h('span', h('b', 'Yes'), h('span.small.muted', 'Allow or Deny their permission requests, and send them messages, from this page on this computer. A phone can join later, in Settings, under Your phone.'))),
        h('label.switch', h('input', { type: 'radio', name: 'control', value: 'no', checked: !f.control, disabled: working, onchange: () => { f.control = false; } }),
          h('span', h('b', 'No'), h('span.small.muted', 'Each agent asks in its own window, as usual. You can switch it on later, in Settings, under Switches.')))),
      h('ul.connect-found',
        h('li', plan.claude ? 'Claude Code: found.' : 'Claude Code: not found on this computer.'),
        h('li', codexLine(plan.codex)),
        (plan.codex?.notes || []).map((n) => h('li.small.muted', n))),
      f.error && h('p.banner.fail', { id: 'connect-error', role: 'alert', tabindex: '-1' }, f.error),
      h('div.control-row',
        h('button.btn.primary', { id: 'connect-go', type: 'submit', disabled: working }, working ? 'Connecting...' : 'Connect'),
        h('button.btn', { id: 'connect-cancel', type: 'button', disabled: working, onclick: closeFlow }, 'Cancel')),
      h('p.small.muted', `It writes your building to data/, a floor for each project, and adds Arnheim's hooks and status line to Claude Code's settings${plan.codex?.hooks ? ', and its hooks to Codex\'s' : ''}, keeping a copy of each file first. It never changes your projects' files, and Undo takes it out again. To start Arnheim each time you log in, run `, h('code.nowrap', 'python3 serve.py --always'), ' in a terminal on this computer.'))];
}

function setupCard() {
  const command = 'python3 connect/setup.py';
  const copy = (event) => {
    const code = event.currentTarget.parentElement.querySelector('code');
    const select = (el) => {
      const range = document.createRange();
      range.selectNodeContents(el);
      getSelection().removeAllRanges();
      getSelection().addRange(range);
    };
    const older = () => { // for browsers that keep the clipboard to themselves
      select(code);
      let copied = false;
      try { copied = document.execCommand('copy'); } catch { copied = false; }
      setupNote = copied ? 'Copied.' : 'Selected: copy it with Ctrl-C, or Cmd-C on a Mac.';
      render();
      const again = !copied && document.querySelector('.setup-run code');
      if (again) select(again);
    };
    if (navigator.clipboard?.writeText) navigator.clipboard.writeText(command).then(() => { setupNote = 'Copied.'; render(); }, older);
    else older();
  };
  if (!fromAway() && !setupAsked) { // this computer's own page: whether Claude Code is here, so the button can show
    setupAsked = true;
    setupGet('here').then((got) => { setupHere = got; render(); });
  }
  if (flow) return h('section.panel-card.setup-card.connect-flow', { id: 'connect-flow', tabindex: '-1', 'aria-label': 'Connect my agents' }, connectFlow());
  const terminal = [
    h('div.setup-run', h('code', command), btn('Copy', copy), setupNote && h('span.small.muted', { role: 'status' }, setupNote)),
    h('p.small.muted', 'It finds the projects you have worked on with Claude Code or Codex and asks before it changes anything. It writes your building to data/, a floor for each project, and adds Arnheim\'s hooks to Claude Code\'s settings and Codex\'s, keeping a copy of each file first. It never changes your projects\' files, and python3 connect/setup.py --undo takes the hooks out again. Then reload this page. On Windows, type py instead of python3.'),
  ];
  const here = !fromAway() && setupHere;
  return h('section.panel-card.setup-card',
    sectHead('laptop', 'See your own agents here'),
    undoneNote && h('div.undone-note', { role: 'status' },
      h('p', h('strong', 'Undone. '), 'Arnheim\'s hooks are out of your settings, and this is the made-up company again.'),
      undoneNote.lines?.length > 0 && doneLog(undoneNote.lines),
      h('div.control-row', btn('Got it', () => { undoneNote = null; unkeep(UNDONE, 'sessionStorage'); render(); }))),
    here?.claude
      ? [h('p', `${org.company} is made up. To see your own projects, and the Claude Code and Codex conversations working in them, connect your agents. Nothing changes until you press Connect.`),
        h('div.control-row.setup-go', h('button.btn.primary', { id: 'connect-open', type: 'button', onclick: openFlow }, icon('zap', 15), 'Connect my agents')),
        h('details.setup-terminal', h('summary.small.muted', 'Or use a terminal instead'), h('p.small.muted.setup-or', 'Run this in Arnheim\'s folder:'), terminal)]
      : here && here.claude === false
        ? [h('p', `${org.company} is made up. Claude Code isn't on this computer, so there are no agents to connect yet. `,
          h('a', { href: here.install || 'https://claude.com/claude-code', target: '_blank', rel: 'noopener' }, 'Install Claude Code'), ', then reload this page.'),
          h('p.small.muted.setup-or', 'With Codex alone, run this in a terminal, in Arnheim\'s folder:'), terminal]
        : [h('p', `${org.company} is made up. To see your own projects, and the Claude Code and Codex conversations working in them, run this in a terminal, in Arnheim's folder:`), terminal]);
}

// Once Connect my agents has done it: your own company, what was done, and Undo (hooks and status line out, and your
// building put aside in data/backups/, so the page goes back to the made-up company).
let connectedNote = keptJson(CONNECTED);
// Connect reloads the page: the press of Connect still counts as using it, so the top light says Answering here at once.
if (connectedNote?.at && Date.now() - connectedNote.at < 120000) control.touch(connectedNote.at);
let undoAsk = false;
async function undoConnect() {
  connectedNote = { ...connectedNote, working: true, error: '' };
  render();
  if (!setupHere) setupHere = await setupGet('here');
  const out = await setupPost('undo', {});
  if (out.error) {
    connectedNote = { ...connectedNote, working: false, error: out.error };
    render();
    return;
  }
  unkeep(CONNECTED);
  unkeep(FIRST);
  keep(UNDONE, JSON.stringify({ lines: out.lines || [] }), 'sessionStorage');
  reloadHome();
}
// Done with the card: the tour stays in the ... menu and Settings, and no longer opens by itself.
const connectedGone = () => { unkeep(CONNECTED); connectedNote = null; keep(TOUR_SEEN, '1'); };
function connectedCard() {
  if (!connectedNote || !ownCompany() || fromAway()) return null;
  const n = connectedNote;
  return h('section.panel-card.connected-card',
    sectHead('circle-check', 'Your agents are connected'),
    h('p', `This is ${org.company}, your own building, with a floor for each project. Conversations you start in their folders from now on show here.`),
    n.control === true && h('p.small', 'You answer their permission requests here too, while you use this page.'),
    n.note && h('p.small.note', n.note),
    n.lines?.length > 0 && doneLog(n.lines),
    n.error && h('p.banner.fail', { role: 'alert' }, n.error),
    undoAsk
      ? h('div.connect-undo',
        h('p.small', 'Take Arnheim\'s hooks and status line out of Claude Code\'s and Codex\'s settings, and put your building aside in data/backups/, so this goes back to the made-up company?'),
        h('div.control-row',
          h('button.btn.primary', { id: 'undo-go', type: 'button', disabled: !!n.working, onclick: undoConnect }, n.working ? 'Undoing...' : 'Undo'),
          h('button.btn', { id: 'undo-keep', type: 'button', disabled: !!n.working, onclick: () => { undoAsk = false; render(); } }, 'Keep it')))
      : h('div.control-row',
        h('button.btn.primary', { id: 'connected-ok', type: 'button', onclick: () => { connectedGone(); render(); } }, 'Got it'),
        !walkOn() && h('button.btn', { id: 'connected-tour', type: 'button', onclick: () => { connectedGone(); render(); tour.open(); } }, 'Show me around'),
        h('button.btn.quiet', { id: 'undo-ask', type: 'button', onclick: () => { undoAsk = true; render(); $('undo-keep')?.focus(); } }, 'Undo')));
}

// Your own company's first moment (welcome.js): until a conversation has ever been seen in this browser, a card that
// says where to start one; when the first comes, the card goes, and a note says it is here, once.
let firstState = null;
let firstArrived = null;
function firstCard() {
  if (!ownCompany()) return null;
  const seen = kept(FIRST) === '1';
  const now = firstMoment({ seen, waiting: !!firstState?.waiting, conversations: work.conversations });
  if (now.seen && !seen) keep(FIRST, '1');
  if (now.arrived) firstArrived = now.arrived;
  firstState = now;
  if (now.waiting) {
    const folders = floorFolders(org);
    const codex = kept(CODEX) !== '0'; // connected from the page without Codex: '0'; set up in a terminal: not known
    const agent = codex ? 'Claude Code (or Codex)' : 'Claude Code';
    return h('section.panel-card.first-card',
      sectHead('bot', 'Waiting for your first agent'),
      folders.length
        ? [h('p', `Open ${agent} in one of these folders, and it shows here as it starts:`),
          h('ul.first-folders', folders.map((x) => h('li', h('code', x.folder), x.floor && h('span.small.muted', ` ${x.floor}`))))]
        : h('p', `Give a floor its folder in data/company.json, then open ${agent} there, and it shows here as it starts.`),
      codex && h('p.small.muted', 'Codex runs Arnheim\'s hooks once you trust them: type /hooks in Codex, once.'));
  }
  if (!firstArrived) return null;
  const c = firstArrived;
  const floor = floorOf(c.project);
  return h('section.panel-card.first-card.arrived', { role: 'status' },
    sectHead('circle-check', 'Your first agent is here'),
    h('p', `${c.title || 'A conversation'}${floor ? `, on ${floor.label}` : ''}. Its floor lights up while it works, and turns amber when it needs you.`),
    h('div.control-row',
      floor && h('a.btn.primary', { href: convoHref(c) }, 'See it'),
      h('button.btn', { id: 'first-ok', type: 'button', onclick: () => { firstArrived = null; render(); } }, 'Got it')));
}

// A newer Arnheim (serve.py's /update, the "Look for a newer Arnheim" switch): a notice on this computer's own page,
// with Update now, which pulls it from GitHub and starts Arnheim again, and the way to do it by hand.
let updateState = null; // what /update said: { token, behind? }
let updateNote = '';
let updateBusy = false;
async function readUpdate() {
  if (fromAway()) return;
  try {
    const r = await fetch('update', { cache: 'no-store', credentials: 'same-origin' });
    updateState = r.ok ? await r.json() : null;
  } catch { updateState = null; }
}
async function backAgain(most = 5 * 60000) {
  const until = Date.now() + most;
  await pause(1500);
  while (Date.now() < until) {
    const stop = new AbortController();
    const timer = setTimeout(() => stop.abort(), 3000);
    try {
      const r = await fetch('look', { cache: 'no-store', signal: stop.signal });
      if (r.ok) return true;
    } catch { /* still starting */ } finally { clearTimeout(timer); }
    await pause(1000);
  }
  return false;
}
async function updateArnheim() {
  if (updateBusy) return;
  updateBusy = true;
  updateNote = '';
  render();
  let out;
  try {
    const r = await fetch('update', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-Arnheim-Switches': updateState?.token || '' }, body: '{}',
    });
    out = await r.json().catch(() => ({}));
    if (!r.ok) out = { error: out.error || `Arnheim answered ${r.status}. Reload the page and try again.` };
  } catch { out = { error: 'Arnheim didn\'t answer. Is it still running?' }; }
  if (out.error) { updateBusy = false; updateNote = out.error; render(); return; }
  updateNote = out.said || 'Updated.';
  render();
  if (!out.restarting) { updateBusy = false; updateState = { ...updateState, behind: 0 }; render(); return; }
  if (await backAgain()) { reloadHome(); return; }
  updateBusy = false;
  updateNote = 'Arnheim hasn\'t come back yet. Look in the terminal it runs in, or start it again there: python3 serve.py';
  render();
}
function updateCard() {
  if (fromAway() || !updateState || (!updateState.behind && !updateNote)) return null;
  const behind = updateState.behind > 0;
  return h('section.panel-card.update-card',
    sectHead('sparkles', behind ? updateLine(updateState.behind) : 'Arnheim'),
    behind && h('div.control-row',
      h('button.btn.primary', { id: 'update-now', type: 'button', disabled: updateBusy, onclick: updateArnheim }, updateBusy ? 'Updating...' : 'Update now')),
    updateNote && h('p.small.note', { role: 'status' }, updateNote),
    behind && h('p.small.muted', 'Update now gets it from GitHub and starts Arnheim again. By hand, in Arnheim\'s folder in a terminal: ',
      h('code', 'git pull'), ', then start Arnheim again. Switch off Look for a newer Arnheim, in Settings, to stop this notice.'));
}

// The first tour (tour.js): once per browser, by itself, and any time from the ... menu or Settings.
const storageWorks = () => { try { window.localStorage.setItem('arnheim-probe', '1'); window.localStorage.removeItem('arnheim-probe'); return true; } catch { return false; } };
function maybeTour() {
  if (document.getElementById('welcome-look')) return; // the welcome card on screen offers it: Look around first
  if (connectedNote && ownCompany()) return; // just connected: that card offers the tour (Show me around)
  const seen = kept(TOUR_SEEN) === '1' || !storageWorks(); // a browser that can't remember would see it on every visit
  if (!tourWanted({ seen, embedded: window.self !== window.top, away: fromAway(), walking: walkOn() || !!building?.walking?.() })) return;
  keep(TOUR_SEEN, '1');
  tour.open();
}
const tourLink = () => !fromAway() && h('button.linkish', { type: 'button', onclick: () => { if (!walkOn()) tour.open(); } }, 'Show the tour again');

function viewCompany() {
  return {
    top: true,
    crumbs: [],
    body: [
      title('Settings'),
      firstRun && setupCard(),
      agentsCard(),
      memoryCard(),
      alwaysCard(),
      switchesCard(),
      h('section.panel-card.company-card',
        sectHead('building-2', org.company),
        org.mission && h('p.mission', h('span.muted', 'Mission: '), org.mission),
        org.about && h('p', org.about)),
      !fromAway() && h('p.small.muted.tour-again', 'New here? ', tourLink()),
    ],
  };
}

// Your own company in Settings: that your agents are connected, and the way back (connect/setup.py --undo).
function agentsCard() {
  if (!ownCompany() || fromAway() || route.floor !== 'company') return null;
  const n = connectedNote || {};
  return h('section.panel-card.agents-card',
    sectHead('laptop', 'Your agents'),
    h('p', `Connected: ${count(org.floors.length, 'project has its floor', 'projects have their floors')}. Claude Code and Codex conversations started in their folders show here as they work.`),
    n.error && h('p.banner.fail', { role: 'alert' }, n.error),
    undoAsk
      ? h('div.connect-undo',
        h('p.small', 'Take Arnheim\'s hooks and status line out of Claude Code\'s and Codex\'s settings, and put your building aside in data/backups/, so this goes back to the made-up company?'),
        h('div.control-row',
          h('button.btn.primary', { id: 'undo-go', type: 'button', disabled: !!n.working, onclick: undoConnect }, n.working ? 'Undoing...' : 'Undo'),
          h('button.btn', { id: 'undo-keep', type: 'button', disabled: !!n.working, onclick: () => { undoAsk = false; render(); } }, 'Keep it')))
      : h('div.control-row', h('button.btn.quiet', { id: 'undo-ask', type: 'button', onclick: () => { undoAsk = true; render(); $('undo-keep')?.focus(); } }, 'Undo connecting')));
}

// The commands you allowed for good (connect/standing.py), each a press away from asking again.
function alwaysCard() {
  if (dir !== 'data' || !control.on) return null;
  const rows = control.standing();
  const when = (at) => new Date(at * 1000).toLocaleDateString([], { day: 'numeric', month: 'short' });
  return h('section.panel-card.always',
    sectHead('shield-check', 'Always allowed'),
    h('p.small.muted', 'Exact commands your agents run on a floor without asking you, for Claude Code and Codex alike. Only plain test, check and build commands, and ones that only look, can be here.'),
    !switchOn('always') && h('p.small.note', 'Always allow is switched off under Switches: each of these asks again until it is back on.'),
    rows.length ? h('ul.list', rows.map((r) => h('li', h('div.row.memory-row', dot('quiet'),
      h('span.row-main', h('span.row-title', h('code', String(r.what || '').replace(/^Bash: /, ''))),
        h('span.row-sub', [floorOf(r.project)?.label || r.project, `since ${when(r.at)}`, r.used ? `used ${r.used} time${r.used === 1 ? '' : 's'}` : 'not used yet'].join(' · '))),
      btn('Stop allowing', () => controlDone(control.unalways(r.id), () => `It asks again on ${floorOf(r.project)?.label || r.project}.`))))))
      : empty('Nothing yet. When you have allowed the same command twice on a floor, the next request offers "Always allow here".'),
    noteOnce());
}

// What every agent is told: the company's memory, with a way to add to it and take from it.
function memoryCard() {
  const rows = memoryNow();
  const canAdd = dir !== 'data' || control.on;
  const add = (event) => {
    event.preventDefault();
    const input = event.currentTarget.elements.text;
    const text = rememberAsked(`remember ${input.value}`);
    if (!text) return;
    input.value = '';
    input.blur();
    rememberIt(text).then((said) => { controlNote = said; render(); });
  };
  return h('section.panel-card.memory',
    sectHead('archive', 'What every agent is told'),
    h('p.small.muted', dir === 'data'
      ? 'Decisions you asked the building to remember. Every Claude Code and Codex agent in the company\'s folders hears them as it starts, and one at work hears new ones with your next message.'
      : 'Decisions the building remembers. With your own company, every Claude Code agent hears them as it starts. These are made up.'),
    !switchOn('memory') && h('p.small.note', 'The company\'s memory is switched off under Switches: no agent is told these until it is back on.'),
    rows.length ? h('ul.list', rows.map((r) => h('li', h('div.row.memory-row', dot('quiet'), h('span.row-main', h('span.row-title', r.text)),
      (memoryWrites() || mineMemory.includes(r)) && btn('Forget', () => forgetIt(r))))))
      : empty('Nothing yet. Tell the receptionist "remember that ...".'),
    canAdd ? h('form.control-say', { onsubmit: add },
      h('input', { name: 'text', type: 'text', maxlength: 300, autocomplete: 'off', placeholder: 'We never push on a Friday', 'aria-label': 'Something every agent should be told' }),
      h('button.btn', { type: 'submit' }, 'Remember'))
      : h('p.small.muted', 'To add from here, switch on Answer agents from the building, under Switches. Or edit data/memory.json.'),
    noteOnce());
}

// A shelf of how-tos (howto.js): each opens on its own floor's page, or the Library's for the whole company's.
const HOWTO = 'howto';
const howtoHref = (x) => {
  const floor = (x.project && floorOf(x.project)) || org.basement || org.lobby || org.floors[0];
  return floor ? `#/${floor.id}/${HOWTO}/${enc(x.id)}` : null;
};
const howtoText = new Map(); // file -> its text, as last read, so a redraw doesn't blink
function howtoCard(floor) {
  const list = howtosOf(org, floor.project);
  if (!list.length) return null;
  return h('section.panel-card',
    sectHead('library', 'How-tos'),
    h('ul.list', list.map((x) => row(howtoHref(x), x.title, x.project ? null : 'For every floor', 'quiet'))),
    h('p.small.muted', 'The company\'s own ways of doing things. Each agent on this floor is told these as it starts.'));
}
function viewHowto(floor, id) {
  const x = howtosOf(org).find((y) => y.id === id);
  if (!x) return { crumbs: crumbsFor(floor, null, 'Not here any more'), body: [title('Not here any more'), h('p', 'That how-to is not on the shelf now.'), h('a.btn', { href: `#/${floor.id}` }, `Back to ${floor.label}`)] };
  const file = `${dir}/${x.file}`;
  const box = h('div.howto');
  const same = (b, i) => i === 0 && b.kind === 'h' && b.text.trim().toLowerCase() === x.title.trim().toLowerCase(); // its title is the page's already
  const draw = (text) => box.replaceChildren(...(text == null ? [empty('Opening it…')] : blocks(text).filter((b, i) => !same(b, i)).map((b) => {
    const inline = (t) => runs(t).map((r) => (r.kind === 'code' ? h('code', r.text) : r.kind === 'strong' ? h('strong', r.text) : r.text));
    if (b.kind === 'h') return h(`h${Math.min(6, b.level + 2)}`, inline(b.text));
    if (b.kind === 'code') return h('pre.howto-code', h('code', b.text));
    if (b.kind === 'ul' || b.kind === 'ol') return h(b.kind, b.items.map((t) => h('li', inline(t))));
    return h('p', inline(b.text));
  })));
  draw(howtoText.get(file) ?? null);
  fetch(file, { cache: 'no-store' }).then((res) => (res.ok ? res.text() : Promise.reject(new Error(String(res.status)))))
    .then((text) => { if (howtoText.get(file) !== text) { howtoText.set(file, text); draw(text); } },
      () => { if (!howtoText.has(file)) box.replaceChildren(h('p.muted', `It can't be read: ${x.file} isn't there, beside company.json.`)); });
  return {
    crumbs: crumbsFor(floor, null, x.title),
    body: [title(x.title), h('p.small.muted', `A how-to${x.project ? ` for ${floorOf(x.project)?.label || x.project}` : ', for every floor'}. ${madeUp() ? 'Made up, like the rest of the sample.' : `From ${dir}/${x.file}.`}`),
      box, h('a.btn', { href: `#/${floor.id}` }, icon('arrow-left', 15), `Back to ${floor.label}`)],
  };
}

function viewFloor(floor) {
  return {
    crumbs: crumbsFor(floor),
    body: [
      title(floor.label),
      org.floors.includes(floor) && leadCard(floor),
      floor === org.lobby && pauseCard(),
      h('p.states', floorLines(floor).map(chip)),
      org.floors.includes(floor) && floorHealth(floor),
      floor.about && h('p', floor.about),
      org.floors.includes(floor) && restoreCard(pointsOf(work.restore, { project: floor.project }), { titles: true }),
      org.floors.includes(floor) && howtoCard(floor),
      floor.story && h('p.muted', floor.story),
      h('ul.room-list', roomsOf(floor).map((room) => {
        const info = roomModel(floor, room);
        return h('li', h(`a.room-tile.glow.glow-${info.state || 'quiet'}`, { href: `#/${floor.id}/${room.id}` },
          h('span.tile-icon', icon(ROOM_ICON[kindOf(floor, room)] || 'box', 20)),
          h('span.room-main', h('span.room-name', room.label), h('span.row-sub', info.sub ?? [info.big, info.detail].filter((x) => x != null && x !== '').join(' '))),
        ));
      })),
    ],
  };
}

function roomItems(floor, room, info) {
  const kind = kindOf(floor, room);
  if (kind === 'machine') {
    const jobs = work.jobs.filter((j) => j.machine === room.id && j.state !== 'done');
    return [
      h('p.states', chip({ text: info.big, kind: info.state })),
      jobs.length ? h('ul.list', jobs.map((j) => row(null, j.name, j.state === 'running' ? 'Running now' : 'Waiting in the queue', j.state === 'running' ? 'working' : 'quiet'))) : empty('No jobs here right now.'),
    ];
  }
  if (kind === 'code') {
    return [
      h('h3', 'Pull requests'),
      info.prs.length ? h('ul.list', info.prs.map((p) => row(p.href, p.title, p.sub, p.draft ? 'quiet' : 'check'))) : empty('No open pull requests.'),
      h('h3', 'Copies with unsaved changes'),
      info.copies.length ? h('ul.list', info.copies.map((c) => row(c.href, c.title, c.sub))) : empty('Everything is saved.'),
    ];
  }
  if (kind === 'company') return [h('ul.list', info.sections.map((s) => row(s.href, s.title, s.sub)))];
  const list = info.items || [];
  if (!list.length) return [empty('Nothing here yet.')];
  return [h('ul.list', list.map((x) => row(x.href, x.title, x.sub, x.mood || (x.working ? 'working' : x.check ? 'check' : x.reached ? 'ok' : 'quiet'))))];
}

function viewRoom(floor, room) {
  const info = roomModel(floor, room);
  return {
    crumbs: crumbsFor(floor, room),
    body: [
      title(room.label),
      room.about && h('p', room.about),
      ...roomItems(floor, room, info),
      control.on && kindOf(floor, room) === 'conversations' ? startForm(floor) : null,
    ],
  };
}

function facts(pairs) {
  return h('dl.facts', pairs.filter(([, v]) => v != null && v !== '').flatMap(([k, v]) => [h('dt', k), h('dd', v)]));
}

// A conversation's page, answer first: what it waits on you for, then what it said in short (doing, next,
// when, what it needs), whether its work is proven, and the rest.
function convoPage(c) {
  const pr = proofOf(c);
  const rv = reviewOf(c);
  const asking = waitingNow().find((i) => i.key === c.id && (i.kind === 'permission' || i.kind === 'question'));
  const agent = c.agent || (REACHABLE.test(c.id) ? 'Claude Code' : null);
  const state = c.working ? (asking ? 'Waiting on you' : 'Working') : c.check ? 'Finished, to check' : 'Quiet';
  const said = c.says?.now || control.run(c.id)?.said;
  const short = [['Doing', c.working ? said : null], ['Said', c.working ? null : said], ['Next', c.says?.next], ['When', c.says?.when], ['Needs you', asking ? null : c.says?.needs]]
    .filter(([, v]) => v);
  const verdict = pr || rv ? (rv?.state === 'failed' || pr?.state === 'failed' ? 'failed' : pr?.state === 'proven' || rv?.state === 'passed' ? 'ok' : 'quiet') : null;
  return [
    title(c.title),
    h('p.muted', { style: 'margin-top: -4px' }, [state, agent, floorOf(c.project)?.label || c.project].filter(Boolean).join(' · ')),
    noteOnce('.done-note'),
    asking && h('div', { style: 'margin: 14px 0' }, focusCard(asking, { open: false })),
    short.length > 0 && h('dl.short', short.flatMap(([k, v]) => [h('dt', k), h('dd', v)])),
    verdict && h('section.panel-card', sectHead('shield-check', 'Is it proven?'),
      h('div.verdict', h(`span.pill.k-${verdict}`, verdict === 'ok' ? 'Proven' : verdict === 'failed' ? 'Not proven' : pr?.word || 'Not yet'),
        h('div', pr && h('p', pr.line), rv && h('p.small.muted', rv.line))),
      proofPart(c, pr)),
    control.on ? convoControls(c, { noAsk: !!asking }) : null,
    restoreCard(pointsOf(work.restore, { key: c.id })),
  ];
}

function viewItem(floor, room, id) {
  const kind = kindOf(floor, room);
  const gone = () => ({ crumbs: crumbsFor(floor, room), body: [title('Not here any more'), h('p', `That is not in ${room.label} now.`), h('a.btn', { href: `#/${floor.id}/${room.id}` }, `Back to ${room.label}`)] });
  const show = (heading, pairs, extra) => ({ crumbs: crumbsFor(floor, room, heading), body: [title(heading), facts(pairs), extra, h('a.btn', { href: `#/${floor.id}/${room.id}` }, icon('arrow-left', 15), `Back to ${room.label}`)] });
  if (floor === org.lobby) {
    const e = work.presence.find((x) => x.id === id);
    if (!e) return gone();
    const address = e.link && madeUp() ? `${e.link} (made up: the .example ending is kept for examples)` : e.link;
    return show(e.name, [['Kind', room.label], ['Status', e.status], ['Address', address || 'None written down'], ['Project', e.project], ['Last check', e.link ? (e.up ? 'Answered' : 'No answer') : null]]);
  }
  if (kind === 'library') {
    const b = work.library.find((x) => x.id === id);
    return b ? show(b.name, [['Status', b.status]], h('p.small.muted', 'A shelf, not an install: nothing here fetches or runs it.')) : gone();
  }
  if (kind === 'work') {
    const t = work.tasks.find((x) => x.id === id && x.project === floor.project);
    return t ? show(t.title, [['Status', STATUS[t.status]], ['Project', t.project], ['Note', t.note]]) : gone();
  }
  if (kind === 'goals' && id === 'new' && !work.goals.some((g) => g.id === 'new' && g.project === floor.project)) {
    // the flagpole, tapped or stood by: type the goal. Once there is one (set by voice, say), the floor's goals, and room for another.
    const have = work.goals.filter((g) => g.project === floor.project);
    const input = h('input.goal-input', { type: 'text', maxLength: 200, placeholder: 'The goal, in a few words', 'aria-label': `The goal for ${floor.label}` });
    const set = () => {
      const title = input.value.trim().replace(/\s+/g, ' ');
      if (title.length < 3) { input.focus(); return; }
      location.hash = goalHref(addGoal(floor.project, title.slice(0, 200)));
    };
    return { crumbs: crumbsFor(floor, room, 'New goal'), body: [
      title(have.length ? `${floor.label}'s goals` : `No goal yet for ${floor.label}`),
      have.length
        ? [h('ul.goal-list', have.map((g) => h('li', h('a', { href: goalHref(g) }, g.title), g.status === 'reached' ? ' (reached)' : null))), h('p.muted', 'Add another:')]
        : h('p.muted', 'What is this project for? Write it in a few words, such as "the reader app in the App Store by spring". On a walk, you can say it at the flagpole instead.'),
      h('form.goal-form', { onsubmit: (event) => { event.preventDefault(); set(); } }, input, h('button.btn', { type: 'submit' }, 'Set the goal')),
      h('p.small.muted', 'It lives in this tab only: nothing is saved.'),
    ] };
  }
  if (kind === 'goals') {
    const g = work.goals.find((x) => x.id === id && x.project === floor.project);
    return g ? show(g.title, [['Status', g.status === 'reached' ? 'Reached' : 'Open'], ['Project', g.project]]) : gone();
  }
  if (kind === 'conversations') {
    const c = work.conversations.find((x) => x.id === id && x.project === floor.project);
    if (!c) return gone();
    return { crumbs: crumbsFor(floor, room, c.title), body: [...convoPage(c), h('a.btn', { href: `#/${floor.id}/${room.id}` }, icon('arrow-left', 15), `Back to ${room.label}`)] };
  }
  if (kind === 'code') {
    const [what, key] = id.split('/');
    if (what === 'pr') {
      const p = work.pullRequests.find((x) => String(x.number) === key && x.project === floor.project);
      return p ? show(`#${p.number} ${p.title}`, [['Status', p.draft ? 'Draft' : 'Ready for review'], ['Project', p.project]]) : gone();
    }
    const c = work.copies.find((x) => x.id === key && x.project === floor.project);
    return c ? show(c.name, [['Unsaved', count(c.changes, 'change', 'changes')], ['Project', c.project]]) : gone();
  }
  if (kind === 'company') {
    const name = id.split('/')[1];
    if (!COMPANY_SECTIONS.includes(name)) return gone();
    const list = work.company.filter((e) => e.section === name);
    return {
      crumbs: crumbsFor(floor, room, name),
      body: [title(name), list.length ? h('ul.list', list.map((e) => row(null, e.name, e.note))) : empty('Nothing here yet.'), h('a.btn', { href: `#/${floor.id}/${room.id}` }, icon('arrow-left', 15), `Back to ${room.label}`)],
    };
  }
  return gone();
}

function viewFor(r) {
  if (!r.floor) return viewOverview();
  if (r.floor === 'company') return viewCompany();
  if (r.floor === 'activity') return viewActivity();
  if (r.floor === 'front-desk') return poe.view();
  const floor = floors().find((f) => f.id === r.floor);
  if (!floor) return viewOverview();
  if (r.room === HOWTO && r.item && !roomsOf(floor).some((x) => x.id === HOWTO)) return viewHowto(floor, r.item);
  const room = r.room && roomsOf(floor).find((x) => x.id === r.room);
  if (!room) return viewFloor(floor);
  return r.item ? viewItem(floor, room, r.item) : viewRoom(floor, room);
}

/* ---------- drawing ---------- */

function renderCrumbs(crumbs) {
  $('crumbs').replaceChildren(h('ol', crumbs.map(([label, href], i) => h('li',
    href && i < crumbs.length - 1 ? h('a', { href }, label) : h('span', { 'aria-current': 'page' }, label)))));
}

function renderTabs() {
  const tab = !route.floor ? 'overview' : route.floor === 'company' ? 'company' : route.floor === 'front-desk' ? null : 'activity';
  for (const name of ['overview', 'activity', 'company']) {
    const el = $(`tab-${name}`);
    if (name === tab) el.setAttribute('aria-current', 'page');
    else el.removeAttribute('aria-current');
  }
}

function render({ nav = false } = {}) {
  noteUsed = false;
  showCounts(); // an answer drops the count at once, even while the sample is paused
  focusNow = null; // viewOverview sets it again when it is the view showing
  const panel = $('content');
  const active = document.activeElement;
  // Never redraw under someone's typing: wait until they leave the box. A switch isn't typing: it redraws at once,
  // and keeps its focus, so the keyboard can go on down the list.
  const ticked = panel.contains(active) && active.matches('input[type=checkbox]');
  if (!nav && panel.contains(active) && active.matches('input, select, textarea') && !ticked) {
    pending = true;
    return;
  }
  pending = false;
  const focusHref = !nav && panel.contains(active) ? active.getAttribute('href') : null;
  const focusKey = !nav && panel.contains(active) && active.id ? active.id : null; // a button with an id keeps its focus
  const focusSwitch = !nav && ticked ? active.closest('label')?.querySelector('b')?.textContent : null;
  const scroll = panel.scrollTop;
  const view = viewFor(route);
  renderCrumbs(view.crumbs || []);
  $('panel-head').hidden = !!view.top;
  renderTabs();
  panel.replaceChildren(...[view.body].flat(Infinity).filter(Boolean));
  if (nav) {
    panel.scrollTop = 0;
    // a phone scrolls the page itself, so a tab would open where the last one was left: start it at its top
    if (view.top && window.scrollY > 0 && window.matchMedia('(max-width: 820px)').matches) {
      const y = panel.getBoundingClientRect().top + window.scrollY - ($('top')?.offsetHeight || 0) - ($('tabs')?.offsetHeight || 0);
      if (window.scrollY > y + 1) window.scrollTo(0, Math.max(0, y));
    }
    $('view-title')?.focus({ preventScroll: true });
  } else {
    panel.scrollTop = scroll;
    if (focusHref) [...panel.querySelectorAll('a')].find((a) => a.getAttribute('href') === focusHref)?.focus({ preventScroll: true });
    if (focusSwitch) [...panel.querySelectorAll('label.switch')].find((l) => l.querySelector('b')?.textContent === focusSwitch)?.querySelector('input')?.focus({ preventScroll: true });
    if (focusKey && !panel.contains(document.activeElement)) document.getElementById(focusKey)?.focus({ preventScroll: true });
  }
  // What came of an answer shows where it was given: on a phone the note sits above, out of sight, without this.
  if (noteFresh) {
    noteFresh = false;
    const note = panel.querySelector('.control-note');
    const box = note?.getBoundingClientRect();
    if (box && (box.top < 0 || box.bottom > window.innerHeight)) note.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }
}

function tick() {
  for (const el of document.querySelectorAll('[data-at]')) el.textContent = agoText(Number(el.dataset.at));
  const now = Date.now() / 1000;
  for (const el of document.querySelectorAll('[data-wait]')) el.textContent = `Waiting ${waitFor(now - Number(el.dataset.wait))}`;
  for (const el of document.querySelectorAll('[data-waited]')) el.textContent = waitFor(now - Number(el.dataset.waited));
  for (const el of document.querySelectorAll('[data-meter]')) {
    const s = now - Number(el.dataset.meter);
    el.style.width = `${Math.max(4, Math.round(Math.min(1, s / LONG) * 100))}%`;
    el.className = `meter-fill s-${waitMood(s)}`;
  }
  showAnswering();
}

function refresh() {
  building?.setLive(liveModel());
  checkAlerts();
  render();
  showAnswering();
  showCounts();
}

// One count everywhere: the top bar's pill, the Needs you tab and the building's filters.
function showCounts() {
  const n = waitingNow().length;
  const moving = work.conversations.filter((c) => c.working).length + work.jobs.filter((j) => j.state === 'running').length;
  const pill = $('needs-pill');
  pill.hidden = n === 0;
  const word = `${n} need${n === 1 ? 's' : ''} you`;
  if ($('needs-word').textContent !== word) {
    $('needs-n').textContent = String(n);
    $('needs-word').querySelector('.needs-more').textContent = word.slice(String(n).length);
  }
  pill.setAttribute('aria-label', `${word}: show the first`);
  const tab = $('tab-count');
  tab.hidden = n === 0;
  if (tab.textContent !== String(n)) tab.textContent = String(n);
  for (const el of document.querySelectorAll('[data-count-of]')) {
    const c = el.dataset.countOf === 'needs' ? n : el.dataset.countOf === 'working' ? moving : null;
    const text = c ? String(c) : '';
    if (el.textContent !== text) el.textContent = text;
    el.hidden = !text;
  }
  showPauseAll();
}

// Pause all, at the top: on your own company while the building answers your agents.
function showPauseAll() {
  const b = $('pause-all');
  const m = $('pause-all-menu'); // a phone's: in the ... menu, in words (demo.css)
  const can = control.on && dir === 'data'; // as the lobby's pause card: a paired phone may pause them too
  b.hidden = !can;
  m.hidden = !can;
  if (!can) return;
  const paused = !!control.paused();
  const sig = paused ? 'paused' : 'going';
  if (b.dataset.sig === sig) return;
  b.dataset.sig = sig;
  b.replaceChildren(icon(paused ? 'rotate-ccw' : 'pause', 14), h('span.pause-word', paused ? 'Resume all' : 'Pause all'));
  b.title = paused ? 'Every agent is paused. Press to let them go on.' : 'Pause every agent at once: each stops at its next step, until you resume them.';
  b.classList.toggle('paused', paused);
  m.replaceChildren(icon(paused ? 'rotate-ccw' : 'pause', 15), paused ? 'Resume all agents' : 'Pause all agents');
}

// The ... menu: light or dark, the list alone, the sample's pause, the tour.
function setupMenu() {
  const more = $('more');
  const menu = $('more-menu');
  const show = (on) => { menu.hidden = !on; more.setAttribute('aria-expanded', String(on)); };
  more.addEventListener('click', (event) => { event.stopPropagation(); show(menu.hidden); if (!menu.hidden) menu.querySelector('button:not([hidden])')?.focus(); });
  document.addEventListener('click', (event) => { if (!menu.hidden && !$('more-wrap').contains(event.target)) show(false); });
  menu.addEventListener('click', (event) => {
    if (!event.target.closest('button')) return;
    const inside = menu.contains(document.activeElement); // the tour or a new view takes the focus itself
    show(false);
    if (inside) more.focus();
  });
  $('more-wrap').addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !menu.hidden) { event.stopPropagation(); show(false); more.focus(); }
  });
  // Tabbing on past the menu closes it. A click on a button that takes no focus (Safari) has no next element: it stays.
  $('more-wrap').addEventListener('focusout', (event) => { if (!menu.hidden && event.relatedTarget && !$('more-wrap').contains(event.relatedTarget)) show(false); });
  $('desk-open').replaceChildren(icon('messages-square', 15), deskAsk());
  $('desk-open').addEventListener('click', () => { primeBrain('receptionist'); goTo(DESK); });
  $('tour-again').hidden = fromAway();
  $('tour-again').addEventListener('click', () => { if (!walkOn()) tour.open(); });
  $('list-mode').addEventListener('click', () => setListOnly(!document.body.classList.contains('list-only')));
  setListOnly(kept(LIST_ONLY) === '1', false);
  for (const id of ['pause-all', 'pause-all-menu']) $(id).addEventListener('click', () => controlDone(control.paused() ? control.resumeAll() : control.pauseAll(), () => ''));
  // The floor and room labels let taps through to the empty space behind them (#labels has pointer-events: none),
  // so a tap on a floor's name did nothing. Now it opens that floor or room, as a tap on the floor itself does; a
  // drag that ends on one is still a drag.
  let labelDown = null;
  $('stage').addEventListener('pointerdown', (event) => { labelDown = event.target.tagName === 'CANVAS' ? [event.clientX, event.clientY] : null; });
  $('stage').addEventListener('click', (event) => {
    const down = labelDown;
    labelDown = null;
    if (!down || event.target.tagName !== 'CANVAS' || walkOn() || Math.hypot(event.clientX - down[0], event.clientY - down[1]) > 6) return;
    const href = labelHref(event.clientX, event.clientY);
    if (href) goTo(href);
  });
  $('needs-pill').addEventListener('click', () => {
    if (!route.floor) { $('content').scrollTop = 0; $('view-title')?.focus({ preventScroll: true }); }
  });
}
// What a label at this point of the screen names: '#/<floor>' or '#/<floor>/<room>', or '' for none.
function labelHref(x, y) {
  for (const el of $('labels').querySelectorAll('.label:not(.small)')) {
    const key = el.dataset.key || '';
    if (el.hidden || !/^[fr]:/.test(key)) continue;
    const box = el.getBoundingClientRect();
    if (x >= box.left && x <= box.right && y >= box.top && y <= box.bottom) return `#/${key.slice(2)}`;
  }
  return '';
}
function setListOnly(on, save = true) {
  document.body.classList.toggle('list-only', on);
  $('list-mode').replaceChildren(icon('layers', 15), on ? 'Show the building' : 'Hide the building');
  if (save) keep(LIST_ONLY, on ? '1' : '0');
}

// The top bar's light while control is on (welcome.js): whether a permission request waits here now, by
// control.js's two-minute rule, or goes to the agent's own window. Pressing it says why.
function showAnswering() {
  const wrap = $('answering-wrap');
  if (!wrap) return;
  const said = answeringWords(control.on, control.using());
  wrap.hidden = !said;
  if (!said) {
    $('answering-why').hidden = true;
    $('answering').setAttribute('aria-expanded', 'false');
    return;
  }
  const light = $('answering');
  light.classList.toggle('here', said.here);
  if ($('answering-word').textContent !== said.text) $('answering-word').textContent = said.text;
  light.title = said.why;
  if ($('answering-why').textContent !== said.why) $('answering-why').textContent = said.why;
}
function setupAnswering() {
  const light = $('answering');
  if (!light) return;
  const why = $('answering-why');
  const show = (on) => { why.hidden = !on; light.setAttribute('aria-expanded', String(on)); };
  light.addEventListener('click', () => show(why.hidden));
  light.addEventListener('blur', () => show(false));
  light.addEventListener('keydown', (event) => { if (event.key === 'Escape' && !why.hidden) { event.stopPropagation(); show(false); } });
}

/* ---------- the story: work moving on a loop ---------- */

function step() {
  if (!playing || document.hidden || !work.story?.length) return;
  const s = work.story[storyAt % work.story.length];
  storyAt += 1;
  for (const [list, id, patch] of s.change || []) {
    const thing = (work[list] || []).find((x) => x.id === id);
    if (thing) Object.assign(thing, patch);
  }
  happened.unshift({ line: s.line, at: Date.now() });
  happened.length = Math.min(happened.length, 6);
  refresh();
}

function setPlaying(on) {
  playing = on;
  const b = $('live');
  b.replaceChildren(icon(on ? 'pause' : 'zap', 15), on ? 'Pause the sample' : 'Resume the sample'); // the words say the state: no pressed
  b.title = on ? 'The sample\'s work is moving on its own. Press to hold it still.' : 'The sample is held still. Press to let its work move again.';
  // The top bar says so too, where it is seen without opening the menu.
  const badge = $('made-up');
  badge.classList.toggle('paused', !on);
  badge.title = on ? '' : 'The sample is held still. Resume it in the ... menu.';
  badge.replaceChildren(...(on ? ['Sample', h('span.made-up-more', ': made up')] : [icon('pause', 12), h('span', 'Paused', h('span.made-up-more', ': the sample holds still'))]));
  if (!route.floor || route.floor === 'activity') render();
}

/* ---------- scenes, theme, routes ---------- */

function applyScene() {
  const mode = SCENE_NAMES[sceneId] ? { mode: sceneId } : { mode: 'floor', floor: sceneId };
  building?.setScene(mode);
  for (const el of $('scenes').children) el.setAttribute('aria-pressed', String(el.dataset.scene === sceneId));
}

function setupScenes() {
  let saved = params.get('scene');
  if (!saved) { try { saved = localStorage.getItem('arnheim-scene'); } catch { saved = null; } }
  const list = Object.entries(SCENE_NAMES); // the floors themselves are the way to a project: tap one, or its label
  if (list.some(([id]) => id === saved)) sceneId = saved;
  // ?scene=<floor id> (docs/embed.md) lights that one floor; the chips then show none pressed.
  else if (params.get('scene') && org.floors.some((f) => f.id === params.get('scene'))) sceneId = params.get('scene');
  $('scenes').replaceChildren(...list.map(([id, name]) => h('button.scene', {
    type: 'button',
    'data-scene': id,
    onclick: () => {
      sceneId = id;
      try { localStorage.setItem('arnheim-scene', id); } catch { /* it just won't be remembered */ }
      applyScene();
      if (id === 'needs' && route.floor && !walkOn()) goTo('#/'); // one meaning for Needs you: the floors lit, and their list beside
    },
  }, icon(SCENE_ICON[id] || 'box', 18), h('span', name), h('span.scene-count', { 'data-count-of': id }))));
}

function isDark() {
  const set = document.documentElement.dataset.theme;
  return set ? set === 'dark' : window.matchMedia('(prefers-color-scheme: dark)').matches;
}

function applyTheme() {
  const dark = isDark();
  $('theme').replaceChildren(icon(dark ? 'sun' : 'moon', 15), dark ? 'Light mode' : 'Dark mode');
  $('theme').setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
  building?.setTheme(dark);
}

function setupTheme() {
  let saved = params.get('theme');
  if (saved !== 'light' && saved !== 'dark') { try { saved = localStorage.getItem('arnheim-theme'); } catch { saved = null; } }
  if (saved === 'light' || saved === 'dark') document.documentElement.dataset.theme = saved;
  $('theme').addEventListener('click', () => {
    const next = isDark() ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('arnheim-theme', next); } catch { /* it just won't be remembered */ }
    applyTheme();
  });
  window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyTheme);
  applyTheme();
}

function readRoute() {
  const parts = location.hash.replace(/^#\/?/, '').split('/').filter(Boolean).map((part) => {
    try { return decodeURIComponent(part); } catch { return ''; }
  });
  const [floor, room, ...rest] = parts;
  route = { floor, room, item: rest.join('/') };
}

function parentHash() {
  if (TOP_ROUTES.has(route.floor)) return '#/';
  if (route.item) return `#/${route.floor}/${route.room}`;
  if (route.room) return `#/${route.floor}`;
  return '#/activity';
}

function focusBuilding() {
  if (route.floor === 'front-desk' && org.lobby) {
    const desk = org.lobby.rooms.find((r) => kindOf(org.lobby, r) === 'websites') || org.lobby.rooms[0];
    if (!poe.touring()) building?.focus({ floor: org.lobby.id, room: desk?.id, item: DESK, close: true });
    return false;
  }
  const isFloor = floors().some((f) => f.id === route.floor);
  building?.focus(isFloor ? { floor: route.floor, room: route.room, item: location.hash } : {});
  return isFloor;
}

function onRoute() {
  controlNote = ''; // a note on the last thing done belongs to the page it was done on
  readRoute();
  if (route.floor !== 'front-desk') poe.stopTour(false);
  else primeBrain('receptionist');
  render({ nav: true });
  const isFloor = focusBuilding();
  $('view-back').hidden = !isFloor;
  $('stage-help').textContent = route.floor === 'front-desk' ? `${deskName() || 'The receptionist'} is at the front desk. Drag to turn, scroll to zoom.`
    : !isFloor ? 'Tap a floor to bring it out. Drag to turn, scroll to zoom.'
      : !route.room ? 'Tap a room or anything in it. Drag to turn.' : 'Tap anything to open it. Drag to turn.';
}

/* ---------- starting the building, and bringing it back if the browser drops it ---------- */

const MODEL_WAITS = [1000, 5000, 15000]; // a fresh start after each of these, then a Try again button
const MODEL_HANDBACK_MS = 4000; // how long the browser gets to hand a lost picture back by itself
const MODEL_STEADY_MS = 60000; // this long with no trouble and fresh starts are available again
let modelTries = 0;
let modelTimer = 0;
let steadyTimer = 0;
let modelLoaded = false;

function stageMessage(text, canRetry = false) {
  $('stage-fail').hidden = !text;
  $('stage-fail-text').textContent = text;
  $('stage-retry').hidden = !canRetry;
  $('stage-help').hidden = !!text;
}

function restartModel() {
  clearTimeout(modelTimer);
  clearTimeout(steadyTimer);
  building?.dispose();
  opening(false);
  setWalking(false);
  building = null;
  if (modelTries >= MODEL_WAITS.length) {
    stageMessage('The 3D building is not showing right now. Everything is still here in the panel.', true);
    return;
  }
  stageMessage('The 3D building dropped out. Bringing it back.');
  modelTimer = setTimeout(startBuilding, MODEL_WAITS[modelTries]);
  modelTries += 1;
}

function onModelStatus(status) {
  clearTimeout(modelTimer);
  clearTimeout(steadyTimer);
  if (status === 'blank' && look?.look === 'photo' && !building?.ready?.()) {
    // the photo-real pictures never arrived whole (a baked/ folder from another version, or half of one): the
    // drawn building instead, at once, saying why
    look = { look: 'drawn', why: PHOTO_FAILED };
    building?.dispose();
    building = null;
    opening(false);
    setWalking(false);
    startBuilding();
    return;
  }
  if (status === 'lost') {
    stageMessage('The 3D building dropped out. Bringing it back.');
    modelTimer = setTimeout(restartModel, MODEL_HANDBACK_MS);
  } else if (status === 'blank') {
    restartModel();
  } else {
    stageMessage('');
    steadyTimer = setTimeout(() => { modelTries = 0; }, MODEL_STEADY_MS);
  }
}

// Which look the building opens in (README, "The photo-real look"): the one the address asks for (?look=photo or
// ?look=drawn), else the photo-real one when serve.py has its pictures (/look), and the drawn one, with a line saying
// why, when it hasn't. Served some other way, the photo-real one when baked/ is there, as an embedding page does.
// Decided once a page; a photo-real building whose pictures don't load gives way to the drawn one (onModelStatus).
let look = null; // { look: 'photo' | 'drawn', why }
const PHOTO_FAILED = "Showing the drawn look: the photo-real pictures didn't load. To get them again, delete the baked folder and start serve.py again.";

async function chooseLook() {
  const asked = params.get('look');
  if (asked === 'photo' || asked === 'drawn') return { look: asked };
  try {
    const res = await fetch('look', { cache: 'no-store' });
    if (res.ok && (res.headers.get('content-type') || '').includes('json')) {
      const said = await res.json();
      return said.look === 'photo' ? { look: 'photo' } : { look: 'drawn', why: typeof said.why === 'string' ? said.why : '' };
    }
  } catch { /* not serve.py */ }
  const there = await fetch('baked/building.json', { cache: 'no-store' }).then((r) => r.ok, () => false);
  return { look: there ? 'photo' : 'drawn' };
}

function lookNote(text) {
  $('look-note').textContent = text || '';
  $('look-note').hidden = !text;
}

// three.js needs WebGL 2. A browser or machine without it gets the list on its own, said once.
function hasWebGL2() {
  try {
    const gl = document.createElement('canvas').getContext('webgl2');
    gl?.getExtension('WEBGL_lose_context')?.loseContext(); // only asked, so give it straight back
    return !!gl;
  } catch { return false; }
}

async function startBuilding() {
  if (params.has('list') || !hasWebGL2()) {
    document.body.classList.add('no-3d');
    $('walk').hidden = true;
    if (!params.has('list')) console.warn('Arnheim: this browser has no WebGL 2, so the building is shown as a list.');
    return;
  }
  try {
    look ||= await chooseLook();
    lookNote(look.why);
    const { createBuilding } = await import('./building.js');
    modelLoaded = true;
    const tip = $('tip');
    // A canvas that has had graphics can't be given new ones, so every start gets its own.
    const canvas = $('scene').cloneNode(false);
    $('scene').replaceWith(canvas);
    building = createBuilding(canvas, org, {
      look: look.look === 'photo' ? 'photo' : undefined,
      talk,
      labels: $('labels'),
      onStatus: onModelStatus,
      onWalk: setWalking,
      onNotes: showNotes,
      onPick(hit) {
        tip.hidden = true;
        if (hit.company) { goTo('#/activity'); return; }
        if (hit.href === DESK) { primeBrain('receptionist'); goTo(DESK); return; }
        if (isAide(hit)) { primeBrain('assistant'); return; } // she has no page of her own: the talk opens in the walk
        if (hit.walk) { goTo(hit.href || `#/${hit.floorId}/${hit.roomId}`); return; }
        if (route.floor !== hit.floorId) { goTo(`#/${hit.floorId}`); return; }
        goTo(hit.href || `#/${hit.floorId}/${hit.roomId}`);
      },
      onHover(info, x, y) {
        tip.hidden = !info;
        if (!info) return;
        tip.textContent = [info.title, info.sub].filter(Boolean).join('. ');
        tip.style.left = `${Math.min(x + 14, $('stage').clientWidth - 270)}px`;
        tip.style.top = `${Math.max(y - 40, 6)}px`;
      },
    });
    building.setTheme(isDark());
    building.setLive(liveModel());
    showNotes();
    applyScene();
    focusBuilding();
    window.__arnheim = { building, model: liveModel, poe, control, brain, talk, facts: brainFacts, dock, features, look: look.look };
  } catch (error) {
    console.error(error);
    building = null;
    restartModel();
  }
}

/* ---------- walking through the building ---------- */

// The founder's notes, hung in their office on a walk, from notes.json beside the company's other
// files (made up in the sample). They are read again whenever someone walks into the office, so an
// edited note shows the next time. A company with no notes.json simply has none.
let notesFrom = 0;
let noNotes = false;
async function showNotes() {
  if (noNotes) return;
  try {
    const reply = await fetch(`${dir}/notes.json`, { cache: 'no-store' });
    if (reply.status === 404) noNotes = true; // not asked for again until the page is reloaded
    if (!reply.ok) return;
    const { notes = [] } = await reply.json();
    notesFrom ||= Date.now();
    building?.setNotes(notes.map((n) => ({ ...n, when: n.when ?? notesFrom - (Number(n.hoursAgo) || 0) * 3600000 })));
  } catch (error) {
    console.warn(`Arnheim: ${dir}/notes.json could not be read, so the office has no notes.`, error); // the office is simply as it was
  }
}

const walkOn = () => $('walk').getAttribute('aria-pressed') === 'true';

// The walk is one step in the browser's history: Back (or a phone's back gesture) leaves it. While it
// is open, whatever changes the panel (a ring you stand in, something tapped, a link or button in the
// panel) replaces the address instead of adding a step, so the only steps are Back and Forward and one
// Back is always enough. Each walk marks its step with its own number, so an old walk's step never
// counts as this one's. The numbers carry this page load's own mark too, since a step's mark outlives
// a reload, and a mark left by an earlier load is cleared as the page starts.
let walkFrom = '';
let walkStep = 0;
let walkMark = '';
const pageMark = `${Math.round(performance.timeOrigin)}.${Math.random().toString(36).slice(2, 8)}`;
if (window.history.state?.arnheimWalk) window.history.replaceState(null, '', location.href);
function goTo(hash) {
  if (!walkOn()) { location.hash = hash; return; }
  if (location.hash === hash) return;
  window.history.replaceState(window.history.state, '', hash);
  onRoute();
}

function setWalking(on) {
  const was = walkOn();
  // Coming out of the walk, a key still held or pressed straight after (A or D in the walk) waits a
  // second, like any change of the home view's first item, so it can never answer a request.
  if (was && !on) focusSince = Date.now();
  $('walk').setAttribute('aria-pressed', String(!!on));
  dock?.hide(!!on); // the walk has its own voice
  if (on && !was) {
    walkStep += 1;
    walkMark = `${pageMark}:${walkStep}`;
    window.history.pushState({ arnheimWalk: walkMark }, '', location.href);
    walkFrom = location.href;
  } else if (was && !on && window.history.state?.arnheimWalk === walkMark) {
    // left where it started: the step it added goes again, so Back isn't pressed for nothing; left
    // somewhere else: that step stays, as the place the walk took you, but no longer as a walk
    if (location.href === walkFrom) window.history.back();
    else window.history.replaceState(null, '', location.href);
  }
}

window.addEventListener('popstate', (event) => {
  if (walkOn() && event.state?.arnheimWalk !== walkMark) { opening(false); setWalking(false); building?.walk(false); }
});
// a link in the panel, clicked mid-walk, goes through goTo like everything else
document.addEventListener('click', (event) => {
  if (!walkOn() || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const link = event.target.closest?.('a[href^="#"]');
  if (!link || link.target) return;
  event.preventDefault();
  goTo(link.getAttribute('href'));
}, true);

let walkOpening = 0;
async function toggleWalk() {
  if (!building) return;
  if (document.body.classList.contains('list-only')) setListOnly(false); // the walk needs the building
  const on = !building.walking() && !walkOn();
  setWalking(on);
  document.activeElement?.blur?.(); // so Space and Enter don't press the button again mid-walk
  if (!on) { opening(false); setWalking(await building.walk(false)); return; }
  // the walk can take a few seconds to open (the building and its real materials load first): say so
  const ask = ++walkOpening;
  const note = setTimeout(() => { if (ask === walkOpening && walkOn()) opening(true); }, 250);
  let walking = false;
  try {
    walking = await building.walk(true);
  } catch (error) {
    console.error('Arnheim: the walk did not open.', error); // its files didn't load: Walk lets go again
  }
  clearTimeout(note);
  if (ask !== walkOpening) return; // pressed again while it opened: that press decides
  opening(false);
  setWalking(walking && walkOn());
  if (walking && !walkOn()) building.walk(false); // Leave was pressed while it opened
}

function opening(on) {
  $('walk-opening').hidden = !on;
}

function setupStageTools() {
  $('zoom-in').addEventListener('click', () => building?.zoomBy(0.86));
  $('zoom-out').addEventListener('click', () => building?.zoomBy(1.16));
  $('view-reset').addEventListener('click', () => building?.resetView());
  $('view-back').addEventListener('click', () => goTo('#/activity'));
  $('stage-retry').addEventListener('click', () => {
    if (!modelLoaded) { location.reload(); return; } // the files themselves never arrived
    modelTries = 0;
    stageMessage('Starting the 3D building again.');
    startBuilding();
  });
  $('stage').addEventListener('keydown', (event) => {
    if (event.target !== $('stage') || building?.walking?.()) return;
    const turns = { ArrowLeft: [-6, 0], ArrowRight: [6, 0], ArrowUp: [0, 4], ArrowDown: [0, -4] };
    if (turns[event.key]) { event.preventDefault(); building?.turn(...turns[event.key]); }
    else if (event.key === '+' || event.key === '=') building?.zoomBy(0.86);
    else if (event.key === '-') building?.zoomBy(1.16);
    else if (event.key === '0') building?.resetView();
  });
  // Hovering or focusing a link in the panel lights up the room it leads to.
  const light = (event) => {
    const link = event.target.closest?.('a[href^="#/"]');
    const [floor, room] = link ? link.getAttribute('href').replace(/^#\/?/, '').split('/') : [];
    building?.highlight(floors().some((f) => f.id === floor) ? { floor, room } : null);
  };
  for (const name of ['mouseover', 'focusin']) $('content').addEventListener(name, light);
  $('content').addEventListener('mouseleave', () => building?.highlight(null));
}

function setupIcons() {
  $('top').querySelector('h1').prepend(icon('building-2', 18));
  $('tab-overview').prepend(icon('bell', 15));
  $('tab-activity').prepend(icon('history', 15));
  $('tab-company').prepend(icon('sliders-horizontal', 15));
  $('more').replaceChildren(icon('ellipsis', 18));
  $('tour-again').prepend(icon('sparkles', 15));
  $('back').prepend(icon('arrow-left', 15));
  $('view-back').prepend(icon('arrow-left', 15));
  $('view-reset').prepend(icon('rotate-ccw', 14));
}

/* ---------- reading the company's files ---------- */

const LISTS = ['tasks', 'goals', 'conversations', 'pullRequests', 'copies', 'company', 'presence', 'machines', 'jobs', 'library', 'story', 'routines', 'restore', 'asks'];
const problem = (text, status) => Object.assign(new Error(text), { own: true, status });

// One of the company's files, or an error that says which one and why.
async function readJson(path) {
  const reply = await fetch(path, { cache: 'no-store' });
  if (!reply.ok) throw problem(`${path} could not be read: the server answered ${reply.status}.`, reply.status);
  const text = await reply.text();
  try {
    return JSON.parse(text);
  } catch (error) {
    throw problem(`${path} is not valid JSON (${error.message}).`);
  }
}

// Plain words for the mistakes in a company map that would otherwise leave the building blank.
function checkMap(map, path) {
  const fail = (why) => { throw problem(`${path}: ${why}`); };
  const named = (x) => typeof x?.id === 'string' && /^[A-Za-z0-9_-]+$/.test(x.id) && !!x.label;
  if (!map || typeof map !== 'object' || Array.isArray(map)) fail('it should be one object, between { and }.');
  if (!map.company) fail('it needs "company", the company\'s name.');
  if (!Array.isArray(map.floors) || !map.floors.length) fail('it needs "floors", a list of at least one floor.');
  const ids = new Set();
  for (const floor of [...map.floors, map.lobby, map.basement].filter(Boolean)) {
    if (!named(floor)) fail('every floor needs a "label" and an "id" made of letters, numbers, dashes or underscores.');
    if (ids.has(floor.id)) fail(`two floors have the id "${floor.id}".`);
    ids.add(floor.id);
    const rooms = floor.rooms || map.rooms;
    if (!Array.isArray(rooms)) fail(`the floor "${floor.id}" has no rooms. Give it "rooms", or give the company a "rooms" list that every floor shares.`);
    const all = [...rooms, ...(Array.isArray(floor.extraRooms) ? floor.extraRooms : [])];
    if (all.length > 5) fail(`the floor "${floor.id}" has ${all.length} rooms, and a floor holds at most five.`);
    if (!all.every(named)) fail(`on the floor "${floor.id}", every room needs a "label" and an "id" made of letters, numbers, dashes or underscores.`);
  }
  for (const floor of map.floors) floor.project ||= floor.label; // what work.json calls its project
  return map;
}

// Your own company from data/ when data/company.json is there, or else the made-up sample. ?sample
// in the address shows the sample anyway. Every list in work.json is optional, and so is
// data/work.json itself: without it the building stands quiet.
async function readCompany() {
  let map = null;
  if (!params.has('sample')) {
    try {
      map = await readJson('data/company.json');
      dir = 'data';
      feeds = feedList(map);
    } catch (error) {
      if (error.status !== 404) throw error;
      firstRun = true;
    }
  }
  const [mapRead, now] = await Promise.all([map || readJson(`${dir}/company.json`), readWork()]);
  return [checkMap(mapRead, `${dir}/company.json`), now];
}

// The files that tools keep up to date for your own company, such as connect/claude_code.py's
// (docs/connect.md): "feeds" in company.json, each a path inside data/.
function feedList(map) {
  const list = Array.isArray(map?.feeds) ? map.feeds : [];
  return list.filter((path) => typeof path === 'string' && /^[\w-]+(\/[\w.-]+)*\.json$/.test(path) && !path.includes('..'));
}

// What is going on: work.json, with every list in each feed added to it. A feed that isn't written
// yet counts as empty; one caught mid-change keeps what it said last time.
async function readWork() {
  const now = await readJson(`${dir}/work.json`).catch((error) => {
    if (dir === 'data' && error.status === 404) return {};
    throw error;
  });
  if (!now || typeof now !== 'object' || Array.isArray(now)) throw problem(`${dir}/work.json: it should be one object, between { and }.`);
  for (const key of LISTS) if (!Array.isArray(now[key])) now[key] = [];
  now.ended = []; // what conversations that left the feeds today spent (connect/budget.py)
  for (const path of feeds) {
    let feed = lastFeed.get(path) || null;
    try {
      feed = await readJson(`data/${path}`);
    } catch (error) {
      if (error.status === 404) feed = null;
    }
    if (!feed || typeof feed !== 'object') continue;
    lastFeed.set(path, feed);
    for (const key of LISTS) if (Array.isArray(feed[key])) now[key].push(...feed[key].filter((x) => x && typeof x === 'object'));
    if (feed.ended && typeof feed.ended === 'object') now.ended.push(feed.ended);
  }
  now.memory = await readMemory();
  now.usage = await readUsage(now);
  if (dir !== 'data') now.pullRequests = now.pullRequests.map((p) => (p.waited ? { ...p, updated: OPENED - p.waited * 86400 } : p)); // the sample's: days waited
  if (dir !== 'data') now.restore = now.restore.map((p) => (Number.isFinite(p.ago) ? { ...p, at: OPENED - p.ago } : p)); // the sample's: seconds ago
  if (dir !== 'data') now.conversations = now.conversations.map((c) => (Number.isFinite(c.ago) ? { ...c, at: OPENED - c.ago } : c));
  // the sample's own permission requests, so it shows one being answered: nothing runs when you do
  now.asks = dir !== 'data' ? now.asks.filter((a) => a && a.id).map((a) => ({ ...a, sample: true, at: OPENED - (Number(a.ago) || 0), until: OPENED + (Number(a.lasts) || 3600) })) : [];
  if (dir !== 'data') { // the sample's routines: their times from their schedules, as if each last ran on time
    now.routines = now.routines.map((r) => {
      const t = timesOf(r, OPENED);
      return { ...r, next: t.next, last: r.last && t.last ? { ...r.last, at: t.last, done: t.last + (r.last.took || 0) } : r.last };
    });
  }
  history = await readHistory();
  return now;
}
const OPENED = Date.now() / 1000;

// Today's moments, for the replay: data/feeds/history/<today>.json for your own company, or the sample's,
// whose times count back from when the page opened.
// The six days before, for the brief (yesterday), the weekly report and the receptionist's history: each
// past day's file is read once, since it doesn't change. The sample's are in sample/week.json.
let history = [];
let todaySpent = {}; // what each floor's agents have spent today, as the hook keeps it beside the moments
let sampleHistory = null;
const pastDays = new Map(); // day -> { day, moments, spent }
let yesterday = { day: '', moments: [] }; // for the brief, which can reach back a day
const dayBefore = (n) => localDay(new Date(Date.now() - n * 864e5));
const dayOf = (raw, day) => ({ day, moments: Array.isArray(raw?.moments) ? raw.moments.filter((m) => m && typeof m === 'object') : [],
  spent: raw?.spent && typeof raw.spent === 'object' && !Array.isArray(raw.spent) ? raw.spent : {} });
async function readPastDays() {
  const days = [1, 2, 3, 4, 5, 6].map(dayBefore);
  for (const d of [...pastDays.keys()]) if (!days.includes(d)) pastDays.delete(d);
  if (dir !== 'data') {
    if (!pastDays.size) {
      const w = await readJson(`${dir}/week.json`).catch(() => null);
      for (const d of Array.isArray(w?.days) ? w.days : []) {
        const at = (clock) => { const t = new Date(Date.now() - (Number(d.back) || 0) * 864e5); const [hh, mm] = String(clock).split(':'); t.setHours(Number(hh) || 0, Number(mm) || 0, 0, 0); return t.getTime() / 1000; };
        const day = dayBefore(Number(d.back) || 0);
        pastDays.set(day, dayOf({ moments: (d.moments || []).map((m) => ({ ...m, at: at(m.at) })), spent: d.spent }, day));
      }
    }
  } else {
    await Promise.all(days.filter((d) => !pastDays.has(d)).map(async (d) => {
      try {
        pastDays.set(d, dayOf(await readJson(`data/feeds/history/${d}.json`), d));
      } catch (error) {
        if (error.status === 404) pastDays.set(d, dayOf(null, d)); // none that day; anything else, look again next time
      }
    }));
  }
  yesterday = pastDays.get(days[0]) || { day: days[0], moments: [] };
}
async function readHistory() {
  try {
    await readPastDays();
    if (dir !== 'data') {
      if (!sampleHistory) {
        const opened = Date.now() / 1000;
        const m = await readJson(`${dir}/history.json`);
        sampleHistory = (Array.isArray(m?.moments) ? m.moments : []).map((x) => ({ ...x, at: opened - (Number(x.ago) || 0) }));
      }
      return sampleHistory;
    }
    const m = await readJson(`data/feeds/history/${localDay()}.json`);
    todaySpent = dayOf(m, localDay()).spent;
    return dayOf(m, localDay()).moments;
  } catch (error) {
    return error.status === 404 ? [] : history;
  }
}
// The week as the weekly report takes it, today first.
const weekDays = () => [{ day: localDay(), moments: history, spent: dir === 'data' ? todaySpent : sampleSpent() }, ...pastDays.values()];
const weekMoments = () => weekDays().flatMap((d) => d.moments);
// The sample's spending today: what its conversations say they spent.
const sampleSpent = () => Object.fromEntries(org.floors.map((f) => [f.project, spentOfFloor(f)]).filter(([, n]) => n > 0));
const spentOfFloor = (f) => spendOf(f)?.spent || 0;

// Your plan's limits as Claude Code and Codex report them (connect/usage.py), for the forecast (usage.js). The
// sample's are made up in its work.json ("usage"), their times counting back from when the page opened.
let lastUsage = null;
async function readUsage(now) {
  if (dir !== 'data') {
    const u = now.usage && typeof now.usage === 'object' ? now.usage : null;
    if (!u?.sources) return null;
    const shift = (rows) => (Array.isArray(rows) ? rows : []).map((r) => ({ at: OPENED - (Number(r.ago) || 0), used: r.used, resets_at: OPENED + (Number(r.resets_in) || 0) }));
    return { sources: Object.fromEntries(Object.entries(u.sources).map(([k, w]) => [k, Object.fromEntries(Object.entries(w || {}).map(([n, rows]) => [n, shift(rows)]))])) };
  }
  try {
    lastUsage = await readJson('data/feeds/usage.json');
  } catch (error) {
    if (error.status === 404) lastUsage = null;
  }
  return lastUsage;
}

// The company's memory: memory.json beside company.json, written through control (docs/connect.md,
// "Company memory"). None yet is an empty memory; one caught mid-change keeps what it said last time.
let lastMemory = [];
let noMemoryUntil = 0; // with no memory.json yet, look again every half a minute, not every few seconds
async function readMemory() {
  if (Date.now() < noMemoryUntil) return lastMemory;
  try {
    const m = await readJson(`${dir}/memory.json`);
    lastMemory = (Array.isArray(m?.memory) ? m.memory : []).filter((r) => r && typeof r === 'object' && typeof r.text === 'string' && r.text.trim());
  } catch (error) {
    if (error.status === 404) {
      lastMemory = [];
      noMemoryUntil = Date.now() + 30000;
    }
  }
  return lastMemory;
}

// Your own company's work is read again every few seconds, so the building follows it as it
// changes: an edit to work.json, or a tool writing its feed.
async function followWork() {
  if (document.hidden && !alerts.on()) return; // with desktop alerts on, it keeps reading in the background, to alert
  try {
    const now = await readWork();
    const sig = JSON.stringify(now);
    if (sig === workSig) return;
    workSig = sig;
    now.tasks.push(...mine);
    now.goals.push(...myGoals);
    for (const task of now.tasks) if (dropped.has(task.id)) task.status = 'dropped';
    work = now;
    if (replayAt != null) replayed();
    refresh();
  } catch {
    // a file mid-edit: the building stays as it was until the next look
  }
}

async function boot() {
  try {
    [[org, work]] = await Promise.all([readCompany(), brain.check()]); // the desk's words depend on the brain
    workSig = JSON.stringify(work);
  } catch (error) {
    console.error(error);
    $('content').replaceChildren(h('p.banner.fail', error.own
      ? `The company could not be shown. ${error.message}`
      : 'The company could not be read. Serve this folder (python3 serve.py) and open the address it prints.'));
    return;
  }
  document.title = madeUp() ? `Arnheim: ${org.company}, a made-up company` : `Arnheim: ${org.company}`;
  $('made-up').hidden = !madeUp();
  // A phone's header stays at the top as the page scrolls, and the tabs just under it (demo.css): how tall it is now.
  const topHeight = () => document.documentElement.style.setProperty('--top-h', `${$('top').offsetHeight}px`);
  topHeight();
  try { new ResizeObserver(topHeight).observe($('top')); } catch { addEventListener('resize', topHeight); }
  $('live').hidden = !hasStory();
  setupDesk();
  readRoute();
  setupTheme();
  setupIcons();
  setupScenes();
  setupMenu();
  setupStageTools();
  setPlaying(params.get('live') !== 'off');
  $('live').addEventListener('click', () => setPlaying(!playing));
  $('walk').addEventListener('click', toggleWalk);
  features.defaults(org.features);
  if (fromAway()) await readRemote(); // a paired phone is not view only
  dock = createTalkDock({
    talk, features, place: $('top'), before: $('walk'), extra: phoneCard,
    people: () => [
      { who: deskWho(), label: `${deskName() || 'The receptionist'}, at the front desk` },
      ...(aideWho() ? [{ who: aideWho(), label: `${org.assistant.name}, ${org.founder?.name ? `${org.founder.name}'s` : 'the'} assistant` }] : []),
      ...(features.get('leads') ? leads.floors().map((f) => ({ who: leads.who(f), label: leads.who(f).title })) : []),
    ],
    here: () => {
      const floor = org.floors.find((f) => f.id === route.floor);
      return floor ? leads.lead(floor.id) : null;
    },
  });
  features.watch(() => render());
  await startBuilding();
  onRoute();
  window.addEventListener('hashchange', onRoute);
  $('back').addEventListener('click', () => goTo(parentHash()));
  $('content').addEventListener('focusout', () => { if (pending) setTimeout(render, 0); });
  document.addEventListener('keydown', (event) => {
    // the walk has its own keys, from the moment Walk is pressed (it takes a moment to open) until it has closed
    if (building?.walking?.() || walkOn()) return;
    if (tour.isOpen) return; // the first tour has its own keys while it is open: a key meant for it never answers a request
    const typing = event.target.matches?.('input, select, textarea, [contenteditable]');
    const free = !typing && !event.metaKey && !event.ctrlKey && !event.altKey;
    if (event.key === 'Escape') {
      if (poe.touring()) poe.stopTour(true);
      else if (!typing && !TOP_ROUTES.has(route.floor)) location.hash = parentHash();
    } else if (TAB_KEYS[event.key] && free) {
      event.preventDefault();
      location.hash = TAB_KEYS[event.key];
    } else if (free && focusNow && /^[adl]$/i.test(event.key)) {
      // the home view's first item: A allows it, D denies it, L puts it off till later. A held key or a press
      // just as the first item changes does nothing, so it can't answer one you haven't seen.
      if (event.repeat || Date.now() - focusSince < 1000) { event.preventDefault(); return; }
      const i = focusNow;
      const key = event.key.toLowerCase();
      if (key === 'l') { event.preventDefault(); later.add(i.id); render(); return; }
      if (!canAnswer(i)) return;
      event.preventDefault();
      answerOnce(i, key === 'a' ? 'allow' : 'deny');
    }
  });
  setInterval(step, Math.max(2, Number(work.every) || 6) * 1000);
  setInterval(tick, 1000);
  if (dir === 'data') setInterval(followWork, FOLLOW_MS);
  checkAlerts(); // what waits on you as the page opens: never alerted
  if (dir === 'data' && !madeUp()) {
    // Control is off unless serve.py says it is on; then the panel follows what waits for you.
    let seen = '';
    let primed = false;
    control.watch((s) => {
      const sig = JSON.stringify([s.on, s.asks.map((a) => a.id), s.runs.map((r) => [r.key, r.state, r.answered]), s.projects.length, s.paused, s.allowed]);
      if (sig === seen) return;
      seen = sig;
      if (s.on && !primed) { // control's first answer: what was already waiting there never alerts either
        primed = true;
        freshAlerts(waitingNow(), alertKnown || (alertKnown = new Set()));
      }
      refresh();
    });
    control.start();
    readSwitches().then((got) => { if (got) render(); });
  }
  setupAnswering();
  showAnswering();
  showCounts();
  if (!fromAway()) { // a newer Arnheim: asked of this computer's serve.py now and every half hour (it asks GitHub once a day)
    readUpdate().then(() => render());
    setInterval(() => readUpdate().then(() => render()), 30 * 60000);
  }
  setTimeout(maybeTour, 1200);
}

boot();
