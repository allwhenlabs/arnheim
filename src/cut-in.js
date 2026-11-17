// Cutting in by talking: while someone in the building is speaking, hears whether you have started talking over
// them, so they stop and listen (voice.js). The microphone also picks up their own voice from the speakers, even
// with the browser's echo cancelling. The page knows how loud what it plays is at each moment, so this learns how
// much of that comes back through the microphone (the echo), from their voice itself rather than the silence
// around it, and only counts sound well above what that echo would be now: a soft voice followed by a loud one,
// or a quiet start to a loud sentence, is expected, never taken for you. Plain module, so tests/test_cut_in.py can
// feed it numbers under Node.
//
// const cut = createCutIn(); cut.reset() as they start speaking; then for each block of sound while they speak,
// cut.hear(db, seconds, room, out) is true once you have talked over them. db: the microphone's loudness;
// room: the quiet room's (voice.js learns it while listening); out: the loudest of what was played during the
// block, all in decibels.

export const CUT_IN = {
  loud: -45, // what is played counts as their voice above this
  learn: 0.4, // seconds of their voice spent learning its echo, before anything counts
  lag: 0.4, // seconds their voice may take to come back: the speakers, the room and the sound card all delay it
  margin: 12, // how far above the echo of what was just played your voice must be, in decibels
  above: 22, // and how far above the quiet room
  quietest: -48, // and never quieter than this
  window: 0.6, // seconds looked back over
  need: 0.2, // seconds of you within them: about one short word said firmly ("wait", "stop"); a cough is less
  rise: 3, // how fast, in decibels a second, the echo may grow once learned (the volume turned up)
  fall: 1, // and fade
  // If you were talking as they started, your voice was learned as their echo; if their voice never once comes
  // back near it, and this many seconds of it have all come back at least `drop` decibels under it, the echo is
  // learned again from them alone, once (so after you stop, the next time you talk over them counts). An echo
  // that was heard as learned is never relearned lower, so the echo cancelling settling for a while, or the
  // volume turned down, and their voice leaking back as loud as before, never cuts them off.
  relearn: 1.5,
  drop: 6,
};

export function createCutIn(opts = {}) {
  const o = { ...CUT_IN, ...opts };
  let echo = null; // how much softer the microphone hears their voice than it is played, in decibels
  let learned = 0; // seconds of their voice heard so far
  let outs = []; // [how loud was played, seconds] for the last `lag` seconds
  let outSpan = 0;
  let seen = []; // [how much softer their voice came back, or null, seconds] for the last `relearn` seconds
  let seenSpan = 0;
  let seenVoiced = 0;
  let sure = false; // their voice has come back near the echo learned (or it was learned again from them)
  let recent = []; // [you, seconds] for the last `window` seconds
  let span = 0;
  let over = 0; // seconds of you within them
  return {
    reset() { echo = null; learned = 0; outs = []; outSpan = 0; seen = []; seenSpan = 0; seenVoiced = 0; sure = false; recent = []; span = 0; over = 0; },
    hear(db, seconds, room = -60, out = -120) {
      const d = Number(db);
      const s = Math.max(0, Number(seconds) || 0);
      if (!Number.isFinite(d)) return false;
      outs.push([Number.isFinite(Number(out)) ? Number(out) : -120, s]);
      outSpan += s;
      while (outs.length > 1 && outSpan - outs[0][1] >= o.lag - 1e-9) outSpan -= outs.shift()[1];
      let played = -120; // the loudest of what was played lately: what the microphone may be hearing back now
      for (const [x] of outs) if (x > played) played = x;
      const voiced = played > o.loud;
      if (learned < o.learn) {
        if (voiced) {
          learned += s;
          echo = echo == null ? d - played : Math.max(echo, d - played);
        }
        return false;
      }
      const loud = d > Math.max(played + echo + o.margin, room + o.above, o.quietest);
      recent.push([loud, s]);
      span += s;
      if (loud) over += s;
      while (span > o.window + 1e-9 && recent.length) {
        const [was, x] = recent.shift();
        span -= x;
        if (was) over -= x;
      }
      // the echo follows a change of volume slowly, only from their voice, and never while you may be talking,
      // so your own voice never raises the bar
      const theirs = voiced && over <= 1e-9;
      if (theirs) {
        const now = d - played;
        if (now >= echo - o.drop) sure = true;
        echo = now > echo ? Math.min(now, echo + o.rise * s) : Math.max(now, echo - o.fall * s);
      }
      seen.push([theirs ? d - played : null, s]);
      seenSpan += s;
      if (theirs) seenVoiced += s;
      while (seen.length > 1 && seenSpan - seen[0][1] >= o.relearn - 1e-9) {
        const [r, x] = seen.shift();
        seenSpan -= x;
        if (r != null) seenVoiced -= x;
      }
      if (!sure && seenSpan >= o.relearn - 1e-9 && seenVoiced >= o.relearn / 2) {
        let most = -Infinity;
        for (const [r] of seen) if (r != null && r > most) most = r;
        if (most <= echo - o.drop) {
          echo = most + o.drop / 2; // a little above it, as the echo may grow again
          sure = true;
        }
      }
      return over >= o.need - 1e-9;
    },
  };
}
