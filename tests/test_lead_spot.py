"""Where a floor's lead stands on a walk (src/lead-spot.js): a few steps from the lift and in sight of its doorstep,
but never in a doorway, on the way into a room, straight out of the lift, or in a corridor they would cut in two.
Their ring, where you stand to talk, keeps out of doorways and those ways too, so walking out of the lift or into a
room never starts a talk. Fed made-up floor plans drawn in squares of 0.2 m: '.' you can stand there, '#' you can't.

The rule is JavaScript, so this runs it under Node.js, and is skipped where Node isn't installed.
Run from the repository's folder: python3 -m unittest discover tests
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")

SCRIPT = r"""
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';
const { leadSpot, crossingOnly } = await import(pathToFileURL(process.argv[1] + '/src/lead-spot.js').href);
const CELL = 0.2;
const centre = (c) => (c + 0.5) * CELL;
// A floor drawn as rows of '.' and '#'. The lift is where 'L' is, facing down the page (towards more rows), unless
// it is given.
function floor(lines, lift = null) {
  const rows = lines.length, cols = lines[0].length;
  const grid = lines.map((line, r) => [...line].map((ch, q) => { if (ch === 'L') lift = { x: centre(q), z: centre(r), yaw: Math.PI }; return ch !== '#'; }));
  const free = (x, z) => { const q = Math.floor(x / CELL), r = Math.floor(z / CELL); return q >= 0 && r >= 0 && q < cols && r < rows && grid[r][q]; };
  const open = new Uint8Array(cols * rows);
  const start = Math.floor(lift.z / CELL) * cols + Math.floor(lift.x / CELL);
  const queue = [start];
  open[start] = 1;
  while (queue.length) {
    const i = queue.pop(), q = i % cols, r = (i - q) / cols;
    for (const [nq, nr] of [[q + 1, r], [q - 1, r], [q, r + 1], [q, r - 1]]) {
      if (nq < 0 || nr < 0 || nq >= cols || nr >= rows || open[nr * cols + nq] || !grid[nr][nq]) continue;
      open[nr * cols + nq] = 1;
      queue.push(nr * cols + nq);
    }
  }
  return { plan: { cols, rows, x0: 0, z0: 0, cell: CELL, open, free }, lift, free, cols, rows, grid };
}
// How many squares that could be walked to from the lift can't be with someone (their body, 0.7 m) at (bx, bz),
// beyond those their body takes.
function cutOff(f, bx, bz) {
  const { cols, rows, plan } = f;
  const seen = new Uint8Array(cols * rows);
  const start = Math.floor(f.lift.z / CELL) * cols + Math.floor(f.lift.x / CELL);
  const queue = [start];
  seen[start] = 1;
  while (queue.length) {
    const i = queue.pop(), q = i % cols, r = (i - q) / cols;
    for (const [nq, nr] of [[q + 1, r], [q - 1, r], [q, r + 1], [q, r - 1]]) {
      const j = nr * cols + nq;
      if (nq < 0 || nr < 0 || nq >= cols || nr >= rows || seen[j] || !plan.open[j]) continue;
      if (Math.hypot(centre(nq) - bx, centre(nr) - bz) < 0.7) continue;
      seen[j] = 1;
      queue.push(j);
    }
  }
  let lost = 0;
  for (let j = 0; j < cols * rows; j++) if (plan.open[j] && !seen[j] && Math.hypot(centre(j % cols) - bx, centre(Math.floor(j / cols)) - bz) >= 0.7) lost += 1;
  return lost;
}
// Whether every point can still be walked to from the lift with someone (their body, 0.7 m) at (bx, bz).
function stillReach(f, bx, bz, points) {
  const { cols, rows, grid, lift } = f;
  const seen = new Uint8Array(cols * rows);
  const start = Math.floor(lift.z / CELL) * cols + Math.floor(lift.x / CELL);
  const queue = [start];
  seen[start] = 1;
  while (queue.length) {
    const i = queue.pop(), q = i % cols, r = (i - q) / cols;
    for (const [nq, nr] of [[q + 1, r], [q - 1, r], [q, r + 1], [q, r - 1]]) {
      if (nq < 0 || nr < 0 || nq >= cols || nr >= rows || seen[nr * cols + nq] || !grid[nr][nq]) continue;
      if (Math.hypot(centre(nq) - bx, centre(nr) - bz) < 0.7) continue;
      seen[nr * cols + nq] = 1;
      queue.push(nr * cols + nq);
    }
  }
  return points.every(([x, z]) => seen[Math.floor(z / CELL) * cols + Math.floor(x / CELL)] === 1);
}
const sees = (free, [ax, az], [bx, bz]) => { const n = Math.ceil(Math.hypot(bx - ax, bz - az) / 0.1); for (let i = 1; i < n; i++) if (!free(ax + ((bx - ax) * i) / n, az + ((bz - az) * i) / n)) return false; return true; };
const toLine = ([px, pz], [ax, az], [bx, bz]) => { const dx = bx - ax, dz = bz - az, l = dx * dx + dz * dz; const t = l ? Math.max(0, Math.min(1, ((px - ax) * dx + (pz - az) * dz) / l)) : 0; return Math.hypot(px - ax - t * dx, pz - az - t * dz); };
const r2 = (n) => Math.round(n * 100) / 100;
// People walking as they do, not as the rule draws its bands: straight out of the lift, drifting up to half a metre
// either side, to the first wall; from the doorstep through every part of each doorway and 3.5 m on into its room;
// and turning off the way out towards each doorway, anywhere from where it comes into sight to 1.5 m further on.
// Gives how close any of them comes to the lead (centre to centre), to their ring, and to their ring while heading
// for them (within 40 degrees: only that starts a talk without stopping, walk.js).
function walks(f, s, doors) {
  const { free, lift } = f;
  const path = (a, b, on) => { // samples every 5 cm from a towards b, then on past b in the same direction, while clear
    const dx = b[0] - a[0], dz = b[1] - a[1], n = Math.hypot(dx, dz) || 1;
    const pts = [];
    for (let t = 0; t <= n + on + 1e-9; t += 0.05) { const p = [a[0] + (dx / n) * t, a[1] + (dz / n) * t, dx / n, dz / n]; if (!free(p[0], p[1])) break; pts.push(p); }
    return pts;
  };
  const lines = [];
  for (let side = -0.5; side <= 0.5001; side += 0.1) lines.push(path([lift.x + side, s.out[1]], [lift.x + side, s.out[1] + 1], 20));
  const straight = path(s.out, [s.out[0], s.out[1] + 1], 20);
  const head = Math.min(...straight.map((p) => Math.hypot(p[0] - s.x, p[1] - s.z))); // straight out, no drift
  for (const [x, z, ox, oz, half = 0.5] of doors) {
    const n = Math.hypot(x - ox, z - oz) || 1, px = -(z - oz) / n, pz = (x - ox) / n;
    for (let k = -half; k <= half + 1e-9; k += 0.1) {
      const through = [x + px * k, z + pz * k];
      if (!free(...through)) continue;
      lines.push([...path(s.out, [ox + px * k, oz + pz * k], 0), ...path([ox + px * k, oz + pz * k], through, 3.5)]);
    }
    const first = straight.findIndex((p) => sees(free, p, [ox, oz]));
    if (first >= 0) for (const from of straight.slice(first, first + 31).filter((_, i) => i % 2 === 0)) lines.push(path(from, [ox, oz], 0));
  }
  let lead = Infinity, ring = Infinity, towards = Infinity;
  for (const [x, z, hx, hz] of lines.flat()) {
    const d = Math.hypot(x - s.x, z - s.z);
    lead = Math.min(lead, d);
    const r = Math.hypot(x - s.stand[0], z - s.stand[1]);
    ring = Math.min(ring, r);
    if ((hx * (s.x - x) + hz * (s.z - z)) / (d || 1) >= Math.cos(Math.PI * 40 / 180)) towards = Math.min(towards, r);
  }
  return { lead: r2(lead), ring: r2(ring), towards: r2(towards), straight: r2(head), count: lines.length };
}
function report(f, doors, ways, extra = {}) {
  const s = leadSpot({ plan: f.plan, lift: f.lift, inLift: extra.inLift || (() => false), doors, ways });
  if (!s) return null;
  const routeGap = (p) => Math.min(Infinity, ...ways.flatMap((w) => w.slice(1).map((b, i) => toLine(p, w[i], b))));
  const lead = [s.x, s.z];
  const doorGap = (p) => Math.min(...doors.flatMap(([a, b, c, d]) => [Math.hypot(p[0] - a, p[1] - b), Math.hypot(p[0] - c, p[1] - d)]));
  const straight = [[f.lift.x, f.lift.z], [f.lift.x, f.lift.z + 3.2]]; // the way straight out of the lift
  return {
    lead: lead.map(r2), stand: s.stand.map(r2), out: s.out.map(r2), eased: s.eased,
    leadDoor: r2(doorGap(lead)), standDoor: r2(doorGap(s.stand)),
    leadOffStraight: r2(toLine(lead, ...straight)), standOffStraight: r2(toLine(s.stand, ...straight)),
    fromOut: r2(Math.hypot(s.x - s.out[0], s.z - s.out[1])), talkGap: r2(Math.hypot(s.x - s.stand[0], s.z - s.stand[1])),
    seen: sees(f.free, s.out, lead), seesRing: sees(f.free, lead, s.stand),
    reachAll: stillReach(f, s.x, s.z, doors.flatMap(([a, b, c, d]) => [[a, b], [c, d]]).concat(extra.reach || [])),
    cutOff: cutOff(f, s.x, s.z),
    walked: walks(f, s, doors),
    leadRoute: r2(routeGap([s.x, s.z])), standRoute: r2(routeGap(s.stand)),
  };
}
const row = (n, s) => s.repeat(n);
// 1. The sample floor's shape: the lift's car, a narrow way out of it, a corridor 0.8 m wide, and straight ahead
//    a doorway 1.4 m wide into a big room; a small room off the corridor to the left. 40 squares by 50.
const studio = [];
for (let r = 0; r < 50; r++) {
  let line = row(40, '#').split('');
  const set = (a, b) => { for (let q = a; q <= b; q++) line[q] = '.'; };
  if (r >= 1 && r <= 4) set(17, 22); // the lift's car
  if (r >= 5 && r <= 8) set(19, 20); // the narrow way out of it
  if (r >= 9 && r <= 12) set(1, 38); // the corridor
  if (r >= 1 && r <= 6) set(2, 10); // a small room...
  if (r === 7 || r === 8) set(5, 7); // ...whose doorway opens on the corridor
  if (r >= 13 && r <= 15) set(17, 23); // the big room's doorway
  if (r >= 16 && r <= 48) set(1, 38); // the big room
  studio.push(line.join(''));
}
studio[2] = studio[2].slice(0, 19) + 'L' + studio[2].slice(20);
const fs = floor(studio);
const doorsStudio = [[centre(20), centre(15), centre(20), centre(12)], [centre(6), centre(7), centre(6), centre(9)]];
const waysStudio = [
  [[fs.lift.x, fs.lift.z], [centre(19.5), centre(10)], [centre(20), centre(12)]],
  [[fs.lift.x, fs.lift.z], [centre(19.5), centre(10)], [centre(6), centre(10)], [centre(6), centre(9)]],
];
// 2. An open lobby: the lift opens straight into a wide hall, with one room's doorway far off.
const lobby = [];
for (let r = 0; r < 40; r++) {
  let line = row(50, '#').split('');
  for (let q = 1; q <= 48; q++) if ((r >= 1 && r <= 3 && q >= 22 && q <= 27) || (r >= 4 && r <= 38)) line[q] = '.';
  lobby.push(line.join(''));
}
lobby[2] = lobby[2].slice(0, 24) + 'L' + lobby[2].slice(25);
const fl = floor(lobby);
const doorsLobby = [[centre(45), centre(37), centre(45), centre(35)]];
const waysLobby = [[[fl.lift.x, fl.lift.z], [centre(45), centre(35)]]];
// 3. Nothing but corridors 0.8 m wide: the lift opens on one, with a doorway at each end. The lead still has a
//    place, and never cuts the way to either.
const narrow = [];
for (let r = 0; r < 20; r++) {
  let line = row(60, '#').split('');
  for (let q = 0; q < 60; q++) if ((r >= 1 && r <= 4 && q >= 27 && q <= 32) || (r >= 5 && r <= 8 && q >= 1 && q <= 58) || (r >= 9 && r <= 18 && (q <= 6 && q >= 1 || q >= 53 && q <= 58))) line[q] = '.';
  narrow.push(line.join(''));
}
narrow[2] = narrow[2].slice(0, 29) + 'L' + narrow[2].slice(30);
const fn = floor(narrow);
const doorsNarrow = [[centre(3), centre(10), centre(3), centre(8)], [centre(56), centre(10), centre(56), centre(8)]];
const waysNarrow = [[[fn.lift.x, fn.lift.z], [centre(29.5), centre(7)], [centre(3), centre(7)], [centre(3), centre(8)]], [[fn.lift.x, fn.lift.z], [centre(29.5), centre(7)], [centre(56), centre(7)], [centre(56), centre(8)]]];
// 4. An open lobby with no doorways in it at all, and two routes across it that pass where the lead would
//    otherwise stand: they stand clear of both.
const fr = floor(lobby);
const waysOnly = [[[fr.lift.x, fr.lift.z], [fr.lift.x, centre(9)], [fr.lift.x + 1.0, centre(16)], [centre(46), centre(37)]],
                  [[fr.lift.x, fr.lift.z], [fr.lift.x, centre(9)], [fr.lift.x - 1.0, centre(16)], [centre(3), centre(37)]]];
// 5. The drawn look's shape: the lift's car opens through a narrow way onto a small lobby, which opens onto a hall
//    running off to one side, along open-fronted rooms. Everyone who walks out turns along the hall.
const hall = [];
for (let r = 0; r < 40; r++) {
  let line = row(70, '#').split('');
  const set = (a, b) => { for (let q = a; q <= b; q++) line[q] = '.'; };
  if (r >= 3 && r <= 8) set(6, 10); // the car
  if (r >= 9 && r <= 11) set(7, 9); // the way out of it
  if (r >= 12 && r <= 22) set(3, 12); // the lobby
  if (r >= 23 && r <= 34) set(3, 68); // the hall
  for (let i = 0; i < 4; i++) if (r >= 3 && r <= 22) set(16 + i * 13, 26 + i * 13); // the rooms, open to the hall
  hall.push(line.join(''));
}
hall[5] = hall[5].slice(0, 8) + 'L' + hall[5].slice(9);
const fh = floor(hall);
const doorsHall = [0, 1, 2, 3].map((i) => [centre(21 + i * 13), centre(19), centre(21 + i * 13), centre(25), 1.9]);
const waysHall = doorsHall.map(([, , ox, oz]) => [[fh.lift.x, fh.lift.z], [fh.lift.x, centre(12)], [centre(13), centre(23)], [ox, oz]]);
// 6. A real floor: the drawn look's project floor as the walk surveys it (tests/floors). The lift opens through a
//    narrow way onto a passage 2.4 m wide, which opens onto a long hall of open-fronted rooms.
const drawn = JSON.parse(readFileSync(process.argv[1] + '/tests/floors/drawn-project-floor.json', 'utf8'));
const fd = floor(drawn.grid, drawn.lift);
// 7. A cupboard: nowhere to stand at all.
const fc = floor(['#####', '#.L.#', '#####']);
console.log(JSON.stringify({
  studio: report(fs, doorsStudio, waysStudio, { inLift: (x, z) => z < 1.0 }),
  studioDoorstep: (() => { const s = leadSpot({ plan: fs.plan, lift: fs.lift, inLift: (x, z) => z < 1.0, doors: doorsStudio, ways: waysStudio }); return s && s.out.map(r2); })(),
  lobby: report(fl, doorsLobby, waysLobby, { inLift: (x, z) => z < 0.8 }),
  narrow: report(fn, doorsNarrow, waysNarrow, { inLift: (x, z) => z < 1.0 }),
  cupboard: leadSpot({ plan: fc.plan, lift: fc.lift, doors: [], ways: [] }),
  routes: report(fr, [], waysOnly, { inLift: (x, z) => z < 0.8 }),
  hall: report(fh, doorsHall, waysHall, { inLift: (x, z) => z < 1.8 }),
  drawn: report(fd, drawn.doors, drawn.ways, { inLift: (x, z) => z < 2.2 }),
  // walking at 1.5 m/s past someone 1 m away to the right (+x) of you, heading off at each angle from them
  crossing: Object.fromEntries([0, 30, 39, 41, 60, 90, 180].map((deg) => {
    const a = (deg * Math.PI) / 180;
    return [deg, crossingOnly(0, 0, 1.5 * Math.cos(a), 1.5 * Math.sin(a), 1, 0)];
  })),
  stopped: [crossingOnly(0, 0, 0, 0, 1, 0), crossingOnly(0, 0, 0, 0.1, 1, 0), crossingOnly(0, 0, 0, 1.5, 1, 0)],
}));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LeadSpotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT], capture_output=True, text=True, timeout=60)
        if out.returncode:
            raise AssertionError(out.stderr)
        cls.r = json.loads(out.stdout)

    def test_out_of_the_doorway(self):
        s = self.r["studio"]
        self.assertIsNotNone(s)
        # Not in a doorway, inside or out, and neither is the ring you stand on to talk to them.
        self.assertGreaterEqual(s["leadDoor"], 1.6, s)
        self.assertGreaterEqual(s["standDoor"], 1.1, s)
        # Not in the way out of the lift either: walking straight out never puts you on their ring.
        self.assertGreaterEqual(s["leadOffStraight"], 1.0, s)
        self.assertGreaterEqual(s["standOffStraight"], 0.6, s)
        # Never cutting anything off, and seen from the lift's doorstep, a few steps out.
        self.assertTrue(s["reachAll"], s)
        self.assertTrue(s["seen"], s)
        self.assertTrue(s["seesRing"], s)
        self.assertTrue(1.2 <= s["fromOut"] <= 5, s)
        self.assertTrue(0.9 <= s["talkGap"] <= 1.4, s)

    def test_people_walking_out_and_in_never_meet_them(self):
        # however people walk out of the lift and into the rooms, drifting or turning: never into the lead (0.35 m for
        # them and 0.22 m for the walker), and never starting a talk (on their ring, within 0.42 m, heading for them)
        for plan in ("studio", "lobby", "hall", "drawn"):
            w = self.r[plan]["walked"]
            self.assertGreater(w["count"], 10, plan)
            self.assertGreaterEqual(w["straight"], 1.07, (plan, self.r[plan]))  # straight out, half a metre either side
            self.assertGreaterEqual(w["lead"], 0.6, (plan, self.r[plan]))
            self.assertGreaterEqual(w["towards"], 0.45, (plan, self.r[plan]))  # no way in or out ever starts a talk
        # where there is room, nobody even crosses their ring
        for plan in ("studio", "lobby", "hall"):
            self.assertGreaterEqual(self.r[plan]["walked"]["ring"], 0.45, (plan, self.r[plan]))
            self.assertIn(self.r[plan]["eased"], (0, 1), plan)  # nothing eased but how much room they have

    def test_the_real_drawn_floor(self):
        # The drawn look's project floor: a passage 2.4 m wide out of the lift onto a long hall of rooms. Every spot
        # within 5 m is on some way people walk, so the lead stands across the hall, against its far wall, in sight
        # of the lift, and their ring may lie where people cross it, but only heading well away from them.
        s = self.r["drawn"]
        self.assertIsNotNone(s)
        self.assertGreater(s["lead"][1], 5.2, s)  # in the hall, not the passage (which ends at 5.2 m)
        self.assertGreaterEqual(s["leadDoor"], 1.6, s)
        self.assertGreaterEqual(s["standDoor"], 1.1, s)
        self.assertTrue(s["seen"] and s["seesRing"], s)
        self.assertTrue(1.2 <= s["fromOut"] <= 5, s)
        self.assertLessEqual(s["cutOff"], 2, s)
        self.assertLessEqual(s["eased"], 3, s)  # their own distance from the ways kept to at least half

    def test_a_ring_crossed_on_the_way_somewhere_else(self):
        # Walking across a lead's ring starts no talk unless heading for them within 40 degrees; standing on it,
        # or barely moving, does.
        c = self.r["crossing"]
        self.assertEqual(c, {"0": False, "30": False, "39": False, "41": True, "60": True, "90": True, "180": True})
        self.assertEqual(self.r["stopped"], [False, False, True])

    def test_clear_of_the_routes_too(self):
        s = self.r["routes"]
        self.assertIsNotNone(s)
        self.assertGreaterEqual(s["leadRoute"], 0.8, s)  # 0.6 from the edge of a route 0.2 either side
        self.assertGreaterEqual(s["standRoute"], 0.8, s)
        for plan in ("studio", "lobby", "hall"):
            self.assertGreaterEqual(self.r[plan]["leadRoute"], 0.8, plan)
            self.assertGreaterEqual(self.r[plan]["standRoute"], 0.8, plan)

    def test_doorstep_is_past_the_narrow_way_out(self):
        # The doorstep is where the narrow way out of the car opens into the corridor (rows 9 to 12), not in the car.
        x, z = self.r["studioDoorstep"]
        self.assertAlmostEqual(x, 3.9, places=1)
        self.assertTrue(1.8 <= z <= 2.6, z)

    def test_open_lobby_keeps_the_way_out_clear(self):
        s = self.r["lobby"]
        self.assertIsNotNone(s)
        self.assertGreaterEqual(s["leadOffStraight"], 1.0, s)
        self.assertGreaterEqual(s["standOffStraight"], 0.6, s)
        self.assertGreaterEqual(s["leadDoor"], 1.6, s)
        self.assertTrue(s["seen"] and s["reachAll"], s)

    def test_only_corridors_still_somewhere_and_nothing_cut_off(self):
        s = self.r["narrow"]
        self.assertIsNotNone(s)
        self.assertLessEqual(s["cutOff"], 2, s)
        self.assertGreaterEqual(s["leadDoor"], 0.7, s)  # never standing on a doorway, even here (their body, 0.7 m)
        for plan in ("studio", "lobby"):
            self.assertLessEqual(self.r[plan]["cutOff"], 2, plan)

    def test_nowhere_to_stand(self):
        self.assertIsNone(self.r["cupboard"])


if __name__ == "__main__":
    unittest.main()
