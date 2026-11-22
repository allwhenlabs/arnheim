// Talk from any screen: a Talk button at the top of the page opens a small panel where you talk out loud, or
// type, to the receptionist or to any floor's lead, without walking. It is the walk's own voice (voice.js) with
// the page's own `talk`. Say "take me to Lantern" and the page goes there; ask "how's Tidepool doing?" and you
// are put through to Tidepool's lead, who answers. The switches for the talking features are in it too
// (features.js), and with a phone paired (serve.py --remote) it works the same from the phone.
//
// createTalkDock({ talk, features, people, here, place, before }):
//   talk      the page's talk (voice.js), with optional extras: through(who, text) gives someone to put the
//             person through to, as { who, then } (then: the question for them to answer, or null), and
//             desk, the receptionist as talk knows them ({ href, title })
//   features  features.js's switches
//   people()  who can be talked to here: [{ who, label }], the receptionist first
//   here()    who to start with on the screen showing now (a floor's lead on its floor), or null
//   place     the element the Talk button goes in, before `before`
//   extra()   optional: more for the switches panel (an element), such as pairing a phone
// Gives { open(who?, opts?), close(), hide(on), refresh(), dispose(), get isOpen, voice }: open gives false when Talk is
// switched off or hidden, so nothing opened.

import { createVoice, voiceWanted } from './voice.js';
import { FEATURES } from './features.js';
import { icon } from './icons.js';

const CSS = new URL('./talk-dock.css', import.meta.url).href;
const keyOf = (who) => (who ? who.href || who.title || '' : '');

function styled() {
  if (document.querySelector('link[data-arnheim-dock]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS;
  link.dataset.arnheimDock = '';
  document.head.append(link);
}

export function createTalkDock({ talk, features, people, here, place, before = null, extra = null }) {
  styled();
  const listeners = new AbortController();
  const { signal } = listeners;
  const el = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };
  const button = (text, onClick, label) => {
    const b = el('button', 'aw-btn', text);
    b.type = 'button';
    if (label) b.setAttribute('aria-label', label);
    b.addEventListener('click', onClick, { signal });
    return b;
  };

  /* ---------- the Talk button, and the panel ---------- */

  const opener = el('button', 'td-open');
  opener.type = 'button';
  opener.id = 'talk';
  opener.setAttribute('aria-expanded', 'false');
  opener.setAttribute('aria-controls', 'talk-dock');
  opener.setAttribute('aria-label', 'Talk'); // a phone hides the word: the button keeps its name
  opener.append(icon('mic', 16), el('span', 'td-open-word', 'Talk'));
  opener.addEventListener('click', () => (isOpen ? close() : open()), { signal });
  place.insertBefore(opener, before);

  const dock = el('section', 'td-dock');
  dock.id = 'talk-dock';
  dock.hidden = true;
  dock.setAttribute('aria-label', 'Talk');
  const head = el('div', 'td-head');
  const pick = el('select', 'td-who');
  pick.setAttribute('aria-label', 'Who you are talking to');
  const gear = button('', () => showSwitches(switches.hidden), 'Talking switches');
  gear.classList.add('td-icon');
  gear.append(icon('sliders-horizontal', 16));
  gear.setAttribute('aria-expanded', 'false');
  const shut = button('', () => close(), 'Close');
  shut.classList.add('td-icon');
  shut.append(icon('x', 16));
  head.append(pick, gear, shut); // the voice puts its Voice on/off button after the first of these
  const switches = el('div', 'td-switches');
  switches.hidden = true;
  const body = el('div', 'td-body');
  const hint = el('p', 'td-hint', 'Try: "what needs me?", "how is Lantern doing?", "take me to Settings".');
  body.append(hint);
  dock.append(head, switches, body);
  document.body.append(dock);

  let isOpen = false;
  let hidden = false;

  // The page's talk, with one more step first: a question meant for someone else ("how's Tidepool doing?",
  // "talk to Lantern's lead") puts you through to them, and they answer it.
  const asIs = talk;
  const through = {
    ...asIs,
    answer(who, text, before, opts) {
      let to = null;
      try { to = asIs.through?.(who, text) || null; } catch (error) { console.warn('Arnheim: could not put you through.', error); }
      if (to?.who && keyOf(to.who) !== keyOf(who)) {
        // the voice drops this answer as soon as you are with someone else, and they take the question
        return new Promise((resolve) => setTimeout(() => {
          setWho(to.who, { greet: to.then ? false : 'again' });
          if (to.then) voice.ask(to.then, { spoken: !!opts?.spoken });
          resolve(null);
        }, 0));
      }
      return asIs.answer(who, text, before, opts);
    },
  };
  const voice = createVoice({
    hud: head, card: body, el, button, signal, early: false, written: true,
    ctx: { talk: through, personRoom: { spec: { person: { href: asIs.desk?.href || null } } } },
  });
  body.append(hint); // under the conversation

  /* ---------- who you are talking to ---------- */

  let list = [];
  function drawPick() {
    try { list = people() || []; } catch (error) { console.warn('Arnheim: no one to talk to.', error); list = []; }
    const now = keyOf(voice.who);
    pick.replaceChildren(...list.map(({ who, label }) => {
      const o = el('option', null, label || who.title);
      o.value = keyOf(who);
      return o;
    }));
    if (now && list.some((p) => keyOf(p.who) === now)) pick.value = now;
  }
  pick.addEventListener('change', () => {
    const p = list.find((x) => keyOf(x.who) === pick.value);
    if (p) setWho(p.who);
  }, { signal });
  function setWho(who, opts) {
    if (!list.some((p) => keyOf(p.who) === keyOf(who))) drawPick();
    voice.talkTo(who, opts);
    if (list.some((p) => keyOf(p.who) === keyOf(who))) pick.value = keyOf(who);
  }

  /* ---------- the switches ---------- */

  function drawSwitches() {
    const rows = FEATURES.map((f) => {
      const row = el('label', 'td-switch');
      const box = el('input');
      box.type = 'checkbox';
      box.checked = features.get(f.id);
      box.addEventListener('change', () => features.set(f.id, box.checked), { signal });
      const words = el('span', 'td-switch-words');
      words.append(el('b', null, f.label), el('span', null, f.about));
      row.append(box, words);
      return row;
    });
    const more = typeof extra === 'function' ? extra() : null;
    switches.replaceChildren(el('h3', null, 'Talking'), ...rows,
      el('p', 'td-note', 'Switching off Talk from any screen hides this button. It comes back in Settings, under Talking.'), ...(more ? [more] : []));
  }
  function showSwitches(on) {
    switches.hidden = !on;
    gear.setAttribute('aria-expanded', String(!!on));
    if (on) drawSwitches();
  }

  /* ---------- open and close ---------- */

  // opts, for someone named: as voice.js's talkTo takes them ({ greet: 'again' } greets even someone already talked to).
  function open(who = null, opts = undefined) {
    if (hidden || !features.get('talk')) return false;
    isOpen = true;
    dock.hidden = false;
    opener.setAttribute('aria-expanded', 'true');
    drawPick();
    let start = who;
    try { start ||= here?.() || null; } catch { start = null; }
    start ||= list[0]?.who || null;
    if (start) setWho(start, who && start === who ? opts : undefined);
    if (!voiceWanted()) hint.textContent = 'This device keeps the voice off, so type to talk.';
    (dock.querySelector('.aw-ask input') || pick).focus({ preventScroll: true });
    return true;
  }

  function close() {
    if (!isOpen) return;
    isOpen = false;
    dock.hidden = true;
    opener.setAttribute('aria-expanded', 'false');
    showSwitches(false);
    voice.talkTo(null); // the microphone closes with the panel
    if (dock.contains(document.activeElement)) opener.focus({ preventScroll: true });
  }

  // While the walk is open, it has its own voice: this one closes and its button goes.
  function hide(on) {
    hidden = !!on;
    refresh();
    if (hidden) close();
  }

  function refresh() {
    opener.hidden = hidden || !features.get('talk');
    if (!features.get('talk')) close();
    if (isOpen) {
      drawPick();
      if (!list.some((p) => keyOf(p.who) === keyOf(voice.who))) setWho(list[0]?.who || null);
    }
    if (!switches.hidden) drawSwitches();
  }
  const unwatch = features.watch(() => refresh());

  dock.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    event.stopPropagation();
    if (!switches.hidden) showSwitches(false);
    else close();
  }, { signal });

  function dispose() {
    unwatch();
    voice.dispose();
    listeners.abort();
    dock.remove();
    opener.remove();
  }

  refresh();
  return { open, close, hide, refresh, dispose, get isOpen() { return isOpen; }, voice };
}
