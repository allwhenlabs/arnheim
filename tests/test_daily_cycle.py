"""The daily cycle (connect/day.py): a plan in the morning from each floor's goals, ready tasks and unfinished work,
fitted to the allowance left; approving it all or a floor at a time; changing it in words; approved items starting
in order, one at a time on each floor, never while paused or over budget; a missed plan time; the evening close;
the phone's way in through control; and the switch. A stand-in for Claude Code's `claude` command answers for real
agents, and the page's words (src/day.js) run under Node.

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

NODE = shutil.which("node")

# Stands in for `claude -p`: says the words back, and stays at work while a file named "hold" is beside it.
FAKE = r'''
import json, os, sys, time
args = sys.argv[1:]
words = sys.stdin.read()
sid = args[args.index("--resume" if "--resume" in args else "--session-id") + 1]
hold = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hold")
with open(os.path.join(os.path.dirname(hold), "started.log"), "a") as log:
    log.write(json.dumps({"cwd": os.getcwd(), "words": words}) + "\n")
print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}), flush=True)
until = time.time() + 20
while os.path.exists(hold) and time.time() < until:
    time.sleep(0.05)
print(json.dumps({"type": "result", "result": "Done: " + words[:40], "session_id": sid}), flush=True)
'''


class FrontDoor(control.Control):
    """Control with round 1's front door as its contract names it: state "ready", and "intake" and "ready_start"."""

    def __init__(self, *args, **kwargs):
        self.ready = []
        self.calls = []
        super().__init__(*args, **kwargs)

    def state(self):
        return {**super().state(), "ready": [dict(r) for r in self.ready]}

    def handle(self, method, name, body=b"", token=""):
        if name == "intake":
            given = json.loads(body)
            self.calls.append(("intake", given))
            rid = f"r{len(self.calls)}"
            self.ready.append({"id": rid, "project": given["project"], "title": given["text"], "state": "ready"})
            return 200, control.JSON, json.dumps({"ok": True, "ready": {"id": rid}}).encode(), {}
        if name == "ready_start":
            given = json.loads(body)
            self.calls.append(("ready_start", given))
            row = next((r for r in self.ready if r["id"] == given["id"]), None)
            if not row:
                return 400, control.JSON, b'{"error": "That ready task has gone."}', {}
            self.ready.remove(row)
            got = self.start(row["project"], row["title"])
            return 200, control.JSON, json.dumps({"ok": True, "key": got["key"]}).encode(), {}
        return super().handle(method, name, body, token)


class DailyCycleTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.data = os.path.join(self.base, "data")
        self.lantern = os.path.realpath(os.path.join(self.base, "code", "lantern"))
        self.tidepool = os.path.realpath(os.path.join(self.base, "code", "tidepool"))
        for folder in (self.data, self.lantern, self.tidepool, os.path.join(self.data, "feeds")):
            os.makedirs(folder, exist_ok=True)
        self.company = {
            "company": "Example Studio",
            "rooms": [{"id": "work", "label": "Work"}],
            "floors": [
                {"id": "lantern", "label": "Lantern", "project": "Lantern", "folder": self.lantern, "lead": {"name": "Juno"}},
                {"id": "tidepool", "label": "Tidepool", "project": "Tidepool", "folder": self.tidepool},
                {"id": "studio", "label": "Studio", "project": "Studio"},  # no folder here: nothing can start, so not planned
            ],
            "feeds": ["feeds/claude-code.json"],
        }
        self.save("company.json", self.company)
        self.save("work.json", {
            "goals": [{"id": "g1", "project": "Lantern", "title": "Ten thousand happy readers", "status": "open"},
                      {"id": "g2", "project": "Lantern", "title": "Sync between devices", "status": "reached"},
                      {"id": "g3", "project": "Tidepool", "title": "A kit anyone can build", "status": "open"},
                      {"id": "g4", "project": "Studio", "title": "Stay small", "status": "open"}],
            "tasks": [{"id": "t1", "project": "Lantern", "title": "Write the notes for version 2", "status": "open"},
                      {"id": "t2", "project": "Lantern", "title": "Pick a badge", "status": "needs_you", "note": "Two designs are ready."},
                      {"id": "t3", "project": "Lantern", "title": "Fix the bookmark", "status": "working"},
                      {"id": "t4", "project": "Tidepool", "title": "Calibrate the wind sensor", "status": "open"},
                      {"id": "t5", "project": "Tidepool", "title": "Order rain gauges", "status": "open"},
                      {"id": "t6", "project": "Tidepool", "title": "Tidy the field notes", "status": "open"}],
        })
        self.feed([])
        self.switches({"daily_cycle": True})
        fake = os.path.join(self.base, "fake_claude.py")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE)
        self.fake = [sys.executable, fake]
        self.control = control.Control(self.data, claude=self.fake)
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

    def feed(self, conversations, ended=None):
        self.save(os.path.join("feeds", "claude-code.json"), {"conversations": conversations, **({"ended": ended} if ended else {})})

    def switches(self, kept):
        self.save("serve.json", kept)

    def hold(self):
        open(os.path.join(self.base, "hold"), "w").close()

    def release(self):
        try:
            os.remove(os.path.join(self.base, "hold"))
        except OSError:
            pass

    def call(self, name, body=None, ctrl=None):
        ctrl = ctrl or self.control
        code, _, raw, _ = ctrl.handle("POST", name, json.dumps(body or {}).encode(), ctrl.token)
        return code, json.loads(raw)

    def floor(self, v, label):
        return next((f for f in v["plan"] if f["label"] == label), None)

    def titles(self, v, label):
        return [it["title"] for it in self.floor(v, label)["items"]]

    def states(self, v, label):
        return [it["state"] for it in self.floor(v, label)["items"]]

    def wait_done(self, most=15):
        until = time.time() + most
        while time.time() < until:
            if not any(self.control.alive(r) for r in list(self.control.runs.values())):
                return
            time.sleep(0.05)
        self.fail("the stand-in agents didn't finish")

    def started(self):
        try:
            with open(os.path.join(self.base, "started.log"), encoding="utf-8") as handle:
                return [json.loads(line) for line in handle if line.strip()]
        except OSError:
            return []

    def yesterday(self, plan):
        date = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        self.save(os.path.join("day", date + ".json"), {"date": date, "made": time.time() - 86400, "plan": plan})

    # ---------- the plan ----------

    def test_plan_from_unfinished_work_ready_tasks_tasks_and_goals(self):
        self.yesterday([{"floor": "Lantern", "label": "Lantern", "approved": True, "items": [
            {"title": "Move the settings page", "text": "Move the settings page.", "state": "approved"},
            {"title": "Speed up search", "text": "Speed up search.", "state": "stopped"},
            {"title": "Already done", "text": "x", "state": "done"}]}])
        self.feed([{"id": "cc-aaaaaaaaaaaa", "project": "Lantern", "title": "Pictures for the store", "working": False,
                    "proof": {"state": "failed", "check": "The picture sizes check", "tail": "1 of 5 pictures is the wrong size."}}])
        front = FrontDoor(self.data, claude=self.fake)
        front.ready = [{"id": "rd1", "project": "Tidepool", "title": "Make the login faster", "state": "ready"},
                       {"id": "rd2", "project": "Tidepool", "title": "Started already", "state": "started"}]
        doc = day.make_plan(self.data, front)
        v = day.view(self.data)
        self.assertTrue(v["made"])
        self.assertEqual([f["label"] for f in v["plan"]], ["Lantern", "Tidepool"])  # Studio has no folder here
        self.assertEqual(self.titles(v, "Lantern"), ["Move the settings page", "Speed up search", 'Get "Pictures for the store" past the picture sizes check'])
        lantern = self.floor(v, "Lantern")
        self.assertEqual(lantern["lead"], "Juno")
        self.assertEqual(lantern["later"], 2)  # the open task and the goal wait: three things a floor
        self.assertEqual([it["source"] for it in lantern["items"]], ["carried", "carried", "unfinished"])
        self.assertIn("approved yesterday", lantern["items"][0]["why"])
        self.assertIn("1 of 5 pictures is the wrong size", lantern["items"][2]["why"])
        self.assertEqual(self.titles(v, "Tidepool"), ["Make the login faster", "Calibrate the wind sensor", "Order rain gauges"])
        self.assertEqual(self.floor(v, "Tidepool")["items"][0]["source"], "ready")
        self.assertEqual(set(self.states(v, "Lantern")), {"proposed"})
        self.assertFalse(v["approved"])
        stored = [it for f in doc["plan"] for it in f["items"] if it.get("ready")]
        self.assertEqual([it["ready"] for it in stored], ["rd1"])
        # without yesterday's or the failed work, the open task and then the goal come up
        os.remove(day.path_of(self.data, day.today()))
        os.remove(day.path_of(self.data, (datetime.date.today() - datetime.timedelta(days=1)).isoformat()))
        self.feed([])
        day.make_plan(self.data, self.control)
        v = day.view(self.data)
        self.assertEqual(self.titles(v, "Lantern"), ["Write the notes for version 2", "Next step toward: Ten thousand happy readers"])
        self.assertEqual(self.floor(v, "Lantern")["items"][1]["source"], "goal")

    def test_no_forecast_is_said_plainly_and_no_cost_is_made_up(self):
        day.make_plan(self.data, self.control)
        v = day.view(self.data)
        self.assertFalse(v["allowance"]["known"])
        self.assertIn("No forecast", v["allowance"]["words"])
        self.assertNotRegex(v["allowance"]["words"], r"\d+%")
        self.assertFalse(any("cost" in it for f in v["plan"] for it in f["items"]))

    def test_the_allowance_left_fits_the_plan(self):
        now = time.time()
        rows = [{"at": now - 3000 + i * 600, "used": 40 + i, "resets_at": now + 2 * 86400 - 3600} for i in range(5)]
        self.save(os.path.join("feeds", "usage.json"), {"sources": {"Claude Code": {"seven_day": rows}}})
        day.make_plan(self.data, self.control)
        v = day.view(self.data)
        self.assertTrue(v["allowance"]["known"])
        self.assertFalse(v["allowance"]["tight"])
        self.assertIn("Claude Code has 56% of its weekly limit left", v["allowance"]["words"])
        self.assertIn("about 28% a day", v["allowance"]["words"])
        self.assertEqual(len(self.floor(v, "Tidepool")["items"]), 3)
        # a 5-hour limit used up only delays the day: it is said, and the plan stays as it was
        rows5 = [{"at": now - 600, "used": 98, "resets_at": now + 3600}, {"at": now - 60, "used": 100, "resets_at": now + 3600}]
        self.save(os.path.join("feeds", "usage.json"), {"sources": {"Claude Code": {"seven_day": rows, "five_hour": rows5}}})
        day.make_plan(self.data, self.control, again=True)
        v = day.view(self.data)
        self.assertFalse(v["allowance"]["tight"])
        self.assertIn("Claude Code's 5-hour limit is used up until", v["allowance"]["words"])
        self.assertEqual(len(self.floor(v, "Tidepool")["items"]), 3)
        # the weekly limit reached before it starts again, at this pace: tight, so each floor proposes one thing
        fast = [{"at": now - 3000 + i * 600, "used": 90 + i * 2, "resets_at": now + 2 * 86400} for i in range(5)]
        self.save(os.path.join("feeds", "usage.json"), {"sources": {"Codex": {"seven_day": fast}}})
        day.make_plan(self.data, self.control, again=True)
        v = day.view(self.data)
        self.assertTrue(v["allowance"]["tight"])
        self.assertIn("At this pace Codex reaches it before it starts again.", v["allowance"]["words"])
        self.assertIn("each floor proposes one thing", v["allowance"]["words"])
        self.assertEqual([len(f["items"]) for f in v["plan"]], [1, 1])

    def test_a_cost_only_from_enough_finished_work(self):
        today = datetime.date.today().isoformat()
        talks = [{"id": f"cc-{i:012d}", "project": "Tidepool", "title": "t", "spent": {"day": today, "tokens": n}} for i, n in enumerate((100000, 300000))]
        self.feed(talks)
        day.make_plan(self.data, self.control)
        self.assertFalse(any("cost" in it for it in self.floor(day.view(self.data), "Tidepool")["items"]))
        self.feed(talks + [{"id": "cc-000000000009", "project": "Tidepool", "title": "t", "spent": {"day": today, "tokens": 200000}},
                           {"id": "cc-000000000010", "project": "Tidepool", "title": "busy", "working": True, "spent": {"day": today, "tokens": 900000}}])
        day.make_plan(self.data, self.control, again=True)
        v = day.view(self.data)
        self.assertEqual({it.get("cost") for it in self.floor(v, "Tidepool")["items"]}, {"about 200 thousand tokens"})
        self.assertFalse(any("cost" in it for it in self.floor(v, "Lantern")["items"]))  # another floor's work says nothing

    def test_a_floor_budget_fits_how_many(self):
        today = datetime.date.today().isoformat()
        self.company["floors"][1]["budget"] = 1000000
        self.save("company.json", self.company)
        self.feed([{"id": f"cc-{i:012d}", "project": "Tidepool", "title": "t", "spent": {"day": today, "tokens": 300000}} for i in range(3)])
        day.make_plan(self.data, self.control)
        tidepool = self.floor(day.view(self.data), "Tidepool")
        self.assertEqual(len(tidepool["items"]), 1)  # 100 thousand left, at about 300 thousand each: one
        self.assertIn("100 thousand tokens are left of its budget today", tidepool["note"])

    # ---------- approving and starting ----------

    def test_approve_the_day_starts_one_at_a_time_on_each_floor_in_order(self):
        self.hold()
        code, got = self.call("day_plan")
        self.assertEqual(code, 200, got)
        code, got = self.call("day_approve")
        self.assertEqual(code, 200, got)
        self.assertIn("Approved 5 things on 2 floors", got["said"])
        v = got["day"]
        self.assertTrue(v["approved"])
        self.assertEqual(self.states(v, "Lantern"), ["started", "approved"])
        self.assertEqual(self.states(v, "Tidepool"), ["started", "approved", "approved"])
        self.assertEqual(len(self.control.runs), 2)
        self.assertEqual(sorted(s["cwd"] for s in self.wait_for_starts(2)), sorted([self.lantern, self.tidepool]))
        self.assertIn("one item on today's plan for the Lantern floor", next(s["words"] for s in self.started() if s["cwd"] == self.lantern))
        self.assertEqual(day.step(self.data, self.control), [])  # still at work: nothing more starts
        self.release()
        self.wait_done()
        time.sleep(5.1)  # a start is given a few seconds to show it is at work
        started = day.step(self.data, self.control)
        self.assertEqual(len(started), 2)
        v = day.view(self.data)
        self.assertEqual(self.states(v, "Tidepool"), ["done", "started", "approved"])
        self.assertEqual(self.states(v, "Lantern"), ["done", "started"])

    def test_never_beside_an_agent_already_at_work_on_the_floor(self):
        # one agent at a time on a floor, with the front door off too (it queues them itself): your own agent at work on
        # Tidepool keeps the plan's next item waiting there (found by the Checker)
        self.switches({"daily_cycle": True, "front_door": False})
        self.hold()
        self.control.start("Tidepool", "your own work on the field notes")
        self.wait_for_starts(1)
        self.call("day_plan")
        code, got = self.call("day_approve")
        self.assertEqual(code, 200, got)
        v = got["day"]
        self.assertEqual(self.states(v, "Lantern"), ["started", "approved"])
        self.assertEqual(self.states(v, "Tidepool"), ["approved", "approved", "approved"])
        first = next(f for f in v["plan"] if f["label"] == "Tidepool")["items"][0]
        self.assertIn("An agent is at work on Tidepool now", first.get("waiting") or "")
        self.release()
        self.wait_done()

    def wait_for_starts(self, n, most=10):
        until = time.time() + most
        while time.time() < until:
            got = self.started()
            if len(got) >= n:
                return got
            time.sleep(0.05)
        self.fail(f"{n} agents didn't start")

    def test_approve_one_floor(self):
        self.hold()
        self.call("day_plan")
        code, got = self.call("day_approve", {"floors": ["tidepool"]})
        self.assertEqual(code, 200, got)
        self.assertIn("Approved 3 things on Tidepool", got["said"])
        v = got["day"]
        self.assertFalse(v["approved"])
        self.assertTrue(self.floor(v, "Tidepool")["approved"])
        self.assertFalse(self.floor(v, "Lantern").get("approved"))
        self.assertEqual(self.states(v, "Lantern"), ["proposed", "proposed"])
        self.assertEqual(len(self.control.runs), 1)
        code, got = self.call("day_approve", {"floors": ["Nowhere"]})
        self.assertEqual(code, 400)
        self.assertIn("no floor called Nowhere", got["error"])

    def test_changes_by_words(self):
        self.call("day_plan")
        code, got = self.call("day_change", {"floor": "Tidepool", "words": "drop the second one"})
        self.assertEqual(code, 200, got)
        self.assertEqual(got["said"], 'Dropped "Order rain gauges" from Tidepool\'s plan.')
        self.assertEqual(self.titles(got["day"], "Tidepool"), ["Calibrate the wind sensor", "Tidy the field notes"])
        code, got = self.call("day_change", {"words": "add: tidy the README on Lantern"})
        self.assertEqual(code, 200, got)
        self.assertEqual(self.titles(got["day"], "Lantern")[-1], "Tidy the README")
        self.assertEqual(got["day"]["plan"][0]["items"][-1]["source"], "added")
        code, got = self.call("day_change", {"floor": "lantern", "words": "do the third one first"})
        self.assertEqual(self.titles(got["day"], "Lantern")[0], "Tidy the README")
        code, got = self.call("day_change", {"words": "add to the plan fix the login on tidepool"})
        self.assertEqual(self.titles(got["day"], "Tidepool")[-1], "Fix the login")
        code, got = self.call("day_change", {"floor": "Tidepool", "words": "drop the field notes one"})
        self.assertEqual(code, 200, got)
        self.assertNotIn("Tidy the field notes", self.titles(got["day"], "Tidepool"))
        code, got = self.call("day_change", {"words": "drop the first one"})
        self.assertEqual(code, 400)
        self.assertIn("On which floor?", got["error"])
        code, got = self.call("day_change", {"floor": "Tidepool", "words": "drop the ninth one"})
        self.assertEqual(code, 400)
        code, got = self.call("day_change", {"floor": "Tidepool", "words": "make it purple"})
        self.assertEqual(code, 400)
        self.assertIn("I can drop one", got["error"])
        # making the plan again keeps what was added and leaves out what was dropped
        code, got = self.call("day_plan")
        self.assertEqual(self.titles(got["day"], "Tidepool"), ["Calibrate the wind sensor", "Next step toward: A kit anyone can build", "Fix the login"])
        self.assertIn("Tidy the README", self.titles(got["day"], "Lantern"))
        # added to an approved floor: approved with the rest, and it starts in its turn
        self.hold()
        self.call("day_approve", {"floors": ["Lantern"]})
        code, got = self.call("day_change", {"words": "add: write the changelog on Lantern"})
        self.assertIn("approved with the rest", got["said"])
        self.assertEqual(got["day"]["plan"][0]["items"][-1]["state"], "approved")
        code, got = self.call("day_change", {"floor": "Lantern", "words": "drop the first one"})
        self.assertEqual(code, 400)
        self.assertIn("has started already", got["error"])

    def test_words_with_a_secret_are_never_added(self):
        import intake
        self.call("day_plan")
        before = json.dumps(self.call("day")[1])
        token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # made up, in a GitHub token's shape (built in two, for scanners)
        aws = "AKIA" + "IOSFODNN7EXAMPLE"  # AWS's own documentation example, built in two
        for words in (f"add: put {token} in the deploy script on Lantern", f"add: use the key {aws} for the backups on Tidepool",
                      f"add: put {token} in the deploy script"):  # no floor: never said back in "On which floor?"
            code, got = self.call("day_change", {"words": words})
            self.assertEqual((code, got["error"]), (400, intake.SECRET_SAID), words)  # the front door's own words
        self.assertEqual(json.dumps(self.call("day")[1]), before)  # nothing was added
        for name in os.listdir(os.path.join(self.data, "day")):
            with open(os.path.join(self.data, "day", name), encoding="utf-8") as handle:
                kept = handle.read()
            self.assertNotIn(token, kept)
            self.assertNotIn(aws, kept)
        code, got = self.call("day_change", {"words": "add: rotate the deploy token on Lantern"})  # naming one is fine
        self.assertEqual(code, 200, got)

    def test_never_while_paused_or_over_budget(self):
        self.hold()
        self.call("day_plan")
        self.control.box.pause()
        code, got = self.call("day_approve")
        self.assertEqual(code, 200, got)
        self.assertIn("Every agent is paused, so nothing starts", got["said"])
        self.assertEqual(self.control.runs, {})
        self.assertIn("paused", self.floor(got["day"], "Lantern")["items"][0]["waiting"])
        self.control.box.resume()
        self.assertEqual(len(day.step(self.data, self.control)), 2)
        self.assertNotIn("waiting", self.floor(day.view(self.data), "Lantern")["items"][0])
        # a floor past its budget for today: its next item waits
        self.release()
        self.wait_done()
        today = datetime.date.today().isoformat()
        self.company["budget"] = 1000
        self.save("company.json", self.company)
        self.feed([{"id": "cc-bbbbbbbbbbbb", "project": "Lantern", "title": "t", "spent": {"day": today, "tokens": 5000}}])
        time.sleep(5.1)
        day.step(self.data, self.control)
        v = day.view(self.data)
        self.assertEqual(self.states(v, "Lantern"), ["done", "approved"])
        self.assertIn("used today's budget", self.floor(v, "Lantern")["items"][1]["waiting"])
        self.assertEqual(self.states(v, "Tidepool")[:2], ["done", "started"])  # Tidepool spent nothing: it goes on

    def test_a_missed_plan_time_makes_the_plan_when_the_page_next_reads(self):
        self.switches({"daily_cycle": True, "day_plan": "00:00", "day_close": "23:59"})
        self.assertEqual(day.due(self.data), "plan")
        self.assertIsNone(day.load(self.data, day.today()))
        state = self.control.state()  # the page's read every few seconds
        self.assertTrue(state["day"]["made"])
        self.assertEqual(state["day"]["plan_at"], "00:00")
        self.assertIsNone(day.due(self.data))
        made = state["day"]["made"]
        day._LAST.clear()
        code, got = self.call("day")
        self.assertEqual(code, 200)
        self.assertEqual(got["made"], made)  # once a day: read again, it isn't made again
        # before its time, nothing is made
        os.remove(day.path_of(self.data, day.today()))
        self.switches({"daily_cycle": True, "day_plan": "23:59", "day_close": "23:59"})
        day._LAST.clear()
        if datetime.datetime.now().strftime("%H:%M") < "23:59":
            self.assertIsNone(self.control.state()["day"]["made"])
        # serve.py's own look, with control off: the plan is made, and nothing starts
        self.switches({"daily_cycle": True, "day_plan": "00:00", "day_close": "23:59"})
        self.assertEqual(day.tick(self.data, None), ["plan"])
        self.assertEqual(day.tick(self.data, None), [])

    def test_the_close(self):
        now = time.time()
        today = datetime.date.today().isoformat()
        self.hold()
        self.call("day_plan")
        self.control.box.pause()
        self.call("day_approve", {"floors": ["Lantern"]})
        self.feed([{"id": "cc-cccccccccccc", "project": "Lantern", "title": "Bookmark fix", "proof": {"state": "passed", "at": now - 60},
                    "spent": {"day": today, "tokens": 1200000}},
                   {"id": "cc-dddddddddddd", "project": "Tidepool", "title": "Sensor drift", "proof": {"state": "failed", "at": now - 60, "tail": "3 of 9 tests failed"},
                    "spent": {"day": today, "tokens": 300000}},
                   {"id": "cc-eeeeeeeeeeee", "project": "Tidepool", "title": "Old work", "proof": {"state": "passed", "at": now - 3 * 86400}}])
        self.control.box.question("cc-cccccccccccc", "words", "Which badge should I use?", more={"project": "Lantern", "title": "Bookmark fix"})
        code, got = self.call("day_close")
        self.assertEqual(code, 200, got)
        close = got["day"]["close"]
        self.assertEqual(close["proven"], [{"floor": "Lantern", "title": "Bookmark fix"}])
        stuck = {(s["floor"], s["title"]): s["why"] for s in close["stuck"]}
        self.assertIn("3 of 9 tests failed", stuck[("Tidepool", "Sensor drift")])
        self.assertIn("paused", stuck[("Lantern", "Write the notes for version 2")])
        tomorrow = {(t["floor"], t["title"]): t["why"] for t in close["tomorrow"]}
        self.assertEqual(tomorrow[("Lantern", "Pick a badge")], "Two designs are ready.")
        self.assertEqual(tomorrow[("Lantern", "Bookmark fix")], "It asks: Which badge should I use?")
        self.assertEqual(tomorrow[("Tidepool", "Calibrate the wind sensor")], "Proposed today and not approved.")
        self.assertEqual(close["cost"]["total"], 1500000)
        self.assertIn("1.5 million new tokens today: Lantern 1.2 million tokens, Tidepool 300 thousand tokens.", close["cost"]["words"])
        self.assertTrue(close["words"].startswith("Today: 1 piece of work proven, 3 stuck, 5 things need you tomorrow. 1.5 million new tokens."), close["words"])
        # at the close time it is made by itself, once
        self.switches({"daily_cycle": True, "day_plan": "00:00", "day_close": "00:00"})
        os.remove(day.path_of(self.data, day.today()))
        self.assertEqual(day.tick(self.data, None), ["plan", "close"])
        self.assertEqual(day.tick(self.data, None), [])

    # ---------- the front door, when it is there ----------

    def test_through_the_front_door_when_it_is_there(self):
        self.hold()
        front = FrontDoor(self.data, claude=self.fake)
        front.ready = [{"id": "rd1", "project": "Tidepool", "title": "Make the login faster", "state": "ready"}]
        day.make_plan(self.data, front)
        code, got = self.call("day_approve", ctrl=front)
        self.assertEqual(code, 200, got)
        self.assertEqual(self.states(got["day"], "Tidepool"), ["started", "approved", "approved"])
        kinds = [c[0] for c in front.calls]
        self.assertEqual(kinds.count("ready_start"), 2)
        self.assertEqual(kinds.count("intake"), 1)  # Lantern's first item is shaped at the front door first
        self.assertEqual(next(c[1] for c in front.calls if c[0] == "ready_start" and c[1]["id"] == "rd1"), {"id": "rd1"})
        self.assertEqual(next(c[1]["project"] for c in front.calls if c[0] == "intake"), "Lantern")
        tide = next(it for f in day.load(self.data, day.today())["plan"] for it in f["items"] if it.get("ready") == "rd1")
        self.assertEqual(tide["how"], "front door")
        self.assertTrue(tide["key"].startswith("cc-"))
        # with the front door switched off, Control.start does it
        self.switches({"daily_cycle": True, "front_door": False})
        self.assertEqual(day.start_item(self.control, {"floor": "Lantern", "label": "Lantern"}, {"text": "Tidy up", "ready": "rd9"})[1], "start")

    def test_the_real_front_door_starts_a_ready_task_once_and_gives_its_key(self):
        """This Arnheim's own front door (connect/intake.py): an approved ready task starts once, through ready_start,
        and the plan follows its agent by its key; an item that wasn't a ready task becomes one once, keeps the plan's
        title and floor, and the new agent's words say it is on today's plan."""
        self.hold()
        code, got = self.call("intake", {"text": "Make the login faster on Tidepool", "via": "box"})
        self.assertEqual(code, 200, got)
        rid = got["task"]["id"]
        day.make_plan(self.data, self.control)
        tide = self.floor(day.view(self.data), "Tidepool")
        self.assertEqual(tide["items"][0]["title"], "Make the login faster")
        code, got = self.call("day_approve")
        self.assertEqual(code, 200, got)
        task = self.control.intake.task(rid)
        self.assertEqual(task["state"], "started")
        doc = day.load(self.data, day.today())
        item = next(it for f in doc["plan"] for it in f["items"] if it.get("ready") == rid)
        self.assertEqual((item["state"], item["key"], item["how"]), ("started", task["key"], "front door"))
        lantern = next(f for f in doc["plan"] if f["floor"] == "Lantern")["items"][0]
        self.assertEqual(lantern["state"], "started")
        made = self.control.intake.task(lantern["ready"])  # made at the front door for it, on the plan's floor, with its title
        self.assertEqual((made["project"], made["title"], made["state"], made["key"]), ("Lantern", lantern["title"], "started", lantern["key"]))
        self.assertEqual(sorted(s["cwd"] for s in self.wait_for_starts(2)), sorted([self.lantern, self.tidepool]))
        self.assertIn("one item on today's plan for the Lantern floor", next(s["words"] for s in self.started() if s["cwd"] == self.lantern))
        # looking again starts nothing more, and makes no second ready task
        self.assertEqual(day.step(self.data, self.control), [])
        self.assertEqual(len(self.control.runs), 2)
        self.assertEqual(len(self.control.intake.tasks()), 2)

    def test_a_queued_ready_task_waits_and_the_plan_follows_it_when_the_queue_starts_it(self):
        """Another agent from the building at work on the floor: the front door queues the item, the plan says why and
        never marks it done, and when the queue starts it the plan follows that agent (started once)."""
        self.hold()
        other = self.control.start("Tidepool", "Something else first")
        code, got = self.call("intake", {"text": "Make the login faster on Tidepool", "via": "box"})
        rid = got["task"]["id"]
        day.make_plan(self.data, self.control)
        self.call("day_approve", {"floors": ["Tidepool"]})
        item = lambda: next(it for f in day.load(self.data, day.today())["plan"] for it in f["items"] if it.get("ready") == rid)  # noqa: E731
        self.assertEqual(self.control.intake.task(rid)["state"], "queued")
        self.assertEqual(item()["state"], "approved")
        self.assertIn("at work on Tidepool", item()["waiting"])
        time.sleep(5.1)
        day.step(self.data, self.control)
        self.assertEqual(item()["state"], "approved")  # still waiting its turn, not done
        self.release()
        self.wait_done()
        until = time.time() + 15
        while self.control.intake.task(rid)["state"] not in ("started", "finished") and time.time() < until:
            time.sleep(0.05)
        task = self.control.intake.task(rid)
        self.assertIn(task["state"], ("started", "finished"))  # the stand-in agent may have finished already
        self.assertNotEqual(task["key"], other["key"])
        day.step(self.data, self.control)
        self.assertEqual((item()["state"], item()["key"]), ("started", task["key"]))
        self.assertEqual(sum(1 for s in self.started() if "login faster" in s["words"].lower()), 1)

    def test_start_ready_tasks_by_themselves_never_starts_an_item_twice(self):
        self.switches({"daily_cycle": True, "ready_auto": True})
        self.hold()
        day.make_plan(self.data, self.control)
        self.call("day_approve", {"floors": ["Lantern"]})
        lantern = next(f for f in day.load(self.data, day.today())["plan"] if f["floor"] == "Lantern")["items"][0]
        self.assertEqual(lantern["state"], "started")
        self.assertEqual(self.control.intake.task(lantern["ready"])["key"], lantern["key"])
        self.wait_for_starts(1)
        time.sleep(0.5)
        self.assertEqual(len(self.started()), 1)
        self.assertEqual(len(self.control.runs), 1)

    # ---------- the phone, the switch and the times ----------

    def test_the_phone_reaches_it_through_control(self):
        import serve
        self.assertIn("day", serve.READS)
        for name in day.NAMES:
            self.assertRegex(name, r"^[a-z][a-z_]{0,15}$")  # what another page that loads these modules passes on
        code, got = self.call("day_plan")
        self.assertEqual(code, 200)
        code, _, raw, _ = self.control.handle("POST", "day", b"{}", "not the token")
        self.assertEqual(code, 403)
        code, got = self.call("day")
        self.assertEqual(code, 200)
        self.assertEqual(got["date"], day.today())

    def test_switched_off_it_shows_and_does_nothing(self):
        self.switches({"daily_cycle": False, "day_plan": "00:00"})
        self.assertIsNone(self.control.state()["day"])
        code, got = self.call("day_plan")
        self.assertEqual(code, 400)
        self.assertIn("switched off", got["error"])
        self.assertEqual(day.tick(self.data, self.control), [])
        self.assertFalse(os.path.exists(os.path.join(self.data, "day", day.today() + ".json")))
        self.switches({})
        self.assertIsNone(self.control.state()["day"])  # off unless you switch it on
        self.assertFalse(dict((s[0], s[4]) for s in __import__("switches").SWITCHES)["daily_cycle"])

    def test_the_times_are_yours(self):
        code, got = self.call("day_times", {"plan": "8:30", "close": "17:45"})
        self.assertEqual(code, 200, got)
        self.assertEqual((got["day"]["plan_at"], got["day"]["close_at"]), ("08:30", "17:45"))
        with open(os.path.join(self.data, "serve.json"), encoding="utf-8") as handle:
            kept = json.load(handle)
        self.assertEqual(kept, {"daily_cycle": True, "day_plan": "08:30", "day_close": "17:45"})
        code, got = self.call("day_times", {"plan": "25:00"})
        self.assertEqual(code, 400)
        self.assertEqual(day.times_of(self.data), {"day_plan": "08:30", "day_close": "17:45"})

    def test_the_command_line(self):
        env = dict(os.environ, ARNHEIM_DATA=self.data)
        done = subprocess.run([sys.executable, os.path.join(ROOT, "connect", "day.py"), "--plan"], capture_output=True, text=True, env=env, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Lantern:", done.stdout)
        self.assertIn("1. Write the notes for version 2 [proposed]", done.stdout)
        done = subprocess.run([sys.executable, os.path.join(ROOT, "connect", "day.py"), "--show"], capture_output=True, text=True, env=env, timeout=30)
        self.assertIn("No forecast", done.stdout)


PAGE = """
import { pathToFileURL } from 'node:url';
const d = await import(pathToFileURL(process.argv[1] + '/src/day.js').href);
const fs = await import('node:fs');
const sample = JSON.parse(fs.readFileSync(process.argv[1] + '/sample/day.json', 'utf8'));
const v = d.sampleDay(sample, new Date(2026, 10, 21, 10, 0).getTime() / 1000);
const lead = { project: 'Tidepool', label: 'Tidepool', lead: { name: 'Marlo' } };
const asked = (t) => d.dayIntent(t)?.kind || null;
const approved = d.sampleApprove(v, null);
const one = d.sampleApprove(v, ['Lantern']);
const dropped = d.sampleChange(v, 'Tidepool', 'drop the second one');
const added = d.sampleChange(v, null, 'add: tidy the README on Lantern');
const moved = d.sampleChange(v, 'Kitefield', 'do the second one first');
console.log(JSON.stringify({
  intents: ["what's the plan?", "What's today's plan", 'approve the day', 'Approve the plan please', 'how did today go?',
    'how was the day', 'drop the second one on Tidepool', 'add: tidy the README on Lantern', 'add to the plan fix the login',
    'make the plan', 'what is the weather', 'add a dark mode to Lantern', 'approve it'].map(asked),
  floorIn: [d.floorIn('approve the day on Tidepool', v.plan), d.floorIn("approve Kitefield's day", v.plan), d.floorIn('approve the day', v.plan)],
  plan: d.sayPlan(v), floorPlan: d.sayPlan(v, lead), close: d.sayClose(v.close), none: d.sayPlan({ ...v, made: null, plan: [] }),
  counts: d.planCount(v), alert: d.planAlert(v), closeAlert: d.closeAlert(v),
  approved: [approved.approved, approved.plan.map((f) => f.items.map((i) => i.state).join(','))],
  one: [one.approved, one.plan.map((f) => !!f.approved)],
  dropped: [dropped.said, dropped.day.plan.find((f) => f.label === 'Tidepool').items.filter((i) => i.state !== 'dropped').length],
  added: [added.said, added.day.plan.find((f) => f.label === 'Lantern').items.at(-1).title],
  moved: moved.day.plan.find((f) => f.label === 'Kitefield').items[0].title,
  madeUp: v.sample,
}));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DayFilesStayHereTest(unittest.TestCase):
    """data/day/ (your plan in your words) and data/control/ (with the decisions the leads answer from) go to this computer
    only: never over --lan, a view-only link or to a paired phone, which reads today's plan through /control/day."""

    @classmethod
    def setUpClass(cls):
        import threading
        sys.path.insert(0, ROOT)
        import serve
        from connect import remote
        cls.serve, cls.remote = serve, remote
        cls.base = tempfile.TemporaryDirectory()
        for name, text in (("index.html", "<!doctype html><title>Arnheim</title>"), ("data/company.json", '{"company": "Example Studio"}'),
                           ("data/day/2026-11-21.json", '{"plan": "private"}'), ("data/control/decisions.json", '{"decisions": "private"}'),
                           ("data/decisions.json", '{"decisions": "private, from before"}')):
            os.makedirs(os.path.dirname(os.path.join(cls.base.name, name)), exist_ok=True)
            with open(os.path.join(cls.base.name, name), "w", encoding="utf-8") as handle:
                handle.write(text)
        cls.root = serve.ROOT
        serve.ROOT = os.path.realpath(cls.base.name)

        class Away(serve.Handler):  # a request marked "away" stands for one from another computer
            def here(self):
                return self.headers.get("X-Test-From") != "away" and super().here()
        cls.server = serve.Server(("127.0.0.1", 0), Away)
        cls.server.lan = True
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.serve.ROOT = cls.root
        cls.server.shutdown()
        cls.server.server_close()
        cls.base.cleanup()

    def ask(self, path, headers=None):
        import http.client
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}", **(headers or {})})
            reply = conn.getresponse()
            return reply.status, reply.read()
        finally:
            conn.close()

    def test_only_this_computer(self):
        kept = ("/data/day/2026-11-21.json", "/data/Day/2026-11-21.json", "/data/DAY/2026-11-21.json", "/data/%64ay/2026-11-21.json",
                "/data/control/decisions.json", "/data/Control/decisions.json", "/data/decisions.json", "/data/Decisions.json")
        for path in kept[:1] + kept[4:5] + kept[6:7]:
            self.assertEqual(self.ask(path)[0], 200, path)  # this computer
        for path in kept:
            status, body = self.ask(path, {"X-Test-From": "away"})  # --lan: another computer
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"private", body)
        self.server.share = "k" * 32  # --share: even with the view-only link's key
        try:
            viewer = {"X-Test-From": "away", "Cookie": f"arnheim_view={'k' * 32}"}
            for path in kept:
                self.assertEqual(self.ask(path, viewer)[0], 404, path)
            self.assertEqual(self.ask("/data/company.json", viewer)[0], 200)
        finally:
            self.server.share = None
        self.server.remote = self.remote.Remote("mac.example-tailnet.ts.net", self.base.name)  # a paired phone: never the files
        try:
            self.server.remote.code()
            key, _ = self.server.remote.pair(self.server.remote.pending["code"])
            phone = {"Host": "mac.example-tailnet.ts.net", "X-Forwarded-For": "100.64.0.7", "Cookie": f"{self.remote.COOKIE}={key}"}
            self.assertEqual(self.ask("/data/company.json", phone)[0], 200)
            for path in kept:
                self.assertEqual(self.ask(path, phone)[0], 404, path)
        finally:
            self.server.remote = None


REDRAW = """
import { pathToFileURL } from 'node:url';
globalThis.setInterval = () => 0; // the page's background read: not in a test
const { createDay } = await import(pathToFileURL(process.argv[1] + '/src/day-page.js').href);
let changed = 0;
let watcher = null;
const page = createDay({ where: () => 'phone', changed: () => { changed += 1; }, alerts: { on: () => false },
  control: { on: true, watch: (f) => { watcher = f; }, dayNow: () => null } });
page.start();
const at = (made, state) => ({ day: { on: true, date: '2026-11-22', made, approved: false, close: null, night: null,
  plan: made ? [{ floor: 'Lantern', label: 'Lantern', items: [{ id: 'i1', title: 'Tidy the README', state }] }] : [] } });
const counts = [];
for (const s of [at(null), at(null), at(1795338000, 'proposed'), at(1795338000, 'proposed'), at(1795338000, 'started'), { day: null }]) {
  watcher(s);
  counts.push(changed);
}
console.log(JSON.stringify(counts));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DayPageRedrawTest(unittest.TestCase):
    def test_the_page_is_drawn_again_when_the_day_changes(self):
        # found after the night shift's trial: the day page only alerted, so a plan the server made at 09:00, or an item
        # starting, stayed off the page until something else changed
        done = subprocess.run([NODE, "--input-type=module", "-e", REDRAW, ROOT], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), [0, 0, 1, 1, 2, 3])


class DailyCycleWordsTest(unittest.TestCase):
    def test_the_page_words_and_the_made_up_day(self):
        done = subprocess.run([NODE, "--input-type=module", "-e", PAGE, ROOT], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(out["intents"], ["plan", "plan", "approve", "approve", "close", "close", "change", "change", "change", "make", None, None, None])
        self.assertEqual(out["floorIn"], ["Tidepool", "Kitefield", None])
        self.assertIn("Today's plan: 7 things on 4 floors.", out["plan"])
        self.assertIn("This day is made up", out["plan"])
        self.assertTrue(out["floorPlan"].startswith("Here's Tidepool's plan for today: 1. "), out["floorPlan"])
        self.assertIn("Approve it, or tell me what to change.", out["floorPlan"])
        self.assertIn("proven", out["close"])
        self.assertIn("tokens", out["close"])
        self.assertIn("comes at 09:00", out["none"])
        self.assertEqual(out["counts"], {"items": 7, "floors": 4})
        self.assertEqual(out["alert"]["body"], "Today's plan is ready: 7 things on 4 floors.")
        self.assertIn("Today", out["closeAlert"]["body"])
        self.assertTrue(out["approved"][0])
        self.assertTrue(all(set(s.split(",")) <= {"approved"} for s in out["approved"][1]), out["approved"])
        self.assertFalse(out["one"][0])
        self.assertEqual(out["dropped"][1], 1)
        self.assertIn("Dropped", out["dropped"][0])
        self.assertEqual(out["added"][1], "Tidy the README")
        self.assertTrue(out["madeUp"])

    def test_the_page_code_parses(self):
        for name in ("day.js", "day-page.js", "demo.js", "control.js"):
            done = subprocess.run([NODE, "--check", os.path.join(ROOT, "src", name)], capture_output=True, text=True, timeout=30)
            self.assertEqual(done.returncode, 0, f"{name}: {done.stderr}")

    def test_no_inline_styles_and_plain_words(self):
        with open(os.path.join(ROOT, "src", "day-page.js"), encoding="utf-8") as handle:
            page = handle.read()
        self.assertNotIn("style:", page)
        self.assertNotIn(".style", page)
        for name in ("src/day.js", "src/day-page.js", "sample/day.json"):
            with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
                text = handle.read()
            self.assertNotIn(chr(0x2014), text, name)  # no long dashes in what people read
        with open(os.path.join(ROOT, "sample", "day.json"), encoding="utf-8") as handle:
            self.assertNotRegex(handle.read(), r"\w - \w")  # nor a short one used as a dash


if __name__ == "__main__":
    unittest.main()
