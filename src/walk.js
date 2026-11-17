// Walking the building in first person. The building lends its scene, camera and floors; this
// adds the halls (three/halls.js), the controls on the page, the lift and the burn between floors
// (three/burn.js), and gives everything back when the walk ends. It loads only when someone walks.
import * as THREE from '../vendor/three/three.module.js';
import { ShaderPass } from '../vendor/three/addons/postprocessing/ShaderPass.js';
import { createBurn } from './three/burn.js';
import { buildHall, buildPenthouse } from './three/halls.js';
import { buildPerson, lookSpec } from './three/poe.js';
import { dressHall, loadPhoto, photoWanted } from './three/photo.js';
import { createWalkNotes } from './walk-notes.js';
import { D, H, W } from './three/rooms.js';
import { createVoice } from './voice.js';
import { leadSpot, crossingOnly } from './lead-spot.js';

const EYE = 1.62;
const WALK = 1.5; // metres a second
const RUN = 3;
const RADIUS = 0.22; // how close you can come to a wall
const CELL = 0.2; // the floor plan that stops you is drawn in squares this size
const STRIDE = 0.74;
const QUIET_MS = 4000; // the hand-held drift fades this long after the last touch
const CURB = 0.14;
const SHUTTER = 1 / 160; // seconds: the motion blur is what a phone's shutter would catch
const MOVES = new Set(['KeyW', 'KeyA', 'KeyS', 'KeyD', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ShiftLeft', 'ShiftRight']);

// The look of phone footage, drawn last: a little motion blur as the camera turns, softer
// corners, a faint vignette and fine grain that is stronger in the shadows. Kept subtle, and
// off for anyone who asks for reduced motion.
const FOOTAGE = {
  uniforms: {
    tDiffuse: { value: null }, uVel: { value: new THREE.Vector2() }, uRes: { value: new THREE.Vector2(1, 1) },
    uTime: { value: 0 }, uGrain: { value: 1 }, uSoft: { value: 1 },
  },
  vertexShader: /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  fragmentShader: /* glsl */ `
uniform sampler2D tDiffuse;
uniform vec2 uVel;
uniform vec2 uRes;
uniform float uTime;
uniform float uGrain;
uniform float uSoft;
varying vec2 vUv;
float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
void main() {
  vec2 c = vUv - 0.5;
  float edge = dot(c, c) * 2.0;
  vec4 sum = vec4(0.0);
  for (int i = 0; i < 7; i++) {
    float t = float(i) / 6.0 - 0.5;
    sum += texture2D(tDiffuse, vUv + uVel * t + c * (edge * uSoft * 0.012 * t));
  }
  vec4 col = sum / 7.0;
  float n = hash(floor(vUv * uRes) + fract(uTime * 7.31) * 113.0) - 0.5;
  float luma = dot(col.rgb, vec3(0.299, 0.587, 0.114));
  col.rgb += n * uGrain * (0.045 - 0.025 * luma);
  col.rgb *= 1.0 - edge * 0.16;
  gl_FragColor = col;
}`,
};

// The walk's look lives in walk.css, added as a stylesheet link rather than a <style> tag, so a page
// whose content security policy allows only its own files (style-src 'self') takes it too. Resolves
// once it has loaded, or failed (the walk still works, plainly), or after four seconds.
// Starts the real materials loading before the walk shows, so it can open on the finished rooms.
// Returns null when this device keeps the drawn ones (photo.js decides).
export function preparePhoto(renderer) {
  if (!photoWanted(renderer)) return null;
  const job = { value: null, failed: false, k: 0, listen: null };
  job.promise = loadPhoto(renderer, (k) => { job.k = k; job.listen?.(k); }).then(
    (p) => { job.value = p; return p; },
    (error) => { job.failed = true; throw error; },
  );
  job.promise.catch(() => {}); // the walk reports a failure itself
  return job;
}

let styled = null;
export function loadStyle() {
  if (styled) return styled;
  const link = document.createElement('link');
  link.id = 'arnheim-walk-style';
  link.rel = 'stylesheet';
  link.href = new URL('./walk.css', import.meta.url).href;
  styled = new Promise((resolve) => {
    link.addEventListener('load', resolve, { once: true });
    link.addEventListener('error', resolve, { once: true });
    setTimeout(resolve, 4000);
  });
  document.head.append(link);
  return styled;
}

export function createWalk(ctx) {
  const { scene, camera, canvas, renderer, storeys, reduced } = ctx;
  const stage = canvas.parentElement;
  const coarse = window.matchMedia('(pointer: coarse)').matches;
  const still = () => reduced.matches;
  const listeners = new AbortController();
  const { signal } = listeners;
  const burn = createBurn(scene, { count: coarse || stage.clientWidth < 820 ? 20000 : 46000 });
  const footage = new ShaderPass(FOOTAGE);
  footage.enabled = !still();
  ctx.composer.addPass(footage);
  const px = new THREE.Vector2();
  let lastYaw = 0;
  let lastPitch = 0;
  // The real materials (photo.js): they start loading as the walk begins, unless this device
  // should keep it light; until they arrive, and if they never do, the drawn ones stand.
  const job = ctx.photo || null; // started by preparePhoto before the walk showed
  let photo = job?.value || null;
  let photoState = !job ? 'off' : photo ? 'on' : job.failed ? 'failed' : 'loading';
  let loadTimer = 0;
  let gone = false;
  const hitMaterial = new THREE.MeshBasicMaterial();
  const halls = new Map();
  const ray = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  const v = new THREE.Vector3();
  const ahead = new THREE.Vector3();
  const order = [...storeys].sort((a, b) => b.y - a.y); // top floor first
  // The founder's office (three/halls.js): a floor above the others that only the walk has, at the
  // top of the lift's list. Its height only matters to its own light.
  const founder = ctx.org.founder || null;
  const given = founder?.firstName || founder?.name?.trim().split(/\s+/)[0] || '';
  const penthouse = {
    id: 'penthouse', label: given ? `${given}'s office` : 'Penthouse', role: 'penthouse', rooms: [],
    group: new THREE.Group(), y: order[0].y + H + 0.3,
  };
  penthouse.group.position.set(order[0].group.position.x, penthouse.y, order[0].group.position.z);
  penthouse.group.visible = false;
  scene.add(penthouse.group);
  order.unshift(penthouse);
  const me = {
    x: 0, z: 0, yaw: 0, pitch: -0.05, yawGoal: 0, pitchGoal: -0.05, vx: 0, vz: 0, speed: 0,
    phase: 0, amp: 0, dip: 0, dipV: 0, striding: false, target: null, stuck: 0,
  };
  const keys = new Set();
  const stick = { x: 0, y: 0, id: null };
  let here = null;
  let hall = null;
  let map = null;
  let doors = new Map(); // a baked room's key -> [x, z] of its doorway, [x, z] just outside it, and its width either side (findDoors)
  let ride = null;
  let inLift = false;
  let press = null;
  let lastTap = null;
  let lastInput = performance.now();
  let seen = ctx.version();
  let surveyed = 0;
  let cardTimer = 0;

  /* ---------- the controls on the page ---------- */

  loadStyle(); // already loaded when the building started the walk; this only covers other callers
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
  const hud = el('div', 'aw-hud');
  const floorName = button('', () => (picker.hidden ? openPicker() : closePicker()), 'Choose a floor for the lift');
  floorName.classList.add('aw-name');
  const floorBox = el('div', 'aw-floor');
  const helpButton = button('?', () => showHelp(help.classList.contains('aw-faded')), 'Show how to walk');
  const downButton = button('▼', () => stepFloor(-1), 'Take the lift down a floor');
  const upButton = button('▲', () => stepFloor(1), 'Take the lift up a floor');
  floorBox.append(downButton, floorName, upButton, helpButton);
  // ▲ on the top floor and ▼ on the bottom one, or either while the lift moves, can't go: they say so
  let liftDrawn = '';
  function drawLiftButtons() {
    const i = order.indexOf(here);
    const sig = `${i}:${!!ride}`;
    if (sig === liftDrawn) return;
    liftDrawn = sig;
    const top = i <= 0;
    const bottom = i >= order.length - 1;
    // aria-disabled, not disabled: a button that keeps its focus (the press itself is refused by stepFloor and rideTo)
    upButton.setAttribute('aria-disabled', String(!!ride || top));
    downButton.setAttribute('aria-disabled', String(!!ride || bottom));
    upButton.setAttribute('aria-label', top ? 'The top floor: the lift goes no higher' : 'Take the lift up a floor');
    downButton.setAttribute('aria-label', bottom ? 'The bottom floor: the lift goes no lower' : 'Take the lift down a floor');
    upButton.title = top ? 'The top floor' : '';
    downButton.title = bottom ? 'The bottom floor' : '';
  }
  // Take me to what needs me: shown while anything in the building needs you, with how many. Each press
  // goes to the next one, by the lift if it is on another floor.
  const needsButton = button('', () => goToNeeds(), 'Take me to what needs me');
  needsButton.classList.add('aw-needs');
  needsButton.hidden = true;
  hud.append(button('Leave', () => ctx.leave(), 'Leave the walk'), needsButton, floorBox);
  const picker = el('div', 'aw-picker');
  picker.hidden = true;
  picker.setAttribute('role', 'dialog');
  picker.setAttribute('aria-label', 'The lift');
  const card = el('div', 'aw-card');
  card.hidden = true;
  card.setAttribute('role', 'status');
  const cardTitle = el('b');
  const cardSub = el('span');
  const cardText = el('div');
  cardText.append(cardTitle, cardSub);
  const openButton = button('Open', () => ctx.leave(), 'Leave the walk and open this in the list');
  card.append(cardText, openButton);
  // How to walk, said for the hands in use; the burn is only mentioned where it plays (not with reduced motion).
  const helpText = () => (coarse
    ? `Walk with the stick and drag to look. Tap the floor to go there, or someone to walk over and talk. The lift is where you arrive, and ▲ ▼ at the top take it from anywhere.${still() ? '' : ' Double-tap to burn this floor and rebuild it.'} ? brings this back.`
    : `WASD or the arrow keys to walk, Shift to hurry, drag to look. Click the floor to go there, or someone to walk over and talk. The lift is where you arrive, and ▲ ▼ at the top (or Page Up and Page Down) take it from anywhere.${still() ? '' : ' Double-click to burn this floor and rebuild it.'} Esc to leave, ? brings this back.`);
  const help = el('p', 'aw-help', helpText());
  const stickEl = el('div', 'aw-stick');
  const knob = el('span');
  stickEl.append(knob);
  stickEl.setAttribute('aria-hidden', 'true');
  const loading = el('div', 'aw-load');
  loading.setAttribute('role', 'status');
  const loadingText = el('span', null, 'Loading real materials');
  const loadingBar = el('b');
  const track = el('i');
  track.append(loadingBar);
  loading.append(loadingText, track);
  loading.hidden = photoState !== 'loading';
  // A small floor plan, bottom right: the floor you can walk, where you are and which way you face, the
  // people's rings (filled where they wait on you), what else waits on you, and the lift. A tap on it walks
  // you there. Its button folds it away to a small Map button, remembered in this browser.
  const planBox = el('div', 'aw-plan');
  const plan = el('canvas');
  plan.setAttribute('role', 'img');
  const planToggle = button('', () => setPlan(planBox.classList.contains('aw-plan-off')), '');
  planToggle.classList.add('aw-plan-toggle');
  planBox.append(plan, planToggle);
  stage.append(hud, picker, card, help, stickEl, loading, planBox);
  stage.classList.add('arnheim-walking');
  // Talking with whoever's ring you stand in, by typing or out loud (voice.js).
  const voice = createVoice({ hud, card, ctx, el, button, signal });
  let helpTimer = 0;
  function showHelp(on = true) {
    clearTimeout(helpTimer);
    help.textContent = helpText();
    help.classList.toggle('aw-faded', !on);
    helpButton.setAttribute('aria-pressed', String(on));
    if (on) helpTimer = setTimeout(() => showHelp(false), 12000);
  }
  showHelp();
  // The founder's notes, hung in their office (walk-notes.js): the page gives them and is asked for more.
  const notes = createWalkNotes({
    stage, signal, coarse, notes: ctx.notes?.(), ask: () => ctx.onNotes?.(), wake: ctx.wake,
    hideCard() { clearTimeout(cardTimer); card.hidden = true; },
    remap() { if (here === penthouse && !ride) look(); },
  });

  function openPicker() {
    if (ride) return;
    const pick = (text, run, label) => {
      const b = el('button', 'aw-btn', text);
      b.type = 'button';
      b.setAttribute('aria-label', label);
      b.onclick = run;
      return b;
    };
    const list = el('ul');
    for (const s of order) {
      const b = pick(s.label, () => rideTo(s), s === here ? `${s.label}, you are here` : `Take the lift to ${s.label}`);
      if (s === here) { b.setAttribute('aria-current', 'true'); b.disabled = true; }
      const item = el('li');
      item.append(b);
      list.append(item);
    }
    // what is on this floor first, a tap walking you there
    const guide = el('ul', 'aw-guide');
    for (const g of onThisFloor()) {
      const b = pick('', () => { closePicker(); g.go(); }, `Walk to ${g.title}`);
      b.classList.add('aw-go', `aw-go-${g.kind}`);
      b.append(el('b', null, g.title));
      if (g.sub) b.append(el('span', null, g.sub));
      const item = el('li');
      item.append(b);
      guide.append(item);
    }
    const where = resumed ? `Back on ${here.label}, where you left off` : `On ${here.label}`;
    resumed = false; // said once, as the walk opens
    picker.replaceChildren(...(guide.children.length ? [el('p', null, where), guide] : []), el('p', null, 'Take the lift to'), list);
    picker.hidden = false;
    card.hidden = true;
  }
  function closePicker() { picker.hidden = true; }

  /* ---------- the floor plan ---------- */

  let planBase = null; // the floor's walkable squares, one pixel each, drawn again at each survey
  let planCrop = null; // the part of the plan that can be walked, so the small picture is all floor
  let planFit = null;
  let planSig = '';
  let planNeeds = new Set(); // the keys of what waits on you on this floor (drawNeeds keeps it)
  function setPlan(on) {
    planBox.classList.toggle('aw-plan-off', !on);
    planToggle.textContent = on ? 'Hide' : 'Map';
    planToggle.setAttribute('aria-label', on ? 'Fold the floor plan away' : 'Show the floor plan');
    try { localStorage.setItem('arnheim-walk-plan', on ? 'on' : 'off'); } catch { /* a private window: it simply isn't remembered */ }
    planSig = '';
    planSize = [0, 0]; // measured again as it opens
    drawPlan();
  }
  function planBaseOf() {
    planBase = null;
    if (!map) return;
    const { cols, rows } = map;
    const open = reach();
    const base = document.createElement('canvas');
    base.width = cols;
    base.height = rows;
    const g = base.getContext('2d');
    const img = g.createImageData(cols, rows);
    let q0 = cols, q1 = -1, r0 = rows, r1 = -1;
    for (let i = 0; i < open.length; i++) {
      if (!open[i]) continue;
      img.data.set([236, 226, 210, 120], i * 4);
      const q = i % cols;
      const r = (i - q) / cols;
      q0 = Math.min(q0, q); q1 = Math.max(q1, q); r0 = Math.min(r0, r); r1 = Math.max(r1, r);
    }
    if (q1 < 0) return;
    g.putImageData(img, 0, 0);
    planBase = base;
    const c0 = Math.max(0, q0 - 2);
    const d0 = Math.max(0, r0 - 2);
    planCrop = { q0: c0, r0: d0, w: Math.min(cols, q1 + 3) - c0, h: Math.min(rows, r1 + 3) - d0 };
    planSig = '';
  }
  // its size: measured once when first drawn (or unfolded), then kept up to date by a ResizeObserver, so
  // no frame reads the page's layout
  let planSize = [0, 0];
  const planWatch = new ResizeObserver(([entry]) => {
    planSize = [entry.contentRect.width, entry.contentRect.height];
    planSig = '';
    drawPlan();
  });
  planWatch.observe(plan);
  function drawPlan() {
    if (!planBase || !here || planBox.classList.contains('aw-plan-off')) return;
    if (!planSize[0] || !planSize[1]) planSize = [plan.clientWidth, plan.clientHeight];
    const [w, h] = planSize;
    if (!w || !h) return;
    const sig = [w, h, here.id, me.x.toFixed(2), me.z.toFixed(2), me.yaw.toFixed(2), spots.length, talking?.ring?.id || 0, [...planNeeds].join('|')].join(',');
    if (sig === planSig) return;
    planSig = sig;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (plan.width !== Math.round(w * dpr) || plan.height !== Math.round(h * dpr)) { plan.width = Math.round(w * dpr); plan.height = Math.round(h * dpr); }
    const g = plan.getContext('2d');
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    const c = planCrop;
    const k = Math.min((w - 10) / c.w, (h - 10) / c.h);
    const ox = (w - c.w * k) / 2;
    const oy = (h - c.h * k) / 2;
    planFit = { k, ox, oy };
    g.imageSmoothingEnabled = false;
    g.drawImage(planBase, c.q0, c.r0, c.w, c.h, ox, oy, c.w * k, c.h * k);
    const at = (x, z) => [ox + ((x - map.x0) / CELL - c.q0) * k, oy + ((z - map.z0) / CELL - c.r0) * k];
    const L = hall.lift;
    const [lx, ly] = at(L.x, L.z);
    g.strokeStyle = 'rgba(255, 255, 255, .75)';
    g.lineWidth = 1.5;
    g.strokeRect(lx - 4, ly - 4, 8, 8);
    for (const room of here.rooms) {
      const r = roomAround(room);
      for (const o of room.objects) {
        if (o.figure || !planNeeds.has(keyOfThing(o))) continue;
        const [x, y] = at(r.x + o.x, r.z + o.z);
        g.fillStyle = '#ffb35c';
        g.fillRect(x - 3, y - 3, 6, 6);
      }
    }
    for (const spot of spots) {
      const [x, y] = at(spot.x, spot.z);
      g.beginPath();
      g.arc(x, y, 3.2, 0, Math.PI * 2);
      if (planNeeds.has(keyOfThing(spot.who))) { g.fillStyle = '#ffb35c'; g.fill(); } else { g.strokeStyle = '#ffc985'; g.lineWidth = 1.5; g.stroke(); }
    }
    // you: a dot and the way you face
    const [mx, my] = at(me.x, me.z);
    const fx = -Math.sin(me.yaw);
    const fy = -Math.cos(me.yaw);
    g.fillStyle = 'rgba(255, 255, 255, .28)';
    g.beginPath();
    g.moveTo(mx, my);
    g.arc(mx, my, 16, Math.atan2(fy, fx) - 0.5, Math.atan2(fy, fx) + 0.5);
    g.closePath();
    g.fill();
    g.fillStyle = '#ffffff';
    g.beginPath();
    g.arc(mx, my, 3.6, 0, Math.PI * 2);
    g.fill();
    plan.setAttribute('aria-label', `Floor plan of ${here.label}: you are the white dot. Tap a place to walk there.`);
  }
  // a tap on the plan walks you to that place, round whatever is in the way
  plan.addEventListener('click', (event) => {
    if (!planFit || ride) return;
    const box = plan.getBoundingClientRect();
    const c = planCrop;
    const x = map.x0 + ((event.clientX - box.left - planFit.ox) / planFit.k + c.q0) * CELL;
    const z = map.z0 + ((event.clientY - box.top - planFit.oy) / planFit.k + c.r0) * CELL;
    const goal = roomAt(x, z);
    const way = goal && wayTo(goal.x, goal.z);
    if (!way) return;
    closePicker();
    me.target = { ...way.shift(), next: way, open: true };
    input();
  }, { signal });

  /* ---------- finding your way: what is on this floor, and what needs you ---------- */

  const keyOfThing = (o) => o.href || o.title;
  // What waits on you: a thing whose own state says so (a task, a budget), or one the page lists as waiting
  // for you (talk.waiting: an agent's permission request or question, which the building shows as at work).
  const WAIT_WORDS = { permission: 'Wants your permission', question: 'Asks you', turn: 'Your turn' };
  function waitingOn() {
    let list = [];
    try { list = ctx.talk?.waiting?.() || []; } catch (error) { console.warn('Arnheim: no waiting list.', error); }
    // its conversation's id decides when it has one (two seats can share a title); the title only when it hasn't
    const at = (o) => list.findIndex((i) => (i.key ? !!o.href?.endsWith(`/${i.key}`) : !!i.title && i.title === o.title));
    const waits = (o) => {
      const i = at(o);
      return i >= 0 ? WAIT_WORDS[list[i].kind] || 'Needs you' : o.mood === 'needs' ? 'Needs you' : null;
    };
    waits.rank = (o) => { const i = at(o); return i >= 0 ? i : list.length; }; // the page's own order: its first is ours
    return waits;
  }
  const roomAround = (room) => room.g?.position || { x: 0, z: 0 }; // a baked floor's rooms are in the floor's own coordinates

  // Walks to a spot on this floor, round whatever is in the way, turning to face `face` on arrival.
  function walkTo(x, z, face) {
    const goal = roomAt(x, z);
    const way = goal && wayTo(goal.x, goal.z);
    if (!way) return false;
    me.target = { ...way.shift(), next: way, face };
    input();
    return true;
  }

  // A thing that needs you: someone with a ring is walked to and talked to; anything else is walked up to
  // and opened in the panel, so it can be answered there.
  function goToThing(o, room) {
    const hit = o.hit?.userData || o; // what a tap on it gives: its title, page and place
    if (o.figure && ringOf(hit) && walkToTalk(hit)) return true;
    const r = roomAround(room);
    const x = r.x + o.x;
    const z = r.z + o.z;
    if (!walkTo(x, z, [x, z])) return false;
    showCard(hit);
    if (!hit.stay) ctx.onPick?.({ ...hit, walk: true });
    return true;
  }

  // A room: a drawn one just inside its open front, a baked one just inside its doorway (or its middle).
  function goToRoom(room) {
    if (room.g) {
      const p = room.g.position;
      return walkTo(p.x + W / 2, p.z + D - 0.9, [p.x + W / 2, p.z + D / 2]);
    }
    const c = room.centre;
    const door = doors.get(room.key);
    if (c && walkTo(c[0], c[1], null)) return true;
    return !!door && walkTo(door[0], door[1], c || null);
  }

  // Who and what is on this floor, for the guide: what needs you first, then the people you can talk to,
  // then the rooms you can reach.
  function onThisFloor() {
    if (!here || !map) return [];
    const out = [];
    const seen = new Set();
    const waits = waitingOn();
    for (const room of here.rooms) {
      for (const o of room.objects) {
        const why = waits(o);
        if (!why || seen.has(keyOfThing(o))) continue;
        seen.add(keyOfThing(o));
        out.push({ kind: 'needs', title: o.title, sub: `${why}, in ${room.label}`, go: () => goToThing(o, room) });
      }
    }
    // the floor's lead first: they can tell you everything else on it
    for (const spot of [...spots].sort((a, b) => (b.who.roomId === 'lead') - (a.who.roomId === 'lead')).slice(0, 8)) {
      if (seen.has(keyOfThing(spot.who))) continue;
      seen.add(keyOfThing(spot.who));
      out.push({ kind: 'person', title: spot.who.title, sub: spot.who.sub || '', go: () => walkToTalk(spot.who) });
    }
    for (const room of here.rooms) {
      if (!room.label || (!room.g && !room.centre && !doors.has(room.key))) continue;
      out.push({ kind: 'room', title: room.label, sub: ctx.infoText(room.info) || '', go: () => goToRoom(room) });
    }
    return out;
  }

  // Everything in the building that waits on you, in the page's own order (so the first is the home view's
  // first), then the rest: this floor's first, then the floors in the lift's order.
  function needsAll() {
    const out = [];
    const seen = new Set();
    const waits = waitingOn();
    for (const s of [here, ...order.filter((f) => f !== here)]) {
      if (!s) continue;
      for (const room of s.rooms || []) {
        for (const o of room.objects || []) {
          if (!waits(o) || seen.has(keyOfThing(o))) continue;
          seen.add(keyOfThing(o));
          out.push({ s, room, o, rank: waits.rank(o) });
        }
      }
    }
    return out.sort((a, b) => a.rank - b.rank); // stable: what the page doesn't list keeps this floor first
  }

  let needsTimer = 0; // started once the walk is open (at the end of createWalk)
  let resumed = false; // this walk started where the last one was left
  let needsGone = new Set(); // the ones this walk has taken you to, so the next press goes on to the next
  let afterRide = null; // what to do once the lift has brought you to another floor
  function drawNeeds() {
    const all = needsAll();
    planNeeds = new Set(all.filter((x) => x.s === here).map((x) => keyOfThing(x.o)));
    drawPlan();
    const n = all.length;
    needsButton.hidden = !n;
    needsButton.replaceChildren(el('span', 'aw-needs-word', 'Needs you'), el('b', null, String(n)));
    needsButton.setAttribute('aria-label', `Take me to what needs me: ${n} waiting`);
  }
  function goToNeeds() {
    if (ride) return;
    const all = needsAll();
    if (!all.length) { drawNeeds(); return; }
    let next = all.find((n) => !needsGone.has(keyOfThing(n.o)));
    if (!next) { needsGone = new Set(); next = all[0]; } // been to each: round again
    needsGone.add(keyOfThing(next.o));
    closePicker();
    if (next.s === here) { goToThing(next.o, next.room); return; }
    afterRide = () => goToThing(next.o, next.room);
    rideTo(next.s);
  }
  // A ride has ended on the floor it was for: whatever was waiting for it, or the guide to the floor.
  function arrived() {
    const then = afterRide;
    afterRide = null;
    if (then) then();
    else openPicker();
  }

  // A card naming what was tapped, for a few seconds; or, while someone stands in a talking ring,
  // naming who they are with, for as long as they stay.
  function showCard(hit, talk = false) {
    const info = ctx.describe(hit) || {};
    cardTitle.textContent = info.title || hit.title || '';
    cardSub.textContent = info.sub || '';
    cardSub.hidden = !cardSub.textContent;
    openButton.hidden = !!hit.stay; // a thing of the walk's own, with nothing to open in the list
    card.classList.toggle('aw-talking', talk);
    card.hidden = false;
    clearTimeout(cardTimer);
    if (!talk) cardTimer = setTimeout(() => { if (talking) showCard(talking.who, true); else card.hidden = true; }, 7000);
  }

  function input() {
    lastInput = performance.now();
    ctx.touched();
    ctx.wake(2);
  }

  /* ---------- floors and halls ---------- */

  function hallFor(s) {
    let entry = halls.get(s.id);
    if (entry) return entry;
    // A building can give its own halls (photo-building.js: the baked floor's corridor, lift and reception).
    entry = ctx.hallFor?.(s, s === penthouse ? { penthouse: true, founder, assistant: ctx.org.assistant || null } : null) || (s === penthouse
      ? buildPenthouse(s, { founder, assistant: ctx.org.assistant || null })
      : buildHall(s, { company: ctx.org.company, mission: ctx.org.mission }));
    if (photo) dressHall(entry, photo);
    if (s === penthouse) notes.hang(entry);
    const person = ctx.personRoom;
    if (entry.poe && person?.storey === s) {
      const P = person.spec.person;
      const hit = new THREE.Mesh(new THREE.BoxGeometry(0.8, 1.1, 0.6), hitMaterial);
      hit.position.set(entry.poe.x, 1.05, entry.poe.z);
      hit.visible = false;
      hit.userData = { hit: true, talk: true, floorId: person.floorId, roomId: person.roomId, href: P.href, title: P.name, sub: `${P.title || 'Receptionist'}. Tap to talk.` };
      entry.group.add(hit);
      entry.picks.push(hit);
    }
    halls.set(s.id, entry);
    return entry;
  }

  // The rooms open onto the hall: no front walls, and a full wall at the far end.
  function setWalls(s, on) {
    for (const r of s.rooms) if (r.walls) r.walls.s.visible = !on;
    const last = s.rooms[s.rooms.length - 1];
    if (last?.walls) last.walls.e.scale.y = on ? H : CURB;
  }

  // The receptionist stands behind the hall's reception desk while you walk, and goes back to their room
  // after. Their room's counter is put away meanwhile, so there is only ever one reception desk.
  function placeReceptionist(on) {
    const room = ctx.personRoom;
    if (!room?.person || room.storey !== here || !hall?.poe || hall.baked) return; // a baked hall's receptionist is already at their desk
    const P = room.spec.person;
    const body = room.person.group;
    if (room.counter) room.counter.visible = !on;
    if (on) {
      hall.group.add(body);
      body.position.set(hall.poe.x, 0, hall.poe.z);
      body.rotation.y = hall.poe.turn;
      room.lamp2.set(hall.poe.x - room.g.position.x + 0.5, 1.9, hall.poe.z - room.g.position.z + 0.9);
    } else {
      room.g.add(body);
      body.position.set(...P.at);
      body.rotation.y = P.turn;
      room.lamp2.set(...room.spec.lamps.side);
    }
  }

  function chest(out) {
    const p = here.group.position;
    return out.set(p.x + me.x, p.y + 1.1, p.z + me.z);
  }

  function enter(s, spawn) {
    if (here) leave(here);
    here = s;
    hall = hallFor(s);
    ctx.entered?.(s, hall);
    if (!hall.group.parent) s.group.add(hall.group);
    hall.group.visible = true;
    setWalls(s, true);
    placeReceptionist(true);
    s.group.visible = true;
    look();
    // off a ride in the real lift's car, you stand where you stood in it: the car is the same on every floor
    const at = spawn === 'car' && hall.car ? { x: me.x, z: me.z, yaw: me.yawGoal } : spawn === 'entrance' && hall.entrance ? hall.entrance : hall.spot;
    me.x = at.x;
    me.z = at.z;
    me.yaw = me.yawGoal = at.yaw;
    me.pitch = me.pitchGoal = -0.05;
    me.vx = me.vz = me.speed = 0;
    me.target = null;
    free();
    if (placeLead(s)) look(); // they stand in the way now, as anyone does
    placeSpots();
    findDoors();
    planBaseOf();
    hall.lift.open = 0;
    hall.setDoors(0);
    inLift = hall.inLift(me.x, me.z);
    floorName.textContent = s.label;
    drawLiftButtons();
    drawNeeds(); // the button's count, and this floor's marks on the plan
    const p = s.group.position;
    ctx.shadows(new THREE.Vector3(p.x + (hall.west + hall.east) / 2, p.y + 1, p.z + hall.front / 2), Math.max(hall.east - hall.west, hall.front) / 2 + 2);
  }

  function leave(s) {
    setTalk(null);
    setWalls(s, false);
    placeReceptionist(false);
    const entry = halls.get(s.id);
    if (entry) entry.group.visible = false;
    s.group.visible = false;
  }

  // Reads the floor as it stands: what stops you (anything between knee and chest height, drawn
  // onto a grid) and what a tap can land on.
  // The floor's fixed part (its walls, the hall, the lift) is surveyed once a visit; a live change (people
  // moving seats, a desk coming or going) only looks again at what stands in the rooms, which is all it can
  // change. `again`: the survey of the fixed part from the last full one.
  function survey(s, again = null) {
    s.group.updateMatrixWorld(true);
    const inv = new THREE.Matrix4().copy(s.group.matrixWorld).invert();
    const m = new THREE.Matrix4();
    const a = new THREE.Vector3();
    const b = new THREE.Vector3();
    const c = new THREE.Vector3();
    const x0 = hall.west - 0.4;
    const z0 = (hall.north ?? 0) - 0.4;
    const cols = Math.ceil((hall.east + 0.4 - x0) / CELL);
    const rows = Math.ceil((hall.front + 0.4 - z0) / CELL);
    const contents = new Set(s.rooms.map((r) => r.content).filter(Boolean)); // what live changes replace
    const same = again && again.cols === cols && again.rows === rows && again.x0 === x0 && again.z0 === z0;
    const cells = same ? again.cells.slice() : new Uint8Array(cols * rows); // what stops you
    const sight = same ? again.sight.slice() : new Uint8Array(cols * rows); // what hides a name behind it: walls and tall things
    const solids = same ? again.solids.slice() : [];
    const mark = (grid, xa, xb, za, zb) => {
      const c0 = Math.max(0, Math.floor((xa - x0) / CELL));
      const c1 = Math.min(cols - 1, Math.floor((xb - x0) / CELL));
      const r0 = Math.max(0, Math.floor((za - z0) / CELL));
      const r1 = Math.min(rows - 1, Math.floor((zb - z0) / CELL));
      for (let r = r0; r <= r1; r++) for (let q = c0; q <= c1; q++) grid[r * cols + q] = 1;
    };
    const visit = (o, top, skip = null) => {
      if (!top && !o.visible) return;
      if (skip?.has(o)) return;
      if (o.isMesh && !o.userData.hit) {
        const mt = Array.isArray(o.material) ? o.material[0] : o.material;
        if (mt && mt.colorWrite !== false) {
          solids.push(o);
          if (!o.userData.noCollide && (!mt.transparent || o.userData.solid)) {
            m.multiplyMatrices(inv, o.matrixWorld);
            const pos = o.geometry.attributes.position;
            const idx = o.geometry.index;
            const n = idx ? idx.count : pos.count;
            for (let i = 0; i + 2 < n; i += 3) {
              a.fromBufferAttribute(pos, idx ? idx.getX(i) : i).applyMatrix4(m);
              b.fromBufferAttribute(pos, idx ? idx.getX(i + 1) : i + 1).applyMatrix4(m);
              c.fromBufferAttribute(pos, idx ? idx.getX(i + 2) : i + 2).applyMatrix4(m);
              const lo = Math.min(a.y, b.y, c.y);
              const hi = Math.max(a.y, b.y, c.y);
              if (hi < 0.12 || lo > 2.4) continue;
              const xa = Math.min(a.x, b.x, c.x);
              const xb = Math.max(a.x, b.x, c.x);
              const za = Math.min(a.z, b.z, c.z);
              const zb = Math.max(a.z, b.z, c.z);
              if (lo <= 1.5) mark(scanInto ? scanInto.cells : cells, xa, xb, za, zb);
              if (hi > 1.6) mark(scanInto ? scanInto.sight : sight, xa, xb, za, zb);
            }
          }
        }
      }
      for (const child of o.children) visit(child, false, skip);
    };
    let fixed = null;
    if (!same) {
      visit(s.group, true, contents);
      fixed = { x0, z0, cols, rows, cells: cells.slice(), sight: sight.slice(), solids: solids.slice() };
    }
    // a room whose contents a change didn't rebuild has the same group as before: its squares are reused
    const key = `${s.id}:${x0}:${z0}:${cols}:${rows}`;
    for (const content of contents) {
      if (!content.parent || !content.visible) continue;
      let found = roomScans.get(content);
      if (found?.key !== key) {
        const before = solids.length;
        const mine = new Uint8Array(cols * rows);
        const mineSight = new Uint8Array(cols * rows);
        const into = { cells: mine, sight: mineSight };
        scanInto = into;
        try { visit(content, true); } finally { scanInto = null; }
        const ones = (grid) => { const out = []; for (let i = 0; i < grid.length; i++) if (grid[i]) out.push(i); return out; };
        found = { key, cells: ones(mine), sight: ones(mineSight), solids: solids.splice(before) };
        roomScans.set(content, found);
      }
      for (const i of found.cells) cells[i] = 1;
      for (const i of found.sight) sight[i] = 1;
      solids.push(...found.solids);
    }
    return { x0, z0, cols, rows, cells, sight, solids, fixed: fixed || again };
  }
  const roomScans = new WeakMap(); // a room's contents -> the squares they stop and hide, and their meshes
  let scanInto = null; // while one room's contents are scanned: the grids they mark

  // Whether the walker can see a spot on this floor, or a wall or something tall is in the way.
  function inView(x1, z1) {
    const len = Math.hypot(x1 - me.x, z1 - me.z);
    const steps = Math.ceil(len / (CELL / 2));
    for (let i = 1; i < steps; i++) {
      const t = i / steps;
      if (len * t < 0.3) continue;
      if (len * (1 - t) < 0.4) break;
      const q = Math.floor((me.x + (x1 - me.x) * t - map.x0) / CELL);
      const r = Math.floor((me.z + (z1 - me.z) * t - map.z0) / CELL);
      if (q >= 0 && r >= 0 && q < map.cols && r < map.rows && map.sight[r * map.cols + q]) return false;
    }
    return true;
  }
  // again: only what stands in the rooms has changed (a live change on the floor you are on)
  function look(again = false) {
    map = survey(here, again && map?.floor === here ? map.fixed : null);
    map.floor = here;
    surveyed = performance.now();
    seen = ctx.version();
  }

  /* ---------- talking: a ring on the floor by each agent at work, and by the receptionist ---------- */

  // Stand in a ring and the walk knows who you mean: the ring lights, a card names them, and the
  // page hears of them as if they had been tapped.
  const ringGeo = new THREE.RingGeometry(0.3, 0.4, 48).rotateX(-Math.PI / 2);
  const ringIdle = new THREE.MeshBasicMaterial({ color: '#ffc985', transparent: true, opacity: 0.4, depthWrite: false });
  const ringLit = new THREE.MeshBasicMaterial({ color: '#ffe4bd', transparent: true, opacity: 0.95, depthWrite: false });
  let spots = [];
  let talking = null;
  let heldOff = false; // a re-seat ended a talk: no new one until the walker steps off the ring

  // Every square of this floor's plan the walker can reach from where they stand.
  // Each baked room's doorway, from the floor plan that stops you: the squares inside the room you can walk to
  // that touch squares outside it, the first ones you'd come to on foot from where you came in. Its name hangs
  // there on a walk, so it can be read before you go in, not only from inside.
  function findDoors() {
    doors = new Map();
    if (!map || !here) return;
    const { cols, rows, x0, z0 } = map;
    const steps = new Int32Array(cols * rows).fill(-1); // how many squares away on foot, -1 for out of reach
    const qs = Math.floor((me.x - x0) / CELL);
    const rs = Math.floor((me.z - z0) / CELL);
    if (qs < 0 || rs < 0 || qs >= cols || rs >= rows) return;
    const queue = [rs * cols + qs];
    steps[queue[0]] = 0;
    for (let head = 0; head < queue.length; head++) {
      const i = queue[head];
      const q = i % cols;
      const r = (i - q) / cols;
      for (const [nq, nr] of [[q + 1, r], [q - 1, r], [q, r + 1], [q, r - 1]]) {
        const j = nr * cols + nq;
        if (nq < 0 || nr < 0 || nq >= cols || nr >= rows || steps[j] >= 0) continue;
        if (blocked(x0 + (nq + 0.5) * CELL, z0 + (nr + 0.5) * CELL, true)) continue;
        steps[j] = steps[i] + 1;
        queue.push(j);
      }
    }
    const centre = (q, r) => [x0 + (q + 0.5) * CELL, z0 + (r + 0.5) * CELL];
    for (const room of here.rooms) {
      const b = room.box;
      if (room.g || !b) continue;
      const within = (x, z) => x >= b.x0 && x <= b.x1 && z >= b.z0 && z <= b.z1;
      const edge = []; // [x, z, outward x, outward z]
      const q0 = Math.max(0, Math.floor((b.x0 - x0) / CELL)), q1 = Math.min(cols - 1, Math.floor((b.x1 - x0) / CELL));
      const r0 = Math.max(0, Math.floor((b.z0 - z0) / CELL)), r1 = Math.min(rows - 1, Math.floor((b.z1 - z0) / CELL));
      for (let r = r0; r <= r1; r++) {
        for (let q = q0; q <= q1; q++) {
          const [x, z] = centre(q, r);
          if (steps[r * cols + q] < 0 || !within(x, z)) continue;
          for (const [nq, nr] of [[q + 1, r], [q - 1, r], [q, r + 1], [q, r - 1]]) {
            if (nq < 0 || nr < 0 || nq >= cols || nr >= rows || steps[nr * cols + nq] < 0) continue;
            const [nx, nz] = centre(nq, nr);
            if (!within(nx, nz)) edge.push([x, z, nx - x, nz - z, steps[r * cols + q]]);
          }
        }
      }
      if (!edge.length) continue;
      const near = edge.reduce((a, e) => (e[4] < a[4] ? e : a));
      const one = edge.filter((e) => Math.hypot(e[0] - near[0], e[1] - near[1]) < 1.6); // that doorway only
      const sum = one.reduce((s, e) => [s[0] + e[0], s[1] + e[1], s[2] + e[2], s[3] + e[3]], [0, 0, 0, 0]);
      const [x, z] = [sum[0] / one.length, sum[1] / one.length];
      const out = Math.hypot(sum[2], sum[3]) || 1;
      const [ux, uz] = [sum[2] / out, sum[3] / out];
      const half = one.reduce((m, e) => Math.max(m, Math.abs((e[0] - x) * -uz + (e[1] - z) * ux)), 0) + CELL / 2; // how wide, either side
      doors.set(room.key, [x, z, x + ux * 0.6, z + uz * 0.6, half]);
    }
  }

  function reach() {
    const { cols, rows, x0, z0 } = map;
    const open = new Uint8Array(cols * rows);
    const q0 = Math.floor((me.x - x0) / CELL);
    const r0 = Math.floor((me.z - z0) / CELL);
    if (q0 < 0 || r0 < 0 || q0 >= cols || r0 >= rows) return open;
    const queue = [r0 * cols + q0];
    open[queue[0]] = 1;
    while (queue.length) {
      const i = queue.pop();
      const q = i % cols;
      const r = (i - q) / cols;
      for (const [nq, nr] of [[q + 1, r], [q - 1, r], [q, r + 1], [q, r - 1]]) {
        const j = nr * cols + nq;
        if (nq < 0 || nr < 0 || nq >= cols || nr >= rows || open[j]) continue;
        if (blocked(x0 + (nq + 0.5) * CELL, z0 + (nr + 0.5) * CELL, true)) continue;
        open[j] = 1;
        queue.push(j);
      }
    }
    return open;
  }

  // A ring for each agent at work on this floor, and for the receptionist: at the place the walker can reach
  // that is nearest a good spot to talk from, not too close to them and not on another ring.
  // Placing them again (the page's work changed and people moved seats) never hands you to someone
  // else while you stand still: the talk goes on if the same person's ring is still where you stand,
  // and otherwise ends, with no new one until you step off the ring you are on: at once if they moved,
  // or, if they went altogether, once they have finished what they were saying (lingering, below).
  function placeSpots() {
    const was = talking;
    for (const s of spots) s.ring.removeFromParent();
    spots = [];
    const open = reach();
    const add = (who, ax, az, sx, sz) => {
      let best = null;
      // Near them and apart from the other rings (they touch at 0.8); in a crowded room, a little
      // further off and closer together, so everyone still has one.
      for (const [far, apart] of [[2.2, 0.8], [2.9, 0.62]]) {
        let gap = Infinity;
        for (let i = 0; i < open.length; i++) {
          if (!open[i]) continue;
          const q = i % map.cols;
          const x = map.x0 + (q + 0.5) * CELL;
          const z = map.z0 + ((i - q) / map.cols + 0.5) * CELL;
          const away = Math.hypot(x - ax, z - az);
          if (away < 0.55 || away > far || spots.some((s) => Math.hypot(x - s.x, z - s.z) < apart)) continue;
          const d = Math.hypot(x - sx, z - sz);
          if (d < gap) { gap = d; best = { x, z }; }
        }
        if (best) break;
      }
      if (!best) return;
      const ring = new THREE.Mesh(ringGeo, ringIdle);
      ring.position.set(best.x, 0.025, best.z);
      hall.group.add(ring);
      spots.push({ ...best, ring, who, ax, az });
    };
    for (const room of here.rooms) {
      const { x: rx, z: rz } = room.g?.position || { x: 0, z: 0 }; // a baked floor's rooms are in the floor's own coordinates
      for (const o of room.objects) {
        const f = o.figure;
        if (f) add({ title: o.title, sub: o.sub, href: o.href, floorId: room.floorId, roomId: room.roomId }, rx + f.x, rz + f.z, rx + f.stand[0], rz + f.stand[1]);
      }
    }
    const person = ctx.personRoom;
    if (hall.poe && person?.storey === here) {
      const P = person.spec.person;
      add({ title: P.name, sub: P.title || 'Receptionist', href: P.href, voice: P.voice || null, floorId: person.floorId, roomId: person.roomId }, hall.poe.x, hall.poe.z, hall.poe.x, hall.poe.z + 1.75);
    }
    const A = hall.assistant; // the founder's assistant, in their office
    if (A) add({ ...A.who, floorId: here.id, roomId: 'office' }, A.x, A.z, A.stand[0], A.stand[1]);
    const L = hall.lead; // the floor's lead, by the lift
    if (L) add({ ...L.who, floorId: here.id, roomId: 'lead' }, L.x, L.z, L.stand[0], L.stand[1]);
    if (!was) return;
    const same = spots.find((s) => (s.who.href || s.who.title) === (was.who.href || was.who.title) && Math.hypot(me.x - s.x, me.z - s.z) < 0.42);
    if (same) {
      talking = same;
      same.ring.material = ringLit;
    } else if (was.who.floorId === here.id && Math.hypot(me.x - was.x, me.z - was.z) < 0.42
      && !spots.some((s) => (s.who.href || s.who.title) === (was.who.href || was.who.title))) {
      // Gone altogether from where you stand (a goal set at its flagpole puts the flag up in its place): they finish
      // what they are saying, and the card stays a few seconds after, unless you walk off.
      const t = performance.now();
      talking = { ...was, gone: true, until: t + LINGER_MS, last: t + LINGER_MAX_MS };
      heldOff = true;
    } else {
      setTalk(null);
      heldOff = true;
    }
  }

  // A talk whose ring went while you stood in it ends a few seconds after the last word either of you said, and
  // 20 seconds after the ring went at the latest, or as soon as you step away. True while it lasts (the frames keep
  // coming meanwhile, so it ends on time in a still room).
  const LINGER_MS = 4000;
  const LINGER_MAX_MS = 20000;
  function lingering(now) {
    if (!talking?.gone) return false;
    const mode = voice.info().mode;
    if (mode === 'thinking' || mode === 'speaking' || mode === 'hearing') talking.until = Math.max(talking.until, now + LINGER_MS);
    if (Math.hypot(me.x - talking.x, me.z - talking.z) < 0.42 && now < Math.min(talking.until, talking.last)) return true;
    setTalk(null);
    return false;
  }

  // Each project floor's lead (leads.js): a few steps from where the lift lets you out, in sight of it but clear of
  // every doorway and the ways into the rooms, with a ring of their own. The page's talk.lead(floor id) says who they are, or null (no project, or leads switched off).
  // Gives true when someone came or went, so the floor is surveyed again.
  const LEAD_LOOKS = {
    skin: ['#f1c7a5', '#deaa82', '#c68a62', '#a26b48', '#7a4a2e', '#5a3622'],
    hair: ['#2b1d18', '#5a3926', '#8a5a36', '#1c1c1c', '#b9874f', '#3b2a22'],
    coat: ['#3d5a6c', '#6b4e3d', '#4a5d3f', '#5b3b5e', '#2f3e5c', '#7a3d3d'],
    style: [undefined, 'bun', 'swept', undefined],
  };
  const pickOf = (key, list, shift) => {
    let n = 2166136261;
    for (const ch of String(key)) n = Math.imul(n ^ ch.charCodeAt(0), 16777619);
    return list[((n >>> 0) >>> shift) % list.length];
  };
  function placeLead(s) {
    let who = null;
    try { who = s === penthouse ? null : ctx.talk?.lead?.(s.id) || null; } catch (error) { console.warn('Arnheim: no lead.', error); }
    const had = hall.lead;
    if (had && (!who || had.who.href !== who.href)) {
      had.group.removeFromParent();
      had.hit.removeFromParent();
      had.group.traverse((o) => o.geometry?.dispose?.());
      had.hit.geometry.dispose();
      const at = hall.picks.indexOf(had.hit);
      if (at >= 0) hall.picks.splice(at, 1);
      hall.lead = null;
    }
    if (!who) return !!had;
    if (hall.lead) { hall.lead.who = { ...who }; return false; }
    // Somewhere a few steps from the lift, in sight, and clear of every doorway and the ways into the rooms
    // (lead-spot.js): baked rooms' doorways, and the open fronts of drawn ones.
    const spot = leadSpot(leadPlan());
    if (!spot) return !!had;
    const { x, z, stand, out } = spot;
    const spec = lookSpec(who.look || {
      skin: pickOf(who.href, LEAD_LOOKS.skin, 3), hair: pickOf(who.href, LEAD_LOOKS.hair, 7),
      coat: pickOf(who.href, LEAD_LOOKS.coat, 11), style: pickOf(who.href, LEAD_LOOKS.style, 17),
    });
    spec.at = [x, 0, z];
    spec.turn = Math.atan2(stand[0] - x, stand[1] - z); // towards where you stand to talk to them
    spec.look = -0.08;
    const person = buildPerson(spec);
    const hit = new THREE.Mesh(new THREE.BoxGeometry(0.8, 1.8, 0.8), hitMaterial);
    hit.position.set(x, 0.92, z);
    hit.visible = false;
    hit.userData = { hit: true, talk: true, href: who.href, title: who.title, sub: `${who.sub || 'The lead here'}. Tap to talk.` };
    hall.group.add(person.group, hit);
    hall.picks.push(hit);
    hall.lead = { x, z, stand, out, who: { ...who }, group: person.group, hit };
    return true;
  }

  // What leadSpot is given on this floor: the plan, the lift, baked rooms' doorways and the open fronts of drawn
  // ones, and the routes from the lift to each.
  function leadPlan() {
    const a = hall.spot || { x: me.x, z: me.z, yaw: me.yaw };
    findDoors();
    const doorways = [...doors.values()];
    for (const room of here.rooms) {
      if (!room.g) continue;
      const p = room.g.position;
      doorways.push([p.x + W / 2, p.z + D - 0.6, p.x + W / 2, p.z + D + 0.6, W / 2 - 0.3]); // its whole open front
    }
    const routes = [];
    for (const [, , ox, oz] of doorways) {
      const way = wayTo(ox, oz);
      if (way) routes.push([[me.x, me.z], ...way.map((w) => [w.x, w.z])]);
    }
    return {
      plan: { cols: map.cols, rows: map.rows, x0: map.x0, z0: map.z0, cell: CELL, open: reach(), free: (x, z) => !blocked(x, z, true) },
      lift: { x: a.x, z: a.z, yaw: a.yaw ?? me.yaw }, inLift: (x, z) => !!hall.inLift?.(x, z), doors: doorways, ways: routes,
    };
  }

  function setTalk(spot) {
    if (spot === talking) return;
    if (talking) talking.ring.material = ringIdle;
    talking = spot;
    if (spot) {
      // Walking into the ring by a tap: on arrival, turn to face whoever it is for.
      if (me.target && Math.hypot(me.target.x - spot.x, me.target.z - spot.z) < 0.5) me.target.face = [spot.ax, spot.az];
      spot.ring.material = ringLit;
      showCard(spot.who, true);
      ctx.onPick?.({ ...spot.who, walk: true });
    } else if (card.classList.contains('aw-talking')) card.hidden = true;
    voice.talkTo(spot?.who || null);
    ctx.wake(2);
  }

  /* ---------- moving ---------- */

  // planning: for a route, which may pass the lift's doors, since they open as you come
  function blocked(x, z, planning = false) {
    if (!planning && hall?.shut?.(x, z, RADIUS)) return true; // the lift's doors, while they are shut
    const c0 = Math.floor((x - RADIUS - map.x0) / CELL);
    const c1 = Math.floor((x + RADIUS - map.x0) / CELL);
    const r0 = Math.floor((z - RADIUS - map.z0) / CELL);
    const r1 = Math.floor((z + RADIUS - map.z0) / CELL);
    for (let r = r0; r <= r1; r++) {
      for (let q = c0; q <= c1; q++) {
        if (q < 0 || r < 0 || q >= map.cols || r >= map.rows) return true;
        if (!map.cells[r * map.cols + q]) continue;
        const nx = Math.max(map.x0 + q * CELL, Math.min(x, map.x0 + (q + 1) * CELL));
        const nz = Math.max(map.z0 + r * CELL, Math.min(z, map.z0 + (r + 1) * CELL));
        if ((nx - x) ** 2 + (nz - z) ** 2 < RADIUS * RADIUS) return true;
      }
    }
    return false;
  }

  // Slides along walls rather than sticking to them. Someone already inside something may walk out.
  function move(dx, dz) {
    const steps = Math.max(1, Math.ceil(Math.hypot(dx, dz) / 0.08));
    const loose = blocked(me.x, me.z);
    const onPlan = (x, z) => x - RADIUS >= map.x0 && z - RADIUS >= map.z0 && x + RADIUS <= map.x0 + map.cols * CELL && z + RADIUS <= map.z0 + map.rows * CELL;
    for (let i = 0; i < steps; i++) {
      const nx = me.x + dx / steps;
      if (loose ? onPlan(nx, me.z) : !blocked(nx, me.z)) me.x = nx;
      const nz = me.z + dz / steps;
      if (loose ? onPlan(me.x, nz) : !blocked(me.x, nz)) me.z = nz;
    }
  }

  // The nearest spot to (x, z) with room to stand: a body's width off walls and furniture where there is
  // one close by, else simply clear. Null if nothing near is.
  function roomAt(x, z) {
    // from a clear spot, only places in plain sight of it: never one on the far side of a wall, which
    // the walker would go the long way round to reach (a narrow corridor keeps the spot itself instead)
    const open = !blocked(x, z, true);
    const sight = (px, pz) => {
      if (!open) return true;
      const steps = Math.ceil(Math.hypot(px - x, pz - z) / (CELL / 2));
      for (let i = 1; i <= steps; i++) if (blocked(x + ((px - x) * i) / steps, z + ((pz - z) * i) / steps, true)) return false;
      return true;
    };
    const roomy = (px, pz) => !blocked(px, pz, true) && [[0.3, 0], [-0.3, 0], [0, 0.3], [0, -0.3]].every(([ox, oz]) => !blocked(px + ox, pz + oz, true)) && sight(px, pz);
    for (const fits of [roomy, (px, pz) => !blocked(px, pz, true)]) {
      if (fits(x, z)) return { x, z };
      for (let r = 0.15; r <= 1.2; r += 0.15) {
        for (let a = 0; a < Math.PI * 2; a += Math.PI / 12) {
          const px = x + Math.cos(a) * r;
          const pz = z + Math.sin(a) * r;
          if (fits(px, pz)) return { x: px, z: pz };
        }
      }
    }
    return null;
  }

  // How far you could see ahead along a heading before a wall: for turning away from one on arrival.
  function openAhead(yaw) {
    const dx = -Math.sin(yaw);
    const dz = -Math.cos(yaw);
    let d = 0.25;
    while (d < 6 && !blocked(me.x + dx * d, me.z + dz * d, true)) d += 0.25;
    return d;
  }

  // Arriving with your nose to a wall, you turn to the most open view, the least turn away.
  function faceTheRoom() {
    if (openAhead(me.yawGoal) >= 1.6) return;
    let best = me.yawGoal;
    let score = -Infinity;
    for (let i = 1; i < 16; i++) {
      const turn = ((i % 2 ? 1 : -1) * Math.ceil(i / 2) * Math.PI) / 8;
      const s = openAhead(me.yawGoal + turn) - Math.abs(turn) * 0.6;
      if (s > score) { score = s; best = me.yawGoal + turn; }
    }
    me.yawGoal = best;
  }

  function free() {
    if (!blocked(me.x, me.z)) return;
    for (let r = 0.2; r < 2.5; r += 0.2) {
      for (let a = 0; a < Math.PI * 2; a += Math.PI / 8) {
        const x = me.x + Math.cos(a) * r;
        const z = me.z + Math.sin(a) * r;
        if (!blocked(x, z)) { me.x = x; me.z = z; return; }
      }
    }
  }

  /* ---------- the lift and the burn ---------- */

  function stepFloor(dir) {
    const to = order[order.indexOf(here) - dir];
    if (to) rideTo(to);
  }

  // Goes to another floor, or (at a point) burns this floor away and rebuilds it.
  function rideTo(to, at = null) {
    if (ride || !to || (to === here && !at)) { if (!ride) afterRide = null; return; }
    closePicker();
    card.hidden = true;
    me.target = null;
    input();
    // In the real lift's car, the ride is a lift's: the doors close, it travels, and they open onto the new floor.
    const inCar = !!hall.car && !at && to !== here && hall.inLift(me.x, me.z);
    // In the car, you turn round to face its doors as it goes, as anyone in a lift does, so you arrive facing out.
    if (inCar && Number.isFinite(hall.spot?.yaw)) {
      const turn = hall.spot.yaw - me.yawGoal;
      me.yawGoal += Math.atan2(Math.sin(turn), Math.cos(turn));
    }
    if (still()) { if (to !== here) { enter(to, inCar ? 'car' : 'lift'); arrived(); } return; }
    ride = { to, same: to === here, at, phase: 'close', t: 0, car: inCar, trip: inCar ? Math.min(4, 1.4 + 0.35 * Math.abs(order.indexOf(to) - order.indexOf(here))) : 0 };
    if (ride.same || !hall.inLift(me.x, me.z)) burnOut();
  }

  function burnOut() {
    ride.phase = 'out';
    burn.start({ root: here.group, origin: ride.at || chest(new THREE.Vector3()), inward: false, eye: camera.position });
    here.group.visible = false;
  }

  function advance(dt) {
    ride.t += dt;
    if (ride.phase === 'close') {
      if (hall.lift.open < 0.05 || ride.t > 1.2) {
        if (!ride.car) burnOut();
        else { ride.phase = 'travel'; ride.t = 0; me.dipV -= 0.12; } // it moves off, a little dip
      }
    } else if (ride.phase === 'travel') {
      if (ride.t < ride.trip) return;
      enter(ride.to, 'car'); // the same car, now at the new floor; its doors open as it stops
      me.dipV += 0.12;
      ride = null;
      arrived();
    } else if (ride.phase === 'out') {
      if (burn.running) return;
      if (!ride.same) enter(ride.to, 'lift');
      here.group.visible = false; // it gathers out of points first
      ride.phase = 'in';
      const eye = chest(new THREE.Vector3());
      burn.start({ root: here.group, origin: ride.same ? ride.at : eye, inward: true, eye });
    } else if (ride.phase === 'in' && !burn.running) {
      here.group.visible = true;
      const moved = !ride.same;
      ride = null;
      if (moved) arrived(); else afterRide = null;
    }
  }

  /* ---------- input ---------- */

  const typing = (event) => event.target?.closest?.('input, textarea, select, [contenteditable]');
  window.addEventListener('keydown', (event) => {
    if (typing(event) || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      if (!picker.hidden) closePicker();
      else if (!card.hidden && !card.classList.contains('aw-talking')) { clearTimeout(cardTimer); card.hidden = true; }
      else ctx.leave();
    } else if (event.key === '?') {
      event.preventDefault();
      showHelp(help.classList.contains('aw-faded'));
    } else if (event.key === 'PageUp' || event.key === 'PageDown') {
      event.preventDefault();
      stepFloor(event.key === 'PageUp' ? 1 : -1);
    } else if (MOVES.has(event.code)) {
      event.preventDefault();
      keys.add(event.code);
      me.target = null;
      if (!inLift) closePicker();
      input();
    }
  }, { signal });
  window.addEventListener('keyup', (event) => {
    keys.delete(event.code);
    if (event.key === 'Meta') keys.clear(); // a Mac drops the key-up of anything held while Cmd was down
  }, { signal });
  document.addEventListener('visibilitychange', () => { if (document.hidden) keys.clear(); }, { signal });
  window.addEventListener('blur', () => keys.clear(), { signal });

  // Drag to look, as if taking hold of the world; a quick tap goes somewhere or opens something.
  canvas.addEventListener('pointerdown', (event) => {
    if (press || (event.pointerType === 'mouse' && event.button !== 0)) return;
    press = { id: event.pointerId, x: event.clientX, y: event.clientY, at: performance.now(), yaw: me.yawGoal, pitch: me.pitchGoal, moved: false, touch: event.pointerType !== 'mouse' };
    try { canvas.setPointerCapture(event.pointerId); } catch { /* a pointer the browser no longer tracks */ }
    input();
  }, { signal });
  canvas.addEventListener('pointermove', (event) => {
    if (!press || event.pointerId !== press.id) return;
    const dx = event.clientX - press.x;
    const dy = event.clientY - press.y;
    if (!press.moved && Math.hypot(dx, dy) > 6) press.moved = true;
    if (!press.moved) return;
    const k = press.touch ? 0.0062 : 0.0045;
    me.yawGoal = press.yaw + dx * k;
    me.pitchGoal = THREE.MathUtils.clamp(press.pitch + dy * k * 0.8, -0.75, 0.6);
    input();
  }, { signal });
  const release = (event) => {
    if (!press || event.pointerId !== press.id) return;
    const tap = !press.moved && performance.now() - press.at < 450;
    press = null;
    if (tap && event.type === 'pointerup') tapAt(event.clientX, event.clientY);
  };
  canvas.addEventListener('pointerup', release, { signal });
  canvas.addEventListener('pointercancel', release, { signal });

  // Tap to talk: tapping someone who has a ring (the receptionist, the founder's assistant, an agent at
  // work or waiting for you) walks you onto it,
  // round whatever is in the way, and turns you to face them as you arrive. The talk itself starts
  // as you step in (setTalk), just as if you had walked there.
  const ringOf = (hit) => spots.find((s) => (hit.href ? s.who.href === hit.href : s.who.title === hit.title)) || null;

  function walkToTalk(hit) {
    const spot = ringOf(hit);
    if (!spot) return false;
    if (spot === talking) { showCard(spot.who, true); return true; }
    const way = wayTo(spot.x, spot.z);
    if (!way) return false;
    showCard(hit);
    me.target = { ...way.shift(), next: way, face: [spot.ax, spot.az] };
    ctx.wake(2);
    return true;
  }

  // The way from here to a spot on this floor: the floor plan's squares, searched outward from where
  // you stand, then pulled straight wherever nothing is in the way. Null if it can't be reached.
  function wayTo(tx, tz) {
    const { cols, rows, x0, z0 } = map;
    const square = (x, z) => {
      const q = Math.floor((x - x0) / CELL);
      const r = Math.floor((z - z0) / CELL);
      return q < 0 || r < 0 || q >= cols || r >= rows ? -1 : r * cols + q;
    };
    const start = square(me.x, me.z);
    const goal = square(tx, tz);
    if (start < 0 || goal < 0) return null;
    const goalBlocked = blocked(tx, tz, true); // the spot itself, which may be off its square's middle
    const from = new Int32Array(cols * rows).fill(-1);
    from[start] = start;
    const queue = [start];
    for (let head = 0; head < queue.length && from[goal] < 0; head++) {
      const i = queue[head];
      const q = i % cols;
      const r = (i - q) / cols;
      for (const [nq, nr] of [[q + 1, r], [q - 1, r], [q, r + 1], [q, r - 1]]) {
        const j = nr * cols + nq;
        if (nq < 0 || nr < 0 || nq >= cols || nr >= rows || from[j] >= 0) continue;
        if (j === goal ? goalBlocked : blocked(x0 + (nq + 0.5) * CELL, z0 + (nr + 0.5) * CELL, true)) continue;
        from[j] = i;
        queue.push(j);
      }
    }
    if (from[goal] < 0) return null;
    const squares = [{ x: tx, z: tz }];
    for (let i = from[goal]; i !== start; i = from[i]) squares.unshift({ x: x0 + ((i % cols) + 0.5) * CELL, z: z0 + (Math.floor(i / cols) + 0.5) * CELL });
    const clear = (a, b) => {
      const steps = Math.ceil(Math.hypot(b.x - a.x, b.z - a.z) / (CELL / 2));
      for (let i = 1; i <= steps; i++) if (blocked(a.x + ((b.x - a.x) * i) / steps, a.z + ((b.z - a.z) * i) / steps, true)) return false;
      return true;
    };
    const points = [];
    let at = { x: me.x, z: me.z };
    for (let k = 0; k < squares.length; k++) {
      let far = k;
      while (far + 1 < squares.length && clear(at, squares[far + 1])) far += 1;
      at = squares[far];
      points.push(at);
      k = far;
    }
    return points;
  }

  function tapAt(x, y) {
    if (ride) return;
    const now = performance.now();
    const double = !!lastTap && now - lastTap.at < 340 && Math.hypot(x - lastTap.x, y - lastTap.y) < 36;
    lastTap = double ? null : { at: now, x, y };
    const box = canvas.getBoundingClientRect();
    ndc.set(((x - box.left) / box.width) * 2 - 1, -((y - box.top) / box.height) * 2 + 1);
    ray.setFromCamera(ndc, camera);
    const surface = ray.intersectObjects(map.solids, false)[0];
    if (double) {
      if (surface) rideTo(here, surface.point.clone());
      return;
    }
    const picks = [...hall.picks];
    for (const r of here.rooms) for (const o of r.objects) if (!o.person) picks.push(o.hit);
    const thing = ray.intersectObjects(picks, false).find((h) => h.distance < 10);
    if (notes.tap(thing && (!surface || thing.distance <= surface.distance + 0.3) ? thing.object.userData : null)) return;
    if (thing && (!surface || thing.distance <= surface.distance + 0.3)) {
      const hit = thing.object.userData;
      if (hit.lift) { openPicker(); return; }
      closePicker();
      if ((hit.talk || ringOf(hit)) && walkToTalk(hit)) return;
      showCard(hit);
      if (!hit.stay) ctx.onPick?.({ ...hit, walk: true });
      return;
    }
    if (!surface) return;
    const spot = here.group.worldToLocal(surface.point.clone());
    if (spot.y > 0.08) spot.copy(here.group.worldToLocal(surface.point.clone().addScaledVector(ray.ray.direction, -0.5)));
    const goal = roomAt(spot.x, spot.z);
    const way = goal && wayTo(goal.x, goal.z);
    if (!way) return; // nowhere to stand there, or no way to it: you stay where you are
    closePicker();
    me.target = { ...way.shift(), next: way, open: true };
    ctx.wake(2);
  }

  // The stick, for thumbs: up walks ahead, sideways steps aside.
  function moveStick(event) {
    const r = stickEl.getBoundingClientRect();
    const max = r.width / 2 - 8;
    let dx = event.clientX - (r.left + r.width / 2);
    let dy = event.clientY - (r.top + r.height / 2);
    const len = Math.hypot(dx, dy);
    if (len > max) { dx *= max / len; dy *= max / len; }
    stick.x = dx / max;
    stick.y = dy / max;
    knob.style.transform = `translate(${dx}px, ${dy}px)`;
    me.target = null;
    if (!inLift) closePicker();
    input();
  }
  stickEl.addEventListener('pointerdown', (event) => {
    event.stopPropagation();
    stick.id = event.pointerId;
    try { stickEl.setPointerCapture(event.pointerId); } catch { /* a pointer the browser no longer tracks */ }
    moveStick(event);
  }, { signal });
  stickEl.addEventListener('pointermove', (event) => { if (event.pointerId === stick.id) moveStick(event); }, { signal });
  const dropStick = (event) => {
    if (event.pointerId !== stick.id) return;
    stick.id = null;
    stick.x = 0;
    stick.y = 0;
    knob.style.transform = '';
  };
  stickEl.addEventListener('pointerup', dropStick, { signal });
  stickEl.addEventListener('pointercancel', dropStick, { signal });

  /* ---------- each frame ---------- */

  // Moves the walk on by dt seconds and places the camera; true while anything is still moving.
  function update(dt, now) {
    if (!here) return false;
    let busy = false;
    if (ride) { advance(dt); busy = true; }
    if (!ride && ctx.version() !== seen && now - surveyed > 1500) { look(true); placeSpots(); free(); planBaseOf(); drawNeeds(); }

    // Turning: smooth, whether by drag, keys or walking somewhere.
    const turn = (keys.has('ArrowLeft') ? 1 : 0) - (keys.has('ArrowRight') ? 1 : 0);
    if (turn && !ride) { me.yawGoal += turn * dt * 1.9; busy = true; }
    const k = still() ? 1 : 1 - Math.exp(-dt * 11);
    const dYaw = me.yawGoal - me.yaw;
    const dPitch = me.pitchGoal - me.pitch;
    if (Math.abs(dYaw) > 1e-4 || Math.abs(dPitch) > 1e-4) {
      me.yaw += dYaw * k;
      me.pitch += dPitch * k;
      busy = true;
    } else {
      me.yaw = me.yawGoal;
      me.pitch = me.pitchGoal;
    }

    // Where the walker wants to go: keys, the stick, or a spot they tapped.
    let f = 0;
    let s = 0;
    if (!ride) {
      if (keys.has('KeyW') || keys.has('ArrowUp')) f += 1;
      if (keys.has('KeyS') || keys.has('ArrowDown')) f -= 1;
      if (keys.has('KeyD')) s += 1;
      if (keys.has('KeyA')) s -= 1;
      if (Math.hypot(stick.x, stick.y) > 0.14) { f -= stick.y; s += stick.x; }
    }
    const manual = Math.hypot(f, s) > 0.05;
    if (manual || ride) me.target = null;
    const sin = Math.sin(me.yaw);
    const cos = Math.cos(me.yaw);
    let wx = 0;
    let wz = 0;
    if (manual) {
      const len = Math.max(1, Math.hypot(f, s));
      const pace = (keys.has('ShiftLeft') || keys.has('ShiftRight') ? RUN : WALK) / len;
      wx = (-sin * f + cos * s) * pace;
      wz = (-cos * f - sin * s) * pace;
    } else if (me.target) {
      // On a way with corners (walkToTalk), each corner is passed on the move, not stopped at.
      if (me.target.next?.length && Math.hypot(me.target.x - me.x, me.target.z - me.z) < 0.3) {
        me.target = { ...me.target.next.shift(), next: me.target.next, face: me.target.face, open: me.target.open };
      }
      const last = !me.target.next?.length;
      const dx = me.target.x - me.x;
      const dz = me.target.z - me.z;
      const dist = Math.hypot(dx, dz);
      if (last && dist < 0.12) {
        const them = me.target.face;
        const open = me.target.open;
        me.target = null;
        if (open) faceTheRoom();
        if (them) {
          const turn = Math.atan2(-(them[0] - me.x), -(them[1] - me.z)) - me.yawGoal;
          me.yawGoal += Math.atan2(Math.sin(turn), Math.cos(turn));
        }
      } else {
        const pace = last ? Math.min(WALK, 0.3 + dist * 1.4) : WALK;
        wx = (dx / dist) * pace;
        wz = (dz / dist) * pace;
        let face = Math.atan2(-dx, -dz) - me.yawGoal;
        face = Math.atan2(Math.sin(face), Math.cos(face));
        if (dist > 0.6 || !last) me.yawGoal += face * Math.min(1, dt * 2.4);
      }
    }
    const want = Math.hypot(wx, wz);
    const ease = still() ? 1 : 1 - Math.exp(-dt * (want > me.speed ? 4.5 : 6.5));
    me.vx += (wx - me.vx) * ease;
    me.vz += (wz - me.vz) * ease;
    me.speed = Math.hypot(me.vx, me.vz);
    if (me.speed < 0.01 && want === 0) { me.vx = 0; me.vz = 0; me.speed = 0; }
    if (me.speed > 0) {
      const ox = me.x;
      const oz = me.z;
      move(me.vx * dt, me.vz * dt);
      const went = Math.hypot(me.x - ox, me.z - oz);
      if (me.target && went < me.speed * dt * 0.3) {
        me.stuck += dt;
        if (me.stuck > 0.4) me.target = null;
      } else me.stuck = 0;
      me.phase += (went / STRIDE) * Math.PI;
      busy = true;
      if (hall.poe && Math.hypot(me.x - hall.poe.x, me.z - hall.poe.z) < 7) ctx.poeAwake();
    }

    // A soft settle as the walker comes to a stop, and the stride fading out.
    if (me.speed > 0.7) me.striding = true;
    else if (me.striding && me.speed < 0.2) { me.striding = false; if (!still()) me.dipV -= 0.2; }
    me.dipV += (-me.dip * 70 - me.dipV * 11) * dt;
    me.dip += me.dipV * dt;
    if (Math.abs(me.dip) > 2e-4 || Math.abs(me.dipV) > 2e-3) busy = true;
    else { me.dip = 0; me.dipV = 0; }
    const ampGoal = still() ? 0 : Math.min(1, me.speed / WALK);
    me.amp += (ampGoal - me.amp) * (1 - Math.exp(-dt * 5));
    if (Math.abs(ampGoal - me.amp) > 0.002) busy = true;
    else me.amp = ampGoal;

    // The lift: its doors open as you come near, and stepping in shows the floors.
    const L = hall.lift;
    const doorGoal = ride ? 0 : Math.hypot(me.x - L.x, me.z - L.z) < 2.4 ? 1 : 0;
    if (Math.abs(doorGoal - L.open) > 0.003) {
      L.open += (doorGoal - L.open) * (still() ? 1 : 1 - Math.exp(-dt * 3.6));
      hall.setDoors(L.open);
      busy = true;
    } else if (L.open !== doorGoal) {
      L.open = doorGoal;
      hall.setDoors(doorGoal);
    }
    if (!ride) {
      const inside = hall.inLift(me.x, me.z);
      if (inside && !inLift) openPicker();
      else if (!inside && inLift) closePicker();
      inLift = inside;
      const ring = spots.find((s) => Math.hypot(me.x - s.x, me.z - s.z) < 0.42) || null;
      // on the way somewhere else (a tap, the guide, Needs you), a ring passed over is only passed over
      const passing = !!ring && !!me.target && (me.target.next?.length > 0 || Math.hypot(me.target.x - ring.x, me.target.z - ring.z) > 0.5);
      // and a lead's ring is by the lift, where everyone walks: walked across on the way somewhere else, it starts
      // nothing. Stop on it, or walk on it towards them (within 40 degrees), and it does.
      const across = !!ring && ring.who.roomId === 'lead' && talking !== ring && !me.target && crossingOnly(me.x, me.z, me.vx, me.vz, ring.ax, ring.az);
      if (!ring) heldOff = false;
      const stay = lingering(now);
      if (stay) busy = true;
      else if (!heldOff) setTalk(passing || across ? null : ring);
    }
    if (notes.update(dt, me, here === penthouse && !ride, still())) busy = true;
    if (burn.update(dt, camera, renderer)) busy = true;

    // The camera at eye height: a gentle bob and sway in step, and a little hand-held drift that
    // fades a few seconds after the last touch, so a still picture really is still.
    const hand = still() ? 0 : Math.max(0, 1 - (now - lastInput) / QUIET_MS) * 0.7 + me.amp * 0.3;
    if (hand > 0.003) busy = true;
    const t = now / 1000;
    const sway = Math.sin(me.phase) * 0.016 * me.amp;
    const bob = (Math.cos(me.phase * 2) - 1) * 0.012 * me.amp;
    const p = here.group.position;
    camera.position.set(p.x + me.x + cos * sway, p.y + EYE + bob + me.dip, p.z + me.z - sin * sway);
    camera.rotation.set(
      me.pitch + hand * (Math.sin(t * 0.7 + 0.4) * 0.6 + Math.sin(t * 2.5) * 0.4) * 0.003,
      me.yaw + hand * (Math.sin(t * 0.9) * 0.6 + Math.sin(t * 2.1 + 1.3) * 0.4) * 0.004,
      Math.sin(me.phase) * 0.005 * me.amp,
      'YXZ',
    );
    footage.enabled = !still();
    if (footage.enabled) {
      const vfov = THREE.MathUtils.degToRad(camera.fov);
      const hfov = 2 * Math.atan(Math.tan(vfov / 2) * camera.aspect);
      // The smear a phone's shutter catches at this speed of turn, whatever the frame rate, kept light.
      const smear = (d, span) => THREE.MathUtils.clamp(((d / Math.max(dt, 0.004)) * SHUTTER) / span, -0.008, 0.008);
      footage.uniforms.uVel.value.set(smear(camera.rotation.y - lastYaw, hfov), smear(camera.rotation.x - lastPitch, vfov));
      footage.uniforms.uTime.value = t;
      footage.uniforms.uRes.value.copy(renderer.getDrawingBufferSize(px));
    }
    lastYaw = camera.rotation.y;
    lastPitch = camera.rotation.x;
    drawPlan();
    drawLiftButtons(); // only touches the page when the floor or the ride changed
    return busy;
  }

  // Names over the nearest open rooms, and the receptionist's, for the building's label layer.
  function labels() {
    if (!here || ride) return [];
    const out = [];
    camera.getWorldDirection(ahead);
    for (const room of here.rooms) {
      // over a drawn room's open front; over a baked one's doorway, so it reads before you go in (its middle if none)
      const door = doors.get(room.key);
      const local = room.g ? [W / 2, H - 0.3, D + 0.02] : door ? [door[0], 2.3, door[1]] : [room.centre[0], 2.3, room.centre[1]];
      const seenAt = room.g ? [room.g.position.x + W / 2, D + 0.02] : door ? [door[2], door[3]] : room.centre;
      ctx.roomWorld(room, v, ...local);
      const d = v.distanceTo(camera.position);
      if (d > 16 || v.sub(camera.position).normalize().dot(ahead) < 0.35 || !inView(...seenAt)) continue;
      out.push({ key: `w:${room.key}`, title: room.label, sub: ctx.infoText(room.info), kind: room.mood, align: 'center', room, local, rank: d });
    }
    // The lift, so it can be found again on any floor: over its doors, while you aren't in it.
    const sign = hall.liftSign || { x: hall.lift.x, z: hall.lift.z, y: 2.4 };
    const gp = here.group.position;
    const signAt = new THREE.Vector3(gp.x + sign.x, gp.y + sign.y, gp.z + sign.z);
    const far = signAt.distanceTo(camera.position);
    if (!inLift && far < 16 && signAt.clone().sub(camera.position).normalize().dot(ahead) > 0.3 && inView(sign.x, sign.z)) {
      out.push({ key: 'w:lift', title: 'Lift', sub: coarse ? 'Tap it, or ▲ ▼ at the top' : 'Click it, or ▲ ▼ at the top', kind: 'quiet', align: 'center', at: signAt.toArray(), rank: 0 }); // first, so a room's name never hides it
    }
    const person = ctx.personRoom;
    if (hall.poe && person?.storey === here) {
      const p = here.group.position;
      v.set(p.x + hall.poe.x, p.y + 2.05, p.z + hall.poe.z);
      if (v.distanceTo(camera.position) < 12 && inView(hall.poe.x, hall.poe.z)) out.push({ key: 'w:poe', title: person.spec.person.name, sub: person.spec.person.title || 'Receptionist', kind: 'quiet', align: 'center', at: v.toArray(), rank: 0 });
    }
    if (hall.desk?.name) {
      const p = here.group.position;
      v.set(p.x + hall.desk.x, p.y + 1.75, p.z + hall.desk.z);
      if (v.distanceTo(camera.position) < 14 && inView(hall.desk.x, hall.desk.z)) out.push({ key: 'w:founder', title: hall.desk.name, sub: hall.desk.title, kind: 'quiet', align: 'center', at: v.toArray(), rank: 0 });
    }
    if (hall.assistant) {
      const p = here.group.position;
      const A = hall.assistant;
      v.set(p.x + A.x, p.y + 2.1, p.z + A.z);
      if (v.distanceTo(camera.position) < 12 && inView(A.x, A.z)) out.push({ key: 'w:assistant', title: A.who.title, sub: A.who.sub, kind: 'quiet', align: 'center', at: v.toArray(), rank: 0 });
    }
    return out.sort((a, b) => a.rank - b.rank).slice(0, 5);
  }

  // A point on this floor (floor-local metres) on the screen, in page pixels, or null behind you.
  function onScreen(x, y, z) {
    const p = here.group.position;
    const v = new THREE.Vector3(p.x + x, p.y + y, p.z + z).project(camera);
    if (v.z > 1 || Math.abs(v.x) > 1 || Math.abs(v.y) > 1) return null;
    const box = canvas.getBoundingClientRect();
    return [Math.round(box.left + ((v.x + 1) / 2) * box.width), Math.round(box.top + ((1 - v.y) / 2) * box.height)];
  }

  // Where the walker is, for tests, with where the people to talk to and the rooms' openings are
  // on the screen, to tap.
  function info() {
    const r2 = (n) => Math.round(n * 100) / 100;
    return {
      floor: here?.id, x: r2(me.x), z: r2(me.z), yaw: r2(me.yaw), speed: r2(me.speed), riding: ride?.phase || null,
      burning: burn.active, points: burn.count, inLift, doors: r2(hall?.lift.open || 0), picker: !picker.hidden, card: card.hidden ? null : cardTitle.textContent,
      photo: photoState, film: footage.enabled, talk: talking?.who.title || null, rings: spots.map((r) => [r2(r.x), r2(r.z)]),
      voice: voice.info(),
      notes: notes.info(),
      people: here ? spots.map((s) => ({ title: s.who.title, href: s.who.href || null, at: onScreen(s.ax, 0.9, s.az), ring: onScreen(s.x, 0.03, s.z) })) : [],
      openings: here ? here.rooms.map((r) => {
        const [x, z] = r.g ? [r.g.position.x + W / 2, r.g.position.z + D + 0.8] : r.centre;
        return { room: r.roomId, x: r2(x), z: r2(z), at: onScreen(x, 0, z) };
      }) : [],
    };
  }

  function dispose() {
    remember();
    planWatch.disconnect();
    gone = true;
    listeners.abort();
    clearTimeout(cardTimer);
    clearTimeout(helpTimer);
    clearTimeout(loadTimer);
    clearInterval(needsTimer);
    voice.dispose();
    if (here) { placeReceptionist(false); setWalls(here, false); }
    for (const entry of halls.values()) {
      entry.group.removeFromParent();
      entry.dispose();
      // the invisible boxes that take taps (the lift, a desk, the receptionist, the assistant) are the walk's own
      for (const pick of entry.picks || []) pick.geometry?.dispose?.();
      entry.lead?.group.traverse((o) => o.geometry?.dispose?.()); // the floor's lead is drawn for this walk alone
    }
    halls.clear();
    notes.dispose();
    penthouse.group.removeFromParent();
    photo?.dispose(); // after the halls: their materials only borrowed these pictures
    photo = null;
    burn.dispose();
    ctx.composer.removePass(footage);
    footage.dispose();
    hitMaterial.dispose();
    ringGeo.dispose();
    ringIdle.dispose();
    ringLit.dispose();
    for (const node of [hud, picker, card, help, stickEl, loading, planBox]) node.remove();
    stage.classList.remove('arnheim-walking');
    here = null;
  }

  /* ---------- start: at the reception's door, or at the lift of the floor in view ---------- */

  // with no lobby, the floor nearest the ground, and above it rather than the basement below
  // Where you were when you last left, in this browser, for this company: the next walk starts there, unless
  // another floor is in view. A few hours on, it starts afresh.
  const WHERE = `arnheim-walk-where:${ctx.org.company || ''}:${ctx.hallFor ? 'photo' : 'drawn'}`;
  const lastTime = (() => {
    try {
      const w = JSON.parse(localStorage.getItem(WHERE) || 'null');
      if (!w || typeof w.floor !== 'string' || !(Date.now() - w.at < 4 * 3600 * 1000)) return null;
      return { floor: w.floor, spot: [w.x, w.z, w.yaw].every(Number.isFinite) ? w : null };
    } catch { return null; }
  })();
  // left mid-ride: the floor it was going to, at its lift
  function remember() {
    if (!here) return;
    const saved = ride ? { floor: (ride.to || here).id } : { floor: here.id, x: me.x, z: me.z, yaw: me.yawGoal };
    try { localStorage.setItem(WHERE, JSON.stringify({ ...saved, at: Date.now() })); } catch { /* a private window: the next walk starts afresh */ }
  }
  window.addEventListener('pagehide', remember, { signal });

  const ground = [...storeys].sort((a, b) => Math.abs(a.y) - Math.abs(b.y) || b.y - a.y)[0];
  const back = lastTime && (!ctx.start || ctx.start === lastTime.floor) ? order.find((s) => s.id === lastTime.floor) : null;
  const fresh = storeys.find((s) => s.id === ctx.start) || storeys.find((s) => s.role === 'lobby') || ground;
  const first = back || fresh;
  for (const s of storeys) s.group.visible = false; // one floor at a time
  enter(first, back ? 'lift' : first.role === 'lobby' ? 'entrance' : 'lift');
  const spot = back && lastTime.spot;
  let fellBack = false;
  if (spot) {
    const at = { x: me.x, z: me.z, yaw: me.yaw };
    me.x = spot.x;
    me.z = spot.z;
    me.yaw = me.yawGoal = spot.yaw;
    free();
    // somewhere you can stand and walk from, or the floor's lift as on any arrival (the floor may have changed)
    // (a pocket a few squares across, walled off from the rest of the floor, counts as nowhere)
    const room = blocked(me.x, me.z) ? 0 : reach().reduce((n, v) => n + v, 0);
    if (room < 60) { me.x = at.x; me.z = at.z; me.yaw = me.yawGoal = at.yaw; fellBack = true; }
    placeSpots();
    findDoors();
    planBaseOf();
    inLift = hall.inLift(me.x, me.z);
    heldOff = spots.some((s) => Math.hypot(me.x - s.x, me.z - s.z) < 0.42); // back in a ring: no talk until you step off it
  }
  resumed = !!back && !fellBack;
  drawNeeds();
  openPicker(); // where you are and what is here, from the first step
  setPlan((() => { try { return localStorage.getItem('arnheim-walk-plan') !== 'off'; } catch { return true; } })());
  needsTimer = setInterval(drawNeeds, 2000);
  // No effect on arrival: the walk simply opens on the finished rooms.

  if (photoState === 'loading') {
    const show = (k) => { loadingBar.style.width = `${Math.round(k * 100)}%`; };
    show(job.k);
    job.listen = show;
    job.promise.then((p) => {
      if (gone) { p.dispose(); return; }
      photo = p;
      for (const entry of halls.values()) dressHall(entry, p);
      photoState = 'on';
      loadingText.textContent = 'Real materials on';
      loadTimer = setTimeout(() => {
        loading.classList.add('aw-faded');
        loadTimer = setTimeout(() => { loading.hidden = true; }, 700);
      }, 900);
      ctx.wake(3);
    }, (error) => {
      if (gone) return;
      photoState = 'failed';
      loading.hidden = true;
      console.warn('Arnheim: the real materials did not load, so the drawn ones stay.', error);
    });
  }

  // For tests: whether a spot on this floor stops the walker, and the squares they can reach from where they stand.
  const debug = { blocked: (x, z) => blocked(x, z), reach: () => reach(), map: () => map, me: () => ({ x: me.x, z: me.z }), doors: () => Object.fromEntries(doors), labels: () => labels(),
    // walks you to a spot on this floor, round whatever is in the way (for tests)
    go(x, z) { const way = wayTo(x, z); if (way) { me.target = { ...way.shift(), next: way }; ctx.wake(2); } return !!way; },
    // what a tap on the floor at (x, z) does: where you would end up standing, and whether there is a way
    tapTo(x, z) { const goal = roomAt(x, z); const way = goal && wayTo(goal.x, goal.z); if (way) { me.target = { ...way.shift(), next: way, open: true }; ctx.wake(2); } return way ? goal : null; },
    yaw: () => me.yawGoal, openAhead: (yaw) => openAhead(yaw ?? me.yawGoal),
    // the guide to this floor and what needs you (for tests)
    guide: () => onThisFloor().map(({ kind, title, sub }) => ({ kind, title, sub })),
    rings: () => spots.map((s) => ({ title: s.who.title, x: s.x, z: s.z, way: !!wayTo(s.x, s.z) })),
    roomAt: (x, z) => { const g = roomAt(x, z); return g && { ...g, way: !!wayTo(g.x, g.z) }; },
    target: () => (me.target ? { x: me.target.x, z: me.target.z, left: me.target.next?.length || 0 } : null),
    needs: () => needsAll().map((n) => ({ floor: n.s.id, title: n.o.title })),
    // the floor you are on, a ride to another (by its id), and where its lead stands (for tests)
    here: () => here?.id || null, leadPlan: () => leadPlan(),
    // this floor's rooms, and how many things in each can be tapped or talked to (for tests)
    rooms: () => here.rooms.map((r) => ({ id: r.roomId, label: r.label, info: ctx.infoText(r.info) || '', things: r.objects.length, people: spots.filter((s) => s.who.roomId === r.roomId && s.who.floorId === r.floorId).length })),
    ride: (id) => { const s = order.find((x) => x.id === id); if (s && s !== here) rideTo(s); return !!s; },
    lead: () => (hall?.lead ? { x: hall.lead.x, z: hall.lead.z, stand: hall.lead.stand, out: hall.lead.out, title: hall.lead.who.title, at: hall.spot && { x: hall.spot.x, z: hall.spot.z } } : null),
    // what a live change costs, part by part, in milliseconds (for tests)
    resurveyCost(full = false) {
      const t = [performance.now()];
      look(!full); t.push(performance.now());
      placeSpots(); t.push(performance.now());
      free(); planBaseOf(); t.push(performance.now());
      drawNeeds(); t.push(performance.now());
      const ms = (i) => Math.round((t[i + 1] - t[i]) * 10) / 10;
      return { survey: ms(0), rings: ms(1), plan: ms(2), needs: ms(3) };
    } };
  return { update, labels, info, dispose, setNotes: notes.set, debug };
}
