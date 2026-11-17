"""Cutting in by talking (src/cut-in.js): while someone in the building speaks, the microphone hears their own
voice back from the speakers. Talking over them stops them, even after talking as they started; their own echo,
however it rises and falls (a soft voice then a loud one, a quiet start, the volume turned up, speakers a long way
behind), never does. Fed sound
levels made up here, a block every 10 ms, with how loud what is played is, as voice.js feeds it.

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
const { createCutIn } = await import(pathToFileURL(process.argv[1] + '/src/cut-in.js').href);
const BLOCK = 0.01;
// a little noise, seeded so it is the same each run
let seed = 7;
const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
// a made-up voice: syllables about every 0.2 s, loud in the middle
const syllables = (t, level) => level - 18 * (1 - Math.sin(Math.PI * ((t * 5) % 1)));
const add = (a, b) => 10 * Math.log10(10 ** (a / 10) + 10 ** (b / 10)); // two sounds together: their powers add
// They speak for `seconds`: `level(t)` is how loud what is played is, after `lead` seconds of silence; the
// microphone hears it back `latency` seconds later, `ratio(t)` decibels softer, over the quiet room. you(t): your
// own level at t, or null. Returns when, in seconds, it first says you cut in; null if never.
function run({ seconds = 10, level = () => -16, ratio = () => -26, latency = 0.08, lead = 0, you = () => null, room = -62 } = {}) {
  const cut = createCutIn();
  const played = (t) => (t < lead ? -120 : syllables(t, level(t)));
  for (let i = 0; i * BLOCK < seconds; i++) {
    const t = i * BLOCK;
    const back = t - latency;
    const theirs = back < lead ? room : add(room, played(back) + ratio(t) + (rand() - 0.5) * 4);
    const mine = you(t);
    if (cut.hear(mine == null ? theirs : add(theirs, mine), BLOCK, room, played(t))) return Math.round(t * 1000) / 1000;
  }
  return null;
}
const yours = (from, level, to = Infinity) => (t) => (t >= from && t < to ? syllables(t + 0.05, level) : null);
const out = {
  // their echo alone, soft, loud, very loud: never
  echoSoft: run({ ratio: () => -40 }), echoLoud: run({ ratio: () => -20 }), echoVeryLoud: run({ ratio: () => -6, seconds: 30 }),
  // louder and softer sentences
  echoSwings: run({ level: (t) => -16 + 8 * Math.sin((2 * Math.PI * t) / 2), seconds: 30 }),
  // a soft voice, then a much louder one (the round: one person, then the next): never
  softThenLoud: run({ level: (t) => (t < 1.5 ? -36 : -10), lead: 0.15, ratio: () => -20 }),
  // a quiet start to a loud answer
  quietStart: run({ level: (t) => (t < 0.6 ? -40 : -12), lead: 0.2 }),
  // one sharp loud syllable of theirs, 0.15 s, 14 dB over the rest: never
  spike: run({ level: (t) => (t > 4 && t < 4.15 ? -2 : -16) }),
  // speakers a long way behind (a wireless speaker): never
  late: run({ latency: 0.3, ratio: () => -16 }),
  // the volume turned up mid-answer
  louder: run({ ratio: (t) => (t < 5 ? -26 : -20) }),
  // you, speaking normally over their echo from 3 s: soon
  you: run({ you: yours(3, -24) }),
  // you, over a loud echo
  youOverLoud: run({ ratio: () => -20, you: yours(3, -18) }),
  // you, over the soft first voice of two
  youOverSoft: run({ level: (t) => (t < 4 ? -36 : -10), lead: 0.15, ratio: () => -20, you: yours(2, -26) }),
  // one firm short word, "stop", about a third of a second
  word: run({ you: yours(3, -20, 3.35) }),
  // a whisper, barely over their echo: not taken for cutting in
  whisper: run({ you: yours(3, -40) }),
  // a cough: loud, but too short
  cough: run({ you: (t) => (t > 5 && t < 5.18 ? -15 : null) }),
  // you talked as they started ("no, wait"), then again later: the second time still cuts in
  early: run({ you: (t) => (t < 0.35 ? syllables(t + 0.05, -20) : t >= 3 ? syllables(t + 0.05, -24) : null) }),
  // the echo falls away for a while (the browser's echo cancelling settling), then comes back: never
  settles: run({ ratio: (t) => (t < 3 ? -20 : t < 6 ? -30 : -20) }),
  // loud at first, then held at the room's level for two seconds, then leaking back as loud: never
  leaks: run({ ratio: (t) => (t < 1 ? -20 : t < 3 ? -70 : -20) }),
  // the volume turned well down for a while, then up past where it was: never
  volume: run({ ratio: (t) => (t < 4 ? -26 : t < 6 ? -38 : -16) }),
  // nothing known of what is played: it never guesses
  blind: (() => { const c = createCutIn(); for (let i = 0; i < 300; i++) if (c.hear(i < 100 ? -40 : -15, BLOCK, -62)) return i; return null; })(),
};
const again = createCutIn();
for (let i = 0; i < 100; i++) again.hear(-20, BLOCK, -62, -16); // learned a loud echo
again.reset();
let t = 0;
for (; t < 3; t += BLOCK) if (again.hear(t < 0.5 ? -56 : -30, BLOCK, -62, -16)) break; // a soft one this time, then you
out.afterReset = Math.round(t * 100) / 100; // a new answer learns its own echo, not the last one's
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class CutInTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT], capture_output=True, text=True, timeout=60)
        if out.returncode:
            raise AssertionError(out.stderr)
        cls.r = json.loads(out.stdout)

    def test_their_own_echo_never_stops_them(self):
        for name in ("echoSoft", "echoLoud", "echoVeryLoud", "echoSwings", "softThenLoud", "quietStart", "spike", "late", "louder", "settles", "leaks", "volume", "cough", "blind"):
            self.assertIsNone(self.r[name], name)

    def test_talking_over_them_stops_them_soon(self):
        for name, start in (("you", 3.0), ("youOverLoud", 3.0), ("youOverSoft", 2.0), ("early", 3.0)):
            when = self.r[name]
            self.assertIsNotNone(when, name)
            self.assertGreaterEqual(when, start, name)
            self.assertLess(when - start, 0.8, name)  # within one short word or two
        self.assertIsNotNone(self.r["word"])  # one firm word is enough

    def test_a_whisper_is_not_cutting_in(self):
        self.assertIsNone(self.r["whisper"])

    def test_each_answer_learns_its_own_echo(self):
        self.assertLess(self.r["afterReset"], 1.5)


if __name__ == "__main__":
    unittest.main()
