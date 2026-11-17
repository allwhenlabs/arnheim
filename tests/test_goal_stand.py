"""The flagpole in an empty Goals room (src/goal-stand.js): say or type the goal, hear it read back, and only a yes
sets it. Questions and greetings are never taken for a goal, a no sets nothing, and when saving fails it says so.

The flagpole's conversation is JavaScript, so this runs it under Node.js, and is skipped where Node isn't installed.
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
const m = await import(pathToFileURL(process.argv[1] + '/src/goal-stand.js').href);
const out = {};
const said = [
  'The goal is to ship the login page by Friday.',
  'our goal should be "a calmer onboarding"',
  'Set the goal to: one release a week',
  'ok, the goal is fewer crashes on tablets',
  'Make every page load in under a second',
  'What is a goal?',
  'what should it be',
  'Hello there',
  'yes',
  'no thanks',
  'Ship',
  'the goal is ok',
  'take me to the lobby',
  'back to the receptionist',
  'tell me about this room',
  'I am not sure',
  'the goal is',
  'Goal: ship it',
  'the goal is ship it?',
  'the goal is what?',
];
out.asked = Object.fromEntries(said.map((s) => [s, m.goalAsked(s)]));
out.long = m.goalAsked('the goal is ' + 'more '.repeat(60));
out.hrefs = {
  made: m.standHref('tide pool'),
  is: m.isStandHref(m.standHref('tide pool')),
  floor: m.standFloor(m.standHref('tide pool')),
  notGoal: m.isStandHref('#/tidepool/goals/3'),
  notNew: m.isStandHref('#/tidepool/code/new'),
  deeper: m.isStandHref('#/a/b/goals/new'),
};
const saved = [];
const stand = m.createGoalStand({ label: 'Tidepool', save: (goal) => { saved.push(goal); } });
const talk = [];
const say = async (text) => talk.push([text, await stand.answer(text)]);
talk.push(['(greet)', stand.greet()]);
await say('hi');
await say('yes');
await say('The goal is a calmer onboarding');
await say('hmm');
await say('no');
await say('yes');
await say('set the goal to fewer crashes on tablets');
await say('yes');
out.talk = talk;
out.saved = saved;
out.heldAfter = stand.held();
const failing = m.createGoalStand({ label: 'Lantern', save: () => Promise.reject(new Error('the list is busy')) });
const fail = [];
fail.push(await failing.answer('the goal is one release a week'));
fail.push(await failing.answer('yes'));
fail.push(await failing.answer('yes'));
out.fail = fail;
// changing your mind while a goal waits for its yes: the latest goal is the one read back, and only it is set
const fixed = [];
const fixing = m.createGoalStand({ label: 'Kitefield', save: (goal) => { fixed.push(goal); }, kept: 'It lasts while this tab is open.' });
const fix = [];
for (const text of ['the goal is A first try', 'ok, the goal is B second try', 'right, the goal is C third try', 'please set the goal to D fourth try',
  'no, the goal is E fifth try', 'set it to something else', 'sure thing', 'yes please']) fix.push(await fixing.answer(text));
out.fix = fix;
out.fixed = fixed;
const throwing = m.createGoalStand({ label: 'Lantern', save: () => { throw new Error('no room for it'); } });
await throwing.answer('the goal is one release a week');
out.thrown = await throwing.answer('sure');
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class GoalStandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT], capture_output=True, text=True, timeout=60)
        if out.returncode:
            raise AssertionError(out.stderr)
        cls.out = json.loads(out.stdout)

    def test_goals_said_plainly_or_with_the_usual_words(self):
        asked = self.out["asked"]
        self.assertEqual(asked["The goal is to ship the login page by Friday."], "Ship the login page by Friday")
        self.assertEqual(asked['our goal should be "a calmer onboarding"'], "A calmer onboarding")
        self.assertEqual(asked["Set the goal to: one release a week"], "One release a week")
        self.assertEqual(asked["ok, the goal is fewer crashes on tablets"], "Fewer crashes on tablets")
        self.assertEqual(asked["Make every page load in under a second"], "Make every page load in under a second")

    def test_questions_greetings_and_answers_are_not_goals(self):
        asked = self.out["asked"]
        for text in ["What is a goal?", "what should it be", "Hello there", "yes", "no thanks", "Ship", "the goal is ok",
                     "take me to the lobby", "back to the receptionist", "tell me about this room", "I am not sure",
                     "the goal is", "the goal is what?"]:
            self.assertIsNone(asked[text], text)
        self.assertEqual(asked["Goal: ship it"], "Ship it")
        self.assertEqual(asked["the goal is ship it?"], "Ship it")

    def test_changing_your_mind_sets_the_latest(self):
        fix = self.out["fix"]
        for said, letter in zip(fix[:5], "ABCDE"):
            self.assertIn(f'goal to "{letter} ', said)
            self.assertIn("Say yes, or no", said)
        self.assertIn('Say yes to set Kitefield\'s goal to "E fifth try"', fix[5])  # "set it to ..." is no yes
        self.assertIn('Say yes to set Kitefield\'s goal to "E fifth try"', fix[6])  # nor is "sure thing"
        self.assertEqual(fix[7], 'Done. Kitefield\'s goal is "E fifth try". It lasts while this tab is open.')
        self.assertEqual(self.out["fixed"], ["E fifth try"])

    def test_at_most_200_characters(self):
        self.assertEqual(len(self.out["long"]), 200)
        self.assertTrue(self.out["long"].startswith("More more"))

    def test_the_link_names_the_floor(self):
        hrefs = self.out["hrefs"]
        self.assertEqual(hrefs["made"], "#/tide%20pool/goals/new")
        self.assertTrue(hrefs["is"])
        self.assertEqual(hrefs["floor"], "tide pool")
        self.assertFalse(hrefs["notGoal"])
        self.assertFalse(hrefs["notNew"])
        self.assertFalse(hrefs["deeper"])

    def test_read_back_and_only_a_yes_sets_it(self):
        talk = dict(enumerate(self.out["talk"]))
        self.assertIn("No goal yet for Tidepool", talk[0][1])
        self.assertIn("What is the goal for Tidepool", talk[1][1])  # a greeting is no goal
        self.assertIn("What is the goal for Tidepool", talk[2][1])  # nor is a yes with nothing read back
        self.assertEqual(talk[3][1], 'Set Tidepool\'s goal to "A calmer onboarding"? Say yes, or no.')
        self.assertEqual(talk[4][1], 'Say yes to set Tidepool\'s goal to "A calmer onboarding", or no.')
        self.assertIn("not set", talk[5][1])
        self.assertIn("What is the goal for Tidepool", talk[6][1])  # the no let it go
        self.assertIn('"Fewer crashes on tablets"?', talk[7][1])
        self.assertEqual(talk[8][1], 'Done. Tidepool\'s goal is "Fewer crashes on tablets".')
        self.assertEqual(self.out["saved"], ["Fewer crashes on tablets"])
        self.assertIsNone(self.out["heldAfter"])

    def test_says_so_when_it_cannot_save(self):
        fail = self.out["fail"]
        self.assertIn("Say yes, or no", fail[0])
        self.assertIn("I couldn't set it: the list is busy", fail[1])
        self.assertIn("What is the goal for Lantern", fail[2])  # nothing is held after a failed try
        self.assertIn("I couldn't set it: no room for it", self.out["thrown"])


if __name__ == "__main__":
    unittest.main()
