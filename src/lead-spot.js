// Where a project floor's lead stands on a walk (walk.js), and the ring you stand on to talk to them: a few steps
// from where the lift lets you out, in sight of its doorstep, but never in a doorway, on the way from the lift into
// a room, straight out of the lift, or in a corridor they would cut in two. The ways people walk are bands, not
// lines: straight out of the lift to the first wall, each doorway's whole width a few steps into its room, and each
// route from the lift. Their ring keeps well clear of them too, so walking out of the lift or into a room, however
// you go, never bumps into them or starts a talk. Plain module, so tests/test_lead_spot.py can feed it made-up floor
// plans under Node.
//
// leadSpot({ plan, lift, inLift, doors, ways }) gives { x, z, stand: [x, z], out: [x, z] }, or null when there is
// nowhere to stand at all.
//   plan: the walk's floor plan in squares, { cols, rows, x0, z0, cell, open, free(x, z) }: open marks the squares
//     the walker can reach from the lift, free(x, z) whether a point is clear to stand on.
//   lift: { x, z, yaw }, where the lift lets you out, facing out; inLift(x, z) whether a point is inside it.
//   doors: each room's doorway as [x, z, outside x, outside z, half]: a point just inside it, one just outside, and
//     how wide it is either side of its middle (0.5 m if left out).
//   ways: the walking routes from the lift to each doorway, as lists of [x, z] corners.
// stand is where you stand to talk to them (their ring), and they face it. out is the lift's doorstep.

export const LEAD_SPOT = {
  near: 1.2, // metres from the lift's doorstep, at the closest
  far: 5, // and at the furthest
  best: 2.6, // the distance that reads best: a few steps out, easily seen
  door: 1.6, // never closer than this to a doorway, inside or out
  way: 0.6, // nor to the edge of a way people walk (out of the lift, into any room, or from the lift to one): never bumped into
  into: 3, // how far past a doorway its whole width counts as the way into its room
  half: 0.5, // a doorway's width either side of its middle, when not given
  wide: 0.3, // how far either side of the straight way out of the lift people drift
  route: 0.2, // and either side of a route from the lift to a doorway
  turn: 1.5, // how far on past where a doorway comes into sight people may walk before turning for it
  body: 0.7, // the squares their body takes, with the walker's own width round it
  talk: [0.9, 1.4], // how far from them you stand to talk
  talkDoor: 1.1, // and that ring's own distance from a doorway
  talkWay: 0.6, // and from the edge of a way people walk: well past the 0.42 m that starts a talk
};

// Whether someone at (x, z) walking at (vx, vz) metres a second is only crossing the ring of a person at (ax, az),
// on their way somewhere else: moving, and heading more than 40 degrees off the way to them. walk.js starts no talk
// for a lead's ring crossed like that; stopping on it, or walking on towards them, starts one.
export const TOWARDS = 40;
export function crossingOnly(x, z, vx, vz, ax, az) {
  const speed = Math.hypot(vx, vz);
  if (!(speed > 0.15)) return false;
  return vx * (ax - x) + vz * (az - z) < speed * Math.hypot(ax - x, az - z) * Math.cos((TOWARDS * Math.PI) / 180);
}

export function leadSpot({ plan, lift, inLift = () => false, doors = [], ways = [], options = {} }) {
  const o = { ...LEAD_SPOT, ...options };
  const { cols, rows, x0, z0, cell, open, free } = plan;
  if (!cols || !rows || !open || !free || !lift) return null;
  const at = (i) => [x0 + ((i % cols) + 0.5) * cell, z0 + (Math.floor(i / cols) + 0.5) * cell];
  const square = (x, z) => {
    const q = Math.floor((x - x0) / cell);
    const r = Math.floor((z - z0) / cell);
    return q < 0 || r < 0 || q >= cols || r >= rows ? -1 : r * cols + q;
  };
  const sees = (ax, az, bx, bz) => {
    const steps = Math.ceil(Math.hypot(bx - ax, bz - az) / (cell / 2));
    for (let i = 1; i < steps; i++) if (!free(ax + ((bx - ax) * i) / steps, az + ((bz - az) * i) / steps)) return false;
    return true;
  };
  const roomy = (x, z, r) => [[0, 0], [r, 0], [-r, 0], [0, r], [0, -r]].every(([a, b]) => free(x + a, z + b));
  const fx = -Math.sin(lift.yaw || 0);
  const fz = -Math.cos(lift.yaw || 0);

  // The lift's doorstep: straight out of it, the first point outside it with room on both sides (past the narrow
  // way out of its car, where there is one).
  let out = [lift.x, lift.z];
  for (let t = cell / 2; t <= 4; t += cell / 2) {
    const x = lift.x + fx * t;
    const z = lift.z + fz * t;
    if (!free(x, z)) break;
    out = [x, z];
    if (!inLift(x, z) && free(x + fz * 0.45, z - fx * 0.45) && free(x - fz * 0.45, z + fx * 0.45)) break;
  }

  // The ways people walk, each a band some way either side of a line: straight out of the lift to the first wall,
  // each route from the lift to a doorway, and each doorway's whole width on into its room (square at its ends: the
  // routes and turns say how people come up to it).
  const segs = []; // [from x, from z, to x, to z, how far either side, square ends]
  const line = (pts, side) => { for (let i = 1; i < pts.length; i++) segs.push([pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1], side]); };
  let ahead = out;
  for (let t = cell / 2; t <= 12; t += cell / 2) {
    const x = out[0] + fx * t;
    const z = out[1] + fz * t;
    if (!free(x, z)) break;
    ahead = [x, z];
  }
  line([[lift.x, lift.z], out, ahead], o.wide);
  for (const w of ways) if (Array.isArray(w) && w.length > 1) line(w, o.route);
  // and the turns people make on the way out: towards each doorway once it comes into sight, or a step or two later
  // (o.turn), from every point of the way out in between, so the whole wedge they may cut across is covered
  const long = Math.hypot(ahead[0] - out[0], ahead[1] - out[1]);
  for (const [, , ox, oz] of doors) {
    let first = null;
    for (let t = 0; t <= long + 1e-9; t += cell) {
      const from = [out[0] + fx * t, out[1] + fz * t];
      if (first === null && sees(from[0], from[1], ox, oz)) first = t;
      if (first !== null && t > first + o.turn) break;
      if (first !== null) line([from, [ox, oz]], o.route);
    }
  }
  for (const [x, z, ox, oz, half] of doors) {
    const n = Math.hypot(x - ox, z - oz) || 1;
    segs.push([ox, oz, x + ((x - ox) / n) * o.into, z + ((z - oz) / n) * o.into, Number.isFinite(half) && half > 0 ? half : o.half, true]);
  }
  // how far a point is from a band's middle line; past a square end, its side plus how far past the end it is
  const toSeg = (px, pz, [ax, az, bx, bz, side, square]) => {
    const dx = bx - ax;
    const dz = bz - az;
    const l = dx * dx + dz * dz;
    if (square && l) {
      const n = Math.sqrt(l);
      const u = ((px - ax) * dx + (pz - az) * dz) / n;
      const v = Math.abs((pz - az) * dx - (px - ax) * dz) / n;
      const past = Math.max(0, -u, u - n);
      return past ? side + Math.hypot(past, Math.max(0, v - side)) : v;
    }
    const t = l ? Math.max(0, Math.min(1, ((px - ax) * dx + (pz - az) * dz) / l)) : 0;
    return Math.hypot(px - ax - t * dx, pz - az - t * dz);
  };
  // Whether walking along every way that passes over (x, z) heads well away from someone at (cx, cz): 55 degrees
  // or more off, either way along it, so crossing their ring there starts no talk (crossingOnly, 40 degrees, with
  // room for a walker's own wander).
  const crossesOnly = (x, z, cx, cz) => {
    const g = Math.hypot(cx - x, cz - z) || 1;
    return segs.every((seg) => {
      if (toSeg(x, z, seg) - seg[4] >= 0.62) return true; // too far off this way to be on its ring while walking it
      const dx = seg[2] - seg[0];
      const dz = seg[3] - seg[1];
      const l = Math.hypot(dx, dz);
      return !l || Math.abs(dx * (cx - x) + dz * (cz - z)) / (l * g) <= Math.cos((55 * Math.PI) / 180);
    });
  };
  const wayGap = (x, z) => segs.reduce((m, s) => Math.min(m, toSeg(x, z, s) - s[4]), Infinity); // from a band's edge
  // and from the middle of the way straight out of the lift, where anyone walking straight out goes
  const straightGap = (x, z) => Math.min(toSeg(x, z, segs[0]), toSeg(x, z, segs[1]));
  const doorGap = (x, z) => doors.reduce((m, [a, b, c, d]) => Math.min(m, Math.hypot(x - a, z - b), Math.hypot(x - c, z - d)), Infinity);

  // Walking from a square, in squares, with someone standing at (bx, bz): -1 where it can't be reached.
  const walk = (start, bx = Infinity, bz = Infinity) => {
    const steps = new Int32Array(open.length).fill(-1);
    let n = 0;
    if (start < 0 || !open[start]) return { steps, n };
    const queue = [start];
    steps[start] = 0;
    for (let head = 0; head < queue.length; head++) {
      const i = queue[head];
      n += 1;
      const q = i % cols;
      const r = (i - q) / cols;
      for (const [nq, nr] of [[q + 1, r], [q - 1, r], [q, r + 1], [q, r - 1]]) {
        const j = nr * cols + nq;
        if (nq < 0 || nr < 0 || nq >= cols || nr >= rows || steps[j] >= 0 || !open[j]) continue;
        const [x, z] = at(j);
        if (Math.hypot(x - bx, z - bz) < o.body) continue;
        steps[j] = steps[i] + 1;
        queue.push(j);
      }
    }
    return { steps, n };
  };
  const home = square(lift.x, lift.z);
  const all = walk(home).n;
  if (!all) return null; // the lift's own square out of reach: nothing could be checked for cutting the floor
  const walked = walk(square(out[0], out[1])).steps;
  // They must never cut the floor in two, as one standing in a narrow corridor would: beyond the squares their body
  // takes, everything reachable stays reachable.
  const keepsWhole = (c) => {
    let body = 0;
    for (let i = 0; i < open.length; i++) {
      if (!open[i]) continue;
      const [x, z] = at(i);
      if (Math.hypot(x - c.x, z - c.z) < o.body) body += 1;
    }
    return all - walk(home, c.x, c.z).n <= body + 2;
  };

  const near = [];
  for (let i = 0; i < open.length; i++) {
    if (!open[i]) continue;
    const [x, z] = at(i);
    const d = Math.hypot(x - out[0], z - out[1]);
    const room = roomy(x, z, 0.45) ? 0.45 : roomy(x, z, 0.25) ? 0.25 : 0; // room round them: by a wall at the least
    if (d < o.near || inLift(x, z) || !room) continue;
    const facing = ((x - out[0]) * fx + (z - out[1]) * fz) / d; // 1 straight ahead as you step out, -1 behind
    const seen = sees(out[0], out[1], x, z);
    const way = wayGap(x, z);
    // seen, the right few steps away, ahead as you step out, and (where the ways leave little room) as far off them as can be
    near.push({ x, z, i, d, room, door: doorGap(x, z), way, straight: straightGap(x, z), score: (seen ? 0 : 1.5) + Math.abs(d - o.best) * 0.5 + (1 - facing) * 0.6 + Math.max(0, o.way - way) * 1.5 });
  }
  near.sort((a, b) => a.score - b.score);

  // Where you stand to talk to someone at c, in sight of them: well clear of the ways people walk, and of those
  // the nearest on foot from the doorstep, so they face the way you come.
  const ringFor = (c, t) => {
    let best = null;
    const span = Math.ceil(o.talk[1] / cell);
    const q0 = c.i % cols;
    const r0 = (c.i - q0) / cols;
    for (let r = r0 - span; r <= r0 + span; r++) {
      for (let q = q0 - span; q <= q0 + span; q++) {
        if (q < 0 || r < 0 || q >= cols || r >= rows) continue;
        const j = r * cols + q;
        if (!open[j] || walked[j] < 0) continue;
        const [x, z] = at(j);
        const g = Math.hypot(x - c.x, z - c.z);
        if (g < o.talk[0] || g > o.talk[1] || inLift(x, z) || !roomy(x, z, 0.2)) continue;
        if (doorGap(x, z) < t.talkDoor || wayGap(x, z) < t.talkWay || straightGap(x, z) < t.ringStraight || !sees(c.x, c.z, x, z)) continue;
        if (t.crossing && !crossesOnly(x, z, c.x, c.z)) continue;
        const score = walked[j] * cell * 0.5 + Math.max(0, 2 - wayGap(x, z)) * 1.5;
        if (!best || score < best.score) best = { x, z, score };
      }
    }
    return best && [best.x, best.z];
  };

  // The rules, kept in full where the floor allows, then eased a step at a time, so a lead always has somewhere
  // (at the last, anywhere on the floor with room to stand). Their ring gives way first: walking across it on the way
  // somewhere else starts nothing (walk.js), so it may lie where people walk, though never on the way straight out.
  // Where they stand gives way only after that, since they are someone to walk round: by a wall, then nearer the
  // ways, and further off only at the very last. Until the very last, someone walking straight out of the lift,
  // drifting half a metre, never walks into them (1.1 m: their body and the walker's are 0.57 m).
  const full = { far: o.far, door: o.door, way: o.way, straight: 1.1, talkDoor: o.talkDoor, talkWay: o.talkWay, ringStraight: 0.9 };
  const ringOnWays = { talkDoor: o.talkDoor / 2, talkWay: -Infinity, ringStraight: 0.5, crossing: true };
  const tiers = [
    { ...full, room: 0.45 },
    { ...full, room: 0.25 },
    { ...full, ...ringOnWays, room: 0.25 },
    { ...full, ...ringOnWays, room: 0.25, way: o.way / 2 },
    { ...full, ...ringOnWays, room: 0.25, way: 0, door: o.door / 2, straight: 0.8 },
    { ...full, ...ringOnWays, room: 0.25, way: -o.way / 2, door: o.door / 2, straight: 0.6 },
    { ...full, ...ringOnWays, room: 0.25, way: -Infinity, door: o.door / 2, straight: 0.6, far: Infinity },
    // never with a doorway inside them, where any floor has room for that
    { far: Infinity, room: 0.25, door: o.body, way: -Infinity, talkDoor: 0, talkWay: -Infinity, straight: 0, ringStraight: 0 },
    { far: Infinity, room: 0.25, door: 0, way: -Infinity, talkDoor: 0, talkWay: -Infinity, straight: 0, ringStraight: 0 },
  ];
  const whole = new Map(); // each spot's floor-cutting check, done once however many rules try it
  for (const [n, t] of tiers.entries()) {
    let tried = 0;
    for (const c of near) {
      if (c.d > t.far || c.room < t.room || c.door < t.door || c.way < t.way || c.straight < t.straight) continue;
      const stand = ringFor(c, t);
      if (!stand) continue;
      if (!whole.has(c.i)) {
        if (tried++ >= (t.far === Infinity ? 400 : 60)) break; // the last resorts look further
        whole.set(c.i, keepsWhole(c));
      }
      if (whole.get(c.i)) return { x: c.x, z: c.z, stand, out, eased: n };
    }
  }
  return null;
}
