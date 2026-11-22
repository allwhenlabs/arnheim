"""A chain of command (docs/connect.md, step 26; connect/deputy.py): before an agent's question waits for you, its
floor's lead answers what you have settled already, says from which decision, and lists it under Answered for you,
with Undo. Remember my answer teaches it; Always ask me and Undo keep a kind of question with you.

Each test makes a company of its own in a temporary folder (ARNHEIM_DATA), so your data/ is never touched, and drives
the hook (connect/claude_code.py, and Codex's connect/codex.py) with made-up events, as Claude Code and Codex would.
It runs under Python 3.9 too. Run from the repository's folder: python3 -m unittest discover tests
"""
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
PACKAGES = [{"question": "Which package manager should I use?", "header": "Packages",
             "options": [{"label": "pnpm", "description": "Fast"}, {"label": "npm", "description": "The usual"},
                         {"label": "yarn", "description": "Another"}], "multiSelect": False}]
COLOURS = [{"question": "Which colour for the button?", "header": "Colour",
            "options": [{"label": "Blue", "description": "As the brand"}, {"label": "Green", "description": "Stands out"}], "multiSelect": False}]
TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # made up, in a GitHub token's shape (built in two, for scanners)
# Stands in for `claude -p` when the brain judges: says what FAKE_SAY holds, whatever it was asked.
FAKE_BRAIN = "import os, sys\nsys.stdin.read()\nprint(os.environ.get('FAKE_SAY', 'NONE'))\n"


class Company(unittest.TestCase):
    """A made-up company with one floor, Lantern, where control has been used."""

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
        fake = os.path.join(self.base, "fake_brain.py")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE_BRAIN)
        self.env = dict(os.environ, ARNHEIM_DATA=self.data, ARNHEIM_CONTROL_WAIT="5", ARNHEIM_CLAUDE=f"{sys.executable} {fake}")
        self.box = control.Box(self.data)
        self.control = control.Control(self.data, claude=["true"])
        self.hook(hook_event_name="UserPromptSubmit", prompt="Set up the project")

    def hook(self, script=HOOK, **event):
        event.setdefault("session_id", SESSION)
        event.setdefault("cwd", self.lantern)
        done = subprocess.run([sys.executable, script], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=90)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def ask(self, questions, script=HOOK):
        return self.hook(script, hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": questions})

    def call(self, method, name, body=None):
        code, _, data, _ = self.control.handle(method, name, b"" if body is None else json.dumps(body).encode(), self.control.token)
        return code, json.loads(data)

    def state(self):
        return self.call("GET", "state")[1]

    def remember_memory(self, text):
        self.assertEqual(self.call("POST", "remember", {"text": text})[0], 200)

    def keep_watching(self):
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                self.box.watch()
                stop.wait(1)
        threading.Thread(target=watch, daemon=True).start()
        self.addCleanup(stop.set)


# ---------- the words: decidedFor, in step with src/memory.js ----------

ROWS = [{"id": "m1", "text": "Use pnpm, never npm or yarn."}, {"id": "m2", "text": "The login page uses the brand blue."},
        {"id": "m3", "text": "Buttons are blue, and the login button too."}, {"id": "m4", "text": "We never push on a Friday."}]
ASKS = ["Which package manager should I use? pnpm npm yarn", "What colour is the login button?", "Should I push now?",
        "Which colour for the login page buttons?", "", "the and for", "Changing the logins page"]


class WordsTest(unittest.TestCase):
    def test_decided_for_keeps_its_threshold(self):
        self.assertEqual(deputy.THRESHOLD, 2)
        self.assertEqual([r["id"] for r in deputy.decided_for(ASKS[0], ROWS)], ["m1"])
        self.assertEqual([r["id"] for r in deputy.decided_for(ASKS[1], ROWS)], ["m3"])  # "login" alone isn't enough for m2
        self.assertEqual([r["id"] for r in deputy.decided_for(ASKS[3], ROWS)], ["m2", "m3"])  # two each: a tie keeps their order
        self.assertEqual(deputy.decided_for(ASKS[2], ROWS), [])  # one word in common is not enough
        self.assertEqual(deputy.decided_for("", ROWS), [])

    @unittest.skipUnless(NODE, "Node.js isn't installed")
    def test_the_same_as_the_page(self):
        script = ("import { pathToFileURL } from 'node:url';\n"
                  "const m = await import(pathToFileURL(process.argv[1] + '/src/memory.js').href);\n"
                  "const [asks, rows] = JSON.parse(process.argv[2]);\n"
                  "console.log(JSON.stringify(asks.map((a) => m.decidedFor(a, rows, 3).map((r) => r.id))));\n")
        done = subprocess.run([NODE, "--input-type=module", "-e", script, ROOT, json.dumps([ASKS, ROWS])],
                              capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), [[r["id"] for r in deputy.decided_for(a, ROWS, 3)] for a in ASKS])

    def test_what_is_never_answered_for_you(self):
        for said in ("Should I push to main?", "Which API key should I use?", "Delete the old files?", "Can I send the email?",
                     "Publish the release now?", "Is £20 a month fine?", "Should I buy the domain?", "Post it on the blog?",
                     "Where is the .env file?", "Should I merge it?", "Which password manager?"):
            self.assertTrue(deputy.never(said), said)
        for said in ("Which package manager should I use?", "Which colour for the button?", "Tabs or spaces?", "Use a dropdown?"):
            self.assertFalse(deputy.never(said), said)

    def test_a_decision_names_one_option(self):
        self.assertEqual(deputy.chosen_option("Use pnpm, never npm or yarn.", ["pnpm", "npm", "yarn"]), "pnpm")
        self.assertIsNone(deputy.chosen_option("Either pnpm or npm is fine.", ["pnpm", "npm"]))
        self.assertIsNone(deputy.chosen_option("Don't use Blue.", ["Blue", "Green"]))
        self.assertEqual(deputy.chosen_option("Buttons are green, not blue.", ["Blue", "Green"]), "Green")
        self.assertIsNone(deputy.chosen_option("Nothing here.", ["Blue", "Green"]))


# ---------- settled: answered for you, by the proven routes ----------

class SettledTest(Company):
    def test_a_question_tool_answered_from_the_companys_memory(self):
        self.remember_memory("Use pnpm for every project, never npm or yarn")
        began = time.time()
        out = self.ask(PACKAGES)["hookSpecificOutput"]
        self.assertLess(time.time() - began, 10)  # at once: nobody needed
        self.assertEqual(out["permissionDecision"], "allow")
        answer = out["updatedInput"]["answers"]["Which package manager should I use?"]
        self.assertTrue(answer.startswith("pnpm (answered by Arnheim from the person's decision on "), answer)
        self.assertEqual(out["updatedInput"]["questions"], PACKAGES)
        self.assertIn("from their decision on", out["additionalContext"])
        self.assertIn('"Use pnpm for every project, never npm or yarn"', out["additionalContext"])
        state = self.state()
        self.assertEqual(state["questions"], [])  # it never waited for you
        one = state["answered"][0]
        self.assertEqual((one["key"], one["project"], one["answer"], one["how"], one["undone"]), (KEY, "Lantern", "pnpm", "rule", False))
        self.assertRegex(one["from"], r'^your decision on \d{1,2} \w{3}: "Use pnpm for every project, never npm or yarn"$')

    def test_remember_my_answer_then_the_same_question_is_answered(self):
        self.assertIsNone(self.ask(COLOURS))  # first time: nobody there, so it asks in its window, and waits as a card
        row = self.state()["questions"][0]
        code, got = self.call("POST", "reply_question", {"id": row["id"], "answers": {"Which colour for the button?": "Blue"}, "remember": True})
        self.assertEqual((code, got["remembered"]), (200, True))
        kept = self.state()["decisions"]["decisions"]
        self.assertEqual([(d["question"], d["answer"], d["project"]) for d in kept], [("Which colour for the button?", "Blue", "Lantern")])
        self.box.take(KEY)
        out = self.ask(COLOURS)["hookSpecificOutput"]
        self.assertTrue(out["updatedInput"]["answers"]["Which colour for the button?"].startswith("Blue (answered by Arnheim"))
        self.assertEqual(self.state()["answered"][0]["how"], "same")
        # a stored decision can be seen and removed: then it asks you again
        self.assertEqual(self.call("POST", "decision_forget", {"id": kept[0]["id"]})[0], 200)
        self.assertEqual(self.call("POST", "decision_forget", {"id": kept[0]["id"]})[0], 400)
        self.assertIsNone(self.ask(COLOURS))

    def test_a_turn_that_ends_with_the_same_question_goes_on_with_your_answer(self):
        self.assertIsNone(self.hook(hook_event_name="Stop", last_assistant_message="I made it blue.\n\nShould I change the hover colour too?"))
        row = self.state()["questions"][0]
        self.call("POST", "reply_question", {"id": row["id"], "text": "Yes, a darker blue", "remember": True})
        self.box.take(KEY)
        said = self.hook(hook_event_name="Stop", last_assistant_message="Done the header.\n\nShould I change the hover colour too?")
        self.assertEqual(said["decision"], "block")
        self.assertIn('"Should I change the hover colour too?": Yes, a darker blue', said["reason"])
        self.assertIn("Go on with that.", said["reason"])
        self.assertEqual(self.state()["questions"], [])  # no card: it went on

    def test_without_the_brain_an_open_question_needs_the_same_question(self):
        self.remember_memory("Hover colours are always a darker shade of the button colour")
        self.assertIsNone(self.hook(hook_event_name="Stop", last_assistant_message="Should the hover colour be darker too?"))
        self.assertEqual(len(self.state()["questions"]), 1)

    def test_switched_off_it_asks_you(self):
        self.remember_memory("Use pnpm for every project, never npm or yarn")
        switches.save("chain", False, self.data)
        self.assertIsNone(self.ask(PACKAGES))
        self.assertEqual(self.state()["answered"], [])
        self.assertFalse(self.state()["chain"])


class KeptTest(Company):
    """Remember my answer is kept for this computer only (data/control/), and never keeps a secret or a risky kind of question."""

    def test_kept_in_control_and_moved_there_from_before(self):
        self.assertIsNone(self.ask(COLOURS))
        row = self.state()["questions"][0]
        self.call("POST", "reply_question", {"id": row["id"], "answers": {"Which colour for the button?": "Blue"}, "remember": True})
        self.assertTrue(os.path.isfile(os.path.join(self.data, "control", "decisions.json")))
        self.assertFalse(os.path.exists(os.path.join(self.data, "decisions.json")))
        # a building from before kept them in data/decisions.json: moved in once, joined with what control/ has
        old = {"decisions": [{"id": "d-0000abcd", "project": "Lantern", "kind": "choices", "question": "Which package manager should I use?",
                              "header": "Packages", "options": ["pnpm", "npm", "yarn"], "answer": "pnpm", "at": time.time() - 86400}],
               "always_ask": [], "not_for": []}
        with open(os.path.join(self.data, "decisions.json"), "w", encoding="utf-8") as handle:
            json.dump(old, handle)
        kept = self.state()["decisions"]["decisions"]
        self.assertEqual(sorted(d["question"] for d in kept), ["Which colour for the button?", "Which package manager should I use?"])
        self.assertFalse(os.path.exists(os.path.join(self.data, "decisions.json")))  # gone from where a phone could read it
        self.box.take(KEY)
        out = self.ask(PACKAGES)["hookSpecificOutput"]
        self.assertTrue(out["updatedInput"]["answers"]["Which package manager should I use?"].startswith("pnpm (answered by Arnheim"))
        # only data/decisions.json from before: moved as it is
        shutil.rmtree(os.path.join(self.data, "control"))
        os.makedirs(os.path.join(self.data, "control"))
        with open(os.path.join(self.data, "decisions.json"), "w", encoding="utf-8") as handle:
            json.dump(old, handle)
        self.assertEqual([d["id"] for d in deputy.read_decisions(self.data)["decisions"]], ["d-0000abcd"])
        self.assertFalse(os.path.exists(os.path.join(self.data, "decisions.json")))

    def test_a_secret_or_a_risky_question_is_never_remembered(self):
        self.assertIsNone(self.hook(hook_event_name="Stop", last_assistant_message="Which token should the deploy script read?"))
        words = self.state()["questions"][0]
        code, got = self.call("POST", "reply_question", {"id": words["id"], "text": f"Use {TOKEN}", "remember": True})
        self.assertEqual(code, 400)
        self.assertIn("password, token or key", got["error"])
        self.assertIn("Untick Remember my answer", got["error"])
        self.assertEqual(self.state()["questions"][0]["id"], words["id"])  # nothing was sent: it still waits
        self.box.take(KEY)
        # a question about pushing, with a harmless answer: refused too, since the leads never answer it
        self.assertIsNone(self.ask([{"question": "Should I push the branch now?", "header": "Branch",
                                     "options": [{"label": "Yes", "description": ""}, {"label": "No", "description": ""}], "multiSelect": False}]))
        push = next(q for q in self.state()["questions"] if q["kind"] == "choices")
        code, got = self.call("POST", "reply_question", {"id": push["id"], "answers": {"Should I push the branch now?": "No"}, "remember": True})
        self.assertEqual(code, 400)
        self.assertIn("pushing", got["error"])
        # without the tick, the same answer goes as it always did
        self.assertEqual(self.call("POST", "reply_question", {"id": push["id"], "answers": {"Should I push the branch now?": "No"}})[0], 200)
        # a secret in the answer to a harmless question
        self.box.take(KEY)
        self.assertIsNone(self.ask(COLOURS))
        colour = next(q for q in self.state()["questions"] if q["text"] == "Which colour for the button?")
        code, got = self.call("POST", "reply_question", {"id": colour["id"], "text": f"Blue, and the key is {TOKEN}", "remember": True})
        self.assertEqual(code, 400)
        self.assertEqual(self.state()["decisions"]["decisions"], [])
        self.assertFalse(os.path.exists(os.path.join(self.data, "control", "decisions.json")))
        with self.assertRaises(ValueError):  # and nothing else can keep one either
            deputy.remember_answer(self.data, "Lantern", "Which colour for the button?", f"Blue {TOKEN}", ["Blue", "Green"])


class NeverTest(Company):
    def test_risky_first_time_and_always_ask_are_never_answered(self):
        self.remember_memory("Always push to the main branch after the tests pass")
        self.remember_memory("The API key for the maps service is the one in the shared vault")
        yes_no = [{"label": "Yes", "description": ""}, {"label": "No", "description": ""}]
        for q in ("Should I push to the main branch now?", "Which API key for the maps service?"):
            self.assertIsNone(self.ask([{"question": q, "header": "", "options": yes_no, "multiSelect": False}]), q)
        self.assertIsNone(self.ask(COLOURS))  # never answered before, and no decision covers it
        self.assertEqual(self.state()["answered"], [])
        # Always ask me: even a decision that answers it waits for you
        self.remember_memory("Use pnpm for every project, never npm or yarn")
        self.assertIsNone(self.ask(COLOURS))
        row = [q for q in self.state()["questions"] if q["kind"] == "choices"][-1]
        self.call("POST", "reply_question", {"id": row["id"], "answers": {"Which colour for the button?": "Green"}, "always_ask": True})
        self.assertEqual(len(self.state()["decisions"]["always_ask"]), 1)
        self.call("POST", "remember", {"text": "The button colour is green, never blue"})
        self.assertIsNone(self.ask(COLOURS))

    def test_a_permission_is_never_answered_from_a_decision(self):
        self.remember_memory("Running npm install is fine on Lantern")
        out = self.hook(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "npm install"})
        self.assertIsNone(out)  # nobody there: it asks in its own window, as always
        self.assertEqual(self.state()["answered"], [])

    def test_a_decision_that_is_risky_itself_is_never_used(self):
        self.remember_memory("Blue buttons, and delete the old green ones")
        self.assertIsNone(self.ask(COLOURS))


# ---------- Undo ----------

class UndoTest(Company):
    def test_undo_tells_the_agent_before_its_next_step_and_keeps_that_decision_away(self):
        self.remember_memory("Use pnpm for every project, never npm or yarn")
        self.assertIsNotNone(self.ask(PACKAGES))
        aid = self.state()["answered"][0]["id"]
        code, got = self.call("POST", "answered_undo", {"id": aid})
        self.assertEqual((code, got["sent"]), (200, "queued"))
        self.assertEqual(self.call("POST", "answered_undo", {"id": aid})[0], 400)  # once
        self.assertTrue(self.state()["answered"][0]["undone"])
        said = self.hook(hook_event_name="PreToolUse", tool_name="Read", tool_input={"file_path": "a.txt"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("The person changed this: don't take that earlier decision as the answer.", said)
        self.assertIn('"Which package manager should I use?"', said)
        # the same kind of question comes to you now
        self.assertIsNone(self.ask(PACKAGES))
        self.assertEqual(len(self.state()["questions"]), 1)
        self.assertEqual(len(self.state()["answered"]), 1)

    def test_undo_with_your_words(self):
        self.remember_memory("Use pnpm for every project, never npm or yarn")
        self.ask(PACKAGES)
        aid = self.state()["answered"][0]["id"]
        self.call("POST", "answered_undo", {"id": aid, "words": "Use yarn on this one, it's an old project"})
        said = self.hook(hook_event_name="PreToolUse", tool_name="Read", tool_input={"file_path": "a.txt"})["hookSpecificOutput"]["additionalContext"]
        self.assertIn("The person changed this: Use yarn on this one, it's an old project.", said)

    def test_codex_hears_an_undo_after_its_step(self):
        self.remember_memory("Hover colours are always a darker shade of the button colour")
        self.call("POST", "reply_question", {"id": "x" * 16, "text": "no"})  # nothing waiting: refused, harmless
        # a turn of Codex's that ends with the same question it was answered before
        self.hook(CODEX, hook_event_name="Stop", last_assistant_message="Should the footer stay grey?")
        row = self.state()["questions"][0]
        self.call("POST", "reply_question", {"id": row["id"], "text": "Yes, keep it grey", "remember": True})
        self.box.take(KEY)
        said = self.hook(CODEX, hook_event_name="Stop", last_assistant_message="Tidied the footer.\n\nShould the footer stay grey?")
        self.assertEqual(said["decision"], "block")
        self.assertIn("Yes, keep it grey", said["reason"])
        aid = self.state()["answered"][0]["id"]
        self.assertEqual(self.state()["answered"][0]["agent"], "Codex")
        self.call("POST", "answered_undo", {"id": aid, "words": "Make it white"})
        self.assertIsNone(self.hook(CODEX, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "ls"}))  # Codex: not before
        out = self.hook(CODEX, hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "ls"}, tool_response="ok")
        self.assertIn("The person changed this: Make it white.", out["hookSpecificOutput"]["additionalContext"])


# ---------- with the brain: the lead judges, and must quote ----------

class BrainTest(Company):
    def setUp(self):
        super().setUp()
        switches.save("brain", True, self.data)
        self.remember_memory("Hover colours are always a darker shade of the button colour")

    def stop(self):
        return self.hook(hook_event_name="Stop", last_assistant_message="Should the hover colour be darker too?")

    def test_the_lead_answers_when_it_quotes_your_decision(self):
        self.env["FAKE_SAY"] = "QUOTE: Hover colours are always a darker shade of the button colour\nANSWER: Yes, a darker shade"
        said = self.stop()
        self.assertEqual(said["decision"], "block")
        self.assertIn("Yes, a darker shade", said["reason"])
        self.assertEqual(self.state()["answered"][0]["how"], "lead")

    def test_a_made_up_quote_or_none_answers_nothing(self):
        for say in ("QUOTE: Hover colours are always lighter\nANSWER: Yes", "NONE", "I think yes."):
            self.env["FAKE_SAY"] = say
            self.assertIsNone(self.stop(), say)
        self.assertEqual(self.state()["answered"], [])

    def test_for_options_the_answer_must_be_one_of_them(self):
        self.remember_memory("Buttons on the welcome screen follow the brand colours")
        question = [{"question": "Which colour for the welcome screen buttons?", "header": "",
                     "options": [{"label": "Brand blue", "description": ""}, {"label": "Grey", "description": ""}], "multiSelect": False}]
        self.env["FAKE_SAY"] = "QUOTE: Buttons on the welcome screen follow the brand colours\nANSWER: Purple"
        self.assertIsNone(self.ask(question))
        self.env["FAKE_SAY"] = "QUOTE: Buttons on the welcome screen follow the brand colours\nANSWER: Brand blue"
        out = self.ask(question)["hookSpecificOutput"]
        self.assertTrue(out["updatedInput"]["answers"]["Which colour for the welcome screen buttons?"].startswith("Brand blue (answered"))


class ContractTest(Company):
    def test_the_names_the_page_and_the_other_builder_use(self):
        for name in ("answered_undo", "decision_forget", "office"):
            self.assertTrue(re.match(r"^[a-z_]{1,16}$", name))
            self.assertNotEqual(self.call("POST", name, {})[0], 404, name)
        state = self.state()
        for key in ("answered", "office", "decisions", "parked", "chain"):
            self.assertIn(key, state)
        self.assertEqual(set(state["office"]) >= {"on", "times", "open", "next", "parked"}, True)
        self.assertTrue(switches.DEFAULTS["chain"])
        self.assertFalse(switches.DEFAULTS["office_hours"])

    def test_loads_by_its_path_alone_on_both_pythons(self):
        script = ("import importlib.util, sys\n"
                  "spec = importlib.util.spec_from_file_location('another_deputy', sys.argv[1])\n"
                  "module = importlib.util.module_from_spec(spec)\n"
                  "spec.loader.exec_module(module)\n"
                  "print(module.office_times(sys.argv[2]), module.never('push it'))\n")
        for python in [sys.executable] + (["/usr/bin/python3"] if os.path.exists("/usr/bin/python3") else []):
            done = subprocess.run([python, "-I", "-c", script, os.path.join(ROOT, "connect", "deputy.py"), self.data],
                                  capture_output=True, text=True, timeout=60, cwd=self.base)
            self.assertEqual(done.returncode, 0, (python, done.stderr))
            self.assertEqual(done.stdout.strip(), "['13:00', '18:00'] True", python)


if __name__ == "__main__":
    unittest.main()
