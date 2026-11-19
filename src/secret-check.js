// The secrets check (connect/secret_scan.py): passwords and tokens saved in an agent's settings in a floor's folder,
// and how far git has taken each. Only what kind each is, where it is and a masked hint ever reach the page, never
// the secret. Your own company's come from serve.py's /secrets/, on this computer only; the made-up company's
// from its work.json. No imports, so tests can run it under Node.

export const SECRET_ORDER = { pushed: 0, committed: 1, open: 2, ignored: 3, outside: 4 };
// Pushed, committed, or about to be: these need fixing. The rest stay on this computer, still worth knowing.
export const SERIOUS = new Set(['pushed', 'committed', 'open']);

const whole = (f) => f && typeof f === 'object' && typeof f.id === 'string' && typeof f.says === 'string' && f.says.trim();

// The findings, worst first.
export function secretsIn(list) {
  return (Array.isArray(list) ? list.filter(whole) : [])
    .sort((a, b) => (SECRET_ORDER[a.state] ?? 9) - (SECRET_ORDER[b.state] ?? 9));
}

// One floor's findings as health problems (health.js): something to fix while git has or would share it, a
// warning otherwise. No agent is ever sent to see to one: it would read the secret.
export function secretProblems(project, secrets = []) {
  return secretsIn(secrets).filter((f) => f.project === project).map((f) => ({
    kind: SERIOUS.has(f.state) ? 'secret' : 'secret-kept', id: `secret:${f.id}`, line: f.says, job: null, finding: f,
  }));
}

export const secretMood = (f) => (SERIOUS.has(f.state) ? 'failed' : 'needs');

// The small line under a finding: its floor, its line in the file, and the hint (ghp_...1a2b, or how long it is).
export const secretSub = (f, floor) => [floor, Number(f.line) > 0 ? `line ${f.line}` : '', f.hint].filter(Boolean).join(' · ');
