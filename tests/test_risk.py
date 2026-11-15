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
  notPermission: r.riskOf({ kind: 'task' }),
  exact: r.exactOf(ask('Bash', 'Bash: npm test -- reader')),
  exactBare: r.exactOf(ask('Read', 'Read')),
  kinds: ['permission', 'question', 'task'].map((kind) => r.kindWord({ kind }).word),
  finished: [{ proof: { state: 'proven' } }, { proof: { state: 'failed' } }, { review: { state: 'failed' }, proof: { state: 'proven' } }, {}]
    .map((x) => r.kindWord({ kind: 'turn', ...x }).word),
  meanings: ['permission', 'question', 'turn', 'task', 'other'].map((kind) => !!r.meaningOf({ kind })),
  asking: q.waitingOnYou({ conversations: [
    { id: 'a', title: 'A', says: { needs: 'Nothing yet. I will ask you first.' } },
    { id: 'b', title: 'B', says: { needs: 'Not yet.' } },
    { id: 'c', title: 'C', says: { needs: 'Should the badge be gold or silver?' } },
    { id: 'd', title: 'D', says: { needs: 'Now: pick a colour.' } },
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
        self.assertEqual([r[k]["word"] for k in ("read", "search", "privateRead", "edit", "web", "command", "unknown")],
                         ["Low risk", "Low risk", "Look first", "Changes files", "Goes online", "Read it first", "Read it first"])
        self.assertEqual([r[k]["mood"] for k in ("read", "privateRead", "edit", "command")], ["ok", "failed", "needs", "needs"])
        self.assertIsNone(r["notPermission"])

    def test_the_exact_thing(self):
        self.assertEqual(self.r["exact"], "npm test -- reader")
        self.assertIsNone(self.r["exactBare"])

    def test_kinds_and_what_they_mean(self):
        self.assertEqual(self.r["kinds"], ["Wants permission", "Asks you", "Your task"])
        self.assertEqual(self.r["finished"], ["Finished, proven", "Finished, not proven", "Finished, not proven", "Finished"])
        self.assertEqual(self.r["meanings"], [True, True, True, True, False])

    def test_needing_nothing_is_not_asking(self):
        self.assertEqual(self.r["asking"], ["c", "d"])


if __name__ == "__main__":
    unittest.main()
