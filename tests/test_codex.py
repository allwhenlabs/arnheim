"""OpenAI's Codex CLI as a full member of the building, through its hooks (connect/codex.py): a conversation
at work, its edits and plan, a permission it asks for answered from the building, you stopping it, what it
spends, and connect/setup.py adding the hooks to Codex's hooks.json. The events are shaped as Codex's own
docs give them. Each test runs in a made-up home folder and company, so nothing of yours is read or touched.

Run from the repository's folder: python3 -m unittest discover tests
"""
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

import budget  # noqa: E402
import control  # noqa: E402

CODEX = os.path.join(ROOT, "connect", "codex.py")
SETUP = os.path.join(ROOT, "connect", "setup.py")
SESSION = "019a2b3c-4d5e-7f80-9123-456789abcdef"
KEY = "cc-019a2b3c4d5e"
PATCH = ("*** Begin Patch\n*** Update File: src/bookmark.js\n@@\n-old\n+new\n*** Add File: src/sort.js\n+export {}\n"
         "*** Update File: src/old-name.js\n*** Move to: src/new-name.js\n*** End Patch\n")


class CodexHooksTest(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.data = os.path.join(self.base, "data")
        self.lantern = os.path.join(self.base, "code", "lantern")
        self.codex_home = os.path.join(self.base, "codex")
        os.makedirs(self.data)
        os.makedirs(os.path.join(self.lantern, "src"))
        os.makedirs(self.codex_home)
        with open(os.path.join(self.data, "company.json"), "w", encoding="utf-8") as handle:
            json.dump({"company": "Example Studio", "rooms": [{"id": "work", "label": "Work"}],
                       "floors": [{"id": "lantern", "label": "Lantern", "folder": self.lantern}],
                       "feeds": ["feeds/claude-code.json"]}, handle)
        self.env = dict(os.environ, ARNHEIM_DATA=self.data, CODEX_HOME=self.codex_home)
        self.box = control.Box(self.data)

    def hook(self, **event):
        """Runs connect/codex.py as Codex runs a hook. What it printed, as JSON, or None."""
        event.setdefault("session_id", SESSION)
        event.setdefault("cwd", self.lantern)
        event.setdefault("transcript_path", None)
        event.setdefault("model", "gpt-5-codex")
        done = subprocess.run([sys.executable, CODEX], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def feed(self):
        with open(os.path.join(self.data, "feeds", "claude-code.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def talk(self):
        return next(c for c in self.feed()["conversations"] if c["id"] == KEY)

    def keep_watching(self):
        """Someone is using the building: its page says so every few seconds."""
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                self.box.watch()
                stop.wait(1)
        threading.Thread(target=watch, daemon=True).start()
        self.addCleanup(stop.set)

    def ask_in_the_background(self, **event):
        event = {"hook_event_name": "PermissionRequest", "session_id": SESSION, "cwd": self.lantern, "turn_id": "t2",
                 "tool_name": "Bash", "tool_input": {"command": "npm test", "description": "Run the tests"}, **event}
        proc = subprocess.Popen([sys.executable, CODEX], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=self.env)
        proc.stdin.write(json.dumps(event))
        proc.stdin.close()
        end = time.time() + 20
        while time.time() < end:
            asks = self.box.asks()
            if asks:
                return proc, asks[0]
            time.sleep(0.1)
        proc.kill()
        self.fail("the request never reached the building")

    def decision(self, proc):
        out = proc.stdout.read()
        proc.stdout.close()
        proc.wait(timeout=30)
        return json.loads(out)["hookSpecificOutput"]["decision"] if out.strip() else None

    def test_a_codex_conversation_from_start_to_end(self):
        self.assertIsNone(self.hook(hook_event_name="SessionStart", source="startup", permission_mode="default"))
        talk = self.talk()
        self.assertEqual((talk["agent"], talk["project"], talk["working"]), ("Codex", "Lantern", False))

        self.hook(hook_event_name="UserPromptSubmit", prompt="Sort the bookmarks by name", turn_id="t1")
        talk = self.talk()
        self.assertEqual((talk["title"], talk["working"], talk["asked"]), ("Sort the bookmarks by name", True, "Sort the bookmarks by name"))

        self.hook(hook_event_name="PostToolUse", turn_id="t1", tool_name="update_plan", tool_use_id="u1",
                  tool_input={"plan": [{"step": "Read the sorting code", "status": "completed"},
                                       {"step": "Sort by name", "status": "in_progress"},
                                       {"step": "Run the tests", "status": "pending"}]}, tool_response="Plan updated")
        tasks = sorted((t["title"], t["status"]) for t in self.feed()["tasks"])
        self.assertEqual(tasks, [("Run the tests", "open"), ("Sort by name", "working")])

        self.hook(hook_event_name="PostToolUse", turn_id="t1", tool_name="apply_patch", tool_use_id="u2",
                  tool_input={"command": PATCH}, tool_response="Success")
        talk = self.talk()
        self.assertEqual([f["path"] for f in talk["files"]],
                         [os.path.join("src", n) for n in ("bookmark.js", "sort.js", "old-name.js", "new-name.js")])
        self.assertTrue(talk["changed"])

        self.hook(hook_event_name="Stop", turn_id="t1", stop_hook_active=False,
                  last_assistant_message="Bookmarks now sort by name. The tests pass.")
        talk = self.talk()
        self.assertEqual((talk["working"], talk["check"], talk["says"]["now"]), (False, True, "Bookmarks now sort by name. The tests pass."))

        self.hook(hook_event_name="UserPromptSubmit", prompt="Now by date", turn_id="t3")
        self.hook(hook_event_name="Interrupt", turn_id="t3", permission_mode="default")
        talk = self.talk()
        self.assertEqual((talk["working"], talk["says"]["now"]), (False, "I stopped, as you asked."))

        day = budget.local_day()
        with open(os.path.join(self.data, "feeds", "history", day + ".json"), encoding="utf-8") as handle:
            moments = [(m["kind"], m["what"]) for m in json.load(handle)["moments"]]
        self.assertIn(("changed", os.path.join("src", "bookmark.js") + " and 3 more"), moments)
        self.assertEqual(moments[-1][0], "stopped")

        self.assertIsNone(self.hook(hook_event_name="SessionEnd", reason="other"))
        self.assertEqual(self.feed()["conversations"], [])

    def test_amber_while_it_asks_and_codex_asks_as_usual_with_nobody_there(self):
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix the bookmark", turn_id="t1")
        began = time.time()
        self.assertIsNone(self.hook(hook_event_name="PermissionRequest", turn_id="t1", tool_name="apply_patch",
                                    tool_input={"command": PATCH}))
        self.assertLess(time.time() - began, 10)  # nobody in the building: straight back to Codex's own prompt
        talk = self.talk()
        self.assertEqual(talk["says"]["needs"], "I'm waiting for your permission: apply_patch: change src/bookmark.js, "
                                                "src/sort.js, src/old-name.js, src/new-name.js.")
        [ask] = [t for t in self.feed()["tasks"] if t["status"] == "needs_you"]
        self.assertEqual(ask["session"], KEY)

    def test_answered_from_the_building(self):
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix the bookmark", turn_id="t1")
        self.keep_watching()
        proc, ask = self.ask_in_the_background()
        self.assertEqual(ask["what"], "Bash: npm test")
        self.assertTrue(self.box.answer(ask["id"], "allow"))
        self.assertEqual(self.decision(proc), {"behavior": "allow"})

        proc, ask = self.ask_in_the_background(tool_input={"command": "rm -rf build"})
        self.box.stop(KEY)
        decision = self.decision(proc)
        self.assertEqual(decision["behavior"], "deny")
        self.assertNotIn("interrupt", decision)  # Codex refuses an interrupt here: it stops at its next step instead
        out = self.hook(hook_event_name="PostToolUse", turn_id="t1", tool_name="Bash", tool_use_id="u9",
                        tool_input={"command": "ls"}, tool_response="")
        self.assertEqual(out, {"continue": False, "stopReason": "Stopped from Arnheim, the building."})

    def test_a_message_from_the_building_reaches_it(self):
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix the bookmark", turn_id="t1")
        self.box.post(KEY, "Test it on the spare laptop too")
        out = self.hook(hook_event_name="Stop", turn_id="t1", stop_hook_active=False, last_assistant_message="Fixed it.")
        self.assertEqual(out["decision"], "block")  # Codex takes the reason as your next message
        self.assertIn("Test it on the spare laptop too", out["reason"])

    def test_two_agents_on_one_file(self):
        claude = dict(self.env)
        hook = os.path.join(ROOT, "connect", "claude_code.py")
        for event in ({"hook_event_name": "UserPromptSubmit", "prompt": "Tidy the bookmarks"},
                      {"hook_event_name": "PostToolUse", "tool_name": "Edit", "tool_input": {"file_path": os.path.join(self.lantern, "src", "sort.js")}}):
            subprocess.run([sys.executable, hook], input=json.dumps({"session_id": "claude-1", "cwd": self.lantern, **event}),
                           capture_output=True, text=True, env=claude, timeout=30, check=True)
        self.hook(hook_event_name="UserPromptSubmit", prompt="Sort the bookmarks", turn_id="t1")
        out = self.hook(hook_event_name="PostToolUse", turn_id="t1", tool_name="apply_patch", tool_input={"command": PATCH})
        words = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn('"Tidy the bookmarks" also changed src/sort.js', words.replace(os.sep, "/"))

    def test_notify_is_left_alone_once_the_hooks_run(self):
        given = {"type": "agent-turn-complete", "thread-id": "th-1", "cwd": self.lantern, "input-messages": ["Rename it"],
                 "last-assistant-message": "Renamed."}
        run = lambda: subprocess.run([sys.executable, CODEX, json.dumps(given)], capture_output=True, text=True, env=self.env, timeout=20)
        feed = os.path.join(self.data, "feeds", "agents.json")
        with open(os.path.join(self.codex_home, "hooks.json"), "w", encoding="utf-8") as handle:
            json.dump({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": f"python3 {CODEX}"}]}]}}, handle)
        run()
        with open(feed, encoding="utf-8") as handle:
            self.assertEqual(len(json.load(handle)["conversations"]), 1)  # hooks written but never run (old, or not trusted): notify shows it
        os.remove(feed)
        self.hook(hook_event_name="SessionStart", source="startup")  # the hooks run
        run()
        self.assertFalse(os.path.exists(feed))  # told once, by the hooks
        os.utime(os.path.join(self.data, "feeds", "codex-hooks"), (1, 1))  # not heard from in a long while
        run()
        self.assertTrue(os.path.exists(feed))


class CodexSpendingTest(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.base, True)
        self.path = os.path.join(self.base, "rollout.jsonl")

    def write(self, *totals, stamp="2026-11-17T10:00:00Z"):
        with open(self.path, "a", encoding="utf-8") as handle:
            for given, cached, wrote in totals:
                handle.write(json.dumps({"timestamp": stamp, "type": "response_item", "payload": {"type": "message", "content": "x"}}) + "\n")
                handle.write(json.dumps({"timestamp": stamp, "type": "event_msg", "payload": {"type": "token_count", "info": {
                    "total_token_usage": {"input_tokens": given, "cached_input_tokens": cached, "output_tokens": wrote,
                                          "reasoning_output_tokens": wrote // 2, "total_tokens": given + wrote},
                    "last_token_usage": {}}, "rate_limits": None}}) + "\n")
            handle.write(json.dumps({"timestamp": stamp, "type": "event_msg", "payload": {"type": "token_count", "info": None}}) + "\n")

    def test_the_growth_of_its_running_total(self):
        self.write((10000, 0, 500), (25000, 9000, 1200))
        day = budget.local_day("2026-11-17T10:00:00Z")
        spent, read = budget.new_tokens(self.path, {})
        self.assertEqual(spent, {day: 25000 - 9000 + 1200})  # fresh reading and writing, never the cache again
        spent, read = budget.new_tokens(self.path, read)
        self.assertEqual(spent, {})  # nothing new
        self.write((40000, 15000, 2000))
        spent, read = budget.new_tokens(self.path, read)
        self.assertEqual(spent, {day: (40000 - 15000 + 2000) - (25000 - 9000 + 1200)})

    def test_met_part_way_through_counts_from_there(self):
        self.write((10000, 0, 500))
        with open(self.path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "response_item", "payload": {"type": "message", "content": "x" * 3000}}) + "\n")
        before = os.path.getsize(self.path)
        self.write((12000, 1000, 600))
        tail = os.path.getsize(self.path) - before
        with open(self.path, "rb") as handle:
            whole = handle.read()
        for window, counted in ((150, 0), (tail + 100, (15000 - 1000 + 900) - (12000 - 1000 + 600))):
            with open(self.path, "wb") as handle:
                handle.write(whole)
            old, budget.FIRST_READ = budget.FIRST_READ, window
            try:
                spent, read = budget.new_tokens(self.path, {})
            finally:
                budget.FIRST_READ = old
            self.assertEqual(spent, {}, window)  # what came before the point it was met isn't counted
            self.write((15000, 1000, 900))
            spent, _ = budget.new_tokens(self.path, read)
            self.assertEqual(sum(spent.values()), counted, window)  # with no total seen yet, the next one is where it starts


class CodexSetupTest(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = os.path.join(self.base, "home")
        self.data = os.path.join(self.base, "data")
        self.project = os.path.join(self.home, "code", "recipes")
        os.makedirs(os.path.join(self.project, ".git"))
        sessions = os.path.join(self.home, ".codex", "sessions", "2026", "11", "17")
        os.makedirs(sessions)
        with open(os.path.join(sessions, "rollout-1.jsonl"), "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"type": "session_meta", "payload": {"id": "x", "cwd": self.project}}) + "\n")

    def run_setup(self, *args, path="/usr/bin:/bin"):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME", "ARNHEIM_DATA")}
        env.update(HOME=self.home, USERPROFILE=self.home, ARNHEIM_DATA=self.data, PATH=path)  # no claude, no codex command
        done = subprocess.run([sys.executable, SETUP, *args], capture_output=True, text=True, env=env, timeout=60)
        return done.returncode, done.stdout + done.stderr

    def hooks(self):
        with open(os.path.join(self.home, ".codex", "hooks.json"), encoding="utf-8") as handle:
            return json.load(handle)

    def test_codex_alone_gets_its_hooks(self):
        code, out = self.run_setup("--yes")
        self.assertEqual(code, 0, out)
        hooks = self.hooks()["hooks"]
        self.assertEqual(sorted(hooks), sorted(["SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PermissionRequest", "Stop", "SessionEnd", "Interrupt"]))
        command = hooks["Stop"][0]["hooks"][0]["command"]
        self.assertTrue(command.endswith("connect/codex.py"), command)
        self.assertEqual((hooks["PermissionRequest"][0]["hooks"][0]["timeout"], hooks["SessionEnd"][0]["hooks"][0]["timeout"]), (150, 3))
        self.assertIn("type /hooks, and trust Arnheim's", out)
        self.assertNotIn("Claude Code doesn't seem to be on this computer", out)  # Codex is enough
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "settings.json")))

        code, out = self.run_setup("--yes")
        self.assertIn("nothing changed", out)

    @unittest.skipIf(os.name == "nt", "the stand-in Codex is a shell script")
    def test_an_old_codex_gets_no_hooks_and_keeps_its_notify(self):
        bin_ = os.path.join(self.base, "bin")
        os.makedirs(bin_)
        with open(os.path.join(bin_, "codex"), "w") as handle:
            handle.write('#!/bin/sh\necho "codex-cli 0.98.0"\n')
        os.chmod(os.path.join(bin_, "codex"), 0o755)
        code, out = self.run_setup("--yes", path=f"{bin_}:/usr/bin:/bin")
        self.assertEqual(code, 0, out)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".codex", "hooks.json")))  # it would only go dark
        self.assertIn("This Codex is 0.98, older than 0.124", out)
        self.assertIn("notify", out)

    def test_your_own_codex_hooks_stay_and_undo_takes_out_only_arnheims(self):
        mine = {"hooks": {"PreToolUse": [{"matcher": "^Bash$", "hooks": [{"type": "command", "command": "python3 ~/.codex/hooks/policy.py"}]}],
                          "Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}
        with open(os.path.join(self.home, ".codex", "hooks.json"), "w", encoding="utf-8") as handle:
            json.dump(mine, handle)
        with open(os.path.join(self.home, ".codex", "config.toml"), "w", encoding="utf-8") as handle:
            handle.write('model = "gpt-5-codex"\nnotify = ["python3", "/old/arnheim/connect/codex.py"]\n\n[features]\nhooks = false\n')
        code, out = self.run_setup("--yes")
        self.assertEqual(code, 0, out)
        hooks = self.hooks()["hooks"]
        self.assertEqual(hooks["PreToolUse"][0], mine["hooks"]["PreToolUse"][0])  # yours first, as it was
        self.assertEqual(hooks["PreToolUse"][1]["matcher"], "apply_patch|Edit|Write|Bash")  # Arnheim's, for restore points
        self.assertEqual(hooks["Stop"][0], mine["hooks"]["Stop"][0])
        self.assertEqual(len(hooks["Stop"]), 2)
        self.assertIn("hooks = false", out)  # what keeps them from running is said
        self.assertIn("(notify)", out)
        self.assertTrue([f for f in os.listdir(os.path.join(self.home, ".codex")) if ".before-arnheim-" in f])

        code, out = self.run_setup("--undo")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.hooks(), mine)


if __name__ == "__main__":
    unittest.main()
