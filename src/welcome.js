// The first minutes with your own agents, and keeping Arnheim up to date: Connect my agents on the made-up company's
// page (serve.py's /setup/, which runs connect/setup.py), the card that waits for your first agent, the light that
// says whether permission requests wait here (control.js's two-minute rule), and the notice that a newer Arnheim is
// out (serve.py's /update). The words and small rules, as a plain module, so tests/test_ease.py can run them under
// Node; demo.js draws them.

export const CONNECTED = 'arnheim-connected'; // this browser: what Connect my agents did, shown once the page reloads
export const UNDONE = 'arnheim-undone'; // this tab: what Undo did, shown on the made-up company it goes back to
export const FIRST = 'arnheim-first-agent'; // this browser: a conversation was seen here, so the waiting card is done

// Connect my agents, as it opens from /setup/plan: every project found ticked, nothing typed, and yes to answering
// agents from the building.
export function connectStart(plan) {
  const projects = Array.isArray(plan?.projects) ? plan.projects : [];
  return { step: 'form', plan: { ...plan, projects }, ticked: new Set(projects.map((p) => p.folder)), typed: '', control: true, error: '' };
}

// What Connect sends to /setup/connect: the folders as the page showed them (in the order found), the typed one,
// and the answer about control.
export function connectRequest(flow) {
  const found = (flow?.plan?.projects || []).map((p) => p.folder);
  return { folders: found.filter((f) => flow.ticked.has(f)), typed: String(flow.typed || '').trim(), control: flow.control !== false };
}

// Codex as the flow says it: found or not, its version, and whether its hooks are added too.
export function codexLine(codex) {
  if (!codex?.here) return 'Codex: not found on this computer.';
  const version = codex.version ? ` (${codex.version})` : '';
  return codex.hooks
    ? `Codex: found${version}. Its hooks are added too, and Codex runs them once you trust them: type /hooks in Codex.`
    : `Codex: found${version}.`;
}

// The first moment with your own company. `seen`: a conversation was seen before in this browser. `waiting`: the
// card was showing a moment ago. Gives { waiting, arrived, seen }: the card shows while nothing has come yet; the
// first conversation to come while it shows is `arrived`, for a note said once; one already there when the page
// opens just marks it seen.
export function firstMoment({ seen = false, waiting = false, conversations = [] } = {}) {
  if (seen) return { waiting: false, arrived: null, seen: true };
  const list = (Array.isArray(conversations) ? conversations : []).filter((c) => c && c.id);
  if (!list.length) return { waiting: true, arrived: null, seen: false };
  const newest = list.reduce((a, b) => ((Number(b.at) || 0) > (Number(a.at) || 0) ? b : a));
  return { waiting: false, arrived: waiting ? newest : null, seen: true };
}

// The floors' folders, as company.json gives them ("folder" or "folders"), each once: [{ floor, folder }].
export function floorFolders(org) {
  const out = [];
  for (const floor of Array.isArray(org?.floors) ? org.floors : []) {
    const list = Array.isArray(floor?.folders) ? floor.folders : floor?.folder ? [floor.folder] : [];
    for (const folder of list) {
      if (typeof folder === 'string' && folder.trim() && !out.some((x) => x.folder === folder)) out.push({ floor: floor.label || floor.id || '', folder });
    }
  }
  return out;
}

// The top bar's light while control is on: whether a permission request waits here now (someone used the page in the
// last two minutes, or is walking) or goes to the agent's own window. Null with control off: no light at all.
export function answeringWords(on, using) {
  if (!on) return null;
  return using
    ? { here: true, text: 'Answering here',
      why: 'Permission requests wait here for your answer while you use this page, and for two minutes after you last touch it. A walk counts too.' }
    : { here: false, text: 'Agents ask in their windows',
      why: 'Nobody has touched this page for two minutes, so each agent asks in its own window, as usual. Touch the page, or walk, and requests wait here again.' };
}

// The Needs you notice of a newer Arnheim, from how many changes GitHub's main has that this copy hasn't.
export const updateLine = (n) => `A newer Arnheim is out (${n} ${n === 1 ? 'change' : 'changes'}).`;
