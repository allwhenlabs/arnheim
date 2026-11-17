"""The voice's own logic (src/voice.js), run under Node.js with a stand-in page, sound card, microphone and voice
server: several people speaking in turn (the leads' round), cutting in by talking over them, never cutting
themselves off while their words are still on the way or when a soft voice gives way to a loud one, speaking up
only when nobody is talking or waiting for an answer, and a button's reply never dropping what you said. Takes
about 40 seconds, as the voice keeps real time.

Skipped where Node isn't installed. Run from the repository's folder: python3 -m unittest discover tests
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (test, ms = 4000) => { const end = Date.now() + ms; while (!test()) { if (Date.now() > end) return false; await sleep(20); } return true; };

/* ---------- a stand-in page ---------- */
function node(tag) {
  return {
    tag, children: [], className: '', hidden: false, textContent: '', value: '', attrs: {}, style: {}, dataset: {},
    append(...c) { this.children.push(...c); }, replaceChildren(...c) { this.children = c; }, setAttribute(k, v) { this.attrs[k] = v; },
    removeAttribute() {}, addEventListener() {}, classList: { add() {}, remove() {}, toggle() {} }, after() {}, remove() {}, focus() {}, blur() {},
    get firstElementChild() { return this.children[0] || null; },
  };
}
globalThis.window = globalThis;
window.addEventListener = () => {};
globalThis.document = { hidden: false, activeElement: null, addEventListener() {}, createTextNode: (t) => ({ text: t }), createElementNS: (_, tag) => node(tag), createElement: node };
globalThis.localStorage = { getItem: (k) => (k === 'arnheim-voice' ? 'on' : null), setItem() {} };
globalThis.location = { search: '' };
let micBlocks = null;
Object.defineProperty(globalThis, 'navigator', { configurable: true, value: { mediaDevices: { getUserMedia: async () => ({ getTracks: () => [{ stop() {} }] }) } } });

/* ---------- a stand-in sound card: each sound plays for its length in real time ---------- */
const t0 = performance.now();
const started = [];
class FakeSource {
  constructor() { this.onended = null; this.stopped = false; }
  connect() {}
  start(at) { this.at = at; started.push(this); const wait = Math.max(0, at - (performance.now() - t0) / 1000) + this.buffer.duration; setTimeout(() => { if (!this.stopped) { this.done = true; this.onended?.(); } }, wait * 1000); }
  stop() { this.stopped = true; }
}
class FakeAudio {
  constructor() { this.state = 'running'; this.sampleRate = 16000; this.destination = {}; this.audioWorklet = { addModule: async () => {} }; }
  get currentTime() { return (performance.now() - t0) / 1000; }
  createBufferSource() { return new FakeSource(); }
  createMediaStreamSource() { return { connect() {}, disconnect() {} }; }
  createGain() { return { gain: {}, connect() {}, disconnect() {} }; }
  decodeAudioData(data) { return Promise.resolve({ duration: data.duration, level: data.level, sampleRate: 16000, getChannelData: () => new Float32Array(Math.round(data.duration * 16000)).fill(10 ** (data.level / 20)) }); }
  resume() { return Promise.resolve(); }
  close() { return Promise.resolve(); }
}
globalThis.AudioContext = FakeAudio;
globalThis.AudioWorkletNode = class { constructor() { this.port = {}; micBlocks = this; } connect() {} disconnect() {} };

/* ---------- a stand-in voice server ---------- */
const says = [];
const levelOf = (v) => (v === 'af_heart' ? -30 : -12); // the receptionist's voice is soft here, everyone else's loud
let sayDelay = 30;
let sayLength = 0.35; // seconds each sentence sounds for
let hearDelay = 30;
let heardWords = 'what about tidepool';
let hears = 0;
const json = (body) => ({ ok: true, json: async () => body });
globalThis.fetch = async (url, init = {}) => {
  const name = String(url).split('/').pop();
  if (name === 'status' || name === 'wake') return json({ say: true, hear: true, state: 'ready', voices: ['af_heart', 'af_bella', 'am_michael', 'bm_george', 'bf_emma'] });
  if (name === 'say') { const b = JSON.parse(init.body); says.push({ voice: b.voice, text: b.text, at: performance.now() }); await sleep(sayDelay); return { ok: true, arrayBuffer: async () => ({ duration: sayLength, level: levelOf(b.voice) }), headers: { get: () => '5' } }; }
  if (name === 'hear') { hears += 1; await sleep(hearDelay); return json({ ok: true, text: heardWords }); }
  return { ok: false, json: async () => ({}) };
};

/* ---------- the microphone: blocks of 10 ms at a given loudness ---------- */
const block = (db) => new Float32Array(160).fill(10 ** (db / 20));
// a real microphone never stops sending: after each step, a second of the quiet room
const quiet = () => feed(-75, 1.0);
// in real time, the microphone hearing only what is sounding now, back from the speakers `ratio` decibels softer
const add = (a, b) => 10 * Math.log10(10 ** (a / 10) + 10 ** (b / 10));
const soundingNow = () => { const now = (performance.now() - t0) / 1000; let most = null; for (const x of started) if (!x.stopped && x.at <= now && now < x.at + x.buffer.duration) most = Math.max(most ?? -200, x.buffer.level); return most; };
const levelsHeard = new Set();
const echoes = async (ratio, seconds) => {
  const from = performance.now();
  for (let i = 0; i < Math.round(seconds / 0.01); i++) {
    while (performance.now() < from + i * 10) await sleep(1);
    const l = soundingNow();
    if (l != null) levelsHeard.add(l);
    micBlocks.port.onmessage({ data: block(l == null ? -75 : add(-75, l + ratio)) });
  }
};
const feed = async (db, seconds) => { for (let i = 0; i < Math.round(seconds / 0.01); i++) { micBlocks.port.onmessage({ data: block(db) }); if (i % 10 === 9) await sleep(1); } };

const { createVoice } = await import(pathToFileURL(process.argv[1] + '/src/voice.js').href);
const asked = [];
let answerWith = null;
let speakUps = 0;
let greetWith = null;
let news = null;
let controls = null;
const desk = { href: '#/front-desk', title: 'Iris' };
const talk = {
  base: 'http://example.test/voice/',
  name: (who) => who.title,
  greet: (who) => greetWith?.(who) ?? null,
  answer: (who, text) => { asked.push(text); return answerWith ? answerWith(text) : 'All right.'; },
  speakUp: () => { speakUps += 1; const n = news; news = null; return n; },
  controls: () => controls,
  cutIn: () => true,
};
const buttons = new Map();
const button = (text, onClick, label) => { const b = node('button'); b.onClick = onClick; buttons.set(label || text, b); return b; };
const voice = createVoice({ hud: node('div'), card: node('div'), ctx: { talk, personRoom: { spec: { person: { href: desk.href } } } }, el: (tag, cls, text) => { const n = node(tag); if (text != null) n.textContent = text; return n; }, button, signal: new AbortController().signal, early: false, written: true });
const out = {};
voice.talkTo(desk);
await until(() => voice.info().ear === 'on');
await sleep(900); // the microphone settles and learns the room
await feed(-70, 0.5);

/* 1. the round: several people in turn, each named and in their own voice */
answerWith = () => ({ turns: [
  { who: null, text: "Here's the round." },
  { who: { href: '#/lantern/lead', title: 'Juno' }, text: 'Lantern. All quiet.' },
  { who: { href: '#/tide/lead', title: 'Marlo' }, text: 'Tidepool. One thing waits on you.' },
] });
const from = says.length;
voice.ask('give me the round');
await until(() => says.length >= from + 3);
out.roundVoices = says.slice(from).map((s) => [s.voice, s.text]);
await until(() => voice.info().mode === 'listening', 6000);
await sleep(400);

/* 2. talking over a long answer stops it at once, and what you say is heard and answered */
answerWith = (text) => (text === 'tell me everything' ? (async function* () {
  for (let i = 1; i <= 8; i++) { yield `Sentence ${i} of a long answer. `; await sleep(150); }
})() : 'Tidepool is fine.');
voice.ask('tell me everything');
await until(() => voice.info().mode === 'speaking' && started.some((s) => !s.stopped && !s.done));
await sleep(100);
await feed(-46, 0.7); // their own voice, back from the speakers: never you
out.echoCut = voice.info().cuts;
await feed(-18, 0.35); // you, talking over them
out.cut = voice.info().cuts;
out.modeAfterCut = voice.info().mode;
const saysAtCut = says.length;
const playingAtCut = started.filter((s) => !s.stopped && !s.done).length;
await feed(-18, 0.4);
hearDelay = 1500; // hearing takes a while: long enough for the rest of the cut answer to sound, if it could
await feed(-75, 0.9); // you stop: what you said goes to be heard
const modesWhileHeard = new Set(); // meanwhile the cut answer's words stop coming: it never says it is listening
const sampler = setInterval(() => { if (!asked.includes('what about tidepool')) modesWhileHeard.add(voice.info().mode); }, 20);
await until(() => asked.includes('what about tidepool'), 5000);
clearInterval(sampler);
out.modesWhileHeard = [...modesWhileHeard];
hearDelay = 30;
out.heardAndAsked = asked.includes('what about tidepool');
out.saysAfterCut = says.slice(saysAtCut).filter((s) => /long answer/.test(s.text)).length; // the rest of the long answer is never said
out.playingAtCut = playingAtCut;
await until(() => voice.info().mode === 'listening', 6000);
await sleep(400);

/* 3. while their words are still on their way, a loud echo never counts; once they sound, their own echo still doesn't */
await quiet();
sayDelay = 900;
const cutsBefore = voice.info().cuts;
news = 'News from Lantern. The fix you asked for is done.';
out.spokeUpQuiet = await until(() => voice.info().mode === 'speaking', 9000); // at the next look for news
await feed(-70, 0.6); // the quiet room, before any of it plays: never taken for the level of their echo
await until(() => started.some((s) => !s.stopped && !s.done), 3000);
await feed(-30, 0.25); // then their voice, loud, back from the speakers: learned as their echo, never you
await feed(-31, 0.25);
await feed(-30, 0.3);
out.selfCut = voice.info().cuts - cutsBefore;
sayDelay = 30;
await until(() => voice.info().mode === 'listening', 6000);
await quiet();

/* 4. never speaking up while an answer is on its way */
await quiet();
answerWith = () => (async function* () { yield 'First, this. '; await sleep(6000); yield 'Here it is.'; })();
voice.ask('a slow question');
await until(() => voice.info().mode === 'listening' && voice.info().sounds > 0, 3000); // quiet between its parts
const ups = speakUps;
news = 'Something to say.';
await sleep(4500);
out.spokeUpMidAnswer = speakUps - ups; // not even asked, while the answer is on its way
await until(() => /Here it is/.test(voice.info().reply), 4000);
await until(() => voice.info().mode === 'listening', 4000);
out.spokeUpAfter = await until(() => news === null, 9000); // at the next look, once things are quiet

/* 5. a button's reply while what you said is being heard never drops your words */
await quiet();
controls = { note: 'One request', buttons: [{ label: 'Allow', run: () => 'Allowed, once.' }] };
await sleep(1100); // the card draws its buttons
answerWith = (text) => (text === 'another long one' ? (async function* () { for (let i = 1; i <= 6; i++) { yield `Part ${i} of it. `; await sleep(150); } })() : 'Got it.');
voice.ask('another long one');
await until(() => voice.info().mode === 'speaking' && started.some((s) => !s.stopped && !s.done));
await sleep(100);
await feed(-46, 0.6); // the microphone hears their voice first, as it always does
await feed(-18, 0.35);
await feed(-18, 0.3);
hearDelay = 700;
heardWords = 'and the other one';
await feed(-75, 0.9); // you stop: now being heard, slowly
await sleep(100);
await buttons.get('Allow')?.onClick(); // a tap lands meanwhile
await until(() => asked.includes('and the other one'), 4000);
out.wordsKept = asked.includes('and the other one');
out.cutsTotal = voice.info().cuts;
await until(() => voice.info().mode === 'listening', 6000);
hearDelay = 30;
await quiet();

/* 6. a button's reply that lands while you are still talking: your words are kept, and the reply waits */
controls = { note: 'One request', buttons: [{ label: 'Deny', run: () => new Promise((r) => setTimeout(() => r('Denied.'), 300)) }] };
await sleep(1200);
await sleep(1600); // well clear of the last answer
heardWords = 'one more thing';
await feed(-18, 0.2); // you start talking
const tap = buttons.get('Deny')?.onClick();
await feed(-18, 0.6); // still talking as the reply lands
await tap;
await feed(-75, 0.9);
await until(() => asked.includes('one more thing'), 4000);
out.keptWhileTalking = asked.includes('one more thing');
await until(() => voice.info().mode === 'listening', 6000);
await quiet();

/* 7. the round's lines are heard only once they sound: cut in during the first, and the rest never were */
const heardTurns = [];
answerWith = (text) => (text !== 'give me the round' ? 'Sure.' : { turns: [
  { who: null, text: "Here's the round. Three of them today. Here they come.", heard: () => heardTurns.push(0) },
  { who: { href: '#/lantern/lead', title: 'Juno' }, text: 'Lantern. All quiet.', heard: () => heardTurns.push(1) },
  { who: { href: '#/tide/lead', title: 'Marlo' }, text: 'Tidepool. Done.', heard: () => heardTurns.push(2) },
] });
await quiet();
voice.ask('give me the round');
await until(() => voice.info().mode === 'speaking' && started.some((x) => !x.stopped && !x.done));
await sleep(50);
await feed(-46, 0.6);
await feed(-18, 0.35); // cut in during the first
await feed(-75, 0.9);
await sleep(1500);
out.heardTurns = heardTurns;
await until(() => voice.info().mode === 'listening', 6000);
await quiet();

/* 8. a round: one person speaking softly, then the next loudly; the microphone hears only them, from the speakers */
answerWith = (text) => (text !== 'give me the round' ? 'Sure.' : { turns: [
  { who: null, text: "Here's the round. Two of them today." },
  { who: { href: '#/lantern/lead', title: 'Juno' }, text: 'Lantern. All quiet. Nothing waits on you.' },
  { who: { href: '#/tide/lead', title: 'Marlo' }, text: 'Tidepool. One thing waits. The release.' },
] });
const cutsBeforeRound = voice.info().cuts;
voice.ask('give me the round');
await until(() => voice.info().mode === 'speaking' && soundingNow() != null);
await echoes(-20, 2.6);
out.roundSelfCut = voice.info().cuts - cutsBeforeRound;
out.roundLevels = [...levelsHeard].sort((a, b) => a - b);
await until(() => voice.info().mode === 'listening', 8000);
await quiet();

/* 9. a pause between their sentences while the next is still on its way: talking then cuts in too */
sayLength = 0.8;
answerWith = (text) => (text === 'a slow talker' ? (async function* () { yield 'The first part of it. '; await sleep(700); yield 'And then the second part. '; yield 'And a third.'; })() : 'Fine.');
const cutsGap = voice.info().cuts;
voice.ask('a slow talker');
await until(() => soundingNow() != null);
sayDelay = 1500; // the rest is slow to come
await echoes(-16, 0.85); // their first sentence, back from the speakers
out.gapState = { sounding: soundingNow(), mode: voice.info().mode };
heardWords = 'hold on';
await feed(-18, 0.4); // you, in the pause
out.gapCut = voice.info().cuts - cutsGap;
await feed(-75, 0.9);
await until(() => asked.includes('hold on'), 4000);
out.gapHeard = asked.includes('hold on');
sayDelay = 30; sayLength = 0.35;
await until(() => voice.info().mode === 'listening', 6000);
await quiet();

/* 10. moving to someone else while what you said is still being heard: they greet you, and then hear you */
hearDelay = 1500;
heardWords = 'for the desk';
await sleep(600); // past the moment after their last word, when the room's echo is ignored
const hearsBefore = hears;
await feed(-18, 0.5);
await feed(-75, 0.9); // you speak to the desk: on its way to being heard, slowly
out.deskSent = hears - hearsBefore;
greetWith = (w) => (w.title === 'Juno' ? 'Hello.' : null);
voice.talkTo({ href: '#/lantern/lead', title: 'Juno' });
await sleep(2500); // her greeting ends while your words for the desk are still being heard; then they come back
hearDelay = 30;
heardWords = 'for juno';
await until(() => voice.info().mode === 'listening', 3000);
out.afterMove = { who: voice.info().who, mode: voice.info().mode };
await feed(-18, 0.5);
await feed(-75, 0.9);
out.heardAfterMove = await until(() => asked.includes('for juno'), 3000);
out.deskAsked = asked.includes('for the desk'); // what was meant for the desk never goes to her
greetWith = null;
voice.dispose();
console.log(JSON.stringify(out));
process.exit(0);
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class VoiceFlowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT], capture_output=True, text=True, timeout=120)
        if out.returncode:
            raise AssertionError(out.stderr or out.stdout)
        cls.r = json.loads(out.stdout.strip().splitlines()[-1])

    def test_the_round_in_their_own_voices(self):
        voices = [v for v, _ in self.r["roundVoices"]]
        self.assertEqual(voices[0], "af_heart")  # the receptionist's
        self.assertNotIn("af_heart", voices[1:])  # each lead their own
        self.assertEqual([t for _, t in self.r["roundVoices"]][:3], ["Here's the round.", "Lantern.", "All quiet."])

    def test_talking_over_them_stops_them_and_is_heard(self):
        self.assertEqual(self.r["echoCut"], 0)  # their own echo first: no
        self.assertEqual(self.r["cut"], 1)
        self.assertEqual(self.r["modeAfterCut"], "hearing")
        self.assertEqual(self.r["playingAtCut"], 0)  # silent at once
        self.assertEqual(self.r["saysAfterCut"], 0)  # and the rest of the answer is never said
        self.assertTrue(self.r["heardAndAsked"])
        self.assertNotIn("listening", self.r["modesWhileHeard"])  # never says it's listening while your words are heard

    def test_never_cut_off_by_their_own_voice_while_it_is_on_its_way(self):
        self.assertTrue(self.r["spokeUpQuiet"])  # they did speak up
        self.assertEqual(self.r["selfCut"], 0)

    def test_speaking_up_waits_for_the_answer(self):
        self.assertEqual(self.r["spokeUpMidAnswer"], 0)
        self.assertTrue(self.r["spokeUpAfter"])

    def test_a_button_never_drops_what_you_said(self):
        self.assertTrue(self.r["wordsKept"])
        self.assertEqual(self.r["cutsTotal"], 2)
        self.assertTrue(self.r["keptWhileTalking"])  # its reply lands while you are still talking

    def test_a_rounds_lines_count_as_heard_only_once_they_sound(self):
        self.assertEqual(self.r["heardTurns"], [0])

    def test_a_soft_voice_then_a_loud_one_never_cuts_itself_off(self):
        self.assertEqual(self.r["roundLevels"], [-30, -12])  # both were heard back
        self.assertEqual(self.r["roundSelfCut"], 0)

    def test_talking_in_a_pause_between_their_sentences_cuts_in(self):
        self.assertEqual(self.r["gapState"], {"sounding": None, "mode": "speaking"})  # the pause, the next on its way
        self.assertEqual(self.r["gapCut"], 1)
        self.assertTrue(self.r["gapHeard"])

    def test_moving_on_while_being_heard_never_leaves_it_deaf(self):
        self.assertEqual(self.r["deskSent"], 1)  # your words for the desk were on their way to being heard
        self.assertEqual(self.r["afterMove"], {"who": "Juno", "mode": "listening"})
        self.assertTrue(self.r["heardAfterMove"])
        self.assertFalse(self.r["deskAsked"])


if __name__ == "__main__":
    unittest.main()
