"""connect/setup.py, the one step from the made-up company to your own: it finds your projects from
your recent conversations, writes data/company.json, and adds Arnheim's hooks to Claude Code's
settings, keeping a copy of each file first. Every test runs in a made-up home folder, so your own
settings are never read or touched. Standard library only.

Run from the repository's folder: python3 -m unittest discover tests
"""
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
sys.path.insert(0, ROOT)

import setup  # noqa: E402  (connect/setup.py)
import serve  # noqa: E402

SETUP = os.path.join(ROOT, "connect", "setup.py")


class Home:
    """A made-up home folder with projects, Claude Code and Codex conversations, and a copy of Arnheim."""

    def __init__(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.home = os.path.join(self.base, "home")
        self.data = os.path.join(self.base, "data")
        os.makedirs(self.home)
        self.claude = os.path.join(self.home, ".claude")

    def path(self, *parts):
        return os.path.join(self.home, *parts)

    def project(self, *parts, git=True):
        folder = self.path(*parts)
        os.makedirs(os.path.join(folder, ".git") if git else folder, exist_ok=True)
        return folder

    def talk(self, cwd, ago, codex=False):
        """A conversation that ran in cwd, `ago` seconds back: its first line names no folder, as Claude Code's don't."""
        n = len(os.listdir(os.path.join(self.claude, "projects"))) if os.path.isdir(os.path.join(self.claude, "projects")) else 0
        if codex:
            folder = self.path(".codex", "sessions", "2026", "11", "14")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"rollout-{n}-{ago}.jsonl")
            rows = [{"type": "session_meta", "payload": {"id": "x", "cwd": cwd}}]
        else:
            folder = os.path.join(self.claude, "projects", f"p{n}")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, "a.jsonl")
            rows = [{"type": "queue-operation"}, {"type": "user", "cwd": cwd, "message": {"content": "never read"}}]
        with open(path, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row) + "\n")
        at = time.time() - ago
        os.utime(path, (at, at))

    def env(self, **extra):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "ARNHEIM_DATA")}
        env.update(HOME=self.home, USERPROFILE=self.home, ARNHEIM_DATA=self.data)
        env.update(extra)
        return env

    def run(self, *args, answers=None, script=SETUP, **env):
        done = subprocess.run([sys.executable, script, *args], input=answers or "", capture_output=True, text=True,
                              env=self.env(**env), timeout=60)
        return done.returncode, done.stdout + done.stderr

    def settings(self):
        with open(os.path.join(self.claude, "settings.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def company(self):
        with open(os.path.join(self.data, "company.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def close(self):
        shutil.rmtree(self.base, ignore_errors=True)


class FindTest(unittest.TestCase):
    def setUp(self):
        self.h = Home()
        self.addCleanup(self.h.close)

    def found(self):
        old = os.environ.copy()
        os.environ.update(self.h.env())
        for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME"):
            os.environ.pop(name, None)
        try:
            return [os.path.relpath(p["folder"], self.h.home) for p in setup.find_projects()]
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_projects_newest_first_and_folded(self):
        h = self.h
        alpha = h.project("code", "alpha")
        h.talk(alpha, 500)
        h.talk(h.project("code", "alpha", "src", git=False), 100)  # inside a repository: alpha's floor, now
        worktree = h.project("code", "alpha", ".claude", "worktrees", "w", git=False)
        with open(os.path.join(worktree, ".git"), "w") as handle:
            handle.write(f"gitdir: {os.path.join(alpha, '.git', 'worktrees', 'w')}\n")
        h.talk(worktree, 50)  # a git worktree is its main repository's
        h.talk(h.project("code", "beta", git=False), 300)  # a plain folder is a project too
        h.talk(h.project("My Projects", "gamma one"), 200)  # spaces in the name
        h.talk(h.project("code", "delta"), 400, codex=True)  # Codex's conversations count
        h.talk(h.path("code"), 60)  # a folder that holds projects isn't one: they are listed themselves
        h.talk(h.path("code", "gone"), 10)  # no longer there
        h.talk(h.home, 20)  # the home folder is never a project
        h.talk(h.project(".config", "tool"), 30)  # nor anything hidden in it
        h.talk(h.project("Library", "Application Support", "App", "x"), 40)
        self.assertEqual(self.found(), [os.path.join("code", "alpha"), os.path.join("My Projects", "gamma one"),
                                        os.path.join("code", "beta"), os.path.join("code", "delta")])

    def test_nothing_found_without_claude_code(self):
        self.assertEqual(self.found(), [])

    def test_a_huge_first_line_is_cut_short(self):
        h = self.h
        folder = os.path.join(h.claude, "projects", "big")
        os.makedirs(folder)
        with open(os.path.join(folder, "a.jsonl"), "w") as handle:
            handle.write('{"type": "image", "data": "' + "x" * (3 << 20) + '"}\n')
            handle.write(json.dumps({"cwd": h.project("code", "late")}) + "\n")
        self.assertEqual(self.found(), [])  # it stops at a megabyte, never reading a whole transcript


class SetupTest(unittest.TestCase):
    def setUp(self):
        self.h = Home()
        self.addCleanup(self.h.close)
        h = self.h
        self.alpha = h.project("code", "alpha")
        self.beta = h.project("code", "beta-app", git=False)
        h.talk(self.alpha, 100)
        h.talk(self.beta, 200)
        os.makedirs(h.claude, exist_ok=True)

    def files(self):
        out = []
        for path in (os.path.join(self.h.claude, "settings.json"), os.path.join(self.h.data, "company.json")):
            with open(path, encoding="utf-8") as handle:
                out.append(handle.read())
        return out

    def backups(self):
        return sorted(f for f in os.listdir(self.h.claude) if ".before-arnheim-" in f)

    def test_one_command_makes_the_building_and_connects_claude_code(self):
        code, out = self.h.run("--yes")
        self.assertEqual(code, 0, out)
        company = self.h.company()
        self.assertEqual([f["label"] for f in company["floors"]], ["Alpha", "Beta app"])
        self.assertEqual([f["id"] for f in company["floors"]], ["alpha", "beta-app"])
        self.assertEqual(company["floors"][0]["folder"], "~/code/alpha")
        self.assertEqual({r["id"] for r in company["rooms"]}, {"work", "conversations", "code"})
        self.assertIn("feeds/claude-code.json", company["feeds"])
        self.assertEqual(company["receptionist"]["name"], "Iris")
        self.assertIn("websites", [r["id"] for r in company["lobby"]["rooms"]])  # where the receptionist sits
        self.assertNotIn("sample", company)
        hooks = self.h.settings()["hooks"]
        self.assertEqual(sorted(hooks), sorted(setup.EVENTS))
        command = hooks["Stop"][0]["hooks"][0]["command"]
        self.assertTrue(command.endswith("connect/claude_code.py"), command)
        self.assertEqual(hooks["PermissionRequest"][0]["hooks"][0]["timeout"], 150)
        self.assertIn("python3 connect/setup.py --undo", out)

    def test_running_twice_changes_nothing(self):
        self.h.run("--yes")
        before = self.files()
        code, out = self.h.run("--yes")
        self.assertEqual(code, 0, out)
        self.assertIn("nothing changed", out)
        self.assertEqual(before, self.files())
        self.assertEqual(self.backups(), [])  # the first run had no settings to copy, the second changed nothing
        self.assertFalse(os.path.exists(os.path.join(self.h.data, "backups")))

    def test_other_settings_and_hooks_stay_and_undo_takes_out_only_arnheims(self):
        mine = {"model": "opus", "env": {"A": "1"}, "permissions": {"allow": ["Bash(npm test)"]},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}],
                          "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}]}}
        with open(os.path.join(self.h.claude, "settings.json"), "w") as handle:
            json.dump(mine, handle)
        code, out = self.h.run("--yes")
        self.assertEqual(code, 0, out)
        got = self.h.settings()
        self.assertEqual({k: got[k] for k in ("model", "env", "permissions")}, {k: mine[k] for k in ("model", "env", "permissions")})
        self.assertEqual(got["hooks"]["Stop"][0], mine["hooks"]["Stop"][0])  # beside yours, not instead
        self.assertEqual(len(got["hooks"]["Stop"]), 2)
        self.assertEqual(got["hooks"]["PreToolUse"], mine["hooks"]["PreToolUse"])
        self.assertEqual(len(self.backups()), 1)
        code, out = self.h.run("--undo")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.h.settings(), mine)
        self.assertIn("Took Arnheim's hooks out", out)
        code, out = self.h.run("--undo")
        self.assertIn("none of Arnheim's hooks", out)

    def test_a_broken_settings_file_is_refused_and_nothing_changes(self):
        path = os.path.join(self.h.claude, "settings.json")
        with open(path, "w") as handle:
            handle.write('{\n  "model": "opus",\n  hooks: {}\n}\n')
        code, out = self.h.run("--yes")
        self.assertEqual(code, 1)
        self.assertIn("isn't valid JSON (line 3", out)
        self.assertIn("Nothing was changed", out)
        self.assertFalse(os.path.exists(os.path.join(self.h.data, "company.json")))  # checked before anything is written
        with open(path, "w") as handle:
            json.dump({"hooks": {"Stop": {"not": "a list"}}}, handle)
        code, out = self.h.run("--yes")
        self.assertEqual(code, 1)
        self.assertIn("should be an object of lists", out)

    def test_another_copy_of_arnheim_is_never_doubled(self):
        other = {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 /elsewhere/arnheim/connect/claude_code.py"}]}]}}
        with open(os.path.join(self.h.claude, "settings.json"), "w") as handle:
            json.dump(other, handle)
        code, out = self.h.run("--yes")
        self.assertEqual(code, 1)
        self.assertIn("/elsewhere/arnheim/connect/claude_code.py", out)
        self.assertEqual(self.h.settings(), other)
        code, out = self.h.run("--undo")  # undo takes out any copy's, so the next run can connect this one
        self.assertEqual(self.h.settings(), {})
        self.assertEqual(self.h.run("--yes")[0], 0)

    def test_an_existing_company_only_gains_floors(self):
        os.makedirs(self.h.data)
        mine = {"company": "Mine", "rooms": [{"id": "goals", "label": "Goals"}],
                "floors": [{"id": "alpha", "label": "Old alpha", "folder": "~/code/alpha"}]}
        with open(os.path.join(self.h.data, "company.json"), "w") as handle:
            json.dump(mine, handle)
        code, out = self.h.run("--yes")
        self.assertEqual(code, 0, out)
        company = self.h.company()
        self.assertEqual(company["company"], "Mine")
        self.assertEqual(company["floors"][0], mine["floors"][0])
        self.assertEqual([f["id"] for f in company["floors"]], ["alpha", "beta-app"])
        self.assertEqual([r["id"] for r in company["floors"][1]["rooms"]], ["work", "conversations", "code"])  # its rooms are its own
        self.assertIn("already had a floor", out)
        copies = os.listdir(os.path.join(self.h.data, "backups"))
        self.assertEqual(len(copies), 1)
        with open(os.path.join(self.h.data, "backups", copies[0])) as handle:
            self.assertEqual(json.load(handle), mine)

    def test_the_made_up_company_is_never_built_on(self):
        os.makedirs(self.h.data)
        shutil.copy(os.path.join(ROOT, "sample", "company.json"), os.path.join(self.h.data, "company.json"))
        code, out = self.h.run("--yes")
        self.assertEqual(code, 1)
        self.assertIn("still the made-up company", out)

    def test_without_claude_code_it_still_makes_the_building(self):
        shutil.rmtree(self.h.claude)
        empty = os.path.join(self.h.base, "bin")
        os.makedirs(empty)
        code, out = self.h.run("--yes", "--folder", self.alpha, PATH=empty)
        self.assertEqual(code, 0, out)
        self.assertEqual([f["id"] for f in self.h.company()["floors"]], ["alpha"])
        self.assertFalse(os.path.exists(self.h.claude))
        self.assertIn("Claude Code doesn't seem to be on this computer", out)

    def test_no_projects_says_how_to_name_one(self):
        code, out = self.h.run("--yes", HOME=os.path.join(self.h.base, "nobody"))
        self.assertEqual(code, 1)
        self.assertIn("--folder", out)

    def test_it_asks_first_and_takes_your_choice(self):
        code, out = self.h.run(answers="n\n")  # "n" stops it, before anything changes
        self.assertEqual(code, 1)
        self.assertIn("Stopped before changing anything", out)
        self.assertFalse(os.path.exists(os.path.join(self.h.data, "company.json")))
        code, out = self.h.run(answers="nowhere\n")  # not a number, a yes or a no: a folder, and there's none
        self.assertIn("There is no folder at nowhere", out)
        code, out = self.h.run(answers="2\nThe Works\nn\nn\n")
        self.assertEqual(code, 1)
        self.assertIn("Stopped before changing anything", out)
        self.assertFalse(os.path.exists(os.path.join(self.h.data, "company.json")))
        self.assertFalse(os.path.exists(os.path.join(self.h.claude, "settings.json")))
        code, out = self.h.run(answers="2\nThe Works\nn\n\n")  # no to answering from the building, then go ahead
        self.assertEqual(code, 0, out)
        self.assertEqual(self.h.company()["company"], "The Works")
        self.assertEqual([f["id"] for f in self.h.company()["floors"]], ["beta-app"])
        with open(os.path.join(self.h.data, "serve.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"control": False})
        self.assertIn("Next: python3 serve.py", out)  # the end of the answers is a no to starting it now

    def test_yes_takes_them_all_and_control_is_asked_once(self):
        code, out = self.h.run(answers="y\n\n\n\n")
        self.assertEqual(code, 0, out)
        self.assertEqual([f["id"] for f in self.h.company()["floors"]], ["alpha", "beta-app"])
        with open(os.path.join(self.h.data, "serve.json"), encoding="utf-8") as handle:
            self.assertEqual(json.load(handle), {"control": True})  # Enter: yes
        code, out = self.h.run("--yes")
        self.assertNotIn("Answer your agents from the building", out)
        self.assertIn("nothing changed", out)

    def test_a_linked_settings_file_stays_a_link(self):
        real = os.path.join(self.h.base, "dotfiles", "settings.json")
        os.makedirs(os.path.dirname(real))
        with open(real, "w") as handle:
            json.dump({"model": "opus"}, handle)
        os.symlink(real, os.path.join(self.h.claude, "settings.json"))
        self.assertEqual(self.h.run("--yes")[0], 0)
        self.assertTrue(os.path.islink(os.path.join(self.h.claude, "settings.json")))
        with open(real) as handle:
            self.assertIn("hooks", json.load(handle))

    def write_settings(self, value, indent=2):
        with open(os.path.join(self.h.claude, "settings.json"), "w") as handle:
            json.dump(value, handle, indent=indent)

    def test_a_file_that_cant_be_written_changes_nothing(self):
        self.write_settings({"model": "opus"})
        os.chmod(self.h.claude, 0o555)  # Claude Code's folder can't be written
        self.addCleanup(os.chmod, self.h.claude, 0o755)
        code, out = self.h.run("--yes")
        self.assertEqual(code, 1, out)
        self.assertIn("can't be written", out)
        self.assertIn("Nothing was changed", out)
        self.assertNotIn("Traceback", out)
        self.assertFalse(os.path.exists(os.path.join(self.h.data, "company.json")))  # not half done
        self.assertEqual(self.h.settings(), {"model": "opus"})
        self.assertEqual(self.backups(), [])

    def test_this_copys_partial_hooks_are_made_whole(self):
        mine = f"python3 {os.path.join(ROOT, 'connect', 'claude_code.py')}"
        self.write_settings({"hooks": {
            "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": mine}, {"type": "command", "command": "echo hi"}]}],
            "Stop": [{"hooks": [{"type": "command", "command": mine + " --quiet"}]}],  # something after the name: still Arnheim's
            "SessionEnd": [{"hooks": [{"type": "command", "command": "python3 connect/claude_code.py"}]}]}})  # works from one folder only
        code, out = subprocess.run([sys.executable, SETUP, "--yes"], capture_output=True, text=True, env=self.h.env(),
                                   cwd=self.h.base, timeout=60).returncode, None
        self.assertEqual(code, 0)
        hooks = self.h.settings()["hooks"]
        self.assertEqual(hooks["PostToolUse"][0], {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]})
        self.assertEqual(len(hooks["PostToolUse"]), 2)  # one for every tool now, and yours as it was
        self.assertNotIn("matcher", hooks["PostToolUse"][1])
        self.assertEqual([h["command"] for g in hooks["Stop"] for h in g["hooks"]], [mine + " --quiet"])  # never doubled
        self.assertEqual(len(hooks["SessionEnd"]), 1)
        self.assertTrue(os.path.isabs(setup.connector_of(hooks["SessionEnd"][0]["hooks"][0]["command"])))
        self.h.run("--undo")
        self.assertEqual(self.h.settings(), {"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}]}})

    def test_undo_leaves_the_rest_exactly_and_keeps_the_files_look(self):
        ours = {"type": "command", "command": "python3 /x/arnheim/connect/claude_code.py"}
        self.write_settings({"model": "opus", "hooks": {"Stop": [], "Notification": [{"hooks": []}, {"hooks": [ours]}],
                                                        "SessionStart": [{"hooks": [ours]}]}}, indent=4)
        self.assertEqual(self.h.run("--undo")[0], 0)
        # an empty list or group of yours stays; a list that held only Arnheim's goes
        self.assertEqual(self.h.settings(), {"model": "opus", "hooks": {"Stop": [], "Notification": [{"hooks": []}]}})
        with open(os.path.join(self.h.claude, "settings.json")) as handle:
            self.assertTrue(handle.read().startswith('{\n    "model"'))

    def test_feeds_alone_are_said_as_feeds(self):
        os.makedirs(self.h.data)
        with open(os.path.join(self.h.data, "company.json"), "w") as handle:
            json.dump({"company": "Mine", "rooms": setup.ROOMS, "floors": [{"id": "a", "label": "A", "folders": ["~/code/alpha", "~/code/beta-app"]}]}, handle)
        code, out = self.h.run("--yes", "--no-hooks")
        self.assertEqual(code, 0, out)
        self.assertIn('add the connectors\' files to "feeds"', out)
        self.assertNotIn("add 0 floors", out)
        self.assertEqual(self.h.company()["feeds"], setup.FEEDS)

    def test_a_project_connected_by_hand_is_pointed_out(self):
        os.makedirs(os.path.join(self.alpha, ".claude"))
        with open(os.path.join(self.alpha, ".claude", "settings.json"), "w") as handle:
            json.dump({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 /x/arnheim/connect/claude_code.py"}]}]}}, handle)
        code, out = self.h.run("--yes")
        self.assertEqual(code, 0, out)
        self.assertIn("~/code/alpha/.claude/settings.json runs Arnheim's hooks too", out)

    def test_the_home_folder_is_never_one_project(self):
        for given in ("~", self.h.home, "/"):
            code, out = self.h.run("--yes", "--folder", given)
            self.assertEqual(code, 1, given)
            self.assertIn("holds everything", out)
        self.assertFalse(os.path.exists(os.path.join(self.h.data, "company.json")))

    def test_the_hook_runs_from_a_folder_with_spaces(self):
        # a copy of Arnheim's connectors in a folder with a space, connected, then handed a moment as Claude Code would
        arnheim = os.path.join(self.h.base, "My Arnheim")
        shutil.copytree(os.path.join(ROOT, "connect"), os.path.join(arnheim, "connect"),
                        ignore=shutil.ignore_patterns("__pycache__"))
        data = os.path.join(arnheim, "data")
        code, out = self.h.run("--yes", script=os.path.join(arnheim, "connect", "setup.py"), ARNHEIM_DATA=data)
        self.assertEqual(code, 0, out)
        command = self.h.settings()["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        self.assertIn("'", command)  # quoted for the shell
        moment = json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": "try", "cwd": self.alpha, "prompt": "Hello"})
        done = subprocess.run(["/bin/sh", "-c", command], input=moment, capture_output=True, text=True,
                              env=self.h.env(ARNHEIM_DATA=data), timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        with open(os.path.join(data, "feeds", "claude-code.json")) as handle:
            seats = json.load(handle)["conversations"]
        self.assertEqual([(c["title"], c["project"]) for c in seats], [("Hello", "Alpha")])


class CommandTest(unittest.TestCase):
    def test_quoting_on_each_system(self):
        self.assertEqual(setup.hook_command("/usr/bin/python3", "/opt/arnheim/connect/claude_code.py", windows=False),
                         "/usr/bin/python3 /opt/arnheim/connect/claude_code.py")
        self.assertEqual(setup.hook_command("/Users/a b/py", "/Users/a b/arnheim/connect/claude_code.py", windows=False),
                         "'/Users/a b/py' '/Users/a b/arnheim/connect/claude_code.py'")
        self.assertEqual(setup.hook_command(r"C:\Program Files\Python312\python.exe", r"C:\Users\Me\My Arnheim\connect\claude_code.py", windows=True),
                         '"C:/Program Files/Python312/python.exe" "C:/Users/Me/My Arnheim/connect/claude_code.py"')

    def test_arnheims_hooks_are_known_in_any_form(self):
        for command in ("python3 /opt/arnheim/connect/claude_code.py",
                        "'/Users/a b/py' '/Users/a b/arnheim/connect/claude_code.py'",
                        '"C:/Program Files/Python312/python.exe" "C:/Users/Me/arnheim/connect/claude_code.py"',
                        r'python C:\Users\Me\arnheim\connect\claude_code.py',
                        "python3 /opt/arnheim/connect/claude_code.py --quiet",
                        "/opt/homebrew/bin/python3.14 connect/claude_code.py"):
            self.assertTrue(setup.connector_of(command), command)
        for command in ("echo connect/claude_code.py done", "echo connect/claude_code.py", "python3 other/claude_code.py",
                        "cat /opt/arnheim/connect/claude_code.py", None, 7):
            self.assertIsNone(setup.connector_of(command), command)

    def test_undo_keeps_a_group_with_other_hooks(self):
        settings = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": r'python C:\Users\Me\arnheim\connect\claude_code.py'},
            {"type": "command", "command": "echo hi"}]}], "Stop": [{"hooks": []}]}}
        out, taken = setup.take_out(settings)
        self.assertEqual(out, {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}],
                                         "Stop": [{"hooks": []}]}})
        self.assertEqual(len(taken), 1)

    def test_a_failed_second_file_puts_the_first_back(self):
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        first, second = os.path.join(base, "company.json"), os.path.join(base, "settings.json")
        for path in (first, second):
            with open(path, "w") as handle:
                json.dump({"was": path}, handle)
        copies = os.path.join(base, "backups")
        calls = []
        real = os.replace

        def replace(a, b):
            calls.append(b)
            if len(calls) == 2:
                raise PermissionError(13, "Permission denied", b)
            return real(a, b)

        setup.os.replace = replace
        try:
            with self.assertRaises(setup.Refused) as said:
                setup.write_all([(first, {"new": 1}), (second, {"new": 2})], {first: copies, second: copies})
        finally:
            setup.os.replace = real
        self.assertIn("Nothing was changed", str(said.exception))
        for path in (first, second):
            with open(path) as handle:
                self.assertEqual(json.load(handle), {"was": path})  # the first, already replaced, is put back
        self.assertEqual(sorted(os.listdir(base)), ["company.json", "settings.json"])  # no copies, parts or empty folder

    def test_labels_and_ids(self):
        taken = set()
        self.assertEqual([setup.label_of(f) for f in ("/x/my-app", "/x/EchoKit", "/x/snake_case.v2", "/x/__")],
                         ["My app", "EchoKit", "Snake case v2", "__"])
        self.assertEqual([setup.id_of(label, taken) for label in ("My app", "My app", "Café", "日本")],
                         ["my-app", "my-app-2", "caf", "project"])


class ProjectsTest(unittest.TestCase):
    def test_git_never_takes_the_index_lock(self):
        import projects  # connect/projects.py
        seen = {}

        class Done:
            returncode, stdout = 0, ""

        def run(args, **kw):
            seen.update(kw.get("env") or {})
            return Done()

        real, projects.subprocess.run = projects.subprocess.run, run
        try:
            projects.run(["git", "status"], ROOT)
        finally:
            projects.subprocess.run = real
        self.assertEqual(seen.get("GIT_OPTIONAL_LOCKS"), "0")


class ServeTest(unittest.TestCase):
    def test_git_is_watched_once_floors_have_folders(self):
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        root, serve.ROOT = serve.ROOT, base
        self.addCleanup(setattr, serve, "ROOT", root)
        self.assertFalse(serve.floors_have_folders())
        os.makedirs(os.path.join(base, "data"))
        path = os.path.join(base, "data", "company.json")
        for company, want in (({"floors": [{"id": "a"}]}, False), ({"floors": [{"id": "a", "folder": "~/a"}]}, True),
                              ({"floors": [{"id": "a", "folders": ["~/a"]}]}, True), ("not json", False)):
            with open(path, "w") as handle:
                handle.write(company if isinstance(company, str) else json.dumps(company))
            self.assertEqual(serve.floors_have_folders(), want, company)


if __name__ == "__main__":
    unittest.main()
