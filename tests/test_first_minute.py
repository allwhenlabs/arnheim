"""The first minute with Arnheim: setup's choice to answer your agents from the building, remembered for each
start (data/serve.json), and Arnheim kept running at login (connect/always.py, serve.py --always). The login
item is written in a made-up home folder and the commands that would start it are only recorded, so nothing
on this computer starts or changes. Standard library only.

Run from the repository's folder: python3 -m unittest discover tests
"""
import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connect"))
sys.path.insert(0, ROOT)

import always  # noqa: E402  (connect/always.py)
import serve  # noqa: E402


class Ran:
    """Stands in for subprocess.run: records each command, and fails the ones named."""

    def __init__(self, fail=()):
        self.commands, self.fail = [], fail

    def __call__(self, command, **_):
        self.commands.append(command)
        failed = any(word in command for word in self.fail)
        return subprocess.CompletedProcess(command, 1 if failed else 0, "", "it said no" if failed else "")


class AlwaysTest(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, True)
        patcher = mock.patch.dict(os.environ, {"HOME": self.home, "USERPROFILE": self.home})
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.command = ["/usr/bin/python3", "/Users/x/arnheim/serve.py", "--brain"]

    def test_on_a_mac_a_launch_agent_for_you_alone(self):
        run = Ran()
        path = always.turn_on(self.command, "/Users/x/arnheim", "/opt/bin:/usr/bin", run=run, platform="darwin")
        self.assertEqual(path, os.path.join(self.home, "Library", "LaunchAgents", "local.arnheim.serve.plist"))
        with open(path, "rb") as handle:
            item = plistlib.load(handle)
        self.assertEqual(item["ProgramArguments"], self.command)
        self.assertEqual(item["EnvironmentVariables"]["PATH"], "/opt/bin:/usr/bin")  # git, gh and claude found as in a terminal
        self.assertEqual((item["RunAtLoad"], item["KeepAlive"]), (True, {"SuccessfulExit": False}))
        self.assertEqual(item["StandardOutPath"], os.path.join(self.home, "Library", "Logs", "arnheim.log"))
        self.assertEqual([c[:2] for c in run.commands], [["launchctl", "bootout"], ["launchctl", "bootstrap"]])
        self.assertTrue(always.installed("darwin"))

        run = Ran()
        self.assertEqual(always.turn_off(run=run, platform="darwin"), path)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(run.commands[0][:2], ["launchctl", "bootout"])
        self.assertIsNone(always.turn_off(run=Ran(), platform="darwin"))  # nothing there: nothing to do

    def test_nothing_running_yet_is_fine_but_a_refusal_is_said(self):
        always.turn_on(self.command, "/x", run=Ran(fail=("bootout",)), platform="darwin")  # the first time, nothing to stop
        with self.assertRaises(RuntimeError) as said:
            always.turn_on(self.command, "/x", run=Ran(fail=("bootstrap",)), platform="darwin")
        self.assertIn("it said no", str(said.exception))

    def test_on_linux_a_user_service(self):
        run = Ran()
        path = always.turn_on(["/usr/bin/python3", "/home/x/my code/serve.py"], "/home/x/my code", "/usr/bin", run=run, platform="linux")
        self.assertEqual(path, os.path.join(self.home, ".config", "systemd", "user", "arnheim.service"))
        with open(path, encoding="utf-8") as handle:
            unit = handle.read()
        self.assertIn('ExecStart=/usr/bin/python3 "/home/x/my code/serve.py"\n', unit)
        self.assertIn("Restart=on-failure", unit)
        self.assertIn(["systemctl", "--user", "enable", "--now", "arnheim.service"], run.commands)

    def test_windows_says_so(self):
        with self.assertRaises(always.Unsupported):
            always.turn_on(self.command, "/x", run=Ran(), platform="win32")
        self.assertIsNone(always.path_of("win32"))


class SavedControlTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.saved = os.path.join(self.base, "serve.json")
        patcher = mock.patch.object(serve, "SAVED", self.saved)
        patcher.start()
        self.addCleanup(patcher.stop)

    def wanted(self, away=None, **flags):
        args = argparse.Namespace(control=flags.get("control", False), no_control=flags.get("no_control", False))
        return serve.control_wanted(args, away)

    def test_your_choice_in_setup_holds_for_each_start(self):
        self.assertEqual(self.wanted(), (False, False))  # nothing chosen: off, as before
        self.assertEqual(self.wanted(control=True), (True, False))
        with open(self.saved, "w") as handle:
            json.dump({"control": True}, handle)
        self.assertEqual(self.wanted(), (True, True))
        self.assertEqual(self.wanted(no_control=True), (False, False))  # off this once
        self.assertEqual(self.wanted(away="--lan"), (False, True))  # never on the network
        with open(self.saved, "w") as handle:
            json.dump({"control": False}, handle)
        self.assertEqual(self.wanted(), (False, False))
        with open(self.saved, "w") as handle:
            handle.write("{not json")
        self.assertEqual(self.wanted(), (False, False))


if __name__ == "__main__":
    unittest.main()
