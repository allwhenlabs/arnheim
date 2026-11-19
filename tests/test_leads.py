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
  moreTasks: L.leadUpdate({ label: 'Tidepool', conversations: [], waiting: [{ kind: 'task', title: 'Post the update', what: '' }],
    tasks: [{ status: 'needs_you' }, { status: 'open' }, { status: 'claude' }] }),
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
  through: ["how's Tidepool doing?", 'talk to Lantern\'s lead', 'put me through to Juno', 'Tidepool lead', 'what is new on Tidepool?', 'how are you?', 'tell me about Lantern and Tidepool status', "how's tide pool doing?"].map((t) => L.throughAsked(t, floors)?.floor.id ?? null),
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
// the round, and what came of what you asked
out.round = ['give me the round', 'the round.', 'morning round', 'do the rounds', "how's everything?", 'update on every project', 'check in with all the leads']
  .map(L.roundAsked);
out.notRound = ['do a round of tests', 'tell them to do a round of testing', 'how are the projects doing?', 'brief me', "what's new?"].map(L.roundAsked);
const P = { at: 1000, key: 'c1', title: 'Why the bookmark jumps', text: 'Test it on the spare laptop.', working: true };
const proved = (state) => ({ id: 'c1', title: 'Why the bookmark jumps', working: false, at: 1200, changed: 1100, proof: { state, check: 'The tests', at: 1150, until: 99999 } });
const fin = [{ key: 'c1', at: 1200, kind: 'finished', what: 'The bookmark stays put now.' }];
const rep = (ctx) => L.reportOf(P, { now: 1300, ...ctx });
out.reports = {
  waiting: rep({ conversations: [{ id: 'c1', working: false, at: 900 }] }),
  working: rep({ conversations: [{ id: 'c1', working: true, at: 900 }], moments: [{ key: 'c1', at: 1100, kind: 'changed', what: 'reader/bookmark.js' }] }),
  needs: rep({ waiting: [run] }),
  proven: rep({ conversations: [proved('passed')], moments: fin }),
  failed: rep({ conversations: [proved('failed')], moments: fin }),
  checking: rep({ conversations: [proved('checking')], moments: fin }),
  claimed: rep({ conversations: [{ ...proved('passed'), changed: 1180 }], moments: fin }),
  plain: rep({ conversations: [{ id: 'c1', working: false, at: 1200 }], moments: fin }),
  stopped: rep({ moments: [{ key: 'c1', at: 1200, kind: 'stopped' }] }),
  stuck: L.reportOf(P, { now: 1000 + L.STUCK_AFTER + 60, conversations: [{ id: 'c1', working: false, at: 900 }] }),
  idleAfter: rep({ conversations: [{ id: 'c1', working: false, at: 1250, says: { now: 'Tested on the spare laptop: it works.' } }] }),
  unread: L.reportOf({ ...P, working: false }, { now: 1000 + L.STUCK_AFTER + 60, conversations: [{ id: 'c1', working: false, at: 900 }] }),
};
out.roundLine = L.leadRoundLine({ label: 'Lantern', since: 50, now: 200, conversations: convos, waiting: [run],
  moments: [{ key: 'c2', at: 120, kind: 'finished', what: 'Ready.' }], reports: ['You asked the one on "Pictures" to crop them. It\'s done.'], reported: ['c9'] });
out.quietLine = L.leadRoundLine({ label: 'Kitefield', since: 50, now: 200, conversations: [], waiting: [], moments: [] });
out.atlas = ["how's that last change going?", 'what is the status of that last test?', "how's tide pool doing?", 'take me to what I had at last']
  .map((t) => L.throughAsked(t, [{ id: 'atlas', label: 'Atlas', project: 'Atlas' }, ...floors])?.floor.id ?? L.goAsked(t, [{ href: '#/atlas', label: 'Atlas', names: ['Atlas'] }])?.href ?? null);
out.more = ['tell me more about the login bug', 'explain in detail why the build failed', 'what are the details of that permission', 'tell me more', 'more detail please'].map((t) => L.leadAsked(t)?.kind ?? null);
out.askAll = ['tell them to ask all the leads', 'ask all the leads', 'give me an update on every project'].map((t) => L.roundAsked(t));
out.markupQuestion = L.reportOf(P, { now: 1300, waiting: [{ kind: 'question', key: 'c1', what: '<agent-message from="x">hi</agent-message>' }] }).line;
out.named = ['Tidepool', 'more on Tidepool', 'tell me more about Lantern', 'what about Juno?', "Tidepool's lead", 'take me to Tidepool', 'the Tidepool floor please', 'nice weather on Tidepool today', 'What about tide pool?']
  .map((t) => L.floorNamed(t, floors)?.id ?? null);
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
        # a task named as waiting on you isn't counted again: the rest are "more", so the numbers add up
        self.assertIn("Open: 2 more tasks.", self.r["moreTasks"])
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
        self.assertEqual(self.r["through"], ["tide", "lantern", "lantern", "tide", "tide", None, None, "tide"])
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

    def test_the_round_is_asked_for(self):
        self.assertEqual(self.r["round"], [True] * 7)
        self.assertEqual(self.r["notRound"], [False] * 5)  # a round of tests, and the health and news questions, stay theirs

    def test_what_came_of_what_you_asked(self):
        r = self.r["reports"]
        start = 'You asked the one on "Why the bookmark jumps" to test it on the spare laptop. '
        self.assertEqual({k: (v["state"], v["final"]) for k, v in r.items()}, {
            "waiting": ("waiting", False), "working": ("working", False), "needs": ("needs:a1", True),
            "proven": ("done:proven", True), "failed": ("done:failed", True), "checking": ("done:checking", True),
            "claimed": ("done:claimed", True), "plain": ("done:none", True), "stopped": ("stopped", True),
            "stuck": ("stuck", True), "unread": ("unread", False), "idleAfter": ("done:none", True)})
        self.assertEqual(r["proven"]["line"], start + "It's done, and proven: the tests passed after its last change.")
        self.assertEqual(r["failed"]["line"], start + "It says it's done, but it isn't proven: the tests failed.")
        self.assertEqual(r["checking"]["line"], start + "It's done. Running the tests on its work now.")
        self.assertEqual(r["claimed"]["line"], start + "It says it's done. It changed files after the tests last ran on them.")
        self.assertEqual(r["plain"]["line"], start + "It's done: The bookmark stays put now.")
        self.assertEqual(r["needs"]["line"], start + "It needs you: it wants your permission to run npm test.")
        self.assertEqual(r["stuck"]["line"], start + "No word back for 21 minutes, and it isn't working: it may be stuck.")
        self.assertEqual(r["working"]["line"], start + "It is on it, and changed reader/bookmark.js.")
        self.assertEqual(r["waiting"]["line"], start + "No word back yet.")
        # no moments from that day at hand: it worked after you asked and is idle now, so its turn is done
        self.assertEqual(r["idleAfter"]["line"], start + "It's done: Tested on the spare laptop: it works.")

    def test_a_line_each_in_the_round(self):
        line = self.r["roundLine"]
        self.assertEqual(line["text"], 'You asked the one on "Pictures" to crop them. It\'s done. "Pictures for the app store" finished, and one agent is at work. '
                         'One thing waits on you: "Why the bookmark jumps" wants your permission to run npm test.')
        self.assertEqual((line["quiet"], line["waits"]), (False, 1))
        self.assertEqual(self.r["quietLine"], {"text": "", "quiet": True, "waits": 0})

    def test_names_only_along_whole_words(self):
        # "that last" is never Atlas; "tide pool" is Tidepool
        self.assertEqual(self.r["atlas"], [None, None, "tide", None])

    def test_tell_me_more_alone_is_the_update(self):
        self.assertEqual(self.r["more"], [None, None, None, "update", "update"])  # with more after it, a real question

    def test_the_round_is_the_whole_of_what_was_said(self):
        self.assertEqual(self.r["askAll"], [False, True, True])

    def test_a_question_in_markup_is_never_read(self):
        self.assertNotIn("<", self.r["markupQuestion"])
        self.assertIn("It needs you: it asks you something, on the screen.", self.r["markupQuestion"])

    def test_a_floor_by_its_name(self):
        # its name, its lead's name, "more on", "what about"; never "take me to" (that goes there), or a longer sentence
        self.assertEqual(self.r["named"], ["tide", "tide", "lantern", "lantern", "tide", None, "tide", None, "tide"])  # "tide pool", as speech recognition wrote it

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


ROUND = r"""
import { pathToFileURL } from 'node:url';
const { createLeadDesk } = await import(pathToFileURL(process.argv[1] + '/src/lead-desk.js').href);
const real = Date.now;
let skew = 0;
Date.now = () => real() + skew; // time passing, for "it may be stuck"
const t0 = () => Date.now() / 1000;
const said = [];
const floors = [
  { id: 'lantern', label: 'Lantern', project: 'Lantern', lead: { name: 'Juno' } },
  { id: 'tide', label: 'Tidepool', project: 'Tidepool' },
  { id: 'kite', label: 'Kitefield', project: 'Kitefield' },
];
const [lantern, tide, kite] = floors;
const convos = {
  Lantern: [{ id: 'c1', title: 'Bookmark', working: true, at: t0() - 60 }],
  Tidepool: [{ id: 't1', title: 'Tides', working: true, at: t0() - 60 }],
  Kitefield: [],
};
const moments = [];
let waiting = [];
const switches = { reports: true };
const desk = createLeadDesk({
  company: 'X', floors: () => floors, label: (p) => p,
  view: (f) => ({ label: f.label, conversations: convos[f.project], waiting: waiting.filter((i) => i.project === f.project) }),
  agents: (f) => convos[f.project].map((c) => ({ id: c.id, title: c.title, working: c.working })),
  moments: (f) => moments.filter((m) => m.project === f.project), waiting: () => waiting, canAnswer: () => true,
  answer: () => 'answered', show: () => {},
  control: { on: true, say: async (id, t) => { said.push([id, t]); return {}; }, halt: async () => {}, projects: () => floors.map((f) => ({ label: f.label, project: f.project })) },
  places: () => [], go: () => {}, back: () => {}, walking: () => false, features: { get: (id) => switches[id] !== false },
  madeUp: () => false, notConnected: () => 'off',
});
const talk = async (f, t) => { const r = desk.says(f, t, { spoken: true }); return r?.then ? await r : r; };
const out = {};
await talk(lantern, 'tell them to fix the header');
out.sent = said.slice();
out.tooSoon = desk.speakUp(lantern);
// it finishes, and its checks are still running
const c1 = convos.Lantern[0];
Object.assign(c1, { working: false, at: t0(), changed: t0() - 5, proof: { state: 'checking', check: 'The tests', at: t0() - 1, until: t0() + 600 } });
moments.push({ key: 'c1', project: 'Lantern', at: t0() + 1, kind: 'finished', what: 'The login works again.' });
skew += 2000;
out.done = desk.speakUp(lantern);
out.onlyOnce = desk.speakUp(lantern);
c1.proof = { state: 'passed', check: 'The tests', at: t0() - 1 };
out.proven = desk.speakUp(lantern);
// on Tidepool, an instruction to an agent that then stops working, and nothing comes back
await talk(tide, 'tell them to check the tides');
convos.Tidepool[0].working = false;
skew += 21 * 60 * 1000;
out.desk = desk.speakUp(null);
out.deskAgain = desk.speakUp(null);
// the round: Lantern has something waiting on you, Tidepool has news, Kitefield is quiet
waiting = [{ kind: 'permission', id: 'ask:q1', key: 'c1', title: 'Bookmark', project: 'Lantern', what: 'to run npm test', tool: 'Bash', ask: { id: 'q1', what: 'Bash: to run npm test' } }];
moments.push({ key: 't1', project: 'Tidepool', at: t0() - 30, kind: 'finished', what: 'Tide tables done.' });
const r = desk.round('give me the round');
out.round = r.turns.map((x) => [x.who?.title ?? null, x.text]);
// cut in after the first lead: the second lead's news was never heard, so it is still to tell
r.turns[1].heard?.();
out.unheard = desk.speakUp(tide);
r.turns.forEach((x) => x.heard?.());
out.notRound = desk.round('how are the projects doing?');
out.fromALead = (await talk(tide, 'do the rounds')).turns.length;
// put through by name, and the lead says where it stands
const deskWho = { href: '#/desk', title: 'Iris' };
out.through = ['more on Tidepool', 'Kitefield', 'what about Juno?'].map((t) => { const to = desk.through(deskWho, t, deskWho); return to && [to.who.title, to.then]; });
out.more = await talk(tide, 'more on Tidepool');
// switched off: nothing unasked, and the greeting keeps to where it stands
switches.reports = false;
waiting = [];
c1.working = true;
await talk(lantern, 'tell them to tidy the notes');
c1.working = false;
moments.push({ key: 'c1', project: 'Lantern', at: t0() + 5, kind: 'finished' });
skew += 10000;
out.off = desk.speakUp(lantern);
out.offGreet = desk.greet(lantern, desk.who(lantern));
switches.reports = true;
out.onGreet = desk.greet(lantern, desk.who(lantern));
// what the brain passed on is reported back too, but only to this floor's own agents
desk.remember(tide, { key: 't1', text: 'write the tide report' });
desk.remember(tide, { key: 'c1', text: 'not from this floor' });
desk.remember(null, { key: 't1', text: 'from the assistant' }); // the assistant's: to whichever floor's agent it went
desk.remember(null, { key: 'nobody', text: 'to no one here' });
out.remembered = desk.passed(tide).map((p) => p.text);
out.rememberedLantern = desk.passed(lantern).some((p) => p.text === 'to no one here');
// several at once: what needs you comes first, at most three are said, and the rest wait for the next time
moments.length = 0; waiting = [];
convos.Lantern = [1, 2, 3, 4].map((n) => ({ id: `m${n}`, title: `Job ${n}`, working: true, at: t0() - 60 }));
await talk(lantern, 'tell them to fix the footer'); await talk(lantern, 'all of them');
for (const c of convos.Lantern.slice(0, 3)) { c.working = false; moments.push({ key: c.id, project: 'Lantern', at: t0() + 1, kind: 'finished', what: `${c.title} is finished.` }); }
waiting = [{ kind: 'permission', id: 'ask:q4', key: 'm4', title: 'Job 4', project: 'Lantern', what: 'to delete the old logs', tool: 'Bash', ask: { id: 'q4', what: 'Bash: rm logs' } }];
skew += 5000;
out.firstThree = desk.speakUp(lantern);
out.thenTheRest = desk.speakUp(lantern);
out.thenNothing = desk.speakUp(lantern);
// four at once again: one needs you and three finish; "what's new?" tells the last three it lists, the greeting
// at most three, and whatever neither said is still told after
convos.Lantern = [1, 2, 3, 4].map((n) => ({ id: `n${n}`, title: `Task ${n}`, working: true, at: t0() - 60 }));
moments.length = 0; waiting = [];
await talk(lantern, 'tell them to tidy the docs'); await talk(lantern, 'all of them');
for (const c of convos.Lantern.slice(1)) { c.working = false; moments.push({ key: c.id, project: 'Lantern', at: t0() + 1, kind: 'finished', what: `${c.title} is tidy.` }); }
waiting = [{ kind: 'permission', id: 'ask:q9', key: 'n1', title: 'Task 1', project: 'Lantern', what: 'to delete the drafts', tool: 'Bash', ask: { id: 'q9', what: 'Bash: rm drafts' } }];
skew += 5000;
out.news = await talk(lantern, "what's new?");
out.afterNews = desk.speakUp(lantern);
convos.Lantern = [1, 2, 3, 4, 5].map((n) => ({ id: `g${n}`, title: `Chore ${n}`, working: true, at: t0() - 60 }));
moments.length = 0; waiting = [];
await talk(lantern, 'tell them to sweep up'); await talk(lantern, 'all of them');
for (const c of convos.Lantern) { c.working = false; moments.push({ key: c.id, project: 'Lantern', at: t0() + 1, kind: 'finished' }); }
skew += 5000;
out.greetFive = desk.greet(lantern, desk.who(lantern));
out.afterGreet = desk.speakUp(lantern);
// told done, then its conversation and moments are gone and a day passes: never a "stuck"
convos.Lantern = []; moments.length = 0; waiting = [];
skew += 30 * 3600 * 1000;
out.afterItEnded = desk.speakUp(lantern);
// markup a message brought in is never read out
convos.Tidepool = [{ id: 't2', title: 'Tide report', working: true, at: t0() - 60 }];
await talk(tide, 'tell them to write the report');
convos.Tidepool[0].working = false;
moments.push({ key: 't2', project: 'Tidepool', at: t0() + 1, kind: 'finished', what: '<task-notification><task-id>x</task-id> done</task-notification>' });
skew += 5000;
out.markup = desk.speakUp(tide);
// "how's everything?" to a lead is their own floor; "how's everything going on Tidepool?" is Tidepool's
out.leadEverything = await talk(tide, "how's everything going?");
out.leadEverythingOn = await talk(tide, "how's everything going on Tidepool?");
out.deskEverything = !!desk.round("how's everything?");
// a lone floor name only puts you through just after the round
skew += 5 * 60 * 1000;
out.bareLater = desk.through(deskWho, 'Tidepool', deskWho);
out.moreLater = desk.through(deskWho, 'more on Tidepool', deskWho)?.who.title;
floors.splice(0, 3, kite);
out.allQuiet = desk.round('give me the round');
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class RoundTest(unittest.TestCase):
    """The round, and leads reporting back (src/lead-desk.js): what came of what you asked is told without
    being asked, once, and again only when it changes; every lead gives a line in the round."""

    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, "--input-type=module", "-e", ROUND, ROOT], capture_output=True, text=True, timeout=60)
        if out.returncode:
            raise AssertionError(out.stderr)
        cls.r = json.loads(out.stdout)

    def test_a_lead_reports_back_once_and_again_when_it_changes(self):
        r = self.r
        self.assertEqual(r["sent"], [["c1", "Fix the header."]])
        self.assertIsNone(r["tooSoon"])  # no word back yet: nothing to say unasked
        self.assertEqual(r["done"], 'You asked the one on "Bookmark" to fix the header. It\'s done. Running the tests on its work now.')
        self.assertIsNone(r["onlyOnce"])
        self.assertEqual(r["proven"], 'You asked the one on "Bookmark" to fix the header. It\'s done, and proven: the tests passed after its last change.')

    def test_the_front_desk_says_whose_news_it_is(self):
        self.assertEqual(self.r["desk"], 'News from Tidepool\'s lead. You asked the one on "Tides" to check the tides. '
                         "No word back for 21 minutes, and it isn't working: it may be stuck.")
        self.assertIsNone(self.r["deskAgain"])

    def test_news_cut_off_in_the_round_is_told_again(self):
        self.assertEqual(self.r["unheard"], 'You asked the one on "Tides" to check the tides. It\'s done: Tide tables done.')

    def test_the_round(self):
        self.assertEqual(self.r["round"][0][0], None)  # whoever you are with starts it
        self.assertTrue(self.r["round"][0][1].startswith("Here's the round, since "), self.r["round"][0])
        # what you asked of "Bookmark" was told done and proven, so its new request is just something waiting on you
        self.assertEqual(self.r["round"][1], ["Juno, Lantern's lead", 'Lantern. "Bookmark" finished, proven. One thing waits on you: "Bookmark" wants your permission to run npm test.'])
        self.assertEqual(self.r["round"][2], ["Tidepool's lead", 'Tidepool. You asked the one on "Tides" to check the tides. It\'s done: Tide tables done.'])
        self.assertEqual(self.r["round"][3], [None, "Nothing new on Kitefield. Say a project's name to talk to its lead."])
        self.assertIsNone(self.r["notRound"])
        self.assertEqual(self.r["fromALead"], 4)  # any lead gives it too
        self.assertTrue(self.r["allQuiet"].startswith("Here's the round: all quiet. Nothing new on Kitefield since "), self.r["allQuiet"])

    def test_put_through_by_name(self):
        self.assertEqual(self.r["through"], [["Tidepool's lead", "more on Tidepool"], ["Kitefield's lead", "Kitefield"], ["Juno, Lantern's lead", "what about Juno?"]])
        self.assertTrue(self.r["more"].startswith("Nobody is working on Tidepool right now."), self.r["more"])

    def test_switched_off_a_lead_waits_to_be_asked(self):
        self.assertIsNone(self.r["off"])
        self.assertNotIn("tidy the notes", self.r["offGreet"])
        self.assertIn('You asked the one on "Bookmark" to tidy the notes. It\'s done, and proven', self.r["onGreet"])
        self.assertNotIn("fix the header", self.r["onGreet"])  # already told it was done and proven: not again

    def test_what_needs_you_first_and_nothing_swallowed(self):
        first = self.r["firstThree"]
        self.assertTrue(first.startswith('You asked the one on "Job 4" to fix the footer. It needs you: it wants your permission to delete the old logs.'), first)
        self.assertEqual(first.count("You asked"), 3)
        self.assertEqual(self.r["thenTheRest"].count("You asked"), 1)  # the fourth is told next, not lost
        self.assertIsNone(self.r["thenNothing"])

    def test_whats_new_and_hello_mark_only_what_they_say(self):
        self.assertNotIn("Task 1", self.r["news"])  # the last three it lists
        self.assertTrue(self.r["afterNews"].startswith('You asked the one on "Task 1" to tidy the docs. It needs you'), self.r["afterNews"])
        self.assertEqual(self.r["greetFive"].count("You asked"), 3)
        self.assertEqual(self.r["afterGreet"].count("You asked"), 2)

    def test_work_that_ended_is_never_called_stuck(self):
        self.assertIsNone(self.r["afterItEnded"])

    def test_markup_is_never_read_out(self):
        self.assertEqual(self.r["markup"], 'You asked the one on "Tide report" to write the report. It\'s done.')

    def test_hows_everything(self):
        self.assertIsInstance(self.r["leadEverything"], str)  # their own floor's update, not the round
        self.assertIsInstance(self.r["leadEverythingOn"], str)
        self.assertTrue(self.r["deskEverything"])

    def test_a_lone_name_only_just_after_the_round(self):
        self.assertIsNone(self.r["bareLater"])  # it may be the answer to "which floor?"
        self.assertEqual(self.r["moreLater"], "Tidepool's lead")

    def test_what_the_brain_passed_on_is_reported_too(self):
        self.assertEqual(self.r["remembered"], ["Check the tides.", "write the tide report", "from the assistant"])
        self.assertFalse(self.r["rememberedLantern"])


OLD = r"""
import { pathToFileURL } from 'node:url';
const kept = new Map();
globalThis.localStorage = { getItem: (k) => kept.get(k) ?? null, setItem: (k, v) => kept.set(k, String(v)) };
const now = Date.now() / 1000;
// kept by the version before reporting back: no "told", no "working"
kept.set('arnheim-passed:X', JSON.stringify([{ at: now - 3600, key: 'c1', title: 'Bookmark', text: 'Test it.', project: 'Lantern' }]));
const { createLeadDesk } = await import(pathToFileURL(process.argv[1] + '/src/lead-desk.js').href);
const floor = { id: 'lantern', label: 'Lantern', project: 'Lantern' };
const convos = [{ id: 'c1', title: 'Bookmark', working: false, at: now - 60 }];
const desk = createLeadDesk({
  company: 'X', floors: () => [floor], label: (p) => p, view: () => ({ label: 'Lantern', conversations: convos, waiting: [] }),
  agents: () => convos, moments: () => [], waiting: () => [], canAnswer: () => true, answer: () => '', show: () => {},
  control: { on: true }, places: () => [], go: () => {}, back: () => {}, walking: () => false, features: { get: () => true },
  madeUp: () => false, notConnected: () => 'off',
});
console.log(JSON.stringify({ unasked: desk.speakUp(floor), greet: desk.greet(floor, desk.who(floor)), asked: desk.says(floor, "what's new?") }));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class OldInstructionsTest(unittest.TestCase):
    """Instructions kept before reporting back was built are never told unasked, so nobody hears a pile of old
    news on the first visit; asked what's new, the lead still says what came of them."""

    def test_old_ones_wait_to_be_asked(self):
        out = subprocess.run([NODE, "--input-type=module", "-e", OLD, ROOT], capture_output=True, text=True, timeout=60)
        if out.returncode:
            raise AssertionError(out.stderr)
        r = json.loads(out.stdout)
        self.assertIsNone(r["unasked"])
        self.assertNotIn("You asked", r["greet"])
        self.assertIn('You asked the one on "Bookmark" to test it. It\'s done.', r["asked"])


if __name__ == "__main__":
    unittest.main()
