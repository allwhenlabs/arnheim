"""The building learns from your corrections (docs/connect.md, "The building learns from your corrections";
connect/deputy.py, connect/control.py). When you Undo an answer a lead gave for you, the building asks once, in the
same place: "Should the leads stop answering this kind of question for you?" Yes keeps that kind of question with you,
with the words it came from, listed under What the leads answer from with Remove; No says nothing more and it never
asks again about that decision. The second Undo of an answer from the same decision sets that decision aside without
asking, and says so, with Undo. Show me's Not quite asks "Should Show me ask you before calling this kind of change
done?", and Yes keeps work of that kind, started by the building, waiting for your Looks good. Never from a secret.

Each test makes a company of its own in a temporary folder (ARNHEIM_DATA), so your data/ is never touched, and drives
the hook (connect/claude_code.py) with made-up events, as Claude Code would. It runs under Python 3.9 too. Run from
the repository's folder: python3 -m unittest discover tests
"""
import json
import os
import re
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
import deputy  # noqa: E402
import show  # noqa: E402
import switches  # noqa: E402

HOOK = os.path.join(ROOT, "connect", "claude_code.py")
NODE = shutil.which("node")
SESSION = "abc123def456-7890"
KEY = "cc-abc123def456"
TRIO = [{"label": "pnpm", "description": ""}, {"label": "npm", "description": ""}, {"label": "yarn", "description": ""}]
PACKAGES = [{"question": "Which package manager should I use?", "header": "Packages", "options": TRIO, "multiSelect": False}]
INSTALL = [{"question": "Which tool installs the dependencies?", "header": "Install", "options": TRIO, "multiSelect": False}]
SCRIPTS = [{"question": "Which runner for the build scripts?", "header": "Runner", "options": TRIO, "multiSelect": False}]
PNPM = "Use pnpm for every project, never npm or yarn"
TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # made up, in a GitHub token's shape (built in two, for scanners)
# Stands in for `claude -p`: says back what it was handed.
FAKE_CLAUDE = r'''
import json, sys
words = sys.stdin.read()
said = "started: " + words[:200]
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}}), flush=True)
print(json.dumps({"type": "result", "result": said}), flush=True)
'''
# Stands in for a floor's show command: prints what it did, so Show me makes a card from it.
SHOW_COMMAND = "import os\nprint('Showed the home page,', os.environ['ARNHEIM_SHOW_PHASE'])\n"


class Company(unittest.TestCase):
    """A made-up company with one floor, Lantern, where control has been used."""

    floor_extra = {}

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.data = os.path.join(self.base, "data")
        self.lantern = os.path.join(self.base, "code", "lantern")
        os.makedirs(os.path.join(self.data, "control"))
        os.makedirs(self.lantern)
        fake = os.path.join(self.base, "fake_claude.py")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE_CLAUDE)
        command = os.path.join(self.base, "show_command.py")
        with open(command, "w", encoding="utf-8") as handle:
            handle.write(SHOW_COMMAND)
        extra = {"show": {"run": [sys.executable, command], "timeout": 30}} if self.floor_extra == "show" else {}
        with open(os.path.join(self.data, "company.json"), "w", encoding="utf-8") as handle:
            json.dump({"company": "Example Studio", "rooms": [{"id": "work", "label": "Work"}],
                       "floors": [{"id": "lantern", "label": "Lantern", "folder": self.lantern, **extra}],
                       "feeds": ["feeds/claude-code.json"]}, handle)
        self.env = dict(os.environ, ARNHEIM_DATA=self.data, ARNHEIM_CONTROL_WAIT="5")
        self.box = control.Box(self.data)
        self.control = control.Control(self.data, claude=[sys.executable, fake])

    def hook(self, **event):
        event.setdefault("session_id", SESSION)
        event.setdefault("cwd", self.lantern)
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=90)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def ask(self, questions):
        self.box.take(KEY)  # what the last ask left waiting is put away, so each is asked afresh
        return self.hook(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": questions})

    def call(self, name, body=None, method="POST"):
        code, _, data, _ = self.control.handle(method, name, b"" if body is None else json.dumps(body).encode(), self.control.token)
        return code, json.loads(data)

    def state(self):
        return self.call("state", method="GET")[1]

    def answered_for(self, questions):
        """Asks, and gives the id of what the lead answered for you."""
        self.assertIsNotNone(self.ask(questions), questions[0]["question"])
        return next(a["id"] for a in self.state()["answered"] if a["question"] == questions[0]["question"])

    def until(self, check, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            got = check()
            if got:
                return got
            time.sleep(0.1)
        self.fail("it never happened")


class FromAnUndo(Company):
    def setUp(self):
        super().setUp()
        self.hook(hook_event_name="UserPromptSubmit", prompt="Set up the project")
        self.assertEqual(self.call("remember", {"text": PNPM})[0], 200)

    def test_asked_once_after_an_undo_and_yes_keeps_that_kind_of_question_with_you(self):
        aid = self.answered_for(PACKAGES)
        code, got = self.call("answered_undo", {"id": aid, "words": "Use yarn on this one, it's an old project"})
        self.assertEqual(code, 200, got)
        self.assertEqual(got["learn"], {"ask": "Should the leads stop answering this kind of question for you?"})
        self.assertEqual(self.state()["answered"][0]["learn"]["ask"], deputy.LEARN_ASK)  # and in the same place on the page
        code, got = self.call("learn_yes", {"id": aid})
        self.assertEqual(code, 200, got)
        self.assertIn("won't answer that kind of question for you again", got["reply"])
        self.assertIsNone(self.state()["answered"][0]["learn"])  # asked once
        self.assertEqual(self.call("learn_yes", {"id": aid})[0], 400)
        always = self.state()["decisions"]["always_ask"]
        self.assertEqual([(a["question"], a["show"]) for a in always], [("Which package manager should I use?", False)])
        self.assertIn('You undid "pnpm"', always[0]["from"])  # with the words it came from
        self.assertIn("Use yarn on this one, it's an old project", always[0]["from"])
        # another decision that would answer it: that kind of question still comes to you
        self.call("remember", {"text": "pnpm is the package manager on Lantern, not npm or yarn"})
        self.assertIsNone(self.ask(PACKAGES))
        # Remove, under What the leads answer from: the leads may answer it again
        self.assertEqual(self.call("decision_forget", {"id": always[0]["id"]})[0], 200)
        self.assertIsNotNone(self.ask(PACKAGES))

    def test_no_says_nothing_more_and_never_asks_again_about_that_decision(self):
        aid = self.answered_for(PACKAGES)
        self.call("answered_undo", {"id": aid})
        code, got = self.call("learn_no", {"id": aid})
        self.assertEqual((code, got["reply"]), (200, ""))
        self.assertIsNone(self.state()["answered"][0]["learn"])
        self.assertEqual(self.state()["decisions"]["always_ask"], [])
        doc = deputy.read_decisions(self.data)
        self.assertEqual(len(doc["declined"]), 1)
        frm = deputy.answered_row(self.data, aid)["answers"][0]["from"]["id"]
        # an answer from that decision, undone later: nothing is asked about it
        later = {"id": "x", "undone": True, "undone_at": time.time(), "project": "Lantern",
                 "answers": [{"question": "Which tool installs the dependencies?", "answer": "pnpm", "from": {"id": frm}}]}
        self.assertIsNone(deputy.learning(self.data, later))
        later["answers"][0]["from"]["id"] = "m-another"
        self.assertEqual(deputy.learning(self.data, later), {"ask": deputy.LEARN_ASK})

    def test_two_undos_of_the_same_decision_set_it_aside_and_say_so_with_undo(self):
        first = self.answered_for(PACKAGES)
        self.call("answered_undo", {"id": first})
        second = self.answered_for(INSTALL)  # another kind of question, answered from the same decision
        code, got = self.call("answered_undo", {"id": second})
        self.assertEqual(code, 200, got)
        self.assertIn("set it aside", got["learn"]["said"])  # without asking
        self.assertNotIn("ask", got["learn"])
        row = next(a for a in self.state()["answered"] if a["id"] == second)
        self.assertEqual(row["learn"]["set_aside"], got["learn"]["set_aside"])
        aside = self.state()["decisions"]["set_aside"]
        self.assertEqual([n["text"] for n in aside], [PNPM])
        self.assertIsNone(self.ask(SCRIPTS))  # a third kind it would have answered: not from a decision set aside
        # Undo, where it said so: the leads may answer from it again
        code, got = self.call("learn_undo", {"id": second})
        self.assertEqual(code, 200, got)
        self.assertEqual(self.state()["decisions"]["set_aside"], [])
        self.assertIsNone(next(a for a in self.state()["answered"] if a["id"] == second)["learn"])
        self.assertIsNotNone(self.ask(SCRIPTS))
        self.assertEqual(self.call("learn_undo", {"id": second})[0], 400)
        self.assertIsNone(self.ask(INSTALL))  # the kinds you undid stay with you

    def test_never_learns_from_a_secret(self):
        aid = self.answered_for(PACKAGES)
        code, got = self.call("answered_undo", {"id": aid, "words": f"Use yarn, the token is {TOKEN}"})
        self.assertEqual(code, 200, got)
        self.assertIsNone(got["learn"])
        self.assertEqual(self.call("learn_yes", {"id": aid})[0], 400)
        second = self.answered_for(INSTALL)
        self.call("answered_undo", {"id": second, "words": f"no, and here is the key {TOKEN}"})
        self.assertEqual(self.state()["decisions"]["set_aside"], [])  # not set aside from words with a secret either
        self.assertNotIn(TOKEN, json.dumps(deputy.read_decisions(self.data)))
        with self.assertRaises(ValueError):
            deputy.ask_always(self.data, "Lantern", "Which package manager?", came_from=f"You said {TOKEN}")

    def test_a_secret_undone_while_switched_off_is_never_asked_about_later(self):
        # Found by the Checker: with learning off at the Undo, the secret wasn't looked for, so switching learning on
        # afterwards asked about it, and a No kept its question.
        switches.save("learn", False, self.data)
        aid = self.answered_for(PACKAGES)
        code, got = self.call("answered_undo", {"id": aid, "words": f"Use yarn, the token is {TOKEN}"})
        self.assertEqual(code, 200, got)
        self.assertTrue(deputy.answered_row(self.data, aid).get("no_learning"))
        switches.save("learn", True, self.data)
        self.assertIsNone(next(a for a in self.state()["answered"] if a["id"] == aid)["learn"])  # nothing asked
        self.assertEqual(self.call("learn_no", {"id": aid})[0], 400)
        self.assertEqual(deputy.read_decisions(self.data)["declined"], [])
        # an answer undone before the mark was kept: the secret is looked for again before anything is asked
        row = dict(deputy.answered_row(self.data, aid), no_learning=False)
        self.assertIsNone(deputy.learning(self.data, row))
        # and a No never keeps a question with a secret in it
        self.assertIsNone(deputy.decline(self.data, "Lantern", f"Which branch is {TOKEN} for?", decision="m-something"))
        self.assertNotIn(TOKEN, json.dumps(deputy.read_decisions(self.data)))

    def test_switched_off_nothing_is_asked_or_set_aside(self):
        self.assertTrue(switches.DEFAULTS["learn"])
        switches.save("learn", False, self.data)
        first = self.answered_for(PACKAGES)
        code, got = self.call("answered_undo", {"id": first})
        self.assertIsNone(got["learn"])
        code, got = self.call("learn_yes", {"id": first})
        self.assertEqual(code, 400)
        self.assertIn("switched off", got["error"])
        second = self.answered_for(INSTALL)
        self.assertIsNone(self.call("answered_undo", {"id": second})[1]["learn"])
        self.assertEqual(self.state()["decisions"]["set_aside"], [])
        self.assertFalse(self.state()["learn"])


# Near the rule "Change the heading colour on the home page": the same kind of change, and another kind of change that
# is still the same kind of question (heading, home and page in common).
SAME_CHANGE = "Make the home page heading colour darker"
ANOTHER_CHANGE = "Fix the heading on the home page"


class FromNotQuite(Company):
    floor_extra = "show"
    talking = False

    def card(self, turn=1000, title="Change the heading colour on the home page", state="waiting", words=None, conv=KEY):
        """A Show me card of the hook's conversation, waiting for you: one turn's finished work."""
        if not self.talking:
            self.hook(hook_event_name="UserPromptSubmit", prompt="Change the heading colour on the home page")
            self.talking = True
        row = {"about": show.ABOUT, "key": show.key_for(conv, turn), "conv": conv, "project": "Lantern", "turn": turn, "phase": "ready",
               "at": time.time(), "state": state, "title": title, "said": "Done.", "pictures": [], "output": {"after": "Showed it"}}
        if words:
            row.update(words=words, decided_at=time.time())
        show.save(self.data, row)
        return row["key"]

    def test_asked_once_after_not_quite_and_yes_is_listed_with_the_words(self):
        key = self.card()
        code, got = self.call("show_again", {"key": key, "words": "The heading should be darker"})
        self.assertEqual(code, 200, got)
        self.assertEqual(got["learn"], {"ask": "Should Show me ask you before calling this kind of change done?"})
        listed = next(s for s in self.state()["shows"] if s["key"] == key)
        self.assertEqual(listed["learn"]["ask"], deputy.SHOW_ASK)
        code, got = self.call("learn_yes", {"show": key})
        self.assertEqual(code, 200, got)
        self.assertIn("Looks good", got["reply"])
        self.assertIsNone(next(s for s in self.state()["shows"] if s["key"] == key)["learn"])
        always = self.state()["decisions"]["always_ask"]
        self.assertEqual([(a["question"], a["show"]) for a in always], [("Change the heading colour on the home page", True)])
        self.assertIn("The heading should be darker", always[0]["from"])
        self.assertEqual(deputy.looks_first(self.data, "Lantern", "Make the home page heading colour darker")["id"], always[0]["id"])
        self.assertIsNone(deputy.looks_first(self.data, "Lantern", "Fix the login form"))
        # the same kind of change again: not asked again
        other = self.card(turn=2000, title="Change the heading colour on the home page to dark blue")
        self.assertIsNone(self.call("show_again", {"key": other, "words": "Smaller"})[1]["learn"])
        # never a question the leads keep from you: a show rule is Show me's alone, so a decision that answers this
        # question still answers it (the rule and the question share four words, a kind of question for the leads)
        question = [{"question": "Which colour for the home page heading?", "options": [{"label": "Blue"}, {"label": "Red"}]}]
        self.assertTrue(deputy.same_kind(always[0]["question"], question[0]["question"]))
        self.assertIsNone(deputy.settle(self.data, "choices", "Lantern", question))  # nothing decided yet
        self.assertEqual(self.call("remember", {"text": "The home page heading colour is Blue on Lantern"})[0], 200)
        got = deputy.settle(self.data, "choices", "Lantern", question)
        self.assertIsNotNone(got)
        self.assertEqual((got["answers"][0]["answer"], got["how"]), ("Blue", "rule"))

    def test_a_kind_of_change_shares_three_words_beyond_the_ones_every_change_has(self):
        # Found by the Checker: two shared words held too much ("home" and "page" are in most titles on a site).
        deputy.ask_always(self.data, "Lantern", "Change the heading colour on the home page", came_from="Not quite", show=True)
        rule = deputy.read_decisions(self.data)["always_ask"][-1]["id"]
        for near in ("Make the home page heading colour darker", "change the heading colour on the home page",
                     "Fix the heading colour on the home pages"):
            self.assertEqual((deputy.looks_first(self.data, "Lantern", near) or {}).get("id"), rule, near)
        for other in ("Add a search box to the home page", "Fix the heading on the home page",
                      "Update the footer colour on the home page", "Change the heading font on the about page"):
            self.assertIsNone(deputy.looks_first(self.data, "Lantern", other), other)
        self.assertIsNone(deputy.looks_first(self.data, "Tidepool", "Make the home page heading colour darker"))  # another floor

    def test_a_rule_with_fewer_words_needs_them_all_and_two_at_least(self):
        # Found by the Checker: three shared words meant a rule with only two that carry meaning ("Fix the login form":
        # login, form) held nothing but its own title.
        deputy.ask_always(self.data, "Lantern", "Fix the login form", came_from="Not quite", show=True)
        rule = deputy.read_decisions(self.data)["always_ask"][-1]["id"]
        for near in ("Make the login form wider", "fix the login form", "Add a login form to the about page"):
            self.assertEqual((deputy.looks_first(self.data, "Lantern", near) or {}).get("id"), rule, near)
        for other in ("Fix the search form", "Fix the login button", "Make the sign up form wider"):
            self.assertIsNone(deputy.looks_first(self.data, "Lantern", other), other)
        # one such word: its own title alone, never a single word in common
        deputy.ask_always(self.data, "Lantern", "Fix the footer", came_from="Not quite", show=True)
        self.assertIsNotNone(deputy.looks_first(self.data, "Lantern", "fix the footer"))
        self.assertIsNone(deputy.looks_first(self.data, "Lantern", "Fix the footer links"))

    def test_kept_already_goes_by_the_kind_of_change_not_the_kind_of_question(self):
        # A test gap the Checker found: kept already compares titles as kinds of change (three words), never as kinds
        # of question (two), so a near title that is another change is still asked about.
        self.assertTrue(deputy.same_kind("Change the heading colour on the home page", ANOTHER_CHANGE))  # the case this guards
        key = self.card()
        self.call("show_again", {"key": key, "words": "Darker"})
        self.assertEqual(self.call("learn_yes", {"show": key})[0], 200)
        self.assertIsNone(self.sent_back(2000, SAME_CHANGE))  # that kind of change is kept already
        self.assertEqual(self.sent_back(3000, ANOTHER_CHANGE), {"ask": deputy.SHOW_ASK})  # another kind: asked

    def test_said_no_goes_by_the_kind_of_change_not_the_kind_of_question(self):
        # The same gap for No: never asked again about that kind of change, and still asked about another.
        key = self.card()
        self.call("show_again", {"key": key, "words": "Darker"})
        self.assertEqual(self.call("learn_no", {"show": key})[0], 200)
        self.assertIsNone(self.sent_back(2000, SAME_CHANGE))
        self.assertEqual(self.sent_back(3000, ANOTHER_CHANGE), {"ask": deputy.SHOW_ASK})

    def sent_back(self, turn, title):
        """Not quite on a card of this title: what it asks."""
        return self.call("show_again", {"key": self.card(turn=turn, title=title), "words": "Smaller"})[1]["learn"]

    def test_no_and_a_secret_are_never_learned_from(self):
        key = self.card()
        self.call("show_again", {"key": key, "words": "Darker"})
        self.assertEqual(self.call("learn_no", {"show": key})[1]["reply"], "")
        other = self.card(turn=2000, title="Change the home page heading colour to dark blue")
        self.assertIsNone(self.call("show_again", {"key": other, "words": "Smaller"})[1]["learn"])  # never asked again
        secret = self.card(turn=3000, title="Tidy the footer links")
        self.assertIsNone(self.call("show_again", {"key": secret, "words": f"Use {TOKEN} for it"})[1]["learn"])
        self.assertEqual(self.call("learn_yes", {"show": secret})[0], 400)
        self.assertEqual(self.state()["decisions"]["always_ask"], [])

    def test_work_of_that_kind_waits_for_your_look_before_it_is_done(self):
        deputy.ask_always(self.data, "Lantern", "Change the heading colour on the home page", came_from="Not quite", show=True)
        code, got = self.call("intake", {"text": "Make the home page heading colour darker on Lantern", "via": "box"})
        self.assertEqual(code, 200, got)
        rid = got["task"]["id"]
        key = self.call("ready_start", {"id": rid})[1]["task"]["key"]
        card = self.until(lambda: next((s for s in show.listing(self.data) if s["conv"] == key and s["state"] == "waiting"), None))
        run = self.until(lambda: (lambda r: r if r and r.get("state") == "done" else None)(self.control.runs.get(key)))
        self.assertTrue(self.control.awaiting_look(run))
        self.control.intake.ticked = 0
        self.control.state()  # the front door's tick: what finished while nobody said so
        self.assertEqual(self.control.intake.task(rid)["state"], "started")  # not counted done
        self.assertTrue(day.running(self.control, key))  # nor is the daily plan's item
        self.assertIn("Looks good", next(s for s in self.state()["shows"] if s["key"] == card["key"])["held"])
        # the floor's next ready task waits with it, and says why
        nxt = self.call("intake", {"text": "Fix the login form on Lantern", "via": "box"})[1]["task"]["id"]
        code, got = self.call("ready_start", {"id": nxt})
        self.assertEqual(code, 200, got)
        self.assertEqual(self.control.intake.task(nxt)["state"], "queued")
        self.assertIn("waits for you to look at it on Show me", self.control.intake.task(nxt)["why"])
        code, got = self.call("show_ok", {"key": card["key"]})
        self.assertEqual(code, 200, got)
        self.assertFalse(self.control.awaiting_look(key))
        self.assertEqual(self.control.intake.task(rid)["state"], "finished")
        self.assertFalse(day.running(self.control, key))
        self.assertIn(self.control.intake.task(nxt)["state"], ("started", "finished"))  # and now it starts

    def test_the_hold_is_decided_as_the_run_is_saved_done(self):
        # Found by the Checker: Control saved the run as done, and only after that marked it as waiting for your look, so
        # the daily plan or the night shift reading it between the two counted the work done.
        deputy.ask_always(self.data, "Lantern", "Change the heading colour on the home page", came_from="Not quite", show=True)
        saved, real = [], self.control.save
        self.control.save = lambda run: (saved.append(dict(run)), real(run))
        keys = []
        for text in ("Fix the login form on Lantern", "Make the home page heading colour darker on Lantern"):  # one floor: the held one last
            rid = self.call("intake", {"text": text, "via": "box"})[1]["task"]["id"]
            keys.append(self.call("ready_start", {"id": rid})[1]["task"]["key"])
            self.until(lambda: any(r.get("key") == keys[-1] and r.get("state") == "done" for r in saved) or None)
        other, held = (next(r for r in saved if r.get("key") == k and r.get("state") == "done") for k in keys)
        self.assertEqual(held["look"]["rule"], deputy.read_decisions(self.data)["always_ask"][-1]["id"])
        self.assertNotIn("look", other)

    def test_other_work_is_done_as_it_finishes(self):
        deputy.ask_always(self.data, "Lantern", "Change the heading colour on the home page", came_from="Not quite", show=True)
        code, got = self.call("intake", {"text": "Fix the login form on Lantern", "via": "box"})
        rid = got["task"]["id"]
        self.call("ready_start", {"id": rid})
        self.until(lambda: self.control.intake.task(rid)["state"] == "finished" or None)


class TheParts(Company):
    def test_names_switch_and_docs(self):
        for name in ("learn_yes", "learn_no", "learn_undo"):
            self.assertTrue(re.match(r"^[a-z][a-z_]{0,15}$", name))
            self.assertNotEqual(self.call(name, {})[0], 404, name)
        row = next(s for s in switches.SWITCHES if s[0] == "learn")
        self.assertEqual((row[1], row[2], row[4]), ("agents", "Learn from your corrections", True))
        with open(os.path.join(ROOT, "docs", "connect.md"), encoding="utf-8") as handle:
            docs = handle.read()
        self.assertIn("The building learns from your corrections", docs)
        self.assertIn("learn_yes", docs)
        self.assertIn('"Make the login form wider" is the same kind as "Fix the login form"', " ".join(docs.split()))  # a rule of two such words
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
            self.assertIn("learns from your corrections", handle.read())

    def test_loads_by_its_path_alone_on_both_pythons(self):
        script = ("import importlib.util, sys\n"
                  "spec = importlib.util.spec_from_file_location('another_deputy', sys.argv[1])\n"
                  "module = importlib.util.module_from_spec(spec)\n"
                  "spec.loader.exec_module(module)\n"
                  f"print(module.has_secret('make the button blue'), module.has_secret('the token is {TOKEN}'), module.learn_on(sys.argv[2]))\n")
        for python in [sys.executable] + (["/usr/bin/python3"] if os.path.exists("/usr/bin/python3") else []):
            done = subprocess.run([python, "-I", "-c", script, os.path.join(ROOT, "connect", "deputy.py"), self.data],
                                  capture_output=True, text=True, timeout=60, cwd=self.base)
            self.assertEqual(done.returncode, 0, (python, done.stderr))
            self.assertEqual(done.stdout.strip(), "False True True", python)

    def test_no_long_dashes_in_what_people_read(self):
        for rel in ("connect/deputy.py", "src/sitting.js", "src/sitting.css", "src/show-me.js", "src/show-me.css"):
            with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
                self.assertNotIn("—", handle.read(), rel)


PAGE = """
import { pathToFileURL } from 'node:url';
const s = await import(pathToFileURL(process.argv[1] + '/src/sitting.js').href);
const m = await import(pathToFileURL(process.argv[1] + '/src/show-me.js').href);
console.log(JSON.stringify({
  heard: ['yes', 'Yes please.', 'stop answering them', 'no', 'No thanks', 'keep answering', 'next', 'maybe'].map((t) => s.learnHeard(t)),
  ask: m.SHOW_ASK,
  asking: m.askingOf([{ key: 'a', state: 'again', learn: { ask: m.SHOW_ASK } }, { key: 'b', state: 'again', learn: null },
    { key: 'c', state: 'waiting', learn: { ask: 'x' } }, null]).map((x) => x.key),
}));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageTest(unittest.TestCase):
    def test_the_page_words(self):
        done = subprocess.run([NODE, "--input-type=module", "-e", PAGE, ROOT], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        got = json.loads(done.stdout)
        self.assertEqual(got["heard"], ["yes", "yes", "yes", "no", "no", "no", None, None])
        self.assertEqual(got["ask"], deputy.SHOW_ASK)  # in step with connect/deputy.py
        self.assertEqual(got["asking"], ["a"])


if __name__ == "__main__":
    unittest.main()
