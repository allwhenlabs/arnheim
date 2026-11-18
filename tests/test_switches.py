"""The switches (connect/switches.py, serve.py's /switches, the Company page): every feature on or off, kept for every
start in data/serve.json, honoured by the hooks at each event and by serve.py at once, changed only from this
computer's own page with its token, and held for a start by a word serve.py started with. Each test makes a company of
its own in a temporary folder.

Run from the repository's folder: python3 -m unittest discover tests
"""
import argparse
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
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "connect"))

import budget  # noqa: E402
import serve  # noqa: E402
import standing  # noqa: E402
import switches  # noqa: E402

HOOK = os.path.join(ROOT, "connect", "claude_code.py")


class FileTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)

    def test_defaults_then_what_you_chose(self):
        self.assertTrue(switches.on("handovers", self.data))
        self.assertFalse(switches.on("routines", self.data))
        self.assertFalse(switches.on("control", self.data))
        self.assertFalse(switches.on("no such thing", self.data))
        switches.save("handovers", False, self.data)
        switches.save("routines", True, self.data)
        self.assertFalse(switches.on("handovers", self.data))
        self.assertTrue(switches.on("routines", self.data))

    def test_setup_s_answer_is_kept_and_read(self):
        with open(switches.path(self.data), "w") as handle:
            json.dump({"control": True, "something": "else"}, handle)  # as connect/setup.py writes it
        self.assertTrue(switches.on("control", self.data))
        switches.save("git", False, self.data)
        with open(switches.path(self.data)) as handle:
            self.assertEqual(json.load(handle), {"control": True, "something": "else", "git": False})

    def test_only_true_or_false_counts(self):
        with open(switches.path(self.data), "w") as handle:
            json.dump({"handovers": "no", "routines": 1, "budget": None}, handle)
        self.assertTrue(switches.on("handovers", self.data))
        self.assertFalse(switches.on("routines", self.data))
        self.assertTrue(switches.on("budget", self.data))
        with open(switches.path(self.data), "w") as handle:
            handle.write("[not an object")
        self.assertTrue(switches.on("handovers", self.data))
        for name, value in (("nothing", True), ("git", "yes"), ("git", 1)):
            with self.assertRaises(ValueError):
                switches.save(name, value, self.data)

    def test_a_file_too_deep_to_read_is_no_file(self):
        with open(switches.path(self.data), "w") as handle:
            handle.write("[" * 100000 + "]" * 100000)
        self.assertTrue(switches.on("memory", self.data))
        self.assertEqual(switches.saved(self.data), {})

    def test_restore_puts_one_back(self):
        switches.save("git", False, self.data)
        switches.save("pings", True, self.data)
        switches.restore("pings", None, self.data)  # it wasn't there before
        switches.restore("git", True, self.data)
        self.assertEqual(switches.saved(self.data), {"git": True})

    def test_listing(self):
        rows = switches.listing(self.data, {"routines": (True, "--routines")})
        self.assertEqual([r["name"] for r in rows], list(switches.NAMES))
        routines = next(r for r in rows if r["name"] == "routines")
        self.assertEqual((routines["on"], routines["set_by"]), (True, "--routines"))
        self.assertIsNone(next(r for r in rows if r["name"] == "git")["set_by"])
        for r in rows:  # words people read: no long dashes
            self.assertNotIn("—", r["label"] + r["about"])


class HookTest(unittest.TestCase):
    """The hooks honour each agent switch at every event."""

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.data = os.path.join(self.base, "data")
        self.lantern = os.path.join(self.base, "lantern")
        os.makedirs(os.path.join(self.data, "howtos"))
        os.makedirs(self.lantern)
        self.company = {"company": "X", "floors": [{"id": "lantern", "label": "Lantern", "folder": self.lantern}],
                        "feeds": ["feeds/claude-code.json"]}
        self.write_company()
        self.env = dict(os.environ, ARNHEIM_DATA=self.data, ARNHEIM_CONTROL_WAIT="1")

    def write_company(self):
        with open(os.path.join(self.data, "company.json"), "w", encoding="utf-8") as handle:
            json.dump(self.company, handle)

    def off(self, name):
        switches.save(name, False, self.data)

    def hook(self, session="one", **event):
        event.update(session_id=session, cwd=self.lantern)
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def told(self, session):
        out = self.hook(session=session, hook_event_name="SessionStart", source="startup")
        return (out or {}).get("hookSpecificOutput", {}).get("additionalContext", "")

    def finish_some_work(self, session="one"):
        self.hook(session=session, hook_event_name="UserPromptSubmit", prompt="Sort the bookmarks by name")
        self.hook(session=session, hook_event_name="PostToolUse", tool_name="Edit", tool_input={"file_path": os.path.join(self.lantern, "sort.js")})
        self.hook(session=session, hook_event_name="Stop", last_assistant_message="Sorted.")

    def test_hand_overs(self):
        self.finish_some_work()
        self.assertIn("Sort the bookmarks by name", self.told("two"))
        self.off("handovers")
        self.assertNotIn("Sort the bookmarks by name", self.told("three"))
        os.remove(os.path.join(self.data, "control", "handover.json"))
        self.finish_some_work("four")  # off: nothing is noted either
        self.assertFalse(os.path.exists(os.path.join(self.data, "control", "handover.json")))

    def test_memory_and_how_tos(self):
        with open(os.path.join(self.data, "memory.json"), "w") as handle:
            json.dump({"memory": [{"text": "We never push on a Friday", "at": time.time()}]}, handle)
        with open(os.path.join(self.data, "howtos", "ship.md"), "w") as handle:
            handle.write("# Shipping\n")
        self.company["howtos"] = [{"file": "howtos/ship.md", "title": "How we ship"}]
        self.write_company()
        words = self.told("one")
        self.assertIn("We never push on a Friday", words)
        self.assertIn("How we ship", words)
        self.off("memory")
        words = self.told("two")
        self.assertNotIn("We never push on a Friday", words)
        self.assertIn("How we ship", words)
        self.off("howtos")
        self.assertNotIn("How we ship", self.told("three"))

    def test_always_allow(self):
        standing.add(self.data, "Lantern", "Bash", "npm test")
        asked = dict(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "npm test"})
        self.hook(hook_event_name="UserPromptSubmit", prompt="Run the tests")
        out = self.hook(**asked)
        self.assertEqual(out["hookSpecificOutput"]["decision"], {"behavior": "allow"})
        self.off("always")
        self.assertIsNone(self.hook(**asked))  # it asks, as it would without Arnheim
        self.assertEqual(len(standing.rows(self.data)), 1)  # and the list is kept

    def test_budget_brake(self):
        self.company["budget"] = 10
        self.write_company()
        os.makedirs(os.path.join(self.data, "feeds"), exist_ok=True)
        talk = {"id": "cc-one", "project": "Lantern", "title": "Busy", "working": True, "at": time.time(),
                "spent": {"day": budget.local_day(), "tokens": 500}}
        for session, brake in (("one", True), ("one", False)):
            with open(os.path.join(self.data, "feeds", "claude-code.json"), "w") as handle:
                json.dump({"conversations": [talk], "tasks": []}, handle)
            if not brake:
                self.off("budget")
            out = self.hook(session=session, hook_event_name="PostToolUse", tool_name="Read", tool_input={"file_path": "x"})
            if brake:
                self.assertFalse(out["continue"])
                self.assertIn("budget", out["stopReason"])
            else:
                self.assertIsNone(out)

    def test_two_agents_one_file(self):
        edit = dict(hook_event_name="PostToolUse", tool_name="Edit", tool_input={"file_path": os.path.join(self.lantern, "a.js")})
        self.hook(session="one", hook_event_name="UserPromptSubmit", prompt="Change a")
        self.hook(session="one", **edit)
        self.hook(session="two", hook_event_name="UserPromptSubmit", prompt="Change a too")
        out = self.hook(session="two", **edit)
        self.assertIn("also changed", out["hookSpecificOutput"]["additionalContext"])
        self.off("clash")
        self.hook(session="three", hook_event_name="UserPromptSubmit", prompt="And again")
        self.assertIsNone(self.hook(session="three", **edit))


class InProcessTest(unittest.TestCase):
    """Proof, the review line and restore points: what the hook would start, stopped before it starts."""

    def setUp(self):
        import claude_code
        self.cc = claude_code
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)
        patcher = mock.patch.object(claude_code, "DATA", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_checks_off_starts_none(self):
        talk = {"id": "cc-one", "project": "Lantern", "changed": time.time()}
        with mock.patch.object(self.cc, "read_feed", return_value={"conversations": [talk]}), \
                mock.patch.object(self.cc.control, "check_for", return_value="The tests"), \
                mock.patch.object(self.cc.control, "prove_later") as later:
            self.cc.prove({"session_id": "one"})
            self.assertEqual(later.call_count, 1)
            switches.save("checks", False, self.data)
            self.cc.prove({"session_id": "one"})
            self.assertEqual(later.call_count, 1)

    def test_review_off_holds_nothing(self):
        switches.save("review", False, self.data)
        with mock.patch.dict(sys.modules, {"review": None}):  # importing it would fail: it is never reached
            self.assertIsNone(self.cc.review({"session_id": "one"}))

    def test_restore_points_off(self):
        event = {"session_id": "one", "cwd": self.data, "tool_name": "Edit", "tool_input": {"file_path": "a"}}
        with mock.patch.object(self.cc, "project_for", return_value="Lantern"), \
                mock.patch.object(self.cc, "read_feed", return_value={"conversations": []}), \
                mock.patch.object(self.cc, "edit_talk"), \
                mock.patch.object(self.cc.restore, "take", return_value="taken") as take:
            self.assertEqual(self.cc.restore_point(event), "taken")
            switches.save("restore", False, self.data)
            self.assertIsNone(self.cc.restore_point(event))
            self.assertEqual(take.call_count, 1)


def started(**given):
    words = {"control": False, "no_control": False, "brain": False, "routines": False, "pings": False, "no_git": False}
    return argparse.Namespace(**{**words, **given})


class Brainless:
    def __init__(self, control=None):
        self.control = control
        self.closed = False

    def close(self):
        self.closed = True


class BoardBase(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)
        patcher = mock.patch.object(serve, "SAVED", os.path.join(self.data, "serve.json"))
        patcher.start()
        self.addCleanup(patcher.stop)

    def board(self, away=None, make_brain=Brainless, **given):
        board = serve.Switchboard(started(**given), away, make_brain)
        board.server = argparse.Namespace(control=None, brain=None)
        return board

    def real_control(self):
        real = serve.Control
        return mock.patch.object(serve, "Control", side_effect=lambda: real(data=self.data))


class BoardTest(BoardBase):
    """serve.py's Switchboard: what a start word holds, and a change that works at once."""

    def test_start_words_hold_a_switch(self):
        board = self.board(routines=True, no_git=True, no_control=True)
        self.assertTrue(board.on("routines"))
        self.assertFalse(board.on("git"))
        for name, on in (("routines", False), ("git", True), ("control", True)):
            with self.assertRaises(serve.Refused):
                board.switch(name, on)
        self.assertEqual(switches.saved(self.data), {})  # nothing kept
        away = self.board(away="--lan")
        with self.assertRaises(serve.Refused) as why:
            away.switch("control", True)
        self.assertIn("only on this computer", str(why.exception))

    def test_control_works_at_once_and_keeps_its_agents(self):
        board = self.board()
        with self.real_control() as made:
            board.switch("control", True)
            first = board.server.control
            self.assertIsNotNone(first)
            board.switch("control", False)
            self.assertIsNone(board.server.control)
            board.switch("control", True)
            self.assertIs(board.server.control, first)  # the same one: agents started from the building stay known
            self.assertEqual(made.call_count, 1)
        self.assertTrue(switches.on("control", self.data))

    def test_the_brain_starts_and_stops(self):
        board = self.board()
        board.switch("brain", True)
        brain = board.server.brain
        self.assertIsInstance(brain, Brainless)
        board.switch("brain", False)
        self.assertIsNone(board.server.brain)
        self.assertTrue(brain.closed)

        def cannot(_control):
            raise ValueError("there is no claude command here")
        board = self.board(make_brain=cannot)
        with self.assertRaises(serve.Refused) as why:
            board.switch("brain", True)
        self.assertIn("no claude command", str(why.exception))
        self.assertFalse(switches.on("brain", self.data))  # it couldn't start: not kept as on
        switches.save("brain", True, self.data)  # kept on from before, and it can't start here now
        with self.assertRaises(serve.Refused):
            board.switch("brain", True)
        self.assertIs(switches.saved(self.data)["brain"], False)  # pressing it once leaves it off, not stuck on

    def test_the_assistant_passes_on_only_while_control_is_on(self):
        board = self.board()
        with self.real_control():
            board.switch("brain", True)
            board.switch("control", True)
            self.assertIs(board.server.brain.control, board.server.control)
            board.switch("control", False)
            self.assertIsNone(board.server.brain.control)


class MoreBoardTest(BoardBase):
    def test_a_brain_kept_on_that_can_t_start_shows_off(self):
        switches.save("brain", True, self.data)
        board = self.board()
        rows = {r["name"]: r["on"] for r in board.listing()}
        self.assertFalse(rows["brain"])  # nothing running: pressing it tries again
        board.server.brain = Brainless()
        self.assertTrue({r["name"]: r["on"] for r in board.listing()}["brain"])

    def test_control_that_can_t_start_changes_nothing(self):
        board = self.board()

        def broken():
            raise ValueError("ARNHEIM_CLAUDE isn't a command")
        with mock.patch.object(serve, "Control", side_effect=broken):
            with self.assertRaises(serve.Refused):
                board.switch("control", True)
        self.assertIsNone(board.server.control)
        self.assertNotIn("control", switches.saved(self.data))  # put back as it was: not there

    def test_a_switch_that_can_t_be_kept_changes_nothing(self):
        board = self.board()
        with mock.patch.object(serve.switches, "save", side_effect=OSError("read-only")):  # serve.py's own copy
            with self.assertRaises(serve.Refused) as why:
                board.switch("brain", True)
        self.assertIn("couldn't be kept", str(why.exception))
        self.assertIsNone(board.server.brain)  # never started

    def test_control_stays_on_while_its_agents_work(self):
        board = self.board()
        with self.real_control():
            board.switch("control", True)
        control = board.server.control
        control.runs["run-1"] = {"key": "run-1"}
        with mock.patch.object(control, "alive", return_value=True):
            with self.assertRaises(serve.Refused) as why:
                board.switch("control", False)
        self.assertIn("still at work", str(why.exception))
        self.assertIs(board.server.control, control)
        control.box.watch()  # the page was in use a moment ago
        with mock.patch.object(control, "alive", return_value=False):
            board.switch("control", False)
        self.assertIsNone(board.server.control)
        self.assertFalse(control.box.watched())  # a waiting request goes back to the agent at once

    def test_the_old_question_takes_the_same_path(self):
        on, chose = serve.control_wanted(argparse.Namespace(control=False, no_control=False), "--lan")
        self.assertEqual((on, chose), (False, False))
        switches.save("control", True, self.data)
        self.assertEqual(serve.control_wanted(argparse.Namespace(control=False, no_control=False), None), (True, True))


class RouteTest(unittest.TestCase):
    """/switches: only this computer's own page, with its token and its Origin."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)
        patcher = mock.patch.object(serve, "SAVED", os.path.join(self.data, "serve.json"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = serve.Server(("127.0.0.1", 0), serve.Handler)
        self.port = self.server.server_address[1]
        self.server.board = serve.Switchboard(started(pings=True), None, Brainless)
        self.server.board.server = self.server
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def ask(self, method="GET", headers=None, body=None, path="/switches"):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", f"127.0.0.1:{self.port}")
            for name, value in (headers or {}).items():
                conn.putheader(name, value)
            raw = json.dumps(body).encode() if body is not None else b""
            if method == "POST":
                conn.putheader("Content-Length", str(len(raw)))
            conn.endheaders(raw if method == "POST" else None)
            reply = conn.getresponse()
            raw = reply.read()
            try:
                return reply.status, json.loads(raw or b"{}")
            except ValueError:  # a refusal before the route: the server's own error page
                return reply.status, {}
        finally:
            conn.close()

    def post(self, body, token=None, origin=True, headers=None):
        given = {"Content-Type": "application/json"}
        if origin:
            given["Origin"] = f"http://127.0.0.1:{self.port}"
        given.update(headers or {})  # another page's Origin, say, in place of its own
        if token:
            given["X-Arnheim-Switches"] = token
        return self.ask("POST", given, body)

    def test_read_then_change(self):
        status, got = self.ask()
        self.assertEqual(status, 200)
        token = got["token"]
        pings = next(s for s in got["switches"] if s["name"] == "pings")
        self.assertEqual((pings["on"], pings["set_by"]), (True, "--pings"))
        self.assertEqual(self.post({"name": "handovers", "on": False}, token)[0], 200)
        self.assertFalse(switches.on("handovers", self.data))
        status, got = self.post({"name": "pings", "on": False}, token)  # held by --pings for this start
        self.assertEqual(status, 409)
        self.assertIn("--pings", got["error"])
        self.assertEqual(self.post({"name": "nothing", "on": False}, token)[0], 400)
        self.assertEqual(self.post({"name": "git", "on": "off"}, token)[0], 400)
        self.assertEqual(self.post(["git"], token)[0], 400)

    def test_never_without_the_token_or_from_another_page(self):
        token = self.ask()[1]["token"]
        self.assertEqual(self.post({"name": "control", "on": True})[0], 403)  # no token
        self.assertEqual(self.post({"name": "control", "on": True}, "guess")[0], 403)
        self.assertEqual(self.post({"name": "control", "on": True}, token, origin=False)[0], 403)  # not its own page
        self.assertEqual(self.post({"name": "control", "on": True}, token, headers={"Origin": "http://example.com"})[0], 403)
        self.assertFalse(switches.on("control", self.data))
        self.assertIsNone(self.server.control)

    def test_never_from_a_phone_or_through_a_proxy(self):
        token = self.ask()[1]["token"]
        self.assertEqual(self.ask(headers={"X-Forwarded-For": "100.64.0.2"})[0], 403)
        self.assertEqual(self.post({"name": "control", "on": True}, token, headers={"X-Forwarded-For": "100.64.0.2"})[0], 403)
        self.assertFalse(switches.on("control", self.data))

    def test_never_by_another_name_even_with_lan(self):
        self.server.lan = True  # with --lan, the page answers to .local names and addresses too
        for host in (f"evil.local:{self.port}", f"192.168.1.5:{self.port}"):
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            try:
                conn.putrequest("GET", "/switches", skip_host=True, skip_accept_encoding=True)
                conn.putheader("Host", host)
                conn.endheaders()
                reply = conn.getresponse()
                self.assertEqual(reply.status, 403, host)
                self.assertNotIn(self.server.board.token.encode(), reply.read())
            finally:
                conn.close()
        self.assertEqual(self.ask()[0], 200)  # its own name, still

    def test_control_switched_on_answers_at_once(self):
        self.assertEqual(self.ask(path="/control/token")[1], {"on": False})
        token = self.ask()[1]["token"]
        real = serve.Control
        with mock.patch.object(serve, "Control", side_effect=lambda: real(data=self.data)):
            self.assertEqual(self.post({"name": "control", "on": True}, token)[0], 200)
        status, got = self.ask(path="/control/token")
        self.assertEqual((status, got["on"]), (200, True))
        self.post({"name": "control", "on": False}, token)
        self.assertEqual(self.ask(path="/control/token")[1], {"on": False})


if __name__ == "__main__":
    unittest.main()
