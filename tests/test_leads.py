"""Each floor's lead and talking from any screen (src/leads.js): where a project stands and what changed, in a
few spoken sentences; who an instruction is for; going somewhere and being put through by name; and answering
a permission out loud, always read back first and never by voice for anything that may be private.

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

SCRIPT = r"""
import { pathToFileURL } from 'node:url';
const L = await import(pathToFileURL(process.argv[1] + '/src/leads.js').href);
const floor = { id: 'lantern', label: 'Lantern', project: 'Lantern', lead: { name: 'Juno', voice: 'af_nicole' } };
const plain = { id: 'kite', label: 'Kitefield', project: 'Kitefield' };
const convos = [
  { id: 'c1', title: 'Why the bookmark jumps', working: true, at: 100, says: { now: "I'm finding out why the bookmark jumps. It saves too soon." } },
  { id: 'c2', title: 'Pictures for the app store', working: false, at: 90, says: { now: 'Done for now.' } },
];
const ask = (id, what, tool = 'Bash', project = 'Lantern', title = 'Why the bookmark jumps') => ({ kind: 'permission', key: 'c1', title, project, what, tool, ask: { id, what: `${tool}: ${what}` } });
const run = ask('a1', 'to run npm test');
const secret = ask('a2', 'to read ~/.ssh/id_rsa', 'Read');
const places = [
  { href: '#/lantern/work', label: 'Work on Lantern', room: true, names: ['Work on Lantern', 'Lantern Work', 'Lanterns Work'] },
  { href: '#/lantern', label: 'Lantern', names: ['Lantern'] },
  { href: '#/company', label: 'the company page', names: ['company page', 'company'] },
];
const floors = [{ ...floor, lead: L.leadOf(floor) }, { id: 'tide', label: 'Tidepool', project: 'Tidepool', lead: L.leadOf({ id: 'tide', label: 'Tidepool', project: 'Tidepool' }) }];
const now = 10_000_000;
let p = null;
const step = (text, items, opts = {}) => { const v = L.voiceAnswer(text, items, p, { now, ...opts }); if (v) p = v.pending; return v; };
const out = {
  lead: L.leadOf(floor), plainLead: L.leadOf(plain), has: [L.hasLead(floor), L.hasLead({ ...floor, lead: false }), L.hasLead({ id: 'lobby' })],
  isLead: [L.isLeadHref('#/lantern/lead'), L.isLeadHref('#/lantern/work')],
  update: L.leadUpdate({ label: 'Lantern', conversations: convos, waiting: [run], goals: [{ title: 'Ten thousand readers', status: 'open' }],
    tasks: [{ status: 'open' }, { status: 'needs_you' }], prs: [{}], health: { problems: [{ kind: 'pr', line: 'x' }] }, spend: { text: '900 thousand tokens today' }, clashes: [] }),
  quiet: L.leadUpdate({ label: 'Kitefield', conversations: [], waiting: [] }),
  markup: L.leadUpdate({ label: 'Kitefield', conversations: [{ title: 'Kites', working: true, says: { now: 'I\'m working on what you asked: "<agent-message from=\"a1\"> [Subagent hand-back] The report".' } }], waiting: [] }),
  news: L.leadNews({ label: 'Lantern', since: 50, now: 200, from: 'since 14:05', conversations: convos,
    moments: [{ key: 'c2', at: 120, kind: 'finished', what: 'The pictures are ready.' }, { key: 'c1', at: 160, kind: 'changed', what: 'reader/bookmark.js' }],
    passed: [{ at: 150, key: 'c1', title: 'Why the bookmark jumps', text: 'Test it on the spare laptop.' }] }),
  nothing: L.leadNews({ label: 'Lantern', since: 50, now: 200, from: 'since 14:05', moments: [], passed: [] }),
  asked: ['where are we?', "what's new?", "who's working?", 'help', 'how is the bookmark fix going', 'tell them to test it on the spare laptop', 'nice weather'].map((t) => L.leadAsked(t)?.kind ?? null),
  pass: ['tell them to test it on the spare laptop', 'ask the agent on the bookmark fix to write the release note', 'pass it on that the key is in the vault',
    'I want them to stop after this step', 'can you tell everyone to tidy the tests', 'tell me a joke', 'ask them how long it will take?'].map((t) => L.passAsked(t)),
  final: ['merge it when the tests pass', 'deploy the shop', 'push the branch', 'test it on the spare laptop', 'write the release note'].map(L.needsSaying),
  target: [
    L.passTarget('test it', convos), L.passTarget('test it', [...convos, { id: 'c3', title: 'Reading streak', working: true }]),
    L.passTarget('test it', [{ id: 'c2', title: 'Pictures', working: false }]), L.passTarget('fix the pictures', convos, 'the agent on the pictures'),
  ].map((t) => (t.to ? `to ${t.to.id}` : t.which ? `which ${t.which.length}` : 'none')),
  pick: ['the second one', 'both of them', 'the one on the reading streak', 'hmm'].map((t) => L.pickFrom(t, [{ id: 'c1', title: 'Why the bookmark jumps' }, { id: 'c3', title: 'Reading streak' }])?.map((a) => a.id) ?? null),
  go: ['take me to Lantern', 'show me the work room on Lantern', "let's go to the company page", 'go home', 'back', 'take me to Narnia', 'what is new'].map((t) => L.goAsked(t, places)),
  through: ["how's Tidepool doing?", 'talk to Lantern\'s lead', 'put me through to Juno', 'Tidepool lead', 'what is new on Tidepool?', 'how are you?', 'tell me about Lantern and Tidepool status'].map((t) => L.throughAsked(t, floors)?.floor.id ?? null),
  throughThen: L.throughAsked("how's Tidepool doing?", floors).then,
  // allow by voice: the first "allow" reads it back; only then does "allow" answer, and only that one
  v1: step('allow', [run, secret]), v2: step('allow', [run, secret]), v3: step('allow', [run, secret]),
};
p = null;
out.privateFirst = step('allow', [secret, run]); out.privateAgain = step('allow', [secret, run]);
p = null;
out.off = step('allow', [run], { on: false }); out.offTyped = step('allow', [run], { on: false, spoken: false });
p = null;
out.none = step('allow', []); out.unrelated = step('nice weather', [run]); out.bareNo = step('no', [run]);
p = null;
step('allow', [run]); out.yes = step('yes', [run]); out.deny = step('deny', [run]);
p = null;
step('allow', [run]); out.late = L.voiceAnswer('allow', [run], p, { now: now + L.VOICE_HOLD_MS + 1 });
p = null;
step('allow', [run]); out.gone = L.voiceAnswer('allow', [ask('a9', 'to run ls')], p, { now });
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LeadsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT], capture_output=True, text=True, timeout=60)
        if out.returncode:
            raise AssertionError(out.stderr)
        cls.r = json.loads(out.stdout)

    def test_who_they_are(self):
        r = self.r
        self.assertEqual(r["lead"]["title"], "Juno, Lantern's lead")
        self.assertEqual((r["lead"]["href"], r["lead"]["voice"], r["lead"]["project"]), ("#/lantern/lead", "af_nicole", "Lantern"))
        self.assertEqual(r["plainLead"]["title"], "Kitefield's lead")
        self.assertIsNone(r["plainLead"]["name"])
        self.assertEqual(r["has"], [True, False, False])  # "lead": false switches one off; a floor with no project has none
        self.assertEqual(r["isLead"], [True, False])

    def test_where_it_stands(self):
        u = self.r["update"]
        for part in ('On Lantern, one agent is at work.', 'The one on "Why the bookmark jumps" says: I\'m finding out why the bookmark jumps.',
                     'One thing waits on you: "Why the bookmark jumps" wants your permission to run npm test.',
                     'The goal is "Ten thousand readers".', 'Open: one task and one pull request, one of them waiting over a week.',
                     'Spent: 900 thousand tokens today.'):
            self.assertIn(part, u)
        self.assertNotIn("It saves too soon", u)  # only the first sentence of what an agent says
        self.assertEqual(self.r["quiet"], "Nobody is working on Kitefield right now. Nothing here waits on you.")
        self.assertIn('One is on "Kites".', self.r["markup"])  # a message's markup is never read out
        self.assertNotIn("<", self.r["markup"])

    def test_what_changed_and_how_they_answered(self):
        n = self.r["news"]
        self.assertTrue(n.startswith("Since 14:05, on Lantern: "), n)
        self.assertIn('You asked the one on "Why the bookmark jumps" to test it on the spare laptop. It is on it, and changed reader/bookmark.js.', n)
        self.assertIn('"Pictures for the app store" finished: The pictures are ready.', n)
        self.assertEqual(self.r["nothing"], "Nothing new on Lantern since 14:05.")

    def test_what_a_lead_understands(self):
        self.assertEqual(self.r["asked"], ["update", "news", "who", "help", "update", "pass", None])

    def test_instructions_to_pass_on(self):
        texts = [x and x["text"] for x in self.r["pass"]]
        self.assertEqual(texts, ["Test it on the spare laptop.", "Write the release note.", "The key is in the vault.", "Stop after this step.",
                                 "Tidy the tests.", None, "How long it will take?"])
        self.assertEqual(self.r["pass"][1]["hint"], "the agent on the bookmark fix")
        self.assertTrue(self.r["pass"][6]["question"])

    def test_some_instructions_are_read_back_first(self):
        self.assertEqual(self.r["final"], [True, True, True, False, False])

    def test_who_an_instruction_is_for(self):
        # the one at work; several at work, so it asks which; nobody at work; the one named, even if it isn't working
        self.assertEqual(self.r["target"], ["to c1", "which 2", "none", "to c2"])
        self.assertEqual(self.r["pick"], [["c3"], ["c1", "c3"], ["c3"], None])

    def test_going_somewhere(self):
        go = self.r["go"]
        self.assertEqual([g and g.get("href") for g in go[:4]], ["#/lantern", "#/lantern/work", "#/company", "#/"])
        self.assertTrue(go[4]["back"])
        self.assertEqual(go[5], {"unknown": "Narnia"})
        self.assertIsNone(go[6])

    def test_being_put_through(self):
        self.assertEqual(self.r["through"], ["tide", "lantern", "lantern", "tide", "tide", None, None])
        self.assertEqual(self.r["throughThen"], "how's Tidepool doing?")

    def test_allowing_by_voice_takes_two_steps(self):
        r = self.r
        self.assertIn('"Why the bookmark jumps" on Lantern wants your permission to run npm test. Read it first:', r["v1"]["reply"])
        self.assertIn('Say "allow" to let it, once, or "deny". One more waits after it.', r["v1"]["reply"])
        self.assertNotIn("act", r["v1"])
        self.assertEqual((r["v2"]["act"]["id"], r["v2"]["act"]["behavior"]), ("a1", "allow"))
        self.assertNotIn("act", r["v3"])  # answered: the next "allow" starts again with a read-back

    def test_private_things_never_by_voice(self):
        r = self.r
        for v in (r["privateFirst"], r["privateAgain"]):
            self.assertIn("so I won't answer it by voice", v["reply"])
            self.assertNotIn("act", v)
            self.assertEqual(v["show"]["ask"]["id"], "a2")

    def test_switched_off_nothing_waiting_and_other_words(self):
        r = self.r
        self.assertEqual(r["off"]["reply"], "Answering by voice is switched off. Answer it on the screen.")
        self.assertIn("Say \"allow\"", r["offTyped"]["reply"])  # typed, it still reads it back
        self.assertEqual(r["none"]["reply"], "Nothing is waiting for your permission.")
        self.assertIsNone(r["unrelated"])
        self.assertIsNone(r["bareNo"])  # a bare "no" with nothing read back is for whoever asked a question
        self.assertEqual(r["yes"]["reply"], 'Say "allow" to let it, or "deny".')  # never a stray yes
        self.assertEqual(r["deny"]["act"]["behavior"], "deny")
        self.assertNotIn("act", r["late"])  # a minute on, it reads it back again
        self.assertNotIn("act", r["gone"])  # the one read back has gone: the new one is read back first


DESK = r"""
import { pathToFileURL } from 'node:url';
const { createLeadDesk } = await import(pathToFileURL(process.argv[1] + '/src/lead-desk.js').href);
const said = [], halted = [], answered = [];
const floor = { id: 'lantern', label: 'Lantern', project: 'Lantern', lead: { name: 'Juno' } };
const tide = { id: 'tide', label: 'Tidepool', project: 'Tidepool' };
const ask = { kind: 'permission', key: 'cc-a1', title: 'Bookmark', project: 'Lantern', what: 'to run npm test', tool: 'Bash', ask: { id: 'q1', what: 'Bash: to run npm test' } };
const agents = { Lantern: [{ id: 'cc-a1', title: 'Bookmark', working: true }], Tidepool: [{ id: 'cc-t1', title: 'Tides', working: true }] };
const control = { on: true, say: async (id, t) => { said.push([id, t]); return {}; }, halt: async (id) => { halted.push(id); }, projects: () => ['Lantern', 'Tidepool'] };
const desk = createLeadDesk({
  company: 'X', floors: () => [floor, tide], label: (p) => p,
  view: (f) => ({ label: f.label, conversations: agents[f.project], waiting: f.project === 'Lantern' ? [ask] : [] }),
  agents: (f) => agents[f.project], moments: () => [], waiting: () => [ask], canAnswer: () => true,
  answer: (act) => { answered.push(act.behavior); return 'answered'; }, show: () => {},
  control, places: () => [], go: () => {}, back: () => {}, walking: () => true, features: { get: () => true },
  madeUp: () => false, notConnected: () => 'off',
});
const talk = async (t, f = floor) => { const r = desk.says(f, t, { spoken: true }); return r?.then ? await r : r; };
const out = {};
for (const t of ['allow', 'tell them to merge it', 'cancel', 'ok']) await talk(t);
out.cancelled = { said: said.length, answered: answered.length };
for (const t of ['allow', 'stop them', 'no']) await talk(t);
out.no = { halted: halted.length, answered: answered.length };
for (const t of ['allow', 'stop them', 'yes']) await talk(t);
out.yes = { halted: [...halted], answered: answered.length };
for (const t of ['allow', 'allow']) await talk(t);
out.allowed = [...answered];
await talk('tell them to test it on the spare laptop');
await talk('tell them to check the tides', tide);
out.sent = said;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class LeadDeskTest(unittest.TestCase):
    """A lead at work (src/lead-desk.js): only the last question waits for your word, and instructions reach
    only that floor's own agents."""

    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, "--input-type=module", "-e", DESK, ROOT], capture_output=True, text=True, timeout=60)
        if out.returncode:
            raise AssertionError(out.stderr)
        cls.r = json.loads(out.stdout)

    def test_a_new_question_ends_the_one_before(self):
        # "allow" reads a request back, then an instruction is read back: "cancel" cancels the instruction,
        # and a later "ok" sends nothing and answers nothing
        self.assertEqual(self.r["cancelled"], {"said": 0, "answered": 0})
        # "allow", then "stop them": "no" and "yes" answer the stop, never the request
        self.assertEqual(self.r["no"], {"halted": 0, "answered": 0})
        self.assertEqual(self.r["yes"], {"halted": ["cc-a1"], "answered": 0})
        self.assertEqual(self.r["allowed"], ["allow"])  # and two "allow"s in a row still answer it

    def test_each_lead_reaches_only_their_own_floor(self):
        self.assertEqual(self.r["sent"], [["cc-a1", "Test it on the spare laptop."], ["cc-t1", "Check the tides."]])


if __name__ == "__main__":
    unittest.main()
