"""The other agent checks the work (connect/review.py, "reviewer"): on a floor with a review line, Codex reads
Claude Code's work and Claude Code reads Codex's, or the one a floor names; the same agent when the other isn't
installed; and every result says who read it, here and on the page (src/review.js).

Each test makes a company of its own in a temporary folder (ARNHEIM_DATA), with a git folder for its floor, and
stand-ins for `claude` (ARNHEIM_CLAUDE) and `codex` (ARNHEIM_CODEX) that answer as told and note what they were
asked, so no real Claude Code or Codex runs and your data/ is never touched.
Run from the repository's folder: python3 -m unittest discover tests
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLAUDE_HOOK = os.path.join(ROOT, "connect", "claude_code.py")
CODEX_HOOK = os.path.join(ROOT, "connect", "codex.py")
sys.path.insert(0, os.path.join(ROOT, "connect"))
import budget  # noqa: E402  (after the path is set)
import review  # noqa: E402

GIT = shutil.which("git")
NODE = shutil.which("node")

# Stands in for `claude -p` (Claude Code's --output-format json): notes what it was asked, answers from claude.json.
CLAUDE = r"""
import json, os, sys
here = os.path.dirname(os.path.abspath(__file__))
asked = sys.stdin.read()
with open(os.path.join(here, "claude-asked.jsonl"), "a") as out:
    out.write(json.dumps({"args": sys.argv[1:], "asked": asked, "cwd": os.getcwd()}) + "\n")
with open(os.path.join(here, "claude.json")) as given:
    print(json.dumps(json.load(given)))
"""

# Stands in for `codex exec --json`: notes its arguments, where it ran and what it was asked, then writes the last
# message to the --output-last-message file and prints the events, as codex.json says.
CODEX = r"""
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
args = sys.argv[1:]
asked = sys.stdin.read()
with open(os.path.join(here, "codex-asked.jsonl"), "a") as out:
    out.write(json.dumps({"args": args, "asked": asked, "cwd": os.getcwd(), "reviewer": os.environ.get("ARNHEIM_REVIEWER")}) + "\n")
with open(os.path.join(here, "codex.json")) as given:
    answer = json.load(given)
time.sleep(answer.get("sleep", 0))
if answer.get("last") is not None and "--output-last-message" in args:
    with open(args[args.index("--output-last-message") + 1], "w") as out:
        out.write(answer["last"])
for event in answer.get("events", []):
    print(json.dumps(event))
sys.exit(answer.get("exit", 0))
"""


def codex_answer(text, exit=0, last=True, more=()):
    """What the stand-in Codex says: its events as `codex exec --json` prints them, and its last message."""
    events = [{"type": "thread.started", "thread_id": "0199a213-81c0-7800-8aa1-bbab2a035a53"}, {"type": "turn.started"},
              {"type": "item.completed", "item": {"id": "item_3", "type": "agent_message", "text": text}}, *more,
              {"type": "turn.completed", "usage": {"input_tokens": 2000, "cached_input_tokens": 1500, "output_tokens": 40, "reasoning_output_tokens": 10}}]
    return {"events": events, "last": text if last else None, "exit": exit}


CODEX_PASS = codex_answer("It does what was asked, and nothing else changed.\nVERDICT: PASS")
CODEX_BACK = codex_answer("The settings page is still red.\n\nVERDICT: SEND BACK: The settings page still uses the old red.")
CLAUDE_PASS = {"result": "Small and clear.\nVERDICT: PASS", "usage": {"input_tokens": 100, "output_tokens": 25}}


class Floor(unittest.TestCase):
    """A company with one floor kept in git, and both stand-ins ready."""

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.data = os.path.join(self.base, "data")
        self.lantern = os.path.join(self.base, "code", "lantern")
        self.tools = os.path.join(self.base, "tools")
        for folder in (self.data, self.lantern, self.tools):
            os.makedirs(folder)
        git = lambda *args: subprocess.run([GIT, "-C", self.lantern, *args], check=True, capture_output=True)
        git("init", "-q")
        self.write("app.js", "const colour = 'red';\n")
        git("add", "app.js")
        git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-q", "-m", "First")
        self.company(review=True)
        for name, text in (("claude.py", CLAUDE), ("codex.py", CODEX)):
            with open(os.path.join(self.tools, name), "w", encoding="utf-8") as handle:
                handle.write(text)
        self.answer("claude.json", CLAUDE_PASS)
        self.answer("codex.json", CODEX_PASS)
        run = lambda name: f"{shlex.quote(sys.executable)} {shlex.quote(os.path.join(self.tools, name))}"
        self.env = dict(os.environ, ARNHEIM_DATA=self.data, ARNHEIM_CLAUDE=run("claude.py"), ARNHEIM_CODEX=run("codex.py"))
        for name in ("ARNHEIM_REVIEWER", "CLAUDECODE"):
            self.env.pop(name, None)
        self.missing = os.path.join(self.tools, "not-installed")  # a command this computer doesn't have

    def company(self, **floor):
        with open(os.path.join(self.data, "company.json"), "w", encoding="utf-8") as handle:
            json.dump({"company": "Example Studio", "feeds": ["feeds/claude-code.json"],
                       "floors": [{"id": "lantern", "label": "Lantern", "folder": self.lantern, **floor}]}, handle)

    def answer(self, name, answer):
        with open(os.path.join(self.tools, name), "w", encoding="utf-8") as handle:
            json.dump(answer, handle)

    def write(self, name, text):
        with open(os.path.join(self.lantern, name), "w", encoding="utf-8") as handle:
            handle.write(text)

    def asked(self, who):
        try:
            with open(os.path.join(self.tools, f"{who}-asked.jsonl"), encoding="utf-8") as handle:
                return [json.loads(row) for row in handle]
        except OSError:
            return []

    def hook(self, codex=False, env=None, **event):
        """One hook event, as Claude Code hands it to its hook, or as Codex hands it to connect/codex.py."""
        event.setdefault("session_id", "abc123def456-7890")
        event.setdefault("cwd", self.lantern)
        done = subprocess.run([sys.executable, CODEX_HOOK if codex else CLAUDE_HOOK], input=json.dumps(event), capture_output=True,
                              text=True, env=env or self.env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout) if done.stdout else None

    def work(self, codex=False, env=None, said="I made it blue."):
        """A turn that changes app.js and ends: what the agent hears back."""
        self.hook(codex, env, hook_event_name="UserPromptSubmit", prompt="Make the button blue")
        self.write("app.js", "const colour = 'blue';\n")
        if codex:
            patch = "*** Begin Patch\n*** Update File: app.js\n@@\n-red\n+blue\n*** End Patch\n"
            self.hook(True, env, hook_event_name="PostToolUse", turn_id="t1", tool_name="apply_patch", tool_input={"command": patch})
        else:
            self.hook(False, env, hook_event_name="PostToolUse", tool_name="Edit", tool_input={"file_path": os.path.join(self.lantern, "app.js")})
        return self.hook(codex, env, hook_event_name="Stop", last_assistant_message=said)

    def talk(self):
        with open(os.path.join(self.data, "feeds", "claude-code.json"), encoding="utf-8") as handle:
            return json.load(handle)["conversations"][0]


@unittest.skipUnless(GIT, "git isn't installed")
class WhoReadsTest(Floor):
    def test_codex_reads_claude_codes_work_by_default(self):
        self.assertIsNone(self.work())
        talk = self.talk()
        self.assertEqual({k: talk["review"][k] for k in ("state", "by", "reviewer", "writer", "said")},
                         {"state": "passed", "by": "Codex", "reviewer": "Codex", "writer": "Claude Code",
                          "said": "Codex reviewed Claude Code's work: It does what was asked, and nothing else changed."})
        self.assertEqual(talk["spent"]["tokens"], 540)  # what Codex read fresh (2000 less 1500 from its cache) and wrote (40)
        self.assertEqual(self.asked("claude"), [])
        [call] = self.asked("codex")
        self.assertEqual((call["cwd"], call["reviewer"]), (self.lantern, "1"))  # in the floor's folder, and left alone by the hooks
        self.assertIn("-const colour = 'red';\n+const colour = 'blue';", call["asked"])  # the same prompt, on its stdin
        self.assertIn("VERDICT: PASS, or VERDICT: SEND BACK:", call["asked"])

    def test_the_codex_reader_can_only_read(self):
        self.work()
        args = self.asked("codex")[0]["args"]
        self.assertEqual(args[0], "exec")
        self.assertEqual(args[args.index("--sandbox") + 1], "read-only")
        configs = [args[n + 1] for n, a in enumerate(args) if a == "-c"]
        self.assertIn('approval_policy="never"', configs)  # never waits for an answer no one will give
        self.assertIn("features.hooks=false", configs)
        for flag in ("--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check", "--json"):
            self.assertIn(flag, args)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", args)
        self.assertNotIn("--yolo", args)
        self.assertEqual(args[args.index("--cd") + 1], self.lantern)
        self.assertEqual(args[-1], "-")  # the prompt comes on stdin
        last = args[args.index("--output-last-message") + 1]
        self.assertFalse(last.startswith(self.lantern + os.sep))  # its answer is kept outside the project
        self.assertFalse(os.path.exists(last))  # and cleared away after
        status = subprocess.run([GIT, "-C", self.lantern, "status", "--porcelain"], capture_output=True, text=True).stdout
        self.assertEqual(status.split(), ["M", "app.js"])  # only the agent's own change: the review added nothing

    def test_claude_code_reads_codexs_work_by_default(self):
        self.assertIsNone(self.work(codex=True))
        talk = self.talk()
        self.assertEqual(talk["agent"], "Codex")
        self.assertEqual({k: talk["review"][k] for k in ("by", "reviewer", "writer", "said")},
                         {"by": "Claude Code", "reviewer": "Claude Code", "writer": "Codex", "said": "Claude Code reviewed Codex's work: Small and clear."})
        self.assertEqual(self.asked("codex"), [])
        self.assertEqual(len(self.asked("claude")), 1)

    def test_the_same_agent_when_the_other_isnt_installed(self):
        self.assertIsNone(self.work(env=dict(self.env, ARNHEIM_CODEX=self.missing)))
        self.assertEqual(self.talk()["review"]["said"], "Claude Code reviewed it, since Codex isn't installed here: Small and clear.")
        self.assertEqual(self.asked("codex"), [])

    def test_codex_reads_its_own_when_claude_code_isnt_installed(self):
        self.assertIsNone(self.work(codex=True, env=dict(self.env, ARNHEIM_CLAUDE=self.missing)))
        self.assertEqual((self.talk()["review"]["by"], self.talk()["review"]["said"]),
                         ("Codex", "Codex reviewed it, since Claude Code isn't installed here: It does what was asked, and nothing else changed."))

    def test_a_floor_can_name_claude_code(self):
        self.company(review={"reviewer": "Claude Code"})
        self.assertIsNone(self.work())
        self.assertEqual(self.talk()["review"]["said"], "Claude Code reviewed it: Small and clear.")
        self.assertEqual(self.asked("codex"), [])

    def test_a_floor_can_name_codex(self):
        self.company(review={"reviewer": "codex"})
        self.assertIsNone(self.work(codex=True))
        self.assertEqual(self.talk()["review"]["said"], "Codex reviewed it: It does what was asked, and nothing else changed.")
        self.assertEqual(self.asked("claude"), [])

    def test_named_but_not_installed_says_so(self):
        self.company(review={"reviewer": "codex"})
        self.assertIsNone(self.work(env=dict(self.env, ARNHEIM_CODEX=self.missing)))  # it reaches you, not reviewed
        talk = self.talk()
        self.assertEqual((talk["review"]["state"], talk["review"]["by"], talk["check"]), ("error", "Codex", True))
        self.assertIn("Codex didn't start to review it", talk["review"]["said"])

    def test_codex_sends_it_back_and_says_so(self):
        self.answer("codex.json", CODEX_BACK)
        out = self.work()
        self.assertEqual(out["decision"], "block")
        self.assertIn("has a review line on this floor, where Codex reads the work, and it sent your work back (time 1 of 2", out["reason"])
        self.assertIn("The settings page still uses the old red.", out["reason"])
        talk = self.talk()
        self.assertEqual((talk["review"]["state"], talk["review"]["by"], talk["review"]["times"], talk["working"]), ("sent back", "Codex", 1, True))

    def test_while_it_waits_the_page_knows_who_reads(self):
        self.answer("codex.json", {**CODEX_PASS, "sleep": 3})
        self.hook(hook_event_name="UserPromptSubmit", prompt="Make the button blue")
        self.write("app.js", "const colour = 'blue';\n")
        self.hook(hook_event_name="PostToolUse", tool_name="Edit", tool_input={"file_path": os.path.join(self.lantern, "app.js")})
        event = {"session_id": "abc123def456-7890", "cwd": self.lantern, "hook_event_name": "Stop"}
        proc = subprocess.Popen([sys.executable, CLAUDE_HOOK], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, env=self.env)
        proc.stdin.write(json.dumps(event).encode())
        proc.stdin.close()
        try:
            seen = None
            for _ in range(40):
                time.sleep(0.1)
                seen = self.talk().get("review") or {}
                if seen.get("state") == "reviewing":
                    break
            self.assertEqual((seen.get("state"), seen.get("reviewer")), ("reviewing", "Codex"))
        finally:
            proc.wait(timeout=30)
        self.assertEqual(self.talk()["review"]["state"], "passed")

    def test_a_check_that_fails_first_is_who_decided(self):
        self.company(review=True, check={"run": [sys.executable, "-c", "raise SystemExit(1)"], "label": "The tests"})
        self.work()
        review_now = self.talk()["review"]
        self.assertEqual((review_now["by"], review_now["reviewer"]), ("The tests", "Codex"))  # Codex never read it
        self.assertEqual(self.asked("codex"), [])

    def test_check_only_names_no_reader(self):
        self.company(review={"read": False})
        self.assertIsNone(self.work())
        self.assertNotIn("reviewer", self.talk()["review"])


@unittest.skipUnless(GIT, "git isn't installed")
class CodexVerdictTest(Floor):
    def read(self, answer, timeout=60):
        self.answer("codex.json", answer)
        return review.read_codex(self.lantern, "Is it ready?", timeout, shlex.split(self.env["ARNHEIM_CODEX"]))

    def test_its_last_message_decides(self):
        got = self.read(codex_answer("Looks fine.\n**VERDICT: SEND BACK:** the test for blue is missing."))
        self.assertEqual((got["state"], got["said"], got["why"], got["tokens"]), ("sent back", "Looks fine.", "the test for blue is missing.", 540))

    def test_without_the_file_its_events_still_say_it(self):
        got = self.read(codex_answer("Fine.\nVERDICT: PASS", last=False))
        self.assertEqual((got["state"], got["said"]), ("passed", "Fine."))

    def test_trouble_is_no_verdict(self):
        failed = codex_answer("", more=[{"type": "turn.failed", "error": {"message": "You are not signed in."}}])
        self.assertEqual(self.read(failed)["said"], "Codex gave no verdict (You are not signed in.).")
        self.assertIn("Codex gave no verdict (it ended with code 2)", self.read({"events": [], "exit": 2})["said"])
        self.assertEqual(self.read(codex_answer("I looked and it's fine."))["said"], "Codex gave no verdict (I looked and it's fine.).")
        self.assertEqual(self.read({**CODEX_PASS, "exit": 1})["state"], "error")  # a verdict from a run that failed doesn't count

    def test_too_long_is_stopped(self):
        got = self.read({**CODEX_PASS, "sleep": 5}, timeout=1)
        self.assertEqual((got["state"], got["said"]), ("error", "Codex took longer than 1 seconds to review it and was stopped."))


class ChoiceTest(unittest.TestCase):
    def test_a_floor_says_who_reads(self):
        self.assertEqual(review.review_of({"review": True})["reviewer"], "other")
        for given, want in (("Claude Code", "claude"), ("claude", "claude"), ("claude-code", "claude"), (" CODEX ", "codex"),
                            ("other", "other"), ("the other agent", "other"), (None, "other"), (7, "other")):
            with self.subTest(given=given):
                self.assertEqual(review.review_of({"review": {"reviewer": given}})["reviewer"], want)

    def test_who_reads_for_each_writer(self):
        both = lambda agent: True
        only_claude = lambda agent: agent == review.CLAUDE
        cases = [("other", "Claude Code", both, ("Codex", "")), ("other", "Codex", both, ("Claude Code", "")),
                 ("other", "Claude Code", only_claude, ("Claude Code", "Codex isn't installed here")),
                 ("other", "Codex", only_claude, ("Claude Code", "")),
                 ("claude", "Codex", both, ("Claude Code", "")), ("codex", "Claude Code", only_claude, ("Codex", ""))]
        for choice, writer, here, want in cases:
            with self.subTest(choice=choice, writer=writer):
                with mock.patch.object(review, "installed", here):
                    self.assertEqual(review.reviewer({"reviewer": choice}, writer), want)

    def test_whose_work_it_is(self):
        self.assertEqual(review.writer_of({"arnheim_agent": "Codex"}, {}), "Codex")
        self.assertEqual(review.writer_of({}, {"agent": "Codex"}), "Codex")
        self.assertEqual(review.writer_of({}, {}), "Claude Code")

    def test_the_commands(self):
        with mock.patch.dict(os.environ, {"ARNHEIM_CODEX": "/opt/tools/codex --profile quiet", "ARNHEIM_CLAUDE": ""}):
            self.assertEqual(review.command_of("Codex"), ["/opt/tools/codex", "--profile", "quiet"])
            self.assertEqual(review.command_of("Claude Code"), ["claude"])

    def test_codex_events(self):
        raw = "\n".join(json.dumps(e) for e in codex_answer("VERDICT: PASS")["events"]) + "\nnot json\n"
        self.assertEqual(review.codex_said(raw), ("VERDICT: PASS", 540, ""))
        self.assertEqual(review.codex_said(json.dumps({"type": "error", "message": "Stream lost"})), ("", 0, "Stream lost"))


# The page's words for who reads (src/review.js), under Node.
SCRIPT = """
import { pathToFileURL } from 'node:url';
const { reviewOf, reviewSaid, reviewerOf, reviewersSaid } = await import(pathToFileURL(process.argv[1] + '/src/review.js').href);
const given = JSON.parse(process.argv[2]);
console.log(JSON.stringify({
  lines: given.talks.map((c) => reviewOf(c, given.now)?.line),
  own: given.talks.map((c) => reviewSaid(c, given.now)),
  floors: given.floors.map((f) => reviewerOf(f)?.line || null),
  settings: reviewersSaid(given.floors),
}));
"""
NOW = 1_800_000_000
TALKS = [
    {"review": {"state": "reviewing", "until": NOW + 300, "reviewer": "Codex"}},
    {"review": {"state": "reviewing", "until": NOW + 300, "reviewer": "Codex"}, "proof": {"state": "checking"}},
    {"review": {"state": "passed", "by": "Codex", "reviewer": "Codex", "said": "Codex reviewed Claude Code's work: It does what was asked."}},
    {"review": {"state": "sent back", "by": "Codex", "reviewer": "Codex", "why": "Still red.", "times": 2}},
    {"review": {"state": "failed", "by": "Claude Code", "reviewer": "Claude Code", "why": "Still red.", "times": 2}},
    {"review": {"state": "failed", "by": "The tests", "reviewer": "Codex", "why": "The tests failed.", "times": 0}},
    {"review": {"state": "error", "by": "Codex", "reviewer": "Codex", "said": "Codex gave no verdict (You are not signed in.)."}},
]
FLOORS = [{"label": "Lantern", "review": True}, {"label": "Studio", "review": {"reviewer": "codex"}},
          {"label": "Tidepool", "review": {"reviewer": "Claude Code"}}, {"label": "Kitefield", "review": {"read": False}},
          {"label": "Harbour"}, {"label": "Orchid", "review": {}}]


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageWordsTest(unittest.TestCase):
    def run_page(self, talks=TALKS, floors=FLOORS):
        given = {"talks": talks, "floors": floors, "now": NOW}
        done = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT, json.dumps(given)], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def test_results_name_who_read_it(self):
        out = self.run_page()
        self.assertEqual(out["lines"], [
            "Codex is reviewing its work before it reaches you.",
            "Its check runs first, then Codex reviews it before it reaches you.",
            "It passed the review line. Codex reviewed Claude Code's work: It does what was asked.",
            "Codex sent it back a second time, so it is fixing it: Still red.",
            "It still failed Claude Code's review after being sent back twice, so it reached you anyway: Still red.",
            "It failed the review line, so it reached you anyway: The tests failed.",  # the check decided, not the reader
            "The review line couldn't finish, so this work reached you unchecked. Codex gave no verdict (You are not signed in.).",
        ])
        self.assertEqual(out["own"][0], "Codex is reviewing my work now, before it reaches you.")
        self.assertEqual(out["own"][3], "Codex sent my work back a second time, so I'm fixing it: Still red.")
        self.assertEqual(out["own"][4], "My work still failed Claude Code's review after being sent back twice, so it reached you anyway: Still red.")

    def test_who_reviews_on_each_floor(self):
        out = self.run_page()
        self.assertEqual(out["floors"], [
            "The other agent reviews: Codex reads Claude Code's work, and Claude Code reads Codex's. If the other one isn't installed, the same agent reads it.",
            "Codex reviews every agent's work here, Claude Code's too.",
            "Claude Code reviews every agent's work here, Codex's too.",
            "No agent reads the work here: only its check decides.",
            None,
            "The other agent reviews: Codex reads Claude Code's work, and Claude Code reads Codex's. If the other one isn't installed, the same agent reads it.",
        ])
        self.assertEqual(out["settings"], "On Lantern and Orchid, the other agent reviews. On Studio, Codex reviews. "
                                          "On Tidepool, Claude Code reviews. On Kitefield, only the check decides.")
        self.assertIsNone(self.run_page(floors=[{"label": "Harbour"}])["settings"])
        for line in out["floors"] + [out["settings"]] + out["lines"]:
            self.assertNotIn("—", line or "")
            self.assertNotIn(" - ", line or "")

    def test_the_sample_shows_codex_reviewing_claude_codes_work(self):
        with open(os.path.join(ROOT, "sample", "work.json"), encoding="utf-8") as handle:
            talks = json.load(handle)["conversations"]
        with open(os.path.join(ROOT, "sample", "company.json"), encoding="utf-8") as handle:
            floors = json.load(handle)["floors"]
        out = self.run_page(talks=talks, floors=floors)
        self.assertIn("It passed the review line. Codex reviewed Claude Code's work: The keep and cancel lists match the statements, "
                      "and nothing was cancelled without asking.", out["lines"])
        self.assertTrue(out["settings"].startswith("On Studio and Lantern, the other agent reviews."))


if __name__ == "__main__":
    unittest.main()
