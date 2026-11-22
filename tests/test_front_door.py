"""One front door (connect/intake.py, src/front-door.js; docs/connect.md, "One front door"): words become a ready
task for a floor, with Done when, Proven by, its agent and an estimate only from real data; Start, the queue, the
switch that starts them by themselves and what it never starts; the sweep; a phone through control; the files never
served; the sample's cards; and the page's rules for what is work.

A stand-in for Claude Code's `claude` command answers for real agents. Each test makes a company of its own in a
temporary folder, so your data/ is never touched. Run from the repository's folder: python3 -m unittest discover tests
"""
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connect"))
NODE = shutil.which("node")

import control  # noqa: E402  (after the path is set)
import intake  # noqa: E402
import switches  # noqa: E402

# Stands in for `claude -p`: says its words back. Words with "hold-on" in them keep it at work while the file named
# by FD_HOLD is there.
FAKE = r'''
import json, os, sys, time
args = sys.argv[1:]
words = sys.stdin.read()
sid = args[args.index("--session-id") + 1] if "--session-id" in args else args[args.index("--resume") + 1]
print(json.dumps({"type": "system", "subtype": "init", "session_id": sid}), flush=True)
end = time.time() + 20
while "hold-on" in words.lower() and os.path.exists(os.environ.get("FD_HOLD", "")) and time.time() < end:
    time.sleep(0.05)
print(json.dumps({"type": "result", "result": "done: " + words[:4000], "session_id": sid}), flush=True)
'''


class FrontDoorTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.data = os.path.join(self.base, "data")
        self.tide = os.path.realpath(os.path.join(self.base, "code", "tidepool"))
        self.lantern = os.path.realpath(os.path.join(self.base, "code", "lantern"))
        for folder in (self.data, self.tide, self.lantern):
            os.makedirs(folder)
        self.company = {
            "company": "Example Studio",
            "rooms": [{"id": "work", "label": "Work"}, {"id": "conversations", "label": "Conversations"}],
            "floors": [{"id": "tidepool", "label": "Tidepool", "folder": self.tide, "check": {"run": ["make", "test"], "label": "The tests"}},
                       {"id": "lantern", "label": "Lantern", "folder": self.lantern},
                       {"id": "studio", "label": "Studio"}],
            "feeds": ["feeds/claude-code.json"],
        }
        self.keep_company()
        fake = os.path.join(self.base, "fake_claude.py")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE)
        self.hold = os.path.join(self.base, "hold")
        os.environ["FD_HOLD"] = self.hold
        self.control = control.Control(self.data, claude=[sys.executable, fake])

    def tearDown(self):
        try:
            os.remove(self.hold)
        except OSError:
            pass
        for run in list(self.control.runs.values()):
            self.until(lambda: not self.control.alive(run))
        shutil.rmtree(self.base)

    def keep_company(self):
        with open(os.path.join(self.data, "company.json"), "w", encoding="utf-8") as handle:
            json.dump(self.company, handle)

    def call(self, name, body=None, method="POST"):
        code, _, data, _ = self.control.handle(method, name, b"" if body is None else json.dumps(body).encode(), self.control.token)
        return code, json.loads(data)

    def take(self, text, **more):
        code, got = self.call("intake", {"text": text, **more})
        self.assertEqual(code, 200, got)
        return got

    def until(self, check, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            got = check()
            if got:
                return got
            time.sleep(0.05)
        self.fail("it never happened")

    def stored(self, tid):
        with open(os.path.join(self.data, "control", "intake", tid + ".json"), encoding="utf-8") as handle:
            return json.load(handle)

    def state(self):
        self.control.intake.ticked = 0  # look at the queue now, not in two seconds
        return self.call("state", method="GET")[1]

    # ---------- shaping ----------

    def test_words_become_a_ready_task(self):
        got = self.take("the login feels slow on Tidepool", via="talk")
        task = got["task"]
        self.assertEqual(task["project"], "Tidepool")
        self.assertEqual(task["title"], "The login feels slow")
        self.assertEqual(task["done_when"], "What you asked for is done, and the tests pass.")
        self.assertEqual(task["proven_by"], "The tests: make test")
        self.assertEqual(task["agent"], "Claude Code")
        self.assertIsNone(task["estimate"])  # no finished work here yet: no estimate, never a guess
        self.assertEqual((task["state"], task["key"], task["via"]), ("ready", None, "talk"))
        self.assertEqual(got["reply"], 'Ready on Tidepool: "The login feels slow". It counts as done when the tests pass. Start it?')
        self.assertTrue(intake.TASK_ID.match(task["id"]))
        kept = self.stored(task["id"])
        self.assertEqual(kept["text"], "the login feels slow on Tidepool")
        self.assertEqual([r["id"] for r in self.state()["ready"]], [task["id"]])

    def test_titles_by_rule(self):
        for words, title in (("Get someone to fix the login bug on the menu on Tidepool", "Fix the login bug on the menu"),
                             ("can you speed up the search page on Tidepool, please?", "Speed up the search page"),
                             ("have an agent on Lantern tidy the rain gauge code", "Tidy the rain gauge code"),
                             ("We need to add a dark mode to the settings on Lantern.", "Add a dark mode to the settings"),
                             ("Tidepool: the export button does nothing", "The export button does nothing")):
            self.assertEqual(self.take(words)["task"]["title"], title, words)
        long = self.take("on Lantern rewrite the whole onboarding flow so that new people see the three steps one at a time with pictures")
        self.assertLessEqual(len(long["task"]["title"]), intake.TITLE_MOST)
        self.assertTrue(long["task"]["title"].endswith("…"))

    def test_proven_by_the_projects_own_tests_or_you_look(self):
        task = self.take("the menu is too slow on Lantern")["task"]
        self.assertEqual((task["proven_by"], task["done_when"]), ("You look at it", "What you asked for is done, and you have looked at it."))
        self.assertIn("once you've looked at it", self.take("fix the footer on Lantern")["reply"])
        with open(os.path.join(self.lantern, "package.json"), "w", encoding="utf-8") as handle:
            json.dump({"scripts": {"test": "node --test"}}, handle)
        self.assertEqual(self.take("fix the footer on Lantern")["task"]["proven_by"], "The tests: npm test")  # as setup finds it

    def test_the_floor_says_which_agent(self):
        self.company["floors"][1]["agent"] = "Codex"
        self.keep_company()
        self.assertEqual(self.take("fix the footer on Lantern")["task"]["agent"], "Codex")
        self.assertEqual(self.take("fix the footer on Tidepool")["task"]["agent"], "Claude Code")

    def test_an_estimate_only_from_finished_work(self):
        history = os.path.join(self.data, "feeds", "history")
        os.makedirs(history)
        now = time.time() - 3 * 3600
        moments = []
        for i, minutes in enumerate((10, 20, 40)):
            moments += [{"at": now + i * 3000, "key": f"cc-done{i}", "project": "Tidepool", "kind": "working"},
                        {"at": now + i * 3000 + 600, "key": f"cc-done{i}", "project": "Tidepool", "kind": "changed"},
                        {"at": now + i * 3000 + minutes * 60, "key": f"cc-done{i}", "project": "Tidepool", "kind": "finished"}]
        moments.append({"at": now, "key": "cc-other", "project": "Lantern", "kind": "working"})
        with open(os.path.join(history, "2026-11-20.json"), "w", encoding="utf-8") as handle:
            json.dump({"moments": moments[:6]}, handle)
        self.assertIsNone(self.take("fix the footer on Tidepool")["task"]["estimate"])  # two finished: not yet
        with open(os.path.join(history, "2026-11-21.json"), "w", encoding="utf-8") as handle:
            json.dump({"moments": moments[6:]}, handle)
        self.assertEqual(self.take("fix the footer on Tidepool")["task"]["estimate"], {"minutes": 20, "tokens": None, "from": 3})
        os.makedirs(os.path.join(self.data, "feeds"), exist_ok=True)
        with open(os.path.join(self.data, "feeds", "claude-code.json"), "w", encoding="utf-8") as handle:
            json.dump({"conversations": [{"id": "cc-done0", "project": "Tidepool", "spent": {"tokens": 100000}},
                                         {"id": "cc-done1", "project": "Tidepool", "spent": {"tokens": 300000}}],
                       "ended": {"day": "2026-11-21", "talks": {"cc-done2": {"project": "Tidepool", "tokens": 200000}}}}, handle)
        self.assertEqual(self.take("fix the footer on Tidepool")["task"]["estimate"], {"minutes": 20, "tokens": 200000, "from": 3})
        self.assertIsNone(self.take("fix the footer on Lantern")["task"]["estimate"])

    # ---------- which floor ----------

    def test_which_floor(self):
        self.assertEqual(self.take("the login feels slow on Tidepool", floor="lantern")["task"]["project"], "Tidepool")  # named first
        self.assertEqual(self.take("Tidepool's export is broken", floor="lantern")["task"]["project"], "Tidepool")
        self.assertEqual(self.take("the export is broken", floor="lantern")["task"]["project"], "Lantern")  # the floor you are on
        self.assertEqual(self.take("the export is broken on tide")["task"]["project"], "Tidepool")  # guessed
        asked = self.take("the export is broken")
        self.assertIsNone(asked["task"])
        self.assertEqual(asked["reply"], "Which floor is that for? Tidepool or Lantern.")
        self.assertEqual(asked["floors"], ["Tidepool", "Lantern"])
        code, got = self.call("intake", {"text": "the export is broken", "floor": "studio"})
        self.assertEqual(code, 400)
        self.assertIn("has no folder on this computer", got["error"])
        self.company["floors"] = self.company["floors"][1:]
        self.keep_company()
        self.assertEqual(self.take("the export is broken")["task"]["project"], "Lantern")  # the only one

    # ---------- refused ----------

    def test_secrets_and_what_is_never_handed_out(self):
        token = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"  # made up, in a GitHub token's shape (built in two, for scanners)
        for words in ("fix the login on Tidepool, the password is hunter2-Xq9Lw3PzT7", f"use token {token} on Tidepool"):
            code, got = self.call("intake", {"text": words})
            self.assertEqual((code, got["error"]), (400, intake.SECRET_SAID), words)
        code, got = self.call("intake", {"text": "buy a new domain for Tidepool"})
        self.assertEqual((code, got["error"]), (400, intake.NEVER_SAID))
        self.assertFalse(os.path.isdir(os.path.join(self.data, "control", "intake")) and os.listdir(os.path.join(self.data, "control", "intake")))
        self.assertEqual(self.call("intake", {"text": ""})[0], 400)
        self.assertEqual(self.call("intake", {"text": "x" * 2001})[0], 400)
        switches.save("front_door", False, self.data)
        code, got = self.call("intake", {"text": "fix the footer on Tidepool"})
        self.assertEqual(code, 400)
        self.assertIn("switched off", got["error"])
        self.assertEqual(self.state()["ready"], [])

    # ---------- start, the queue ----------

    def test_start_hands_over_done_when_and_proven_by(self):
        task = self.take("the login feels slow on Tidepool")["task"]
        code, got = self.call("ready_start", {"id": task["id"]})
        self.assertEqual(code, 200, got)
        self.assertTrue(got["reply"].startswith('Started on Tidepool: "The login feels slow".'))
        self.assertEqual(got["task"]["state"], "started")
        key = got["task"]["key"]
        run = self.control.runs[key]
        self.assertEqual((run["title"], run["ready"], run["project"]), ("The login feels slow", task["id"], "Tidepool"))
        said = self.until(lambda: self.control.runs[key].get("said"))
        for part in ("The login feels slow on Tidepool", "Done when: What you asked for is done, and the tests pass.",
                     "Proven by: The tests: make test. Before you say it is done, prove it: run make test yourself",
                     "You were started from Arnheim"):
            self.assertIn(part, said)
        self.until(lambda: self.stored(task["id"])["state"] == "finished")
        self.assertEqual(self.stored(task["id"])["outcome"], "done")
        self.assertEqual(self.state()["ready"], [])
        self.assertEqual(self.call("ready_start", {"id": task["id"]})[0], 400)  # once

    def test_one_at_a_time_on_a_floor(self):
        open(self.hold, "w").close()
        first = self.take("hold-on: tidy the tests on Tidepool")["task"]
        second = self.take("fix the footer on Tidepool")["task"]
        other = self.take("fix the footer on Lantern")["task"]
        self.assertEqual(self.call("ready_start", {"id": first["id"]})[1]["task"]["state"], "started")
        got = self.call("ready_start", {"id": second["id"]})[1]
        self.assertEqual(got["task"]["state"], "queued")
        self.assertEqual(got["reply"], 'Queued on Tidepool: "Fix the footer". An agent started from the building is at work on Tidepool, '
                                       "so it starts when that one finishes.")
        self.assertEqual(self.call("ready_start", {"id": other["id"]})[1]["task"]["state"], "started")  # another floor
        ready = self.state()["ready"]
        self.assertEqual([(r["id"], r["state"]) for r in ready], [(second["id"], "queued")])
        os.remove(self.hold)  # the first finishes, and the next starts
        self.until(lambda: self.stored(second["id"])["state"] in ("started", "finished"))
        self.assertEqual(self.stored(first["id"])["state"], "finished")

    def test_paused_or_over_budget_waits_queued(self):
        task = self.take("fix the footer on Tidepool")["task"]
        self.control.box.pause()
        got = self.call("ready_start", {"id": task["id"]})[1]
        self.assertEqual((got["task"]["state"], got["task"]["why"]), ("queued", "Every agent is paused, so it starts when you resume them."))
        self.assertEqual(self.state()["ready"][0]["state"], "queued")  # still paused: it waits
        self.company["floors"][0]["budget"] = 1000
        self.keep_company()
        os.makedirs(os.path.join(self.data, "feeds"), exist_ok=True)
        with open(os.path.join(self.data, "feeds", "claude-code.json"), "w", encoding="utf-8") as handle:
            json.dump({"conversations": [{"id": "cc-spent", "project": "Tidepool", "spent": {"day": control.budget.local_day(), "tokens": 5000}}]}, handle)
        self.control.box.resume()
        self.assertEqual(self.state()["ready"][0]["why"], "Tidepool is over today's budget, so it starts once you let its agents go on.")
        self.call("allow_more", {"project": "Tidepool"})
        self.call("allow_more", {"project": "Tidepool"})
        self.call("allow_more", {"project": "Tidepool"})
        self.call("allow_more", {"project": "Tidepool"})
        self.call("allow_more", {"project": "Tidepool"})
        self.state()  # the queue moves on once it can
        self.until(lambda: self.stored(task["id"])["state"] in ("started", "finished"))

    def test_drop_and_change(self):
        task = self.take("fix the footer on Tidepool")["task"]
        code, got = self.call("ready_change", {"id": task["id"], "title": "Fix the footer links", "done_when": "Every footer link opens its page"})
        self.assertEqual(code, 200, got)
        self.assertEqual((got["task"]["title"], got["task"]["done_when"]), ("Fix the footer links", "Every footer link opens its page."))
        aws = "AKIA" + "IOSFODNN7EXAMPLQ"  # made up, in an AWS key's shape (built in two, for scanners)
        code, got = self.call("ready_change", {"id": task["id"], "done_when": f"the key is {aws} in prod"})
        self.assertEqual((code, got["error"]), (400, intake.SECRET_SAID))
        self.assertEqual(self.call("ready_change", {"id": task["id"], "title": "x"})[0], 400)
        self.assertEqual(self.call("ready_drop", {"id": task["id"]})[1]["task"]["state"], "dropped")
        self.assertEqual(self.state()["ready"], [])
        for name in ("ready_start", "ready_drop", "ready_change"):
            self.assertEqual(self.call(name, {"id": task["id"], "title": "Again"})[0], 400, name)
        self.assertEqual(self.call("ready_start", {"id": "../../serve"})[0], 400)

    # ---------- started by themselves ----------

    def test_the_switch_starts_them_by_themselves(self):
        self.assertFalse(switches.on("ready_auto", self.data))  # off unless you switch it on
        switches.save("ready_auto", True, self.data)
        open(self.hold, "w").close()
        got = self.take("hold-on: tidy the tests on Tidepool")
        self.assertEqual(got["task"]["state"], "started")
        self.assertTrue(got["reply"].startswith('Started on Tidepool by itself: "Hold-on: tidy the tests".'))
        nxt = self.take("fix the footer on Tidepool")  # one at a time on a floor
        self.assertEqual(nxt["task"]["state"], "queued")
        held = self.take("rotate the API key for the mailer on Tidepool")
        self.assertEqual((held["task"]["state"], held["task"]["held"]), ("ready", intake.HELD_SECRET))
        self.assertIn(intake.HELD_SECRET, held["reply"])
        final = self.take("merge the release branch on Lantern")
        self.assertEqual((final["task"]["state"], final["task"]["held"]), ("ready", intake.HELD_FINAL))
        os.remove(self.hold)
        self.until(lambda: self.stored(nxt["task"]["id"])["state"] in ("started", "finished"))
        self.assertEqual(self.stored(held["task"]["id"])["state"], "ready")  # never by itself
        self.control.box.pause()
        paused = self.take("fix the header on Lantern")
        self.assertEqual((paused["task"]["state"], paused["task"]["why"]), ("queued", "Every agent is paused, so it starts when you resume them."))
        self.control.box.resume()
        self.state()
        self.until(lambda: self.stored(paused["task"]["id"])["state"] in ("started", "finished"))
        started = self.call("ready_start", {"id": held["task"]["id"]})[1]  # your Start starts it
        self.assertIn(started["task"]["state"], ("started", "queued"))

    # ---------- the lead writes it, with the brain on ----------

    def test_the_lead_writes_it_and_it_is_checked(self):
        class Lead:
            said = {"title": "Speed up the slow login", "done_when": "Signing in takes under a second on a normal connection"}

            def shape(self, text, floor, wait=30):
                return dict(self.said)
        lead = Lead()
        self.control.brain = lead
        rules = self.take("the login feels slow on Tidepool")["task"]
        self.assertEqual(rules["title"], "The login feels slow")  # the brain is switched off: the rule's words
        switches.save("brain", True, self.data)
        got = self.take("the login feels slow on Tidepool")
        self.assertEqual((got["task"]["title"], got["task"]["done_when"]), ("Speed up the slow login", "Signing in takes under a second on a normal connection."))
        self.assertEqual(got["reply"], 'Ready on Tidepool: "Speed up the slow login". Done when signing in takes under a second on a normal connection. Start it?')
        for bad in ({"title": "Deploy the login fix", "done_when": "It is live"},  # something you didn't ask for that can't be taken back
                    {"title": "Fix the login", "done_when": "It works with password hunter2-Xq9Lw3PzT7"},  # a secret
                    {"title": "x" * 200, "done_when": "It works"}, {"title": "Fix it", "done_when": "Two\nlines here"}):
            lead.said = bad
            self.assertEqual(self.take("the login feels slow on Tidepool")["task"]["title"], "The login feels slow", bad)

    # ---------- kept, swept and never served ----------

    def test_the_sweep(self):
        tasks = {state: self.take(f"fix the {state} page on Tidepool")["task"]["id"] for state in ("ready", "queued", "finished", "dropped", "fresh")}
        old = time.time()
        for state, tid in tasks.items():
            row = self.stored(tid)
            row["state"] = "ready" if state == "fresh" else state
            row["updated"] = old - (8 if state in ("ready", "queued", "fresh") else 31) * 86400
            if state == "fresh":
                row["updated"] = old - 6 * 86400
            intake.write(os.path.join(self.data, "control", "intake", tid + ".json"), row)
        recent = self.take("fix the about page on Tidepool")["task"]["id"]
        self.control.intake.sweep()
        left = sorted(os.listdir(os.path.join(self.data, "control", "intake")))
        self.assertEqual(left, sorted([tasks["fresh"] + ".json", recent + ".json"]))

    def test_a_phone_through_control_and_never_as_a_file(self):
        sys.path.insert(0, ROOT)
        import serve  # noqa: E402
        task = self.take("fix the footer on Tidepool", via="phone")["task"]
        self.assertEqual(task["via"], "phone")
        old_root = serve.ROOT
        serve.ROOT = self.base
        server = serve.Server(("127.0.0.1", 0), serve.Handler)
        server.control = self.control
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for path in (f"/data/control/intake/{task['id']}.json", f"/data/Control/Intake/{task['id']}.json", "/data/control/intake/"):
                conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
                conn.request("GET", path)
                answer = conn.getresponse()
                body = answer.read()
                self.assertIn(answer.status, (403, 404), path)
                self.assertNotIn(b"footer", body)
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
            conn.request("GET", "/control/state", headers={"X-Arnheim-Control": self.control.token})
            got = json.loads(conn.getresponse().read())
            self.assertEqual([r["title"] for r in got["ready"]], ["Fix the footer"])
            self.assertTrue({"id", "project", "title", "done_when", "proven_by", "agent", "estimate", "state", "key", "at"} <= set(got["ready"][0]))
            self.assertNotIn("intake", serve.READS)  # an action: logged for a phone
        finally:
            server.shutdown()
            server.server_close()
            serve.ROOT = old_root


# Stands in for the brain's `claude` (stream-json in and out): writes a ready task, or something else when asked to.
SHAPER = r'''
import json, sys
print(json.dumps({"type": "system", "subtype": "init"}), flush=True)
for raw in sys.stdin:
    text = json.loads(raw)["message"]["content"][0]["text"]
    said = text.split("What the person said: ", 1)[-1]
    answer = "Sure! Here you go." if "chatty" in said else "TITLE: Speed up the slow login\nDONE WHEN: Signing in takes under a second."
    print(json.dumps({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": answer}}}), flush=True)
    print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": answer}), flush=True)
'''


class BrainShapeTest(unittest.TestCase):
    def test_the_lead_writes_two_lines_or_nothing(self):
        import brain
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        fake = os.path.join(base, "fake_brain.py")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(SHAPER)
        mind = brain.Brain(claude=[sys.executable, fake], model="haiku", wait=20)
        self.addCleanup(mind.close)
        self.assertEqual(mind.shape("the login feels slow", "Tidepool"), {"title": "Speed up the slow login", "done_when": "Signing in takes under a second."})
        self.assertIsNone(mind.shape("be chatty about the login", "Tidepool"))
        self.assertIn("--tools", mind.args(brain.SHAPER))  # no tools, as every claude the brain starts


class SampleReadyTest(unittest.TestCase):
    def test_the_sample_shows_believable_ready_tasks(self):
        with open(os.path.join(ROOT, "sample", "work.json"), encoding="utf-8") as handle:
            work = json.load(handle)
        with open(os.path.join(ROOT, "sample", "company.json"), encoding="utf-8") as handle:
            company = json.load(handle)
        projects = {f.get("project") or f["label"] for f in company["floors"]}
        self.assertTrue(company["sample"])
        self.assertTrue(1 <= len(work["ready"]) <= 3)
        for task in work["ready"]:
            self.assertIn(task["project"], projects)
            self.assertIn(task["state"], ("ready", "queued"))
            self.assertTrue(intake.TASK_ID.match(task["id"]))
            self.assertLessEqual(len(task["title"]), intake.TITLE_LONGEST)
            self.assertIn(task["agent"], ("Claude Code", "Codex"))
            self.assertTrue(task["done_when"].endswith(".") and task["proven_by"])

    def test_the_switches(self):
        names = [s[0] for s in switches.SWITCHES]
        self.assertIn("front_door", names)
        self.assertTrue(switches.DEFAULTS["front_door"])
        self.assertFalse(switches.DEFAULTS["ready_auto"])


# The page's rules (src/front-door.js), under Node: what is work, the read back, the queue line, and the talk.
SCRIPT = """
import { pathToFileURL } from 'node:url';
globalThis.window = { addEventListener() {} };
const fd = await import(pathToFileURL(process.argv[1] + '/src/front-door.js').href);
const [kind, given] = JSON.parse(process.argv[2]);
const floors = [{ project: 'Tidepool', label: 'Tidepool' }, { project: 'Lantern', label: 'Lantern' }];
if (kind === 'work') console.log(JSON.stringify(given.map((t) => fd.workSaid(t, floors))));
if (kind === 'words') console.log(JSON.stringify({ queue: fd.queueLine(given, (p) => p), est: fd.estimateWords(given[0].estimate) }));
if (kind === 'talk') {
  const calls = [];
  const tasks = { 'rd-0123456789': { id: 'rd-0123456789', project: 'Tidepool', label: 'Tidepool', title: 'The login feels slow', state: 'ready' } };
  const control = {
    on: true,
    intake: async (text, floor, via) => { calls.push(['intake', text, floor, via]);
      return floor || /tidepool/i.test(text) ? { task: tasks['rd-0123456789'], reply: 'Ready on Tidepool: "The login feels slow". It counts as done when the tests pass. Start it?' }
        : { task: null, reply: 'Which floor is that for? Tidepool or Lantern.', floors: ['Tidepool', 'Lantern'] }; },
    startReady: async (id) => { calls.push(['start', id]); return { task: { ...tasks[id], state: 'started' }, reply: 'Started on Tidepool.' }; },
  };
  const door = fd.createFrontDoor({ control, on: () => true, madeUp: () => false, floors: () => floors, styled: false });
  let pending = null;
  const out = [];
  for (const said of given) {
    let r = pending ? door.answer(pending, said, { via: 'talk' }) : null;
    if (!r) r = door.take(said, { floor: null, via: 'talk' });
    if (!r) { out.push(null); continue; }
    pending = r.pending;
    out.push(await r.reply);
  }
  console.log(JSON.stringify({ out, calls }));
}
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageRulesTest(unittest.TestCase):
    def node(self, kind, given):
        run = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT, json.dumps([kind, given])], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        return json.loads(run.stdout)

    def test_what_is_work(self):
        work = ["the login feels slow on Tidepool", "Fix the footer links", "can you speed up the search page?", "We need a dark mode",
                "get someone to fix the login bug on Lantern", "The export button doesn't work", "there's a typo on the about page",
                "Tidepool's sign up form is broken", "add a reset password link", "please tidy the tests on Lantern"]
        chat = ["what needs me?", "how's Tidepool doing?", "is the login slow?", "thanks", "hello there", "who is working on Lantern",
                "start it", "yes", "remind me to call the bank", "remember that we use pnpm", "tell them to use pnpm", "stop them",
                "what's new", "give me the round", "take me to Lantern", "I love this building"]
        self.assertEqual(self.node("work", work), [True] * len(work))
        self.assertEqual(self.node("work", chat), [False] * len(chat))

    def test_words_for_the_page(self):
        tasks = [{"project": "Tidepool", "title": "Fix the footer", "state": "queued", "estimate": {"minutes": 25, "tokens": 380000, "from": 4}},
                 {"project": "Tidepool", "title": "Tidy the tests", "state": "queued"}, {"project": "Lantern", "title": "Add dark mode", "state": "ready"}]
        got = self.node("words", tasks)
        self.assertEqual(got["queue"], ['Next on Tidepool: "Fix the footer", then 1 more.'])
        self.assertEqual(got["est"], "About 25 minutes and 380 thousand tokens, going by 4 finished jobs here.")

    def test_talk_reads_it_back_and_starts_it(self):
        got = self.node("talk", ["the login feels slow on Tidepool", "yes, start it"])
        self.assertEqual(got["out"], ['Ready on Tidepool: "The login feels slow". It counts as done when the tests pass. Start it?', "Started on Tidepool."])
        self.assertEqual(got["calls"], [["intake", "the login feels slow on Tidepool", None, "talk"], ["start", "rd-0123456789"]])
        got = self.node("talk", ["the login feels slow", "Tidepool", "no"])
        self.assertEqual(got["out"][0], "Which floor is that for? Tidepool or Lantern.")
        self.assertEqual(got["out"][2], "All right, it stays ready. It's on Needs you and in Tidepool's Work room when you want it.")
        self.assertEqual(got["calls"], [["intake", "the login feels slow", None, "talk"], ["intake", "the login feels slow", "Tidepool", "talk"]])


if __name__ == "__main__":
    unittest.main()
