"""A morning briefing out loud (src/morning.js): the first time the page opens each day, once today's plan is made, the
receptionist says what the night shift finished and what is proven, then the plan floor by floor, and asks "Approve the
day?". "Yes" approves it, "change ..." changes it and asks again, "not now" leaves it. Out loud only while the voice is
on and the browser lets the page make sound; otherwise the same words are a card at the top of Needs you. Once a day on
each device, kept in the browser, and once a page load where nothing can be kept. The made-up company's morning says it
is made up. The words and the flow run under Node, with the made-up company's own day and night.

Run from the repository's folder: python3 -m unittest discover tests
"""
import json
import os
import re
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connect"))

import switches  # noqa: E402  (after the path is set)

NODE = shutil.which("node")

PAGE = r"""
import { pathToFileURL } from 'node:url';
import fs from 'node:fs';
const root = process.argv[1];
const m = await import(pathToFileURL(root + '/src/morning.js').href);
const n = await import(pathToFileURL(root + '/src/night.js').href);
const d = await import(pathToFileURL(root + '/src/day.js').href);
const at = (h, min = 0, date = 21) => new Date(2026, 10, date, h, min).getTime() / 1000;
const rawDay = JSON.parse(fs.readFileSync(root + '/sample/day.json', 'utf8'));
const rawNight = JSON.parse(fs.readFileSync(root + '/sample/night.json', 'utf8'));
const T = at(10);
const day = d.sampleDay(rawDay, T);
const night = n.sampleNight(rawNight, T);
const out = {};

// the words
const parts = m.morningParts({ day, night, now: T });
out.words = m.sayMorning(parts);
out.floors = parts.floors;
out.ask = parts.ask;
out.approvedWords = m.sayMorning(m.morningParts({ day: d.sampleApprove(day), night, now: T }));
out.noNight = m.sayMorning(m.morningParts({ day: { ...day, night: null }, night: null, now: T }));
out.nightOnly = m.sayMorning(m.morningParts({ day: null, night, now: T }));
out.oldNight = m.nightSaid({ ...night, report: { ...night.report, night: '2026-11-01' } }, null, T);
out.ownNight = m.nightSaid({ report: { night: '2026-11-20', at: at(7), words: 'Nothing ran overnight.', items: [] } }, null, T);
out.hello = [at(8), at(14), at(19), at(2)].map(m.helloOf);

// when it is due
const due = (o) => m.morningDue({ day, night, now: T, ...o });
out.due = {
  now: due({}), before: due({ now: at(8, 59) }), afterClose: due({ now: at(18, 0) }), givenToday: due({ given: '2026-11-21' }),
  givenYesterday: due({ given: '2026-11-20' }), off: due({ on: false }), notRead: due({ on: undefined }), unknown: due({ known: false }),
  notMade: due({ day: { ...day, made: null } }), otherDay: due({ day: { ...day, date: '2026-11-20' } }),
  empty: due({ day: { ...day, plan: [], night: null }, night: null }), emptyWithNight: due({ day: { ...day, plan: [] } }),
  nightOnly: due({ day: null }), nightSeen: due({ day: null, night: { ...night, report: { ...night.report, seen: true } } }),
  nightOld: due({ day: null, night: { ...night, report: { ...night.report, night: '2026-11-01' } } }),
  nightQuiet: due({ day: null, night: { ...night, quiet_now: true } }), nothing: due({ day: null, night: null }),
};

// your answer
const plan = day.plan;
out.answers = ['yes', 'Yes please.', 'yeah, go ahead', 'approve the day', 'OK, approve it', 'sounds good', 'not now', 'Later',
  'no thanks', 'leave it', 'change: drop the second one on Lantern', 'Change it, add: tidy the README on Studio', 'change',
  'I want to change something', 'drop the second one on Lantern', 'no, drop the second one on Lantern', "approve Lantern's plan",
  "what's the weather like", 'how did the night go?', ''].map((t) => m.morningAnswer(t, plan));
// a bare okay, fine or sure is as often said to something else: never a yes to the day
out.notYes = ['okay', 'OK.', 'ok thanks', 'fine', 'Fine!', 'sure', "that's fine", 'all good'].map((t) => m.morningAnswer(t, plan));

// the flow, with a stand-in page: a store that is kept between "page loads", the day changed as the plan card does
function page({ speakable = false, ready = false, store = null, time = T, speaks = true, sw = null } = {}) {
  const kept = store || new Map();
  const storage = store === 'broken' ? { getItem() { throw new Error('no'); }, setItem() { throw new Error('no'); } }
    : { getItem: (k) => (kept.has(k) ? kept.get(k) : null), setItem: (k, v) => kept.set(k, String(v)) };
  const log = { spoke: [], approved: 0, changed: [], redraws: 0 };
  let today = d.sampleDay(rawDay, time);
  const env = {
    styled: false, storage, now: () => s.time, company: () => 'Fernhollow',
    day: () => today, night: () => night, known: () => true, switchOn: () => (s.sw === 'notRead' ? undefined : s.sw),
    approve: () => { log.approved += 1; today = d.sampleApprove(today); return 'Approved the day. The company is made up, so nothing starts.'; },
    change: (words) => { const got = d.sampleChange(today, null, words); today = got.day; log.changed.push(words); return got.said; },
    speakable: () => s.speakable, speak: (again) => { log.spoke.push(!!again); return s.speaks; },
    // 'notRead': the switches haven't been read yet
    voiceOn: () => true, ready: () => s.ready, changed: () => { log.redraws += 1; },
  };
  const s = { speakable, ready, speaks, time, sw, log, kept, morning: m.createMorning(env), today: () => today };
  return s;
}

// the voice off (or sound held back): the card, once
const a = page();
out.card = { first: a.morning.check(), again: a.morning.check(), kept: JSON.parse(a.kept.get('arnheim-morning:Fernhollow')),
  spoke: a.log.spoke.length, greeting: a.morning.greeting(), heardYes: a.morning.heard('yes'), redraws: a.log.redraws };
// opening the page again the same day: nothing; the next day: again
const a2 = page({ store: a.kept });
const a3 = page({ store: a.kept, time: at(10, 0, 22) });
out.reload = { sameDay: a2.morning.check(), nextDay: a3.morning.check() };
// a private window: once while the page is open
const b = page({ store: 'broken' });
out.privateWindow = [b.morning.check(), b.morning.check()];
// the switch off, or not read yet: nothing; Talk switched off: the card
out.switchOff = page({ sw: false }).morning.check();
out.switchNotRead = page({ sw: 'notRead' }).morning.check();
out.talkOff = page({ speakable: true, speaks: false }).morning.check();

// out loud: hello at once, the rest once her voice is ready, then "yes"
const c = page({ speakable: true });
const said = c.morning.check();
const greeting = c.morning.greeting();
const early = c.morning.unasked();
c.ready = true;
const rest = c.morning.unasked();
const twice = c.morning.unasked();
const yes = await c.morning.heard('yes');
out.outLoud = { said, spoke: c.log.spoke, greeting, early, rest, twice, yes, approved: c.log.approved, after: c.morning.heard('yes'),
  kept: JSON.parse(c.kept.get('arnheim-morning:Fernhollow')).how, dayApproved: c.today().approved, card: c.morning.home() };

// a voice that never gets ready: the words are shown anyway after half a minute
const w = page({ speakable: true });
w.morning.check();
w.time = T + 10;
const waited = w.morning.unasked();
w.time = T + 31;
out.neverReady = { waited, shown: w.morning.unasked() };

// her voice ready at once: the whole briefing is her greeting
const r = page({ speakable: true, ready: true });
r.morning.check();
out.readyGreeting = r.morning.greeting();

// change, then not now
const e = page({ speakable: true, ready: true });
e.morning.check();
e.morning.greeting();
const which = e.morning.heard('change');
const changed = await e.morning.heard('change: drop the second one on Lantern');
const later = await e.morning.heard('not now');
out.change = { which, changed, later, words: e.log.changed, approved: e.log.approved, stillAsking: e.morning.asking(),
  plan: e.morning.words(), kept: JSON.parse(e.kept.get('arnheim-morning:Fernhollow')).how };

// anything else ends the question, and is answered as usual
const f = page({ speakable: true, ready: true });
f.morning.check();
f.morning.greeting();
out.other = { heard: f.morning.heard("what's the weather like"), then: f.morning.heard('yes'), approved: f.log.approved };

// office hours' sitting opened while she asks (the page drops her question): a "yes" there is the sitting's, even
// one the sitting itself doesn't take, and never approves the day
const g = page({ speakable: true, ready: true });
g.morning.check();
g.morning.greeting();
const wasAsking = g.morning.asking();
g.morning.drop();
out.sitting = { wasAsking, asking: g.morning.asking(), yes: g.morning.heard('yes'), approved: g.log.approved, dayApproved: g.today().approved };

// "okay" while she asks: the question ends, nothing is approved, and the word is answered as usual
const k = page({ speakable: true, ready: true });
k.morning.check();
k.morning.greeting();
out.okay = { heard: k.morning.heard('okay'), then: k.morning.heard('yes'), approved: k.log.approved };

// the card's question says the same, and the plan approved elsewhere leaves it nothing to ask
out.sameWords = a.morning.words() === out.words;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class MorningTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run([NODE, "--input-type=module", "-e", PAGE, ROOT], capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            raise AssertionError(done.stderr)
        cls.got = json.loads(done.stdout)

    def test_the_words_say_the_night_then_the_plan_floor_by_floor_then_ask(self):
        words = self.got["words"]
        self.assertTrue(words.startswith("Good morning. This company is made up"), words)
        night = words.index("From the night shift: 4 things finished overnight, 3 proven, 1 not.")
        proven = words.index('Proven: "Tidy the field notes" on Tidepool')
        plan = words.index("Today's plan: 7 things on 4 floors.")
        floors = [words.index(f"{label}: ") for label in ("Studio", "Lantern", "Tidepool", "Kitefield")]
        self.assertLess(night, proven)
        self.assertLess(proven, plan)
        self.assertEqual(floors, sorted(floors))
        self.assertLess(plan, floors[0])
        self.assertTrue(words.endswith("Approve the day?"), words)
        self.assertEqual(len(self.got["floors"]), 4)
        self.assertTrue(self.got["ask"])

    def test_an_approved_plan_isnt_asked_again(self):
        self.assertIn("It's approved", self.got["approvedWords"])
        self.assertNotIn("Approve the day?", self.got["approvedWords"])

    def test_with_one_of_the_two_switched_off(self):
        self.assertNotIn("night shift", self.got["noNight"])
        self.assertIn("Approve the day?", self.got["noNight"])
        self.assertIn("4 things finished overnight", self.got["nightOnly"])
        self.assertNotIn("Today's plan", self.got["nightOnly"])
        self.assertNotIn("Approve the day?", self.got["nightOnly"])
        self.assertIsNone(self.got["oldNight"])  # a report from days ago isn't this morning's
        self.assertEqual(self.got["ownNight"], "From the night shift: nothing ran overnight.")
        self.assertEqual(self.got["hello"], ["Good morning", "Good afternoon", "Good evening", "Hello"])

    def test_when_it_is_due(self):
        due = self.got["due"]
        self.assertEqual(due["now"], "day")
        self.assertEqual(due["givenYesterday"], "day")
        for name in ("before", "afterClose", "givenToday", "off", "notRead", "unknown", "notMade", "otherDay", "empty",
                     "nightSeen", "nightOld", "nightQuiet", "nothing"):
            self.assertIsNone(due[name], name)
        self.assertEqual(due["emptyWithNight"], "day")
        self.assertEqual(due["nightOnly"], "night")

    def test_your_answer(self):
        kinds = [a and a["kind"] for a in self.got["answers"]]
        self.assertEqual(kinds, ["yes", "yes", "yes", "yes", "yes", "yes", "later", "later", "later", "later", "change", "change",
                                 "which", "which", "change", "change", None, None, None, None])
        answers = self.got["answers"]
        self.assertEqual(answers[10]["words"], "drop the second one on Lantern")
        self.assertEqual(answers[11]["words"], "add: tidy the README on Studio")
        self.assertEqual(answers[15]["words"], "drop the second one on Lantern")

    def test_the_card_when_it_isnt_said_out_loud_once_a_day(self):
        card = self.got["card"]
        self.assertEqual(card["first"], "shown")
        self.assertIsNone(card["again"])
        self.assertEqual(card["kept"], {"date": "2026-11-21", "how": "shown"})
        self.assertEqual(card["spoke"], 0)
        self.assertIsNone(card["greeting"])
        self.assertIsNone(card["heardYes"])  # she never asked, so a "yes" to her is answered as usual
        self.assertGreaterEqual(card["redraws"], 1)
        self.assertEqual(self.got["reload"], {"sameDay": None, "nextDay": "shown"})
        self.assertEqual(self.got["privateWindow"], ["shown", None])
        self.assertIsNone(self.got["switchOff"])
        self.assertIsNone(self.got["switchNotRead"])
        self.assertEqual(self.got["talkOff"], "shown")

    def test_out_loud_then_yes_approves(self):
        o = self.got["outLoud"]
        self.assertEqual(o["said"], "said")
        self.assertEqual(o["spoke"], [False])
        self.assertEqual(o["greeting"], "Good morning.")
        self.assertIsNone(o["early"])  # nothing more until her voice can be heard
        self.assertTrue(o["rest"].startswith("This company is made up"), o["rest"])
        self.assertTrue(o["rest"].endswith("Approve the day?"))
        self.assertIsNone(o["twice"])
        self.assertIn("Approved the day", o["yes"])
        self.assertEqual(o["approved"], 1)
        self.assertIsNone(o["after"])  # asked once: a second "yes" isn't another approval
        self.assertEqual(o["kept"], "done")
        self.assertTrue(o["dayApproved"])
        self.assertIsNone(o["card"])  # said out loud: no card as well
        self.assertIsNone(self.got["neverReady"]["waited"])
        self.assertTrue(self.got["neverReady"]["shown"].endswith("Approve the day?"))
        self.assertTrue(self.got["readyGreeting"].startswith("Good morning. This company is made up"))
        self.assertTrue(self.got["readyGreeting"].endswith("Approve the day?"))

    def test_change_asks_again_and_not_now_leaves_it(self):
        c = self.got["change"]
        self.assertTrue(c["which"].startswith("What should change?"), c["which"])
        self.assertIn("Dropped", c["changed"])
        self.assertTrue(c["changed"].endswith("Approve the day?"))
        self.assertEqual(c["words"], ["drop the second one on Lantern"])
        self.assertIn("it waits", c["later"])
        self.assertEqual(c["approved"], 0)
        self.assertFalse(c["stillAsking"])
        self.assertNotIn("Test the app on the spare laptop", c["plan"])  # the words follow the change
        self.assertEqual(c["kept"], "done")
        o = self.got["other"]
        self.assertIsNone(o["heard"])
        self.assertIsNone(o["then"])
        self.assertEqual(o["approved"], 0)

    def test_a_yes_in_the_sitting_never_approves_the_day(self):
        s = self.got["sitting"]
        self.assertTrue(s["wasAsking"])  # she had asked "Approve the day?"
        self.assertFalse(s["asking"])  # the sitting opened: her question stops waiting
        self.assertIsNone(s["yes"])
        self.assertEqual(s["approved"], 0)
        self.assertFalse(s["dayApproved"])

    def test_a_bare_okay_is_not_a_yes(self):
        self.assertEqual(self.got["notYes"], [None] * 8)
        o = self.got["okay"]
        self.assertIsNone(o["heard"])
        self.assertIsNone(o["then"])  # the question ended with it
        self.assertEqual(o["approved"], 0)

    def test_the_card_and_the_voice_say_the_same(self):
        self.assertTrue(self.got["sameWords"])

    def test_no_dashes_in_what_she_says(self):
        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for v in value.values():
                    yield from strings(v)
            elif isinstance(value, list):
                for v in value:
                    yield from strings(v)
        for text in strings(self.got):
            self.assertNotIn(chr(0x2014), text)
            self.assertNotIn(" - ", text)


# The receptionist's greeting and what she says unasked (src/demo.js's talk.greet and talk.speakUp), run as they are
# with stand-ins for the rest of the page: during office hours' sitting she never asks "Approve the day?" again, and
# when a lead's news takes the conversation, her question stops waiting.
DESK_TALK = r"""
import fs from 'node:fs';
const src = fs.readFileSync(process.argv[1] + '/src/demo.js', 'utf8');
const method = (name) => {
  const start = src.indexOf(`\n  ${name}(who) {`);
  const end = src.indexOf('\n  },\n', start);
  if (start < 0 || end < 0) throw new Error(`no ${name} in demo.js`);
  return src.slice(start, end + 4);
};
const calls = [];
let news = null;
const ctx = {
  DESK: '#/desk',
  sitting: { isOpen: false },
  morning: { greeting: () => { calls.push('greeting'); return 'Good morning. Approve the day?'; },
    unasked: () => { calls.push('unasked'); return null; }, drop: () => calls.push('drop') },
  leads: { floorOf: () => null, speakUp: () => news },
  standOf: () => null, isAide: () => false, talkItem: () => null, isConvo: () => false, primeBrain: () => {},
  briefTold: true, brain: { on: false }, control: { on: false },
};
const scope = new Proxy(ctx, {
  has: (t, k) => typeof k === 'string' && !(k in globalThis),
  get: (t, k) => (typeof k === 'symbol' ? undefined : k in t ? t[k] : () => null),
  set: (t, k, v) => { t[k] = v; return true; },
});
const talk = new Function('scope', `with (scope) { return ({${method('greet')},${method('speakUp')}}); }`)(scope);
const desk = { href: '#/desk' };
const out = {};
const run = (f) => { calls.length = 0; const said = f(); return { said, calls: [...calls] }; };
out.closedGreet = run(() => talk.greet(desk));
ctx.sitting.isOpen = true;
out.openGreet = run(() => talk.greet(desk));
out.openUnasked = run(() => talk.speakUp(desk));
ctx.sitting.isOpen = false;
out.quiet = run(() => talk.speakUp(desk));
news = "News from Lantern's lead. It's done.";
out.news = run(() => talk.speakUp(desk));
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class DeskDuringTheSittingTest(unittest.TestCase):
    def test_she_never_asks_again_during_the_sitting_and_news_ends_her_question(self):
        # Found by the Checker: walking up to her, or her voice coming ready, during the sitting gave the briefing again,
        # so "Approve the day?" waited for a "yes" meant for the sitting; and a lead's news said unasked left it waiting.
        done = subprocess.run([NODE, "--input-type=module", "-e", DESK_TALK, ROOT], capture_output=True, text=True, timeout=60)
        if done.returncode != 0:
            raise AssertionError(done.stderr)
        got = json.loads(done.stdout)
        self.assertEqual(got["closedGreet"], {"said": "Good morning. Approve the day?", "calls": ["greeting"]})
        self.assertNotIn("greeting", got["openGreet"]["calls"])  # the sitting is open: her plain hello
        self.assertNotIn("Approve the day?", got["openGreet"]["said"])
        self.assertEqual(got["openUnasked"]["calls"], [])
        self.assertEqual(got["quiet"], {"said": None, "calls": ["unasked"]})  # nothing to say: her question is left as it is
        self.assertEqual(got["news"], {"said": "News from Lantern's lead. It's done.", "calls": ["unasked", "drop"]})


class MorningPlaceTest(unittest.TestCase):
    """Its switch, its place on the page, its words for people, and its docs."""

    def read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as handle:
            return handle.read()

    def test_its_switch_is_on_unless_switched_off(self):
        self.assertIn("morning", switches.NAMES)
        row = next(s for s in switches.SWITCHES if s[0] == "morning")
        self.assertEqual(row[1], "page")
        self.assertTrue(switches.DEFAULTS["morning"])

    def test_the_page_uses_it(self):
        demo = self.read("src/demo.js")
        for needed in ("from './morning.js'", "morning.home()", "morning.heard(text)", "morning.greeting()", "morning.unasked()",
                       "morning.start()", "switchOn('morning')", "push('morning')"):
            self.assertIn(needed, demo, needed)
        # office hours' sitting: her question is dropped as it opens, and while it is open she never takes a "yes" as
        # approving the day (the sitting's own words come first, and one it doesn't take isn't hers either)
        opener = demo[demo.index("function openSitting()"):]
        opener = opener[:opener.index("\n}\n")]
        self.assertLess(opener.index("morning.drop()"), opener.index("sitting.open()"))
        self.assertIn("if (who.href === DESK && !sitting.isOpen) {", demo)
        self.assertLess(demo.index("if (sitting.isOpen) { const said = sitting.heard("), demo.index("morning.heard(text)"))
        # the card at the top of Needs you: before anything else that may wait there
        self.assertLess(demo.index("morning.home()"), demo.index("pausedCard(),"))

    def test_no_inline_styles_and_no_long_dashes(self):
        js = self.read("src/morning.js")
        self.assertIsNone(re.search(r"\bstyle\s*:", js))
        self.assertIn("morning.css", js)
        for rel in ("src/morning.js", "src/morning.css", "tests/test_morning.py"):
            self.assertNotIn(chr(0x2014), self.read(rel), rel)

    def test_its_docs(self):
        self.assertIn("A morning briefing out loud", self.read("docs/connect.md"))
        # opening the sitting ends her question; what stays on Needs you is today's plan (the card may never have shown)
        self.assertIn("Today's plan stays on Needs you until you answer it there.", self.read("docs/connect.md"))
        self.assertNotIn("The card on Needs you stays", self.read("docs/connect.md"))
        self.assertIn("A morning briefing out loud", self.read("README.md"))


if __name__ == "__main__":
    unittest.main()
