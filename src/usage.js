// Your plan's limits, and when you'd reach them at this pace (docs/connect.md, "Usage forecast"). The readings
// are Claude Code's and Codex's own, kept a few hours back by connect/usage.py in data/feeds/usage.json:
// { sources: { "Claude Code": { five_hour: [{ at, used, resets_at }, ...], seven_day: [...] }, "Codex": {...} } }.
// The pace is how fast the last hour's readings rose; at that pace, the limit is reached at reachAt, and that
// matters only if it comes before the limit starts again. A week's limit goes by the average pace since its
// week began instead: one busy hour says little about the days left. Plain module: tests/test_usage.py runs it
// under Node.

const NAMES = { five_hour: '5-hour limit', seven_day: 'weekly limit' };
const PACE = 3600; // seconds of readings that set the pace
const SHORTEST = 300; // readings spanning less than this set no pace yet
const STALE = 6 * 3600; // a last reading older than this says nothing about now
const LENGTH = { five_hour: 5 * 3600, seven_day: 7 * 86400 }; // how long each limit's window is

const finite = (n) => typeof n === 'number' && Number.isFinite(n);

// [{ source, name, label, used, at, resets, rate, reachAt, reaches }], the most pressing first. `reaches` is
// 'now' (used up), 'before' (reached before it starts again), 'after' (it lasts), or 'unknown' (no pace yet).
export function forecastOf(feed, now = Date.now() / 1000) {
  const out = [];
  const sources = feed && typeof feed.sources === 'object' && feed.sources ? feed.sources : {};
  for (const [source, windows] of Object.entries(sources)) {
    if (!windows || typeof windows !== 'object') continue;
    for (const [name, rows] of Object.entries(windows)) {
      const list = (Array.isArray(rows) ? rows : []).filter((r) => r && finite(r.at) && finite(r.used)).sort((a, b) => a.at - b.at);
      const last = list[list.length - 1];
      if (!last || now - last.at > STALE) continue;
      const resets = finite(last.resets_at) ? last.resets_at : null;
      if (resets && resets <= now) continue; // it has started again since the last reading
      const same = (r) => (finite(r.resets_at) ? r.resets_at : null) === resets || (resets && finite(r.resets_at) && Math.abs(r.resets_at - resets) < 120);
      const recent = list.filter((r) => r.at >= last.at - PACE && same(r));
      const first = recent[0];
      const span = first ? last.at - first.at : 0;
      const began = resets && LENGTH[name] ? resets - LENGTH[name] : null;
      const since = began != null ? last.at - began : 0;
      const average = since >= SHORTEST ? last.used / since : null; // since the window began
      const hour = span >= SHORTEST ? Math.max(0, last.used - first.used) / span : null; // the last hour's
      const rate = name === 'seven_day' ? (average ?? hour) : (hour ?? average); // percent a second
      const left = Math.max(0, 100 - last.used);
      const reachAt = rate > 0 ? last.at + left / rate : null;
      const reaches = last.used >= 100 ? 'now' : reachAt && (!resets || reachAt < resets) ? 'before' : rate === null ? 'unknown' : 'after';
      out.push({ source, name, label: NAMES[name] || name.replace(/_/g, ' '), used: last.used, at: last.at, resets, rate, reachAt, reaches });
    }
  }
  const rank = { now: 0, before: 1, unknown: 2, after: 3 };
  return out.sort((a, b) => rank[a.reaches] - rank[b.reaches] || (a.reaches === 'before' ? a.reachAt - b.reachAt : b.used - a.used));
}

// A time as people say it: 15:40 today, or with the day, "Sat 09:00", when it is further off.
export function clockOf(t, now = Date.now() / 1000) {
  const d = new Date(t * 1000);
  const hm = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const today = new Date(now * 1000).toDateString() === d.toDateString();
  return today ? hm : `${d.toLocaleDateString([], { weekday: 'short' })} ${hm}`;
}

// What a forecast means for you, in one sentence: when you'd reach the limit, or that it lasts.
export function usageLine(f, now = Date.now() / 1000) {
  const again = f.resets ? ` at ${clockOf(f.resets, now)}` : '';
  if (f.reaches === 'now') return `Used up. It starts again${again || ' soon'}.`;
  if (f.reaches === 'before') return `At this pace you reach it around ${clockOf(f.reachAt, now)}, before it starts again${again}.`;
  if (f.reaches === 'after') return `At this pace it lasts until it starts again${again}.`;
  return again ? `It starts again${again}.` : 'Not enough readings yet to tell the pace.';
}

// One forecast in words, said whole.
export function usageWords(f, now = Date.now() / 1000) {
  if (f.reaches === 'now') return `${f.source}'s ${f.label} is used up. ${usageLine(f, now).replace(/^Used up\. /, '')}`;
  return `${f.source}: ${Math.round(f.used)}% of the ${f.label} is used. ${usageLine(f, now)}`;
}

// Whether any limit is used up, or will be before it starts again.
export const pressing = (list) => list.some((f) => f.reaches === 'now' || f.reaches === 'before');
