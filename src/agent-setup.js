// Set your agents up well (connect/agent_setup.py, through serve.py's /setup/): which steps are ticked, what Connect
// or Set up sends, the exact changes for what is ticked, and each floor's steps for Settings' card. The words and
// small rules, as a plain module, so tests/test_agent_setup.py can run them under Node; demo.js draws them.

// The five steps, as Settings names them. Instructions, check and the allow list are each project's own; secrets
// and MCP servers are set once, for every project.
export const WELL_STEPS = [
  { id: 'instructions', label: 'Shared instructions', title: 'One instructions file both agents read' },
  { id: 'check', label: 'Check', title: 'Its check, so done means proven' },
  { id: 'secrets', label: 'Secrets guarded', title: 'Secret files kept from Claude Code', once: true },
  { id: 'allow', label: 'Allow list', title: 'Its check runs without asking' },
  { id: 'mcp', label: 'MCP the same', title: 'The same MCP servers in both', once: true },
];
const PER_PROJECT = new Set(['instructions', 'check', 'allow']);

// What each kind of change does to its file, for Show the exact changes.
export const HOW = {
  new: 'A new file:',
  append: 'One line added at the end:',
  fallback: 'Added to Codex\'s own settings:',
  check: 'Added to this floor in your building:',
  deny: 'Added to "permissions" "deny":',
  allow: 'Added to "permissions" "allow":',
  exclude: 'Added to the repository\'s own ignore file, which is never committed:',
  command: 'Runs:',
};

const key = (folder, id) => `${folder}|${id}`;

// As it opens: every step that would change something ticked, and each project's check as found.
export function wellStart(well) {
  const ticked = new Set();
  const checks = {};
  for (const p of Array.isArray(well?.projects) ? well.projects : []) {
    for (const i of p.items || []) {
      if (i.state === 'todo') ticked.add(key(p.folder, i.id));
      if (i.id === 'check') checks[p.folder] = i.run || '';
    }
  }
  return { ticked, checks, secrets: well?.secrets?.state === 'todo', mcp: well?.mcp?.state === 'todo', open: false };
}

// A fresh plan for some projects (a folder typed, or a check changed) in place of theirs. A step that newly needs
// doing starts ticked; one you unticked stays unticked. Secrets and MCP servers stay as the whole plan said: a plan
// for one folder knows only that folder's servers.
export function wellMerge(well, fresh, state) {
  const out = { ...(well || {}), projects: [...(well?.projects || [])] };
  for (const p of fresh?.projects || []) {
    const at = out.projects.findIndex((x) => x.folder === p.folder);
    const before = at >= 0 ? out.projects[at] : null;
    for (const i of p.items || []) {
      const was = before?.items?.find((x) => x.id === i.id);
      if (i.state === 'todo' && was?.state !== 'todo') state?.ticked.add(key(p.folder, i.id));
      if (i.id === 'check' && state && !(p.folder in state.checks)) state.checks[p.folder] = i.run || '';
    }
    if (at >= 0) out.projects[at] = p;
    else out.projects.push(p);
  }
  return out;
}

// The projects among `folders` (those being connected, or a floor's), in the order given.
const among = (well, folders) => (folders || []).map((f) => (well?.projects || []).find((p) => p.folder === f)).filter(Boolean);

// What Connect or Set up sends: each project's ticked steps, its check as typed (unless its floor has one), and
// whether to guard secrets and share MCP servers.
export function wellRequest(well, state, folders) {
  const projects = among(well, folders).map((p) => {
    const check = (p.items || []).find((i) => i.id === 'check');
    return {
      folder: p.folder,
      items: (p.items || []).filter((i) => PER_PROJECT.has(i.id) && i.state === 'todo' && state.ticked.has(key(p.folder, i.id))).map((i) => i.id),
      check: check && check.state !== 'done' ? String(state.checks[p.folder] ?? check.run ?? '').trim() : null,
    };
  });
  return { projects, secrets: !!state.secrets && well?.secrets?.state === 'todo', mcp: !!state.mcp && well?.mcp?.state === 'todo' };
}

// Whether anything ticked would change something.
export function wellTicked(well, state, folders) {
  const r = wellRequest(well, state, folders);
  return r.secrets || r.mcp || r.projects.some((p) => p.items.length > 0);
}

// The exact changes for what is ticked, file by file: [{ label, file, how, text }].
export function wellChanges(well, state, folders) {
  const out = [];
  for (const p of among(well, folders)) {
    for (const i of p.items || []) {
      if (i.state !== 'todo' || !state.ticked.has(key(p.folder, i.id))) continue;
      for (const c of i.changes || []) out.push({ label: p.label, file: c.file, how: HOW[c.how] || '', text: c.text });
    }
  }
  for (const [id, on] of [['secrets', state.secrets], ['mcp', state.mcp]]) {
    const i = well?.[id];
    if (!on || i?.state !== 'todo') continue;
    for (const c of i.changes || []) out.push({ label: 'Every project', file: c.file, how: HOW[c.how] || '', text: c.text });
  }
  return out;
}

// Settings' card: for each floor, its five steps as done (in place), todo (can be set up) or none (can't, with why).
export function wellStatus(well) {
  return (well?.projects || []).map((p) => ({
    label: p.label,
    folder: p.folder,
    steps: WELL_STEPS.map((s) => {
      const item = s.once ? well?.[s.id] : (p.items || []).find((i) => i.id === s.id);
      return { id: s.id, label: s.label, state: item?.state || 'none', says: item?.says || '' };
    }),
  }));
}

// Whether any floor has a step that can still be set up.
export const wellMissing = (well) => wellStatus(well).some((f) => f.steps.some((s) => s.state === 'todo'));

// One floor's line in Settings: what is in place, what can be set up, and what can't be from here.
export function wellLine(floor) {
  const of = (state) => floor.steps.filter((s) => s.state === state).map((s) => s.label);
  const [done, todo, none] = [of('done'), of('todo'), of('none')];
  if (done.length === floor.steps.length) return 'All five in place.';
  return [done.length && `In place: ${done.join(', ')}.`, todo.length && `Can be set up: ${todo.join(', ')}.`,
    none.length && `Not set up: ${none.join(', ')}.`].filter(Boolean).join(' ');
}

// Why each step that can't be set up from here isn't, once each: [{ who, says }], a floor's own first.
export function wellNotes(well) {
  const out = [];
  for (const p of well?.projects || []) {
    for (const i of p.items || []) if (i.state === 'none' && i.says) out.push({ who: p.label, says: i.says });
  }
  for (const id of ['secrets', 'mcp']) {
    if (well?.[id]?.state === 'none' && well[id].says) out.push({ who: 'Every project', says: well[id].says });
  }
  return out;
}
