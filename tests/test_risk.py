"""What a waiting request asks of you, in plain words (src/risk.js): how careful to be with a permission, the
exact thing it would do, and what each kind of request means. Also the queue's rule that an agent saying it
needs nothing isn't asking anything (src/queue.js).

The rules are JavaScript, so this runs them under Node.js, and is skipped where Node isn't installed.
Run from the repository's folder: python3 -m unittest discover tests
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")

SCRIPT = """
import { pathToFileURL } from 'node:url';
const r = await import(pathToFileURL(process.argv[1] + '/src/risk.js').href);
const q = await import(pathToFileURL(process.argv[1] + '/src/queue.js').href);
const ask = (tool, what, extra = {}) => ({ kind: 'permission', tool, read: extra.read ?? true, ask: { what }, ...extra });
const cases = {
  read: r.riskOf(ask('Read', 'Read: notes.md')),
  privateRead: r.riskOf(ask('Read', 'Read: ~/.ssh/id_ed25519', { read: false })),
  search: r.riskOf(ask('Grep', 'Grep: TODO')),
  edit: r.riskOf(ask('Edit', 'Edit: app.js')),
  web: r.riskOf(ask('WebFetch', 'WebFetch: https://example.com')),
  command: r.riskOf(ask('Bash', 'Bash: npm test')),
  unknown: r.riskOf(ask('Mystery', 'Mystery')),
  proto: r.riskOf(ask('__proto__', '__proto__')),
  secretSearch: r.riskOf(ask('Grep', 'Grep: password in ~/.aws')),
  hiddenWrite: r.riskOf(ask('Write', 'Write: ~/.zshrc')),
  secretCommand: r.riskOf(ask('Bash', 'Bash: cat ~/.ssh/id_rsa')),
  notPermission: r.riskOf({ kind: 'task' }),
  exact: r.exactOf(ask('Bash', 'Bash: npm test -- reader')),
  exactBare: r.exactOf(ask('Read', 'Read')),
  kinds: ['permission', 'question', 'task'].map((kind) => r.kindWord({ kind }).word),
  finished: [{ proof: { state: 'proven' } }, { proof: { state: 'failed' } }, { review: { state: 'failed' }, proof: { state: 'proven' } }, {}]
    .map((x) => r.kindWord({ kind: 'turn', ...x }).word),
  meanings: ['permission', 'question', 'turn', 'task', 'other'].map((kind) => !!r.meaningOf({ kind })),
  asking: q.waitingOnYou({ conversations: [
    { id: 'a', title: 'A', says: { needs: 'Nothing yet.' } },
    { id: 'b', title: 'B', says: { needs: 'Not yet.' } },
    { id: 'c', title: 'C', says: { needs: 'Should the badge be gold or silver?' } },
    { id: 'd', title: 'D', says: { needs: 'Now: pick a colour.' } },
    { id: 'e', title: 'E', says: { needs: 'No, but should the badge be gold or silver?' } },
    { id: 'f', title: 'F', says: { needs: 'None of these fit. Which one should I use?' } },
    { id: 'g', title: 'G', says: { needs: 'Nothing works yet: can you check the key' } },
    { id: 'h', title: 'H', says: { needs: 'Not yet sure which colour you want.' } },
    { id: 'i', title: 'I', says: { needs: 'None.' } },
    { id: 'j', title: 'J', says: { needs: 'Not yet. Is the spare sensor ready?' } },
    { id: 'k', title: 'K', says: { needs: 'Not yet. Please add the API key to settings.' } },
    { id: 'l', title: 'L', says: { needs: 'Nothing yet!' } },
    { id: 'm', title: 'M', says: { needs: 'None. But the deploy needs your sign-off.' } },
  ] }).map((i) => i.key),
};
console.log(JSON.stringify(cases));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class RiskTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT], capture_output=True, text=True, timeout=60)
        if out.returncode:
            raise AssertionError(out.stderr)
        cls.r = json.loads(out.stdout)

    def test_how_careful_to_be(self):
        r = self.r
        # every read or search that asks reaches outside the project, so none is ever called low risk
        self.assertEqual([r[k]["word"] for k in ("read", "search", "privateRead", "edit", "web", "command", "unknown", "proto")],
                         ["Reads outside", "Searches outside", "Look first", "Changes files", "Goes online", "Read it first", "Read it first", "Read it first"])
        self.assertNotIn("ok", [r[k]["mood"] for k in ("read", "search", "edit", "web", "command", "unknown")])
        self.assertIn("AI service", r["read"]["line"])
        self.assertIsNone(r["notPermission"])

    def test_private_places_always_say_look_first(self):
        self.assertEqual([self.r[k]["word"] for k in ("secretSearch", "hiddenWrite", "secretCommand")], ["Look first"] * 3)

    def test_the_exact_thing(self):
        self.assertEqual(self.r["exact"], "npm test -- reader")
        self.assertIsNone(self.r["exactBare"])

    def test_kinds_and_what_they_mean(self):
        self.assertEqual(self.r["kinds"], ["Wants permission", "Asks you", "Your task"])
        self.assertEqual(self.r["finished"], ["Finished, proven", "Finished, not proven", "Finished, not proven", "Finished"])
        self.assertEqual(self.r["meanings"], [True, True, True, True, False])

    def test_needing_nothing_is_not_asking(self):
        # only a bare "Nothing yet.", "Not yet." or "None." is not asking; anything more still is
        self.assertEqual(self.r["asking"], ["c", "d", "e", "f", "g", "h", "j", "k", "m"])

    def test_one_answer_per_request(self):
        # keys and buttons both go through answerOnce, which never answers a request it already answered
        with open(os.path.join(ROOT, "src", "demo.js"), encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn("if (answered.has(i.ask.id)) return;", page)
        self.assertEqual(page.count("controlDone(answerAsk(i.ask.id"), 1)  # only inside answerOnce

    def test_no_allow_button_is_green(self):
        # every request that asks reaches outside the project or changes something: yes is never the easy reflex
        with open(os.path.join(ROOT, "src", "demo.js"), encoding="utf-8") as handle:
            page = handle.read()
        self.assertNotIn("'.go'", page)
        self.assertNotIn("btn.go", page)


if __name__ == "__main__":
    unittest.main()
