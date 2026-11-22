// Show me, on the page (connect/show.py; docs/connect.md, "Show me"): finished work comes with something to look at,
// so you review it by seeing it, not by reading code. When an agent finishes work on a floor that says how to show it,
// a card shows the pictures from before and after side by side, at a desktop width and a phone width (or what the
// floor's show command made or printed), with whether its check passed (src/proof.js) and the lines it changed in
// short. Then Looks good, or Not quite with what to change, typed or said in Talk ("not quite, make the button
// bigger"). On a phone, swipe right for Looks good and left for Not quite, as well as the buttons.
//
// Where the cards come from: control's state (connect/control.py, "shows"), on this computer or a paired phone that may
// control agents, and each picture through control as base64 (show_image), so a phone, or a page whose server keeps
// the data elsewhere, gets them the same way. The made-up company has made-up cards (sample/shows.json), drawn here,
// and says so. Nothing shows while the switch is off: control then lists none.
//
// createShowMe(env) takes:
//   control       control.js's
//   where()       'live' (control is on), 'sample' (the made-up company) or 'none'
//   on()          whether the Show me switch is on
//   phone()       whether this page is a paired phone's (it fetches fewer pictures by itself)
//   label(p)      a floor's name
//   href(key)     a conversation's page, or null
//   ago(at)       how long ago, in words
//   done(promise, said)  what the page does with an answer from a button
//   changed()     the cards changed: draw the page again
//   talkTo(key)   open Talk with that agent, to say what to change
//   sampleUrl()   where the made-up cards are

import { icon } from './icons.js';
import { proofMood, proofOf } from './proof.js';
import { learnAsk } from './sitting.js'; // the building learns from your corrections: the question after Not quite

const CSS = new URL('./show-me.css', import.meta.url).href;
const SVG = 'http://www.w3.org/2000/svg';
const FAR = 90; // pixels a finger moves sideways for a swipe to count

/* ---------- words, and the rules: plain functions, so tests/test_show_me.py can run them under Node ---------- */

export const lookWords = (n) => (n === 1 ? '1 thing to look at' : `${n} things to look at`);

const VIEW_NAMES = { desktop: 'Desktop width', phone: 'Phone width' };
export const viewName = (view) => VIEW_NAMES[view] || String(view || 'Picture').replace(/[-_]+/g, ' ').replace(/^./, (c) => c.toUpperCase());

// The pictures put side by side: one row for each width (or each picture a show command made, by its name), its
// picture from before beside its picture from after. Rows with an after come first, in the order they were taken.
export function pairsOf(pictures) {
  const rows = new Map();
  for (const p of Array.isArray(pictures) ? pictures : []) {
    if (!p || (p.phase !== 'before' && p.phase !== 'after')) continue;
    const view = String(p.view || 'picture');
    if (!rows.has(view)) rows.set(view, { view, label: viewName(view), before: null, after: null });
    rows.get(view)[p.phase] = p;
  }
  return [...rows.values()].sort((a, b) => (b.after ? 1 : 0) - (a.after ? 1 : 0));
}

// The lines it changed, in short: "3 files changed, 12 lines in and 4 out."
export function changedWords(ch) {
  if (!ch || !Number(ch.files)) return null;
  const files = Number(ch.files) === 1 ? '1 file changed' : `${Number(ch.files)} files changed`;
  const add = Number(ch.added) || 0;
  const cut = Number(ch.removed) || 0;
  const lines = add || cut ? `, ${add} ${add === 1 ? 'line' : 'lines'} in and ${cut} out` : '';
  return `${files}${lines}.`;
}

// A swipe on a phone: right is Looks good, left is Not quite. Only a clearly sideways move counts, so scrolling the
// page up and down never answers anything.
export function swipeOf(dx, dy, far = FAR) {
  const x = Number(dx) || 0;
  const y = Number(dy) || 0;
  if (Math.abs(x) < far || Math.abs(x) < 2 * Math.abs(y)) return null;
  return x > 0 ? 'good' : 'again';
}

// What was said about a card in Talk, or typed to its agent: Looks good, or Not quite with what to change.
const GOOD = /^(?:yes[,.!]?\s+)?(?:(?:it|that|this)\s+)?(?:looks?|is)\s+(?:good|great|fine|right)(?:\s+to\s+me)?(?:,?\s+thanks?(?:\s+you)?)?[.!]?$|^(?:approve(?:\s+it)?|ship\s+it|lgtm)[.!]?$/i;
const AGAIN = /^(?:no[,.!]?\s+)?not\s+quite\b[\s,.:;!-]*(.*)$/i;
export function heardShow(text) {
  const words = String(text || '').trim();
  if (GOOD.test(words)) return { act: 'good' };
  const m = AGAIN.exec(words);
  if (m) return m[1].trim() ? { act: 'again', words: m[1].trim().replace(/^(?:please\s+)?/i, '') } : { act: 'ask' };
  return null;
}

// Asked once after Not quite (connect/deputy.py, show_learning): Yes means work of this kind that the building starts on
// this floor isn't counted done until you say Looks good.
export const SHOW_ASK = 'Should Show me ask you before calling this kind of change done?';

// The cards still asking that, after Not quite: answered here once, even when nothing else waits for you.
export const askingOf = (rows) => (Array.isArray(rows) ? rows : []).filter((s) => s && s.state === 'again' && s.learn?.ask);

export function stateLine(s) {
  if (s?.state === 'approved') return 'You said it looks good.';
  if (s?.state === 'again') return s.words ? `You asked for a change: "${s.words}"` : 'You asked for a change.';
  return 'Waiting for you to look.';
}

/* ---------- drawing ---------- */

function styled() {
  if (typeof document === 'undefined' || document.querySelector('link[data-arnheim-show-me]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = CSS;
  link.dataset.arnheimShowMe = '';
  document.head.append(link);
}

function h(tag, props, ...kids) {
  const [name, ...classes] = tag.split('.');
  const el = document.createElement(name || 'div');
  if (classes.length) el.className = classes.join(' ');
  const isProps = props && typeof props === 'object' && !(props instanceof Node) && !Array.isArray(props);
  if (!isProps) kids.unshift(props);
  for (const [key, v] of Object.entries(isProps ? props : {})) {
    if (v == null || v === false) continue;
    if (key.startsWith('on')) el.addEventListener(key.slice(2), v);
    else el.setAttribute(key, v === true ? '' : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : String(kid));
  }
  return el;
}
const btn = (label, onclick, cls = '', glyph = null, more = {}) => h(`button.btn${cls}`, { type: 'button', onclick, ...more }, glyph && icon(glyph, 15), label);

// A made-up picture of a made-up page, drawn from sample/shows.json: rectangles, circles and words, nothing fetched.
function drawn(spec, alt) {
  const w = Number(spec?.w) || 1280;
  const hgt = Number(spec?.h) || 800;
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', `0 0 ${w} ${hgt}`);
  svg.setAttribute('role', 'img');
  svg.setAttribute('aria-label', alt);
  svg.setAttribute('class', 'sm-img sm-drawn');
  const add = (tag, attrs, text) => {
    const el = document.createElementNS(SVG, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    if (text != null) el.textContent = text;
    svg.append(el);
  };
  add('rect', { x: 0, y: 0, width: w, height: hgt, fill: spec?.bg || '#f6f3ee' });
  for (const part of Array.isArray(spec?.parts) ? spec.parts : []) {
    const [kind, ...v] = part;
    if (kind === 'rect') add('rect', { x: v[0], y: v[1], width: v[2], height: v[3], fill: v[4] || '#ddd', rx: v[5] || 0 });
    else if (kind === 'circle') add('circle', { cx: v[0], cy: v[1], r: v[2], fill: v[3] || '#ddd' });
    else if (kind === 'line') add('polyline', { points: v[0], fill: 'none', stroke: v[1] || '#333', 'stroke-width': v[2] || 4, 'stroke-linejoin': 'round' });
    else if (kind === 'text') add('text', { x: v[0], y: v[1], 'font-size': v[2] || 32, fill: v[3] || '#222', 'font-family': 'system-ui, sans-serif', 'font-weight': v[5] || 500 }, v[4] || '');
  }
  return svg;
}

// What the agent said, as words to read: its Markdown marks (bold, code) left out, and a list's dashes as spaces.
export const plainSaid = (text) => String(text || '').replace(/\*\*|__|`/g, '').replace(/(^|[.:!?])\s+[-*]\s+(?=\S)/g, '$1 ').trim();

export function createShowMe(env) {
  styled();
  const control = env.control;
  const where = () => { try { return env.where(); } catch { return 'none'; } };
  const on = () => { try { return env.on() !== false; } catch { return true; } };
  const pictures = new Map(); // "<key>:<n>" -> a data: address, or a promise of one
  const open = new Set(); // keys whose Not quite box is open
  const redraw = () => { try { env.changed?.(); } catch (error) { console.warn('Arnheim: Show me could not redraw.', error); } };
  // Not quite, pressed or swiped: its box opens, ready to type in.
  const opening = (key) => {
    open.add(key);
    redraw();
    requestAnimationFrame(() => [...document.querySelectorAll('.sm-show')].find((el) => el.dataset.smKey === key)?.querySelector('.sm-again input')?.focus());
  };
  let chosen = null; // the card shown in full on Needs you, when another than the first was tapped
  let sample = null; // the made-up cards
  const sampleSaid = new Map(); // key -> { state, words }: what was said to a made-up card, on this page only
  let sig = '';

  async function loadSample() {
    if (sample) return;
    sample = { shows: [] };
    try {
      const r = await fetch(env.sampleUrl(), { cache: 'no-store', credentials: 'same-origin' });
      const got = r.ok ? await r.json() : null;
      const opened = Date.now() / 1000;
      sample = { shows: (got?.shows || []).map((s) => ({ ...s, at: Number(s.at) <= 0 ? opened + Number(s.at) : s.at, sample: true })) };
    } catch {
      sample = { shows: [] };
    }
    redraw();
  }

  // Every card: those waiting for you first, newest first.
  function list() {
    if (!on()) return [];
    const w = where();
    let rows = [];
    if (w === 'live' && control?.on) rows = typeof control.shows === 'function' ? control.shows() : [];
    else if (w === 'sample') {
      if (!sample) loadSample();
      rows = (sample?.shows || []).map((s) => ({ ...s, ...(sampleSaid.get(s.key) || {}) }));
    }
    rows = rows.filter((s) => s && s.key);
    return [...rows.filter((s) => s.state === 'waiting'), ...rows.filter((s) => s.state !== 'waiting')];
  }
  // Waiting for you: the newest of each conversation, since its later work replaces what it showed before.
  const waiting = () => {
    const seen = new Set();
    return list().filter((s) => s.state === 'waiting' && !seen.has(s.conv || s.key) && seen.add(s.conv || s.key));
  };
  const find = (key) => list().find((s) => s.key === key) || null;

  // Control's cards changed: draw the page again (only then, so a picture loading never redraws it).
  if (control?.watch) {
    control.watch((state) => {
      const next = JSON.stringify((state?.shows || []).map((s) => [s.key, s.state, s.pictures?.length, s.proof?.proof?.state, s.proof?.changed]));
      if (next === sig) return;
      sig = next;
      redraw();
    });
  }

  /* ---------- the pictures ---------- */

  // A phone may make 20 requests a minute to control, so there it fetches the phone-width pictures by itself, and the
  // others when tapped. A picture that couldn't be fetched is fetched again when tapped.
  const phone = () => { try { return !!env.phone?.(); } catch { return false; } };
  const later = new Set(); // "<key>:<n>" a phone was asked to fetch, by a tap

  function picture(s, p, alt) {
    if (!p) return h('div.sm-img.sm-none', h('span.small.muted', alt));
    if (s.sample) return p.draw ? drawn(p.draw, alt) : h('div.sm-img.sm-none', h('span.small.muted', alt));
    const id = `${s.key}:${p.n}`;
    const got = pictures.get(id);
    if (got == null && phone() && p.view !== 'phone' && !later.has(id)) {
      return h('span.sm-img.sm-none.sm-fetch', { 'data-sm-fetch': id }, h('span.small', 'Tap to see this picture'));
    }
    const img = h('img.sm-img.sm-loading', { alt, width: p.width || null, height: p.height || null, decoding: 'async' });
    const put = (src) => { if (src) { img.src = src; img.classList.remove('sm-loading'); } else img.classList.add('sm-failed'); };
    if (typeof got === 'string') put(got);
    else {
      const asked = got || (typeof control?.showImage === 'function'
        ? control.showImage(s.key, p.n).then((r) => (r?.data ? `data:${r.type || 'image/png'};base64,${r.data}` : null), () => null)
        : Promise.resolve(null));
      if (!got) pictures.set(id, asked);
      asked.then((src) => {
        if (src) pictures.set(id, src); else pictures.delete(id);
        put(src);
      });
    }
    return img;
  }

  function pairBlock(s, pair, noBefore) {
    const zoom = (event) => {
      const wanted = event.currentTarget.querySelector('[data-sm-fetch]') || (event.currentTarget.querySelector('.sm-failed') ? event.currentTarget : null);
      if (wanted) { // fetch it now, rather than make it bigger
        const p = event.currentTarget.dataset.smN;
        const id = `${s.key}:${p}`;
        later.add(id);
        pictures.delete(id);
        const fresh = picture(s, (s.pictures || []).find((x) => String(x.n) === p), event.currentTarget.getAttribute('aria-label') || 'Picture');
        event.currentTarget.replaceChildren(fresh);
        return;
      }
      event.currentTarget.closest('.sm-pair')?.classList.toggle('sm-zoom');
    };
    return h(`figure.sm-pair.sm-view-${pair.view === 'phone' ? 'phone' : pair.view === 'desktop' ? 'desktop' : 'made'}`,
      h('figcaption.small.muted', icon(pair.view === 'phone' ? 'smartphone' : 'laptop', 14), ' ', pair.label),
      h('div.sm-two',
        h('div.sm-shot',
          h('span.sm-tag', 'Before'),
          pair.before ? h('button.sm-tap', { type: 'button', onclick: zoom, 'data-sm-n': pair.before.n, 'aria-label': `Before, ${pair.label}` }, picture(s, pair.before, `Before, ${pair.label}`))
            : h('div.sm-img.sm-none', h('span.small.muted', noBefore))),
        h('div.sm-shot',
          h('span.sm-tag.sm-tag-after', 'After'),
          pair.after ? h('button.sm-tap', { type: 'button', onclick: zoom, 'data-sm-n': pair.after.n, 'aria-label': `After, ${pair.label}` }, picture(s, pair.after, `After, ${pair.label}`))
            : h('div.sm-img.sm-none', h('span.small.muted', 'No picture from after.')))));
  }

  /* ---------- answering ---------- */

  const failed = (error) => error?.message || "That didn't reach it.";

  function good(s) {
    if (s.sample) {
      sampleSaid.set(s.key, { state: 'approved' });
      return Promise.resolve('Marked as looked at and good. The company is made up, so no agent hears it.');
    }
    return control.showOk(s.key).then((r) => r?.reply || 'Marked as looked at and good.', (error) => { throw new Error(failed(error)); });
  }

  function again(s, words) {
    const said = String(words || '').trim();
    if (!said) return Promise.reject(new Error('Say what should change first.'));
    if (s.sample) {
      sampleSaid.set(s.key, { state: 'again', words: said, learn: { ask: SHOW_ASK } });
      return Promise.resolve('Sent back with what to change. The company is made up, so no agent hears it.');
    }
    return control.showAgain(s.key, said).then(
      (r) => r?.reply || (r?.sent === 'resumed' ? "Sent. It's carrying on with what you said now." : 'Sent. It reads what to change at its next step.'),
      (error) => { throw new Error(failed(error)); });
  }

  const act = (promise) => { open.clear(); env.done(promise, (said) => said); };

  // Yes or No to SHOW_ASK. No says nothing more.
  function learn(s, yes) {
    if (s.sample) {
      sampleSaid.set(s.key, { ...(sampleSaid.get(s.key) || {}), learn: null });
      return Promise.resolve(yes ? 'Done, in this tab only: the company is made up, so nothing is kept.' : '');
    }
    return (yes ? control.learnYes : control.learnNo)({ show: s.key }).then((r) => (yes ? r?.reply || 'Done.' : ''),
      (error) => { throw new Error(failed(error)); });
  }
  const learnPart = (s) => (s.state === 'again' && s.learn?.ask
    ? learnAsk(s.learn.ask, { yes: () => act(learn(s, true)), no: () => act(learn(s, false)) }) : null);

  function againForm(s) {
    const send = (event) => {
      event.preventDefault();
      const input = event.currentTarget.elements.words;
      const text = input.value.trim();
      if (!text) { input.focus(); return; }
      input.value = '';
      input.blur();
      act(again(s, text));
    };
    return h('form.control-say.sm-again', { onsubmit: send },
      h('input', { name: 'words', type: 'text', maxlength: 1500, autocomplete: 'off', placeholder: 'What should change?', 'aria-label': `What should change in ${s.title}` }),
      h('button.btn.primary', { type: 'submit' }, 'Send'),
      !s.sample && env.talkTo ? btn('Say it', () => env.talkTo(s.conv), '.quiet', 'mic', { title: 'Open Talk with the agent and say "not quite", then what to change' }) : null);
  }

  // The swipe, on a phone or any touch screen: the card leans as the finger moves, and lets go to answer.
  function swipeable(el, s) {
    let start = null;
    const lean = (dir) => {
      el.classList.toggle('sm-lean-good', dir === 'good');
      el.classList.toggle('sm-lean-again', dir === 'again');
    };
    el.addEventListener('pointerdown', (event) => {
      if (event.pointerType !== 'touch' || s.state !== 'waiting' || event.target.closest('input, textarea, form')) return;
      start = { x: event.clientX, y: event.clientY, id: event.pointerId };
    });
    el.addEventListener('pointermove', (event) => {
      if (!start || event.pointerId !== start.id) return;
      lean(swipeOf(event.clientX - start.x, event.clientY - start.y, FAR / 2));
    });
    const end = (event) => {
      if (!start || event.pointerId !== start.id) return;
      const dir = event.type === 'pointerup' ? swipeOf(event.clientX - start.x, event.clientY - start.y) : null;
      start = null;
      lean(null);
      if (dir === 'good') act(good(s));
      else if (dir === 'again') opening(s.key);
    };
    el.addEventListener('pointerup', end);
    el.addEventListener('pointercancel', end);
    return el;
  }

  /* ---------- a card ---------- */

  function block(s, { heading = true } = {}) {
    const pr = s.proof ? proofOf(s.proof) : null;
    const mood = proofMood(pr);
    const pairs = pairsOf(s.pictures);
    const noBefore = s.why_before || 'No picture from before: it began before Show me could take one.';
    const output = s.output && typeof s.output === 'object' ? s.output : {};
    const changed = changedWords(s.changed);
    const place = [env.label?.(s.project) || s.project, s.at ? env.ago?.(s.at) : null].filter(Boolean).join(' · ');
    const card = h(`div.sm-show.sm-${s.state || 'waiting'}`, { 'data-sm-key': s.key, role: 'group', 'aria-label': `Show me: ${s.title}` },
      heading ? h('h4.sm-title', s.title) : null,
      h('p.small.muted.sm-where', place),
      s.said ? h('p.small.sm-said', h('span.muted', 'It says: '), plainSaid(s.said)) : null,
      pairs.length ? h('div.sm-pairs', pairs.map((pair) => pairBlock(s, pair, noBefore))) : null,
      output.after ? h('details.explain.sm-out', { open: !pairs.length || null }, h('summary', 'What its show printed'), h('pre.sm-output', output.after)) : null,
      output.before ? h('details.explain.sm-out', h('summary', 'What it printed before the work'), h('pre.sm-output', output.before)) : null,
      !pairs.length && !output.after && s.why ? h('p.small.sm-why', s.why) : null,
      pr ? h('div.sm-proof', h(`span.pill${mood ? `.k-${mood}` : ''}`, pr.word), h('span.small', pr.line)) : null,
      changed ? h('p.small.sm-changed', changed, s.changed?.names?.length ? h('span.muted', ` ${s.changed.names.slice(0, 4).join(', ')}${s.changed.names.length > 4 ? ', and more' : ''}`) : null) : null,
      s.address ? h('p.small.muted', `Pictures of ${s.address}`) : null,
      s.state === 'waiting'
        ? [
          h('div.control-row.sm-do',
            btn('Looks good', () => act(good(s)), '.primary', 'check'),
            btn('Not quite', () => { if (open.has(s.key)) { open.delete(s.key); redraw(); } else opening(s.key); }, '', 'x', { 'aria-expanded': open.has(s.key) ? 'true' : 'false' })),
          open.has(s.key) ? againForm(s) : null,
          h('p.small.muted.sm-swipe-hint', 'Swipe right for Looks good, left for Not quite.'),
        ]
        : [h('p.small.sm-decided', stateLine(s)), learnPart(s)],
      s.held && s.state === 'waiting' ? h('p.small.sm-held', s.held) : null,
      s.sample ? h('p.small.muted', 'Made up, like the rest of this company: these pictures are drawn, and no agent did this work.') : null);
    return swipeable(card, s);
  }

  // Needs you: "3 things to look at", the first (or the one tapped) in full and the rest as rows.
  function needsCard() {
    const rows = waiting();
    const asking = askingOf(list());
    if (!rows.length && !asking.length) return null;
    const first = rows.find((s) => s.key === chosen) || rows[0];
    const rest = rows.filter((s) => s !== first);
    return h('section.panel-card.sm-card', { 'aria-label': 'Show me' },
      h('div.sect-head', icon('monitor', 18), h('h3.sect-title', rows.length ? `Show me: ${lookWords(rows.length)}` : 'Show me')),
      asking.map((s) => h('div.sm-asking', h('p.small', h('b', s.title), h('span.muted', ` You said Not quite: "${s.words || 'change it'}"`)), learnPart(s))),
      first ? block(first) : null,
      rest.length ? h('ul.list.sm-rest', rest.map((s) => h('li',
        h('button.sm-row', { type: 'button', onclick: () => { chosen = s.key; open.clear(); redraw(); } },
          h('b', s.title), h('span.small.muted', ` ${[env.label?.(s.project) || s.project, s.at ? env.ago?.(s.at) : null].filter(Boolean).join(' · ')}`))))) : null);
  }

  // A conversation's page: its latest card, waiting or not.
  function convoCard(c) {
    const mine = list().filter((s) => s.conv === c?.id).sort((a, b) => (Number(b.at) || 0) - (Number(a.at) || 0));
    if (!mine.length) return null;
    const s = mine[0]; // its newest: what it finished last
    return h('section.panel-card.sm-card', { 'aria-label': 'Show me' },
      h('div.sect-head', icon('monitor', 18), h('h3.sect-title', s.state === 'waiting' ? 'Show me: its finished work' : 'Show me')),
      block(s, { heading: false }),
      mine.length > 1 ? h('p.small.muted', `${mine.length - 1} earlier ${mine.length === 2 ? 'card' : 'cards'} from this conversation ${mine.length === 2 ? 'is' : 'are'} kept too.`) : null);
  }

  // Said in Talk to an agent with a card waiting, or typed to it on its page: Looks good, or Not quite and what to change.
  function heard(key, text) {
    const s = waiting().find((x) => x.conv === key);
    const got = s ? heardShow(text) : null;
    if (!got) return null;
    if (got.act === 'ask') return 'What should I change? Say "not quite", then what you would like different.';
    const promise = got.act === 'good' ? good(s) : again(s, got.words);
    return promise.then((said) => { redraw(); return said; }, (error) => error.message);
  }

  return { list, waiting, count: () => waiting().length, find, needsCard, convoCard, heard, block };
}
