"""Your plan's limits and the forecast (connect/usage.py, src/usage.js): Claude Code's status line and Codex's
own record say how much is used and when it starts again; the readings are kept a few hours back; setup adds
the status line and keeps yours; and the page tells from the last hour's pace whether you reach a limit
before it starts again. The page's part is JavaScript and runs under Node, skipped where Node isn't there.
Each test works in a temporary folder.

Run from the repository's folder: python3 -m unittest discover tests
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connect"))

import setup  # noqa: E402
import usage  # noqa: E402

USAGE = os.path.join(ROOT, "connect", "usage.py")
CODEX = os.path.join(ROOT, "connect", "codex.py")
NODE = shutil.which("node")


class ReadingsTest(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.data = os.path.join(self.base, "data")
        self.env = dict(os.environ, ARNHEIM_DATA=self.data)

    def feed(self):
        with open(os.path.join(self.data, "feeds", "usage.json"), encoding="utf-8") as handle:
            return json.load(handle)["sources"]

    def test_both_agents_said_the_same_way(self):
        claude = usage.from_claude({"rate_limits": {"five_hour": {"used_percentage": 37.4, "resets_at": 1800000000},
                                                    "seven_day": {"used_percentage": 112, "resets_at": 1800300000}, "odd": "x"}})
        self.assertEqual(claude, {"five_hour": {"used": 37.4, "resets_at": 1800000000}, "seven_day": {"used": 100.0, "resets_at": 1800300000}})
        codex = usage.from_codex({"primary": {"used_percent": 20, "window_minutes": 300, "resets_in_seconds": 600},
                                  "secondary": {"used_percent": 5, "window_minutes": 10080, "resets_at": 1800300000}}, now=1000)
        self.assertEqual(codex, {"five_hour": {"used": 20.0, "resets_at": 1600}, "seven_day": {"used": 5.0, "resets_at": 1800300000}})
        self.assertEqual(usage.from_claude({}), {})
        self.assertEqual(usage.from_codex(None), {})

    def test_kept_once_a_minute_unless_it_changes(self):
        reading = {"five_hour": {"used": 30, "resets_at": 5000}}
        self.assertTrue(usage.keep("Claude Code", reading, self.data, now=1000))
        self.assertFalse(usage.keep("Claude Code", reading, self.data, now=1030))  # the same, too soon
        self.assertTrue(usage.keep("Claude Code", {"five_hour": {"used": 31, "resets_at": 5000}}, self.data, now=1040))
        self.assertTrue(usage.keep("Claude Code", {"five_hour": {"used": 31, "resets_at": 5000}}, self.data, now=1200))
        self.assertTrue(usage.keep("Claude Code", reading, self.data, now=1000 + usage.KEEP + 100))  # the old ones go
        self.assertEqual([r["at"] for r in self.feed()["Claude Code"]["five_hour"]], [1200, 1000 + usage.KEEP + 100])

    def test_the_status_line_notes_and_shows_yours(self):
        given = json.dumps({"model": {"id": "x"}, "rate_limits": {"five_hour": {"used_percentage": 42, "resets_at": time.time() + 3600}}})
        done = subprocess.run([sys.executable, USAGE], input=given, capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual((done.returncode, done.stdout), (0, "Arnheim · 5h 42%"))
        self.assertEqual(self.feed()["Claude Code"]["five_hour"][-1]["used"], 42)
        done = subprocess.run([sys.executable, USAGE, "--then", "cat | wc -c | tr -d ' '"], input=given, capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual(done.stdout.strip(), str(len(given)))  # yours, handed the same, shows as it did
        done = subprocess.run([sys.executable, USAGE], input="not json", capture_output=True, text=True, env=self.env, timeout=30)
        self.assertEqual((done.returncode, done.stdout), (0, "Arnheim"))  # never troubles Claude Code

    def test_codex_says_it_in_its_own_record(self):
        lantern = os.path.join(self.base, "lantern")
        os.makedirs(lantern)
        os.makedirs(self.data, exist_ok=True)
        with open(os.path.join(self.data, "company.json"), "w") as handle:
            json.dump({"company": "X", "floors": [{"id": "lantern", "label": "Lantern", "folder": lantern}], "feeds": ["feeds/claude-code.json"]}, handle)
        record = os.path.join(self.base, "rollout.jsonl")
        with open(record, "w") as handle:
            handle.write(json.dumps({"timestamp": "2026-11-17T10:00:00Z", "type": "event_msg", "payload": {"type": "token_count", "info": None,
                                     "rate_limits": {"primary": {"used_percent": 33, "window_minutes": 300, "resets_in_seconds": 5000}}}}) + "\n")
        event = {"hook_event_name": "Stop", "session_id": "c-1", "cwd": lantern, "transcript_path": record, "last_assistant_message": "Done."}
        subprocess.run([sys.executable, CODEX], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=30, check=True)
        self.assertEqual(self.feed()["Codex"]["five_hour"][-1]["used"], 33)


class StatusLineSetupTest(unittest.TestCase):
    def test_added_wrapped_and_put_back(self):
        out, did = setup.plan_status({})
        self.assertEqual(did, "added")
        self.assertTrue(out["statusLine"]["command"].endswith("connect/usage.py"))
        self.assertEqual(setup.plan_status(out), (None, None))  # already there
        back, changed = setup.take_out_status(out)
        self.assertTrue(changed)
        self.assertNotIn("statusLine", back)

        mine = {"model": "opus", "statusLine": {"type": "command", "command": "~/bin/my status --short 'it''s'", "padding": 0}}
        out, did = setup.plan_status(mine)
        self.assertEqual(did, "wrapped")
        self.assertEqual(out["statusLine"]["padding"], 0)
        self.assertIn("--then", out["statusLine"]["command"])
        back, changed = setup.take_out_status(out)
        self.assertEqual(back, mine)  # exactly as it was

        self.assertEqual(setup.plan_status({"statusLine": {"type": "static", "text": "hi"}}), (None, "left"))


FORECAST = """
import { pathToFileURL } from 'node:url';
const u = await import(pathToFileURL(process.argv[1] + '/src/usage.js').href);
const now = 1800000000;
const rows = (pairs, resets) => pairs.map(([ago, used]) => ({ at: now - ago, used, resets_at: resets }));
const one = (rows, extra = {}) => u.forecastOf({ sources: { 'Claude Code': { five_hour: rows, ...extra } } }, now);
const out = {
  rising: one(rows([[3600, 40], [1800, 51], [60, 62]], now + 7200))[0],
  lasting: one(rows([[3600, 40], [60, 45]], now + 3600))[0],
  flat: one(rows([[3600, 40], [60, 40]], now + 3600))[0],
  usedUp: one(rows([[600, 99], [60, 100]], now + 900))[0],
  tooFew: one(rows([[60, 50]], now + 900))[0],
  stale: one(rows([[8 * 3600, 50]], now + 900)),
  restarted: one(rows([[3600, 90], [60, 95]], now - 10)),
  newWindow: one([...rows([[3000, 90]], now - 600), ...rows([[1200, 2], [60, 4]], now + 4 * 3600)])[0],
  order: u.forecastOf({ sources: { 'Claude Code': { seven_day: rows([[3600, 10], [60, 11]], now + 5 * 86400) },
                                   'Codex': { five_hour: rows([[3600, 10], [60, 70]], now + 7200) } } }, now).map((f) => f.source),
  junk: u.forecastOf({ sources: { x: 'no', y: { five_hour: [null, { at: 'x' }] } } }, now),
  week: u.forecastOf({ sources: { c: { seven_day: rows([[3600, 29], [60, 31]], now + 3 * 86400) } } }, now)[0],
  weekBusy: u.forecastOf({ sources: { c: { seven_day: rows([[3600, 70], [60, 72]], now + 3 * 86400) } } }, now)[0],
  firstReading: one(rows([[60, 30]], now + 3 * 3600))[0],
};
out.words = [out.rising, out.lasting, out.usedUp, out.tooFew].map((f) => u.usageWords(f, now));
out.pressing = [u.pressing([out.rising]), u.pressing([out.lasting])];
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ForecastTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run([NODE, "--input-type=module", "-e", FORECAST, ROOT], capture_output=True, text=True, timeout=60,
                              env=dict(os.environ, TZ="UTC"))
        if done.returncode:
            raise AssertionError(done.stderr)
        cls.r = json.loads(done.stdout)

    def test_the_last_hours_pace(self):
        r = self.r
        self.assertEqual(r["rising"]["reaches"], "before")  # 22 points an hour: 38 left goes in about 1.7 hours, inside 2
        self.assertAlmostEqual(r["rising"]["reachAt"] - (1800000000 - 60), 38 / (22 / 3540), delta=1)
        self.assertEqual(r["lasting"]["reaches"], "after")
        self.assertEqual(r["flat"]["reaches"], "after")
        self.assertEqual(r["usedUp"]["reaches"], "now")
        self.assertEqual(r["tooFew"]["reaches"], "after")  # one reading, 4h44 into its window: 50% then, and 15 minutes left
        self.assertEqual((r["stale"], r["restarted"], r["junk"]), ([], [], []))
        self.assertEqual((r["newWindow"]["used"], r["newWindow"]["reaches"]), (4, "after"))  # only the readings since it started again
        self.assertEqual(r["order"], ["Codex", "Claude Code"])  # the one you'd reach first comes first
        self.assertEqual(r["pressing"], [True, False])
        # a week goes by its average since it began: 31% in 4 days lasts the 3 left, a busy hour or not
        self.assertEqual(r["week"]["reaches"], "after")
        self.assertEqual(r["weekBusy"]["reaches"], "before")  # 72% in 4 days doesn't
        # one reading of a 5-hour limit two hours in: its average pace says it lasts (30% in 2 hours: 100% in 6.7)
        self.assertEqual(r["firstReading"]["reaches"], "after")

    def test_in_words(self):
        rising, lasting, used_up, too_few = self.r["words"]
        self.assertTrue(rising.startswith("Claude Code: 62% of the 5-hour limit is used. At this pace you reach it around "), rising)
        self.assertIn("before it starts again at", rising)
        self.assertIn("lasts until it starts again", lasting)
        self.assertTrue(used_up.startswith("Claude Code's 5-hour limit is used up. It starts again at"), used_up)
        self.assertIn("starts again", too_few)


if __name__ == "__main__":
    unittest.main()
