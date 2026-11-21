"""Working beside your agents (docs/connect.md, "Work beside your agents"): each conversation's screen
(connect/live.py), a reply straight away with each message queued, taken and answered, questions that come to the
building, review together, and holding an agent at its next step (connect/control.py and the hook,
connect/claude_code.py, which Codex's events reach through connect/codex.py).

Each test makes a company of its own in a temporary folder (ARNHEIM_DATA), so your data/ is never touched, and
stand-ins answer for Claude Code's `claude` command. It runs under Python 3.9 too.
Run from the repository's folder: python3 -m unittest discover tests
"""
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

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connect"))

import control  # noqa: E402  (after the path is set)
import live  # noqa: E402
import switches  # noqa: E402

HOOK = os.path.join(ROOT, "connect", "claude_code.py")
CODEX = os.path.join(ROOT, "connect", "codex.py")
SESSION = "abc123def456-7890"
KEY = "cc-abc123def456"
TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"  # made up, in a GitHub token's shape
# Stands in for `claude -p`: says back what it was handed. Words starting "wait" keep it busy a while.
FAKE = r'''
import json, os, sys, time
args = sys.argv[1:]
words = sys.stdin.read()
how = "resumed" if "--resume" in args else "started"
sid = args[args.index("--resume" if how == "resumed" else "--session-id") + 1]
if words.startswith("wait"):
    time.sleep(30)
said = f"{how}: {words[:60]}"
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}}), flush=True)
print(json.dumps({"type": "result", "result": said, "session_id": sid}), flush=True)
'''
QUESTIONS = [{"question": "Which colour for the button?", "header": "Colour",
              "options": [{"label": "Blue", "description": "As the brand"}, {"label": "Green", "description": "Stands out"}], "multiSelect": False}]


class Company(unittest.TestCase):
    """A made-up company with one floor, Lantern, whose folder is a git repository."""

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.data = os.path.join(self.base, "data")
        self.lantern = os.path.join(self.base, "code", "lantern")
        os.makedirs(self.data)
        os.makedirs(os.path.join(self.lantern, "src"))
        with open(os.path.join(self.data, "company.json"), "w", encoding="utf-8") as handle:
            json.dump({"company": "Example Studio", "rooms": [{"id": "work", "label": "Work"}],
                       "floors": [{"id": "lantern", "label": "Lantern", "folder": self.lantern}, {"id": "studio", "label": "Studio"}],
                       "feeds": ["feeds/claude-code.json"]}, handle)
        fake = os.path.join(self.base, "fake_claude.py")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE)
        self.env = dict(os.environ, ARNHEIM_DATA=self.data, ARNHEIM_CONTROL_WAIT="5")
        self.box = control.Box(self.data)
        self.control = control.Control(self.data, claude=[sys.executable, fake])
        self.lv = live.Live(self.data)

    def hook(self, script=HOOK, **event):
        """Runs the hook as Claude Code does. What it printed, as JSON, or None."""
        event.setdefault("session_id", SESSION)
        event.setdefault("cwd", self.lantern)
        done = subprocess.run([sys.executable, script], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def in_background(self, script=HOOK, **event):
        """Runs the hook without waiting for it: (process, a function giving what it printed)."""
        event.setdefault("session_id", SESSION)
        event.setdefault("cwd", self.lantern)
        proc = subprocess.Popen([sys.executable, script], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=self.env)
        proc.stdin.write(json.dumps(event))
        proc.stdin.close()
        self.addCleanup(lambda: proc.poll() is None and proc.kill())

        def out(seconds=30):
            said = proc.stdout.read()
            proc.stdout.close()
            self.assertEqual(proc.wait(timeout=seconds), 0)
            return json.loads(said) if said.strip() else None
        return proc, out

    def call(self, method, name, body=None, token=None):
        code, _, data, _ = self.control.handle(method, name, b"" if body is None else json.dumps(body).encode(),
                                               self.control.token if token is None else token)
        return code, json.loads(data)

    def until(self, check, seconds=15):
        end = time.time() + seconds
        while time.time() < end:
            got = check()
            if got:
                return got
            time.sleep(0.1)
        self.fail("it never happened")

    def keep_watching(self):
        """Someone is using the building: its page says `here` every few seconds."""
        stop = threading.Event()

        def watch():
            while not stop.is_set():
                self.box.watch()
                stop.wait(1)
        threading.Thread(target=watch, daemon=True).start()
        self.addCleanup(stop.set)
        return stop

    def doc(self, key=KEY):
        return self.lv.read(key)

    def switch(self, name, on):
        switches.save(name, on, self.data)

    def git(self, *words):
        subprocess.run(["git", "-C", self.lantern, *words], check=True, capture_output=True,
                       env=dict(os.environ, GIT_AUTHOR_NAME="A", GIT_AUTHOR_EMAIL="a@example.com", GIT_COMMITTER_NAME="A",
                                GIT_COMMITTER_EMAIL="a@example.com", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull))


# ---------- 1. over their shoulder ----------

class WordsTest(unittest.TestCase):
    def test_steps_in_plain_words_inside_the_floor_folder(self):
        cwd = os.path.realpath(tempfile.gettempdir())
        self.assertEqual(live.what("Read", {"file_path": os.path.join(cwd, "src", "login.js")}, cwd)[1:], ("Reading src/login.js", "Read src/login.js", ["src/login.js"]))
        self.assertEqual(live.what("Bash", {"command": "npm test"}, cwd)[:3], ("command", "Running npm test", "Ran npm test"))
        self.assertEqual(live.what("Edit", {"file_path": "src/a.js"}, cwd)[1], "Editing src/a.js")
        self.assertEqual(live.what("apply_patch", {"command": "*** Begin Patch\n*** Update File: a.js\n@@\n-x\n+y\n*** Add File: b.js\n+z\n*** Add File: c.js\n+w\n*** End Patch"}, cwd)[1],
                         "Changing a.js, b.js and 1 more")
        self.assertEqual(live.what("exec_command", {"command": ["bash", "-lc", "cargo test"]}, cwd)[1], "Running cargo test")
        self.assertEqual(live.what("AskUserQuestion", {"questions": QUESTIONS}, cwd)[1], "Asking you: Which colour for the button?")
        self.assertEqual(live.what("mcp__github__create_issue", {}, cwd)[1], "Using create issue from github")
        # never this computer's own folders: a file elsewhere by its name, the home folder as ~
        self.assertEqual(live.what("Read", {"file_path": "/etc/hosts"}, cwd)[1], "Reading hosts")
        home = os.path.expanduser("~")
        self.assertEqual(live.what("Bash", {"command": f"ls {home}/x"}, cwd)[1], "Running ls ~/x")

    def test_secrets_are_hidden_in_words_and_in_lines(self):
        self.assertNotIn(TOKEN, live.what("Bash", {"command": f"curl -H 'Authorization: Bearer {TOKEN}' https://example.com"}, None)[1])
        self.assertEqual(live.redact(f"git push https://x:{TOKEN}@example.com"), "git push https://x:[hidden]@example.com")
        self.assertEqual(live.redact('db_password = "hunter2-correct-horse"'), 'db_password = "[hidden]"')
        self.assertEqual(live.redact('"api_key": "Zx9Qw8Er7Ty6Ui5Op4As3"'), '"api_key": "[hidden]"')
        self.assertEqual(live.redact("const total = 42"), "const total = 42")  # ordinary code stays
        made = "hunter2" + "-made-up"  # unquoted, as settings files and commands write them (the Checker's shapes)
        for given, shown in ((f"password: {made}", "password: [hidden]"), (f"db.password={made}", "db.password=[hidden]"),
                             (f"password = {made}", "password = [hidden]"), (f"client_secret: {TOKEN}", "client_secret: [hidden]"),
                             (f"mysql -u root -p{made} shop", "mysql -u root -p[hidden] shop")):
            self.assertEqual(live.redact(given), shown)
        for kept in ("token = getToken()", "MAX_TOKENS = 4000", "api_key: ${API_KEY}", "url: https://example.com/a"):
            self.assertEqual(live.redact(kept), kept)  # a call, a count, a reference and a link stay
        said = live.instant({}, True, "queued", permission=f"curl -H 'Authorization: Bearer {TOKEN}' https://example.com")
        self.assertNotIn(TOKEN, said["words"])  # the permission it waits on, as its instant reply names it
        made_up = "".join("Ab3dEf9h"[(n * 5) % 8] for n in range(64))  # in parts, so no scanner takes this file for a key
        block = ["const key = `", "-----BEGIN " + "RSA PRIVATE KEY-----", made_up, "-----END " + "RSA PRIVATE KEY-----", "`;"]
        hidden = live.redact_lines(block)
        self.assertEqual(len(hidden), len(block))  # the same lines, for the line numbers
        self.assertEqual(hidden[0], "const key = `")
        self.assertTrue(all("PRIVATE KEY" not in line and made_up not in line for line in hidden[1:4]), hidden)
        hunk = live.capped({"lines": [["+", f"TOKEN={TOKEN}"]]})
        self.assertNotIn(TOKEN, json.dumps(hunk))

    def test_the_caps(self):
        long = live.capped({"lines": [["+", "x" * 1000]] * 300 + [["-", "y"]] * 5})
        self.assertEqual(len(long["lines"]), live.HUNK_LINES)
        self.assertTrue(long["cut"])
        self.assertEqual((long["added"], long["removed"]), (300, 5))  # counted before cutting
        self.assertLessEqual(len(long["lines"][0][1]), live.LINE_CHARS)
        self.assertLessEqual(len(live.clean("word " * 400)), live.WORDS)
        with tempfile.TemporaryDirectory() as data:
            lv = live.Live(data)
            cwd = os.path.realpath(data)
            for n in range(live.STEPS_KEPT + 15):
                lv.finish({"session_id": SESSION, "cwd": cwd, "tool_name": "Edit", "tool_use_id": f"t{n}",
                           "tool_input": {"file_path": "big.js", "old_string": "a", "new_string": "b"},
                           "tool_response": {"structuredPatch": [{"oldStart": 1, "newStart": 1, "lines": ["+" + "z" * 300] * 60}]}}, "Lantern", "Claude Code")
            doc = lv.read(KEY)
            self.assertEqual(len(doc["steps"]), live.STEPS_KEPT)
            self.assertEqual(doc["steps"][-1]["id"], f"s{live.STEPS_KEPT + 15}")  # the newest are kept
            self.assertLessEqual(len(doc["changes"]), live.HUNKS_KEPT)
            self.assertLessEqual(os.path.getsize(os.path.join(data, "live", KEY + ".json")), live.FILE_MOST)
            for n in range(live.MESSAGES_KEPT + 5):
                lv.posted(KEY, f"m{n}", "hello " * 600)
            doc = lv.read(KEY)
            self.assertEqual(len(doc["messages"]), live.MESSAGES_KEPT)
            self.assertLessEqual(len(doc["messages"][0]["text"]), live.MESSAGE_CHARS)
            self.assertEqual(oct(os.stat(os.path.join(data, "live", KEY + ".json")).st_mode & 0o777), "0o600")  # yours alone

    def test_what_it_says_straight_away(self):
        now = 1000.0
        busy = {"now": {"kind": "command", "words": "Running npm test", "started_at": now - 40}}
        self.assertEqual(live.instant(busy, True, "queued", now=now),
                         {"words": "Got it. I'm running npm test right now, 40 seconds in. I'll pick this up as soon as that's done.", "when": "next_step"})
        self.assertEqual(live.instant({"now": {"kind": "thinking", "words": "Thinking", "started_at": now}}, True, "queued", now=now)["when"], "next_step")
        self.assertIn("between steps", live.instant({}, True, "queued", now=now)["words"])
        self.assertEqual(live.instant(busy, True, "queued", permission="Bash: rm -rf build", now=now)["when"], "after_permission")
        self.assertEqual(live.instant(busy, True, "queued", asking=True, now=now)["when"], "as_answer")
        self.assertEqual(live.instant(busy, True, "queued", hold={"state": "held"}, now=now)["when"], "now")
        self.assertEqual(live.instant(busy, True, "queued", hold={"state": "asked"}, now=now)["when"], "next_step")
        self.assertEqual(live.instant(busy, True, "queued", paused=True, now=now)["when"], "when_resumed")
        self.assertEqual(live.instant(None, False, "queued", now=now)["when"], "next_turn")
        self.assertEqual(live.instant(None, False, "resumed", now=now), {"words": "Got it. I'd finished, so I'm starting again on this now.", "when": "now"})
        self.assertIn("3 minutes in", live.instant({"now": {"kind": "edit", "words": "Editing src/a.js", "started_at": now - 200}}, True, "queued", now=now)["words"])
        for case in (busy, {}, None):  # words people read: no long dashes
            self.assertNotIn("—", live.instant(case, True, "queued", now=now)["words"])


class ChangesTest(unittest.TestCase):
    def setUp(self):
        self.cwd = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.cwd, True)
        os.makedirs(os.path.join(self.cwd, "src"))

    def put(self, name, text):
        with open(os.path.join(self.cwd, name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def event(self, tool, given, response=None):
        return {"session_id": SESSION, "cwd": self.cwd, "tool_name": tool, "tool_input": given, "tool_response": response or {}}

    def test_claude_codes_own_record_of_an_edit(self):
        got = live.hunks_of(self.event("Edit", {"file_path": os.path.join(self.cwd, "src/a.js"), "old_string": "b", "new_string": "B"},
                                       {"structuredPatch": [{"oldStart": 4, "oldLines": 3, "newStart": 4, "newLines": 3, "lines": [" a", "-b", "+B", " c"]}]}))
        self.assertEqual(got[0]["file"], "src/a.js")
        self.assertEqual((got[0]["start"], got[0]["old_start"], got[0]["added"], got[0]["removed"]), (4, 4, 1, 1))
        self.assertEqual(got[0]["lines"], [[" ", "a"], ["-", "b"], ["+", "B"], [" ", "c"]])

    def test_an_edit_from_its_words_placed_in_the_file(self):
        self.put("src/a.js", "one\ntwo\nthree\nFOUR\nfive\n")
        got = live.hunks_of(self.event("Edit", {"file_path": "src/a.js", "old_string": "three\nfour", "new_string": "three\nFOUR"}))
        self.assertEqual(got[0]["lines"], [[" ", "three"], ["-", "four"], ["+", "FOUR"]])
        self.assertEqual(got[0]["start"], 3)  # where it landed in the file
        multi = live.hunks_of(self.event("MultiEdit", {"file_path": "src/a.js", "edits": [{"old_string": "1", "new_string": "one"},
                                                                                        {"old_string": "5", "new_string": "five"}]}))
        self.assertEqual([h["start"] for h in multi], [1, 5])

    def test_a_write_compared_with_the_file_as_it_was_or_whole(self):
        before = "".join(f"line {n}\n" for n in range(1, 21))
        after = before.replace("line 12\n", "line twelve\n")
        got = live.hunks_of(self.event("Write", {"file_path": "src/b.js", "content": after}), before=before)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["start"], got[0]["kind"]), (9, "edit"))  # three lines either side
        self.assertIn(["-", "line 12"], got[0]["lines"])
        self.assertIn(["+", "line twelve"], got[0]["lines"])
        new = live.hunks_of(self.event("Write", {"file_path": "src/c.js", "content": "a\nb\n"}), before=live.NEW_FILE)
        self.assertEqual((new[0]["kind"], new[0]["lines"]), ("add", [["+", "a"], ["+", "b"]]))
        unknown = live.hunks_of(self.event("Write", {"file_path": "src/d.js", "content": "a\n"}))
        self.assertEqual(unknown[0]["kind"], "whole")  # its file as it was couldn't be read: marked so
        created = live.hunks_of(self.event("Write", {"file_path": "src/e.js", "content": "x\n"}, {"type": "create", "structuredPatch": []}))
        self.assertEqual(created[0]["kind"], "add")

    def test_a_notebook_cell(self):
        got = live.hunks_of(self.event("NotebookEdit", {"notebook_path": "n.ipynb", "cell_id": "c1", "new_source": "print(1)\nprint(2)", "edit_mode": "insert"}))
        self.assertEqual((got[0]["kind"], got[0]["cell"], got[0]["mode"], got[0]["added"]), ("notebook", "c1", "insert", 2))

    def test_codex_apply_patch_as_hunks(self):
        self.put("src/app.js", "import x\nconst a = 1\nconst b = 3\nexport {a}\n\nfunction go() {\n  return 2\n}\n")
        patch = ("*** Begin Patch\n"
                 "*** Update File: src/app.js\n@@\n const a = 1\n-const b = 2\n+const b = 3\n export {a}\n"
                 "@@ function go() {\n-  return 1\n+  return 2\n }\n"
                 "*** Add File: src/new.js\n+export const n = 1\n+export const m = 2\n"
                 "*** Delete File: src/old.js\n"
                 "*** Update File: src/name.js\n*** Move to: src/renamed.js\n@@\n-x\n+y\n"
                 "*** End Patch\n")
        files = live.parse_patch(patch)
        self.assertEqual([(f, op) for f, op, _ in files], [("src/app.js", "update"), ("src/new.js", "add"), ("src/old.js", "delete"), ("src/name.js", "update")])
        got = live.hunks_of(self.event("apply_patch", {"command": patch}))
        self.assertEqual([(h["file"], h["kind"]) for h in got],
                         [("src/app.js", "edit"), ("src/app.js", "edit"), ("src/new.js", "add"), ("src/old.js", "delete"), ("src/name.js", "edit")])
        first, second = got[0], got[1]
        self.assertEqual(first["lines"], [[" ", "const a = 1"], ["-", "const b = 2"], ["+", "const b = 3"], [" ", "export {a}"]])
        self.assertEqual((first["start"], second["start"]), (2, 7))  # placed in the file as it is now
        self.assertEqual((got[2]["added"], got[2]["start"]), (2, 1))
        self.assertEqual(got[4]["to"], "src/renamed.js")
        self.assertEqual(live.hunks_of(self.event("apply_patch", {"input": patch}))[0]["lines"], first["lines"])  # however Codex names it


class GitTest(Company):
    def put(self, name, text):
        with open(os.path.join(self.lantern, name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_git_diff_of_the_floors_folder_with_fixed_words_and_a_cap(self):
        self.assertIn("isn't kept in git", live.git_diff(self.lantern)["note"])
        self.git("init", "-q")
        self.put("src/a.js", "one\ntwo\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "first")
        self.put("src/a.js", f"one\nTWO\nconst token = '{TOKEN}'\n")
        self.put("src/new.js", "new\n")
        got = live.git_diff(self.lantern)
        self.assertEqual([f["file"] for f in got["files"]], ["src/a.js"])
        self.assertEqual(got["files"][0]["hunks"][0]["start"], 1)
        self.assertEqual(got["untracked"], ["src/new.js"])
        self.assertNotIn(TOKEN, json.dumps(got))
        cut = live.git_diff(self.lantern, most=40)
        self.assertTrue(cut["cut"])
        # through the page's request: the agent's own changes by file, and git's, labelled honestly, with no folders
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix it")
        self.hook(hook_event_name="PostToolUse", tool_name="Edit", tool_input={"file_path": os.path.join(self.lantern, "src/a.js"), "old_string": "two", "new_string": "TWO"},
                  tool_response={"structuredPatch": [{"oldStart": 1, "newStart": 1, "lines": [" one", "-two", "+TWO"]}]})
        code, changes = self.call("POST", "changes", {"key": KEY})
        self.assertEqual(code, 200, changes)
        self.assertEqual([f["file"] for f in changes["files"]], ["src/a.js"])
        self.assertEqual(changes["files"][0]["added"], 1)
        self.assertIn("Everything not yet committed in Lantern's folder, by anyone", changes["git"][0]["label"])
        self.assertEqual([f["file"] for f in changes["git"][0]["files"]], ["src/a.js"])
        self.assertNotIn(self.lantern, json.dumps(changes))
        self.assertEqual(self.call("POST", "changes", {"key": "cc-nobody"})[0], 400)


class ShoulderHookTest(Company):
    def test_now_steps_and_the_to_do_list_from_the_hooks(self):
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix the login page")
        self.assertEqual(self.doc()["now"]["words"], "Thinking about what you asked")
        began = time.time()
        self.assertIsNone(self.hook(hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": f"npm test --token {TOKEN}"}, tool_use_id="t1"))
        now = self.doc()["now"]
        self.assertEqual((now["kind"], now["words"], now["id"]), ("command", "Running npm test --token [hidden]", "t1"))
        self.assertGreaterEqual(now["started_at"], began - 1)
        self.hook(hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "npm test"}, tool_use_id="t1")
        doc = self.doc()
        self.assertEqual((doc["steps"][-1]["words"], doc["steps"][-1]["kind"]), ("Ran npm test", "command"))
        self.assertIsNotNone(doc["steps"][-1]["took"])
        self.assertEqual(doc["now"]["kind"], "thinking")
        self.hook(hook_event_name="PostToolUse", tool_name="TodoWrite", tool_input={"todos": [
            {"content": "Find the bug", "status": "completed"}, {"content": "Fix it", "status": "in_progress"}, {"content": "Test it", "status": "pending"}]})
        self.assertEqual([(t["title"], t["state"]) for t in self.doc()["todos"]], [("Find the bug", "done"), ("Fix it", "working"), ("Test it", "open")])
        self.hook(hook_event_name="TaskCreated", task_id="7", task_subject="Write the notes")
        self.hook(hook_event_name="TaskCompleted", task_id="7")
        self.assertIn({"id": "t7", "title": "Write the notes", "state": "done"}, self.doc()["todos"])
        # A Write, compared with the file as it was, kept before it was written.
        path = os.path.join(self.lantern, "src", "a.js")
        with open(path, "w") as handle:
            handle.write("one\ntwo\nthree\n")
        given = {"file_path": path, "content": "one\nTWO\nthree\n"}
        self.hook(hook_event_name="PreToolUse", tool_name="Write", tool_input=given, tool_use_id="t2")
        with open(path, "w") as handle:
            handle.write(given["content"])
        self.hook(hook_event_name="PostToolUse", tool_name="Write", tool_input=given, tool_use_id="t2")
        change = self.doc()["changes"][-1]
        self.assertEqual((change["file"], change["kind"], change["start"]), ("src/a.js", "edit", 1))
        self.assertEqual(os.listdir(os.path.join(self.data, "live", "before")), [])  # the copy goes once it is used
        index = self.lv.index()[KEY]
        self.assertEqual((index["project"], index["todos"]["done"], index["changed"]["files"]), ("Lantern", 2, 1))
        self.hook(hook_event_name="Stop", last_assistant_message="Fixed.")
        self.assertEqual((self.doc()["state"], self.doc()["now"]), ("finished", None))
        made = os.listdir(os.path.join(self.data, "control")) if os.path.isdir(os.path.join(self.data, "control")) else []
        self.assertEqual([n for n in made if not n.startswith("handover")], [])  # only the hand-over, as before: no mail, questions or holds

    def test_codex_steps_and_apply_patch(self):
        self.hook(script=CODEX, hook_event_name="UserPromptSubmit", prompt="Sort the list", turn_id="t1")
        self.hook(script=CODEX, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "cargo test"}, tool_use_id="c1", turn_id="t1")
        self.assertEqual(self.doc()["now"]["words"], "Running cargo test")
        patch = "*** Begin Patch\n*** Add File: src/sort.js\n+export {}\n*** End Patch\n"
        self.hook(script=CODEX, hook_event_name="PostToolUse", tool_name="apply_patch", tool_input={"command": patch}, tool_use_id="c2", turn_id="t1")
        doc = self.doc()
        self.assertEqual((doc["agent"], doc["steps"][-1]["words"]), ("Codex", "Changed src/sort.js"))
        self.assertEqual(doc["changes"][-1]["lines"], [["+", "export {}"]])

    def test_switched_off_nothing_is_recorded_and_outside_work_never(self):
        self.switch("live", False)
        self.switch("replies", False)
        self.hook(hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "ls"})
        self.hook(hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "ls"})
        self.assertFalse(os.path.exists(os.path.join(self.data, "live")))
        self.switch("live", True)
        self.hook(hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "ls"}, cwd=self.base, session_id="elsewhere-1")
        self.assertIsNone(self.lv.read("cc-elsewhere1"))  # a folder no floor names: not this company's work


class NeverAwayTest(unittest.TestCase):
    """data/live/ goes to this computer only: never over --lan, --share or a view-only link, and a phone gets it only
    through /control/ while this computer lets it control agents."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, ROOT)
        import serve
        from connect import remote
        cls.serve, cls.remote = serve, remote
        cls.base = tempfile.TemporaryDirectory()
        base = cls.base.name
        for name, text in (("index.html", "<!doctype html><title>Arnheim</title>"), ("data/company.json", '{"company": "Example Studio"}'),
                           ("data/live/cc-abc.json", '{"steps": "private"}'), ("data/live/index.json", '{"conversations": "private"}')):
            os.makedirs(os.path.dirname(os.path.join(base, name)), exist_ok=True)
            with open(os.path.join(base, name), "w", encoding="utf-8") as handle:
                handle.write(text)
        cls.root = serve.ROOT
        serve.ROOT = os.path.realpath(base)

        class Away(serve.Handler):  # a request marked "away" stands for one from another computer
            def here(self):
                return self.headers.get("X-Test-From") != "away" and super().here()
        cls.server = serve.Server(("127.0.0.1", 0), Away)
        cls.server.lan = True
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.serve.ROOT = cls.root
        cls.server.shutdown()
        cls.server.server_close()
        cls.base.cleanup()

    def ask(self, path, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}", **(headers or {})})
            reply = conn.getresponse()
            return reply.status, reply.read()
        finally:
            conn.close()

    def test_only_this_computer(self):
        self.assertEqual(self.ask("/data/live/index.json")[0], 200)
        self.assertEqual(self.ask("/data/live/cc-abc.json")[0], 200)
        for path in ("/data/live/index.json", "/data/Live/cc-abc.json", "/data/LIVE/index.json", "/data/%6Cive/index.json"):
            status, body = self.ask(path, {"X-Test-From": "away"})  # --lan: another computer
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"private", body)
        self.server.share = "k" * 32  # --share: even with the view-only link's key
        try:
            status, body = self.ask("/data/live/index.json", {"X-Test-From": "away", "Cookie": f"arnheim_view={'k' * 32}"})
            self.assertEqual(status, 404)
            self.assertEqual(self.ask("/data/company.json", {"X-Test-From": "away", "Cookie": f"arnheim_view={'k' * 32}"})[0], 200)
        finally:
            self.server.share = None
        # a paired phone: never the file, and /control/live only while this computer lets it control agents
        self.server.remote = self.remote.Remote("mac.example-tailnet.ts.net", self.base.name)
        calls = []

        class Stub:
            def handle(self, method, name, body=b"", token=""):
                calls.append(name)
                return 200, "application/json", b'{"ok": true}', {}
        self.server.control = Stub()
        try:
            self.server.remote.code()
            key, _ = self.server.remote.pair(self.server.remote.pending["code"])
            phone = {"Host": "mac.example-tailnet.ts.net", "X-Forwarded-For": "100.64.0.7", "Cookie": f"{self.remote.COOKIE}={key}"}
            self.assertEqual(self.ask("/data/live/index.json", phone)[0], 404)
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("POST", "/control/live", body=b'{"key": "cc-abc"}', headers={**phone, "Origin": "https://mac.example-tailnet.ts.net"})
            self.assertEqual(conn.getresponse().status, 403)
            conn.close()
            self.assertEqual(calls, [])
            self.server.remote.grant(self.server.remote.phones[0]["id"], 15)
            conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            conn.request("POST", "/control/live", body=b'{"key": "cc-abc"}', headers={**phone, "Origin": "https://mac.example-tailnet.ts.net"})
            self.assertEqual(conn.getresponse().status, 200)
            conn.close()
            self.assertEqual(calls, ["live"])
        finally:
            self.server.remote = None
            self.server.control = None


# ---------- 2. messages: status and the reply straight away ----------

class MessagesTest(Company):
    def test_queued_taken_answered_with_a_reply_straight_away(self):
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix the bookmark")
        self.hook(hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "npm test"}, tool_use_id="t1")
        code, sent = self.call("POST", "say", {"key": KEY, "text": "Use the blue button"})
        self.assertEqual((code, sent["sent"], sent["when"]), (200, "queued", "next_step"))
        self.assertTrue(sent["reply"].startswith("Got it. I'm running npm test right now,"), sent["reply"])
        self.assertTrue(sent["reply"].endswith("I'll pick this up as soon as that's done."))
        message = self.doc()["messages"][-1]
        self.assertEqual((message["id"], message["state"], message["reply"]), (sent["id"], "queued", sent["reply"]))
        # after the step under way it would sit in the tool's output: it waits for the next step, and goes in before it
        self.assertIsNone(self.hook(hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "npm test"}, tool_use_id="t1"))
        self.assertEqual(self.doc()["messages"][-1]["state"], "queued")
        out = self.hook(hook_event_name="PreToolUse", tool_name="Read", tool_input={"file_path": "a.js"}, tool_use_id="t2")
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])  # the step goes ahead
        self.assertIn('"Use the blue button"', out["hookSpecificOutput"]["additionalContext"])
        message = self.doc()["messages"][-1]
        self.assertEqual(message["state"], "taken")
        self.assertIsNotNone(message["taken_at"])
        self.assertEqual(message["taken_words"], 'I\'ve got your note about "Use the blue button" and I\'m on it.')
        self.hook(hook_event_name="Stop", last_assistant_message="Done: the button is blue now.")
        message = self.doc()["messages"][-1]
        self.assertEqual((message["state"], message["answer"]), ("answered", "Done: the button is blue now."))
        self.assertEqual(self.lv.index()[KEY]["messages"][-1]["state"], "answered")

    def test_answered_mid_turn_from_what_it_said_next(self):
        transcript = os.path.join(self.base, "t.jsonl")

        def says(words):
            with open(transcript, "a", encoding="utf-8") as handle:
                handle.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": words}]}}) + "\n")
        says("Looking at the tests.")
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix the bookmark", transcript_path=transcript)
        _, sent = self.call("POST", "say", {"key": KEY, "text": "Also the back button"})
        self.hook(hook_event_name="PostToolUse", tool_name="Read", tool_input={"file_path": "a.js"}, transcript_path=transcript)
        self.hook(hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, transcript_path=transcript)
        self.assertEqual(self.doc()["messages"][-1]["state"], "taken")  # nothing new said yet
        says("Sure, I'll fix the back button too.")
        self.hook(hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, transcript_path=transcript)
        message = self.doc()["messages"][-1]
        self.assertEqual((message["state"], message["answer"]), ("answered", "Sure, I'll fix the back button too."))

    def test_one_started_here_starts_again_at_once(self):
        _, started = self.call("POST", "start", {"project": "Lantern", "text": "Fix the login page"})
        key = started["key"]
        self.until(lambda: (self.control.runs.get(key) or {}).get("state") == "done")
        code, sent = self.call("POST", "say", {"key": key, "text": "And the logout page"})
        self.assertEqual((code, sent["sent"], sent["when"]), (200, "resumed", "now"))
        self.assertEqual(self.lv.read(key)["messages"][-1]["state"], "taken")
        self.until(lambda: self.lv.read(key)["messages"][-1]["state"] == "answered")
        self.assertEqual(self.lv.read(key)["messages"][-1]["answer"], "resumed: And the logout page")

    def test_switched_off_no_reply(self):
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix the bookmark")
        self.switch("replies", False)
        code, sent = self.call("POST", "say", {"key": KEY, "text": "Hello"})
        self.assertEqual(code, 200)
        self.assertNotIn("reply", sent)
        self.assertEqual((self.doc() or {}).get("messages") or [], [])  # nothing on its screen about it

    def test_the_new_requests_keep_controls_rules(self):
        for name in ("live", "changes", "hold", "go_on", "reply_question", "comment", "walk_through"):
            self.assertEqual(self.call("POST", name, {"key": KEY}, token="a guess")[0], 403, name)
            self.assertEqual(self.call("GET", name, token=self.control.token)[0], 405, name)
            self.assertEqual(self.call("POST", name, {"key": "../../etc"})[0], 400, name)


# ---------- 3. questions ----------

class QuestionsTest(Company):
    def setUp(self):
        super().setUp()
        self.hook(hook_event_name="UserPromptSubmit", prompt="Make the button nicer")
        os.makedirs(self.box.root)  # control has been used on this computer, though nobody uses the building now

    def asked(self):
        return self.until(lambda: next(iter(self.call("GET", "state")[1]["questions"]), None))

    def test_ask_user_question_answered_from_the_building(self):
        self.keep_watching()
        proc, out = self.in_background(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": QUESTIONS}, tool_use_id="q1")
        row = self.asked()
        self.assertEqual((row["key"], row["kind"], row["state"], row["text"]), (KEY, "choices", "waiting", "Which colour for the button?"))
        self.assertEqual([o["label"] for o in row["questions"][0]["options"]], ["Blue", "Green"])
        self.assertEqual(self.doc()["asking"]["id"], row["id"])
        self.assertEqual(self.call("POST", "reply_question", {"id": row["id"], "answers": {"Another question?": "Blue"}})[0], 400)
        code, got = self.call("POST", "reply_question", {"id": row["id"], "answers": {"Which colour for the button?": "Blue"}})
        self.assertEqual((code, got["sent"]), (200, "now"))
        said = out()["hookSpecificOutput"]
        self.assertEqual(said["permissionDecision"], "allow")
        self.assertEqual(said["updatedInput"], {"questions": QUESTIONS, "answers": {"Which colour for the button?": "Blue"}})
        self.assertEqual(self.call("GET", "state")[1]["questions"], [])
        self.assertEqual(self.call("POST", "reply_question", {"id": row["id"], "text": "Green"})[0], 400)  # once

    def test_own_words_and_a_message_answer_it_too(self):
        self.keep_watching()
        proc, out = self.in_background(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": QUESTIONS})
        row = self.asked()
        self.call("POST", "reply_question", {"id": row["id"], "text": "Purple, like the logo"})
        self.assertEqual(out()["hookSpecificOutput"]["updatedInput"]["answers"], {"Which colour for the button?": "Purple, like the logo"})
        proc, out = self.in_background(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": QUESTIONS})
        self.asked()
        _, sent = self.call("POST", "say", {"key": KEY, "text": "Green please"})
        self.assertEqual(sent["when"], "as_answer")
        self.assertEqual(out()["hookSpecificOutput"]["updatedInput"]["answers"], {"Which colour for the button?": "Green please"})
        self.assertEqual(self.doc()["messages"][-1]["state"], "taken")

    def test_nobody_there_asks_in_its_window_and_answering_later_is_a_message(self):
        began = time.time()
        self.assertIsNone(self.hook(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": QUESTIONS}))
        self.assertLess(time.time() - began, 5)  # nobody using the building: it asks in its window at once
        row = self.call("GET", "state")[1]["questions"][0]
        self.assertEqual(row["state"], "window")
        code, got = self.call("POST", "reply_question", {"id": row["id"], "answers": {"Which colour for the button?": "Blue"}})
        self.assertEqual((code, got["sent"]), (200, "queued"))
        out = self.hook(hook_event_name="PreToolUse", tool_name="Read", tool_input={})
        self.assertIn('About your question ("Which colour for the button?"): Blue', out["hookSpecificOutput"]["additionalContext"])

    def test_no_answer_in_time_falls_back_to_its_window(self):
        self.keep_watching()
        began = time.time()
        proc, out = self.in_background(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": QUESTIONS})
        self.assertIsNone(out())  # ARNHEIM_CONTROL_WAIT is 5 seconds here
        self.assertLess(time.time() - began, 15)
        self.assertEqual(self.call("GET", "state")[1]["questions"][0]["state"], "window")
        # answered in its own window: the card goes
        self.hook(hook_event_name="PostToolUse", tool_name="AskUserQuestion", tool_input={"questions": QUESTIONS})
        self.assertEqual(self.call("GET", "state")[1]["questions"], [])

    def test_a_turn_that_ends_with_a_question(self):
        self.keep_watching()
        proc, out = self.in_background(hook_event_name="Stop", last_assistant_message="I made it blue.\n\nShould I change the hover colour too?")
        row = self.asked()
        self.assertEqual((row["kind"], row["text"], row["state"]), ("words", "Should I change the hover colour too?", "waiting"))
        self.assertIn("I made it blue.", row["said"])  # what it said before asking, for the card
        self.call("POST", "reply_question", {"id": row["id"], "text": "Yes, a darker blue"})
        said = out()
        self.assertEqual(said["decision"], "block")
        self.assertIn('answered your question from Arnheim, the building: "Yes, a darker blue"', said["reason"])

    def test_a_turn_ending_with_a_question_nobody_sees_becomes_a_card(self):
        self.assertIsNone(self.hook(hook_event_name="Stop", last_assistant_message="Done. Want me to open a pull request?"))
        row = self.call("GET", "state")[1]["questions"][0]
        self.assertEqual(row["state"], "open")
        self.call("POST", "reply_question", {"id": row["id"], "text": "Yes"})
        self.assertIn("About your question", self.box.take(KEY)[0]["text"])
        self.assertIsNone(self.hook(hook_event_name="Stop", last_assistant_message="All done. The tests pass."))  # no question: nothing

    def test_switched_off_it_asks_in_its_window(self):
        self.switch("questions", False)
        self.keep_watching()
        self.assertIsNone(self.hook(hook_event_name="PreToolUse", tool_name="AskUserQuestion", tool_input={"questions": QUESTIONS}))
        self.assertIsNone(self.hook(hook_event_name="Stop", last_assistant_message="Should I go on?"))
        self.assertEqual(self.call("GET", "state")[1]["questions"], [])
        self.assertEqual(self.call("POST", "reply_question", {"id": "x" * 16, "text": "Yes"})[0], 400)

    def test_agents_started_here_are_told_to_ask_rather_than_guess(self):
        floor = control.floors_of(self.data)[0]
        self.assertIn("Ask rather than guess on anything that matters", self.control.brief("Fix it", floor))
        self.assertTrue(self.control.brief("Fix it", floor).endswith("say plainly what you did and how you checked it."))
        self.switch("questions", False)
        self.assertNotIn("Ask rather than guess", self.control.brief("Fix it", floor))
        self.assertNotIn("Ask rather than guess", control.brief(self.data, "Fix it", floor, more="as a routine"))  # routines: nobody to ask

    def test_what_counts_as_a_question(self):
        import claude_code
        self.assertEqual(claude_code.asked_in("Fixed.\n\nShould I also update the docs? Or leave them?")[0], "Should I also update the docs? Or leave them?")
        self.assertEqual(claude_code.asked_in("Which do you prefer?\n\n1. Blue\n2. Green")[0], "Which do you prefer?")
        self.assertIsNone(claude_code.asked_in("Done. See https://example.com/?a=1 for the page."))
        self.assertIsNone(claude_code.asked_in("Why did it fail? The cache was stale.\n\nI fixed it.\n\nAll tests pass."))
        self.assertIsNone(claude_code.asked_in("```\nwhat?\n```"))
        # Seen with real Claude Code: a dot in a file name or version doesn't end the sentence, and Markdown's marks go.
        self.assertEqual(claude_code.asked_in("Which colour should go in `colour.txt`: **Red** or **Blue**?")[0],
                         "Which colour should go in colour.txt: Red or Blue?")
        self.assertEqual(claude_code.asked_in("I updated v1.2 of the file. Should I push it?")[0], "Should I push it?")
        began = time.time()
        self.assertIsNone(claude_code.asked_in("word " * 20000))  # a long last message without a stop: read at once
        self.assertLess(time.time() - began, 1)


# ---------- 4. review together ----------

class ReviewTest(Company):
    def test_a_note_on_one_line_and_walk_me_through_it(self):
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix the login page")
        code, sent = self.call("POST", "comment", {"key": KEY, "file": "src/login.js", "line": 42, "text": "if (user = null) {",
                                                   "words": "That should be a comparison"})
        self.assertEqual((code, sent["sent"]), (200, "queued"))
        rows = self.box.take(KEY)
        self.assertEqual(rows[0]["text"], 'About your change to src/login.js, line 42 ("if (user = null) {"): That should be a comparison')
        self.assertEqual(self.doc()["messages"][-1]["taken_words"], "I've got your note on src/login.js, line 42, and I'm on it.")
        self.assertEqual(self.doc()["messages"][-1]["via"], "comment")
        self.call("POST", "comment", {"key": KEY, "file": "src/login.js", "line": 9, "text": "retry(3)", "words": "Keep the retry", "side": "old"})
        self.assertEqual(self.box.take(KEY)[0]["text"], 'About your change to src/login.js, line 9 as it was before your change ("retry(3)"): Keep the retry')
        for bad in ({"file": "", "line": 1, "words": "x"}, {"file": "a.js", "line": 0, "words": "x"}, {"file": "a.js", "line": "4", "words": "x"},
                    {"file": "a.js", "line": True, "words": "x"}, {"file": "a\nb", "line": 1, "words": "x"}, {"file": "a.js", "line": 1, "words": ""},
                    {"file": "a.js", "line": 1, "words": "x", "side": "left"}):
            self.assertEqual(self.call("POST", "comment", {"key": KEY, **bad})[0], 400, bad)
        code, sent = self.call("POST", "walk_through", {"key": KEY})
        self.assertEqual(code, 200)
        self.assertEqual(self.box.take(KEY)[0]["text"], control.WALK)
        self.switch("review_together", False)
        self.assertEqual(self.call("POST", "walk_through", {"key": KEY})[0], 400)
        self.assertEqual(self.call("POST", "comment", {"key": KEY, "file": "a.js", "line": 1, "words": "x"})[0], 400)


# ---------- 5. hold and carry on ----------

class Clock:
    """Time for await_hold that moves only as it waits."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class HoldWaitTest(unittest.TestCase):
    """await_hold on its own, with its times given, so a ten-minute hold takes no time."""

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, True)
        self.box = control.Box(self.data)
        self.clock = Clock()

    def wait(self, **given):
        return control.await_hold(self.box, KEY, **{"most": 600, "nobody": 120, "budget": 570, "tick": 0.25, "clock": self.clock,
                                                    "sleep": self.clock.sleep, **given})

    def test_not_held(self):
        self.assertIsNone(self.wait())

    def test_ten_minutes(self):
        self.box.hold(KEY)
        self.box.watch()  # someone is using the building all along
        self.assertEqual(self.wait(budget=10_000), ("ten minutes", []))
        self.assertGreaterEqual(self.clock.now, 1600)
        self.assertIsNone(self.box.hold_row(KEY))  # told once, then gone

    def test_two_minutes_after_nobody_is_there(self):
        self.box.hold(KEY)
        self.assertEqual(self.wait(), ("nobody", []))
        self.assertLess(abs(self.clock.now - 1120), 1)

    def test_still_held_when_one_step_has_waited_its_most(self):
        self.box.hold(KEY)
        self.box.watch()
        self.assertEqual(self.wait(budget=30), ("still", []))
        self.assertEqual(self.box.hold_row(KEY)["state"], "held")  # the hold goes on at its next step
        self.assertEqual(self.box.hold_row(KEY)["until"], 1600)  # ten minutes from the step it first held at

    def test_messages_carry_on_stop_and_off(self):
        self.box.hold(KEY)
        self.box.watch()
        self.box.post(KEY, "Use the other table")
        how, rows = self.wait()
        self.assertEqual((how, rows[0]["text"]), ("words", "Use the other table"))
        self.assertEqual(self.box.hold_row(KEY)["state"], "held")  # held again at its next step
        self.assertEqual(self.box.go_on(KEY), "held")
        self.assertEqual(self.wait(), ("carry on", []))
        self.assertIsNone(self.box.hold_row(KEY))
        self.box.hold(KEY)
        self.box.stop(KEY)
        self.assertEqual(self.wait(), ("stopped", []))
        self.assertTrue(self.box.stopping(KEY))  # left for the hook to spend, or for Codex's next step
        self.box.hold(KEY)
        self.assertEqual(self.wait(on=lambda: False), ("off", []))

    def test_two_steps_at_once_hand_over_once(self):
        self.box.hold(KEY)
        self.box.watch()

        def another_step_handed_over(seconds):  # a step run beside this one took your words while it waited
            self.box.change_hold(KEY, handed=7)
            self.clock.sleep(seconds)
        self.assertEqual(self.wait(sleep=another_step_handed_over), ("gone", []))  # so this one lets go, saying nothing
        self.assertEqual(self.wait(budget=10)[0], "still")  # its next step is held again
        self.box.go_on(KEY)
        self.assertEqual(self.wait(), ("carry on", []))
        self.assertEqual(self.wait(), None)  # told once: another step hears nothing

    def test_carry_on_before_any_step_tells_nothing(self):
        self.box.hold(KEY)
        self.assertEqual(self.box.go_on(KEY), "asked")
        self.assertIsNone(self.box.hold_row(KEY))
        self.assertIsNone(self.box.go_on(KEY))


class HoldHookTest(Company):
    def setUp(self):
        super().setUp()
        self.hook(hook_event_name="UserPromptSubmit", prompt="Tidy the tables")

    def held(self):
        return self.until(lambda: (self.box.hold_row(KEY) or {}).get("state") == "held")

    def test_hold_talk_it_through_and_carry_on(self):
        self.keep_watching()
        code, got = self.call("POST", "hold", {"key": KEY})
        self.assertEqual((code, got["hold"]["state"], got["reply"]), (200, "asked", "Okay, I'll hold at my next step."))
        began = time.time()  # after a step what you said would sit in the tool's output: it holds before the next one
        self.assertIsNone(self.hook(hook_event_name="PostToolUse", tool_name="Read", tool_input={"file_path": "a.js"}))
        self.assertLess(time.time() - began, 5)
        self.assertEqual(self.box.hold_row(KEY)["state"], "asked")
        proc, out = self.in_background(hook_event_name="PreToolUse", tool_name="Read", tool_input={"file_path": "a.js"})
        self.held()
        self.until(lambda: self.doc()["state"] == "held" and self.doc()["hold"]["until"] - self.doc()["hold"]["since"] == 600)  # ten minutes at most
        _, sent = self.call("POST", "say", {"key": KEY, "text": "Use the users table, not accounts"})
        self.assertEqual(sent["when"], "now")
        said = out()["hookSpecificOutput"]
        self.assertEqual(said["permissionDecision"], "deny")  # not run yet: it reads your words first
        context = said["additionalContext"]
        self.assertIn('"Use the users table, not accounts"', context)
        self.assertIn("Arnheim holds you there again until they say carry on", context)
        self.assertEqual(self.doc()["messages"][-1]["state"], "taken")
        # its next step: held again, before it runs; carry on lets it go, told why
        proc, out = self.in_background(hook_event_name="PreToolUse", tool_name="Edit", tool_input={"file_path": "a.js"})
        self.held()
        self.assertEqual(self.call("POST", "go_on", {"key": KEY})[1]["was"], "held")
        said = out()["hookSpecificOutput"]
        self.assertNotIn("permissionDecision", said)  # the step goes ahead as usual
        self.assertEqual(said["additionalContext"], control.HOLD_ENDS["carry on"])
        self.assertIsNone(self.hook(hook_event_name="PostToolUse", tool_name="Edit", tool_input={"file_path": "a.js"}))  # told once
        self.assertEqual(self.call("POST", "go_on", {"key": KEY})[0], 400)

    def test_words_before_a_step_turn_it_down_so_it_reads_them_first(self):
        self.keep_watching()
        self.call("POST", "hold", {"key": KEY})
        proc, out = self.in_background(hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "rm -rf build"})
        self.held()
        self.call("POST", "say", {"key": KEY, "text": "Don't delete build, it has the release"})
        said = out()["hookSpecificOutput"]
        self.assertEqual(said["permissionDecision"], "deny")
        # The words come as added context, never as the reason: Claude Code shows that reason as a hook error and won't
        # take instructions from it (seen with the real Claude Code, 21 Nov).
        self.assertIn("Read their words, given with this", said["permissionDecisionReason"])
        self.assertIn("Don't delete build", said["additionalContext"])
        self.assertIn("This step was not run", said["additionalContext"])
        self.assertNotIn("Don't delete build", said["permissionDecisionReason"])

    def test_a_write_turned_down_leaves_no_copy_of_the_file(self):
        self.keep_watching()
        with open(os.path.join(self.lantern, "settings.txt"), "w", encoding="utf-8") as handle:
            handle.write("as it was\n")
        self.call("POST", "hold", {"key": KEY})
        given = {"file_path": os.path.join(self.lantern, "settings.txt"), "content": "new\n"}
        proc, out = self.in_background(hook_event_name="PreToolUse", tool_name="Write", tool_input=given, tool_use_id="w1")
        self.held()
        self.assertEqual(len(os.listdir(self.lv.path("before"))), 1)  # kept while it waits, to show the change
        self.call("POST", "say", {"key": KEY, "text": "Leave settings alone"})
        self.assertEqual(out()["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(os.listdir(self.lv.path("before")), [])  # the step never ran: its copy goes at once
        old = os.path.join(self.lv.path("before"), "f" * 32)  # one left by a permission denied long ago
        with open(old, "w", encoding="utf-8") as handle:
            handle.write("old")
        os.utime(old, (time.time() - live.BEFORE_KEPT - 5,) * 2)
        self.hook(hook_event_name="PostToolUse", tool_name="Read", tool_input={"file_path": "a.js"})
        self.assertFalse(os.path.exists(old))

    def test_stop_still_stops_while_held(self):
        self.keep_watching()
        self.call("POST", "hold", {"key": KEY})
        proc, out = self.in_background(hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "ls"})
        self.held()
        self.call("POST", "stop", {"key": KEY})
        said = out()
        self.assertEqual(said["continue"], False)
        self.assertEqual(said["hookSpecificOutput"]["permissionDecision"], "deny")  # the step about to run doesn't
        self.assertFalse(self.box.stopping(KEY))  # spent
        self.assertIsNone(self.box.hold_row(KEY))

    def test_codex_held_and_stopped_before_a_step(self):
        self.hook(script=CODEX, hook_event_name="UserPromptSubmit", prompt="Tidy", turn_id="t1")
        self.keep_watching()
        self.call("POST", "hold", {"key": KEY})
        proc, out = self.in_background(script=CODEX, hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "ls"}, turn_id="t1")
        self.held()
        self.call("POST", "stop", {"key": KEY})
        said = out()
        self.assertNotIn("continue", said)  # Codex takes no continue: false before a step
        self.assertEqual(said["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertTrue(self.box.stopping(KEY, keep=True))  # it stops at its next step
        out = self.hook(script=CODEX, hook_event_name="PostToolUse", tool_name="Bash", tool_input={"command": "ls"}, turn_id="t1")
        self.assertEqual(out["continue"], False)

    def test_it_never_hangs(self):
        watching = self.keep_watching()
        self.env.update(ARNHEIM_HOLD_MOST="2")  # ten minutes, made two seconds
        self.call("POST", "hold", {"key": KEY})
        began = time.time()
        said = self.hook(hook_event_name="PreToolUse", tool_name="Read", tool_input={})
        self.assertLess(time.time() - began, 10)
        self.assertEqual(said["hookSpecificOutput"]["additionalContext"], control.HOLD_ENDS["ten minutes"])
        self.assertNotIn("permissionDecision", said["hookSpecificOutput"])
        self.env.update(ARNHEIM_HOLD_MOST="600", ARNHEIM_HOOK_MOST="1")  # one hook waits a second at most
        self.call("POST", "hold", {"key": KEY})
        said = self.hook(hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "ls"})
        self.assertEqual((said["hookSpecificOutput"]["permissionDecision"], said["hookSpecificOutput"]["additionalContext"]),
                         ("deny", control.STILL_HELD))
        self.env.update(ARNHEIM_HOOK_MOST="570", ARNHEIM_HOLD_NOBODY="1")  # two minutes after nobody is there, made one second
        watching.set()
        time.sleep(0.3)
        os.remove(self.box.path("watched"))  # nobody uses the building now
        began = time.time()
        said = self.hook(hook_event_name="PreToolUse", tool_name="Read", tool_input={})
        self.assertLess(time.time() - began, 10)
        self.assertEqual(said["hookSpecificOutput"]["additionalContext"], control.HOLD_ENDS["nobody"])
        self.assertIsNone(self.box.hold_row(KEY))

    def test_a_new_message_ends_a_hold_left_from_before(self):
        self.call("POST", "hold", {"key": KEY})  # held, then you press Esc in Claude Code and type something new
        self.assertEqual(self.box.hold_row(KEY)["state"], "asked")
        self.hook(hook_event_name="UserPromptSubmit", prompt="Do the other thing instead")
        self.assertIsNone(self.box.hold_row(KEY))
        self.assertIsNone(self.doc().get("hold"))
        self.assertIsNone(self.hook(hook_event_name="PreToolUse", tool_name="Read", tool_input={}))  # not held again

    def test_a_hold_at_the_end_of_a_turn(self):
        self.keep_watching()
        self.call("POST", "hold", {"key": KEY})
        proc, out = self.in_background(hook_event_name="Stop", last_assistant_message="All done.")
        self.held()
        self.call("POST", "say", {"key": KEY, "text": "Wait, run the linter too"})
        said = out()
        self.assertEqual(said["decision"], "block")
        self.assertIn('"Wait, run the linter too"', said["reason"])
        proc, out = self.in_background(hook_event_name="Stop", last_assistant_message="Linted.")
        self.held()
        self.call("POST", "go_on", {"key": KEY})
        self.assertIsNone(out())  # carry on: the turn ends as it was going to
        self.assertEqual(self.doc()["state"], "finished")

    def test_only_while_it_works_and_switched_on(self):
        self.hook(hook_event_name="Stop", last_assistant_message="Done.")
        self.assertEqual(self.call("POST", "hold", {"key": KEY})[0], 400)  # nothing to hold
        self.hook(hook_event_name="UserPromptSubmit", prompt="Again")
        self.switch("hold", False)
        self.assertEqual(self.call("POST", "hold", {"key": KEY})[0], 400)
        self.switch("hold", True)
        self.assertEqual(self.call("POST", "hold", {"key": KEY})[0], 200)
        self.switch("hold", False)  # switched off while asked: the hook lets it go, and says so
        said = self.hook(hook_event_name="PreToolUse", tool_name="Read", tool_input={})
        self.assertEqual(said["hookSpecificOutput"]["additionalContext"], control.HOLD_ENDS["off"])


class StateTest(Company):
    def test_state_says_what_is_on_and_what_waits(self):
        self.hook(hook_event_name="UserPromptSubmit", prompt="Fix it")
        self.hook(hook_event_name="PreToolUse", tool_name="Bash", tool_input={"command": "npm test"})
        state = self.call("GET", "state")[1]
        self.assertEqual(state["parts"], {"live": True, "replies": True, "questions": True, "review_together": True, "hold": True})
        self.assertEqual(state["live"][KEY]["now"]["words"], "Running npm test")
        self.assertEqual((state["questions"], state["holds"]), ([], {}))
        self.call("POST", "hold", {"key": KEY})
        self.assertEqual(self.call("GET", "state")[1]["holds"][KEY]["state"], "asked")
        code, one = self.call("POST", "live", {"key": KEY})
        self.assertEqual((code, one["on"], one["live"]["now"]["words"], one["hold"]["state"]), (200, True, "Running npm test", "asked"))
        self.assertNotIn(self.lantern, json.dumps(state))  # no folders in what the page is given
        self.switch("live", False)
        self.assertEqual(self.call("GET", "state")[1]["live"], {})

    def test_every_part_is_a_switch_on_by_default(self):
        for name in control.PARTS:
            self.assertIn(name, switches.NAMES)
            self.assertTrue(switches.DEFAULTS[name])


class LoadedByPathTest(unittest.TestCase):
    """A page with a server of its own may load Arnheim's modules by their paths alone under python3 -I; the new one must load that way too, and run
    under the Mac's own Python 3.9."""

    def test_loads_by_its_path_on_both_pythons(self):
        script = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('another_name', sys.argv[1])\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "c = module.Control(data=sys.argv[2], claude=['true'])\n"
            "print(module.live.redact('token ghp_' + 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'), len(module.live.parse_patch('*** Add File: a\\n+x')))\n")
        pythons = [sys.executable] + (["/usr/bin/python3"] if os.path.exists("/usr/bin/python3") else [])
        for python in pythons:
            base = tempfile.mkdtemp()
            try:
                done = subprocess.run([python, "-I", "-c", script, os.path.join(ROOT, "connect", "control.py"), base],
                                      capture_output=True, text=True, timeout=60, cwd=base)
            finally:
                shutil.rmtree(base)
            self.assertEqual(done.returncode, 0, (python, done.stderr))
            self.assertEqual(done.stdout.strip(), "token [hidden] 1", python)


if __name__ == "__main__":
    unittest.main()
