// Desktop alerts when an agent needs you: each browser's own choice, kept in it (localStorage). While it is on, a
// permission request or a question that comes while the page is in the background brings one desktop alert: the
// floor's name, what it asks in a short line, tagged with the item's id so it never comes twice. Never for what was
// already waiting when the page opened, and never for the made-up company (demo.js decides that). Plain module, so
// tests/test_ease.py can run it under Node with a stand-in for the browser's Notification.

export const ALERTS = 'arnheim-alerts';
const KINDS = new Set(['permission', 'question']); // what needs you, as the Overview's list has it (queue.js)

// The items that need you and haven't been seen on this page before. Every item given is marked seen in `known`, so
// one that comes while the page is in front never alerts later.
export function freshAlerts(items, known) {
  const fresh = [];
  for (const item of Array.isArray(items) ? items : []) {
    if (!item || !KINDS.has(item.kind) || !item.id || known.has(item.id)) continue;
    known.add(item.id);
    fresh.push(item);
  }
  return fresh;
}

// One line, cut short at a word if it is long.
export function shortLine(text, most = 120) {
  const line = String(text || '').replace(/\s+/g, ' ').trim();
  if (line.length <= most) return line;
  const cut = line.slice(0, most - 1);
  const at = cut.lastIndexOf(' ');
  return `${(at > most / 2 ? cut.slice(0, at) : cut).replace(/[\s.,;:]+$/, '')}…`;
}

// The alert for an item: { title, body, tag }.
export function alertOf(item, floor) {
  const who = item.title || 'An agent';
  const what = item.kind === 'permission' ? `${who} wants your permission ${item.what || ''}` : `${who} asks: ${item.what || ''}`;
  return { title: floor || 'Arnheim', body: shortLine(what), tag: item.id };
}

// What this browser allows: 'none' (no desktop alerts at all), 'default' (not asked yet), 'denied' or 'granted'.
export function alertsState(win) {
  const N = win?.Notification;
  if (typeof N !== 'function') return 'none';
  return ['default', 'denied', 'granted'].includes(N.permission) ? N.permission : 'default';
}

const SAID = {
  none: "This browser can't show desktop alerts.",
  denied: 'This browser blocks alerts from this page. To have them, allow notifications for this page in the browser\'s site settings, then switch this on again.',
  refused: "Alerts stay off: the browser wasn't allowed to show them.",
  on: 'Desktop alerts are on in this browser. One comes when an agent needs you while this page is in the background.',
  off: 'Desktop alerts are off in this browser.',
  broken: "This browser can't show desktop alerts from a page, so they are off.",
};

export function createAlerts({ win = globalThis, storage = null } = {}) {
  const read = () => { try { return storage?.getItem(ALERTS) === 'on'; } catch { return false; } };
  const write = (on) => { try { storage?.setItem(ALERTS, on ? 'on' : 'off'); } catch { /* a private window: it lasts this visit */ } };
  let wanted = read();
  const asked = (N) => new Promise((done) => {
    try {
      const out = N.requestPermission((answer) => done(answer)); // older Safari answers by callback
      if (out && typeof out.then === 'function') out.then(done, () => done('default'));
    } catch { done('default'); }
  });
  return {
    // on: chosen here, and the browser lets the page show them
    on: () => wanted && alertsState(win) === 'granted',
    state: () => alertsState(win),
    // Switches them on (asking the browser first) or off. Gives what to say, in words.
    async set(on) {
      if (!on) { wanted = false; write(false); return SAID.off; }
      const state = alertsState(win);
      if (state === 'none' || state === 'denied') { wanted = false; write(false); return SAID[state]; }
      const answer = state === 'granted' ? 'granted' : await asked(win.Notification);
      wanted = answer === 'granted';
      write(wanted);
      return wanted ? SAID.on : answer === 'denied' ? SAID.denied : SAID.refused;
    },
    // One alert for an item; `open` runs when it is clicked, after the page is brought forward. Gives whether it showed.
    show(item, floor, open) {
      if (!wanted || alertsState(win) !== 'granted') return false;
      const a = alertOf(item, floor);
      try {
        const shown = new win.Notification(a.title, { body: a.body, tag: a.tag });
        shown.onclick = () => {
          try { win.focus?.(); } catch { /* the browser brings it forward itself */ }
          try { open?.(); } finally { shown.close?.(); }
        };
        return true;
      } catch {
        wanted = false; // a phone's browser that only shows them from a service worker: said once, and off
        write(false);
        return false;
      }
    },
    said: (why) => SAID[why] || '',
  };
}
