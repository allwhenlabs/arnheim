"""Office hours (docs/connect.md, step 27; connect/deputy.py): with the switch on, while nobody is using the building
outside the times you chose, an agent's question tool hears you are away until the next one, a turn that ends with a
question waits as a card, and a permission asks in the agent's own window and is listed for the sitting. Urgent
things still reach you at once. In the building, or in an office hour, everything is as it always was. And the page's
sitting (src/sitting.js), under Node.

Each test makes a company of its own in a temporary folder (ARNHEIM_DATA), so your data/ is never touched, and drives
the hook with made-up events. It runs under Python 3.9 too. Run from the repository's folder:
python3 -m unittest discover tests
"""
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connect"))

import control  # noqa: E402  (after the path is set)
import deputy  # noqa: E402
import switches  # noqa: E402

HOOK = os.path.join(ROOT, "connect", "claude_code.py")
CODEX = os.path.join(ROOT, "connect", "codex.py")
NODE = shutil.which("node")
SESSION = "abc123def456-7890"
KEY = "cc-abc123def456"
COLOURS = [{"question": "Which colour for the button?", "header": "Colour",
            "options": [{"label": "Blue", "description": "As the brand"}, {"label": "Green", "description": "Stands out"}], "multiSelect": False}]
AWAY = re.compile(r"^The person is away until \d\d:\d\d( tomorrow)? \(office hours\)\. If one option is clearly safe and easy to change later, "
                  r"take it and say which you took; otherwise put this aside, carry on with work that doesn't depend on it, and if there "
                  r"is none, finish your turn saying what you need\.$")


def clock(seconds_from_now):
    return datetime.datetime.fromtimestamp(time.time() + seconds_from_now).strftime("%H:%M")


class Company(unittest.TestCase):
    """A made-up company with one floor, Lantern, where control has been used, with office hours on, the next one six
    hours from now."""

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.data = os.path.join(self.base, "data")
        self.lantern = os.path.join(self.base, "code", "lantern")
        os.makedirs(os.path.join(self.data, "control"))
        os.makedirs(self.lantern)
        with open(os.path.join(self.data, "company.json"), "w", encoding="utf-8") as handle:
            json.dump({"company": "Example Studio", "rooms": [{"id": "work", "label": "Work"}],
                       "floors": [{"id": "lantern", "label": "Lantern", "folder": self.lantern}], "feeds": ["feeds/claude-code.json"]}, handle)
        self.env = dict(os.environ, ARNHEIM_DATA=self.data, ARNHEIM_CONTROL_WAIT="5")
        self.box = control.Box(self.data)
        self.control = control.Control(self.data, claude=["true"])
        switches.save("office_hours", True, self.data)
        deputy.save_times(self.data, [clock(6 * 3600)])
        self.hook(hook_event_name="UserPromptSubmit", prompt="Make the button nicer")

    def hook(self, script=HOOK, **event):
        event.setdefault("session_id", SESSION)
        event.setdefault("cwd", self.lantern)
        done = subprocess.run([sys.executable, script], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def in_background(self, **event):
        event.setdefault("session_id", SESSION)
        event.setdefault("cwd", self.lantern)
        proc = subprocess.Popen([sys.executable, HOOK], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=self.env)
        proc.stdin.write(json.dumps(event))
        proc.stdin.close()
        self.addCleanup(lambda: proc.poll() is None and proc.kill())

        def out(seconds=30):
            said = proc.stdout.read()
            proc.stdout.close()
            self.assertEqual(proc.wait(timeout=seconds), 0)
            return json.loads(said) if said.strip() else None
        return out

    def ask(self):
        return self.hook(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": COLOURS})

    def call(self, method, name, body=None):
        code, _, data, _ = self.control.handle(method, name, b"" if body is None else json.dumps(body).encode(), self.control.token)
        return code, json.loads(data)

    def state(self):
        return self.call("GET", "state")[1]

    def keep_watching(self):
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                self.box.watch()
                stop.wait(1)
        threading.Thread(target=watch, daemon=True).start()
        self.addCleanup(stop.set)


class TimesTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)

    def test_up_to_four_a_day_kept_beside_the_switches(self):
        self.assertEqual(deputy.office_times(self.data), ["13:00", "18:00"])
        switches.save("memory", False, self.data)
        self.assertEqual(deputy.save_times(self.data, ["18:00", "9:30", "13:00", "13:00"]), ["09:30", "13:00", "18:00"])
        self.assertEqual(deputy.office_times(self.data), ["09:30", "13:00", "18:00"])
        self.assertFalse(switches.on("memory", self.data))  # the switches are kept as they were
        for bad in ([], ["1:00", "2:00", "3:00", "4:00", "5:00"], ["25:00"], ["noon"], "13:00"):
            with self.assertRaises(ValueError):
                deputy.clean_times(bad)

    def test_open_for_half_an_hour_from_each_time_and_the_next_one(self):
        deputy.save_times(self.data, ["13:00", "18:00"])
        day = datetime.datetime(2026, 11, 21)
        at = lambda h, m=0, d=0: (day + datetime.timedelta(days=d, hours=h, minutes=m)).timestamp()  # noqa: E731
        self.assertFalse(deputy.office_open(self.data, at(12, 59)))
        self.assertTrue(deputy.office_open(self.data, at(13, 0)))
        self.assertTrue(deputy.office_open(self.data, at(13, 29)))
        self.assertFalse(deputy.office_open(self.data, at(13, 30)))
        self.assertEqual(deputy.until_words(self.data, at(10)), "13:00")
        self.assertEqual(deputy.until_words(self.data, at(15)), "18:00")
        self.assertEqual(deputy.until_words(self.data, at(19)), "13:00 tomorrow")
        self.assertEqual(deputy.next_office(self.data, at(19)), at(13, d=1))
        # a sitting opened now is open for half an hour
        deputy.open_sitting(self.data, at(10))
        self.assertTrue(deputy.office_open(self.data, at(10, 20)))
        deputy.close_sitting(self.data, at(10, 25))
        self.assertFalse(deputy.office_open(self.data, at(10, 26)))

    def test_away_only_with_the_switch_on_nobody_there_and_out_of_hours(self):
        deputy.save_times(self.data, ["13:00"])
        out_of_hours = datetime.datetime(2026, 11, 21, 10).timestamp()
        self.assertFalse(deputy.away(self.data, False, out_of_hours))  # off by default
        switches.save("office_hours", True, self.data)
        self.assertTrue(deputy.away(self.data, False, out_of_hours))
        self.assertFalse(deputy.away(self.data, True, out_of_hours))
        self.assertFalse(deputy.away(self.data, False, datetime.datetime(2026, 11, 21, 13, 10).timestamp()))

    def test_urgent_permissions(self):
        self.assertTrue(deputy.high_risk("Read", "Read: ~/.ssh/id_rsa"))
        self.assertTrue(deputy.high_risk("Bash", "Bash: git push origin main", "git push origin main"))
        self.assertTrue(deputy.high_risk("Bash", "Bash: rm -rf build", "rm -rf build"))
        self.assertIsNone(deputy.high_risk("Bash", "Bash: npm test", "npm test"))
        self.assertIsNone(deputy.high_risk("WebFetch", "WebFetch: https://example.com/token"))


class AwayTest(Company):
    def test_a_question_tool_hears_you_are_away_at_once_and_waits_for_the_sitting(self):
        began = time.time()
        out = self.ask()["hookSpecificOutput"]
        self.assertLess(time.time() - began, 10)
        self.assertEqual(out["permissionDecision"], "allow")
        self.assertEqual(out["updatedInput"]["questions"], COLOURS)
        self.assertRegex(out["updatedInput"]["answers"]["Which colour for the button?"], AWAY)
        self.assertIn(f"away until {clock(6 * 3600)}", out["updatedInput"]["answers"]["Which colour for the button?"])
        state = self.state()
        self.assertEqual(state["questions"], [])
        self.assertEqual([(p["kind"], p["text"], p["state"]) for p in state["parked"]], [("question", "Which colour for the button?", "parked")])
        self.assertEqual(state["office"]["parked"], 1)
        self.assertTrue(state["office"]["on"])
        self.assertFalse(state["office"]["open"])
        # answered in the sitting: it reaches the agent as a message before its next step, and can be remembered
        pid = state["parked"][0]["id"]
        code, got = self.call("POST", "reply_question", {"id": pid, "answers": {"Which colour for the button?": "Green"}, "remember": True})
        self.assertEqual((code, got["sent"], got["remembered"]), (200, "queued", True))
        said = self.hook(hook_event_name="PreToolUse", tool_name="Read", tool_input={"file_path": "a.txt"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn('About your question ("Which colour for the button?"), which you put aside while the person was away: Green', said)
        self.assertEqual(self.state()["parked"], [])
        self.assertEqual(self.call("POST", "reply_question", {"id": pid, "text": "Blue"})[0], 400)

    def test_remember_is_refused_for_a_secret_before_anything_is_sent(self):
        self.ask()
        pid = self.state()["parked"][0]["id"]
        token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # made up, in a GitHub token's shape (built in two, for scanners)
        code, got = self.call("POST", "reply_question", {"id": pid, "text": f"Green, and push with {token}", "remember": True})
        self.assertEqual(code, 400)
        self.assertIn("Untick Remember my answer", got["error"])
        self.assertEqual([p["id"] for p in self.state()["parked"]], [pid])  # nothing was sent: it still waits for the sitting
        self.assertEqual(self.state()["decisions"]["decisions"], [])

    def test_a_turn_that_ends_with_a_question_waits_as_a_card(self):
        self.assertIsNone(self.hook(hook_event_name="Stop", last_assistant_message="Done.\n\nShould I change the hover colour too?"))
        self.assertEqual([(q["kind"], q["state"], q["urgent"]) for q in self.state()["questions"]], [("words", "open", None)])

    def test_a_permission_asks_in_its_window_and_is_listed_for_the_sitting(self):
        self.assertIsNone(self.hook(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "npm install"}))
        row = self.state()["parked"][0]
        self.assertEqual((row["kind"], row["what"], row["urgent"], row["state"]), ("permission", "Bash: npm install", None, "parked"))
        self.hook(hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "npm install"}, tool_response="ok")
        self.assertEqual(self.state()["parked"][0]["state"], "moved on")  # answered in its own window
        # glanced at in the sitting
        code, got = self.call("POST", "office", {"seen": [row["id"]]})
        self.assertEqual((code, got["seen"], got["office"]["parked"]), (200, 1, 0))
        self.assertEqual(self.state()["parked"], [])

    def test_urgent_reaches_you_at_once(self):
        # a permission that reaches something private
        self.hook(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "cat ~/.ssh/id_rsa"})
        self.assertEqual(self.state()["parked"][0]["urgent"], "It reaches something that may be private.")
        # the same question a second time: it asks in its window, as a card marked urgent
        self.assertIsNotNone(self.ask())
        self.assertIsNone(self.ask())
        q = self.state()["questions"][0]
        self.assertEqual((q["state"], q["urgent"]), ("window", "It asked the same thing a second time."))

    def test_a_risky_question_is_never_told_you_are_away(self):
        # secrets, money, deleting, pushing, publishing or sending, in the question, its header or only in an option
        risky = [[{"question": "Should I push the branch now?", "header": "Branch", "options": [
                     {"label": "Yes", "description": "Now"}, {"label": "No", "description": "Later"}], "multiSelect": False}],
                 [{"question": "Which way to finish?", "header": "Finish", "options": [
                     {"label": "Tidy", "description": "Keep it on this computer"}, {"label": "Go", "description": "Deploy it to the live site"}],
                   "multiSelect": False}],
                 [{"question": "Which plan for the trial?", "header": "Billing", "options": [
                     {"label": "Monthly", "description": "Smaller"}, {"label": "Yearly", "description": "Bigger"}], "multiSelect": False}]]
        for questions in risky:
            out = self.hook(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": questions})
            self.assertIsNone(out)  # no away words: it asks in its own window, and waits as a card
            row = next(q for q in self.state()["questions"] if q["text"] == questions[0]["question"])
            self.assertEqual((row["state"], row["urgent"]), ("window", deputy.NEVER_URGENT))  # it reaches you at once
        self.assertEqual(self.state()["parked"], [])
        # a safe one still hears you are away
        self.assertRegex(self.ask()["hookSpecificOutput"]["updatedInput"]["answers"]["Which colour for the button?"], AWAY)

    def test_an_agent_close_to_its_limit_is_urgent(self):
        os.makedirs(os.path.join(self.data, "feeds"), exist_ok=True)
        with open(os.path.join(self.data, "feeds", "usage.json"), "w", encoding="utf-8") as handle:
            json.dump({"sources": {"Claude Code": {"five_hour": [{"at": time.time() - 30, "used": 96.0, "resets_at": time.time() + 3600}]}}}, handle)
        self.assertIsNone(self.ask())
        self.assertEqual(self.state()["questions"][0]["urgent"], "It is close to its plan's limit.")
        self.assertIsNone(self.hook(hook_event_name="Stop", last_assistant_message="Should I keep going?"))
        self.assertEqual(self.state()["questions"][0]["urgent"], "It is close to its plan's limit.")

    def test_codex_too(self):
        self.assertIsNone(self.hook(CODEX, hook_event_name="Stop", last_assistant_message="Should I add a test for it?"))
        self.assertEqual(self.state()["questions"][0]["agent"], "Codex")
        self.assertIsNone(self.hook(CODEX, hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "git push"}))
        row = self.state()["parked"][0]
        self.assertEqual((row["agent"], row["urgent"]), ("Codex", "It could delete, overwrite or send things."))


class NotAwayTest(Company):
    def test_in_the_building_nothing_is_parked(self):
        self.keep_watching()
        out = self.in_background(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": COLOURS})
        row = None
        end = time.time() + 15
        while not row and time.time() < end:
            row = next(iter(self.state()["questions"]), None)
            time.sleep(0.1)
        self.assertEqual(row["state"], "waiting")
        self.call("POST", "reply_question", {"id": row["id"], "answers": {"Which colour for the button?": "Blue"}})
        self.assertEqual(out()["hookSpecificOutput"]["updatedInput"]["answers"], {"Which colour for the button?": "Blue"})
        self.assertEqual(self.state()["parked"], [])

    def test_in_an_office_hour_or_a_sitting_it_is_as_it_always_was(self):
        deputy.save_times(self.data, [clock(-600)])  # began ten minutes ago
        self.assertIsNone(self.ask())
        self.assertEqual(self.state()["questions"][0]["state"], "window")
        self.assertTrue(self.state()["office"]["open"])
        deputy.save_times(self.data, [clock(6 * 3600)])
        self.assertEqual(self.call("POST", "office", {"open": True})[1]["office"]["open"], True)
        self.assertIsNone(self.ask())
        self.assertEqual(self.state()["parked"], [])
        self.assertEqual(self.call("POST", "office", {"open": False})[1]["office"]["open"], False)

    def test_switched_off_it_is_as_it_always_was(self):
        self.assertEqual(self.call("POST", "office", {"on": False})[1]["office"]["on"], False)
        self.assertIsNone(self.ask())
        self.assertIsNone(self.hook(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "npm install"}))
        self.assertEqual(self.state()["parked"], [])

    def test_the_office_request(self):
        code, got = self.call("POST", "office", {"times": ["09:00", "13:00", "18:00"]})
        self.assertEqual((code, got["office"]["times"]), (200, ["09:00", "13:00", "18:00"]))
        self.assertEqual(self.call("POST", "office", {"times": ["1:00", "2:00", "3:00", "4:00", "5:00"]})[0], 400)
        self.assertEqual(self.call("POST", "office", {"on": "yes"})[0], 400)
        self.assertEqual(self.state()["office"]["times"], ["09:00", "13:00", "18:00"])


# ---------- the sitting, on the page (src/sitting.js), under Node ----------

SITTING = """
import { pathToFileURL } from 'node:url';
const m = await import(pathToFileURL(process.argv[1] + '/src/sitting.js').href);
const out = JSON.parse(process.argv[2]).map(([fn, ...a]) => {
  if (fn === 'heard') return m.sittingHeard(a[0], a[1]);
  if (fn === 'minutes') return m.aboutMinutes(a[0]);
  if (fn === 'alert') return m.officeAlert(a[0]);
  if (fn === 'summary') return m.summaryOf(a[0]);
  if (fn === 'times') { try { return m.parseTimes(a[0]); } catch (e) { return 'error'; } }
  if (fn === 'items') return m.sittingItems(a[0]).map((i) => `${i.kind}:${i.id}`);
  if (fn === 'due') return m.dueOffice(a[0], a[1], new Set(a[2]));
  throw new Error(fn);
});
console.log(JSON.stringify(out));
"""

# The sitting itself (createSitting), shut, with a stand-in for the page and for control: what a spoken or typed word
# does to the permission in front of you, and whether it was answered (answerAsk's calls).
SITTING_VOICE = """
import { pathToFileURL } from 'node:url';
// Just enough of a page to draw the sitting into
class Node {}
class El extends Node {
  constructor(tag) { super(); this.tag = tag; this.kids = []; this.dataset = {}; this.classList = { add() {}, remove() {} }; }
  append(...kids) { this.kids.push(...kids); }
  replaceChildren(...kids) { this.kids = kids; }
  setAttribute() {}
  addEventListener() {}
  querySelector() { return null; }
  remove() {}
}
globalThis.Node = Node;
globalThis.document = { querySelector: () => ({}), createElement: (t) => new El(t), createElementNS: (_, t) => new El(t),
  body: new El('body'), head: new El('head'), addEventListener() {}, removeEventListener() {} };
const m = await import(pathToFileURL(process.argv[1] + '/src/sitting.js').href);
const out = [];
for (const [what, risk, on, said, spoken] of JSON.parse(process.argv[2])) {
  const calls = [];
  const asks = [{ id: 'a1', key: 'cc-a', tool: 'Read', what }];
  const sitting = m.createSitting({
    control: { on: true, state: () => ({ asks }) },
    state: () => ({ asks }),
    item: (kind, id) => (kind === 'permission' && id === 'a1' ? { kind: 'permission', id: 'ask:a1', ask: asks[0], what } : null),
    answerAsk: (i, behavior) => { calls.push(behavior); return Promise.resolve({ ok: true }); },
    risk: () => ({ word: risk, mood: 'warn', line: '' }),
    voiceOn: () => on,
    label: (p) => p,
  });
  sitting.open();
  const got = await sitting.heard(said, spoken == null ? undefined : { spoken });
  sitting.close();
  out.push([got, calls]);
}
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SittingVoiceTest(unittest.TestCase):
    """A spoken "allow" in the sitting follows the same rule as at the desk and a ring (src/leads.js, voiceAnswer)."""

    def run_js(self, cases):
        done = subprocess.run([NODE, "--input-type=module", "-e", SITTING_VOICE, ROOT, json.dumps(cases)], capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_a_private_file_is_never_allowed_by_voice(self):
        private = "Read: ~/.ssh/id_rsa"
        got = self.run_js([[private, "Look first", True, "allow", True], [private, "Look first", True, "deny", True],
                           [private, "Look first", True, "allow", False], [private, "Look first", True, "allow", None]])
        look = "That one may touch something private, so I won't answer it by voice: answer it on the screen."
        self.assertEqual(got[0], [look, []])  # said out loud: nothing is answered
        self.assertEqual(got[1], [look, []])
        self.assertEqual(got[2][1], ["allow"])  # typed in Talk: it goes, as the A key and the button do
        self.assertTrue(got[2][0].startswith("Allowed."))
        self.assertEqual(got[3][1], ["allow"])  # no word on how it came: typed

    def test_answering_by_voice_switched_off(self):
        got = self.run_js([["Bash: npm test", "Usually fine", False, "allow", True], ["Bash: npm test", "Usually fine", True, "allow", True],
                           ["Bash: npm test", "Usually fine", False, "allow", False]])
        self.assertEqual(got[0], ["Answering by voice is switched off. Answer it on the screen.", []])  # the reason it was refused
        self.assertEqual(got[1][1], ["allow"])  # switched on, and nothing private: as at the desk
        self.assertEqual(got[2][1], ["allow"])  # typed: the switch is about voice only
        for text in (got[0][0], got[1][0]):
            self.assertNotIn("\u2014", text)

    def test_the_page_says_how_it_came_and_whether_voice_may_answer(self):
        """The other half lives in src/demo.js: Talk tells the sitting a word was spoken, and hands it the switch."""
        with open(os.path.join(ROOT, "src", "demo.js"), encoding="utf-8") as handle:
            page = handle.read()
        self.assertRegex(page, r"sitting\.heard\(\s*text\s*,\s*\{\s*spoken\s*\}\s*\)")
        self.assertRegex(page, r"voiceOn:\s*\(\)\s*=>\s*features\.get\('answers'\)")


@unittest.skipUnless(NODE, "Node.js isn't installed")
class SittingPageTest(unittest.TestCase):
    def run_js(self, calls):
        done = subprocess.run([NODE, "--input-type=module", "-e", SITTING, ROOT, json.dumps(calls)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_what_you_say_in_a_sitting(self):
        q = {"kind": "question", "options": ["Blue", "Green"]}
        p = {"kind": "permission"}
        got = self.run_js([["heard", "next", q], ["heard", "Skip it", q], ["heard", "allow", p], ["heard", "deny it", p],
                           ["heard", "the first one", q], ["heard", "the second one", q], ["heard", "green", q],
                           ["heard", "Make it purple like the logo", q], ["heard", "allow", q], ["heard", "later", p],
                           ["heard", "undo", {"kind": "answered"}], ["heard", "start it", {"kind": "ready"}], ["heard", "hello", p]])
        self.assertEqual(got, [{"do": "next"}, {"do": "next"}, {"do": "allow"}, {"do": "deny"}, {"do": "pick", "option": "Blue"},
                               {"do": "pick", "option": "Green"}, {"do": "pick", "option": "Green"},
                               {"do": "words", "words": "Make it purple like the logo"}, {"do": "words", "words": "allow"}, {"do": "later"},
                               {"do": "undo"}, {"do": "start"}, None])

    def test_the_alert_the_count_and_the_summary(self):
        got = self.run_js([["minutes", 7], ["minutes", 1], ["alert", 7], ["alert", 1],
                           ["summary", {"answered": 3, "allowed": 1, "denied": 1, "later": 2, "undone": 1}], ["summary", {}],
                           ["times", "13:00, 18:00"], ["times", "9:30 18:00 9:30"], ["times", "1:00 2:00 3:00 4:00 5:00"], ["times", "noon"]])
        self.assertEqual(got[:4], [4, 1, {"title": "Arnheim", "body": "Office hours: 7 things, about 4 minutes.", "tag": got[2]["tag"]},
                                   {"title": "Arnheim", "body": "Office hours: 1 thing, about 1 minute.", "tag": got[3]["tag"]}])
        self.assertEqual(got[4], "Done. You answered 3, allowed 1, denied 1 and left 2 for later. 1 answer for you was undone.")
        self.assertEqual(got[5], "Done. Nothing needed you.")
        self.assertEqual(got[6:], [["13:00", "18:00"], ["09:30", "18:00"], "error", "error"])
        for text in got[4:6]:
            self.assertNotIn("—", text)

    def test_one_at_a_time_in_order(self):
        given = {"questions": [{"id": "q1", "key": "cc-a", "text": "Which?", "state": "open"}],
                 "asks": [{"id": "a1", "key": "cc-b", "tool": "Bash", "what": "Bash: ls"}],
                 "parked": [{"id": "p1", "kind": "question", "text": "Tabs?"}, {"id": "p2", "kind": "permission", "what": "Bash: npm i"}],
                 "answered": [{"id": "x1", "undone": False, "seen": False}, {"id": "x2", "undone": True}, {"id": "x3", "seen": True}],
                 "ready": [{"id": "r1", "title": "Speed up the login"}]}
        self.assertEqual(self.run_js([["items", given], ["items", {**given, "ready": None}]]), [
            ["question:q1", "permission:a1", "parked:p1", "parked:p2", "answered:x1", "ready:r1"],
            ["question:q1", "permission:a1", "parked:p1", "parked:p2", "answered:x1"]])  # no ready tasks in this building yet

    def test_an_office_hour_comes_once(self):
        now = datetime.datetime(2026, 11, 21, 13, 5).timestamp()
        got = self.run_js([["due", ["13:00", "18:00"], now, []], ["due", ["13:00", "18:00"], now, ["2026-11-21 13:00"]],
                           ["due", ["18:00"], now, []]])
        self.assertEqual(got, ["2026-11-21 13:00", None, None])


if __name__ == "__main__":
    unittest.main()
