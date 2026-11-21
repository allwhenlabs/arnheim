"""Working beside your agents, the page's side (src/beside.js): what "hold on", "carry on", "walk me through it",
"looks good", "the second change" and "line 42" mean, picking a question's choice by what was said, how long things
have been going and how a message, a hold and a question stand, in words, a change's lines with their numbers, and the
reply that follows a message as it is taken and answered. Also that a question an agent waits on comes first on
Needs you (src/queue.js). The rules are JavaScript, so this test runs under Node.js, and is skipped where Node
isn't installed.
Run from the repository's folder: python3 -m unittest discover tests
"""
import json
import os
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which("node")
NOW = 1_800_000_000  # seconds

SCRIPT = """
import { pathToFileURL } from 'node:url';
const b = await import(pathToFileURL(process.argv[1] + '/src/beside.js').href);
const queue = await import(pathToFileURL(process.argv[1] + '/src/queue.js').href);
const NOW = Number(process.argv[2]);
const clock = (at) => `T${at - NOW}`;
const choices = (multi = false) => ({ kind: 'choices', questions: [{ question: 'Which colour for the button?', header: 'Colour',
  options: [{ label: 'Blue', description: 'As the brand' }, { label: 'Green', description: 'Stands out' }, { label: 'Dark grey' }], multiSelect: multi }] });
const hunks = [
  { file: 'src/login.js', start: 10, old_start: 10, added: 1, removed: 1, lines: [[' ', 'function login(user) {'], ['-', '  if (user = null) {'], ['+', '  if (user === null) {'], [' ', '    return false']] },
  { file: 'src/button.css', start: 3, old_start: 3, added: 2, removed: 0, lines: [[' ', '.button {'], ['+', '  colour: blue;'], ['+', '  padding: 4px;'], [' ', '}']] },
  { file: 'src/login.js', start: 40, old_start: 40, added: 0, removed: 1, lines: [[' ', '}'], ['-', 'console.log(user)']] },
  { file: 'notes.md', kind: 'whole', start: null, old_start: null, added: 2, removed: 0, lines: [['+', 'one'], ['+', 'two']] },
];

// replyFlow with a made-up clock: the message is taken at the second look and answered at the fourth
async function flow(sent, states, most = 60000) {
  let t = 0, look = 0;
  const noted = [];
  const said = [];
  for await (const piece of b.replyFlow({ sent, most, every: 1000, clock: () => t, sleep: async (ms) => { t += ms; },
    find: () => states[Math.min(look++, states.length - 1)], taken: (id, what) => noted.push(`${id}:${what}`) })) said.push(piece);
  return { said, noted };
}
const queued = { id: 'm1', state: 'queued' };
const taken = { id: 'm1', state: 'taken', taken_words: "I've read your note." };
const answered = { id: 'm1', state: 'answered', answer: 'Done: blue it is.' };

console.log(JSON.stringify({
  asked: ['hold on', 'Hold on a second', 'wait', 'Wait!', 'stop there', 'Stop right there please', 'hang on a moment', 'no, wait',
    'stop', 'Stop.', 'Wait, what are you doing?', 'hold on, use the helper instead',
    'carry on', 'OK carry on', 'you can carry on now', 'keep going', 'go ahead',
    'walk me through it', 'Can you walk me through your changes?', 'explain your changes', 'what did you change?', 'show me the changes',
    'looks good', 'That looks great to me, thanks', 'LGTM', 'ok ship it', 'looks good but change the colour', 'what looks good?', '']
    .map((t) => [t, b.besideAsked(t)]),
  points: ['the second change', 'the second change: use a helper', 'change 3, put it back', 'the last change', 'line 42',
    'line 12 in login.js please rename it', 'on line 7 of src/app.py: why?', 'the 2nd edit', 'the zeroth change', 'make the change', 'online 4']
    .map((t) => [t, b.pointAsked(t)]),
  picked: ['blue', 'Blue please', 'the green one', 'the first one', 'option 2', 'number three', 'the last one', 'dark grey', 'purple', 'option 9', 'I think green']
    .map((t) => [t, b.optionPicked(t, choices())]),
  pickedMulti: b.optionPicked('green', choices(true)),
  pickedTwoParts: b.optionPicked('blue', { kind: 'choices', questions: [choices().questions[0], { question: 'Where?', options: [{ label: 'Top' }] }] }),
  pickedPlain: b.optionPicked('blue', { kind: 'text', text: 'Blue or green?' }),
  said: [b.questionSaid(choices()), b.questionSaid(choices(true)), b.questionSaid({ kind: 'text', text: 'Should I keep the old login' }),
    b.questionSaid({ kind: 'choices', questions: [choices().questions[0], { question: 'Where?', options: [{ label: 'Top' }] }] }), b.questionSaid(null)],
  wait: [b.questionWait({ state: 'waiting', until: NOW + 84 }, NOW), b.questionWait({ state: 'waiting', until: NOW + 300 }, NOW),
    b.questionWait({ state: 'waiting', until: NOW - 1 }, NOW), b.questionWait({ state: 'window' }, NOW), b.questionWait({ state: 'open' }, NOW)],
  forWords: [0, 4, 5, 40, 60, 119, 120, 3599, 3600, 3900, 7260].map(b.forWords),
  leftWords: [0.4, 1, 2, 84, 119, 120, 150, 300].map(b.leftWords),
  status: [b.messageStatus(queued, clock), b.messageStatus({ ...queued, reply: 'Got it. I will read this at my next step.' }, clock),
    b.messageStatus({ ...taken, taken_at: NOW + 5 }, clock), b.messageStatus({ state: 'taken' }, clock),
    b.messageStatus({ ...answered, answered_at: NOW + 9 }, clock), b.messageStatus({ state: 'answered' }, clock), b.messageStatus(null, clock)],
  when: ['now', 'next_step', 'after_permission', 'as_answer', 'when_resumed', 'next_turn', 'later'].map(b.whenWords),
  hold: [b.holdWords({ state: 'asked' }, NOW), b.holdWords({ state: 'held', until: NOW + 90 }, NOW), b.holdWords({ state: 'held', until: NOW + 480 }, NOW),
    b.holdWords({ state: 'held' }, NOW), b.holdWords({ state: 'held', until: NOW - 3 }, NOW), b.holdWords({ state: 'ended' }, NOW), b.holdWords(null, NOW)],
  ended: [['carry on', 10], ['ten minutes', 10], ['nobody', 10], ['off', 10], ['stopped', 10], ['other', 10], ['carry on', 500]]
    .map(([why, ago]) => b.holdEndedWords({ why, at: NOW - ago }, NOW)),
  endedSaid: ['carry on', 'ten minutes', 'nobody', 'off', 'stopped'].map((why) => b.holdEndedSaid({ why })),
  good: [b.goodSaid({ check: 'The tests' }), b.goodSaid({ check: 'npm test', reviewer: true }), b.goodSaid({ check: 'The tests', review: 'The review line found nothing to fix.' }),
    b.goodSaid({})],
  plain: [b.plainReply({ sent: 'resumed' }, true), b.plainReply({ sent: 'queued' }, true), b.plainReply({ sent: 'queued' }, false, 'Codex')],
  now: [b.nowOf({ state: 'working', now: { kind: 'command', words: 'Running npm test', started_at: NOW - 40 } }, NOW),
    b.nowOf({ state: 'finished', steps: [{ words: 'Ran npm test' }] }, NOW), b.nowOf({ state: 'working', last: { words: 'Edited src/login.js' } }, NOW),
    b.nowOf({ state: 'working', last: { words: 'NPM install' } }, NOW), b.nowOf({ state: 'working' }, NOW)],
  monitor: [b.monitorLine({ state: 'working', now: { words: 'Running npm test', started_at: NOW - 40 }, todos: [{ state: 'done' }, { state: 'working' }, { state: 'open' }] }, NOW),
    b.monitorLine({ state: 'working', now: { words: 'Running npm test', started_at: NOW - 40 }, asking: { text: 'Which colour for the button?' } }, NOW),
    b.monitorLine({ state: 'held', now: { words: 'Running npm test', started_at: NOW - 40 }, todos: { done: 1, all: 3 } }, NOW),
    b.monitorLine({ state: 'working' }, NOW)],
  steps: [b.stepLine({ words: 'Ran npm test', took: 38 }), b.stepLine({ words: 'Ran npm test', took: 38, failed: true }), b.stepLine({ words: 'Read a.js', took: 1 })],
  todo: b.todoOf({ todos: [{ title: 'Find it', state: 'done' }, { title: 'Fix it', state: 'working' }, { title: 'Test it', state: 'open' }, null] }),
  lines: b.numberLines(hunks[0]).concat(b.numberLines(hunks[3])),
  files: b.filesOf(hunks).map((f) => [f.file, f.added, f.removed, f.hunks.map((h) => h.n)]),
  totals: [b.totalsWords(b.changeTotals(hunks)), b.totalsWords(b.changeTotals([hunks[0]])), b.totalsWords(b.changeTotals([]))],
  kinds: [{ kind: 'add' }, { kind: 'delete' }, { kind: 'whole' }, { kind: 'notebook', cell: 'c2', mode: 'insert' }, { to: 'src/new.js' }, {}].map(b.hunkKind),
  resolved: [[{ change: 2 }], [{ change: -1 }], [{ change: 9 }], [{ line: 11 }], [{ line: 11, file: 'login.js' }], [{ line: 41 }], [{ line: 4, file: 'button.css' }],
    [{ line: 4, file: 'other.css' }], [{ line: 999 }], [{ change: 1 }, []]].map(([p, list]) => b.resolvePoint(p, list ?? hunks)),
  pointSaid: [b.pointSaid(b.resolvePoint({ change: 2 }, hunks)), b.pointSaid(b.resolvePoint({ line: 41 }, hunks)),
    b.pointSaid({ file: 'notes.md', line: null, text: '' }), b.pointSaid(null)],
  flows: {
    takenThenAnswered: await flow({ id: 'm1', reply: 'Got it.', when: 'next_step', sent: 'queued' }, [queued, taken, taken, answered]),
    answeredAtOnce: await flow({ id: 'm1', reply: 'Got it.', when: 'next_step', sent: 'queued' }, [queued, answered]),
    resumed: await flow({ id: 'm1', reply: 'On it.', when: 'now', sent: 'resumed' }, [taken, answered]),
    nextTurn: await flow({ id: 'm1', reply: 'I read this next time.', when: 'next_turn', sent: 'queued' }, [queued]),
    neverAnswered: await flow({ id: 'm1', reply: 'Got it.', when: 'next_step', sent: 'queued' }, [queued], 3000),
  },
  queue: queue.waitingOnYou({
    now: NOW,
    asks: [{ id: 'a1', key: 'k1', tool: 'Bash', what: 'Bash: npm test', at: NOW - 30, until: NOW + 100 }],
    conversations: [{ id: 'k1', title: 'Fix the login', project: 'Shop', at: NOW - 60, working: true },
      { id: 'k2', title: 'New button', project: 'Shop', at: NOW - 60, working: true },
      { id: 'k3', title: 'Tidy', project: 'Lab', at: NOW - 900, says: { needs: 'Should I delete the old files?' } }],
    questions: [{ id: 'q1', key: 'k2', state: 'waiting', at: NOW - 10, until: NOW + 50, kind: 'choices', questions: choices().questions },
      { id: 'q2', key: 'k3', state: 'open', at: NOW - 900, kind: 'text', text: 'Keep the old files?' }],
  }).map((i) => [i.kind, i.id, i.key, i.title, i.what, i.until, !!i.urgent]),
}));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class BesideWordsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        done = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT, str(NOW)], capture_output=True, text=True, timeout=30)
        if done.returncode != 0:
            raise AssertionError(done.stderr)
        cls.out = json.loads(done.stdout)

    def test_what_was_said(self):
        asked = dict(self.out["asked"])
        for text in ["hold on", "Hold on a second", "wait", "Wait!", "stop there", "Stop right there please", "hang on a moment", "no, wait"]:
            self.assertEqual(asked[text], "hold", text)
        # "stop" alone still stops the agent, and a question or an instruction that starts with "wait" or "hold on" is
        # a message, not a hold
        for text in ["stop", "Stop.", "Wait, what are you doing?", "hold on, use the helper instead", "", "looks good but change the colour", "what looks good?"]:
            self.assertIsNone(asked[text], text)
        for text in ["carry on", "OK carry on", "you can carry on now", "keep going", "go ahead"]:
            self.assertEqual(asked[text], "carry", text)
        for text in ["walk me through it", "Can you walk me through your changes?", "explain your changes", "what did you change?", "show me the changes"]:
            self.assertEqual(asked[text], "walk", text)
        for text in ["looks good", "That looks great to me, thanks", "LGTM", "ok ship it"]:
            self.assertEqual(asked[text], "good", text)

    def test_pointing_at_a_change(self):
        points = dict(self.out["points"])
        self.assertEqual(points["the second change"], {"change": 2, "rest": ""})
        self.assertEqual(points["the second change: use a helper"], {"change": 2, "rest": "use a helper"})
        self.assertEqual(points["change 3, put it back"], {"change": 3, "rest": "put it back"})
        self.assertEqual(points["the last change"], {"change": -1, "rest": ""})
        self.assertEqual(points["line 42"], {"line": 42, "file": None, "rest": ""})
        self.assertEqual(points["line 12 in login.js please rename it"], {"line": 12, "file": "login.js", "rest": "rename it"})
        self.assertEqual(points["on line 7 of src/app.py: why?"], {"line": 7, "file": "src/app.py", "rest": "why?"})
        self.assertEqual(points["the 2nd edit"], {"change": 2, "rest": ""})
        for text in ["the zeroth change", "make the change", "online 4"]:
            self.assertIsNone(points[text], text)

    def test_picking_a_choice(self):
        picked = dict(self.out["picked"])
        q = "Which colour for the button?"
        want = {"blue": "Blue", "Blue please": "Blue", "the green one": "Green", "the first one": "Blue", "option 2": "Green",
                "number three": "Dark grey", "the last one": "Dark grey", "dark grey": "Dark grey", "I think green": "Green"}
        for text, label in want.items():
            self.assertEqual(picked[text], {"answers": {q: label}}, text)
        self.assertIsNone(picked["purple"])  # your own words, sent as they are
        self.assertIsNone(picked["option 9"])
        self.assertEqual(self.out["pickedMulti"], {"answers": {q: ["Green"]}})
        self.assertIsNone(self.out["pickedTwoParts"])  # two questions at once are answered on the screen
        self.assertIsNone(self.out["pickedPlain"])

    def test_a_question_said_and_its_wait(self):
        said = self.out["said"]
        self.assertEqual(said[0], "I have a question. Which colour for the button? Blue, Green, or Dark grey. Say one, or tell me in your own words.")
        self.assertEqual(said[1], "I have a question. Which colour for the button? Blue, Green, or Dark grey, as many as you like. Say one, or tell me in your own words.")
        self.assertEqual(said[2], "I have a question: Should I keep the old login?")
        self.assertEqual(said[3], "I have a question. Which colour for the button? Blue, Green, or Dark grey. I have 1 more question on the screen. Say one, or tell me in your own words.")
        self.assertEqual(said[4], "")
        wait = self.out["wait"]
        self.assertEqual(wait[0], "It's waiting for you here for 84 more seconds, then it asks in its own window.")
        self.assertEqual(wait[1], "It's waiting for you here for 5 more minutes, then it asks in its own window.")
        self.assertEqual(wait[2], "Its wait here is over, so it asks in its own window now. You can still answer here.")
        self.assertEqual(wait[3], "It asked in its own window instead. You can still answer here: it gets your answer as a message.")
        self.assertEqual(wait[4], "Its turn ended on this question. Answer here and it gets your answer as a message.")

    def test_time_in_words(self):
        self.assertEqual(self.out["forWords"], ["a few seconds", "a few seconds", "5 seconds", "40 seconds", "a minute", "a minute", "2 minutes",
                                                "59 minutes", "an hour", "an hour and 5 minutes", "2 hours and 1 minute"])
        # never says a short wait is longer than it is: seconds under two minutes
        self.assertEqual(self.out["leftWords"], ["a second more", "a second more", "2 more seconds", "84 more seconds", "119 more seconds",
                                                 "2 more minutes", "3 more minutes", "5 more minutes"])

    def test_how_a_message_stands(self):
        status = self.out["status"]
        self.assertEqual(status[0], {"state": "queued", "word": "Waiting for it to read this", "line": ""})
        self.assertEqual(status[1]["line"], "Got it. I will read this at my next step.")
        self.assertEqual(status[2], {"state": "taken", "word": "Read at T5", "line": "I've read your note."})
        self.assertEqual(status[3], {"state": "taken", "word": "Read", "line": "I've got your note and I'm on it."})
        self.assertEqual(status[4], {"state": "answered", "word": "Answered at T9", "line": "Done: blue it is."})
        self.assertEqual(status[5], {"state": "answered", "word": "Answered", "line": "It answered in its own window."})
        self.assertIsNone(status[6])
        self.assertEqual(self.out["when"], ["It gets this now.", "It reads this at its next step.", "It reads this once the permission it waits on is answered.",
                                            "This answers the question it asked you.", "It reads this once you resume your agents.",
                                            "It reads this the next time you send it something in its own window.", ""])
        self.assertEqual(self.out["plain"], ["On it.", "Got it. I'll read that at my next step.",
                                             "I'm waiting for you in Codex, so I'll see this the next time you send me something there."])

    def test_a_hold_in_words(self):
        hold = self.out["hold"]
        self.assertEqual(hold[0]["word"], "Holding at its next step")
        self.assertIsNone(hold[0]["left"])
        self.assertEqual(hold[1]["line"], "It's waiting for you, keeping what it has done. It can stay held for 90 more seconds at most, or until 2 minutes "
                                          "after nobody is using the building. What you say reaches it straight away.")
        self.assertEqual(hold[1]["left"], 90)
        self.assertIn("for 8 more minutes at most", hold[2]["line"])
        self.assertIn("for up to ten minutes", hold[3]["line"])
        self.assertIn("only a moment more", hold[4]["line"])
        self.assertIsNone(hold[5])
        self.assertIsNone(hold[6])
        self.assertEqual(self.out["ended"], ["It carried on, as you said.", "It carried on: a hold lasts ten minutes at most.",
                                             "It carried on: nobody was using the building for 2 minutes.",
                                             "It carried on: Hold on and carry on was switched off.", "It stopped while it was held.", "It carried on.", None])
        # the agent says how a hold ended only when you didn't end it yourself
        self.assertEqual(self.out["endedSaid"], [None, "I've carried on: a hold lasts ten minutes at most.",
                                                 "I've carried on: nobody was using the building for 2 minutes.", "I've carried on: holding was switched off.", None])

    def test_looks_good(self):
        good = self.out["good"]
        self.assertEqual(good[0], "Thanks. I'm running the tests on my work now, and my page shows whether it passes.")
        self.assertEqual(good[1], "Thanks. I'm running npm test on my work now, and my page shows whether it passes. "
                                  "The review line reads my work as my turn ends, before it reaches you.")
        self.assertEqual(good[2], "Thanks. I'm running the tests on my work now, and my page shows whether it passes. The review line found nothing to fix.")
        self.assertTrue(good[3].startswith("Thanks. My floor has no check to run"))

    def test_what_it_is_doing(self):
        now = self.out["now"]
        self.assertEqual(now[0], {"words": "Running npm test", "since": 40, "kind": "command", "state": "working"})
        self.assertEqual(now[1]["words"], "Finished. Last, it ran npm test")
        self.assertEqual(now[2]["words"], "Last, it edited src/login.js")
        self.assertEqual(now[3]["words"], "Last, it NPM install")  # a name in capitals keeps them
        self.assertIsNone(now[4])
        monitor = self.out["monitor"]
        self.assertEqual(monitor[0], {"title": "Running npm test", "sub": "40 seconds, 1 of 3 done", "kind": "working"})
        self.assertEqual(monitor[1], {"title": "Asking you", "sub": "Which colour for the button?", "kind": "needs"})
        self.assertEqual(monitor[2], {"title": "Held, as you asked", "sub": "1 of 3 done", "kind": "needs"})
        self.assertIsNone(monitor[3])
        self.assertEqual(self.out["steps"], ["Ran npm test, took 38 seconds", "Ran npm test, it didn't work", "Read a.js"])
        todo = self.out["todo"]
        self.assertEqual([todo["done"], todo["all"], todo["working"]], [1, 3, "Fix it"])

    def test_lines_and_their_numbers(self):
        self.assertEqual(self.out["lines"], [
            {"sign": " ", "text": "function login(user) {", "old": 10, "new": 10},
            {"sign": "-", "text": "  if (user = null) {", "old": 11, "new": None},
            {"sign": "+", "text": "  if (user === null) {", "old": None, "new": 11},
            {"sign": " ", "text": "    return false", "old": 12, "new": 12},
            # a file written whole, whose old lines couldn't be read: no numbers rather than wrong ones
            {"sign": "+", "text": "one", "old": None, "new": None},
            {"sign": "+", "text": "two", "old": None, "new": None},
        ])
        # by file, in the order each was first changed, each change keeping its place in the list
        self.assertEqual(self.out["files"], [["src/login.js", 1, 2, [1, 3]], ["src/button.css", 2, 0, [2]], ["notes.md", 2, 0, [4]]])
        self.assertEqual(self.out["totals"], ["3 files: 5 lines put in, 2 taken out.", "1 file: 1 line put in, 1 taken out.", "No changes yet."])
        self.assertEqual(self.out["kinds"], ["A new file", "Deleted", "Written whole: the file as it was could not be read",
                                             "A notebook cell (c2), put in", "Renamed to src/new.js", ""])

    def test_resolving_a_point(self):
        r = self.out["resolved"]
        self.assertEqual(r[0], {"file": "src/button.css", "line": 4, "text": "  colour: blue;", "side": None, "n": 2})
        self.assertEqual(r[1], {"file": "notes.md", "line": None, "text": "one", "side": None, "n": 4})
        self.assertIsNone(r[2])
        self.assertEqual(r[3], {"file": "src/login.js", "line": 11, "text": "  if (user === null) {", "side": None, "n": 1})
        self.assertEqual(r[4], r[3])
        # a line only in the file as it was: the line taken out
        self.assertEqual(r[5], {"file": "src/login.js", "line": 41, "text": "console.log(user)", "side": "old", "n": 3})
        self.assertEqual(r[6], {"file": "src/button.css", "line": 4, "text": "  colour: blue;", "side": None, "n": 2})
        self.assertIsNone(r[7])
        self.assertIsNone(r[8])
        self.assertIsNone(r[9])
        said = self.out["pointSaid"]
        self.assertEqual(said[0], "That's change 2, in src/button.css, line 4: \"colour: blue;\". What would you like me to do with it?")
        self.assertEqual(said[1], "That's change 3, in src/login.js, line 41 as it was: \"console.log(user)\". What would you like me to do with it?")
        self.assertEqual(said[2], "That is in notes.md. What would you like me to do with it?")
        self.assertEqual(said[3], "")

    def test_the_reply_as_it_happens(self):
        flows = self.out["flows"]
        self.assertEqual(flows["takenThenAnswered"]["said"], ["Got it.", " I've read your note.", " Done: blue it is."])
        self.assertEqual(flows["takenThenAnswered"]["noted"], ["m1:taken", "m1:answered"])
        # answered before it was seen taken: it is still never said as taken again elsewhere
        self.assertEqual(flows["answeredAtOnce"]["said"], ["Got it.", " Done: blue it is."])
        self.assertEqual(flows["answeredAtOnce"]["noted"], ["m1:taken", "m1:answered"])
        # sent to an agent the building resumed: it has it at once, so "taken" isn't said again
        self.assertEqual(flows["resumed"]["said"], ["On it.", " Done: blue it is."])
        # nothing will happen until you act: no waiting
        self.assertEqual(flows["nextTurn"]["said"], ["I read this next time."])
        self.assertEqual(flows["neverAnswered"]["said"], ["Got it.", " I'm still on it. My answer will show on my page."])

    def test_a_waiting_question_comes_first(self):
        q = self.out["queue"]
        # the question its hook waits on now comes before the permission whose wait runs out later; a question left
        # for later comes after the permissions, with the questions
        self.assertEqual([row[1] for row in q], ["q:q1", "ask:a1", "q:q2"])
        self.assertEqual(q[0], ["question", "q:q1", "k2", "New button", "Which colour for the button?", NOW + 50, True])
        self.assertEqual(q[2], ["question", "q:q2", "k3", "Tidy", "Keep the old files?", 0, False])


if __name__ == "__main__":
    unittest.main()
