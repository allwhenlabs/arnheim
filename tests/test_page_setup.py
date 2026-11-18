"""Connect my agents from the page (serve.py's /setup/, which runs connect/setup.py in the server): what it finds, what
it takes, what it writes, Undo, and who may ask. Every test runs in a made-up home folder, with Claude Code's and
Codex's settings in temporary folders, so your own are never read or touched, and nothing ever starts at login.
Standard library only.

Run from the repository's folder: python3 -m unittest discover tests
"""
import argparse
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "connect"))

import serve  # noqa: E402
import switches  # noqa: E402

TOOL = serve.connect_setup  # connect/setup.py as serve.py runs it


def started(**given):
    words = dict(control=False, no_control=False, brain=False, routines=False, pings=False, no_git=False)
    words.update(given)
    return argparse.Namespace(**words)


class Brainless:
    def __init__(self, control=None):
        self.control = control

    def close(self):
        pass


class PageSetupBase(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = os.path.join(self.base, "home")
        self.data = os.path.join(self.base, "data")
        self.claude = os.path.join(self.home, ".claude")
        self.codex = os.path.join(self.home, ".codex")
        os.makedirs(self.claude)
        os.makedirs(self.data)
        env = {"HOME": self.home, "USERPROFILE": self.home, "CLAUDE_CONFIG_DIR": self.claude, "CODEX_HOME": self.codex}
        for patcher in (mock.patch.dict(os.environ, env),
                        mock.patch.object(serve, "SAVED", os.path.join(self.data, "serve.json")),
                        mock.patch.object(TOOL, "DATA", TOOL.DATA),  # put back after each test
                        mock.patch.object(TOOL, "claude_code_here", return_value=True),
                        mock.patch.object(TOOL, "codex_here", return_value=False),
                        mock.patch.object(TOOL, "codex_version", return_value=None),
                        mock.patch.object(TOOL, "start_always", side_effect=AssertionError("never starts at login from here"))):
            patcher.start()
            self.addCleanup(patcher.stop)
        real = serve.Control
        patcher = mock.patch.object(serve, "Control", side_effect=lambda: real(data=self.data))
        patcher.start()
        self.addCleanup(patcher.stop)
        # projects, and recent conversations in them, as Claude Code keeps them
        self.alpha = self.project("code", "alpha")
        self.beta = self.project("code", "beta-app", git=False)
        self.talk(self.alpha, 100)
        self.talk(self.beta, 200)

    def project(self, *parts, git=True):
        folder = os.path.join(self.home, *parts)
        os.makedirs(os.path.join(folder, ".git") if git else folder, exist_ok=True)
        return folder

    def talk(self, cwd, ago):
        folder = os.path.join(self.claude, "projects", f"p{len(os.listdir(os.path.join(self.claude, 'projects'))) if os.path.isdir(os.path.join(self.claude, 'projects')) else 0}")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, "a.jsonl")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "user", "cwd": cwd, "message": {"content": "never read"}}) + "\n")
        at = time.time() - ago
        os.utime(path, (at, at))

    def settings(self):
        with open(os.path.join(self.claude, "settings.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def company(self):
        with open(os.path.join(self.data, "company.json"), encoding="utf-8") as handle:
            return json.load(handle)


class PlanTest(PageSetupBase):
    """What the flow shows, and what Connect takes, without the web in between."""

    def test_the_settings_are_the_made_up_home_s(self):
        self.assertTrue(TOOL.settings_path().startswith(self.base))
        self.assertTrue(TOOL.codex_hooks_path().startswith(self.base))

    def test_the_plan_lists_what_setup_finds(self):
        plan = serve.setup_plan(self.data)
        self.assertEqual([p["folder"] for p in plan["projects"]], ["~/code/alpha", "~/code/beta-app"])  # newest first, ~ for home
        self.assertEqual([p["label"] for p in plan["projects"]], ["Alpha", "Beta app"])
        self.assertEqual(plan["projects"][0]["when"], "today")
        self.assertTrue(plan["claude"])
        self.assertEqual(plan["codex"], {"here": False, "version": None, "hooks": False, "notes": []})
        self.assertIsNone(plan["control"])
        self.assertFalse(plan["company"])
        self.assertEqual(TOOL.DATA, self.data)  # setup works in this server's data folder

    def test_an_old_codex_is_said_as_setup_says_it(self):
        with mock.patch.object(TOOL, "codex_here", return_value=True), mock.patch.object(TOOL, "codex_version", return_value=(0, 110)):
            codex = serve.setup_plan(self.data)["codex"]
        self.assertEqual((codex["here"], codex["version"], codex["hooks"]), (True, "0.110", False))
        self.assertIn("older than 0.124, which brought hooks, so none will be added for it", codex["notes"][0])
        with mock.patch.object(TOOL, "codex_here", return_value=True), mock.patch.object(TOOL, "codex_version", return_value=(0, 130)):
            codex = serve.setup_plan(self.data)["codex"]
        self.assertEqual((codex["version"], codex["hooks"]), ("0.130", True))

    def test_connect_does_what_setup_does(self):
        board = serve.Switchboard(started(), None, Brainless)
        board.server = argparse.Namespace(control=None, brain=None)
        other = self.project("work", "gamma", git=False)  # not in the list: typed
        code, out = serve.setup_connect({"folders": ["~/code/alpha"], "typed": " ~/work/gamma ", "control": True}, self.data, board)
        self.assertEqual(code, 200, out)
        company = self.company()
        self.assertEqual([f["label"] for f in company["floors"]], ["Alpha", "Gamma"])
        self.assertEqual([f["folder"] for f in company["floors"]], ["~/code/alpha", "~/work/gamma"])
        self.assertTrue(os.path.isdir(other))
        hooks = self.settings()["hooks"]
        self.assertEqual(sorted(hooks), sorted(TOOL.EVENTS))
        self.assertTrue(hooks["Stop"][0]["hooks"][0]["command"].endswith("connect/claude_code.py"))
        self.assertIn("usage.py", self.settings()["statusLine"]["command"])
        self.assertEqual(switches.saved(self.data), {"control": True})
        self.assertIsNotNone(board.server.control)  # switched on at once, through the Switchboard
        lines = "\n".join(out["lines"])
        self.assertIn("Wrote", lines)
        self.assertIn("Added to", lines)
        self.assertIn("Conversations you start in these folders from now on show in the building.", lines)
        for never in ("This will:", "Go ahead", "Next:", "Start Arnheim now", "log in"):
            self.assertNotIn(never, lines)
        self.assertEqual(out["control"], True)

    def test_no_to_control_is_kept_and_control_stays_off(self):
        board = serve.Switchboard(started(), None, Brainless)
        board.server = argparse.Namespace(control=None, brain=None)
        code, out = serve.setup_connect({"folders": ["~/code/beta-app"], "control": False}, self.data, board)
        self.assertEqual(code, 200, out)
        self.assertEqual(switches.saved(self.data), {"control": False})
        self.assertIsNone(board.server.control)
        code, out = serve.setup_connect({"folders": ["~/code/alpha"], "control": True}, self.data, board)  # asked again on the page: the new answer
        self.assertEqual(code, 200, out)
        self.assertEqual(switches.saved(self.data), {"control": True})
        self.assertEqual([f["id"] for f in self.company()["floors"]], ["beta-app", "alpha"])

    def test_a_start_word_that_holds_control_is_said(self):
        board = serve.Switchboard(started(no_control=True), None, Brainless)
        board.server = argparse.Namespace(control=None, brain=None)
        code, out = serve.setup_connect({"folders": ["~/code/alpha"], "control": True}, self.data, board)
        self.assertEqual(code, 200, out)
        self.assertIn("--no-control", out["note"])
        self.assertIsNone(board.server.control)

    def test_only_found_or_typed_folders(self):
        bad = [
            ({"folders": ["~/code/elsewhere"], "control": True}, "isn't one of the projects found"),
            ({"folders": [self.home], "control": True}, "isn't one of the projects found"),
            ({"folders": [], "typed": "code/alpha", "control": True}, "whole path"),  # relative: never from serve.py's folder
            ({"folders": [], "typed": "~/nowhere", "control": True}, "There is no folder at ~/nowhere"),
            ({"folders": [], "typed": "~", "control": True}, "holds everything"),
            ({"folders": [], "typed": "/", "control": True}, "holds everything"),
            ({"folders": [], "typed": "~/code/alpha\0x", "control": True}, "whole path"),
            ({"folders": [], "typed": "", "control": True}, "Choose at least one project"),
            ({"folders": ["~/code/alpha"], "control": "yes"}, "doesn't make sense"),
            ({"folders": "~/code/alpha", "control": True}, "doesn't make sense"),
            ({"folders": [1], "control": True}, "doesn't make sense"),
            ({"folders": ["~/code/alpha"] * 51, "control": True}, "doesn't make sense"),
        ]
        for given, said in bad:
            code, out = serve.setup_connect(given, self.data, None)
            self.assertEqual(code, 400, given)
            self.assertIn(said, out["error"], given)
        self.assertFalse(os.path.exists(os.path.join(self.data, "company.json")))
        self.assertFalse(os.path.exists(os.path.join(self.claude, "settings.json")))

    def test_a_refusal_is_said_and_nothing_changes(self):
        with open(os.path.join(self.claude, "settings.json"), "w") as handle:
            handle.write("{ not json")
        code, out = serve.setup_connect({"folders": ["~/code/alpha"], "control": True}, self.data, None)
        self.assertEqual(code, 409)
        self.assertIn("isn't valid JSON", out["error"])
        self.assertFalse(os.path.exists(os.path.join(self.data, "company.json")))

    def test_codex_hooks_go_in_too(self):
        with mock.patch.object(TOOL, "codex_here", return_value=True), mock.patch.object(TOOL, "codex_version", return_value=(0, 130)):
            code, out = serve.setup_connect({"folders": ["~/code/alpha"], "control": True}, self.data, None)
        self.assertEqual(code, 200, out)
        with open(os.path.join(self.codex, "hooks.json"), encoding="utf-8") as handle:
            self.assertEqual(sorted(json.load(handle)["hooks"]), sorted(TOOL.CODEX_EVENTS))
        self.assertIn("type /hooks", "\n".join(out["lines"]))

    def test_undo_takes_it_all_out_and_puts_the_building_aside(self):
        mine = {"model": "opus", "statusLine": {"type": "command", "command": "my-line"},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}
        with open(os.path.join(self.claude, "settings.json"), "w") as handle:
            json.dump(mine, handle)
        self.assertEqual(serve.setup_connect({"folders": ["~/code/alpha"], "control": True}, self.data, None)[0], 200)
        code, out = serve.setup_undo(self.data)
        self.assertEqual(code, 200, out)
        got = self.settings()
        self.assertEqual(got["hooks"], mine["hooks"])  # yours stay
        self.assertEqual(got["statusLine"], mine["statusLine"])  # your own status line back
        self.assertEqual(got["model"], "opus")
        self.assertFalse(os.path.exists(os.path.join(self.data, "company.json")))
        aside = [f for f in os.listdir(os.path.join(self.data, "backups")) if f.startswith("company.undone-")]
        self.assertEqual(len(aside), 1)
        with open(os.path.join(self.data, "backups", aside[0]), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["floors"][0]["id"], "alpha")
        lines = "\n".join(out["lines"])
        self.assertIn("Took Arnheim's hooks out", lines)
        self.assertIn("made-up company again", lines)
        self.assertNotIn("Delete the data folder", lines)
        code, out = serve.setup_undo(self.data)  # twice: nothing more to do, and nothing breaks
        self.assertEqual(code, 200, out)
        self.assertIn("none of Arnheim's hooks", "\n".join(out["lines"]))


class RouteTest(PageSetupBase):
    """/setup/: only this computer's own page, with its token and its Origin."""

    def setUp(self):
        super().setUp()
        self.server = serve.Server(("127.0.0.1", 0), serve.Handler)
        self.port = self.server.server_address[1]
        self.server.board = serve.Switchboard(started(), None, Brainless)
        self.server.board.server = self.server
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def ask(self, path, method="GET", body=None, host=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host or f"127.0.0.1:{self.port}")
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
            except ValueError:
                return reply.status, {}
        finally:
            conn.close()

    def post(self, name, body, token=None, origin=True, headers=None):
        given = {"Content-Type": "application/json"}
        if origin:
            given["Origin"] = f"http://127.0.0.1:{self.port}"
        if token:
            given["X-Arnheim-Switches"] = token
        given.update(headers or {})
        return self.ask(f"/setup/{name}", "POST", body, headers=given)

    def test_here_plan_connect_and_undo(self):
        status, here = self.ask("/setup/here")
        self.assertEqual(status, 200)
        self.assertEqual((here["claude"], here["company"]), (True, False))
        self.assertEqual(here["token"], self.server.board.token)
        status, plan = self.ask("/setup/plan")
        self.assertEqual([p["folder"] for p in plan["projects"]], ["~/code/alpha", "~/code/beta-app"])
        status, out = self.post("connect", {"folders": ["~/code/alpha", "~/code/beta-app"], "control": True}, here["token"])
        self.assertEqual(status, 200, out)
        self.assertEqual(len(self.company()["floors"]), 2)
        self.assertIsNotNone(self.server.control)  # control works at once
        self.assertEqual(self.ask("/control/token")[1]["on"], True)
        status, out = self.post("undo", {}, here["token"])
        self.assertEqual(status, 200, out)
        self.assertFalse(os.path.exists(os.path.join(self.data, "company.json")))
        self.assertNotIn("hooks", self.settings())

    def test_without_claude_code_the_page_says_where_to_get_it(self):
        with mock.patch.object(TOOL, "claude_code_here", return_value=False):
            status, here = self.ask("/setup/here")
        self.assertEqual((status, here["claude"]), (200, False))
        self.assertEqual(here["install"], "https://claude.com/claude-code")

    def test_never_without_the_token_or_from_another_page(self):
        token = self.ask("/setup/here")[1]["token"]
        body = {"folders": ["~/code/alpha"], "control": True}
        self.assertEqual(self.post("connect", body)[0], 403)  # no token
        self.assertEqual(self.post("connect", body, "guess")[0], 403)
        self.assertEqual(self.post("connect", body, token, origin=False)[0], 403)  # not its own page
        self.assertEqual(self.post("connect", body, token, headers={"Origin": "http://example.com"})[0], 403)
        self.assertEqual(self.post("undo", {}, "guess")[0], 403)
        self.assertEqual(self.post("connect", ["x"], token)[0], 400)
        self.assertEqual(self.post("nothing", {}, token)[0], 404)
        self.assertFalse(os.path.exists(os.path.join(self.data, "company.json")))
        self.assertFalse(os.path.exists(os.path.join(self.claude, "settings.json")))

    def test_never_from_a_phone_a_proxy_or_another_name(self):
        token = self.ask("/setup/here")[1]["token"]
        self.assertEqual(self.ask("/setup/here", headers={"X-Forwarded-For": "100.64.0.2"})[0], 403)
        self.assertEqual(self.post("connect", {"folders": ["~/code/alpha"], "control": True}, token, headers={"X-Forwarded-For": "100.64.0.2"})[0], 403)
        self.server.lan = True  # with --lan, the page answers to .local names and addresses too, but this never does
        for host in (f"evil.local:{self.port}", f"192.168.1.5:{self.port}"):
            status, said = self.ask("/setup/plan", host=host)
            self.assertEqual(status, 403, host)
            self.assertNotIn("token", said)
        self.assertFalse(os.path.exists(os.path.join(self.data, "company.json")))


class CommandLineTest(unittest.TestCase):
    """The terminal's setup says what it will do and asks, as before: the page's way leaves that out."""

    def test_the_plan_is_said_in_the_terminal_only(self):
        base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, True)
        home, data = os.path.join(base, "home"), os.path.join(base, "data")
        project = os.path.join(home, "code", "alpha")
        os.makedirs(os.path.join(project, ".git"))
        os.makedirs(os.path.join(home, ".claude"))
        env = {"HOME": home, "USERPROFILE": home, "CLAUDE_CONFIG_DIR": os.path.join(home, ".claude"), "CODEX_HOME": os.path.join(home, ".codex")}
        heard = []
        with mock.patch.dict(os.environ, env), mock.patch.object(TOOL, "DATA", data), \
                mock.patch.object(TOOL, "codex_here", return_value=False), mock.patch.object(TOOL, "codex_version", return_value=None):
            args = argparse.Namespace(folder=[project], yes=True, name=None, no_hooks=True, undo=False)
            self.assertEqual(TOOL.setup(args, say=heard.append), 0)
        said = "\n".join(heard)
        self.assertIn("This will:", said)
        self.assertIn("Next: python3 serve.py", said)


if __name__ == "__main__":
    unittest.main()
