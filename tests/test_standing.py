"""Always allow what you always allow (connect/standing.py): what you allowed is counted, wherever you
allowed it; after twice, the next request offers to allow that exact command on its floor for good; a
standing allow then answers for every agent there, Claude Code and Codex alike, without asking; and only
commands that can't do much harm can stand. Each test makes a company of its own in a temporary folder.

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

import control  # noqa: E402
import standing  # noqa: E402

HOOK = os.path.join(ROOT, "connect", "claude_code.py")
CODEX = os.path.join(ROOT, "connect", "codex.py")


class CanStandTest(unittest.TestCase):
    def test_only_plain_checks_and_looks_from_the_list(self):
        for ok in ("npm test", "npm run lint", "npm run test:unit", "pnpm test", "yarn lint", "pytest -q", "git status",
                   "git diff --stat", "git log -5 --oneline", "git branch -a", "python3 -m unittest discover tests", "ls src",
                   "go test ./...", "cargo test", "make test", "make -j4 check", "./gradlew test", "ruff check .",
                   "npm test -- reader", "pytest -k bookmark", "go test -run Sort ./...", "git log -n 5", "head -20 README.md",
                   "grep -rn TODO src", "tsc --noEmit", "cargo test -p core"):
            self.assertTrue(standing.can_stand("Bash", ok), ok)
        for never in ("rm -rf build", "git push", "git reset --hard", "curl https://example.com", "npm install left-pad",
                      "pip install requests", "cat ~/.ssh/id_rsa", "cat .env", "echo hi > notes.txt", "npm test && rm x",
                      "sudo ls", "npx create-thing", "make deploy", "npm test 2>&1", "bash -c 'ls'; eval x", "ls $(pwd)",
                      "cat secrets.txt", "git commit -am wip", "mv a b", "brew upgrade", "npm test &", "gh pr merge 3",
                      "sh -c ls | sh", "git -c x pull", "npm test -- reader | tail -20",
                      # what got past the old list of what can never stand (the Checker's, 17 Nov)
                      "unlink build/out.txt", 'find . -name "*.log" -delete', "/bin/rm -r build", "\\rm -r build",
                      'sed -i "" s/a/b/ src/app.js', "tar -xf a.tar", "git update-ref -d refs/heads/main",
                      "git reflog expire --expire=now --all", "uvx cowsay", "go run example.com/x@latest", "ping -c 1 example.com",
                      "git send-email", "pkexec ls", 'python3 -c "import shutil"', "node -e x", "npm run test-and-deploy",
                      "npm run build:prod", "git diff --output=x", "git branch -D x", "eslint --fix .", "go test -exec x ./...",
                      "pytest -p evil", "make", "make install", "cat /etc/passwd", "ls ../other", "ls build\nnpm test",
                      # round two: a listed flag first, then one that deletes or moves; flags that write or run another program
                      "git branch -v -D feature", "git branch -r -d origin/feature", "git branch -v -f main 1a2b3c4",
                      "git branch -v -m main old", "go build -o=README.md", "go build -o x", "go test -toolexec=rm ./...",
                      "go vet -vettool=./x", "pytest --basetemp=src", "pytest --junitxml=README.md", "tsc --outFile README.md",
                      "jest -u", "deno test https://example.com/x.ts", "npm test -- -u", "npm test -- --outputFile=x",
                      "git diff --no-index a b", "cargo build --target-dir x",
                      # round three: the folder above the project
                      "pytest ..", "python3 -m unittest discover -s tests -t ..", "grep -r -i api ..", "ls -la ..", "du -sh ..",
                      "cat ..", "ls src/../.."):
            self.assertFalse(standing.can_stand("Bash", never), never)
        self.assertFalse(standing.can_stand("Read", "notes.md"))  # reads, searches, edits and the web always ask
        self.assertFalse(standing.can_stand("apply_patch", "npm test"))
        self.assertFalse(standing.can_stand("Bash", None))

    def test_only_the_exact_words_of_a_plain_request(self):
        self.assertEqual(standing.command_in("Bash", {"command": "npm test", "description": "Run the tests", "timeout": 60000}), "npm test")
        self.assertIsNone(standing.command_in("Bash", {"command": ["bash", "-lc", "rm -rf build"], "description": "npm test"}))
        self.assertIsNone(standing.command_in("Bash", {"command": "npm test", "dangerouslyDisableSandbox": True}))
        self.assertIsNone(standing.command_in("Bash", {"command": "npm test", "run_in_background": True}))
        self.assertIsNone(standing.command_in("Bash", {"command": "npm test", "with_escalated_permissions": True}))
        self.assertEqual(standing.command_in("Bash", {"command": "npm test", "run_in_background": False}), "npm test")
        self.assertIsNone(standing.command_in("Read", {"command": "npm test"}))


class StandingTest(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.data = os.path.join(self.base, "data")
        self.lantern = os.path.join(self.base, "code", "lantern")
        self.kite = os.path.join(self.base, "code", "kite")
        for folder in (self.data, self.lantern, self.kite):
            os.makedirs(folder)
        with open(os.path.join(self.data, "company.json"), "w", encoding="utf-8") as handle:
            json.dump({"company": "Example Studio", "rooms": [{"id": "work", "label": "Work"}],
                       "floors": [{"id": "lantern", "label": "Lantern", "folder": self.lantern},
                                  {"id": "kite", "label": "Kite", "folder": self.kite}],
                       "feeds": ["feeds/claude-code.json"]}, handle)
        self.env = dict(os.environ, ARNHEIM_DATA=self.data, ARNHEIM_CONTROL_WAIT="20")
        self.box = control.Box(self.data)
        self.control = control.Control(self.data, claude=[sys.executable, "-c", "pass"])

    def hook(self, script=HOOK, session="claude-1", cwd=None, **event):
        event.update(session_id=session, cwd=cwd or self.lantern)
        done = subprocess.run([sys.executable, script], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def allowed_in_the_agent(self, command, **where):
        """Asked with nobody in the building, so the agent asked in its own window, and you allowed it there: it ran."""
        self.assertIsNone(self.hook(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": command}, **where))
        self.hook(hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": command}, tool_response="ok", **where)

    def keep_watching(self):
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                self.box.watch()
                stop.wait(1)
        threading.Thread(target=watch, daemon=True).start()
        self.addCleanup(stop.set)

    def ask_in_the_background(self, command, script=HOOK, session="claude-1"):
        event = {"hook_event_name": "PermissionRequest", "session_id": session, "cwd": self.lantern, "tool_name": "Bash", "tool_input": {"command": command}}
        proc = subprocess.Popen([sys.executable, script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=self.env)
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

    def finish(self, proc):
        out = proc.stdout.read()
        proc.stdout.close()
        proc.wait(timeout=30)
        return json.loads(out)["hookSpecificOutput"]["decision"] if out.strip() else None

    def call(self, name, body=None):
        code, _, data, _ = self.control.handle("POST" if body is not None else "GET", name,
                                               json.dumps(body).encode() if body is not None else b"", self.control.token)
        return code, json.loads(data)

    def test_twice_allowed_then_always_then_never_asked_again(self):
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix the bookmark")
        self.allowed_in_the_agent("npm test")
        self.allowed_in_the_agent("npm test")
        self.allowed_in_the_agent("npm test", cwd=self.kite)  # another floor counts for that floor only
        self.assertEqual(standing.times(self.data, "Lantern", "Bash", "npm test"), 2)
        # asked, then not run (denied, say): never counted
        self.hook(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "npm test"})
        self.hook(hook_event_name="PostToolUse", tool_name="Read", tool_input={"file_path": "a.js"}, tool_response="")
        self.assertEqual(standing.times(self.data, "Lantern", "Bash", "npm test"), 2)

        self.keep_watching()
        proc, ask = self.ask_in_the_background("npm test")
        self.assertEqual((ask["before"], ask["standable"], ask["project"]), (2, True, "Lantern"))
        code, state = self.call("state")
        self.assertEqual(state["asks"][0]["before"], 2)
        code, said = self.call("always", {"id": ask["id"]})
        self.assertEqual(code, 200, said)
        self.assertEqual(self.finish(proc), {"behavior": "allow"})
        [row] = self.call("state")[1]["always"]
        self.assertEqual((row["project"], row["command"], row["what"]), ("Lantern", "npm test", "Bash: npm test"))

        began = time.time()
        out = self.hook(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "npm test"}, session="claude-2")
        self.assertEqual(out["hookSpecificOutput"]["decision"], {"behavior": "allow"})  # another agent, no waiting, no asking
        self.assertLess(time.time() - began, 10)
        self.assertEqual(standing.rows(self.data)[0]["used"], 1)
        with open(os.path.join(self.data, "feeds", "claude-code.json"), encoding="utf-8") as handle:
            feed = json.load(handle)
        self.assertFalse([t for t in feed["tasks"] if t["status"] == "needs_you" and t["session"] == "cc-claude2"])  # never amber

        out = self.hook(script=CODEX, hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "npm test"}, session="codex-1")
        self.assertEqual(out["hookSpecificOutput"]["decision"], {"behavior": "allow"})  # Codex too
        self.assertIsNone(self.hook(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "npm test"},
                                    cwd=self.kite, session="claude-3"))  # Kite still asks: it was allowed on Lantern
        # The same words, but a list that runs something else, or outside the sandbox: asked as ever (what the hook does)
        for given in ({"command": ["bash", "-lc", "rm -rf build"], "description": "npm test"},
                      {"command": "npm test", "dangerouslyDisableSandbox": True}, {"command": "npm  test"}):
            self.assertIsNone(standing.allows(self.data, "Lantern", "Bash", standing.command_in("Bash", given)), given)

        self.assertEqual(self.call("unalways", {"id": row["id"]})[0], 200)
        self.assertEqual(self.call("unalways", {"id": row["id"]})[0], 400)
        self.assertEqual(standing.rows(self.data), [])

    def test_never_for_a_command_that_can_do_harm(self):
        for _ in range(3):
            self.allowed_in_the_agent("rm -rf build")
        self.assertEqual(standing.times(self.data, "Lantern", "Bash", "rm -rf build"), 0)  # not even counted
        self.keep_watching()
        proc, ask = self.ask_in_the_background("rm -rf build")
        self.assertFalse(ask["standable"])
        code, said = self.call("always", {"id": ask["id"]})
        self.assertEqual(code, 400)
        self.assertIn("asks each time", said["error"])
        self.box.answer(ask["id"], "deny")
        self.assertEqual(self.finish(proc)["behavior"], "deny")

    def test_a_standing_allow_written_by_hand_is_checked_again(self):
        os.makedirs(os.path.join(self.data, "control"), exist_ok=True)
        with open(os.path.join(self.data, "control", "always.json"), "w", encoding="utf-8") as handle:
            json.dump({"rows": [{"id": "x1", "project": "Lantern", "tool": "Bash", "command": "rm -rf /", "what": "Bash: rm -rf /"}]}, handle)
        self.assertIsNone(self.hook(hook_event_name="PermissionRequest", tool_name="Bash", tool_input={"command": "rm -rf /"}))

    def test_not_for_good_until_allowed_twice_and_only_while_it_waits(self):
        self.keep_watching()
        proc, ask = self.ask_in_the_background("npm test")
        code, said = self.call("always", {"id": ask["id"]})  # the page offers it only after two; the server holds to that too
        self.assertEqual(code, 400)
        self.assertIn("Allow it 2 times", said["error"])
        self.assertEqual(standing.rows(self.data), [])
        self.box.answer(ask["id"], "deny")
        self.assertEqual(self.finish(proc)["behavior"], "deny")

    def test_stop_allowing_holds_while_the_hooks_count(self):
        row = standing.add(self.data, "Lantern", "Bash", "npm test")
        counting = [threading.Thread(target=lambda: [standing.used(self.data, row["id"]) for _ in range(20)]) for _ in range(4)]
        for t in counting:
            t.start()
        self.assertTrue(standing.remove(self.data, row["id"]))
        for t in counting:
            t.join()
        self.assertEqual(standing.rows(self.data), [])  # no count put it back


if __name__ == "__main__":
    unittest.main()
