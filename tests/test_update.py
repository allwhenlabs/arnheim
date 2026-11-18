"""A newer Arnheim (serve.py's look_for_newer, /update, the "Look for a newer Arnheim" switch): a git checkout of
Arnheim asks GitHub, at the start and once a day, whether main has changes it hasn't, sending only its commit; a
notice shows only when it is behind; Update now runs the same `git pull --ff-only` every time, and says why when it
can't. git and GitHub are stand-ins here: nothing is fetched and nothing is pulled. Standard library only.

Run from the repository's folder: python3 -m unittest discover tests
"""
import argparse
import http.client
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "connect"))

import serve  # noqa: E402
import switches  # noqa: E402

SHA = "0123456789abcdef0123456789abcdef01234567"


class Git:
    """Stands in for subprocess.run with git: answers by the words given, and records each command."""

    def __init__(self, top=None, remote="https://github.com/allwhenlabs/arnheim.git", head=SHA, pull=(0, "Updating a..b\nFast-forward\n", "")):
        self.top, self.remote, self.head, self.pull = top or serve.ROOT, remote, head, pull
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append((command, kwargs))
        words = command[1:]
        if words == ["rev-parse", "--show-toplevel"]:
            return subprocess.CompletedProcess(command, 0, self.top + "\n", "")
        if words == ["remote", "-v"]:
            return subprocess.CompletedProcess(command, 0, f"origin\t{self.remote} (fetch)\norigin\t{self.remote} (push)\n", "")
        if words == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(command, 0, self.head + "\n", "")
        if words == ["pull", "--ff-only"]:
            code, out, err = self.pull
            return subprocess.CompletedProcess(command, code, out, err)
        return subprocess.CompletedProcess(command, 1, "", "unknown")


class GitHub:
    """Stands in for urllib's urlopen: records each request, and answers with the JSON given, or raises."""

    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.requests = answer, error, []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if self.error:
            raise self.error
        return io.BytesIO(json.dumps(self.answer).encode())


class NewerTest(unittest.TestCase):
    def test_behind_is_the_only_notice(self):
        github = GitHub({"status": "behind", "behind_by": 3, "ahead_by": 0})
        self.assertEqual(serve.newer_arnheim(run=Git(), opener=github), 3)
        request = github.requests[0]
        self.assertEqual(request.full_url, f"https://api.github.com/repos/allwhenlabs/arnheim/compare/main...{SHA}?per_page=1")
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(dict(request.header_items()), {"User-agent": "Arnheim", "Accept": "application/vnd.github+json"})  # nothing personal
        for answer in ({"status": "identical", "behind_by": 0}, {"status": "ahead", "ahead_by": 2, "behind_by": 0},
                       {"status": "diverged", "ahead_by": 1, "behind_by": 4}, {"status": "behind", "behind_by": 0},
                       {"status": "behind", "behind_by": "3"}, {"status": "behind", "behind_by": True}, ["behind"], {}):
            self.assertIsNone(serve.newer_arnheim(run=Git(), opener=GitHub(answer)), answer)

    def test_quiet_when_github_doesnt_know_it_or_cant_be_reached(self):
        missing = urllib.error.HTTPError("https://api.github.com", 404, "Not Found", {}, io.BytesIO(b"{}"))
        self.assertIsNone(serve.newer_arnheim(run=Git(), opener=GitHub(error=missing)))  # commits of its own
        self.assertIsNone(serve.newer_arnheim(run=Git(), opener=GitHub(error=urllib.error.URLError("no network"))))
        self.assertIsNone(serve.newer_arnheim(run=Git(), opener=GitHub(error=OSError("down"))))
        self.assertIsNone(serve.newer_arnheim(run=Git(), opener=GitHub(error=http.client.IncompleteRead(b""))))

        class Garbled:
            def __call__(self, request, timeout=None):
                return io.BytesIO(b"<html>not json")
        self.assertIsNone(serve.newer_arnheim(run=Git(), opener=Garbled()))

    def test_only_a_checkout_of_arnheim_itself_asks(self):
        for git in (Git(remote="https://github.com/someone/arnheim-fork.git"), Git(remote="https://example.com/allwhenlabs/arnheim.git"),
                    Git(top=os.path.dirname(serve.ROOT)), Git(head="not-a-sha")):
            github = GitHub({"status": "behind", "behind_by": 3})
            self.assertIsNone(serve.newer_arnheim(run=git, opener=github))
            self.assertEqual(github.requests, [])  # GitHub never asked
        for remote in ("git@github.com:allwhenlabs/arnheim.git", "https://github.com/allwhenlabs/arnheim", "ssh://git@github.com/allwhenlabs/arnheim.git"):
            self.assertEqual(serve.newer_arnheim(run=Git(remote=remote), opener=GitHub({"status": "behind", "behind_by": 1})), 1, remote)

        def no_git(command, **_):
            raise FileNotFoundError("git")
        self.assertIsNone(serve.newer_arnheim(run=no_git, opener=GitHub({"status": "behind", "behind_by": 1})))

    def test_a_download_never_runs_git(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder, True)
        git, github = Git(top=folder), GitHub({"status": "behind", "behind_by": 1})
        with mock.patch.object(serve, "ROOT", folder):  # Arnheim's files, with no .git beside them
            self.assertIsNone(serve.newer_arnheim(run=git, opener=github))
        self.assertEqual((git.commands, github.requests), ([], []))

    def test_git_runs_with_fixed_words_in_this_folder_and_never_prompts(self):
        git = Git()
        serve.newer_arnheim(run=git, opener=GitHub({"status": "identical"}))
        for command, kwargs in git.commands:
            self.assertEqual(command[0], "git")
            self.assertEqual(kwargs["cwd"], serve.ROOT)
            self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")


class Board:
    def __init__(self, on=True):
        self.is_on = on

    def on(self, name):
        assert name == "updates"
        return self.is_on


class DailyTest(unittest.TestCase):
    def test_once_a_day_while_the_switch_is_on(self):
        server, board, asked = argparse.Namespace(update=None), Board(), []

        def ask():
            asked.append(1)
            return 5
        last = serve.check_newer(server, board, 0, ask, now=1000)
        self.assertEqual((server.update, len(asked)), ({"behind": 5}, 1))
        last = serve.check_newer(server, board, last, ask, now=1000 + 3600)
        self.assertEqual(len(asked), 1)  # not again within the day
        last = serve.check_newer(server, board, last, ask, now=1000 + 86400)
        self.assertEqual(len(asked), 2)
        board.is_on = False
        last = serve.check_newer(server, board, last, ask, now=1000 + 86400 + 60)
        self.assertIsNone(server.update)  # switched off: the notice goes, and GitHub isn't asked
        self.assertEqual((len(asked), last), (2, 0))
        board.is_on = True
        serve.check_newer(server, board, last, lambda: None, now=1000 + 86400 + 120)  # on again: asked at once
        self.assertIsNone(server.update)  # nothing newer: no notice

    def test_the_switch(self):
        data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, data, True)
        row = next(r for r in switches.listing(data) if r["name"] == "updates")
        self.assertEqual((row["group"], row["on"], row["label"]), ("running", True, "Look for a newer Arnheim"))
        switches.save("updates", False, data)
        self.assertFalse(switches.on("updates", data))


class UpdateNowTest(unittest.TestCase):
    def server(self, control=None):
        return argparse.Namespace(control=control, update={"behind": 2}, brain=None)

    def test_the_same_fixed_command_every_time(self):
        git = Git()
        done, words = serve.update_now(self.server(), run=git)
        self.assertTrue(done)
        self.assertIn("starting again", words)
        command, kwargs = git.commands[-1]
        self.assertEqual(command, ["git", "pull", "--ff-only"])
        self.assertEqual(kwargs["cwd"], serve.ROOT)
        self.assertEqual(kwargs["env"]["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(serve.update_now(self.server(), run=Git(pull=(0, "Already up to date.\n", "")))[1], serve.UP_TO_DATE)

    def test_why_it_couldnt_in_words(self):
        local = (1, "", "error: Your local changes to the following files would be overwritten by merge:\n\tsrc/demo.js\n"
                        "Please commit your changes or stash them before you merge.\nAborting\n")
        done, words = serve.update_now(self.server(), run=Git(pull=local))
        self.assertFalse(done)
        self.assertIn("changes of its own", words)
        done, words = serve.update_now(self.server(), run=Git(pull=(128, "", "fatal: Not possible to fast-forward, aborting.\n")))
        self.assertIn("commits of its own", words)
        done, words = serve.update_now(self.server(), run=Git(pull=(1, "", "fatal: unable to access 'https://github.com/': Could not resolve host\n")))
        self.assertIn("Could not resolve host", words)

        def no_git(command, **_):
            raise FileNotFoundError(2, "No such file or directory")
        done, words = serve.update_now(self.server(), run=no_git)
        self.assertFalse(done)
        self.assertIn("git pull", words)

    def test_not_while_agents_started_here_work(self):
        class Busy:
            runs = {"run-1": {"key": "run-1"}}

            def alive(self, run):
                return True
        git = Git()
        done, words = serve.update_now(self.server(Busy()), run=git)
        self.assertFalse(done)
        self.assertIn("still at work", words)
        self.assertEqual(git.commands, [])  # nothing run


def started():
    return argparse.Namespace(control=False, no_control=False, brain=False, routines=False, pings=False, no_git=False)


class RouteTest(unittest.TestCase):
    """/update: only this computer's own page, and Update now only with its token."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)
        patcher = mock.patch.object(serve, "SAVED", os.path.join(self.data, "serve.json"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = serve.Server(("127.0.0.1", 0), serve.Handler)
        self.port = self.server.server_address[1]
        self.server.board = serve.Switchboard(started(), None)
        self.server.board.server = self.server
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def ask(self, method="GET", token=None, host=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest(method, "/update", skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host or f"127.0.0.1:{self.port}")
            if method == "POST":
                conn.putheader("Origin", f"http://127.0.0.1:{self.port}")
                conn.putheader("Content-Length", "2")
            if token:
                conn.putheader("X-Arnheim-Switches", token)
            for name, value in (headers or {}).items():
                conn.putheader(name, value)
            conn.endheaders(b"{}" if method == "POST" else None)
            reply = conn.getresponse()
            raw = reply.read()
            try:
                return reply.status, json.loads(raw or b"{}")
            except ValueError:
                return reply.status, {}
        finally:
            conn.close()

    def test_the_notice_and_update_now(self):
        status, got = self.ask()
        self.assertEqual(status, 200)
        self.assertNotIn("behind", got)
        self.server.update = {"behind": 3}
        status, got = self.ask()
        self.assertEqual(got["behind"], 3)
        token = got["token"]
        with mock.patch.object(serve, "update_now", return_value=(False, "Arnheim's folder has changes of its own")) as pulled:
            self.assertEqual(self.ask("POST")[0], 403)  # no token: never pulled
            self.assertEqual(self.ask("POST", "guess")[0], 403)
            pulled.assert_not_called()
            status, got = self.ask("POST", token)
            self.assertEqual(status, 409)
            self.assertIn("changes of its own", got["error"])
        self.assertEqual(self.server.update, {"behind": 3})  # still behind
        with mock.patch.object(serve, "update_now", return_value=(True, serve.UP_TO_DATE)), mock.patch.object(serve, "restart_self") as again:
            status, got = self.ask("POST", token)
            self.assertEqual((status, got.get("restarting")), (200, None))
            again.assert_not_called()  # nothing new: no start again
        self.server.update = {"behind": 3}
        with mock.patch.object(serve, "update_now", return_value=(True, "Updated.")), mock.patch.object(serve, "restart_self") as again:
            status, got = self.ask("POST", token)
            self.assertEqual((status, got["restarting"]), (200, True))
            for _ in range(100):
                if again.called:
                    break
                threading.Event().wait(0.02)
            again.assert_called_once_with(self.server)
        self.assertIsNone(self.server.update)

    def test_only_this_computer_s_own_page(self):
        self.server.update = {"behind": 3}
        self.assertEqual(self.ask(headers={"X-Forwarded-For": "100.64.0.2"})[0], 403)
        self.server.lan = True
        for host in (f"evil.local:{self.port}", f"192.168.1.5:{self.port}"):
            status, got = self.ask(host=host)
            self.assertEqual(status, 403, host)
            self.assertNotIn("token", got)
        with mock.patch.object(serve, "update_now") as pulled:
            token = self.ask()[1]["token"]
            self.assertEqual(self.ask("POST", token, host=f"192.168.1.5:{self.port}")[0], 403)
            pulled.assert_not_called()


if __name__ == "__main__":
    unittest.main()
