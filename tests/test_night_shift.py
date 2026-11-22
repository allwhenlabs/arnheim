"""The night shift (connect/night.py): during the quiet hours, work you approved for it (a ready task ticked Tonight, an
approved item of the day's plan that didn't start) runs on allowance the forecast says would otherwise go unused. The
window with and without a forecast, the share and the margin, quiet hours across midnight, only what you approved,
the refusals, paused and over budget, one agent a floor, the brake, the proof, the morning report, Undo through
restore points, the switch, and the phone's way in through control. A stand-in for Claude Code's `claude` command
answers for real agents, and the page's words (src/night.js) and the front door's "tonight" run under Node.

Each test makes a company of its own in a temporary folder, so your data/ is never touched.
Run from the repository's folder: python3 -m unittest discover tests
"""
import datetime
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

import control  # noqa: E402  (after the path is set)
import day  # noqa: E402
import night  # noqa: E402
import restore  # noqa: E402
import usage  # noqa: E402

NODE = shutil.which("node")
HOUR = 3600

# Stands in for `claude -p`: says the words back, tells its plan's limits when limits.json is beside it, and stays at
# work while a file named "hold" is beside it. It notes the git settings it was started with. Started as the night
# shift's probe (no session kept), it tells the limits in probe_limits.json, if any, and notes the probe; started as
# Codex is (`exec`), it only notes the start.
FAKE = r'''
import json, os, sys, time
args = sys.argv[1:]
here = os.path.dirname(os.path.abspath(__file__))
seen = {k: v for k, v in os.environ.items() if k.startswith("GIT_CONFIG")}
if "--no-session-persistence" in args:
    with open(os.path.join(here, "probes.log"), "a") as log:
        log.write(json.dumps({"cwd": os.getcwd(), "args": args}) + "\n")
    limits = os.path.join(here, "probe_limits.json")
    if os.path.exists(limits):
        with open(limits) as handle:
            print(json.dumps({"type": "rate_limit_event", "rate_limit_info": json.load(handle)}), flush=True)
    print(json.dumps({"type": "result", "result": "ok"}), flush=True)
    sys.exit(0)
words = sys.stdin.read()
if "exec" in args:
    with open(os.path.join(here, "started.log"), "a") as log:
        log.write(json.dumps({"cwd": os.getcwd(), "words": words, "agent": "Codex", "env": seen}) + "\n")
    sys.exit(0)
sid = args[args.index("--resume" if "--resume" in args else "--session-id") + 1]
hold = os.path.join(here, "hold")
with open(os.path.join(here, "started.log"), "a") as log:
    log.write(json.dumps({"cwd": os.getcwd(), "words": words, "env": seen}) + "\n")
print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}), flush=True)
limits = os.path.join(here, "limits.json")
if os.path.exists(limits):
    with open(limits) as handle:
        print(json.dumps({"type": "rate_limit_event", "rate_limit_info": json.load(handle), "session_id": sid}), flush=True)
until = time.time() + 20
while os.path.exists(hold) and time.time() < until:
    time.sleep(0.05)
print(json.dumps({"type": "result", "result": "Done: " + words[:40], "session_id": sid}), flush=True)
'''


def git(folder, *args):
    return subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, check=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git isn't installed")
class NightShiftTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.data = os.path.join(self.base, "data")
        self.lantern = os.path.realpath(os.path.join(self.base, "code", "lantern"))
        self.tidepool = os.path.realpath(os.path.join(self.base, "code", "tidepool"))
        for folder in (self.data, self.lantern, self.tidepool, os.path.join(self.data, "feeds")):
            os.makedirs(folder, exist_ok=True)
        for folder in (self.lantern, self.tidepool):
            git(folder, "init", "-q")
            for name, value in (("user.name", "Someone"), ("user.email", "someone@example.com"), ("commit.gpgsign", "false")):
                git(folder, "config", name, value)
            with open(os.path.join(folder, "app.py"), "w", encoding="utf-8") as handle:
                handle.write("print('one')\n")
            git(folder, "add", "-A")
            git(folder, "commit", "-qm", "first")
        self.company = {
            "company": "Example Studio",
            "floors": [
                {"id": "lantern", "label": "Lantern", "project": "Lantern", "folder": self.lantern, "lead": {"name": "Juno"}},
                {"id": "tidepool", "label": "Tidepool", "project": "Tidepool", "folder": self.tidepool},
            ],
            "feeds": ["feeds/claude-code.json"],
        }
        self.save("company.json", self.company)
        self.feed([])
        self.now = time.time()
        self.quiet_around()
        fake = os.path.join(self.base, "fake_claude.py")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE)
        self.fake = [sys.executable, fake]
        self.control = control.Control(self.data, claude=self.fake)
        night._LAST.clear()
        day._LAST.clear()

    def tearDown(self):
        self.release()
        for run in list(self.control.runs.values()):
            proc = self.control.procs.get(run["key"])
            if proc is not None:
                proc.wait(timeout=30)
        time.sleep(0.05)
        shutil.rmtree(self.base, ignore_errors=True)

    # ---------- helpers ----------

    def save(self, name, doc):
        path = os.path.join(self.data, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)

    def feed(self, conversations):
        self.save(os.path.join("feeds", "claude-code.json"), {"conversations": conversations})

    def quiet_around(self, before=HOUR, after=2 * HOUR, **more):
        """Quiet hours that began `before` seconds ago and end in `after`, with the switch on."""
        clock = lambda t: datetime.datetime.fromtimestamp(t).strftime("%H:%M")  # noqa: E731
        self.save("serve.json", {"night": True, "night_from": clock(self.now - before), "night_to": clock(self.now + after), **more})

    def limits(self, used=60, resets_in=HOUR, five=None, at=None, source="Claude Code", rows=None):
        """A weekly reading (and a 5-hour one) as connect/usage.py keeps them."""
        at = self.now - 60 if at is None else at
        windows = {"seven_day": rows or [{"at": at, "used": used, "resets_at": self.now + resets_in}]}
        if five is not None:
            windows["five_hour"] = [{"at": at, "used": five, "resets_at": self.now + HOUR}]
        feed = {"sources": {source: windows}}
        old = os.path.join(self.data, "feeds", "usage.json")
        if os.path.exists(old) and source != "Claude Code":
            with open(old, encoding="utf-8") as handle:
                feed["sources"].update({k: v for k, v in json.load(handle)["sources"].items() if k != source})
        self.save(os.path.join("feeds", "usage.json"), feed)

    def hold(self):
        open(os.path.join(self.base, "hold"), "w").close()

    def release(self):
        try:
            os.remove(os.path.join(self.base, "hold"))
        except OSError:
            pass

    def call(self, name, body=None):
        code, _, raw, _ = self.control.handle("POST", name, json.dumps(body or {}).encode(), self.control.token)
        return code, json.loads(raw)

    def ready(self, text, floor="Tidepool"):
        code, got = self.call("intake", {"text": text, "floor": floor, "via": "box"})
        self.assertEqual(code, 200, got)
        return got["task"]["id"]

    def tick_tonight(self, rid, on=True):
        return self.call("night_tick", {"id": rid, "tonight": on})

    def started(self):
        try:
            with open(os.path.join(self.base, "started.log"), encoding="utf-8") as handle:
                return [json.loads(line) for line in handle if line.strip()]
        except OSError:
            return []

    def wait_done(self, most=15):
        until = time.time() + most
        while time.time() < until:
            if not any(self.control.alive(r) for r in list(self.control.runs.values())):
                return
            time.sleep(0.05)
        self.fail("the stand-in agents didn't finish")

    def tonight(self):
        return night.load(self.data, night.span(night.settings(self.data)["quiet"], self.now)["night"])

    def plan(self, items, floor="Lantern", approved=True, date=None):
        date = date or day.today(self.now)
        rows = [{"id": f"d-{i:08x}", "title": t, "text": t + ".", "why": "An open task on this floor.", "source": "task",
                 "state": "approved" if approved else "proposed"} for i, t in enumerate(items, 1)]
        self.save(os.path.join("day", date + ".json"), {"date": date, "made": self.now - 9 * HOUR,
                                                         "plan": [{"floor": floor, "label": floor, "approved": approved, "items": rows}]})

    # ---------- the window: what would go unused ----------

    def test_with_no_forecast_it_runs_nothing_and_says_why(self):
        rid = self.ready("tidy the field notes on Tidepool")
        self.assertEqual(self.tick_tonight(rid)[0], 200)
        win = night.window(self.data, self.now)
        self.assertFalse(win["known"])
        self.assertIn("No forecast", win["words"])
        self.assertEqual(night.tick(self.data, self.control, self.now), [])
        self.assertEqual(self.started(), [])
        self.assertIn("No forecast", self.tonight()["said"])
        # a reading older than six hours is no forecast either
        self.limits(at=self.now - 7 * HOUR)
        self.assertFalse(night.window(self.data, self.now)["known"])

    def test_a_week_that_starts_again_before_you_are_back(self):
        self.limits(used=60, resets_in=HOUR)  # quiet hours end in two
        a = night.window(self.data, self.now)["agents"]["Claude Code"]
        self.assertTrue(a["open"])
        self.assertEqual((a["lost"], a["room"]), (40, 30))  # 80% of 40 is 32, but never past 90: 30
        self.assertIn("before you're back", a["words"])
        self.assertIn("40% unused", a["words"])

    def test_the_pace_decides_when_the_week_ends_after_you_are_back(self):
        # 40% used four days into the week: 10% a day, so about 70% by its end in three days, 30% unused
        rows = [{"at": self.now - 60, "used": 40, "resets_at": self.now + 3 * 86400}]
        self.limits(rows=rows)
        a = night.window(self.data, self.now)["agents"]["Claude Code"]
        self.assertTrue(a["open"])
        self.assertAlmostEqual(a["lost"], 30, delta=0.5)
        self.assertAlmostEqual(a["room"], 24, delta=0.5)
        self.assertIn("would be left unused", a["words"])
        # at a pace that uses it all, nothing would go unused, and nothing runs
        rows = [{"at": self.now - 60, "used": 80, "resets_at": self.now + 3 * 86400}]
        self.limits(rows=rows)
        a = night.window(self.data, self.now)["agents"]["Claude Code"]
        self.assertFalse(a["open"])
        self.assertIn("none would go unused", a["words"])

    def test_the_share_and_the_margin(self):
        self.quiet_around(night_share=50)
        self.limits(used=60, resets_in=HOUR)
        self.assertEqual(night.window(self.data, self.now)["agents"]["Claude Code"]["room"], 20)  # half of 40
        self.quiet_around()
        self.limits(used=85, resets_in=HOUR)
        self.assertEqual(night.window(self.data, self.now)["agents"]["Claude Code"]["room"], 5)  # never past 90
        self.limits(used=88, resets_in=HOUR)
        a = night.window(self.data, self.now)["agents"]["Claude Code"]
        self.assertFalse(a["open"])  # 2 points is too little
        self.assertIn("too little", a["words"])
        self.limits(used=50, resets_in=HOUR, five=92)  # a 5-hour limit close to its end holds it too
        a = night.window(self.data, self.now)["agents"]["Claude Code"]
        self.assertFalse(a["open"])
        self.assertIn("5-hour limit", a["words"])
        code, got = self.call("night_set", {"share": 5})
        self.assertEqual(code, 400)
        code, got = self.call("night_set", {"share": 70, "quiet": {"from": "22:30", "to": "06:00"}})
        self.assertEqual(code, 200, got)
        self.assertEqual(night.settings(self.data), {"quiet": {"from": "22:30", "to": "06:00"}, "share": 70})

    def test_quiet_hours_across_midnight_and_within_a_day(self):
        at = lambda d, hm: datetime.datetime.combine(d, datetime.time(*hm)).timestamp()  # noqa: E731
        d = datetime.date(2026, 11, 21)
        nights = {"from": "23:00", "to": "07:00"}
        evening = night.span(nights, at(d, (22, 0)))
        self.assertFalse(evening["in"])
        self.assertEqual((evening["began"], evening["ends"]), (at(d, (23, 0)), at(d + datetime.timedelta(days=1), (7, 0))))
        late = night.span(nights, at(d, (23, 30)))
        self.assertTrue(late["in"])
        self.assertEqual(late["night"], "2026-11-21")
        small = night.span(nights, at(d, (3, 0)))
        self.assertTrue(small["in"])
        self.assertEqual(small["night"], "2026-11-20")  # the evening it began
        self.assertEqual(small["ends"], at(d, (7, 0)))
        self.assertFalse(night.span(nights, at(d, (7, 0)))["in"])
        self.assertFalse(night.span(nights, at(d, (8, 0)))["in"])
        early = {"from": "01:00", "to": "06:00"}
        self.assertFalse(night.span(early, at(d, (0, 30)))["in"])
        self.assertTrue(night.span(early, at(d, (3, 0)))["in"])
        self.assertEqual(night.span(early, at(d, (7, 0)))["began"], at(d + datetime.timedelta(days=1), (1, 0)))
        for bad in ({"from": "23:00", "to": "23:00"}, {"from": "25:00", "to": "07:00"}, "soon"):
            with self.assertRaises(night.Refused):
                night.save_settings(self.data, quiet=bad)
        self.assertEqual(night.save_settings(self.data, quiet="22:00-06:30")["quiet"], {"from": "22:00", "to": "06:30"})

    # ---------- only what you approved ----------

    def test_only_ticked_ready_tasks_and_approved_plan_items_run(self):
        self.quiet_around(daily_cycle=True)
        self.limits(used=40, resets_in=HOUR)
        ticked = self.ready("tidy the field notes on Tidepool")
        self.ready("sort the bookmarks on Tidepool")  # ready, but not ticked
        code, got = self.tick_tonight(ticked)
        self.assertEqual(code, 200, got)
        self.assertIn("Ticked for tonight", got["said"])
        self.assertEqual(got["night"]["ticked"], [ticked])
        self.plan(["Write the notes for version 2"], floor="Lantern")
        self.plan(["Not approved"], floor="Lantern", approved=False, date=(datetime.date.fromtimestamp(self.now) - datetime.timedelta(days=1)).isoformat())
        did = night.tick(self.data, self.control, self.now)
        self.assertEqual(len(did), 2, did)
        self.wait_done()
        words = [s["words"] for s in self.started()]
        self.assertEqual(len(words), 2)
        self.assertTrue(any("tidy the field notes" in w.lower() for w in words))
        self.assertTrue(any("write the notes for version 2" in w.lower() for w in words))
        self.assertFalse(any("bookmarks" in w.lower() or "not approved" in w.lower() for w in words))
        for w in words:  # told it is the night shift, and never to push or publish
            self.assertIn("night shift", w)
            self.assertIn("Never push, publish", w)
        doc = self.tonight()
        self.assertEqual(sorted(r["kind"] for r in doc["ran"]), ["day", "ready"])
        item = day.load(self.data, day.today(self.now))["plan"][0]["items"][0]
        self.assertEqual((item["state"], item["how"]), ("started", "night shift"))
        self.assertTrue(item["ready"])  # made a ready task once, through the front door
        task = self.control.intake.task(ticked)
        self.assertIn(task["state"], ("started", "finished"))
        self.assertNotIn("night shift", task.get("note") or "")  # the card keeps its own words
        self.assertEqual(night.ticks(self.data), {})  # its tick is spent

    def test_untick_and_what_it_refuses(self):
        rid = self.ready("tidy the field notes on Tidepool")
        self.assertEqual(self.tick_tonight(rid)[0], 200)
        code, got = self.tick_tonight(rid, False)
        self.assertEqual(code, 200)
        self.assertIn("Not tonight", got["said"])
        self.assertEqual(night.ticks(self.data), {})
        for words, why in (("push the new release to the store on Tidepool", "push"),
                           ("delete the old field logs on Tidepool", "delet"),
                           ("decide whether the sensor page needs a map on Tidepool", "decision"),
                           ("update the password field on the sign up form on Tidepool", "password")):
            rid = self.ready(words)
            code, got = self.tick_tonight(rid)
            self.assertEqual(code, 400, words)
            self.assertIn("leaves", got["error"])
            self.assertIn(why, got["error"].lower(), words)
        self.assertEqual(night.ticks(self.data), {})
        code, got = self.tick_tonight("rd-0000000000")
        self.assertEqual(code, 400)

    def test_a_plan_item_it_refuses_waits_for_you(self):
        self.quiet_around(daily_cycle=True)
        self.limits(used=40, resets_in=HOUR)
        self.plan(["Deploy the new site", "Should we switch to tabs?"], floor="Lantern")
        v = night.view(self.data, self.control, self.now)
        self.assertEqual(len(v["queued"]), 2)
        self.assertTrue(all(e["why"] for e in v["queued"]))
        self.assertEqual(night.tick(self.data, self.control, self.now), [])
        self.assertEqual(self.started(), [])
        self.assertIn("waits for you", self.tonight()["said"])

    def test_day_items_wait_for_the_night_shift_in_its_quiet_hours(self):
        self.quiet_around(daily_cycle=True)
        self.plan(["Write the notes for version 2"], floor="Lantern")
        self.assertEqual(day.step(self.data, self.control, self.now), [])  # the daily cycle leaves it to the night shift
        item = day.load(self.data, day.today(self.now))["plan"][0]["items"][0]
        self.assertEqual(item["state"], "approved")
        self.assertIn("night shift", item["waiting"])
        self.quiet_around(before=-HOUR, after=2 * HOUR, daily_cycle=True)  # quiet hours start in an hour: the day goes on
        self.assertEqual(len(day.step(self.data, self.control, self.now)), 1)

    # ---------- paused, over budget, one a floor ----------

    def test_never_while_paused_or_over_budget(self):
        self.limits(used=40, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        self.control.box.pause()
        self.assertEqual(night.tick(self.data, self.control, self.now), [])
        self.assertIn("paused", self.tonight()["said"])
        self.control.box.resume()
        self.company["floors"][1]["budget"] = 1000
        self.save("company.json", self.company)
        self.feed([{"id": "cc-aaaaaaaaaaaa", "project": "Tidepool", "spent": {"day": day.budget.local_day(), "tokens": 5000}}])
        self.assertEqual(night.tick(self.data, self.control, self.now), [])
        self.assertIn("over today's budget", self.tonight()["said"])
        self.assertEqual(self.started(), [])
        self.assertEqual(self.control.intake.task(rid)["state"], "ready")  # never queued at the front door

    def test_one_agent_a_floor_and_a_fresh_reading_before_the_next(self):
        self.limits(used=40, resets_in=HOUR)
        first = self.ready("tidy the field notes on Tidepool")
        second = self.ready("sort the readings by day on Tidepool")
        other = self.ready("tidy the reading list on Lantern", floor="Lantern")
        for rid in (first, second, other):
            self.assertEqual(self.tick_tonight(rid)[0], 200)
        self.hold()
        did = night.tick(self.data, self.control, self.now)
        self.assertEqual(len(did), 2, did)  # Tidepool's first and Lantern's: one a floor
        self.assertEqual(self.control.intake.task(second)["state"], "ready")
        night._LAST.clear()
        self.assertEqual(night.tick(self.data, self.control, self.now + 30), [])  # Tidepool is at work
        self.release()
        self.wait_done()
        self.assertEqual(night.tick(self.data, self.control, self.now + 60), [])  # no reading since the last began
        self.assertIn("Waiting for Claude Code", self.tonight()["said"])
        self.limits(used=45, resets_in=HOUR, at=self.now + 70)
        did = night.tick(self.data, self.control, self.now + 90)
        self.assertEqual(len(did), 1, did)
        self.assertIn("sort the readings", did[0].lower())

    def test_a_plan_item_that_waits_for_your_look_on_show_me_waits_at_night_too(self):
        # Found by the Checker: the docs say work Show me asks you about first isn't done until your Looks good, plan
        # items the night shift runs included, but the night marked its plan item done as the run ended, and started the
        # floor's next work while your look still waited.
        self.quiet_around(daily_cycle=True)
        self.limits(used=40, resets_in=HOUR)
        self.plan(["Write the notes for version 2", "Tidy the changelog"], floor="Lantern")
        did = night.tick(self.data, self.control, self.now)
        self.assertEqual(len(did), 1, did)
        self.wait_done()
        key = self.tonight()["ran"][0]["key"]
        # Show me asks you first about this kind of change (tests/test_learning.py sets that up for real): Control marks
        # the run so, and says whether its finished work still waits for your look
        held = {"on": True}
        self.control.runs[key]["look"] = {"rule": "a-rule", "since": self.now}
        self.control.awaiting_look = lambda run: held["on"] and (run if isinstance(run, str) else (run or {}).get("key")) == key
        item = lambda n: day.load(self.data, day.today(self.now))["plan"][0]["items"][n]  # noqa: E731
        night._LAST.clear()
        night.tick(self.data, self.control, self.now + 30)
        r = self.tonight()["ran"][0]
        self.assertEqual((r["state"], r.get("item_waits")), ("done", True))
        self.assertEqual(item(0)["state"], "started")  # not counted done while your look waits
        self.assertIn("waits for you to look at it on Show me", night.busy(self.data, self.control, "Lantern", self.tonight(), {}))
        self.limits(used=45, resets_in=HOUR, at=self.now + 40)  # a fresh reading: only the hold keeps the next from starting
        night._LAST.clear()
        self.assertEqual(night.tick(self.data, self.control, self.now + 60), [])
        self.assertEqual(item(1)["state"], "approved")
        # Looks good: the item is done, and the floor may take the next
        held["on"] = False
        self.assertIsNone(night.busy(self.data, self.control, "Lantern", self.tonight(), {}))
        night._LAST.clear()
        night.tick(self.data, self.control, self.now + 90)
        self.assertEqual(item(0)["state"], "done")
        self.assertNotIn("item_waits", self.tonight()["ran"][0])

    def held_night_item(self):
        """A plan item the night shift ran, whose finished work waits for your look on Show me (stood in for, as above):
        gives its run's key, the hold (on while your look waits), and the plan's items."""
        self.quiet_around(daily_cycle=True)
        self.limits(used=40, resets_in=HOUR)
        self.plan(["Write the notes for version 2", "Tidy the changelog"], floor="Lantern")
        self.assertEqual(len(night.tick(self.data, self.control, self.now)), 1)
        self.wait_done()
        key = self.tonight()["ran"][0]["key"]
        held = {"on": True}
        self.control.runs[key]["look"] = {"rule": "a-rule", "since": self.now}
        self.control.awaiting_look = lambda run: held["on"] and (run if isinstance(run, str) else (run or {}).get("key")) == key
        night._LAST.clear()
        night.tick(self.data, self.control, self.now + 30)
        self.assertTrue(self.tonight()["ran"][0].get("item_waits"))
        return key, held, lambda n: day.load(self.data, day.today(self.now))["plan"][0]["items"][n]

    def test_not_quite_on_a_held_night_item_keeps_it_open_until_the_work_it_sent_back_is_looked_at(self):
        # Found by the Checker: after Not quite the same run is at work again and no longer waits for your look, so the
        # next tick marked its plan item done while the agent was still redoing it.
        key, held, item = self.held_night_item()
        self.hold()
        held["on"] = False  # Not quite: the card is answered, and the agent is sent back to work
        self.assertEqual(self.control.say(key, "The notes should say what changed")["sent"], "resumed")
        self.assertTrue(self.control.working(key))
        night._LAST.clear()
        night.tick(self.data, self.control, self.now + 60)
        self.assertEqual(item(0)["state"], "started")  # at work again: not done
        self.assertTrue(self.tonight()["ran"][0].get("item_waits"))
        self.release()
        self.wait_done()
        held["on"] = True  # its next finish waits for your look again
        night._LAST.clear()
        night.tick(self.data, self.control, self.now + 90)
        self.assertEqual(item(0)["state"], "started")
        held["on"] = False  # Looks good
        night._LAST.clear()
        night.tick(self.data, self.control, self.now + 120)
        self.assertEqual(item(0)["state"], "done")
        self.assertNotIn("item_waits", self.tonight()["ran"][0])

    def test_a_held_night_item_ends_as_the_work_it_was_sent_back_for_ended(self):
        # With the Checker's fix: the item is settled as the run last ended, not as it first did. Here you stop the
        # work Not quite sent it back for, so the item is stopped, not done.
        key, held, item = self.held_night_item()
        self.hold()
        held["on"] = False
        self.control.say(key, "The notes should say what changed")
        self.control.stop(key)
        self.wait_done()
        self.assertEqual(self.control.runs[key]["state"], "stopped")
        night._LAST.clear()
        night.tick(self.data, self.control, self.now + 60)
        self.assertEqual(item(0)["state"], "stopped")
        self.assertEqual(self.tonight()["ran"][0]["state"], "done")  # the night's report still says how its own run went

    def test_a_held_night_item_is_settled_on_a_tick_after_the_quiet_hours_end(self):
        # A test gap the Checker found: your Looks good after the quiet hours ended is seen by the next tick, which
        # settles last night's waiting items too.
        _, held, item = self.held_night_item()
        held["on"] = False
        later = self.now + 3 * HOUR  # the quiet hours ended an hour ago
        self.assertFalse(night.span(night.settings(self.data)["quiet"], later)["in"])
        night._LAST.clear()
        night.tick(self.data, self.control, later)
        self.assertEqual(item(0)["state"], "done")
        self.assertNotIn("item_waits", self.tonight()["ran"][0])

    # ---------- the brake ----------

    def test_the_brake_stops_it_before_the_limit_and_the_rest_waits(self):
        self.limits(used=60, resets_in=HOUR)  # a cap of 90
        first = self.ready("tidy the field notes on Tidepool")
        later = self.ready("tidy the reading list on Lantern", floor="Lantern")
        self.tick_tonight(first)
        self.hold()
        self.assertEqual(len(night.tick(self.data, self.control, self.now)), 1)  # Lantern's waits: only Tidepool's ticked yet
        self.tick_tonight(later)
        r = self.tonight()["ran"][0]
        self.assertEqual(self.tonight()["caps"]["Claude Code"]["cap"], 90)
        self.limits(used=91, resets_in=HOUR, at=self.now + 20)  # a reading past the cap
        self.assertEqual(night.tick(self.data, self.control, self.now + 30), [])
        r = self.tonight()["ran"][0]
        self.assertTrue(r["braked_at"])
        self.assertIn("before the limit", r["why"])
        self.assertTrue(os.path.exists(os.path.join(self.data, "control", "stop", r["key"])))  # the hook stops it at its next step
        self.assertTrue(self.tonight()["caps"]["Claude Code"]["braked"])
        self.release()
        self.wait_done()
        night.tick(self.data, self.control, self.now + 60)
        self.assertEqual(self.tonight()["ran"][0]["state"], "braked")
        self.assertEqual(self.control.intake.task(later)["state"], "ready")  # the rest waits for another night
        self.assertIn("reached the most", self.tonight()["said"])

    def test_a_week_that_started_again_brakes_too(self):
        self.limits(used=60, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        self.hold()
        night.tick(self.data, self.control, self.now)
        self.limits(used=1, resets_in=7 * 86400, at=self.now + 20)  # a new week
        night.tick(self.data, self.control, self.now + 30)
        self.assertIn("started again", self.tonight()["ran"][0]["why"])

    def test_claude_codes_own_word_on_the_limits_is_kept(self):
        self.assertEqual(usage.from_claude_event({"status": "allowed_warning", "rateLimitType": "seven_day", "utilization": 0.75,
                                                  "resetsAt": 1800000000}), {"seven_day": {"used": 75.0, "resets_at": 1800000000}})
        got = usage.from_claude_event({"status": "allowed", "unifiedWindows": {"five_hour": {"utilization": 0.2, "resetsAt": 1800000000000},
                                                                                "seven_day": {"utilization": 0.5, "resetsAt": 1800500000}}})
        self.assertEqual(got, {"five_hour": {"used": 20.0, "resets_at": 1800000000.0}, "seven_day": {"used": 50.0, "resets_at": 1800500000}})
        self.assertEqual(usage.from_claude_event({"status": "rejected", "rateLimitType": "five_hour"}), {"five_hour": {"used": 100.0, "resets_at": None}})
        self.assertEqual(usage.from_claude_event({"status": "allowed"}), {})
        self.assertEqual(usage.from_claude_event("no"), {})
        # an agent started here that reports them: kept for the forecast, which the night shift reads
        with open(os.path.join(self.base, "limits.json"), "w", encoding="utf-8") as handle:
            json.dump({"status": "allowed_warning", "rateLimitType": "seven_day", "utilization": 0.82, "resetsAt": int(self.now + HOUR)}, handle)
        self.control.start("Tidepool", "tidy the field notes")
        self.wait_done()
        time.sleep(0.2)
        week = next(f for f in day.forecast(self.data) if f["name"] == "seven_day")
        self.assertEqual((week["source"], week["used"]), ("Claude Code", 82.0))

    # ---------- the morning ----------

    def morning(self, proof_states):
        """A night with a run for each proof state, ended; and the morning after."""
        self.limits(used=40, resets_in=HOUR)
        rids = []
        for i, _ in enumerate(proof_states):
            floor = ("Tidepool", "Lantern")[i % 2]
            rid = self.ready(f"tidy the notes number {i + 1} on {floor}", floor=floor)
            self.tick_tonight(rid)
            rids.append(rid)
        for i in range(0, len(proof_states), 2):
            night.tick(self.data, self.control, self.now + i * 60)
            self.wait_done()
            self.limits(used=41 + i, resets_in=HOUR, at=self.now + i * 60 + 30)
        doc = self.tonight()
        self.assertEqual(len(doc["ran"]), len(proof_states))
        talks = []
        for r, state in zip(doc["ran"], proof_states):
            talk = {"id": r["key"], "project": r["project"], "title": r["title"], "working": False}
            if state:
                talk.update(changed=self.now + 100, proof={"state": state, "check": "The tests", "at": self.now + 200, "tail": "1 failed"})
            talks.append(talk)
        self.feed(talks)
        after = doc["ends"] + 60
        night.tick(self.data, self.control, after)
        return after, doc

    def test_the_morning_report_counts_what_is_proven(self):
        after, doc = self.morning(["passed", "passed", "failed", None])
        v = night.view(self.data, self.control, after)
        report = v["report"]
        self.assertIsNotNone(report)
        self.assertFalse(report["seen"])
        self.assertTrue(report["words"].startswith("4 things finished overnight, 2 proven, 2 not."), report["words"])
        states = [i["proof"]["state"] for i in report["items"]]
        self.assertEqual(states, ["proven", "proven", "failed", "none"])
        self.assertEqual(report["items"][2]["proof"]["tail"], "1 failed")
        self.assertIn("passed after its last change", report["items"][0]["proof"]["line"])
        self.assertEqual(night.report_words([{"state": "done", "proof": {"state": "proven"}}] * 3, {}), "3 things finished overnight, all proven.")
        self.assertIn("4 things finished overnight", night.morning_line(self.data, after))
        self.quiet_around(daily_cycle=True)  # the daily cycle's plan carries the line too
        self.assertIn("4 things finished overnight", day.view(self.data, after)["night"])
        code, got = self.call("night_set", {"seen": report["id"]})
        self.assertEqual(code, 200, got)
        self.assertTrue(night.view(self.data, self.control, after)["report"]["seen"])

    def test_undo_puts_its_restore_point_back(self):
        after, doc = self.morning(["passed"])
        r = doc["ran"][0]
        folder = self.tidepool
        point = restore.take(folder, "before changing files", key=r["key"], project="Tidepool", data=self.data, now=r["started_at"] + 1)
        self.assertTrue(point)
        with open(os.path.join(folder, "app.py"), "w", encoding="utf-8") as handle:
            handle.write("print('changed overnight')\n")
        item = night.view(self.data, self.control, after)["report"]["items"][0]
        self.assertTrue(item["undo"])
        code, got = self.call("night_undo", {"id": r["id"]})
        self.assertEqual(code, 200, got)
        self.assertIn("Put back", got["said"])
        with open(os.path.join(folder, "app.py"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "print('one')\n")
        item = night.view(self.data, self.control, after)["report"]["items"][0]
        self.assertEqual((item["state"], item["undo"]), ("undone", False))
        self.assertEqual(night.view(self.data, self.control, after)["report"]["words"], "1 thing finished overnight, all proven.")
        # found in a real night: Undo on a run stopped before the limit made it "finished" in the report's words
        braked = {**item, "ended": "braked"}
        self.assertEqual(night.report_words([braked], {}), "Nothing finished overnight. 1 stopped before the limit.")
        code, got = self.call("night_undo", {"id": r["id"]})
        self.assertEqual(code, 400)
        self.assertIn("undone already", got["error"])
        code, got = self.call("night_undo", {"id": "n-00000000"})
        self.assertEqual(code, 400)

    def test_with_no_restore_point_there_is_no_undo(self):
        after, doc = self.morning([None])
        item = night.view(self.data, self.control, after)["report"]["items"][0]
        self.assertFalse(item["undo"])
        self.assertIn("nothing to put back", item["no_undo"])
        self.assertEqual(self.call("night_undo", {"id": doc["ran"][0]["id"]})[0], 400)

    def test_it_keeps_its_own_restore_point_when_no_hook_does(self):
        # An agent whose hooks aren't on (found in a real night run): no hook keeps a restore point and the feed never sees
        # its steps. The night shift keeps its own point before it starts, and the morning doesn't say it changed nothing.
        self.limits(used=40, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        self.hold()
        night.tick(self.data, self.control, self.now)
        r = self.tonight()["ran"][0]
        points = restore.read_points(self.data)
        self.assertEqual([(p["by"], p["project"]) for p in points], [("night shift", "Tidepool")])
        self.assertEqual(r["point"], points[0]["id"])
        with open(os.path.join(self.tidepool, "app.py"), "w", encoding="utf-8") as handle:
            handle.write("print('changed overnight')\n")  # what the agent did, unseen
        self.release()
        self.wait_done()
        after = self.tonight()["ends"] + 60
        night.tick(self.data, self.control, after)
        report = night.view(self.data, self.control, after)["report"]
        item = report["items"][0]
        self.assertEqual((item["proof"]["state"], item["proof"]["word"]), ("unseen", "Not proven"))
        self.assertIn("didn't see its steps", item["proof"]["line"])
        self.assertTrue(report["words"].startswith("1 thing finished overnight, none proven."), report["words"])
        self.assertTrue(item["undo"])
        code, got = self.call("night_undo", {"id": r["id"]})
        self.assertEqual(code, 200, got)
        with open(os.path.join(self.tidepool, "app.py"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "print('one')\n")

    def test_a_run_that_changed_files_with_its_shell_never_reads_changed_nothing(self):
        # Found in a real Codex night run: Codex added a line with `printf >> NOTES.md`. The hook saw every step but counts
        # only edit tools as changes, so the morning said "Changed nothing" and hid Undo. Git now says what differs from
        # the run's own restore point when it ends.
        self.limits(used=40, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        self.hold()
        night.tick(self.data, self.control, self.now)
        r = self.tonight()["ran"][0]
        point = next(p for p in restore.read_points(self.data) if p["id"] == r["point"])
        self.assertEqual(restore.changed_since(point, self.data), 0)
        with open(os.path.join(self.tidepool, "app.py"), "w", encoding="utf-8") as handle:
            handle.write("print('changed overnight')\n")  # what its shell did: no edit tool, so the hook counted no change
        with open(os.path.join(self.tidepool, "notes.md"), "w", encoding="utf-8") as handle:
            handle.write("a new file\n")
        self.assertEqual(restore.changed_since(point, self.data), 2)
        self.feed([{"id": r["key"], "project": "Tidepool", "title": r["title"], "working": False}])  # seen, no edit counted
        self.release()
        self.wait_done()
        after = self.tonight()["ends"] + 60
        night.tick(self.data, self.control, after)
        self.assertEqual(self.tonight()["ran"][0]["touched"], 2)
        report = night.view(self.data, self.control, after)["report"]
        item = report["items"][0]
        self.assertEqual((item["proof"]["state"], item["proof"]["word"]), ("claimed", "Not proven"))
        # git sees what differs, not who changed it: the words never say it was the run
        self.assertTrue(item["proof"]["line"].startswith("2 files on its floor differ from how they were before it started"), item["proof"]["line"])
        self.assertNotIn("own commands", item["proof"]["line"])
        self.assertTrue(report["words"].startswith("1 thing finished overnight, none proven."), report["words"])
        self.assertTrue(item["undo"])
        self.assertNotIn("no_undo", item)
        code, got = self.call("night_undo", {"id": r["id"]})
        self.assertEqual(code, 200, got)
        with open(os.path.join(self.tidepool, "app.py"), encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "print('one')\n")
        self.assertEqual(restore.changed_since({**point, "commit": "0" * 40}, self.data), None)  # not one git holds
        self.assertIsNone(restore.changed_since({"id": "rp-000000000000"}, self.data))

    def test_moving_the_end_of_the_quiet_hours_tonight_makes_no_early_report(self):
        # Found in a real night: quiet hours moved later during the night kept the old end, so the report came mid-night.
        self.limits(used=40, resets_in=5 * HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        night.tick(self.data, self.control, self.now)
        self.wait_done()
        self.quiet_around(after=4 * HOUR)  # the same night, now ending two hours later
        later = self.now + 3 * HOUR  # past the old end, before the new
        night.tick(self.data, self.control, later)
        v = night.view(self.data, self.control, later)
        self.assertTrue(v["quiet_now"])
        self.assertIsNone(v["report"])
        self.assertIsNone(self.tonight()["report"])
        self.assertEqual(self.tonight()["ends"], night.span(night.settings(self.data)["quiet"], later)["ends"])
        self.quiet_around(after=2 * HOUR)  # and moved back earlier: the night is over, and the report comes
        night.tick(self.data, self.control, later + 60)
        self.assertEqual(self.tonight()["ends"], later + 60)
        self.assertIsNotNone(night.view(self.data, self.control, later + 60)["report"])

    def test_a_floor_not_in_git_is_left(self):
        shutil.rmtree(os.path.join(self.tidepool, ".git"))
        self.limits(used=40, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        self.assertEqual(night.tick(self.data, self.control, self.now), [])
        self.assertIn("isn't kept in git", self.tonight()["said"])

    # ---------- the switch and the phone ----------

    def test_switched_off_it_shows_and_does_nothing(self):
        self.save("serve.json", {})
        self.limits(used=40, resets_in=HOUR)
        self.assertIsNone(self.control.state()["night"])
        rid = self.ready("tidy the field notes on Tidepool")
        code, got = self.tick_tonight(rid)
        self.assertEqual(code, 400)
        self.assertIn("switched off", got["error"])
        self.assertEqual(night.tick(self.data, self.control, self.now), [])
        self.assertFalse(os.path.isdir(os.path.join(self.data, "night")))
        self.assertFalse(dict((s[0], s[4]) for s in __import__("switches").SWITCHES)["night"])  # off unless you switch it on
        code, got = self.call("night")
        self.assertEqual((code, got["on"]), (200, False))
        code, got = self.call("night_set", {"on": True})
        self.assertEqual(code, 200, got)
        self.assertTrue(got["night"]["on"])

    def test_the_phone_reaches_it_through_control(self):
        import serve
        self.assertIn("night", serve.READS)
        self.assertIn("/data/night/", serve.NEVER_SERVED)  # read only through control
        for name in night.NAMES:
            self.assertRegex(name, r"^[a-z][a-z_]{0,15}$")  # what another page that loads these modules passes on
        code, _, raw, _ = self.control.handle("POST", "night", b"{}", "not the token")
        self.assertEqual(code, 403)
        code, got = self.call("night")
        self.assertEqual(code, 200)
        self.assertEqual(set(got) >= {"on", "quiet", "share", "window", "queued", "ran", "report"}, True)
        state = self.control.state()["night"]
        self.assertEqual(state["quiet"], night.settings(self.data)["quiet"])
        self.assertTrue(state["quiet_now"])

    def test_the_command_line(self):
        env = dict(os.environ, ARNHEIM_DATA=self.data)
        done = subprocess.run([sys.executable, os.path.join(ROOT, "connect", "night.py"), "--show"], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("No forecast", done.stdout)
        self.assertIn("Nothing is approved for tonight.", done.stdout)

    # ---------- the Checker's round 3 findings ----------

    def test_a_limit_past_one_or_on_overage_counts_as_used_up(self):
        # Claude Code's utilization is a fraction: 1.03 is past the limit, never 1.03% used
        self.assertEqual(usage.from_claude_event({"status": "allowed", "rateLimitType": "seven_day", "utilization": 1.03}),
                         {"seven_day": {"used": 100.0, "resets_at": None}})
        self.assertEqual(usage.from_claude_event({"status": "allowed", "rateLimitType": "seven_day", "utilization": 1.0}),
                         {"seven_day": {"used": 100.0, "resets_at": None}})
        self.assertEqual(usage.from_claude_event({"status": "allowed_warning", "rateLimitType": "seven_day", "utilization": 0.5,
                                                  "isUsingOverage": True}), {"seven_day": {"used": 100.0, "resets_at": None}})
        got = usage.from_claude_event({"status": "allowed", "rateLimitType": "seven_day", "isUsingOverage": True,
                                       "unifiedWindows": {"five_hour": {"utilization": 0.2}, "seven_day": {"utilization": 0.9}}})
        self.assertEqual((got["five_hour"]["used"], got["seven_day"]["used"]), (20.0, 100.0))  # the window it names
        self.assertEqual(usage.from_claude_event({"status": "rejected", "unifiedWindows": {"seven_day": {"utilization": 0.4}}}),
                         {"seven_day": {"used": 100.0, "resets_at": None}})
        # and so the night's window stays shut
        a = night.agent_room("Claude Code", {"used": usage.from_claude_event({"rateLimitType": "seven_day", "utilization": 1.03})["seven_day"]["used"],
                                             "resets": self.now + HOUR, "rate": 0.0, "at": self.now}, None, self.now, self.now + 2 * HOUR, 0.8)
        self.assertEqual((a["open"], a["room"]), (False, 0.0))

    def test_a_carried_plan_item_says_what_its_title_hides(self):
        self.quiet_around(daily_cycle=True)
        self.limits(used=40, resets_in=HOUR)
        date = day.today(self.now)
        rows = [{"id": "d-00000001", "title": "Tidy the notes page", "text": "Tidy the notes page, then deploy it.", "source": "carried",
                 "state": "approved"},
                {"id": "d-00000002", "title": "Wire up the weather panel", "text": "Wire up the weather panel with the token from last week.",
                 "source": "unfinished", "state": "approved"},
                {"id": "d-00000003", "title": "Finish the reading list", "text": "Finish the reading list and upload it.", "source": "goal",
                 "state": "approved"}]
        self.save(os.path.join("day", date + ".json"), {"date": date, "made": self.now - 9 * HOUR,
                                                         "plan": [{"floor": "Lantern", "label": "Lantern", "approved": True, "items": rows}]})
        v = night.view(self.data, self.control, self.now)
        self.assertEqual(len(v["queued"]), 3)
        whys = [e["why"] or "" for e in v["queued"]]
        self.assertIn("deploy", whys[0])
        self.assertIn("password or key", whys[1])
        self.assertIn("upload", whys[2])
        self.assertEqual(night.tick(self.data, self.control, self.now), [])
        self.assertEqual(self.started(), [])
        self.assertIn("waits for you", self.tonight()["said"])

    def test_a_ready_task_the_front_door_holds_never_starts_at_night(self):
        self.limits(used=40, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.assertEqual(self.tick_tonight(rid)[0], 200)
        task = self.control.intake.task(rid)
        task["held"] = "The front door holds it back, so it starts only when you press Start."  # whatever its reason
        self.control.intake.save(task)
        [entry] = night.view(self.data, self.control, self.now)["queued"]
        self.assertIn("press Start", entry["why"] or "")
        self.assertEqual(night.tick(self.data, self.control, self.now), [])
        with self.assertRaises(night.Refused) as got:
            night.launch_ready(self.control, rid, "the night's note")
        self.assertIn("leaves it to you", str(got.exception))
        self.assertEqual(self.started(), [])
        self.assertEqual(self.control.intake.task(rid)["state"], "ready")
        self.tick_tonight(rid, False)
        code, got = self.tick_tonight(rid)
        self.assertEqual(code, 400)
        self.assertIn("press Start", got["error"])

    def test_the_night_refuses_what_reaches_outside_or_tidies_away(self):
        for words in ("open a pull request for the footer", "upload the build to the server", "sync the site to production",
                      "gh pr create", "clean up the old log files", "prune old branches", "reply to the customer"):
            self.assertTrue(night.refusal(words), words)
        self.assertIsNone(night.refusal("tidy the field notes on Tidepool"))

    def probe_wait(self):
        thread = night._PROBING.get(self.data)
        if thread is not None:
            thread.join(30)
            self.assertFalse(thread.is_alive(), "the probe didn't finish")

    def probes(self):
        try:
            with open(os.path.join(self.base, "probes.log"), encoding="utf-8") as handle:
                return [json.loads(line) for line in handle if line.strip()]
        except OSError:
            return []

    def probe_says(self, used):
        with open(os.path.join(self.base, "probe_limits.json"), "w", encoding="utf-8") as handle:
            json.dump({"status": "allowed", "rateLimitType": "seven_day", "utilization": used / 100, "resetsAt": int(self.now + HOUR)}, handle)

    def test_a_claude_code_run_asks_with_a_probe_and_the_brake_goes_by_its_reading(self):
        # Claude Code tells its limits once a run, at its first request (2.1.325): a quiet quarter of an hour is no
        # reason to stop. A probe asks instead, and the brake goes by what it says.
        self.limits(used=60, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        self.hold()
        self.assertEqual(len(night.tick(self.data, self.control, self.now)), 1)
        night.tick(self.data, self.control, self.now + 5 * 60)
        self.assertEqual(self.probes(), [])  # a reading five minutes old needs no probe
        self.probe_says(70)
        night.tick(self.data, self.control, self.now + 11 * 60)
        self.probe_wait()
        probes = self.probes()
        self.assertEqual(len(probes), 1)
        args = probes[0]["args"]
        for given in (["-p", "ok"], ["--model", "haiku"], ["--max-turns", "1"], ["--tools", ""], ["--output-format", "stream-json"]):
            self.assertIn(given, [args[i:i + len(given)] for i in range(len(args))], given)
        self.assertIn('{"disableAllHooks": true}', args)
        self.assertIn("--strict-mcp-config", args)
        self.assertEqual(os.path.realpath(probes[0]["cwd"]), os.path.realpath(os.path.join(self.data, "night", "probe")))
        self.assertEqual(os.listdir(os.path.join(self.data, "night", "probe")), [])  # an empty folder of its own
        with open(os.path.join(self.data, "feeds", "usage.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["sources"]["Claude Code"]["seven_day"][-1]["used"], 70.0)  # kept as a run's
        self.assertFalse(night.probe(self.data, self.control, self.now + 11 * 60 + 5))  # one at a time, and not straight after
        night.tick(self.data, self.control, self.now + 16 * 60)  # sixteen minutes, under the cap: it goes on
        self.assertNotIn("braked_at", self.tonight()["ran"][0])
        self.probe_wait()
        self.probe_says(95)  # the next probe says the cap is passed
        night.tick(self.data, self.control, self.now + 30 * 60)
        self.probe_wait()
        night.tick(self.data, self.control, self.now + 31 * 60)
        r = self.tonight()["ran"][0]
        self.assertTrue(r.get("braked_at"))
        self.assertIn("Stopped before the limit", r["why"])
        self.assertTrue(os.path.exists(os.path.join(self.data, "control", "stop", r["key"])))

    def test_two_probes_with_no_reading_stop_a_claude_code_run_to_be_safe(self):
        self.limits(used=60, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        self.hold()
        self.assertEqual(len(night.tick(self.data, self.control, self.now)), 1)
        night.tick(self.data, self.control, self.now + 11 * 60)  # no probe_limits.json: the probe says nothing
        self.probe_wait()
        self.assertEqual(night.probe_state(self.data).get("misses"), 1)
        night.tick(self.data, self.control, self.now + 12 * 60 + 30)  # one probe with nothing is not enough: a second goes
        self.assertNotIn("braked_at", self.tonight()["ran"][0])
        self.probe_wait()
        self.assertEqual(len(self.probes()), 2)
        night.tick(self.data, self.control, self.now + 13 * 60 + 30)
        r = self.tonight()["ran"][0]
        self.assertTrue(r.get("braked_at"))
        self.assertEqual(r["why"], "No fresh reading of your limits, so it stopped to be safe.")
        self.assertTrue(os.path.exists(os.path.join(self.data, "control", "stop", r["key"])))
        self.assertFalse(self.tonight()["caps"]["Claude Code"].get("braked"))  # a fresh reading lets the rest go on

    def test_no_reading_stays_safe_for_the_next_run_too(self):
        # found by the Checker: the run of empty probes kept the first one's start, so a later run whose probes brought
        # nothing was never stopped (nor one after an old night's probe record)
        os.makedirs(os.path.join(self.data, "night"), exist_ok=True)
        win = {"agents": {"Claude Code": {"used": 50.0, "at": self.now}}}
        b = {"agent": "Claude Code", "started_at": self.now}
        earlier = [self.now - 3000, self.now - 2900]  # an earlier run's two empty probes, braked then
        with open(night.probe_path(self.data), "w", encoding="utf-8") as handle:
            json.dump({"misses": 2, "missed_since": earlier[0], "missed": earlier, "ended": self.now + 11 * 60}, handle)
        self.assertIsNone(night.stale_why(b, win, self.now + 11 * 60, self.data, self.control))  # not this run's
        claude = list(self.control.claude)
        self.assertFalse(night.probe_once(self.data, claude, self.now + 11 * 60))  # no probe_limits.json: nothing said
        self.assertIsNone(night.stale_why(b, win, self.now + 12 * 60, self.data, self.control))  # one is not enough
        self.assertFalse(night.probe_once(self.data, claude, self.now + 12 * 60 + 30))
        self.assertEqual(night.stale_why(b, win, self.now + 13 * 60 + 30, self.data, self.control), night.BLIND)
        self.probe_says(60)  # a reading wipes the slate
        self.assertTrue(night.probe_once(self.data, claude, self.now + 14 * 60))
        self.assertEqual(night.probe_state(self.data)["missed"], [])
        self.assertNotIn("missed_since", night.probe_state(self.data))

    def test_a_command_too_long_to_read_waits_at_night(self):
        self.assertTrue(night.command_refusal("echo " + "a" * (night.LONGEST + 1)))
        self.assertIn("too long", night.step_refusal("Bash", {"command": "echo " + "a" * (night.LONGEST + 1)}))
        os.makedirs(os.path.dirname(night.probe_path(self.data)), exist_ok=True)
        with open(night.probe_path(self.data), "w", encoding="utf-8") as handle:
            json.dump({"missed": 5}, handle)  # a hand-edited record is passed over, never an error
        self.assertIsNone(night.stale_why({"agent": "Claude Code", "started_at": self.now}, {}, self.now, self.data, self.control))
        self.assertIsNone(night.command_refusal("echo " + "a" * 100))

    def test_a_codex_run_whose_readings_stop_is_braked(self):
        # Codex reports its limits through its hooks as it works: no probe, and 15 quiet minutes stop it.
        win = {"agents": {"Codex": {"used": 50.0, "at": self.now}}}
        r = {"agent": "Codex", "started_at": self.now}
        self.assertIsNone(night.stale_why(r, win, self.now + 10 * 60, self.data, self.control))
        self.assertEqual(night.stale_why(r, win, self.now + 16 * 60, self.data, self.control), night.BLIND)
        self.assertEqual(self.probes(), [])

    def hook(self, session, **event):
        env = dict(os.environ, ARNHEIM_DATA=self.data, ARNHEIM_CONTROL_WAIT="5")
        event.update(session_id=session, cwd=self.tidepool)
        done = subprocess.run([sys.executable, os.path.join(ROOT, "connect", "claude_code.py")], input=json.dumps(event),
                              capture_output=True, text=True, env=env, timeout=90)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def test_the_hook_turns_down_a_night_runs_push(self):
        import standing
        self.quiet_around(always=True)
        self.limits(used=40, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        self.hold()
        self.assertEqual(len(night.tick(self.data, self.control, self.now)), 1)
        r = self.tonight()["ran"][0]
        mine = self.control.runs[r["key"]]["sid"]
        other = "0f0f0f0f-1111-2222-3333-444444444444"  # someone's own conversation on the same floor
        steps = ("git push origin main", "gh pr create --fill", "rsync -av dist/ server:/srv/site", "scp build.zip server:",
                 "curl -X POST https://example.com/hook -d '{}'", "rm -rf build", "npm publish")
        for command in steps:
            got = self.hook(mine, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": command})
            self.assertEqual((got or {}).get("hookSpecificOutput", {}).get("permissionDecision"), "deny", command)
            self.assertIn("night shift", got["hookSpecificOutput"]["permissionDecisionReason"])
        got = self.hook(mine, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": ["git", "push", "origin", "main"]})
        self.assertEqual(got["hookSpecificOutput"]["permissionDecision"], "deny")  # a command as a list of words, as Codex may give it
        got = self.hook(mine, hook_event_name="PreToolUse", tool_name="mcp__github__create_pull_request", tool_input={})
        self.assertEqual(got["hookSpecificOutput"]["permissionDecision"], "deny")
        for command in ("npm test", "git status", "git commit -am 'Tidy the notes'"):
            got = self.hook(mine, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": command})
            self.assertNotEqual((got or {}).get("hookSpecificOutput", {}).get("permissionDecision"), "deny", command)
        for command in ("git push origin main", "gh pr create --fill"):  # the same step from a normal run: as it was
            got = self.hook(other, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": command})
            self.assertNotEqual((got or {}).get("hookSpecificOutput", {}).get("permissionDecision"), "deny", command)
        # a standing allow never lets a night run through: nobody is watching it
        standing.add(self.data, "Tidepool", "Bash", "npm test")
        got = self.hook(other, hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "npm test"})
        self.assertEqual(got["hookSpecificOutput"]["decision"], {"behavior": "allow"})
        got = self.hook(mine, hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "npm test"})
        self.assertNotEqual(((got or {}).get("hookSpecificOutput") or {}).get("decision"), {"behavior": "allow"})

    def night_run(self):
        """A night run at work on Tidepool, from a ready task ticked Tonight: its session id."""
        self.limits(used=40, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        self.hold()
        self.assertEqual(len(night.tick(self.data, self.control, self.now)), 1)
        return self.control.runs[self.tonight()["ran"][0]["key"]]["sid"]

    def decision(self, got):
        return ((got or {}).get("hookSpecificOutput") or {}).get("permissionDecision")

    def test_the_hook_turns_down_what_got_round_it(self):
        mine = self.night_run()
        for command in ('git -C "my dir" push', "gh -R owner/repo pr create --fill", "./ship.sh", "bash scripts/release.sh",
                        "npm run release", "python3 push.py", "make publish", "aws s3 cp dist s3://site --recursive",
                        "curl --json '{}' https://example.com/hook", "git -c url.x.pushInsteadOf=https:// status",
                        "GIT_CONFIG_COUNT=0 git status", "env -i sh ./tidy.sh"):
            got = self.hook(mine, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": command})
            self.assertEqual(self.decision(got), "deny", command)
        # any tool handed a command is a shell step: Monitor, Codex's exec_command (a list of words), PowerShell
        for tool, given in (("Monitor", {"command": "git push origin main", "description": "push"}),
                            ("exec_command", {"cmd": ["git", "push"]}), ("exec_command", {"command": ["git", "push"]}),
                            ("PowerShell", {"command": "git push"})):
            got = self.hook(mine, hook_event_name="PreToolUse", tool_name=tool, tool_input=given)
            self.assertEqual(self.decision(got), "deny", tool)
        # another server's tools: only those that only read
        for tool in ("mcp__slack__chat_postMessage", "mcp__s3__put_object", "mcp__github__fork_repository", "mcp__linear__save_issue",
                     "mcp__shell__run_command", "mcp__claude-in-chrome__javascript_tool"):
            got = self.hook(mine, hook_event_name="PreToolUse", tool_name=tool, tool_input={})
            self.assertEqual(self.decision(got), "deny", tool)
            self.assertIn("only to read", got["hookSpecificOutput"]["permissionDecisionReason"])
        for tool, given in (("mcp__github__get_file_contents", {}), ("mcp__github__list_pull_requests", {}),
                            ("Bash", {"command": "cargo build --release"}), ("Bash", {"command": "pushd src && npm test"}),
                            ("apply_patch", {"command": "*** Begin Patch\n*** Update File: a.js\n+items.push(x)\n*** End Patch"})):
            got = self.hook(mine, hook_event_name="PreToolUse", tool_name=tool, tool_input=given)
            self.assertNotEqual(self.decision(got), "deny", (tool, given))

    def test_options_may_come_before_gits_or_ghs_own_word(self):
        for command in ('git -C "my dir" push', "git --git-dir=.git -c core.x=1 push origin", "gh -R owner/repo pr create",
                        "gh --repo owner/repo release create v1", "git -C a send-email x.patch"):
            self.assertTrue(night.NIGHT_STEPS.search(command), command)
        for command in ("git status", "git -C src diff", "gh --version", "git commit -am 'Tidy the notes'"):
            self.assertIsNone(night.NIGHT_STEPS.search(command), command)

    def test_a_broken_night_row_never_turns_down_your_own_push(self):
        mine = self.night_run()
        doc = self.tonight()
        doc["ran"] = ["half written", {"state": "working", "ready": ["not", "an", "id"]}, {"state": "working", "key": {}}] + doc["ran"]
        night.keep(self.data, doc)
        self.assertTrue(night.working_run(self.data, self.control.runs[doc["ran"][-1]["key"]]["key"]))  # the good row still counts
        other = "0f0f0f0f-1111-2222-3333-444444444444"
        got = self.hook(other, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "git push origin main"})
        self.assertNotEqual(self.decision(got), "deny")
        got = self.hook(mine, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "git push origin main"})
        self.assertEqual(self.decision(got), "deny")

    def test_when_the_nights_rules_cant_be_read_only_the_buildings_agents_wait(self):
        import claude_code
        mine = self.night_run()
        key = "cc-" + mine.replace("-", "")[:12]
        self.assertTrue(os.path.isfile(os.path.join(self.data, "control", "runs", key + ".json")))
        kept, rule = claude_code.DATA, claude_code.night_rule

        def broken(event):
            raise ValueError("the night's records can't be read")
        claude_code.DATA, claude_code.night_rule = self.data, broken
        try:
            step = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git push origin main"},
                    "cwd": self.tidepool}
            self.assertEqual(self.decision(claude_code.before_step({**step, "session_id": mine})), "deny")
            other = claude_code.before_step({**step, "session_id": "0f0f0f0f-1111-2222-3333-444444444444"})
            self.assertNotEqual(self.decision(other), "deny")  # your own conversation: as it always was
        finally:
            claude_code.DATA, claude_code.night_rule = kept, rule

    def pushes(self, env):
        """A real `git push` from a script, in a scratch repository, to a folder on this computer and to an https and a
        git@ address (never reached): {where: (exit code, what git said)}."""
        work, bare = os.path.join(self.base, "pushing"), os.path.join(self.base, "remote.git")
        if not os.path.isdir(work):
            subprocess.run(["git", "init", "-q", "--bare", bare], check=True, capture_output=True)
            os.makedirs(work)
            git(work, "init", "-q")
            for name, value in (("user.name", "Someone"), ("user.email", "someone@example.com"), ("commit.gpgsign", "false")):
                git(work, "config", name, value)
            git(work, "commit", "-q", "--allow-empty", "-m", "first")
            with open(os.path.join(work, "ship.sh"), "w", encoding="utf-8") as handle:
                handle.write('#!/bin/sh\ngit push "$1" HEAD:refs/heads/main\n')
        env = {**env, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        out = {}
        for where, url in (("here", "file://" + bare), ("https", "https://example.invalid/owner/repo.git"),
                           ("git@", "git@example.invalid:owner/repo.git"), ("ssh", "ssh://example.invalid/repo.git")):
            done = subprocess.run(["sh", "ship.sh", url], cwd=work, env=env, capture_output=True, text=True, timeout=60)
            out[where] = (done.returncode, done.stderr)
        return out

    def test_a_night_runs_git_pushes_go_nowhere_whatever_starts_them(self):
        for codex in (False, True):
            env = night.no_push_env({"PATH": os.environ.get("PATH", ""), "HOME": self.base}, codex=codex)
            got = self.pushes(env)
            self.assertEqual(got["here"][0], 0, got["here"])  # a folder on this computer: as usual
            for where in ("https", "git@", "ssh"):
                self.assertNotEqual(got[where][0], 0, where)
                self.assertIn("night-shift-never-pushes", got[where][1], (codex, where))  # failed before it connected
        # what was in the environment already is kept, and these come after it
        env = night.no_push_env({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "user.name", "GIT_CONFIG_VALUE_0": "Someone"})
        self.assertEqual((env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_COUNT"]), ("user.name", str(1 + len(night.NO_PUSH_FROM))))
        self.assertEqual(env["GIT_CONFIG_KEY_1"], "url.night-shift-never-pushes://.pushInsteadOf")
        env = night.no_push_env({"GIT_CONFIG_PARAMETERS": "'user.name=Someone'"}, codex=True)
        self.assertTrue(env["GIT_CONFIG_PARAMETERS"].startswith("'user.name=Someone' 'url.night-shift-never-pushes://"))

    def test_your_own_words_to_a_finished_night_run_carry_on_without_the_night_settings(self):
        # found by the Checker: a resumed night run kept them, so a morning "push it" failed with git's own error
        self.night_run()
        self.release()
        self.wait_done()
        key = self.tonight()["ran"][0]["key"]
        self.assertIn("night-shift-never-pushes", json.dumps(self.started()[0]["env"]))
        self.hold()  # your turn is still at work when the night shift next looks
        self.assertEqual(self.control.say(key, "push it to the branch now")["sent"], "resumed")
        self.assertNotIn("night", self.control.runs[key])
        # before the next tick, too: the hook doesn't take your turn for the night's (found by the Checker)
        self.assertFalse(night.working_run(self.data, key))
        sid = self.control.runs[key]["sid"]
        out = self.hook(sid, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "git push origin main"})
        self.assertNotIn("night shift", json.dumps(out or {}))
        night.tick(self.data, self.control, self.now + 60)
        self.assertEqual(self.tonight()["ran"][0]["state"], "done")  # the night's row ends; your turn goes on
        night.tick(self.data, self.control, self.now + night.BRAKE_WAIT + 120)
        self.assertFalse(self.control.runs[key].get("stopping"))  # and nothing of the night stops it
        self.assertFalse(os.path.exists(os.path.join(self.data, "control", "stop", key)))
        self.release()
        self.wait_done()
        self.assertEqual(len(self.started()), 2)
        self.assertNotIn("night-shift-never-pushes", json.dumps(self.started()[-1]["env"]))

    def test_undo_waits_while_your_carried_on_turn_works(self):
        # found by the Checker: once the night's row settles, Undo could put files back under your own turn when the
        # hooks don't see it
        self.night_run()
        self.release()
        self.wait_done()
        key = self.tonight()["ran"][0]["key"]
        self.hold()
        self.assertEqual(self.control.say(key, "and the footer too")["sent"], "resumed")
        self.feed([])  # hooks off: the feed doesn't see your turn
        night.tick(self.data, self.control, self.now + 60)
        r = self.tonight()["ran"][0]
        self.assertEqual(r["state"], "done")
        code, got = self.call("night_undo", {"id": r["id"]})
        self.assertEqual(code, 400, got)
        self.assertIn("is at work on", got["error"])
        self.release()
        self.wait_done()

    def test_the_night_starts_its_agents_with_pushes_sent_nowhere(self):
        self.night_run()
        self.release()
        self.wait_done()
        started = self.started()
        self.assertEqual(len(started), 1)
        env = started[0]["env"]
        self.assertIn("night-shift-never-pushes", json.dumps(env))
        got = self.pushes({**{k: v for k, v in os.environ.items() if not k.startswith("GIT_CONFIG")}, **env})
        self.assertEqual(got["here"][0], 0)
        self.assertIn("night-shift-never-pushes", got["https"][1])
        # Codex, on a floor that names it, gets them in its own way
        self.company["floors"][0]["agent"] = "Codex"
        self.save("company.json", self.company)
        self.control.codex = self.fake
        self.limits(used=40, resets_in=HOUR, source="Codex")
        rid = self.ready("tidy the field notes on Lantern", floor="Lantern")
        self.tick_tonight(rid)
        night.tick(self.data, self.control, self.now + 60)
        self.wait_done()
        codex = [s for s in self.started() if s.get("agent") == "Codex"]
        self.assertEqual(len(codex), 1, self.tonight().get("said"))
        self.assertIn("night-shift-never-pushes", codex[0]["env"].get("GIT_CONFIG_PARAMETERS", ""))
        self.assertNotIn("GIT_CONFIG_COUNT", codex[0]["env"])
        # your own agents start as they always did
        self.control.start("Tidepool", "say hello")
        self.wait_done()
        self.assertNotIn("night-shift-never-pushes", json.dumps(self.started()[-1]["env"]))

    def test_undo_waits_while_a_night_agent_works_on_the_floor(self):
        after, doc = self.morning(["passed"])
        r = doc["ran"][0]
        restore.take(self.tidepool, "before changing files", key=r["key"], project="Tidepool", data=self.data, now=r["started_at"] + 1)
        doc = night.load(self.data, doc["night"])
        doc["ran"].append({**r, "id": "n-0badc0de", "key": "cc-000000000000", "state": "working", "point": None})
        night.keep(self.data, doc)
        code, got = self.call("night_undo", {"id": r["id"]})
        self.assertEqual(code, 400, got)
        self.assertIn("still at work on Tidepool", got["error"])

    def test_show_changes_nothing(self):
        self.limits(used=40, resets_in=HOUR)
        rid = self.ready("tidy the field notes on Tidepool")
        self.tick_tonight(rid)
        os.remove(os.path.join(self.data, "control", "intake", rid + ".json"))  # its task has gone
        path = night.ticks_path(self.data)
        with open(path, "rb") as handle:
            before = handle.read()
        env = dict(os.environ, ARNHEIM_DATA=self.data)
        done = subprocess.run([sys.executable, os.path.join(ROOT, "connect", "night.py"), "--show"], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), before)

    def test_the_nights_are_never_served_however_they_are_reached(self):
        import http.client
        import threading
        sys.path.insert(0, ROOT)
        import serve
        self.tick_tonight(self.ready("tidy the field notes on Tidepool"))
        os.symlink(os.path.join(self.data, "night"), os.path.join(self.data, "elsewhere"))
        old_root = serve.ROOT
        serve.ROOT = os.path.realpath(self.base)
        server = serve.Server(("127.0.0.1", 0), serve.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for path in ("/data/night/tonight.json", "/data/Night/tonight.json", "/data/elsewhere/tonight.json"):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
                conn.request("GET", path, headers={"Host": f"127.0.0.1:{server.server_address[1]}"})
                answer = conn.getresponse()
                body = answer.read()
                self.assertIn(answer.status, (403, 404), path)
                self.assertNotIn(b"ticked", body, path)
        finally:
            server.shutdown()
            server.server_close()
            serve.ROOT = old_root


PAGE = """
import { pathToFileURL } from 'node:url';
const n = await import(pathToFileURL(process.argv[1] + '/src/night.js').href);
const door = await import(pathToFileURL(process.argv[1] + '/src/front-door.js').href);
const fs = await import('node:fs');
const raw = JSON.parse(fs.readFileSync(process.argv[1] + '/sample/night.json', 'utf8'));
const v = n.sampleNight(raw, new Date(2026, 10, 21, 8, 0).getTime() / 1000);
console.log(JSON.stringify({
  intents: ['how did the night go?', 'What happened overnight', "what's on tonight?", 'what will the night shift do',
    'fix the footer on Tidepool tonight', 'what is the weather'].map((t) => n.nightIntent(t)),
  words: v.report.words, said: n.sayReport(v.report), tonight: n.sayTonight(v), madeUp: v.sample,
  alert: n.reportAlert(v.report), moods: v.report.items.map(n.itemMood),
  doorTonight: ['do it tonight', 'Tonight please', 'leave it for the night shift', 'yes', 'start it'].map((t) => door.TONIGHT_IT.test(t)),
  doorEnd: [door.tonightCut('fix the footer on Tidepool tonight'), door.tonightCut('fix the footer on Tidepool')],
  redraws: (() => {
    let changed = 0;
    let watcher = null;
    const page = n.createNight({ styled: false, where: () => 'here', changed: () => { changed += 1; }, alerts: { on: () => false },
      control: { on: true, watch: (f) => { watcher = f; }, nightNow: () => null } });
    page.start();
    const at = (ticked, seen = false) => ({ night: { quiet: { from: '23:00', to: '07:00' }, share: 80, ticked, ran: [], queued: [],
      report: { id: 'night-2026-11-21', seen, words: 'Nothing ran overnight.', items: [] } } });
    const counts = [];
    for (const s of [at([]), at([]), at(['rd-0123456789']), at(['rd-0123456789'], true)]) { watcher(s); counts.push(changed); }
    return counts;
  })(),
  undoneBraked: n.reportWords([{ state: 'done', proof: { state: 'proven' } }, { state: 'undone', ended: 'braked', proof: { state: 'unseen' } }]),
}));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class NightPageTest(unittest.TestCase):
    def test_the_page_words(self):
        done = subprocess.run([NODE, "--input-type=module", "-e", PAGE, ROOT], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        got = json.loads(done.stdout)
        self.assertEqual(got["intents"], ["report", "report", "tonight", "tonight", None, None])
        self.assertTrue(got["madeUp"])
        self.assertTrue(got["words"].startswith("4 things finished overnight, 3 proven, 1 not."), got["words"])
        self.assertIn("made up", got["said"].lower())
        self.assertIn("4 things finished overnight", got["said"])
        self.assertTrue(got["tonight"])
        self.assertEqual(got["alert"]["title"], "The night shift")
        self.assertIn("4 things finished overnight", got["alert"]["body"])
        self.assertIn("ok", got["moods"])
        self.assertIn("failed", got["moods"])
        self.assertEqual(got["doorTonight"], [True, True, True, False, False])
        self.assertEqual(got["doorEnd"], ["fix the footer on Tidepool", None])
        # found in a real night: a Tonight tick (and Got it) stayed as it was on the page until something else changed
        self.assertEqual(got["redraws"], [0, 0, 1, 2])
        # found in a real night: Undo on a run stopped before the limit made it "finished"
        self.assertEqual(got["undoneBraked"], "1 thing finished overnight, all proven. 1 stopped before the limit.")

    def test_no_long_dashes_in_what_people_read(self):
        for rel in ("src/night.js", "src/night.css", "sample/night.json", "connect/night.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
                self.assertNotIn("—", handle.read(), rel)


if __name__ == "__main__":
    unittest.main()
