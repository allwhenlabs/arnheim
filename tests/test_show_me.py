"""Show me (docs/connect.md, "Show me"): finished work comes with something to look at. A floor that says how to show
its work (show_url, show) gets a picture from before, taken as an agent starts its first change after a message, and
one from after, taken in the background as its turn finishes (the hook, connect/claude_code.py, and connect/show.py),
at a desktop width and a phone width, or what the floor's show command made. The building lists them (connect/control.py,
"shows"), with Looks good and Not quite (show_ok, show_again) and each picture as base64 (show_image).

Each test makes a company of its own in a temporary folder (ARNHEIM_DATA), so your data/ is never touched. A stand-in
browser writes the pictures, so no real browser is needed; one test takes a real picture when Chrome, Chromium or Edge
is installed, and is skipped otherwise. The page's rules run under Node.js, skipped where it isn't installed. It runs
under Python 3.9 too. Run from the repository's folder: python3 -m unittest discover tests
"""
import base64
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connect"))
sys.path.insert(0, ROOT)

import control  # noqa: E402  (after the path is set)
import show  # noqa: E402
import switches  # noqa: E402

HOOK = os.path.join(ROOT, "connect", "claude_code.py")
SESSION = "abc123def456-7890"
KEY = "cc-abc123def456"
NODE = shutil.which("node")

# Stands in for Chrome: writes a white PNG the size of its window where --screenshot says, notes what it was asked, and
# with FAKE_BROWSER_SLOW takes that long first.
FAKE_BROWSER = r'''
import json, os, struct, sys, time, zlib
args = sys.argv[1:]
if os.environ.get("FAKE_BROWSER_LOG"):
    with open(os.environ["FAKE_BROWSER_LOG"], "a") as handle:
        handle.write(json.dumps(args) + "\n")
if os.environ.get("FAKE_BROWSER_SLOW"):
    time.sleep(float(os.environ["FAKE_BROWSER_SLOW"]))
out = next(a.split("=", 1)[1] for a in args if a.startswith("--screenshot="))
w, h = (int(x) for x in next(a.split("=", 1)[1] for a in args if a.startswith("--window-size=")).split(","))
def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
raw = (b"\x00" + b"\xff\xff\xff" * w) * h
with open(out, "wb") as handle:
    handle.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
'''
# Stands in for a floor's show command: one picture in ARNHEIM_SHOW_OUT, and a line of what it did.
SHOW_COMMAND = r'''
import os, struct, sys, zlib
def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
raw = (b"\x00" + b"\x00\x80\x00" * 4) * 3
with open(os.path.join(os.environ["ARNHEIM_SHOW_OUT"], "home-page.png"), "wb") as handle:
    handle.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 3, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
print("Phase:", os.environ["ARNHEIM_SHOW_PHASE"])
print("Made the home page picture. password = 'hunter2hunter2'")
'''
# Stands in for `claude -p`: says back what it was handed.
FAKE_CLAUDE = r'''
import json, sys
args = sys.argv[1:]
words = sys.stdin.read()
how = "resumed" if "--resume" in args else "started"
said = f"{how}: {words[:200]}"
print(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": said}]}}), flush=True)
print(json.dumps({"type": "result", "result": said}), flush=True)
'''


def png(w, h):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    raw = (b"\x00" + b"\x10\x20\x30" * w) * h
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


@unittest.skipIf(os.name == "nt", "the stand-in browser is a shell script")
class Company(unittest.TestCase):
    """A made-up company with one floor, Lantern, that shows its work: a page in its folder."""

    floor_extra = {"show_url": "site/index.html"}

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.data = os.path.join(self.base, "data")
        self.lantern = os.path.join(self.base, "code", "lantern")
        os.makedirs(self.data)
        os.makedirs(os.path.join(self.lantern, "site"))
        with open(os.path.join(self.lantern, "site", "index.html"), "w", encoding="utf-8") as handle:
            handle.write("<!doctype html><title>Lantern</title><h1>Before</h1>")
        self.write_company(self.floor_extra)
        fake = os.path.join(self.base, "fake_browser.py")
        with open(fake, "w", encoding="utf-8") as handle:
            handle.write(FAKE_BROWSER)
        self.browser = os.path.join(self.base, "fake-browser")
        with open(self.browser, "w", encoding="utf-8") as handle:
            handle.write(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n')
        os.chmod(self.browser, 0o755)
        self.command = os.path.join(self.base, "show_command.py")
        with open(self.command, "w", encoding="utf-8") as handle:
            handle.write(SHOW_COMMAND)
        self.claude = os.path.join(self.base, "fake_claude.py")
        with open(self.claude, "w", encoding="utf-8") as handle:
            handle.write(FAKE_CLAUDE)
        self.log = os.path.join(self.base, "browser.log")
        self.env = dict(os.environ, ARNHEIM_DATA=self.data, ARNHEIM_BROWSER=self.browser, FAKE_BROWSER_LOG=self.log, ARNHEIM_CONTROL_WAIT="5")
        self.env.pop("FAKE_BROWSER_SLOW", None)
        self.saved_env = {k: os.environ.get(k) for k in ("ARNHEIM_BROWSER", "FAKE_BROWSER_LOG", "ARNHEIM_SHOW_SECONDS", "FAKE_BROWSER_SLOW")}
        os.environ.update(ARNHEIM_BROWSER=self.browser, FAKE_BROWSER_LOG=self.log)
        self.addCleanup(self.restore_env)
        self.control = control.Control(self.data, claude=[sys.executable, self.claude])

    def restore_env(self):
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def write_company(self, extra):
        with open(os.path.join(self.data, "company.json"), "w", encoding="utf-8") as handle:
            json.dump({"company": "Example Studio", "rooms": [{"id": "work", "label": "Work"}],
                       "floors": [{"id": "lantern", "label": "Lantern", "folder": self.lantern, **extra}, {"id": "studio", "label": "Studio"}],
                       "feeds": ["feeds/claude-code.json"]}, handle)

    def hook(self, **event):
        event.setdefault("session_id", SESSION)
        event.setdefault("cwd", self.lantern)
        done = subprocess.run([sys.executable, HOOK], input=json.dumps(event), capture_output=True, text=True, env=self.env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout.strip() else None

    def call(self, name, body=None, method="POST"):
        code, _, data, _ = self.control.handle(method, name, b"" if body is None else json.dumps(body).encode(), self.control.token)
        return code, json.loads(data)

    def until(self, check, seconds=20):
        end = time.time() + seconds
        while time.time() < end:
            got = check()
            if got:
                return got
            time.sleep(0.1)
        self.fail("it never happened")

    def a_turn(self, said="I made the heading say After.", change=True):
        """A message, a change to the page and the turn ending: what the hook hears from Claude Code."""
        page = os.path.join(self.lantern, "site", "index.html")
        self.hook(hook_event_name="UserPromptSubmit", prompt="Make the heading say After")
        if change:
            self.hook(hook_event_name="PreToolUse", tool_name="Edit", tool_use_id="t1",
                      tool_input={"file_path": page, "old_string": "Before", "new_string": "After"})
            with open(page, "w", encoding="utf-8") as handle:
                handle.write("<!doctype html><title>Lantern</title><h1>After</h1>")
            self.hook(hook_event_name="PostToolUse", tool_name="Edit", tool_use_id="t1",
                      tool_input={"file_path": page, "old_string": "Before", "new_string": "After"}, tool_response={"success": True})
        return self.hook(hook_event_name="Stop", last_assistant_message=said)

    def ready(self):
        """The one show, once its pictures from after are in."""
        def got():
            rows = show.listing(self.data)
            return rows[0] if rows else None
        return self.until(got)

    def shows_dir(self):
        return os.path.join(self.data, "shows")


class FloorsAndBrowser(Company):

    def test_what_a_floor_shows(self):
        self.assertEqual(show.show_for("Lantern", self.data)["url"][:7], "file://")
        self.assertIsNone(show.show_for("Studio", self.data))  # says nothing, and has no folder
        self.write_company({"show_url": "http://localhost:3000/", "show": {"run": ["make", "shots"], "timeout": 5000}})
        given = show.show_for("Lantern", self.data)
        self.assertEqual(given["url"], "http://localhost:3000/")
        self.assertEqual(given["run"], ["make", "shots"])
        self.assertEqual(given["timeout"], 600)  # at most ten minutes
        self.write_company({"show_url": "../../outside.html"})  # outside the floor's folder: nothing
        self.assertIsNone(show.show_for("Lantern", self.data))
        self.write_company({"show_url": "javascript:alert(1)"})
        self.assertIsNone(show.show_for("Lantern", self.data))

    def test_finding_a_browser_never_assumes_a_path(self):
        seen = []

        def isfile(path):
            seen.append(path)
            return path.endswith("Microsoft Edge")
        mac = show.find_browser(env={}, which=lambda name: None, isfile=isfile, system="Darwin", home="/Users/someone")
        self.assertTrue(mac.endswith("Microsoft Edge.app/Contents/MacOS/Microsoft Edge"))
        self.assertTrue(any("Google Chrome.app" in p for p in seen))  # looked for Chrome first
        linux = show.find_browser(env={}, which=lambda name: "/usr/bin/chromium" if name == "chromium" else None, isfile=lambda p: False,
                                  system="Linux")
        self.assertEqual(linux, "/usr/bin/chromium")
        win = show.find_browser(env={"PROGRAMFILES": "C:\\Program Files"}, which=lambda name: None,
                                isfile=lambda p: p.endswith("chrome.exe"), system="Windows")
        self.assertTrue(win.endswith("chrome.exe"))
        self.assertIsNone(show.find_browser(env={}, which=lambda name: None, isfile=lambda p: False, system="Linux"))
        self.assertIsNone(show.find_browser(env={"ARNHEIM_BROWSER": "none"}))
        self.assertEqual(show.find_browser(env={"ARNHEIM_BROWSER": self.browser}), self.browser)

    def test_the_browser_is_asked_for_nothing_but_a_picture(self):
        args = show.browser_args("chrome", "http://localhost:3000/", "/tmp/x.png", 390, 844, "/tmp/profile")
        for word in ("--headless=new", "--disable-sync", "--disable-background-networking", "--disable-component-update",
                     "--no-first-run", "--user-data-dir=/tmp/profile", "--window-size=390,844", "--screenshot=/tmp/x.png"):
            self.assertIn(word, args)
        self.assertEqual(args[-1], "http://localhost:3000/")

    def test_a_server_that_isnt_running_says_so(self):
        self.write_company({"show_url": "http://127.0.0.1:9/"})  # the discard port: nothing answers
        got = show.take(self.data, "cc-abc123-1", "Lantern", "after", show.show_for("Lantern", self.data))
        self.assertEqual(got["pictures"], [])
        self.assertIn("nothing answered", got["why"])

    def test_a_real_picture_when_a_browser_is_here(self):
        real = show.find_browser(env={k: v for k, v in os.environ.items() if k != "ARNHEIM_BROWSER"})
        if not real:
            self.skipTest("no Chrome, Chromium or Edge on this computer")
        out = os.path.join(self.base, "real.png")
        why = show.capture(real, show.show_for("Lantern", self.data)["url"], out, 390, 844, wait=60)
        self.assertIsNone(why)
        self.assertEqual(show.picture_kind(out), "png")
        self.assertEqual(show.size_of(out), (390, 844))


class TheFinishPoint(Company):

    def test_before_at_the_first_change_and_after_as_the_turn_finishes(self):
        self.a_turn()
        s = self.ready()
        self.assertEqual(s["state"], "waiting")
        self.assertEqual(s["conv"], KEY)
        self.assertEqual(s["project"], "Lantern")
        self.assertEqual(s["how"], "browser")
        self.assertEqual(s["title"], "Make the heading say After")
        self.assertEqual(s["said"], "I made the heading say After.")
        seen = sorted((p["phase"], p["view"], p["width"], p["height"]) for p in s["pictures"])
        self.assertEqual(seen, [("after", "desktop", 1280, 800), ("after", "phone", 390, 844),
                                ("before", "desktop", 1280, 800), ("before", "phone", 390, 844)])
        self.assertEqual(s["changed"]["files"], 1)
        self.assertEqual(s["changed"]["names"], ["site/index.html"])
        with open(self.log, encoding="utf-8") as handle:
            asked = [json.loads(line) for line in handle]
        self.assertEqual(len(asked), 4)  # two widths, before and after
        self.assertTrue(all(a[-1].startswith("file://") and a[-1].endswith("site/index.html") for a in asked))
        # the picture from before was taken before the change: as the first change started, once
        before = os.path.getmtime(os.path.join(self.shows_dir(), f"{s['key']}-before-desktop.png"))
        self.assertLessEqual(before, os.path.getmtime(os.path.join(self.lantern, "site", "index.html")))

    def test_once_a_turn_and_a_new_turn_a_new_card(self):
        self.a_turn()
        first = self.ready()
        time.sleep(1.1)  # a turn is named by the second its message came
        self.a_turn(said="I changed it again.")
        self.until(lambda: len(show.listing(self.data)) == 2)
        keys = [r["key"] for r in show.listing(self.data)]
        self.assertIn(first["key"], keys)
        with open(self.log, encoding="utf-8") as handle:
            self.assertEqual(len(handle.readlines()), 8)

    def test_a_turn_that_ends_with_a_question_or_changed_nothing_shows_nothing(self):
        self.a_turn(said="I made it. Should the subheading change too?")
        time.sleep(1.5)
        self.assertEqual(show.listing(self.data), [])
        time.sleep(1.1)
        self.a_turn(change=False, said="The heading already says After.")
        time.sleep(1.5)
        self.assertEqual(show.listing(self.data), [])

    def test_a_floor_that_says_nothing_takes_nothing(self):
        self.write_company({})
        self.a_turn()
        time.sleep(1.5)
        self.assertFalse(os.path.exists(os.path.join(self.shows_dir(), "index.json")))
        self.assertFalse(os.path.exists(self.log))

    def test_switched_off_nothing_is_taken_and_nothing_listed(self):
        switches.save("show_me", False, self.data)
        self.a_turn()
        time.sleep(1.5)
        self.assertFalse(os.path.exists(self.log))
        self.assertEqual(self.control.state()["shows"], [])
        code, said = self.call("shows", {})
        self.assertEqual(code, 400)
        self.assertIn("switched off", said["error"])
        code, said = self.call("show_ok", {"key": "cc-abc123def456-1"})
        self.assertEqual(code, 400)

    def test_its_check_result_sits_beside_it(self):
        self.write_company({"show_url": "site/index.html", "check": {"run": [sys.executable, "-c", "print('all good')"], "label": "The tests"}})
        self.a_turn()
        self.ready()
        # as the turn ends the floor's check runs too (connect/prove.py): its result comes beside the pictures, for
        # src/proof.js to read as proven, not proven or claimed
        s = self.until(lambda: (lambda rows: rows[0] if rows and (rows[0]["proof"] or {}).get("proof", {}).get("state") == "passed" else None)(
            self.control.state()["shows"]))
        self.assertTrue(s["proof"]["changed"])
        self.assertEqual(s["proof"]["proof"]["check"], "The tests")


class TheCommand(Company):

    def test_no_browser_the_command_shows_it(self):
        self.write_company({"show_url": "site/index.html", "show": {"run": [sys.executable, self.command], "timeout": 30}})
        self.env["ARNHEIM_BROWSER"] = "none"
        self.a_turn()
        s = self.ready()
        self.assertEqual(s["how"], "command")
        self.assertEqual(sorted((p["phase"], p["view"]) for p in s["pictures"]), [("after", "home-page"), ("before", "home-page")])
        self.assertIn("Phase: after", s["output"]["after"])
        self.assertIn("Phase: before", s["output"]["before"])
        self.assertNotIn("hunter2hunter2", json.dumps(s))  # what looks like a secret is hidden
        self.assertFalse(os.path.exists(self.log))  # no browser was asked

    def test_no_browser_and_no_command_says_why(self):
        got = show.take(self.data, "cc-abc123-1", "Lantern", "after", show.show_for("Lantern", self.data), finder=lambda: None)
        self.assertEqual(got["pictures"], [])
        self.assertEqual(got["why"], show.NO_BROWSER)

    def test_a_browser_here_and_a_page_to_show_the_command_waits(self):
        self.write_company({"show_url": "site/index.html", "show": {"run": [sys.executable, self.command]}})
        got = show.take(self.data, "cc-abc123-1", "Lantern", "after", show.show_for("Lantern", self.data))
        self.assertEqual(got["how"], "browser")
        self.assertIsNone(got["output"])


class TimeLimits(Company):

    def test_a_slow_browser_is_stopped(self):
        os.environ["FAKE_BROWSER_SLOW"] = "30"
        started = time.time()
        out = os.path.join(self.base, "slow.png")
        why = show.capture(self.browser, "file:///nothing", out, 390, 844, wait=1)
        self.assertLess(time.time() - started, 15)
        self.assertIn("longer than 1 second,", why)
        self.assertFalse(os.path.exists(out))

    def test_a_slow_command_is_stopped(self):
        slow = os.path.join(self.base, "slow.py")
        with open(slow, "w", encoding="utf-8") as handle:
            handle.write("import time\nprint('starting', flush=True)\ntime.sleep(30)\n")
        self.write_company({"show": {"run": [sys.executable, slow], "timeout": 1}})
        started = time.time()
        got = show.take(self.data, "cc-abc123-1", "Lantern", "after", show.show_for("Lantern", self.data))
        self.assertLess(time.time() - started, 15)
        self.assertEqual(got["how"], "command")
        self.assertIn("starting", got["output"])

    def test_the_picture_from_before_waits_a_short_while_at_most(self):
        os.environ["FAKE_BROWSER_SLOW"] = "30"
        started = time.time()
        key = show.before(self.data, KEY, "Lantern", 1000, wait=1)
        self.assertLess(time.time() - started, 15)
        row = show.record(self.data, key)
        self.assertEqual(row["pictures"], [])
        self.assertIn("longer than 1 second,", row["why_before"])


class LooksGoodAndNotQuite(Company):

    def test_looks_good(self):
        self.a_turn()
        s = self.ready()
        state = self.control.state()
        self.assertEqual([x["key"] for x in state["shows"]], [s["key"]])
        code, said = self.call("show_ok", {"key": s["key"]})
        self.assertEqual(code, 200, said)
        self.assertEqual(said["state"], "approved")
        self.assertEqual(show.listing(self.data)[0]["state"], "approved")
        code, said = self.call("show_ok", {"key": "cc-nothere-1"})
        self.assertEqual(code, 400)

    def test_not_quite_reaches_the_agent_before_its_next_step(self):
        self.a_turn()
        s = self.ready()
        code, said = self.call("show_again", {"key": s["key"], "words": "Make the heading blue too."})
        self.assertEqual(code, 200, said)
        self.assertEqual(said["sent"], "queued")
        self.assertEqual(show.listing(self.data)[0]["state"], "again")
        self.assertEqual(show.listing(self.data)[0]["words"], "Make the heading blue too.")
        out = self.hook(hook_event_name="PreToolUse", tool_name="Read", tool_input={"file_path": "x"})
        told = out["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Make the heading blue too.", told)
        self.assertIn("Show me", told)
        code, said = self.call("show_again", {"key": s["key"], "words": ""})
        self.assertEqual(code, 400)

    def test_an_agent_started_here_carries_on_with_it(self):
        code, got = self.call("start", {"project": "Lantern", "text": "make the heading say After"})
        self.assertEqual(code, 200, got)
        key = got["key"]
        # its hooks never saw it (the stand-in runs none): Show me takes its pictures as it finishes
        s = self.until(lambda: next((r for r in show.listing(self.data) if r["conv"] == key), None))
        self.assertEqual(s["state"], "waiting")
        self.assertEqual({p["phase"] for p in s["pictures"]}, {"after"})
        code, said = self.call("show_again", {"key": s["key"], "words": "Bigger, please."})
        self.assertEqual(code, 200, said)
        self.assertEqual(said["sent"], "resumed")
        run = self.until(lambda: (lambda r: r if r and r.get("state") == "done" and "resumed" in (r.get("said") or "") else None)(self.control.runs.get(key)))
        self.assertIn("Bigger, please.", run["said"])
        code, said = self.call("show_ok", {"key": s["key"]})
        self.assertEqual(code, 200)
        self.assertTrue(self.control.runs[key].get("reviewed"))

    def test_looks_good_marks_the_ready_task_it_was_started_for(self):
        """One front door: an agent started from a ready task, and its Show me card's Looks good marks that task looked
        at (connect/intake.py, reviewed)."""
        code, got = self.call("intake", {"text": "Make the heading say After on Lantern", "via": "box"})
        self.assertEqual(code, 200, got)
        rid = got["task"]["id"]
        code, got = self.call("ready_start", {"id": rid})
        self.assertEqual(code, 200, got)
        key = got["task"]["key"]
        self.assertTrue(key.startswith("cc-"))
        s = self.until(lambda: next((r for r in show.listing(self.data) if r["conv"] == key), None))
        self.until(lambda: self.control.intake.task(rid)["state"] == "finished" or None)
        self.assertNotIn("reviewed", self.control.intake.task(rid))
        code, said = self.call("show_ok", {"key": s["key"]})
        self.assertEqual(code, 200, said)
        task = self.control.intake.task(rid)
        self.assertTrue(task.get("reviewed"))
        self.assertEqual(task["state"], "finished")
        # a task still marked started (its end not seen yet) is finished by Looks good
        task.update(state="started", reviewed=None)
        self.control.intake.save(task)
        self.assertEqual(self.control.intake.reviewed(key)["state"], "finished")
        self.assertIsNone(self.control.intake.reviewed("cc-nothere"))


class ThroughControl(Company):

    def test_a_picture_as_base64_for_a_phone(self):
        self.a_turn()
        s = self.ready()
        n = next(p["n"] for p in s["pictures"] if p["phase"] == "after" and p["view"] == "phone")
        code, got = self.call("show_image", {"key": s["key"], "n": n})
        self.assertEqual(code, 200, got)
        self.assertEqual(got["type"], "image/png")
        raw = base64.b64decode(got["data"])
        with open(os.path.join(self.shows_dir(), f"{s['key']}-after-phone.png"), "rb") as handle:
            self.assertEqual(raw, handle.read())
        for bad in ({"key": s["key"], "n": 99}, {"key": s["key"], "n": "0"}, {"key": s["key"], "n": True}, {"key": "../../etc", "n": 0}):
            self.assertEqual(self.call("show_image", bad)[0], 400, bad)

    def test_a_picture_never_comes_from_outside_its_folder(self):
        self.a_turn()
        s = self.ready()
        row = show.record(self.data, s["key"])
        row["pictures"][0]["file"] = "../company.json"
        show.write(show.record_path(self.data, s["key"]), row)
        self.assertIsNone(show.image(self.data, s["key"], 0))

    def test_the_server_keeps_the_pictures_on_this_computer(self):
        import serve
        self.assertIn("/data/shows/", serve.NEVER_AWAY)
        self.assertIn("shows", serve.HERE_ONLY_FOLDERS)
        self.assertIn("shows", serve.READS)
        self.assertIn("show_image", serve.READS)
        for name in ("shows", "show_ok", "show_again", "show_image"):
            self.assertRegex(name, r"^[a-z][a-z_]{0,15}$")  # a name another page passes on


class Sweep(Company):

    def test_the_last_twenty_of_each_for_thirty_days(self):
        folder = self.shows_dir()
        os.makedirs(folder)
        now = time.time()
        for i in range(25):
            key = f"cc-sweep1-{1000 + i}"
            with open(os.path.join(folder, f"{key}-after-desktop.png"), "wb") as handle:
                handle.write(png(2, 2))
            show.write(show.record_path(self.data, key), {"key": key, "conv": "cc-sweep1", "turn": 1000 + i, "phase": "ready", "state": "waiting",
                                                          "at": now - 60, "pictures": [{"file": f"{key}-after-desktop.png", "phase": "after", "view": "desktop"}]})
        old = "cc-sweep2-5"
        with open(os.path.join(folder, f"{old}-after-phone.png"), "wb") as handle:
            handle.write(png(2, 2))
        show.write(show.record_path(self.data, old), {"key": old, "conv": "cc-sweep2", "turn": 5, "phase": "ready", "state": "approved",
                                                      "at": now - 31 * 86400, "pictures": [{"file": f"{old}-after-phone.png"}]})
        for name, age in (("cc-stray1-1-after-desktop.png", 7200), ("cc-stray2-1-after-desktop.png", 10)):
            path = os.path.join(folder, name)
            with open(path, "wb") as handle:
                handle.write(png(2, 2))
            os.utime(path, (now - age, now - age))
        self.assertEqual(show.sweep(self.data, now=now), 6)
        kept = sorted(n for n in os.listdir(folder) if n.startswith("cc-sweep1-") and n.endswith(".json"))
        self.assertEqual(len(kept), 20)
        self.assertEqual(kept[0], "cc-sweep1-1005.json")  # the newest twenty
        self.assertFalse(os.path.exists(os.path.join(folder, "cc-sweep1-1000-after-desktop.png")))
        self.assertFalse(os.path.exists(show.record_path(self.data, old)))
        self.assertFalse(os.path.exists(os.path.join(folder, f"{old}-after-phone.png")))
        self.assertFalse(os.path.exists(os.path.join(folder, "cc-stray1-1-after-desktop.png")))  # named by no card, an hour old
        self.assertTrue(os.path.exists(os.path.join(folder, "cc-stray2-1-after-desktop.png")))  # perhaps being taken now
        self.assertEqual(len(show.listing(self.data)), 20)


class TheWords(unittest.TestCase):
    """What people read: no long dashes, the switch, the docs and the made-up cards."""

    def test_the_switch(self):
        row = next(s for s in switches.SWITCHES if s[0] == "show_me")
        self.assertTrue(row[4])  # on by default: it does nothing on a floor that doesn't say how to show its work
        self.assertNotIn("\u2014", row[2] + row[3])
        self.assertNotIn(" - ", row[2] + row[3])

    def test_the_docs(self):
        with open(os.path.join(ROOT, "docs", "connect.md"), encoding="utf-8") as handle:
            text = handle.read()
        part = text[text.index("## 28. Show me"):text.index("## What is kept, and where")]
        for word in ("show_url", "Looks good", "Not quite", "swipe", "data/shows/", "ARNHEIM_BROWSER", "20"):
            self.assertIn(word, part)
        self.assertNotIn("\u2014", part)
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
            self.assertIn("### Show me", handle.read())

    def test_the_made_up_cards_say_so(self):
        with open(os.path.join(ROOT, "sample", "shows.json"), encoding="utf-8") as handle:
            sample = json.load(handle)
        self.assertIn("Made up", sample["about"])
        self.assertEqual(len([s for s in sample["shows"] if s["state"] == "waiting"]), 3)
        for s in sample["shows"]:
            self.assertTrue(s["pictures"] or s.get("output"), s["key"])
            for p in s["pictures"]:
                self.assertIn("draw", p)
        text = json.dumps(sample, ensure_ascii=False)
        self.assertNotIn("\u2014", text)
        with open(os.path.join(ROOT, "src", "show-me.js"), encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn("Made up, like the rest of this company", page)
        self.assertNotIn("style=", page)
        self.assertNotIn(".style.", page)


PAGE = """
import { pathToFileURL } from 'node:url';
const s = await import(pathToFileURL(process.argv[1] + '/src/show-me.js').href);
const pics = [
  { n: 0, phase: 'before', view: 'desktop' }, { n: 1, phase: 'before', view: 'phone' },
  { n: 2, phase: 'after', view: 'desktop' }, { n: 3, phase: 'after', view: 'phone' }, { n: 4, phase: 'after', view: 'home-page' },
  { n: 5, phase: 'before', view: 'only-before' },
];
console.log(JSON.stringify({
  look: [1, 3].map(s.lookWords),
  pairs: s.pairsOf(pics).map((p) => [p.view, p.label, p.before?.n ?? null, p.after?.n ?? null]),
  changed: [s.changedWords({ files: 3, added: 12, removed: 4 }), s.changedWords({ files: 1, added: 1, removed: 0 }), s.changedWords(null)],
  swipes: [[120, 10], [-120, 5], [60, 0], [120, 90], [0, 300]].map(([x, y]) => s.swipeOf(x, y)),
  heard: ['looks good', 'That looks great to me.', 'approve it', 'not quite, make the button bigger', 'Not quite.', 'looks like rain', 'hold on']
    .map((t) => s.heardShow(t)),
  states: [{ state: 'waiting' }, { state: 'approved' }, { state: 'again', words: 'Bigger' }].map(s.stateLine),
}));
"""


# The cards drawn with a stand-in for the browser's document: the made-up company's, and one of your own through control.
CARDS = """
import { pathToFileURL } from 'node:url';
import { readFileSync } from 'node:fs';
class El {
  constructor(tag) { this.tag = tag; this.kids = []; this.attrs = {}; this.on = {}; this.dataset = {}; this.cls = new Set(); this.textContent = '';
    const self = this;
    this.classList = { add: (...c) => c.forEach((x) => self.cls.add(x)), remove: (...c) => c.forEach((x) => self.cls.delete(x)),
      toggle: (c, f) => { const want = f === undefined ? !self.cls.has(c) : !!f; if (want) self.cls.add(c); else self.cls.delete(c); return want; },
      contains: (c) => self.cls.has(c) }; }
  set className(v) { String(v).split(' ').filter(Boolean).forEach((c) => this.cls.add(c)); }
  append(...k) { for (const x of k) this.kids.push(x); }
  replaceChildren(...k) { this.kids = []; this.append(...k); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(k, f) { (this.on[k] ||= []).push(f); }
  querySelector() { return null; }
  closest() { return null; }
  all(pred, out = []) { if (pred(this)) out.push(this); for (const k of this.kids) if (k instanceof El) k.all(pred, out); return out; }
  text() { return [this.textContent, ...this.kids.map((k) => (k instanceof El ? k.text() : String(k)))].join(''); }
}
globalThis.Node = El;
globalThis.document = { createElement: (t) => new El(t), createElementNS: (ns, t) => new El(t), querySelector: () => null, querySelectorAll: () => [], head: new El('head') };
globalThis.requestAnimationFrame = () => 0;
const root = process.argv[1];
globalThis.fetch = async (url) => ({ ok: true, json: async () => JSON.parse(readFileSync(root + '/sample/shows.json', 'utf8')) });
const { createShowMe } = await import(pathToFileURL(root + '/src/show-me.js').href);
const tick = () => new Promise((r) => setTimeout(r, 20));
const base = { on: () => true, phone: () => false, label: (p) => p, ago: () => 'just now', done: () => {}, changed: () => {}, sampleUrl: () => 'sample/shows.json' };

const sample = createShowMe({ ...base, control: null, where: () => 'sample' });
sample.list(); await tick();
const made = sample.needsCard();
const out = { sampleCount: sample.count(), sampleText: made.text(), sampleDrawn: made.all((e) => e.tag === 'svg' && String(e.attrs.class || '').includes('sm-drawn')).length };

const asked = [];
const control = { on: true, watch() {}, shows: () => [{ key: 'cc-abc123-100', conv: 'cc-abc123', title: 'Make it green', project: 'Lantern', at: 1, state: 'waiting',
  pictures: [{ n: 0, phase: 'before', view: 'desktop' }, { n: 1, phase: 'before', view: 'phone' }, { n: 2, phase: 'after', view: 'desktop' }, { n: 3, phase: 'after', view: 'phone' }],
  proof: { changed: 10, proof: { state: 'passed', check: 'The tests', at: 11 } }, changed: { files: 2, added: 5, removed: 1, names: ['a.js', 'b.css'] } }],
  showImage: async (key, n) => { asked.push(n); return { type: 'image/png', data: 'iVBORw0KGgo=' }; },
  showOk: async (key) => ({ reply: `ok ${key}` }), showAgain: async (key, words) => ({ sent: 'queued', words }) };
const live = createShowMe({ ...base, control, where: () => 'live' });
const card = live.needsCard();
await tick();
const imgs = card.all((e) => e.tag === 'img');
out.liveText = card.text();
out.liveImgs = imgs.length;
out.liveLoaded = imgs.filter((e) => String(e.src || '').startsWith('data:image/png;base64,')).length;
out.asked = [...asked].sort();
out.heardGood = await live.heard('cc-abc123', 'looks good');
out.heardOther = live.heard('cc-other', 'looks good');
const phone = createShowMe({ ...base, control: { ...control, showImage: async (key, n) => { asked.push(`phone ${n}`); return { type: 'image/png', data: 'AA==' }; } },
  where: () => 'live', phone: () => true });
asked.length = 0;
phone.needsCard(); await tick();
out.phoneAsked = [...asked].sort();
const off = createShowMe({ ...base, control, where: () => 'live', on: () => false });
out.offCard = off.needsCard();
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class ThePage(unittest.TestCase):
    """The page's rules (src/show-me.js), under Node."""

    def test_the_cards_draw(self):
        done = subprocess.run([NODE, "--input-type=module", "-e", CARDS, ROOT], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        got = json.loads(done.stdout)
        self.assertEqual(got["sampleCount"], 3)
        for words in ("Show me: 3 things to look at", "Pictures for the app store", "Made up, like the rest of this company", "Looks good",
                      "Not quite", "Not proven", "Before", "After", "Desktop width", "Phone width"):
            self.assertIn(words, got["sampleText"])
        self.assertEqual(got["sampleDrawn"], 4)  # the first card: two widths, before and after, drawn
        for words in ("Show me: 1 thing to look at", "Make it green", "Proven", "2 files changed, 5 lines in and 1 out.", "Looks good"):
            self.assertIn(words, got["liveText"])
        self.assertEqual(got["liveImgs"], 4)
        self.assertEqual(got["liveLoaded"], 4)
        self.assertEqual(got["asked"], [0, 1, 2, 3])
        self.assertEqual(got["heardGood"], "ok cc-abc123-100")
        self.assertIsNone(got["heardOther"])
        self.assertEqual(got["phoneAsked"], ["phone 1", "phone 3"])  # a phone fetches the phone width's by itself, the rest when tapped
        self.assertIsNone(got["offCard"])

    def test_rules(self):
        done = subprocess.run([NODE, "--input-type=module", "-e", PAGE, ROOT], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        got = json.loads(done.stdout)
        self.assertEqual(got["look"], ["1 thing to look at", "3 things to look at"])
        self.assertEqual(got["pairs"], [["desktop", "Desktop width", 0, 2], ["phone", "Phone width", 1, 3], ["home-page", "Home page", None, 4],
                                        ["only-before", "Only before", 5, None]])
        self.assertEqual(got["changed"], ["3 files changed, 12 lines in and 4 out.", "1 file changed, 1 line in and 0 out.", None])
        self.assertEqual(got["swipes"], ["good", "again", None, None, None])
        self.assertEqual(got["heard"], [{"act": "good"}, {"act": "good"}, {"act": "good"}, {"act": "again", "words": "make the button bigger"},
                                        {"act": "ask"}, None, None])
        self.assertEqual(got["states"], ["Waiting for you to look.", "You said it looks good.", 'You asked for a change: "Bigger"'])

    def test_it_parses(self):
        for name in ("show-me.js", "control.js", "demo.js"):
            done = subprocess.run([NODE, "--check", os.path.join(ROOT, "src", name)], capture_output=True, text=True, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)


if __name__ == "__main__":
    unittest.main()
