"""The week on one page (connect/week.py, src/week.js; docs/connect.md, "The week on one page"): each floor's finished
and proven work, what was undone and what waits, and where the week's allowance went, from what Arnheim keeps: the
hook's history (with each moment's tokens and the checks' results, kept for it), the daily cycle's days, the night
shift's nights, Show me's cards, restore points put back and your plan's limits. Honest about days with no readings,
and never a secret in a title. It only reads, through control. The made-up company's week says it is made up."""
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

import budget  # noqa: E402  (after the path is set)
import claude_code  # noqa: E402
import control  # noqa: E402
import intake  # noqa: E402
import prove  # noqa: E402
import switches  # noqa: E402
import week  # noqa: E402

NODE = shutil.which("node")
PYTHON = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
SECRET_TITLE = "Use the password is Fernhollow-swordfish-4417 for the staging login"


class WeekTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.data = os.path.join(self.base, "data")
        for folder in ("feeds/history", "day", "night", "shows"):
            os.makedirs(os.path.join(self.data, folder), exist_ok=True)
        self.now = time.time()
        self.today = datetime.date.fromtimestamp(self.now)
        self.save("company.json", {"company": "Example Studio", "feeds": ["feeds/claude-code.json"], "floors": [
            {"id": "lantern", "label": "Lantern", "project": "Lantern"}, {"id": "tidepool", "label": "Tidepool", "project": "Tidepool"}]})
        self.save("feeds/claude-code.json", {"conversations": []})
        self.history_was = claude_code.HISTORY

    def tearDown(self):
        claude_code.HISTORY = self.history_was
        shutil.rmtree(self.base, ignore_errors=True)

    def save(self, rel, doc):
        path = os.path.join(self.data, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(doc, handle)

    def load(self, rel):
        with open(os.path.join(self.data, rel), encoding="utf-8") as handle:
            return json.load(handle)

    def day(self, back):
        return self.today - datetime.timedelta(days=back)

    def at(self, back, hh, mm=0):
        return time.mktime(datetime.datetime.combine(self.day(back), datetime.time(hh, mm)).timetuple())

    def moment(self, back, hh, mm, key, project, title, kind, tokens=None):
        m = {"at": self.at(back, hh, mm), "key": key, "project": project, "title": title, "kind": kind, "what": "x"}
        if tokens is not None:
            m["tokens"] = tokens
        return m

    def a_week(self):
        """Two floors' week: Lantern's work proven, a plan item, a close's proven work and an Undo; Tidepool's work whose
        check failed, sent back from Show me, a night run, a night run undone, and a proposal waiting."""
        self.save(f"feeds/history/{self.day(1).isoformat()}.json", {
            "moments": [self.moment(1, 10, 0, "cc-a", "Lantern", "Faster first page", "working", 100),
                        self.moment(1, 10, 10, "cc-a", "Lantern", "Faster first page", "changed", 300),
                        self.moment(1, 10, 30, "cc-a", "Lantern", "Faster first page", "finished", 500),
                        self.moment(1, 11, 0, "cc-q", "Lantern", "Just a question", "working"),
                        self.moment(1, 11, 5, "cc-q", "Lantern", "Just a question", "finished")],
            "spent": {"Lantern": 2000, "Tidepool": 400},
            "proofs": {"cc-a": {"project": "Lantern", "title": "Faster first page", "state": "passed", "at": self.at(1, 10, 35)}}})
        self.save(f"feeds/history/{self.day(0).isoformat()}.json", {
            "moments": [self.moment(0, 0, 1, "cc-b", "Tidepool", "Rain gauge", "working", 50),
                        self.moment(0, 0, 2, "cc-b", "Tidepool", "Rain gauge", "changed", 120),
                        self.moment(0, 0, 3, "cc-b", "Tidepool", "Rain gauge", "finished", 200),
                        self.moment(0, 0, 5, "cc-b", "Tidepool", "Rain gauge", "working", 220),
                        self.moment(0, 0, 6, "cc-b", "Tidepool", "Rain gauge", "changed", 400),
                        self.moment(0, 0, 7, "cc-b", "Tidepool", "Rain gauge", "finished", 500)],
            "spent": {"Tidepool": 900}})
        for back in (3, 5):  # kept, but nothing happened
            self.save(f"feeds/history/{self.day(back).isoformat()}.json", {"moments": [], "spent": {}})
        self.save("feeds/claude-code.json", {"conversations": [
            {"id": "cc-b", "project": "Tidepool", "title": "Rain gauge", "proof": {"state": "failed", "at": self.at(0, 0, 8), "done": self.at(0, 0, 9)}}]})
        self.save(f"day/{self.day(1).isoformat()}.json", {"date": self.day(1).isoformat(), "plan": [
            {"floor": "Lantern", "label": "Lantern", "approved": True,
             "items": [{"id": "d-1", "title": "Faster first page", "state": "done", "key": "cc-a", "spent": 300, "how": "front door"}]},
            {"floor": "Tidepool", "label": "Tidepool", "approved": True,
             "items": [{"id": "d-2", "title": "Tidy notes", "state": "done", "key": "cc-n1", "spent": 999, "how": "night shift"}]}],
            "close": {"proven": [{"floor": "Lantern", "title": "Old proven work"}], "stuck": [], "tomorrow": []}})
        self.save(f"day/{self.day(0).isoformat()}.json", {"date": self.day(0).isoformat(), "plan": [
            {"floor": "Tidepool", "label": "Tidepool", "approved": False, "items": [{"id": "d-3", "title": "Publish the guide", "state": "proposed"}]}]})
        self.save(f"night/{self.day(1).isoformat()}.json", {"night": self.day(1).isoformat(), "ran": [
            {"id": "n-00000001", "key": "cc-n1", "project": "Tidepool", "label": "Tidepool", "title": "Tidy notes", "state": "done",
             "spent": 999, "started_at": self.at(0, 0, 0) + 10},
            {"id": "n-00000002", "key": "cc-n2", "project": "Tidepool", "label": "Tidepool", "title": "Calibrate the sensor", "state": "done",
             "spent": 100, "started_at": self.at(0, 0, 0) + 20, "undone": self.at(0, 0, 4)}]})
        self.save("feeds/restore.json", {"restore": [
            {"id": "rp-000000000001", "by": "you", "why": "before going back to 00:00", "project": "Tidepool", "at": self.at(0, 0, 4) + 3},
            {"id": "rp-000000000002", "by": "you", "why": "before going back to 11:00", "project": "Lantern", "at": self.at(1, 12, 0)},
            {"id": "rp-000000000003", "by": "agent", "why": "before its first change", "project": "Lantern", "at": self.at(1, 10, 9)}]})
        self.save("shows/index.json", {"shows": [
            {"key": "cc-b-1", "conv": "cc-b", "project": "Tidepool", "state": "again", "decided_at": self.at(0, 0, 4), "title": "Rain gauge"},
            {"key": "cc-a-1", "conv": "cc-a", "project": "Lantern", "state": "waiting", "title": "Faster first page"}]})
        self.save("feeds/usage.json", {"sources": {"Claude Code": {"seven_day": [
            {"at": self.now - 600, "used": 50.0, "resets_at": self.now + 3 * 86400},
            {"at": self.now - 60, "used": 64.2, "resets_at": self.now + 3 * 86400}]}}})
        self.save("work.json", {"tasks": [{"id": "t1", "project": "Lantern", "title": "Sign the form", "status": "needs_you"}]})

    def test_each_floor_and_where_the_allowance_went(self):
        self.a_week()
        v = week.view(self.data, now=self.now)
        floors = {f["project"]: f for f in v["floors"]}
        self.assertEqual(list(floors), ["Lantern", "Tidepool"])  # in the building's order
        lantern, tidepool = floors["Lantern"], floors["Tidepool"]
        # Lantern: its work proven (a question it only answered isn't finished work), and the close's proven work
        self.assertEqual((lantern["finished"], lantern["proven"], lantern["failed"]), (2, 2, 0))
        self.assertNotIn("Just a question", [i["title"] for i in lantern["items"]["finished"]])
        self.assertEqual(lantern["undone"], 1)  # files you put back; an agent's own restore point is no Undo
        self.assertEqual(sorted(w["why"] for w in lantern["items"]["waits"]), ["It needs you.", "Its Show me card waits for Looks good or Not quite."])
        self.assertEqual(lantern["line"], "2 finished, all proven. 1 undone. 2 things wait for you.")
        # Tidepool: a check that failed, a night run nothing checked, a night run undone (one act, not two)
        self.assertEqual((tidepool["finished"], tidepool["proven"], tidepool["failed"], tidepool["undone"], tidepool["waits"]), (2, 0, 1, 1, 1))
        self.assertEqual(tidepool["items"]["undone"], [{"title": "Calibrate the sensor", "how": "night shift"}])
        self.assertEqual(tidepool["line"], "2 finished: 1 not proven and 1 not checked. 1 undone. 1 thing waits for you.")
        self.assertIn({"title": "Tidy notes", "how": "night", "proof": "unchecked"}, tidepool["items"]["finished"])
        # The allowance: the plan's own item (not the one the night shift ran), the night's runs, and what the work sent
        # back with Not quite spent from the sending to its next finish (500 - 200); the rest is your own.
        parts = {p["name"]: p for p in v["allowance"]["parts"]}
        self.assertEqual(v["allowance"]["tokens"], 3300)
        self.assertEqual({k: p["tokens"] for k, p in parts.items()}, {"plans": 300, "night": 1099, "show": 300, "own": 1601})
        self.assertEqual({k: p["share"] for k, p in parts.items()}, {"plans": 9, "night": 33, "show": 9, "own": 49})
        self.assertEqual(sum(p["share"] for p in parts.values()), 100)
        self.assertEqual((v["allowance"]["sent_back"], v["allowance"]["sent_counted"]), (1, 1))
        said = v["allowance"]["words"]
        self.assertIn("Of the 3 thousand new tokens counted this week: your own conversations 49%, the night shift 33%", said)
        self.assertIn("Claude Code says 64% of its weekly limit is used, and it starts again on", said)  # the newest reading
        self.assertIn("use none of it", said)
        # Honest about the days with no history at all
        names = [d["name"] for d in v["days"] if not d["read"]]
        self.assertEqual(len(names), 3)
        self.assertIn(f"No readings {names[0]}, {names[1]} or {names[2]}, so your own conversations then aren't counted.", v["words"])
        self.assertTrue(v["words"].startswith("This week, 4 pieces of work finished on 2 floors, 2 proven. 2 undone. 3 things wait for you."), v["words"])
        self.assertEqual(v["id"], f"week-{self.today.isoformat()}")
        self.assertEqual(v["sunday"], self.today.weekday() == 6)

    def test_nothing_kept_is_said_plainly(self):
        v = week.view(self.data, now=self.now)
        self.assertEqual(v["floors"], [])
        self.assertFalse(v["allowance"]["known"])
        self.assertIn("No spending was counted this week", v["allowance"]["words"])
        self.assertIn("No readings all week: the hook wrote nothing, so your own conversations aren't counted.", v["words"])
        self.assertIn("Nothing finished this week", v["words"])

    def test_sent_back_work_that_could_not_be_counted_says_so(self):
        self.a_week()
        rows = self.load("shows/index.json")["shows"]
        rows.append({"key": "cc-z-1", "conv": "cc-z", "project": "Lantern", "state": "again", "decided_at": self.at(0, 0, 1)})
        self.save("shows/index.json", {"shows": rows})
        a = week.view(self.data, now=self.now)["allowance"]
        self.assertEqual((a["sent_back"], a["sent_counted"]), (2, 1))
        self.assertIn("What 1 piece of work sent back with Not quite spent couldn't be counted", a["words"])

    def test_sent_back_work_the_plan_or_the_night_counts_is_never_counted_twice(self):
        # Found by the Checker: a plan item sent back with Not quite was counted in the plan's share, whole, and again as
        # work Show me sent back. An item Show me holds for your look settles only after the work it was sent back for,
        # so that work is in the plan's share: there alone.
        self.a_week()
        plan = self.load(f"day/{self.day(1).isoformat()}.json")
        plan["plan"][0]["items"][0]["ended_at"] = self.at(0, 0, 55)  # settled after the rework ended (00:50)
        self.save(f"day/{self.day(1).isoformat()}.json", plan)
        today = self.load(f"feeds/history/{self.day(0).isoformat()}.json")
        today["moments"] += [self.moment(0, 0, 40, "cc-a", "Lantern", "Faster first page", "working", 10),
                             self.moment(0, 0, 50, "cc-a", "Lantern", "Faster first page", "finished", 700)]
        self.save(f"feeds/history/{self.day(0).isoformat()}.json", today)
        rows = self.load("shows/index.json")["shows"]
        rows += [{"key": "cc-a-2", "conv": "cc-a", "project": "Lantern", "state": "again", "decided_at": self.at(0, 0, 35)}]
        self.save("shows/index.json", {"shows": rows})
        a = week.view(self.data, now=self.now)["allowance"]
        parts = {p["name"]: p["tokens"] for p in a["parts"]}
        self.assertEqual((parts["plans"], parts["night"], parts["show"]), (300, 1099, 300))  # as before: not counted again
        self.assertEqual((a["sent_back"], a["sent_counted"]), (2, 2))
        self.assertNotIn("couldn't be counted", a["words"])

    def test_work_sent_back_after_its_share_was_taken_is_show_mes(self):
        # Found by the Checker: the plan's and the night's shares are taken once, as the item or the run ends, so work
        # sent back after that was in neither share, nor in Show me's: it was counted as your own conversations.
        self.a_week()
        night_doc = self.load(f"night/{self.day(1).isoformat()}.json")
        night_doc["ran"][0]["ended_at"] = self.at(0, 0, 10)  # the night run ended, and its share was taken, at 00:10
        self.save(f"night/{self.day(1).isoformat()}.json", night_doc)
        plan = self.load(f"day/{self.day(1).isoformat()}.json")
        plan["plan"][0]["items"][0]["ended_at"] = self.at(0, 0, 30)  # the plan item settled at 00:30
        self.save(f"day/{self.day(1).isoformat()}.json", plan)
        today = self.load(f"feeds/history/{self.day(0).isoformat()}.json")
        today["moments"] += [self.moment(0, 0, 10, "cc-n1", "Tidepool", "Tidy notes", "finished", 999),
                             self.moment(0, 0, 20, "cc-n1", "Tidepool", "Tidy notes", "working", 1000),
                             self.moment(0, 0, 30, "cc-n1", "Tidepool", "Tidy notes", "finished", 1500),
                             self.moment(0, 0, 40, "cc-a", "Lantern", "Faster first page", "working", 10),
                             self.moment(0, 0, 50, "cc-a", "Lantern", "Faster first page", "finished", 700)]
        self.save(f"feeds/history/{self.day(0).isoformat()}.json", today)
        rows = self.load("shows/index.json")["shows"]
        rows += [{"key": "cc-n1-1", "conv": "cc-n1", "project": "Tidepool", "state": "again", "decided_at": self.at(0, 0, 15)},
                 {"key": "cc-a-2", "conv": "cc-a", "project": "Lantern", "state": "again", "decided_at": self.at(0, 0, 35)}]
        self.save("shows/index.json", {"shows": rows})
        a = week.view(self.data, now=self.now)["allowance"]
        parts = {p["name"]: p["tokens"] for p in a["parts"]}
        # the shares as they were taken, and Show me's: cc-b's 300, the night run's rework 1500 - 999, the item's 700
        self.assertEqual((parts["plans"], parts["night"], parts["show"]), (300, 1099, 300 + 501 + 700))
        self.assertEqual(a["tokens"], 3300)
        self.assertEqual((a["sent_back"], a["sent_counted"]), (3, 3))
        # still at work after its share was taken: counted nowhere yet, and said so
        rows.append({"key": "cc-a-3", "conv": "cc-a", "project": "Lantern", "state": "again", "decided_at": self.at(0, 0, 52)})
        self.save("shows/index.json", {"shows": rows})
        a = week.view(self.data, now=self.now)["allowance"]
        self.assertEqual((a["sent_back"], a["sent_counted"]), (4, 3))
        self.assertIn("couldn't be counted", a["words"])

    def test_its_docs_say_when_sent_back_work_is_in_a_share(self):
        with open(os.path.join(ROOT, "docs", "connect.md"), encoding="utf-8") as handle:
            docs = " ".join(handle.read().split())
        self.assertIn("sent-back work that ended after that is counted as Show me's", docs)
        self.assertNotIn("is counted in that share alone, never twice", docs)

    def test_a_title_that_names_a_secret_is_never_shown(self):
        self.assertTrue(intake.has_secret(SECRET_TITLE))  # the case this guards
        self.save(f"feeds/history/{self.day(0).isoformat()}.json", {"moments": [
            self.moment(0, 0, 1, "cc-s", "Lantern", SECRET_TITLE, "changed", 10),
            self.moment(0, 0, 2, "cc-s", "Lantern", SECRET_TITLE, "finished", 20)], "spent": {"Lantern": 20}})
        self.save("work.json", {"tasks": [{"id": "t2", "project": "Lantern", "title": SECRET_TITLE, "status": "needs_you"}]})
        raw = json.dumps(week.view(self.data, now=self.now))
        self.assertNotIn("swordfish", raw)
        self.assertIn(week.SEALED, raw)

    def test_through_control_only_reading_and_its_switch(self):
        self.a_week()
        ctrl = control.Control(self.data, claude=[sys.executable, "-c", "pass"])
        before = {os.path.join(root, n): os.path.getmtime(os.path.join(root, n)) for root, _, names in os.walk(self.data) for n in names}
        code, _, body, _ = ctrl.handle("POST", "week", b"{}", ctrl.token)
        self.assertEqual(code, 200)
        got = json.loads(body)
        self.assertTrue(got["on"])
        self.assertEqual([f["project"] for f in got["floors"]], ["Lantern", "Tidepool"])
        after = {os.path.join(root, n): os.path.getmtime(os.path.join(root, n)) for root, _, names in os.walk(self.data) for n in names}
        self.assertEqual({k: v for k, v in after.items() if k in before}, before)  # reading it changes nothing kept
        self.assertEqual(ctrl.handle("POST", "week", b"{}", "not-the-token")[0], 403)
        self.assertEqual(ctrl.handle("GET", "week", b"", ctrl.token)[0], 405)
        self.assertTrue(switches.DEFAULTS["week"])  # on unless you switch it off
        switches.save("week", False, self.data)
        self.assertEqual(json.loads(ctrl.handle("POST", "week", b"{}", ctrl.token)[2]), {"on": False})
        sys.path.insert(0, ROOT)
        import serve
        self.assertIn("week", serve.READS)  # counted for a phone, never logged

    def test_the_hook_keeps_each_moments_tokens_and_the_checks_results(self):
        history = os.path.join(self.data, "feeds", "history")
        claude_code.HISTORY = history
        talk = {"id": "cc-h", "title": "Bookmark tests", "spent": {"day": budget.local_day(), "tokens": 1234}}
        claude_code.add_moment(talk, "Lantern", "changed", "reader/bookmark.js")
        claude_code.note_proof(talk, "Lantern", {"state": "checking", "at": self.now})  # still running: not kept
        path = os.path.join(history, budget.local_day() + ".json")
        kept = self.load(path)
        self.assertEqual(kept["moments"][-1]["tokens"], 1234)
        self.assertNotIn("proofs", kept)
        # prove.py's result reaches the history beside the feed, and later moments keep it
        claude_code_edit = claude_code.edit_feed
        feed = {"conversations": [{"id": "cc-h", "project": "Lantern", "title": "Bookmark tests"}], "tasks": []}
        claude_code.edit_feed = lambda edit, *_, **__: edit(feed)
        try:
            prove.mark("Lantern", {"cc-h"}, {"state": "passed", "check": "The tests", "at": self.now, "done": self.now + 3})
        finally:
            claude_code.edit_feed = claude_code_edit
        self.assertEqual(feed["conversations"][0]["proof"]["state"], "passed")
        claude_code.add_moment(talk, "Lantern", "finished", "Done.")
        kept = self.load(path)
        self.assertEqual(kept["proofs"]["cc-h"]["state"], "passed")
        self.assertEqual(kept["proofs"]["cc-h"]["project"], "Lantern")
        self.assertEqual([m["kind"] for m in kept["moments"]], ["changed", "finished"])
        f = week.view(self.data, now=self.now)["floors"][0]
        self.assertEqual((f["project"], f["finished"], f["proven"]), ("Lantern", 1, 1))

    def test_a_days_checks_are_kept_up_to_a_few_hundred(self):
        # Found by the Checker: a day kept up to 5,000 checks' results, rewritten whole with every moment.
        history = os.path.join(self.data, "feeds", "history")
        claude_code.HISTORY = history
        path = os.path.join(history, budget.local_day() + ".json")
        self.save(os.path.relpath(path, self.data), {"moments": [], "spent": {}, "proofs": {
            f"cc-{n:04d}": {"project": "Lantern", "title": None, "state": "passed", "at": self.now} for n in range(600)}})
        claude_code.note_proof({"id": "cc-new", "title": "Bookmark tests"}, "Lantern", {"state": "failed", "at": self.now})
        proofs = self.load(path)["proofs"]
        self.assertEqual(len(proofs), claude_code.PROOFS_MOST)
        self.assertLessEqual(claude_code.PROOFS_MOST, 500)
        self.assertEqual(list(proofs)[-1], "cc-new")  # the newest kept, the oldest gone
        self.assertNotIn("cc-0000", proofs)

    def test_it_loads_by_path_on_the_systems_python(self):
        self.a_week()
        env = dict(os.environ, ARNHEIM_DATA=self.data)
        done = subprocess.run([PYTHON, "-I", os.path.join(ROOT, "connect", "week.py"), "--json"], capture_output=True, text=True,
                              env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue(json.loads(done.stdout)["on"])
        said = subprocess.run([PYTHON, "-I", os.path.join(ROOT, "connect", "week.py")], capture_output=True, text=True, env=env, timeout=60)
        self.assertIn("This week, 4 pieces of work finished", said.stdout)


PAGE = """
import { pathToFileURL } from 'node:url';
const w = await import(pathToFileURL(process.argv[1] + '/src/week.js').href);
const fs = await import('node:fs');
const raw = JSON.parse(fs.readFileSync(process.argv[1] + '/sample/week.json', 'utf8'));
const real = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const v = w.sampleWeek(raw, new Date(2026, 10, 22, 10, 0).getTime() / 1000);
let reads = 0;
let changed = 0;
const page = w.createWeek({ styled: false, where: () => 'here', changed: () => { changed += 1; },
  control: { on: true, week: async () => { reads += 1; return real; } } });
const first = page.heard('How did the week go?');
await new Promise((go) => setTimeout(go, 20));
const second = page.heard('How did the week go?');
console.log(JSON.stringify({
  sample: { madeUp: v.sample, words: v.words, missing: v.missing, sunday: v.sunday,
    shares: v.allowance.parts.map((p) => p.share), total: v.allowance.tokens,
    lines: Object.fromEntries(v.floors.map((f) => [f.label, f.line])), allowance: v.allowance.words },
  intents: ['How did the week go?', 'where did the allowance go?', 'What did this week cost', 'weekly report please',
    'how did the night go?', "what's the plan?"].map((t) => w.weekIntent(t)),
  same: { words: w.sayWeekPage(real), lines: real.floors.map((f) => w.floorWords(f)), allowance: w.allowanceWords(real.allowance) },
  page: { first, second, reads, changed, again: (page.heard('the week in review'), reads), other: page.heard('what is the weather'),
    spent: page.heard('Where did the allowance go?') },
  shares: [w.sharesOf([['a', 1], ['b', 1], ['c', 1]]), w.sharesOf([['a', 0], ['b', 0]])],
}));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class WeekPageTest(unittest.TestCase):
    def test_the_page_words(self):
        maker = WeekTest("test_each_floor_and_where_the_allowance_went")
        maker.setUp()
        try:
            maker.a_week()
            real = week.view(maker.data, now=maker.now)
            path = os.path.join(maker.base, "week.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(real, handle)
            done = subprocess.run([NODE, "--input-type=module", "-e", PAGE, ROOT, path], capture_output=True, text=True, timeout=60)
        finally:
            maker.tearDown()
        self.assertEqual(done.returncode, 0, done.stderr)
        got = json.loads(done.stdout)
        s = got["sample"]
        self.assertTrue(s["madeUp"])
        self.assertTrue(s["words"].startswith("This week is made up, like the rest of the company. This week, 12 pieces of work finished"), s["words"])
        self.assertTrue(s["sunday"])  # 22 November 2026 is a Sunday: Needs you has it
        # the made-up days four and six days back have no entry, and say so
        self.assertEqual(s["missing"], "No readings Monday or Wednesday, so your own conversations then aren't counted.")
        self.assertEqual(sum(s["shares"]), 100)
        self.assertEqual(s["total"], 6620000)
        self.assertEqual(s["lines"]["Lantern"], "5 finished: 4 proven and 1 not proven. 1 undone. 2 things wait for you.")
        self.assertEqual(s["lines"]["Studio"], "2 finished, not checked. 1 thing waits for you.")
        self.assertIn("Made up: Claude Code says 64% of its weekly limit is used", s["allowance"])
        self.assertEqual(got["intents"], [True, True, True, True, False, False])
        # The page says what the building says, word for word
        self.assertEqual(got["same"]["words"], real["words"])
        self.assertEqual(got["same"]["lines"], [f["line"] for f in real["floors"]])
        self.assertEqual(got["same"]["allowance"], real["allowance"]["words"])
        # Your own company's week is read once a minute at most, and the receptionist answers from it once it is in
        p = got["page"]
        self.assertIsNone(p["first"])
        self.assertEqual(p["second"], real["words"])
        self.assertEqual(p["reads"], 1)
        self.assertEqual(p["again"], 1)
        self.assertIsNone(p["other"])
        self.assertTrue(p["spent"].startswith("Of the 3 thousand new tokens counted this week: your own conversations 49%"), p["spent"])
        self.assertIn("No readings", p["spent"])
        self.assertEqual(got["shares"], [{"a": 34, "b": 33, "c": 33}, {"a": 0, "b": 0}])

    def test_no_long_dashes_or_inline_styles(self):
        for rel in ("src/week.js", "src/week.css", "sample/week.json", "connect/week.py"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
                text = handle.read()
            self.assertNotIn("—", text, rel)
            if rel.endswith(".js"):  # a host page with a strict style policy forbids inline styles: classes, and week.css loaded as a link
                self.assertNotRegex(text, r"\bstyle\s*:|\.style\b|['\"]style['\"]", rel)


if __name__ == "__main__":
    unittest.main()
