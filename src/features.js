// The talking features, each switched on or off by whoever uses the page, in this browser: talking from any
// screen, a lead on each project floor, and answering requests by voice. A company can set its own defaults in
// company.json ("features": { "leads": false }); what someone switches here wins in their browser.
// Plain module: talk-dock.js shows the switches, the page reads them.

const KEY = 'arnheim-features';

export const FEATURES = [
  { id: 'talk', label: 'Talk from any screen', about: 'A Talk button at the top of every screen: ask what you want to know, go somewhere or answer by voice, without walking.' },
  { id: 'leads', label: 'A lead on each floor', about: 'Someone on every project floor who knows it in depth, says where it stands, and passes what you want done to its agents.' },
  { id: 'answers', label: 'Answer requests by voice', about: 'Say "allow" or "deny" to a permission request once it has been read back to you. Anything that may be private is always answered on the screen.' },
];

export function createFeatures(defaults = {}) {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch { saved = {}; }
  if (typeof saved !== 'object' || Array.isArray(saved)) saved = {};
  let given = defaults && typeof defaults === 'object' ? defaults : {};
  const subs = new Set();
  const get = (id) => (typeof saved[id] === 'boolean' ? saved[id] : given[id] !== false);
  return {
    get,
    all: () => Object.fromEntries(FEATURES.map((f) => [f.id, get(f.id)])),
    set(id, on) {
      if (!FEATURES.some((f) => f.id === id)) return;
      saved = { ...saved, [id]: !!on };
      try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch { /* a private window: it lasts this visit */ }
      for (const fn of subs) { try { fn(id, !!on); } catch (error) { console.warn('Arnheim: a switch watcher failed.', error); } }
    },
    // A company's own defaults, read after the page starts (company.json "features").
    defaults(d) { given = d && typeof d === 'object' ? d : {}; },
    watch(fn) { subs.add(fn); return () => subs.delete(fn); },
  };
}
