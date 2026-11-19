// A one-minute first tour: three short steps, each pointing at a real part of the page (the building, Needs you,
// Walk), with Next, Back and Skip. It shows once per browser (localStorage), on this computer's own page and never
// inside a page that embeds Arnheim or mid-walk; "Show the tour again" opens it any time. Esc closes it, focus moves
// into it and back to where it was, a narrow screen gets it as a sheet along the bottom, and with reduced motion
// nothing slides. The steps and where the card goes are plain, for tests/test_ease.py under Node.

export const TOUR = 'arnheim-tour';

// Each step's target: the first of its selectors that is showing. A step whose targets are all hidden (Walk, with no
// 3D) is left out.
export const STEPS = [
  { target: ['#stage', '#tab-activity'], title: 'Each floor is a project',
    text: 'Tap a floor to bring it out: its rooms show what is going on in that project. Drag to turn the building.' },
  { target: ['#tab-overview'], title: 'Amber means it needs you',
    text: 'A floor lit amber has an agent waiting for your answer, and blue means one is at work. The Needs you tab lists what waits, with its answer beside it.' },
  { target: ['#walk'], title: 'Walk goes inside',
    text: 'Press Walk to step in and talk to the people at work. Settings is where your own projects come in (Connect my agents) and where every feature is switched on or off.' },
];

// Whether the tour opens by itself: a first visit in this browser, on this computer's own page, not inside another
// page, and not mid-walk.
export function tourWanted({ seen = false, embedded = false, away = false, walking = false } = {}) {
  return !seen && !embedded && !away && !walking;
}

// Where the card goes, given its target's box (or none), the card's size and the window's: under the target if it
// fits, else over it, else inside its lower part (the building fills the screen); a sheet at the bottom when narrow.
export function placeCard(target, card, view, { gap = 12, edge = 8, narrow = 600 } = {}) {
  if (view.width <= narrow) return { sheet: true };
  const clampLeft = (x) => Math.max(edge, Math.min(x, view.width - card.width - edge));
  if (!target) return { sheet: false, top: Math.max(edge, (view.height - card.height) / 2), left: clampLeft((view.width - card.width) / 2) };
  if (target.bottom + gap + card.height <= view.height - edge) return { sheet: false, top: target.bottom + gap, left: clampLeft(target.left) };
  if (target.top - gap - card.height >= edge) return { sheet: false, top: target.top - gap - card.height, left: clampLeft(target.left) };
  const bottom = Math.min(target.bottom, view.height);
  return { sheet: false, top: Math.max(edge, bottom - card.height - 24), left: clampLeft(target.left + 24) };
}

export function createTour({ steps = STEPS, doc = globalThis.document, win = globalThis.window, onClose = () => {} } = {}) {
  const el = (tag, cls, text) => {
    const node = doc.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  };
  const button = (text, cls, onclick) => {
    const b = el('button', `btn${cls ? ` ${cls}` : ''}`, text);
    b.type = 'button';
    b.addEventListener('click', onclick);
    return b;
  };
  const reduced = () => !!win.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

  const ring = el('div', 'tour-ring');
  ring.setAttribute('aria-hidden', 'true');
  const card = el('div', 'tour');
  card.id = 'tour';
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-modal', 'true');
  card.setAttribute('aria-labelledby', 'tour-title');
  card.setAttribute('aria-describedby', 'tour-text');
  const count = el('p', 'tour-count');
  const title = el('h2', 'tour-title');
  title.id = 'tour-title';
  title.tabIndex = -1;
  const text = el('p', 'tour-text');
  text.id = 'tour-text';
  const back = button('Back', '', () => show(at - 1));
  const next = button('Next', 'primary', () => (at >= list.length - 1 ? close() : show(at + 1)));
  const skip = button('Skip', 'quiet', () => close());
  const row = el('div', 'tour-do');
  row.append(back, next, skip);
  card.append(count, title, text, row);

  let open = false;
  let at = 0;
  let list = [];
  let before = null; // what had focus, to go back to
  let target = null;

  const showing = (node) => {
    if (!node || !node.isConnected) return false;
    const box = node.getBoundingClientRect();
    return box.width > 0 && box.height > 0 && win.getComputedStyle(node).visibility !== 'hidden';
  };
  const targetOf = (step) => step.target.map((s) => doc.querySelector(s)).find(showing) || null;

  function place() {
    if (!open) return;
    const view = { width: win.innerWidth, height: win.innerHeight };
    const box = target && showing(target) ? target.getBoundingClientRect() : null;
    ring.hidden = !box;
    if (box) {
      const pad = 6;
      Object.assign(ring.style, { top: `${box.top - pad}px`, left: `${box.left - pad}px`, width: `${box.width + pad * 2}px`, height: `${box.height + pad * 2}px` });
    }
    card.classList.remove('sheet');
    Object.assign(card.style, { top: '', left: '' });
    const spot = placeCard(box, { width: card.offsetWidth, height: card.offsetHeight }, view);
    if (spot.sheet) card.classList.add('sheet');
    else Object.assign(card.style, { top: `${Math.round(spot.top)}px`, left: `${Math.round(spot.left)}px` });
  }

  function show(n) {
    at = Math.max(0, Math.min(n, list.length - 1));
    const step = list[at];
    count.textContent = `${at + 1} of ${list.length}`;
    title.textContent = step.title;
    text.textContent = step.text;
    back.hidden = at === 0;
    next.textContent = at === list.length - 1 ? 'Done' : 'Next';
    target = targetOf(step);
    if (target) {
      const narrow = win.innerWidth <= 600;
      target.scrollIntoView({ block: narrow ? 'center' : 'nearest', inline: 'nearest', behavior: reduced() ? 'auto' : 'smooth' });
    }
    place();
    title.focus({ preventScroll: true });
  }

  function keys(event) {
    if (!open) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === 'Tab') {
      const stops = [back, next, skip].filter((b) => !b.hidden);
      const i = stops.indexOf(doc.activeElement);
      if (event.shiftKey ? i <= 0 : i === stops.length - 1 || i < 0) {
        event.preventDefault();
        (event.shiftKey ? stops[stops.length - 1] : stops[0]).focus();
      }
    }
  }

  function close() {
    if (!open) return;
    open = false;
    ring.remove();
    card.remove();
    win.removeEventListener('keydown', keys, true);
    win.removeEventListener('resize', place);
    win.removeEventListener('scroll', place, true);
    const to = before && before.isConnected ? before : null;
    before = null;
    if (to) to.focus({ preventScroll: true });
    onClose();
  }

  return {
    // Opens at the first step. False when there is nothing to point at, or it is already open.
    open() {
      if (open) return false;
      list = steps.filter((s) => targetOf(s));
      if (!list.length) return false;
      open = true;
      before = doc.activeElement && doc.activeElement !== doc.body ? doc.activeElement : null;
      card.classList.toggle('still', reduced());
      doc.body.append(ring, card);
      win.addEventListener('keydown', keys, true);
      win.addEventListener('resize', place);
      win.addEventListener('scroll', place, true);
      show(0);
      return true;
    },
    close,
    get isOpen() { return open; },
  };
}
