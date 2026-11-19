"""The page's first minutes and small helps (src/welcome.js, src/tour.js, src/alerts.js): Connect my agents' choices,
the card that waits for your first agent, the "Answering here" light, the first tour's steps and where its card goes,
desktop alerts (never twice, never for what was already waiting, said in words when the browser can't), and the
newer-Arnheim notice. Run under Node, skipped where Node isn't there; the page's own wiring is checked by reading it.

Run from the repository's folder: python3 -m unittest discover tests
"""
import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")

SCRIPT = """
import { pathToFileURL } from 'node:url';
const src = (name) => import(pathToFileURL(process.argv[1] + '/src/' + name).href);
const w = await src('welcome.js');
const t = await src('tour.js');
const a = await src('alerts.js');
const out = {};

// Connect my agents
const plan = { projects: [{ folder: '~/code/alpha', label: 'Alpha' }, { folder: '~/code/beta', label: 'Beta' }], claude: true };
const flow = w.connectStart(plan);
out.ticked = [...flow.ticked];
out.control = flow.control;
flow.ticked.delete('~/code/alpha');
flow.ticked.add('~/code/alpha'); // ticked again: still sent in the order found
flow.ticked.delete('~/code/beta');
flow.typed = '  ~/work/gamma ';
out.request = w.connectRequest(flow);
flow.control = false;
out.requestNo = w.connectRequest(flow);
out.empty = w.connectStart({}).plan.projects;
out.codex = [w.codexLine(null), w.codexLine({ here: true, version: '0.130', hooks: true }), w.codexLine({ here: true, version: '0.110', hooks: false })];

// The first moment
const c1 = { id: 'cc-a', title: 'Fix the login', project: 'Alpha', at: 100 };
const c2 = { id: 'cc-b', title: 'Tidy the tests', project: 'Alpha', at: 200 };
out.first = [
  w.firstMoment({ seen: false, waiting: false, conversations: [] }),
  w.firstMoment({ seen: false, waiting: true, conversations: [c1, c2] }),
  w.firstMoment({ seen: false, waiting: false, conversations: [c1] }),
  w.firstMoment({ seen: true, waiting: false, conversations: [] }),
];
out.folders = w.floorFolders({ floors: [{ id: 'a', label: 'Alpha', folder: '~/code/alpha' }, { id: 'b', label: 'Beta', folders: ['~/code/beta', '~/code/alpha'] }, { id: 'c', label: 'Gamma' }] });

// The light
out.light = [w.answeringWords(false, true), w.answeringWords(true, true), w.answeringWords(true, false)];
out.update = [w.updateLine(1), w.updateLine(12)];

// The tour
out.steps = t.STEPS;
out.wanted = [t.tourWanted({}), t.tourWanted({ seen: true }), t.tourWanted({ embedded: true }), t.tourWanted({ away: true }), t.tourWanted({ walking: true })];
const card = { width: 340, height: 180 };
const view = { width: 1280, height: 800 };
out.place = {
  narrow: t.placeCard({ top: 10, left: 300, bottom: 40, right: 360 }, card, { width: 375, height: 812 }),
  below: t.placeCard({ top: 10, left: 1200, bottom: 44, right: 1260 }, card, view),
  above: t.placeCard({ top: 700, left: 100, bottom: 740, right: 160 }, card, view),
  inside: t.placeCard({ top: 50, left: 0, bottom: 800, right: 840 }, card, view),
  none: t.placeCard(null, card, view),
};

// Desktop alerts
const known = new Set();
const items = [
  { kind: 'permission', id: 'ask:1', title: 'Fix the login', what: 'to run npm test', project: 'Alpha' },
  { kind: 'question', id: 'talk:cc-b', title: 'Tidy the tests', what: 'Should the old ones go too?', project: 'Alpha' },
  { kind: 'turn', id: 'turn:cc-c', title: 'Done thing', what: 'Finished.' },
  { kind: 'task', id: 'task:t1', title: 'Pay the bill' },
];
out.loaded = a.freshAlerts(items, known).map((i) => i.id);
out.again = a.freshAlerts(items, known).map((i) => i.id);
out.later = a.freshAlerts([...items, { kind: 'permission', id: 'ask:2', title: 'X', what: 'to read a.md' }], known).map((i) => i.id);
out.alertOf = [a.alertOf(items[0], 'Alpha'), a.alertOf(items[1], ''), a.alertOf({ kind: 'question', id: 'q', title: 'Long', what: 'word '.repeat(60) }, 'Beta')];

class Store { constructor() { this.m = new Map(); } getItem(k) { return this.m.has(k) ? this.m.get(k) : null; } setItem(k, v) { this.m.set(k, String(v)); } }
const shown = [];
const make = (permission, answer) => {
  class N {
    constructor(title, options) { this.title = title; this.options = options; this.closed = false; shown.push(this); }
    close() { this.closed = true; }
    static requestPermission() { N.permission = answer; return Promise.resolve(answer); }
  }
  N.permission = permission;
  return N;
};
const focused = [];
const win = (N) => ({ Notification: N, focus: () => focused.push(1) });
const said = {};
const none = a.createAlerts({ win: {}, storage: new Store() });
said.none = [none.state(), await none.set(true), none.on()];
const blocked = a.createAlerts({ win: win(make('denied', 'denied')), storage: new Store() });
said.denied = [blocked.state(), await blocked.set(true), blocked.on()];
const refused = a.createAlerts({ win: win(make('default', 'default')), storage: new Store() });
said.refused = [await refused.set(true), refused.on()];
const store = new Store();
const yes = a.createAlerts({ win: win(make('default', 'granted')), storage: store });
said.offBefore = [yes.on(), yes.show(items[0], 'Alpha')];
said.granted = [await yes.set(true), yes.on(), store.getItem('arnheim-alerts')];
let opened = 0;
said.show = yes.show(items[0], 'Alpha', () => { opened += 1; });
const n = shown[shown.length - 1];
said.notification = { title: n.title, body: n.options.body, tag: n.options.tag };
n.onclick();
said.clicked = [opened, focused.length, n.closed];
said.remembered = a.createAlerts({ win: win(make('granted', 'granted')), storage: store }).on();
said.off = [await yes.set(false), yes.on(), store.getItem('arnheim-alerts')];
class Broken { static permission = 'granted'; constructor() { throw new TypeError('Illegal constructor'); } }
const phone = a.createAlerts({ win: win(Broken), storage: new Store() });
await phone.set(true);
said.phone = [phone.show(items[0], 'Alpha'), phone.on()];
out.said = said;
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT], capture_output=True, text=True, timeout=60)
        if done.returncode:
            raise AssertionError(done.stderr)
        cls.r = json.loads(done.stdout)

    def test_connect_my_agents(self):
        r = self.r
        self.assertEqual(r["ticked"], ["~/code/alpha", "~/code/beta"])  # every project found, ticked
        self.assertTrue(r["control"])  # yes by default
        self.assertEqual(r["request"], {"folders": ["~/code/alpha"], "typed": "~/work/gamma", "control": True})
        self.assertFalse(r["requestNo"]["control"])
        self.assertEqual(r["empty"], [])
        self.assertEqual(r["codex"][0], "Codex: not found on this computer.")
        self.assertIn("(0.130). Its hooks are added too", r["codex"][1])
        self.assertIn("type /hooks in Codex", r["codex"][1])
        self.assertEqual(r["codex"][2], "Codex: found (0.110).")

    def test_the_first_moment(self):
        waiting, arrived, already, seen = self.r["first"]
        self.assertEqual(waiting, {"waiting": True, "arrived": None, "seen": False})
        self.assertEqual(arrived["arrived"]["id"], "cc-b")  # the newest, while the card showed: said once
        self.assertFalse(arrived["waiting"])
        self.assertEqual(already, {"waiting": False, "arrived": None, "seen": True})  # there when the page opened: no note
        self.assertEqual(seen, {"waiting": False, "arrived": None, "seen": True})  # seen before: never the card again
        self.assertEqual(self.r["folders"], [{"floor": "Alpha", "folder": "~/code/alpha"}, {"floor": "Beta", "folder": "~/code/beta"}])

    def test_the_answering_light(self):
        off, here, away = self.r["light"]
        self.assertIsNone(off)  # control off: no light at all
        self.assertEqual((here["here"], here["text"]), (True, "Answering here"))
        self.assertEqual((away["here"], away["text"]), (False, "Agents ask in their windows"))
        self.assertIn("Touch the page", away["why"])
        self.assertIn("two minutes", here["why"])

    def test_the_update_notice(self):
        self.assertEqual(self.r["update"], ["A newer Arnheim is out (1 change).", "A newer Arnheim is out (12 changes)."])

    def test_the_tour(self):
        steps = self.r["steps"]
        self.assertEqual(len(steps), 3)
        self.assertEqual([s["target"][0] for s in steps], ["#stage", "#tab-overview", "#walk"])
        with open(os.path.join(ROOT, "index.html"), encoding="utf-8") as handle:
            page = handle.read()
        for step in steps:  # each points at a real part of the page
            for target in step["target"]:
                self.assertIn(f'id="{target[1:]}"', page, target)
        self.assertIn("project", steps[0]["title"])
        self.assertIn("Amber", steps[1]["title"])
        self.assertIn("Needs you", steps[1]["text"])
        self.assertIn("Connect my agents", steps[2]["text"])  # the last step says where your own projects come from
        self.assertIn("Walk", steps[2]["title"])
        self.assertEqual(self.r["wanted"], [True, False, False, False, False])
        place = self.r["place"]
        self.assertEqual(place["narrow"], {"sheet": True})  # a phone's width: a sheet along the bottom
        self.assertEqual(place["below"], {"sheet": False, "top": 56, "left": 1280 - 340 - 8})  # under Walk, kept on screen
        self.assertEqual(place["above"], {"sheet": False, "top": 700 - 12 - 180, "left": 100})
        self.assertEqual(place["inside"], {"sheet": False, "top": 800 - 180 - 24, "left": 24})  # the building fills the screen
        self.assertEqual(place["none"]["sheet"], False)

    def test_desktop_alerts(self):
        r = self.r
        self.assertEqual(r["loaded"], ["ask:1", "talk:cc-b"])  # what needs you: permissions and questions only
        self.assertEqual(r["again"], [])  # never twice
        self.assertEqual(r["later"], ["ask:2"])
        first, second, long = r["alertOf"]
        self.assertEqual(first, {"title": "Alpha", "body": "Fix the login wants your permission to run npm test", "tag": "ask:1"})
        self.assertEqual(second["title"], "Arnheim")
        self.assertEqual(second["body"], "Tidy the tests asks: Should the old ones go too?")
        self.assertLessEqual(len(long["body"]), 120)
        self.assertTrue(long["body"].endswith("…"))
        said = r["said"]
        self.assertEqual(said["none"], ["none", "This browser can't show desktop alerts.", False])
        self.assertEqual(said["denied"][0], "denied")
        self.assertIn("blocks alerts from this page", said["denied"][1])
        self.assertIn("site settings", said["denied"][1])
        self.assertFalse(said["denied"][2])
        self.assertIn("wasn't allowed", said["refused"][0])
        self.assertFalse(said["refused"][1])
        self.assertEqual(said["offBefore"], [False, False])  # never before it is chosen
        self.assertIn("are on", said["granted"][0])
        self.assertEqual(said["granted"][1:], [True, "on"])
        self.assertTrue(said["show"])
        self.assertEqual(said["notification"], {"title": "Alpha", "body": "Fix the login wants your permission to run npm test", "tag": "ask:1"})
        self.assertEqual(said["clicked"], [1, 1, True])  # brought forward, opened, closed
        self.assertTrue(said["remembered"])  # this browser keeps the choice
        self.assertEqual(said["off"][1:], [False, "off"])
        self.assertEqual(said["phone"], [False, False])  # a browser that can't show them from a page: off, not broken


class WiringTest(unittest.TestCase):
    """The page's own wiring, read from demo.js and control.js."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ROOT, "src", "demo.js"), encoding="utf-8") as handle:
            cls.page = handle.read()
        with open(os.path.join(ROOT, "src", "control.js"), encoding="utf-8") as handle:
            cls.control = handle.read()

    def test_keys_meant_for_the_tour_never_answer(self):
        guard = self.page.index("if (tour.isOpen) return;")
        self.assertLess(guard, self.page.index("answerOnce(i, key === 'a' ? 'allow' : 'deny');"))

    def test_alerts_only_for_your_own_company_and_never_for_what_was_there(self):
        self.assertIn("const ownCompany = () => dir === 'data' && !madeUp();", self.page)
        check = self.page[self.page.index("function checkAlerts()"):]
        check = check[:check.index("\n}\n")]
        self.assertIn("if (!ownCompany()) return;", check)
        self.assertIn("if (!alertKnown) { alertKnown = new Set(); freshAlerts(items, alertKnown); return; }", check)
        self.assertIn("(!document.hidden && document.hasFocus())", check)
        self.assertIn("if (document.hidden && !alerts.on()) return;", self.page)  # it keeps reading in the background only for alerts

    def test_control_js_gains_using_and_keeps_the_rest(self):
        self.assertIn("    using,\n", self.control)
        self.assertIn("const using = () => { try { return !!busy() || Date.now() - touched < 120000; } catch { return false; } };", self.control)

    def test_connect_and_update_only_on_this_computer(self):
        self.assertIn("if (!fromAway() && !setupAsked)", self.page)
        self.assertIn("if (fromAway() || !updateState", self.page)
        self.assertIn("'X-Arnheim-Switches': setupHere?.token || ''", self.page)

    @unittest.skipUnless(NODE, "Node.js isn't installed")
    def test_the_page_parses_as_a_module(self):
        # one name declared twice, say, stops the whole page before it draws anything: only a browser's missing
        # globals (window, location) may stop it under Node
        script = ("import { pathToFileURL } from 'node:url';"
                  "import(pathToFileURL(process.argv[1] + '/src/demo.js').href).then(() => console.log('ran'), (e) => console.log(e.name));")
        done = subprocess.run([NODE, "--input-type=module", "-e", script, ROOT], capture_output=True, text=True, timeout=60)
        self.assertNotIn("SyntaxError", done.stdout + done.stderr)

    def test_words_people_read(self):
        for name in ("welcome.js", "tour.js", "alerts.js"):
            with open(os.path.join(ROOT, "src", name), encoding="utf-8") as handle:
                text = handle.read()
            self.assertNotIn("—", text, name)  # no long dashes
            for said in re.findall(r"'([^'\n]{12,})'|`([^`\n]{12,})`", text):
                words = re.sub(r"\$\{[^}]*\}", "", "".join(said))  # the words, not the code inside them
                self.assertNotIn(" - ", words, name)


if __name__ == "__main__":
    unittest.main()
