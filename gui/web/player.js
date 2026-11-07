"use strict";
/* Player: the library view, the bar that stays at the bottom, the equalizer and the crossfade.
   Uses the helpers of app.js ($, $$, esc, fmt, call, toast, show); the program side is Api.library_list / get_player / save_player.
   Audio graph: two decks (so that two songs can overlap) -> preamp -> 10 filters -> analyser -> volume -> speakers. */

const EQ_FREQS = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
const EQ_LABELS = ["31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k"];
const EQ_RANGE = 12;
/* Starting points: the blogs that publish "best settings" disagree with each other, so these are moderate curves
   (nothing beyond +5.5 dB) in the spirit of the classic desktop-player presets. The preamp lowers the level by
   the biggest boost, so a preset never clips. */
const EQ_PRESETS = [
  { id: "flat", name: "Plano", bands: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0] },
  { id: "bass", name: "Bajos", bands: [5, 4.5, 3.5, 2, .5, 0, 0, 0, 0, 0] },
  { id: "treble", name: "Agudos", bands: [0, 0, 0, 0, 0, 1, 2.5, 4, 5, 5.5] },
  { id: "pop", name: "Pop", bands: [-1.5, -.5, 1, 2.5, 3.5, 3, 1.5, 0, -.5, -1] },
  { id: "rock", name: "Rock", bands: [4, 3, 2, .5, -1, -.5, 1.5, 3, 4, 4.5] },
  { id: "hiphop", name: "Hip-hop y reggaetón", bands: [5, 5, 3.5, 1, -2, -1, .5, 1.5, 2, 2] },
  { id: "electronic", name: "Electrónica", bands: [4.5, 4, 2, 0, -1, -1.5, 0, 2, 4, 4.5] },
  { id: "jazz", name: "Jazz", bands: [3, 2, 1, 1.5, -1.5, -1.5, 0, 1, 2, 3] },
  { id: "classical", name: "Clásica", bands: [2, 1.5, 1, .5, 0, 0, 0, .5, 1.5, 2] },
  { id: "acoustic", name: "Acústica", bands: [2, 2, 1.5, .5, .5, 1, 1.5, 2, 2, 1.5] },
  { id: "vocal", name: "Voz", bands: [-2, -1.5, -1, .5, 2, 3, 3, 2, .5, 0] },
  { id: "loudness", name: "Volumen bajo", bands: [4.5, 3.5, 1, 0, -1, -.5, 0, 1.5, 3.5, 4.5] },
];
const FLAT = EQ_PRESETS[0].bands;
const MAX_CUSTOM = 8, MIN_CUSTOM = 3, MAX_SAVED_QUEUE = 2000;
const QUICK_FADE = .35;     // seconds: when the user skips by hand
const TICK = 150;
const MAX_RECENT = 30;

const P = {
  tracks: [], byId: new Map(), queue: [], original: null, pos: -1,
  shuffle: false, repeat: "off", volume: .8, muted: false, xf: 0,
  eq: { on: true, bands: [...FLAT], preset: "flat" },
  custom: [1, 2, 3].map(n => ({ id: "c" + n, name: "Personalizado " + n, bands: [...FLAT] })),
  seen: new Map(), q: "", sort: "artist", pulseOn: true, discId: "", swapToken: 0, armAngle: null, armLifted: true, armBusy: false, ready: false, dragging: false, errors: 0,
  ctx: null, decks: [], active: 0, pre: null, filters: [], analyser: null, master: null,
  fading: null, timer: 0, saveTimer: 0, lastSaved: 0, accent: "", bars: 0, wired: false,
  recent: [],      // the ids of the songs played last, newest first (the start page of the phone layout shows them)
};

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const trackOf = id => P.byId.get(id) || P.seen.get(id) || null;
const current = () => trackOf(P.queue[P.pos]);
const deck = () => P.decks[P.active];
const isPlaying = () => !!(P.decks.length && !deck().el.paused);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/* ---------- audio graph ---------- */
function buildAudio() {
  if (P.ctx) return;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  P.ctx = new Ctx();
  P.pre = P.ctx.createGain();
  P.filters = EQ_FREQS.map((f, i) => {
    const node = P.ctx.createBiquadFilter();
    node.type = i === 0 ? "lowshelf" : i === EQ_FREQS.length - 1 ? "highshelf" : "peaking";
    node.frequency.value = f; node.Q.value = 1.4;
    return node;
  });
  // 512 samples = bands of ~94 Hz (the bass gets its own bands); the default range tops out at -30 dB, where loud music's bass
  // saturates and every hit looks the same
  P.analyser = P.ctx.createAnalyser(); P.analyser.fftSize = 512; P.analyser.smoothingTimeConstant = .6;
  P.analyser.minDecibels = -90; P.analyser.maxDecibels = -8;
  P.master = P.ctx.createGain();
  P.decks = [0, 1].map(() => {
    const el = new Audio();
    el.crossOrigin = "anonymous"; el.preload = "auto";
    const gain = P.ctx.createGain();
    P.ctx.createMediaElementSource(el).connect(gain);
    gain.connect(P.pre);
    const d = { el, gain };
    el.addEventListener("ended", () => { if (d === deck()) { resetListening(); advance(true); } });
    el.addEventListener("error", () => { if (d === deck() && el.getAttribute("src")) onBroken(); });
    el.addEventListener("play", () => { if (d === deck()) { render(); syncMediaState(); } });
    el.addEventListener("seeked", () => { if (d === deck()) syncMediaState(); });
    el.addEventListener("loadedmetadata", () => { if (d === deck()) syncMediaState(); });
    el.addEventListener("playing", () => { if (d === deck()) P.errors = 0; });   // a song that plays ends the run of broken ones
    el.addEventListener("pause", () => { if (d === deck()) { render(); saveSoon(); syncMediaState(); } });
    return d;
  });
  P.decks[1].gain.gain.value = 0;
  [P.pre, ...P.filters, P.analyser, P.master].reduce((a, b) => (a.connect(b), b));
  P.master.connect(P.ctx.destination);
  applyEq(); applyVolume();
}

function applyEq() {
  if (!P.ctx) return;
  const bands = P.eq.on ? P.eq.bands : FLAT;
  bands.forEach((g, i) => { P.filters[i].gain.value = g; });
  P.pre.gain.value = 10 ** (-Math.max(0, ...bands) / 20);
}

function applyVolume() {
  if (P.master) P.master.gain.value = P.muted ? 0 : P.volume * P.volume * (P.fade ?? 1);   // P.fade: the sleep timer lowering the volume
}

/* Equal-power fade: the two songs keep a steady loudness while they overlap. */
function fadeGain(node, from, seconds) {
  const g = node.gain, now = P.ctx.currentTime, steps = 48, curve = new Float32Array(steps);
  for (let i = 0; i < steps; i++) { const t = i / (steps - 1); curve[i] = from ? Math.cos(t * Math.PI / 2) : Math.sin(t * Math.PI / 2); }
  g.cancelScheduledValues(now);
  g.setValueAtTime(g.value, now);
  g.setValueCurveAtTime(curve, now + .001, Math.max(.05, seconds));
}

function endFade() {
  if (!P.fading) return;
  clearTimeout(P.fading.timer);
  const old = P.fading.old;
  old.el.pause(); old.el.removeAttribute("src"); old.el.load();
  old.gain.gain.cancelScheduledValues(0); old.gain.gain.value = 0;
  P.fading = null;
}

/* ---------- playing ---------- */
function cueTrack(track, atTime = 0) {
  buildAudio();
  endFade();
  const d = deck();
  d.gain.gain.cancelScheduledValues(0); d.gain.gain.value = 1;
  d.el.src = track.url;
  if (atTime > 0) d.el.addEventListener("loadedmetadata", () => { d.el.currentTime = Math.min(atTime, Math.max(0, d.el.duration - 1)); }, { once: true });
}

async function startTrack(track, seconds = 0) {
  buildAudio();
  try { await P.ctx.resume(); } catch (e) { /* the bar still shows the song */ }
  const old = deck();
  const overlap = seconds > 0 && !old.el.paused && old.el.getAttribute("src");
  endFade();
  if (overlap) {
    const incoming = P.decks[1 - P.active];
    incoming.el.src = track.url;
    P.active = 1 - P.active;
    fadeGain(incoming.gain, 0, seconds);
    fadeGain(old.gain, 1, seconds);
    P.fading = { old, timer: setTimeout(endFade, seconds * 1000 + 80) };
    incoming.el.play().catch(onPlayRefused);
  } else {
    old.el.pause();
    old.gain.gain.cancelScheduledValues(0); old.gain.gain.value = 1;
    old.el.src = track.url;
    old.el.play().catch(onPlayRefused);
  }
  trackChanged();
}

function onPlayRefused(error) {
  if (error && ["AbortError", "NotSupportedError"].includes(error.name)) return;   // skipped before it started / a broken file (its own error event reports it)
  toast("No pude reproducir esa canción.", true);
}

function onBroken() {
  const track = current();
  toast(`No pude reproducir «${track ? track.title : "la canción"}». La salto.`, true);
  if (++P.errors > Math.min(P.queue.length, 5)) { P.errors = 0; return; }
  advance(true, true);
}

function hasNext() { return P.pos + 1 < P.queue.length || (P.repeat === "all" && P.queue.length > 0); }

function advance(auto, skipBroken = false) {
  if (!P.queue.length) return;
  if (auto && SL.mode === "song") {      // the sleep timer waits for this song to end: no crossfade into the next, no next
    const el = deck().el;
    if (el.ended || (isFinite(el.duration) && el.duration - el.currentTime < .8)) finishSleep();
    return;
  }
  if (auto && P.repeat === "one" && !skipBroken) { deck().el.currentTime = 0; deck().el.play().catch(onPlayRefused); return; }
  let next = P.pos + 1;
  if (next >= P.queue.length) {
    if (P.repeat !== "all") {
      if (auto) { deck().el.pause(); deck().el.currentTime = 0; render(); }
      return;
    }
    next = 0;
  }
  goTo(next, auto ? Math.min(P.xf, Math.max(0, deck().el.duration - deck().el.currentTime)) : QUICK_FADE);
}

function goTo(position, seconds = QUICK_FADE) {
  const track = trackOf(P.queue[position]);
  if (!track) return;
  P.pos = position;
  startTrack(track, reduced() ? 0 : seconds);
}

function previous() {
  if (!P.queue.length) return;
  if (deck().el.currentTime > 3 || P.pos <= 0 && P.repeat !== "all") { deck().el.currentTime = 0; return; }
  goTo(P.pos <= 0 ? P.queue.length - 1 : P.pos - 1);
}

function toggle() {
  if (!current()) return;
  buildAudio();
  if (deck().el.paused) {
    if (!deck().el.getAttribute("src")) { cueTrack(current(), P.resume || 0); P.resume = 0; }   // it was unloaded to be tagged
    P.ctx.resume().catch(() => {}); deck().el.play().catch(onPlayRefused);
  }
  else { endFade(); deck().el.pause(); }   // a pause during a crossfade cuts the song that was leaving
}

function seek(seconds) {
  if (!current() || !isFinite(deck().el.duration)) return;
  deck().el.currentTime = clamp(seconds, 0, deck().el.duration);
  paint();
}

function setVolume(v) {
  P.volume = clamp(v, 0, 1);
  if (P.volume > 0) P.muted = false;
  applyVolume(); paintVolume(); saveSoon();
}

/* ---------- queue ---------- */
function shuffled(list) {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [out[i], out[j]] = [out[j], out[i]]; }
  return out;
}

function playList(ids, startId) {
  const start = startId || ids[0];
  if (!ids.length) return;
  P.original = [...ids];
  if (P.shuffle) { P.queue = [start, ...shuffled(ids.filter(id => id !== start))]; P.pos = 0; }
  else { P.queue = [...ids]; P.pos = Math.max(0, ids.indexOf(start)); }
  startTrack(current(), 0);
  renderQueue(); saveSoon();
}

function setShuffle(on) {
  P.shuffle = on;
  const id = P.queue[P.pos];
  if (on && P.queue.length) {
    P.original = P.original || [...P.queue];
    P.queue = [id, ...shuffled(P.queue.filter(x => x !== id))]; P.pos = 0;
  } else if (!on && P.original) {
    const kept = P.original.filter(x => trackOf(x));
    if (kept.includes(id)) { P.queue = kept; P.pos = kept.indexOf(id); }
  }
  render(); renderQueue(); saveSoon();
  if (window.__nativeMedia) window.__nativeMedia();      // the phone's notification shows the shuffle state
}

function cycleRepeat() {
  P.repeat = { off: "all", all: "one", one: "off" }[P.repeat];
  render(); saveSoon();
}

function enqueue(id, asNext, source) {
  if (!trackOf(id)) return;
  if (!P.queue.length) return playList([id], id);
  P.original = null;
  P.queue.splice(asNext ? P.pos + 1 : P.queue.length, 0, id);
  flyToQueue(source);
  toast(asNext ? "Sonará a continuación." : "Añadida a la cola.");
  renderQueue(); saveSoon();
}

/* The song's cover leaves its row, curves down and shrinks into the queue button, which then gives a little bump. */
function flyToQueue(source) {
  const target = $("#pl-queue");
  if (!source || reduced() || $("#player").classList.contains("hidden")) return;
  const from = source.getBoundingClientRect(), to = target.getBoundingClientRect();
  const ghost = source.cloneNode(true);
  Object.assign(ghost.style, { position: "fixed", left: from.left + "px", top: from.top + "px", width: from.width + "px", height: from.height + "px",
    margin: 0, zIndex: 40, pointerEvents: "none", borderRadius: "10px", boxShadow: "0 10px 30px rgba(0,0,0,.5)" });
  document.body.append(ghost);
  const dx = to.left + to.width / 2 - (from.left + from.width / 2), dy = to.top + to.height / 2 - (from.top + from.height / 2);
  const fly = ghost.animate([
    { transform: "translate(0, 0) scale(1)", opacity: 1, offset: 0 },
    { transform: `translate(${dx * .35}px, ${dy * .1 - 40}px) scale(1.12) rotate(-6deg)`, opacity: 1, offset: .35 },
    { transform: `translate(${dx}px, ${dy}px) scale(.3) rotate(8deg)`, opacity: .35, offset: 1 },
  ], { duration: 650, easing: "cubic-bezier(.45, 0, .55, 1)", fill: "forwards" });
  fly.onfinish = () => {
    ghost.remove();
    target.animate([{ transform: "scale(1)" }, { transform: "scale(1.35)" }, { transform: "scale(1)" }], { duration: 360, easing: "cubic-bezier(.23, 1, .32, 1)" });
  };
}

function removeFromQueue(index) {
  const wasCurrent = index === P.pos, wasPlaying = isPlaying();
  P.original = null;
  P.queue.splice(index, 1);
  if (index < P.pos) P.pos--;
  if (!P.queue.length) {
    P.pos = -1;
    if (P.decks.length) { deck().el.pause(); deck().el.removeAttribute("src"); deck().el.load(); }
  } else if (wasCurrent) {
    if (P.pos >= P.queue.length) P.pos = P.queue.length - 1;   // it was the last one: the new last one is cued, not played
    else if (wasPlaying) { startTrack(current(), QUICK_FADE); return renderQueue(), saveSoon(); }
    if (!wasPlaying || index >= P.queue.length) { deck().el.pause(); cueTrack(current()); }
  }
  trackChanged(); renderQueue(); saveSoon();
}

function moveInQueue(from, to) {
  if (from === to || from < 0 || to < 0 || from >= P.queue.length || to >= P.queue.length) return;
  const id = P.queue[P.pos];
  P.original = null;
  const [moved] = P.queue.splice(from, 1);
  P.queue.splice(to, 0, moved);
  P.pos = P.queue.indexOf(id);
  renderQueue(); saveSoon();
}

function clearQueue() {
  const id = P.queue[P.pos];
  P.original = null;
  P.queue = id ? [id] : []; P.pos = id ? 0 : -1;
  renderQueue(); saveSoon();
}

/* ---------- the bar ---------- */
/* A song without a cover gets a gradient whose hue comes from its name, so the same song always looks the same. */
function hueOf(track) {
  let h = 0;
  for (const c of `${track.artist}|${track.title}`) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

function coverHTML(track) {
  return track.cover_url ? `<img src="${esc(track.cover_url)}" alt="" loading="lazy" decoding="async">` : "";
}

function noteRecent(track) {
  P.recent = [track.id, ...P.recent.filter(id => id !== track.id)].slice(0, MAX_RECENT);
}

function trackChanged() {
  const track = current();
  if (track) noteRecent(track);
  if (!track) extractAccent({});
  paintCover(track);
  render();
  paintLibraryMarks();
  renderQueue();
  setMediaSession(track);
  lyricsTrackChanged();
  resetListening();
  if (track) extractAccent(track);
  saveSoon(true);
}

function render() {
  const track = current(), playing = isPlaying();
  $("#player").classList.toggle("hidden", !track);
  $("#app").classList.toggle("has-player", !!track);
  document.body.classList.toggle("has-player", !!track);   // the toasts rise above the bar
  $("#player").classList.toggle("is-playing", playing);
  $("#app").classList.toggle("audio-on", playing);   // the vinyl and the little bars move only while it sounds
  if (!track) return paintArm();
  $("#pl-title").textContent = track.title;
  $("#pl-artist").textContent = track.artist || "Artista desconocido";
  const liked = L.liked.has(track.id);
  $("#pl-like").classList.toggle("on", liked); $("#pl-like").setAttribute("aria-pressed", liked);
  $("#pl-like").title = liked ? "Quitar de Me gusta" : "Me gusta";
  $("#pl-play").setAttribute("aria-label", playing ? "Pausa" : "Reproducir");
  $("#pl-play").title = playing ? "Pausa" : "Reproducir";
  $("#pl-shuffle").setAttribute("aria-pressed", P.shuffle);
  $("#pl-repeat").setAttribute("aria-pressed", P.repeat !== "off");
  $("#pl-repeat").dataset.mode = P.repeat;
  $("#pl-repeat").title = { off: "Repetir: no", all: "Repetir toda la cola", one: "Repetir esta canción" }[P.repeat];
  paintVolume();
  paint();
  loopSpectrum();   // also paused: the bars sink to a flat line (or draw it the first time)
}

function paintCover(track) {
  const img = $("#pl-cover"), disc = $("#vinyl-cover"), has = !!(track && track.cover_url);
  $("#pl-initial").textContent = track ? (track.title || "♪").trim().charAt(0).toUpperCase() : "♪";
  $(".pl-cover").classList.toggle("ph", !has);
  if (track) $(".pl-cover").style.setProperty("--h", hueOf(track));
  const paintDisc = () => {
    if (has) { disc.src = track.cover_url; disc.hidden = false; }
    else { disc.hidden = true; disc.removeAttribute("src"); }
  };
  if (has) { img.src = track.cover_url; img.hidden = false; }
  else { img.hidden = true; img.removeAttribute("src"); }
  const id = track ? track.id : "";
  if (id !== P.discId) { const first = !P.discId; P.discId = id; swapVinyl(paintDisc, first); }
  else paintDisc();
}

/* Changing song changes the record, as on a turntable: the one on the platter lifts off to the side and fades, the new one
   (its label is the new cover) drops in from above and settles, turning all the while. The turning is the css animation on
   `transform`; these use the separate `translate`, `scale` and `opacity` properties, so the two do not fight. */
async function swapVinyl(apply, first) {
  const disc = $("#vinyl");
  const token = ++P.swapToken;
  disc.getAnimations().forEach(a => { if (a.id === "swap") a.cancel(); });
  const opacity = parseFloat(getComputedStyle(disc).opacity);
  if (reduced() || getComputedStyle(disc).display === "none" || opacity < .05) {   // not on screen: just change it
    apply(); P.armBusy = false; paintArm();
    return;
  }
  const run = (keyframes, options) => { const a = disc.animate(keyframes, { id: "swap", ...options }); return a.finished.catch(() => {}); };
  // The needle goes first: it lifts and swings clear of the record, then the record goes and the next one comes.
  if (first) { P.armBusy = true; setArm(ARM.rest, 0, true); }
  else {
    await armAway();
    if (token !== P.swapToken) return;
    await run([{ translate: "0 0", scale: "1", opacity }, { translate: "90px -46px", scale: ".9", opacity: 0 }],
              { duration: 340, easing: "cubic-bezier(.5, 0, .9, .45)", fill: "forwards" });
    if (token !== P.swapToken) return;
  }
  apply();
  disc.getAnimations().forEach(a => { if (a.id === "swap") a.cancel(); });
  await run([{ translate: "-30px -80px", scale: "1.08", opacity: 0 }, { translate: "0 0", scale: "1", opacity, offset: .7 }, { translate: "0 0", scale: "1", opacity }],
            { duration: 620, easing: "cubic-bezier(.23, 1, .32, 1)", fill: "backwards" });
  if (token === P.swapToken) await armBack();      // ...and the needle comes down on the new record, where the song is
}

/* ---------- the tonearm ---------- */
const ARM = { out: 153, inn: 121.8, rest: 170, lift: 3 };    // degrees: needle on the outer groove, on the inner one, clear of the record
const ARM_EASE = "cubic-bezier(.4, 0, .2, 1)";
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

function setArm(angle, ms, lifted, ease = "linear") {
  const arm = $(".ta-arm");
  P.armAngle = angle; P.armLifted = lifted;
  arm.style.transition = reduced() || !ms ? "none" : `rotate ${ms}ms ${ease}`;
  arm.style.rotate = angle + "deg";
  $("#tonearm").classList.toggle("lifted", lifted);
}

/* Where the needle belongs now: along the record as far as the song has gone (a little lifted while paused); with nothing
   loaded it rests clear of the record. */
function armPlace() {
  const track = current();
  if (!track || !P.decks.length) return { angle: ARM.rest, lifted: true };
  const el = deck().el, dur = isFinite(el.duration) && el.duration > 0 ? el.duration : track.duration || 0;
  const base = ARM.out - (ARM.out - ARM.inn) * clamp(dur ? (el.currentTime || 0) / dur : 0, 0, 1);
  return el.paused ? { angle: base + ARM.lift, lifted: true } : { angle: base, lifted: false };
}

/* Called on every tick: the needle follows the playing time in small steps; when the time jumps (the bar is dragged, a seek) or
   it lifts or lands (pause, play), it glides there instead of snapping. */
function paintArm() {
  if (P.armBusy) return;
  const { angle, lifted } = armPlace();
  const jump = Math.abs(angle - (P.armAngle ?? angle)) > 1.2, toggled = lifted !== P.armLifted;
  if (angle === P.armAngle && !toggled) return;
  setArm(angle, jump ? 700 : toggled ? 450 : 220, lifted, jump || toggled ? ARM_EASE : "linear");
}

async function armAway() {
  P.armBusy = true;
  setArm(ARM.rest, 380, true, ARM_EASE);
  await wait(380);
}

async function armBack() {
  const { angle, lifted } = armPlace();
  P.armAngle = null;
  setArm(angle, 620, lifted, ARM_EASE);
  await wait(620);
  P.armBusy = false;
  paintArm();
}

function paint() {
  const track = current();
  if (!track || !P.decks.length) return;
  const el = deck().el, dur = isFinite(el.duration) && el.duration > 0 ? el.duration : track.duration || 0;
  const bar = $("#pl-progress");
  bar.max = String(dur || 1);
  if (!P.dragging) bar.value = String(Math.min(el.currentTime || 0, dur || 1));
  const shown = P.dragging ? +bar.value : el.currentTime || 0;
  bar.style.setProperty("--p", dur ? (shown / dur * 100) + "%" : "0%");
  paintArm();
  $("#pl-cur").textContent = fmt(Math.floor(shown));
  $("#pl-dur").textContent = fmt(Math.floor(dur));
}

function paintVolume() {
  const bar = $("#pl-volume");
  bar.value = String(P.muted ? 0 : P.volume);
  bar.style.setProperty("--p", (P.muted ? 0 : P.volume * 100) + "%");
  $("#pl-mute").classList.toggle("is-muted", P.muted || P.volume === 0);
}

function tick() {
  if (!P.decks.length) return;
  paint();
  const el = deck().el;
  countListening(el);
  if (!el.paused && P.xf > 0 && P.repeat !== "one" && !P.fading && hasNext()) {
    const left = el.duration - el.currentTime;
    if (isFinite(left) && el.duration > P.xf * 2 && left <= P.xf) advance(true);
  }
  if (Date.now() - P.lastSaved > 5000 && !el.paused) { P.lastSaved = Date.now(); call("save_player", snapshot()); }
}

function setMediaSession(track) {
  if (!("mediaSession" in navigator)) return;
  if (!track) { navigator.mediaSession.metadata = null; return; }
  navigator.mediaSession.metadata = new MediaMetadata({
    title: track.title, artist: track.artist, album: track.album,
    // Windows shows the cover in its media panel; sizes are a hint, the same picture serves them all
    artwork: track.cover_url ? ["96x96", "256x256", "512x512"].map(sizes => ({ src: track.cover_url, sizes })) : [],
  });
  syncMediaState();
}

// what the system panel (and the keyboard's media keys) show: playing or paused, and where in the song
function syncMediaState() {
  if (!("mediaSession" in navigator)) return;
  const el = P.decks.length ? deck().el : null;
  navigator.mediaSession.playbackState = !current() ? "none" : isPlaying() ? "playing" : "paused";
  try {
    if (el && isFinite(el.duration) && el.duration > 0) navigator.mediaSession.setPositionState({ duration: el.duration, position: Math.min(el.currentTime, el.duration), playbackRate: el.playbackRate || 1 });
  } catch (e) { /* the browser refuses odd values while a song is loading */ }
  if (window.__nativeMedia) window.__nativeMedia();      // inside the Android app: the notification and the lock screen (androidmedia.js)
}

/* ---------- colour from the cover ---------- */
const DEFAULT_ACCENT = "#b5ef4a";
function extractAccent(track) {
  const style = $("#app").style;
  const apply = tones => {
    if (!tones) { P.accent = DEFAULT_ACCENT; ["--pc", "--blob1", "--blob2", "--blob3"].forEach(k => style.removeProperty(k)); return; }
    P.accent = tones.accent;
    style.setProperty("--pc", tones.accent);
    style.setProperty("--blob1", tones.b1); style.setProperty("--blob2", tones.b2); style.setProperty("--blob3", tones.b3);
  };
  if (!track.cover_url) return apply(null);
  const img = new Image();
  img.crossOrigin = "anonymous";
  img.onload = () => {
    if (current() !== track) return;
    try {
      const c = document.createElement("canvas"); c.width = c.height = COVER_SAMPLE;
      const x = c.getContext("2d", { willReadFrequently: true });
      x.drawImage(img, 0, 0, COVER_SAMPLE, COVER_SAMPLE);
      apply(tonesOf(x.getImageData(0, 0, COVER_SAMPLE, COVER_SAMPLE).data));
    } catch (e) { apply(null); }
  };
  img.onerror = () => apply(null);
  img.src = track.cover_url;
}

/* The colours of the window for a cover, from the RGBA pixels of a small copy of it. The three blobs of the background take the
   three most present colours of the cover, so the whole window changes with the song and not just one corner.
   The colours are found by counting hues (how vivid and bright each pixel is decides its weight), not by averaging: a cover that
   is red and turquoise averages to grey, and the window must be red and turquoise. A grey, black or white cover (a third of a
   real library) has no hue at all: it gets a cool neutral, and its brightness decides how bright the glow is (dim for a black
   cover, soft and light for a white one). */
const COVER_SAMPLE = 20, HUE_BINS = 24;
const hueGap = (a, b) => { const d = Math.abs(a - b) % 360; return d > 180 ? 360 - d : d; };

function tonesOf(pixels) {
  const weight = new Float32Array(HUE_BINS), vx = new Float32Array(HUE_BINS), vy = new Float32Array(HUE_BINS), sat = new Float32Array(HUE_BINS);
  let n = 0, lightSum = 0;
  for (let i = 0; i < pixels.length; i += 4) {
    const r = pixels[i] / 255, g = pixels[i + 1] / 255, b = pixels[i + 2] / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), c = max - min;
    n++; lightSum += (max + min) / 2;
    if (c < .1 || max < .15) continue;                                  // greys and near-blacks carry no hue
    const h = (max === r ? ((g - b) / c) % 6 : max === g ? (b - r) / c + 2 : (r - g) / c + 4) * 60;
    const bin = Math.floor(((h + 360) % 360) / (360 / HUE_BINS)) % HUE_BINS, w = c * (.4 + max * .6);
    weight[bin] += w; vx[bin] += Math.cos(h * Math.PI / 180) * w; vy[bin] += Math.sin(h * Math.PI / 180) * w;
    sat[bin] += c / (1 - Math.abs(max + min - 1) || 1) * w;
  }
  const light = lightSum / n * 100, total = weight.reduce((a, b) => a + b, 0);
  const near = i => weight[(i + HUE_BINS - 1) % HUE_BINS] * .5 + weight[i] + weight[(i + 1) % HUE_BINS] * .5;   // neighbouring bins are one colour
  // the most present colours, each at least 50° from the ones already chosen
  const peaks = [];
  [...weight.keys()].sort((a, b) => near(b) - near(a)).forEach(bin => {
    const share = near(bin) / (total || 1);
    if (peaks.length >= 3 || share < .06) return;
    const around = [bin - 1, bin, bin + 1].map(k => (k + HUE_BINS) % HUE_BINS);
    const x = around.reduce((a, k) => a + vx[k], 0), y = around.reduce((a, k) => a + vy[k], 0), w = around.reduce((a, k) => a + weight[k], 0);
    const hue = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
    if (peaks.every(p => hueGap(p.hue, hue) >= 50)) peaks.push({ hue, s: around.reduce((a, k) => a + sat[k], 0) / (w || 1) });
  });
  const neutral = total < n * .03 || !peaks.length;                      // hardly any colour in the whole cover
  const hsl = (h, s, l) => `hsl(${Math.round((h + 360) % 360)} ${Math.round(s * 100)}% ${l}%)`;
  if (neutral) {
    const tone = l => hsl(215, .07, l);
    return { accent: tone(clamp(40 + light * .5, 55, 84)), b1: tone(clamp(18 + light * .6, 22, 70)), b2: tone(clamp(22 + light * .6, 26, 72)), b3: tone(clamp(24 + light * .6, 28, 74)) };
  }
  // fewer than three colours in the cover: the missing ones are neighbours of the main one, as before
  const [first, second = { hue: first.hue + 55, s: first.s * .9 }, third = { hue: first.hue - 50, s: first.s * .9 }] = peaks;
  const strong = s => clamp(s * 1.25, .4, .85);
  return { accent: hsl(first.hue, strong(first.s), 62), b1: hsl(first.hue, strong(first.s), 52), b2: hsl(second.hue, strong(second.s), 56), b3: hsl(third.hue, strong(third.s), 58) };
}

/* ---------- spectrum ---------- */
/* The bars grow from the middle line up and down. Each one eases towards its level (quickly up, slowly down), so a pause
   lets them sink to a flat line instead of vanishing; the loop stops by itself once they are flat. */
/* Fits a canvas to the pixels it really covers (css size x screen density), so the bars stay sharp on any window size and screen. */
function fitCanvas(canvas, scale = 1) {
  const w = Math.max(1, Math.round(canvas.clientWidth * scale)), h = Math.max(1, Math.round(canvas.clientHeight * scale));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  return [w, h];
}

/* One level per bar, each easing towards its target (quickly up, slowly down), so a pause lets everything sink instead of
   vanishing. Bars are spread over the lower 70 % of the spectrum, where the music is. */
function easeLevels(store, key, n, data, live) {
  if (!store[key] || store[key].length !== n) store[key] = new Float32Array(n);
  const lv = store[key];
  let moving = false;
  for (let i = 0; i < n; i++) {
    const v = live ? Math.min(1, (data[Math.floor(Math.pow(i / n, 1.4) * data.length * .7) + 1] / 255) ** 1.7 * 1.25) : 0;
    lv[i] += (v - lv[i]) * (v > lv[i] ? .5 : .1);
    if (lv[i] > .01) moving = true; else if (!live) lv[i] = 0;
  }
  return { lv, moving };
}

const viz = { store: {}, spring: null, pulse: 0, K: .1, D: .84, soft: .2, mem: .1, size: .13, reach: 22 };   // the pulse: spring stiffness and damping, how soft the target is, how far the halos move

/* The little bars in the player bar: from the middle line up and down; as many as fit in the width. */
function drawSmall(data, live) {
  const canvas = $("#pl-spectrum");
  if (!canvas.clientWidth) return false;           // hidden in narrow windows
  const dpr = devicePixelRatio || 1;
  const [w, h] = fitCanvas(canvas, dpr);
  const n = clamp(Math.floor(canvas.clientWidth / 5), 6, 24), slot = w / n, gap = Math.max(1, Math.round(slot * .3));
  const { lv, moving } = easeLevels(viz.store, "small", n, data, live);
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, w, h);
  ctx.fillStyle = P.accent || DEFAULT_ACCENT;
  for (let i = 0; i < n; i++) {
    const bar = Math.max(2 * dpr, lv[i] * h);
    ctx.globalAlpha = .4 + lv[i] * .6;
    ctx.fillRect(i * slot + gap / 2, (h - bar) / 2, slot - gap, bar);
  }
  return moving;
}

/* The halos sway with the music. A kick (the bass jumping above its own recent average) moves a soft spring: the target is
   smoothed first and the spring is well damped, so the halos swell and settle gently (a hint of overshoot, no jolt). Each halo
   leans in its own direction. The vinyl does not take part: it only turns. */
const BLOB_PUSH = [[-1, -.8], [1, -.3], [.4, 1]];     // where each of the three halos leans on a hit (x, y)
function drawPulse(data, live) {
  const spring = viz.spring || (viz.spring = { x: 0, v: 0, t: 0, avg: 0, peak: .05 });
  const bass = live ? (data[0] + data[1] + data[2]) / 765 : 0;      // up to ~280 Hz: kick and bass line
  // A hit is the bass rising above what it was a moment ago, judged against the biggest recent rise: loud and compressed music
  // (bass always near the top) and quiet music both give hits that fill the range.
  const rise = live ? Math.max(0, bass - spring.avg) : 0;
  spring.avg += (bass - spring.avg) * viz.mem;
  spring.peak = Math.max(rise, spring.peak * .99, .03);
  spring.t += ((live ? Math.min(1, rise / spring.peak) : 0) - spring.t) * viz.soft;     // no sudden jumps of the target
  spring.v = (spring.v + (spring.t - spring.x) * viz.K) * viz.D;
  spring.x += spring.v;
  const x = Math.abs(spring.x) < .003 && Math.abs(spring.v) < .003 && spring.t < .003 ? 0 : spring.x;
  if (!x) spring.x = spring.v = spring.t = 0;
  $$(".bg i:not(.glow)").forEach((blob, i) => {
    const [dx, dy] = BLOB_PUSH[i % BLOB_PUSH.length];
    blob.style.scale = x ? String(1 + x * (viz.size + i * .06)) : "";
    blob.style.translate = x ? `${dx * x * viz.reach}px ${dy * x * viz.reach}px` : "";
  });
  viz.pulse = x;               // read by the tests
  return x !== 0;
}

function loopSpectrum() {
  if (P.bars || !P.analyser) return;
  const data = new Uint8Array(P.analyser.frequencyBinCount);
  const draw = () => {
    P.bars = 0;
    const live = isPlaying() && !document.hidden && !reduced();
    if (live) P.analyser.getByteFrequencyData(data);
    const small = drawSmall(data, live), halos = P.pulseOn ? drawPulse(data, live) : false;
    if (live || small || halos) P.bars = requestAnimationFrame(draw);
  };
  P.bars = requestAnimationFrame(draw);
}

/* The background that beats with the music (the halos of colour) on or off; the halos go back to rest when it is turned off. */
function setPulse(on) {
  P.pulseOn = !!on;
  $("#viz-on").checked = P.pulseOn;
  $$(".bg i:not(.glow)").forEach(blob => { blob.style.scale = ""; blob.style.translate = ""; });
  viz.spring = null; viz.pulse = 0;
  loopSpectrum(); saveSoon();
}

/* ---------- panels ---------- */
function togglePanel(which) {
  const panels = { queue: ["#pl-queue-panel", "#pl-queue"], eq: ["#pl-eq-panel", "#pl-eq"] };
  Object.entries(panels).forEach(([name, [panel, button]]) => {
    const open = name === which && $(panel).classList.contains("hidden");
    $(panel).classList.toggle("hidden", !open);
    $(button).setAttribute("aria-expanded", open);
  });
  if (which === "queue") renderQueue();
}
const closePanels = () => togglePanel(null);

function renderQueue() {
  const panel = $("#pl-queue-panel");
  if (panel.classList.contains("hidden")) return;
  const list = $("#q-list");
  if (!P.queue.length) { list.innerHTML = '<p class="muted small q-empty">La cola está vacía. Elige una canción en la biblioteca.</p>'; return; }
  list.innerHTML = P.queue.map((id, i) => {
    const t = trackOf(id);
    if (!t) return "";
    return `<div class="q-row${i === P.pos ? " now" : ""}" draggable="true" data-i="${i}">
      <span class="q-cover${t.cover_url ? "" : " ph"}" style="--h:${hueOf(t)}"><span class="initial">${esc((t.title || "♪").trim().charAt(0).toUpperCase())}</span>${coverHTML(t)}<i class="q-eq" aria-hidden="true"><b></b><b></b><b></b></i></span>
      <span class="q-t"><b>${esc(t.title)}</b><span class="muted small">${esc(t.artist || "Artista desconocido")}</span></span>
      <button class="icon-btn q-grip" type="button" aria-label="Arrastrar para reordenar" title="Arrastrar para reordenar"><svg viewBox="0 0 24 24"><path d="M5 9h14M5 15h14"/></svg></button>
      <button class="icon-btn q-rm" type="button" data-rm="${i}" aria-label="Quitar de la cola" title="Quitar de la cola"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>`;
  }).join("");
  const now = $(".q-row.now", list);
  if (now) now.scrollIntoView({ block: "nearest" });
}

function wireQueue() {
  const list = $("#q-list");
  let from = -1;
  list.addEventListener("click", ev => {
    const rm = ev.target.closest("[data-rm]");
    if (rm) return removeFromQueue(+rm.dataset.rm);
    const row = ev.target.closest(".q-row");
    if (row) goTo(+row.dataset.i);
  });
  list.addEventListener("dragstart", ev => { const row = ev.target.closest(".q-row"); if (!row) return; from = +row.dataset.i; row.classList.add("drag"); ev.dataTransfer.effectAllowed = "move"; ev.dataTransfer.setData("text/plain", String(from)); });
  // A finger cannot start the browser's drag and drop: on a touch screen the row has a handle that follows the finger
  list.addEventListener("pointerdown", ev => {
    const grip = ev.target.closest(".q-grip");
    if (!grip || ev.pointerType === "mouse") return;
    const row = grip.closest(".q-row"), start = +row.dataset.i;
    let over = start;
    ev.preventDefault();
    try { grip.setPointerCapture(ev.pointerId); } catch (e) { /* the finger already left: the listeners below still end the drag */ }
    row.classList.add("drag");
    const move = e => {
      const rect = list.getBoundingClientRect();
      if (e.clientY < rect.top + 36) list.scrollBy(0, -10); else if (e.clientY > rect.bottom - 36) list.scrollBy(0, 10);     // near an edge the list follows
      const hit = document.elementFromPoint(e.clientX, e.clientY), target = hit && hit.closest(".q-row");
      if (target && list.contains(target)) { $$(".q-row.over", list).forEach(r => r.classList.remove("over")); target.classList.add("over"); over = +target.dataset.i; }
    };
    const end = () => {
      grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", end); grip.removeEventListener("pointercancel", end);
      $$(".q-row", list).forEach(r => r.classList.remove("drag", "over"));
      if (over !== start) moveInQueue(start, over);
    };
    grip.addEventListener("pointermove", move); grip.addEventListener("pointerup", end); grip.addEventListener("pointercancel", end);
  });
  list.addEventListener("dragend", () => { from = -1; $$(".q-row", list).forEach(r => r.classList.remove("drag", "over")); });
  list.addEventListener("dragover", ev => {
    const row = ev.target.closest(".q-row");
    if (from < 0 || !row) return;
    ev.preventDefault();
    $$(".q-row.over", list).forEach(r => r !== row && r.classList.remove("over"));
    row.classList.add("over");
  });
  list.addEventListener("drop", ev => {
    const row = ev.target.closest(".q-row");
    if (from < 0 || !row) return;
    ev.preventDefault();
    moveInQueue(from, +row.dataset.i);
  });
  $("#q-clear").onclick = clearQueue;
}

/* ---------- equalizer ---------- */
function sameBands(a, b) { return a.every((v, i) => Math.abs(v - b[i]) < .01); }
const activeCustom = () => P.custom.find(c => c.id === P.eq.preset) || null;

function buildEq() {
  $("#eq-bands").innerHTML = EQ_FREQS.map((_, i) => `<label class="eq-band"><output data-out="${i}">0</output>
    <input type="range" min="${-EQ_RANGE}" max="${EQ_RANGE}" step="0.5" value="0" data-band="${i}" aria-label="${EQ_LABELS[i]} Hz" orient="vertical">
    <span class="muted small">${EQ_LABELS[i]}</span></label>`).join("");
  $("#eq-bands").addEventListener("input", ev => {
    const i = ev.target.dataset.band;
    if (i === undefined) return;
    P.eq.bands[+i] = +ev.target.value;
    const slot = activeCustom();
    if (slot) slot.bands = [...P.eq.bands];                 // an own equalizer remembers what you do to it
    else P.eq.preset = EQ_PRESETS.find(p => sameBands(p.bands, P.eq.bands))?.id || "manual";
    applyEq(); paintEq(true); saveSoon();
  });
  $("#eq-bands").addEventListener("dblclick", ev => {
    const i = ev.target.dataset.band;
    if (i === undefined) return;
    ev.target.value = "0"; ev.target.dispatchEvent(new Event("input", { bubbles: true }));
  });
  $("#eq-presets").addEventListener("click", ev => {
    const b = ev.target.closest("[data-preset]");
    if (b) choosePreset(b.dataset.preset);
  });
  $("#eq-on").onchange = () => { P.eq.on = $("#eq-on").checked; applyEq(); paintEq(); saveSoon(); };
  $("#eq-save").onclick = saveCurrentEq;
  $("#eq-custom").addEventListener("click", ev => {
    const rename = ev.target.closest("[data-rename]"), del = ev.target.closest("[data-del]"), pick = ev.target.closest("[data-slot]");
    if (rename) return startRename(rename.dataset.rename);
    if (del) return deleteSlot(del.dataset.del);
    if (pick && !ev.target.closest("input")) choosePreset(pick.dataset.slot);
  });
  $("#eq-custom").addEventListener("dblclick", ev => { const pick = ev.target.closest("[data-slot]"); if (pick) startRename(pick.dataset.slot); });
}

function choosePreset(id) {
  const found = EQ_PRESETS.find(p => p.id === id) || P.custom.find(c => c.id === id);
  if (!found) return;
  P.eq.preset = id; P.eq.bands = [...found.bands]; P.eq.on = true;
  applyEq(); paintEq(); saveSoon();
}

function saveCurrentEq() {
  if (activeCustom()) return toast(`«${activeCustom().name}» ya guarda cada cambio que haces.`);
  let slot = P.custom.find(c => sameBands(c.bands, FLAT));
  if (!slot && P.custom.length < MAX_CUSTOM) {
    slot = { id: "c" + Date.now().toString(36), name: "Personalizado " + (P.custom.length + 1), bands: [...FLAT] };
    P.custom.push(slot);
  }
  if (!slot) return toast("Ya tienes 8 ecualizadores. Elige uno y ajústalo, o borra alguno.", true);
  slot.bands = [...P.eq.bands]; P.eq.preset = slot.id;
  paintEq(); saveSoon();
  toast(`Guardado en «${slot.name}». Pulsa el lápiz para cambiarle el nombre.`);
}

function startRename(id) {
  const slot = P.custom.find(c => c.id === id);
  const row = $$("[data-slot]").find(r => r.dataset.slot === id);
  if (!slot || !row) return;
  const label = $(".slot-name", row);
  const input = document.createElement("input");
  input.type = "text"; input.value = slot.name; input.maxLength = 24; input.className = "slot-input"; input.setAttribute("aria-label", "Nombre del ecualizador");
  label.replaceWith(input);
  input.focus(); input.select();
  let done = false;
  const finish = save => {
    if (done) return;
    done = true;
    if (save && input.value.trim()) slot.name = input.value.trim();
    paintEq(); saveSoon();
  };
  input.onkeydown = ev => { if (ev.key === "Enter") finish(true); else if (ev.key === "Escape") finish(false); ev.stopPropagation(); };
  input.onblur = () => finish(true);
}

function deleteSlot(id) {
  if (P.custom.length <= MIN_CUSTOM) {
    const slot = P.custom.find(c => c.id === id);
    if (slot) { slot.bands = [...FLAT]; if (P.eq.preset === id) { P.eq.bands = [...FLAT]; applyEq(); } }
  } else {
    P.custom = P.custom.filter(c => c.id !== id);
    if (P.eq.preset === id) P.eq.preset = "manual";
  }
  paintEq(); saveSoon();
}

function paintEq(fromSlider = false) {
  $("#eq-on").checked = P.eq.on;
  $("#pl-eq-panel").classList.toggle("off", !P.eq.on);
  $("#pl-eq").classList.toggle("active", P.eq.on && !sameBands(P.eq.bands, FLAT));
  $$("#eq-bands input").forEach((input, i) => {
    if (!fromSlider) input.value = String(P.eq.bands[i]);
    input.style.setProperty("--p", ((+input.value + EQ_RANGE) / (EQ_RANGE * 2) * 100) + "%");
    const v = P.eq.bands[i];
    $(`[data-out="${i}"]`).textContent = (v > 0 ? "+" : "") + (Number.isInteger(v) ? v : v.toFixed(1));
  });
  if (fromSlider && $("#eq-presets").dataset.shown === P.eq.preset) return;
  $("#eq-presets").dataset.shown = P.eq.preset;
  $("#eq-presets").innerHTML = EQ_PRESETS.map(p => `<button type="button" class="chip-btn${P.eq.preset === p.id ? " on" : ""}" data-preset="${esc(p.id)}">${esc(p.name)}</button>`).join("")
    + (P.eq.preset === "manual" ? '<span class="chip-btn on static">Ajuste manual</span>' : "");
  $("#eq-custom").innerHTML = P.custom.map(c => {
    const empty = sameBands(c.bands, FLAT);
    return `<div class="slot${P.eq.preset === c.id ? " on" : ""}" data-slot="${esc(c.id)}" role="button" tabindex="0">
      <span class="slot-name">${esc(c.name)}</span><span class="muted small">${empty ? "vacío" : "guardado"}</span>
      <button class="icon-btn" type="button" data-rename="${esc(c.id)}" aria-label="Cambiar el nombre" title="Cambiar el nombre"><svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4"/></svg></button>
      <button class="icon-btn" type="button" data-del="${esc(c.id)}" aria-label="${P.custom.length > MIN_CUSTOM ? "Borrar" : "Vaciar"}" title="${P.custom.length > MIN_CUSTOM ? "Borrar" : "Vaciar"}"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>`;
  }).join("");
}

function paintCrossfade() {
  $("#xf").value = String(P.xf);
  $("#xf").style.setProperty("--p", (P.xf / 12 * 100) + "%");
  $("#xf-out").textContent = P.xf ? P.xf + " s" : "Apagado";
}

/* ---------- remembering ---------- */
function snapshot() {
  const el = P.decks.length ? deck().el : null;
  return {
    volume: P.volume, muted: P.muted, xf: P.xf, shuffle: P.shuffle, repeat: P.repeat, pulse: P.pulseOn, tab: L.tab,
    eq: { on: P.eq.on, bands: P.eq.bands, preset: P.eq.preset },
    custom: P.custom.map(c => ({ id: c.id, name: c.name, bands: c.bands })),
    queue: P.queue.slice(0, MAX_SAVED_QUEUE), pos: P.pos, track: P.queue[P.pos] || "", recent: P.recent,
    time: el && isFinite(el.currentTime) ? Math.floor(el.currentTime) : 0,
  };
}

function saveSoon(now = false) {
  clearTimeout(P.saveTimer);
  P.saveTimer = setTimeout(() => { P.lastSaved = Date.now(); call("save_player", snapshot()); }, now ? 50 : 600);
}

function restore(saved) {
  if (!saved || typeof saved !== "object") return;
  const num = (v, lo, hi, d) => typeof v === "number" && isFinite(v) ? clamp(v, lo, hi) : d;
  P.volume = num(saved.volume, 0, 1, .8); P.muted = !!saved.muted; P.xf = Math.round(num(saved.xf, 0, 12, 0));
  P.shuffle = !!saved.shuffle; P.repeat = ["off", "all", "one"].includes(saved.repeat) ? saved.repeat : "off";
  // on unless it was turned off (older saves kept a mode: "off" was off, the other modes — pulse among them — become the pulse)
  P.pulseOn = typeof saved.pulse === "boolean" ? saved.pulse : saved.viz !== "off";
  if (Array.isArray(saved.recent)) P.recent = saved.recent.filter(id => typeof id === "string").slice(0, MAX_RECENT);
  if (TABS.some(([id]) => id === saved.tab)) L.tab = saved.tab;      // the section of the library you were in
  const bands = b => Array.isArray(b) && b.length === 10 && b.every(v => typeof v === "number") ? b.map(v => clamp(v, -EQ_RANGE, EQ_RANGE)) : null;
  if (saved.eq && typeof saved.eq === "object") {
    P.eq.on = saved.eq.on !== false; P.eq.bands = bands(saved.eq.bands) || [...FLAT];
    P.eq.preset = typeof saved.eq.preset === "string" ? saved.eq.preset : "manual";
  }
  if (Array.isArray(saved.custom)) {
    const slots = saved.custom.filter(c => c && typeof c.id === "string" && /^[\w-]{1,20}$/.test(c.id) && bands(c.bands)).slice(0, MAX_CUSTOM)
      .map(c => ({ id: c.id, name: String(c.name || "").slice(0, 24) || "Personalizado", bands: bands(c.bands) }));
    if (slots.length >= MIN_CUSTOM) P.custom = slots;
  }
  if (P.eq.preset !== "manual" && ![...EQ_PRESETS, ...P.custom].some(p => p.id === P.eq.preset)) P.eq.preset = "manual";
}

function restoreQueue(saved) {
  if (!saved || !Array.isArray(saved.queue)) return;
  const ids = saved.queue.filter(id => typeof id === "string" && trackOf(id));
  if (!ids.length || !trackOf(saved.track)) return;
  P.queue = ids; P.pos = Math.max(0, ids.indexOf(saved.track));
  P.original = null;
  cueTrack(current(), typeof saved.time === "number" ? saved.time : 0);
  trackChanged();
}

/* ---------- library ---------- */
const durationText = secs => {
  const h = Math.floor(secs / 3600), m = Math.floor(secs % 3600 / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
};

/* The songs the list shows: those of the tab (or of the open album or playlist, crate.js), filtered by the search. An album or a
   playlist keeps its own order; the other lists follow the sort chosen. */
function visibleTracks() {
  const q = P.q.trim().toLocaleLowerCase();
  const base = baseTracks();
  const list = q ? base.filter(t => `${t.title} ${t.artist} ${t.album}`.toLocaleLowerCase().includes(q)) : [...base];
  if (L.open) return list;
  const by = {
    artist: (a, b) => (!a.artist - !b.artist) || a.artist.localeCompare(b.artist) || a.title.localeCompare(b.title),   // songs without artist go last
    title: (a, b) => a.title.localeCompare(b.title),
    recent: (a, b) => b.added - a.added,
  }[P.sort];
  return list.sort(by);
}

const ICON_NEXT = '<svg viewBox="0 0 24 24"><path d="M4 6h11M4 12h6M4 18h6"/><path d="M14 11.5v9l7-4.5z" class="fill"/></svg>';
const ICON_HEART = '<svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>';
const ICON_TAG ='<svg viewBox="0 0 24 24"><path d="M3 12V4h8l9 9-8 8z"/><circle cx="7.5" cy="8.5" r="1"/></svg>';
const ICON_ADD = '<svg viewBox="0 0 24 24"><path d="M4 6h12M4 12h12M4 18h6M18 14v6M15 17h6"/></svg>';

function renderSongList() {
  const list = visibleTracks(), box = $("#lib-list"), empty = $("#lib-empty");
  $$("#lib-play-all, #lib-shuffle").forEach(b => b.disabled = !list.length);
  empty.classList.toggle("hidden", !!list.length);
  if (!list.length) {
    box.innerHTML = "";
    const none = !baseTracks().length;
    const emptyOwn = L.open && (L.byKey.get(L.open) || {}).mine;       // a playlist of yours with nothing in it yet
    empty.innerHTML = emptyOwn
      ? `<div class="panel-ic">${ICON_PLAYLIST}</div><div class="panel-body"><h3>Esta playlist está vacía</h3><p class="muted">Añade canciones desde el menú «⋯» de cualquier canción de tu biblioteca: elige «Añadir a playlist».</p></div>`
      : none
      ? `<div class="panel-ic">${ICONS.search}</div><div class="panel-body"><h3>${L.tab === "likes" ? "Todavía no te gusta ninguna canción" : "Aún no hay canciones en tu biblioteca"}</h3><p class="muted">${L.tab === "likes" ? "Dale al corazón de una canción y aparece aquí; las que bajaste como «Me gusta» de Spotify ya están." : "Aquí aparece todo lo que descargues en tu carpeta de descargas, listo para escuchar."}</p><div class="btn-row"><button class="btn primary" id="lib-go-home" type="button">Descargar canciones</button></div></div>`
      : `<div class="panel-ic">${ICONS.search}</div><div class="panel-body"><h3>Nada coincide con «${esc(P.q)}»</h3><p class="muted">Prueba con otra parte del título, el artista o el álbum.</p></div>`;
    const go = $("#lib-go-home"); if (go) go.onclick = () => show("home");
    return;
  }
  const playing = current() && current().id;
  box.innerHTML = list.map((t, i) => `<div class="lib-row${t.id === playing ? " playing" : ""}" role="listitem" tabindex="0" data-id="${esc(t.id)}" style="--i:${i}">
    <span class="lib-n">${i + 1}</span>
    <span class="lib-cover${t.cover_url ? "" : " ph"}" style="--h:${hueOf(t)}"><span class="initial">${esc((t.title || "♪").trim().charAt(0).toUpperCase())}</span>${coverHTML(t)}<i class="q-eq" aria-hidden="true"><b></b><b></b><b></b></i></span>
    <span class="lib-t"><b>${esc(t.title)}${t.complete ? "" : '<i class="lib-flag" title="Le faltan etiquetas o la portada" aria-label="Etiquetas incompletas"></i>'}</b><span class="muted small">${esc(t.artist || "Artista desconocido")}</span></span>
    <span class="lib-album muted">${esc(t.album)}</span>
    <span class="lib-act"><button type="button" class="icon-btn" data-act="next" title="Reproducir a continuación" aria-label="Reproducir a continuación">${ICON_NEXT}</button>
      <button type="button" class="icon-btn" data-act="add" title="Añadir a la cola" aria-label="Añadir a la cola">${ICON_ADD}</button>
      <button type="button" class="icon-btn" data-act="tags" title="Completar etiquetas de esta canción" aria-label="Completar etiquetas de esta canción">${ICON_TAG}</button>
      <button type="button" class="icon-btn" data-act="more" title="Más opciones" aria-label="Más opciones" aria-haspopup="menu">${ICON_MORE}</button></span>
    <button type="button" class="icon-btn heart${L.liked.has(t.id) ? " on" : ""}" data-act="like" aria-pressed="${L.liked.has(t.id)}" title="${L.liked.has(t.id) ? "Quitar de Me gusta" : "Me gusta"}" aria-label="Me gusta">${ICON_HEART}</button>
    <span class="lib-dur muted">${t.duration ? fmt(t.duration) : "—"}</span></div>`).join("");
}

/* Hands songs of the library to "Completar etiquetas" (tags.js). Writing tags replaces the file, which Windows refuses while
   it is being read, so a song that is loaded in the player is unloaded first; play brings it back where it was. */
function releaseFile(ids) {
  const track = current();
  if (!track || !ids.includes(track.id) || !P.decks.length || !deck().el.getAttribute("src")) return;
  P.resume = deck().el.currentTime;
  deck().el.pause();
  deck().el.removeAttribute("src");
  deck().el.load();
  render();
}

async function sendToTags(ids) {
  releaseFile(ids);
  const paths = await call("library_paths", ids);
  if (!Array.isArray(paths) || !paths.length) return toast("No encontré ese archivo en tu carpeta de descargas.", true);
  addPaths(paths);
}

function paintLibraryMarks() {
  const id = current() && current().id;
  $$("#lib-list .lib-row").forEach(r => r.classList.toggle("playing", r.dataset.id === id));
  $("#app").classList.toggle("audio-on", isPlaying());
}

async function loadLibrary() {
  const r = await call("library_list");
  if (r.error) return false;
  P.tracks = r.tracks || [];
  P.byId = new Map(P.tracks.map(t => [t.id, t]));
  P.tracks.forEach(t => P.seen.set(t.id, t));   // a song that plays keeps its bar even if the next scan no longer lists it
  await loadCollections();
  return true;
}

async function openLibrary() {
  if (await loadLibrary()) renderLibrary();
}

/* ---------- the small menu of a song, the confirmation dialog, and deleting ---------- */
const ICON_MORE = '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="19" cy="12" r="1.4"/></svg>';
const ICON_PLAYLIST = '<svg viewBox="0 0 24 24"><path d="M4 6h12M4 12h12M4 18h7M18 14v6M15 17h6"/></svg>';
const ICON_MINUS = '<svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg>';
const ICON_TRASH ='<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>';

function closeMenu() { const menu = $("#ctx"); if (menu) menu.remove(); }

/* A menu of actions at a point of the window: items are { label, icon, danger, run } or { sep: true }. */
function openMenu(x, y, items) {
  closeMenu();
  const menu = document.createElement("div");
  menu.id = "ctx"; menu.className = "ctx"; menu.setAttribute("role", "menu");
  menu.innerHTML = items.map((it, i) => it.sep ? '<i class="ctx-sep"></i>'
    : `<button type="button" role="menuitem" class="ctx-item${it.danger ? " danger" : ""}" data-i="${i}">${it.icon || ""}<span>${esc(it.label)}</span></button>`).join("");
  document.body.append(menu);
  const box = menu.getBoundingClientRect();
  menu.style.left = Math.max(8, Math.min(x, innerWidth - box.width - 8)) + "px";
  menu.style.top = Math.max(8, Math.min(y, innerHeight - box.height - 8)) + "px";
  menu.addEventListener("click", ev => { const b = ev.target.closest(".ctx-item"); if (b) { closeMenu(); items[+b.dataset.i].run(); } });
  menu.addEventListener("keydown", ev => {
    const all = $$(".ctx-item", menu), at = all.indexOf(document.activeElement);
    if (ev.key === "ArrowDown") all[(at + 1) % all.length].focus();
    else if (ev.key === "ArrowUp") all[(at - 1 + all.length) % all.length].focus();
    else if (ev.key === "Escape" || ev.key === "Tab") closeMenu();
    else return;
    ev.preventDefault(); ev.stopPropagation();
  });
  $(".ctx-item", menu).focus();
}
document.addEventListener("click", ev => { if (!ev.target.closest("#ctx") && !ev.target.closest('[data-act="more"]')) closeMenu(); });
addEventListener("resize", closeMenu);
document.addEventListener("scroll", closeMenu, true);

/* What a song can be done from its menu: add it to a playlist of yours (a second menu, with «Nueva playlist…»), take it out of
   the playlist whose page is open, delete it. */
function openSongMenu(x, y, ids) {
  const mine = L.open && (L.byKey.get(L.open) || {}).mine ? L.byKey.get(L.open) : null;
  // On a phone the row's own buttons (next, add, tags) are hidden: everything goes through this menu, so everything is here too
  const items = ids.length === 1
    ? [{ label: "Reproducir a continuación", icon: ICON_NEXT, run: () => enqueue(ids[0], true) }, { label: "Añadir a la cola", icon: ICON_ADD, run: () => enqueue(ids[0], false) },
       { label: "Completar etiquetas…", icon: ICON_TAG, run: () => sendToTags(ids) }, { sep: true }]
    : [{ label: "Añadir a la cola", icon: ICON_ADD, run: () => ids.forEach(id => enqueue(id, false)) }, { sep: true }];
  items.push({ label: "Añadir a playlist…", icon: ICON_PLAYLIST, run: () => openPlaylistMenu(x, y, ids) });
  if (mine) items.push({ label: `Quitar de «${mine.title}»`, icon: ICON_MINUS, run: () => removeFromPlaylist(mine.pid, ids) });
  items.push({ sep: true }, { label: ids.length > 1 ? `Eliminar ${ids.length} canciones…` : "Eliminar de la biblioteca…", icon: ICON_TRASH, danger: true, run: () => deleteTracks(ids) });
  openMenu(x, y, items);
}

/* Resolves true or false: the window's own question box (the system's would look out of place). Escape or a click outside says no.
   With `input` ({ value }) it asks for a text instead: it resolves the text typed, or null when cancelled. */
function confirmDialog({ title, text = "", ok, danger = false, input = null }) {
  if (!$("#dialog").classList.contains("hidden")) return Promise.resolve(input ? null : false);      // one question at a time (a double click)
  return new Promise(resolve => {
    const box = $("#dialog"), yes = $("#dialog-yes"), no = $("#dialog-no"), field = $("#dialog-input");
    $("#dialog-title").textContent = title; $("#dialog-text").textContent = text;
    $("#dialog-text").classList.toggle("hidden", !text);
    yes.textContent = ok; yes.classList.toggle("danger", danger);
    field.classList.toggle("hidden", !input);
    if (input) field.value = input.value || "";
    box.classList.remove("hidden");
    const done = answer => {
      box.classList.add("hidden");
      yes.onclick = no.onclick = box.onclick = field.onkeydown = null;
      document.removeEventListener("keydown", onKey, true);
      resolve(input ? (answer ? field.value.trim() : null) : answer);
    };
    const onKey = ev => { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); done(false); } };
    document.addEventListener("keydown", onKey, true);
    yes.onclick = () => done(true); no.onclick = () => done(false);
    field.onkeydown = ev => { if (ev.key === "Enter") { ev.preventDefault(); done(true); } };
    box.onclick = ev => { if (ev.target === box) done(false); };
    if (input) { field.focus(); field.select(); } else no.focus();        // the safe answer has the focus
  });
}

/* Songs leave the queue first (the player lets go of their files), then they go to the Recycle Bin. A file that is still being
   read by the audio element is refused by Windows, so a refusal is tried once more a moment later. */
async function deleteTracks(ids) {
  const tracks = ids.map(trackOf).filter(Boolean);
  if (!tracks.length) return;
  const one = tracks.length === 1;
  // the same song can be kept as another file (in an album and in liked/): only the one chosen goes, and the user is told
  const copies = one ? P.tracks.filter(o => o.id !== tracks[0].id && songKey(o) === songKey(tracks[0]) && tracks[0].artist) : [];
  const copyNote = copies.length ? ` Tiene ${copies.length === 1 ? "otra copia" : copies.length + " copias más"} en tu biblioteca (${[...new Set(copies.map(c => c.group || { liked: "Me gusta", track: "Canciones sueltas" }[c.kind] || "otra carpeta"))].join(", ")}) que no se borra${copies.length === 1 ? "" : "n"}.` : "";
  const ok = await confirmDialog({
    title: one ? "¿Eliminar esta canción?" : `¿Eliminar ${tracks.length} canciones?`,
    text: onAndroid()
      ? (one ? `«${tracks[0].title}»${tracks[0].artist ? " de " + tracks[0].artist : ""} se quita de la biblioteca de este teléfono.${copyNote}` : "Se quitan de la biblioteca de este teléfono.")
      : (one ? `«${tracks[0].title}»${tracks[0].artist ? " de " + tracks[0].artist : ""} se manda a la Papelera de Reciclaje: puedes recuperarla desde allí.${copyNote}`
             : "Se mandan a la Papelera de Reciclaje: puedes recuperarlas desde allí."),
    ok: onAndroid() ? "Eliminar" : "Mandar a la Papelera", danger: true,
  });
  if (!ok) return;
  for (let i = P.queue.length - 1; i >= 0; i--) if (ids.includes(P.queue[i])) removeFromQueue(i);
  releaseFile(ids);
  await wait(700);
  let result = await call("library_delete", ids);
  if (result && result.failed && result.failed.length) {
    await wait(900);
    const again = await call("library_delete", result.failed.map(f => f.id));
    result = { deleted: result.deleted + (again.deleted || 0), failed: again.failed || [] };
  }
  await openLibrary();
  if (!result || result.error) return toast("No pude eliminar la canción.", true);
  if (result.failed.length) toast(`${result.failed[0].error}${result.failed.length > 1 ? ` (y ${result.failed.length - 1} más)` : ""}`, true);
  if (result.deleted) toast(result.deleted === 1 ? "Canción enviada a la Papelera." : `${result.deleted} canciones enviadas a la Papelera.`);
}

function wireLibrary() {
  const list = $("#lib-list");
  const play = id => playList(visibleTracks().map(t => t.id), id);
  list.addEventListener("click", ev => {
    const row = ev.target.closest(".lib-row");
    if (!row) return;
    const act = ev.target.closest("[data-act]");
    if (act && act.dataset.act === "tags") return sendToTags([row.dataset.id]);
    if (act && act.dataset.act === "like") return toggleLike(row.dataset.id, act);
    if (act && act.dataset.act === "more") { const r = act.getBoundingClientRect(); return openSongMenu(r.left, r.bottom + 4, [row.dataset.id]); }
    if (act) return enqueue(row.dataset.id, act.dataset.act === "next", $(".lib-cover", row));
    play(row.dataset.id);
  });
  list.addEventListener("contextmenu", ev => {
    const row = ev.target.closest(".lib-row");
    if (row) { ev.preventDefault(); openSongMenu(ev.clientX, ev.clientY, [row.dataset.id]); }
  });
  list.addEventListener("keydown", ev => {
    const row = ev.target.closest(".lib-row");
    if (row && ev.target === row && ev.key === "Enter") play(row.dataset.id);
  });
  $("#lib-play-all").onclick = () => { const ids = visibleTracks().map(t => t.id); playList(ids, P.shuffle ? ids[Math.floor(Math.random() * ids.length)] : ids[0]); };
  $("#lib-shuffle").onclick = () => { P.shuffle = true; const ids = visibleTracks().map(t => t.id); playList(ids, ids[Math.floor(Math.random() * ids.length)]); render(); };
  let timer = 0;
  $("#lib-q").oninput = ev => { clearTimeout(timer); timer = setTimeout(() => { P.q = ev.target.value; renderLibrary(); }, 120); };
  $("#lib-folder").onclick = async () => { if (!(await call("open_folder"))) toast("No pude abrir la carpeta de descargas.", true); };
  dropdown($("#lib-sort"));
  $("#lib-sort").onchange = ev => { P.sort = ev.target.value; renderLibrary(); };
}

/* A <select> opens the system's list (white, out of tune with the window): this one keeps the real select hidden and
   draws a button and a list of its own that follow the window's look. The select still holds the value and fires `change`. */
function dropdown(select) {
  const box = document.createElement("div");
  box.className = "dd";
  box.innerHTML = `<button type="button" class="dd-btn" aria-haspopup="listbox" aria-expanded="false"><span></span><svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg></button>
    <div class="dd-list hidden" role="listbox"></div>`;
  select.hidden = true;
  select.after(box);
  const btn = $(".dd-btn", box), list = $(".dd-list", box);
  const label = () => { $("span", btn).textContent = select.options[select.selectedIndex].textContent; };
  const close = () => { list.classList.add("hidden"); btn.setAttribute("aria-expanded", "false"); };
  const open = () => {
    list.innerHTML = [...select.options].map(o => `<button type="button" role="option" class="dd-opt" data-v="${esc(o.value)}" aria-selected="${o.value === select.value}">
      <svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>${esc(o.textContent)}</button>`).join("");
    list.classList.remove("hidden"); btn.setAttribute("aria-expanded", "true");
    ($('[aria-selected="true"]', list) || $(".dd-opt", list)).focus();
  };
  btn.onclick = ev => { ev.stopPropagation(); list.classList.contains("hidden") ? open() : close(); };
  list.onclick = ev => {
    const opt = ev.target.closest(".dd-opt");
    if (!opt) return;
    select.value = opt.dataset.v; label(); close(); btn.focus();
    select.dispatchEvent(new Event("change", { bubbles: true }));
  };
  list.onkeydown = ev => {
    const opts = $$(".dd-opt", list), at = opts.indexOf(document.activeElement);
    if (ev.key === "ArrowDown") opts[(at + 1) % opts.length].focus();
    else if (ev.key === "ArrowUp") opts[(at - 1 + opts.length) % opts.length].focus();
    else if (ev.key === "Escape") { close(); btn.focus(); }
    else if (ev.key === "Tab") close();
    else return;
    ev.preventDefault(); ev.stopPropagation();
  };
  document.addEventListener("click", ev => { if (!box.contains(ev.target)) close(); });
  label();
}

/* ---------- keys ---------- */
function wireKeys() {
  document.addEventListener("keydown", ev => {
    if (ev.ctrlKey || ev.metaKey || ev.altKey || !current() || !$("#dialog").classList.contains("hidden")) return;
    const t = ev.target;
    if (t.closest && t.closest("input:not([type=range]), textarea, select, [contenteditable]")) return;
    const onRange = t.type === "range";
    switch (ev.key) {
      case " ": if (t.closest && t.closest("button, a")) return; ev.preventDefault(); toggle(); break;
      case "ArrowRight": if (onRange) return; ev.preventDefault(); ev.shiftKey ? advance(false) : seek(deck().el.currentTime + 5); break;
      case "ArrowLeft": if (onRange) return; ev.preventDefault(); ev.shiftKey ? previous() : seek(deck().el.currentTime - 5); break;
      case "ArrowUp": if (onRange) return; ev.preventDefault(); setVolume(P.volume + .05); break;
      case "ArrowDown": if (onRange) return; ev.preventDefault(); setVolume(P.volume - .05); break;
      case "m": case "M": P.muted = !P.muted; applyVolume(); paintVolume(); saveSoon(); break;
      case "Escape": closePanels(); break;
    }
  });
  if ("mediaSession" in navigator) {
    const set = (name, fn) => { try { navigator.mediaSession.setActionHandler(name, fn); } catch (e) { /* not supported */ } };
    set("play", () => { if (!isPlaying()) toggle(); }); set("pause", () => { if (isPlaying()) toggle(); });
    set("stop", () => { if (isPlaying()) toggle(); }); set("previoustrack", previous); set("nexttrack", () => advance(false));
    set("seekto", d => seek(d.seekTime));
  }
}

/* ---------- start ---------- */
function wireBar() {
  $("#pl-play").onclick = toggle;
  $("#pl-like").onclick = () => { const t = current(); if (t) toggleLike(t.id, $("#pl-like")); };
  $("#pl-next").onclick = () => advance(false);
  $("#pl-prev").onclick = previous;
  $("#pl-shuffle").onclick = () => setShuffle(!P.shuffle);
  $("#pl-repeat").onclick = cycleRepeat;
  $("#pl-queue").onclick = ev => { ev.stopPropagation(); togglePanel("queue"); };
  $("#pl-eq").onclick = ev => { ev.stopPropagation(); togglePanel("eq"); };
  $("#pl-mute").onclick = () => { P.muted = !P.muted; applyVolume(); paintVolume(); saveSoon(); };
  $("#pl-volume").oninput = ev => setVolume(+ev.target.value);
  const bar = $("#pl-progress");
  bar.addEventListener("input", () => { P.dragging = true; paint(); });   // the thumb is the user's until they let go
  bar.addEventListener("change", () => { P.dragging = false; seek(+bar.value); });
  $("#xf").oninput = ev => { P.xf = +ev.target.value; paintCrossfade(); saveSoon(); };
  $("#viz-on").onchange = ev => setPulse(ev.target.checked);
  document.addEventListener("click", ev => {
    // the path is taken at the click: a button the panel redraws is already out of the page when this runs
    const inside = ev.composedPath().some(n => n.classList && (n.classList.contains("pl-panel") || n.id === "pl-queue" || n.id === "pl-eq"));
    if (!inside) closePanels();
  });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && isPlaying()) loopSpectrum(); });
  addEventListener("pagehide", () => { call("save_player", snapshot()); });
}

const Player = {
  async init() {
    if (P.wired) return;
    P.wired = true;
    restore(await call("get_player"));
    buildEq(); paintEq(); paintCrossfade(); paintVolume();
    wireBar(); wireQueue(); wireLibrary(); wireCrate(); wireLyrics(); wireSleep(); wireStats(); wireKeys();
    setPulse(P.pulseOn);
    setArm(ARM.rest, 0, true);        // nothing loaded yet: the needle rests clear of the record
    P.timer = setInterval(tick, TICK);
    if (await loadLibrary()) restoreQueue(await call("get_player"));
    P.ready = true;
  },
  open: openLibrary,
  refresh: loadLibrary,            // for the picker of "Completar etiquetas"
  tracks: () => P.tracks,
  release: releaseFile,
};

/* A browser with ?demo has no program side: short generated tones stand in for the songs. */
function demoPlayerApi(art) {
  const demoPlays = [], demoOffsets = {}, demoScales = {}, demoVersions = {};
  const tone = (notes, seconds) => {
    const rate = 22050, n = rate * seconds, data = new DataView(new ArrayBuffer(44 + n * 2));
    const text = (o, s) => [...s].forEach((c, i) => data.setUint8(o + i, c.charCodeAt(0)));
    text(0, "RIFF"); data.setUint32(4, 36 + n * 2, true); text(8, "WAVEfmt "); data.setUint32(16, 16, true); data.setUint16(20, 1, true);
    data.setUint16(22, 1, true); data.setUint32(24, rate, true); data.setUint32(28, rate * 2, true); data.setUint16(32, 2, true); data.setUint16(34, 16, true);
    text(36, "data"); data.setUint32(40, n * 2, true);
    for (let i = 0; i < n; i++) {
      const t = i / rate, note = notes[Math.floor(t * 2) % notes.length], env = Math.min(1, t * 20, (seconds - t) * 20);
      const v = (Math.sin(2 * Math.PI * note * t) * .5 + Math.sin(2 * Math.PI * note * 2 * t) * .2 + Math.sin(2 * Math.PI * note / 2 * t) * .25) * env * .5;
      data.setInt16(44 + i * 2, v * 32767, true);
    }
    return URL.createObjectURL(new Blob([data], { type: "audio/wav" }));
  };
  const scales = [[220, 277, 330, 277], [196, 247, 294, 247], [262, 330, 392, 330], [174, 220, 262, 220], [233, 294, 349, 294], [247, 311, 370, 311]];
  const albums = [["After Hours", "The Weeknd"], ["MICRODOSIS", "Mora"], ["Starboy", "The Weeknd"], ["Cabernet", "Mora"], ["Hunting High and Low", "a-ha"],
    ["Back In Black", "AC/DC"], ["Slippery When Wet", "Bon Jovi"], ["The Wall", "Pink Floyd"], ["RADIO VENEZUELA", "Chino & Nacho"], ["Dream On", "Aerosmith"],
    ["Paranoid", "Black Sabbath"], ["Pa' Mi Gente", "Varios artistas"]];
  const playlists = [["Rock", ["Thunderstruck", "Crazy", "Paranoid", "Hells Bells", "Highway to Hell", "Livin' On A Prayer"]],
    ["Para correr", ["Blinding Lights", "Take On Me", "Eye of the Tiger", "Stronger", "Levitating"]], ["Noche", ["Volando", "Cabernet", "Sin Miedo", "Luna"]]];
  const cover = seed => art(`hsl(${seed * 47 % 360} 55% 36%)`, `hsl(${(seed * 47 + 55) % 360} 65% 60%)`);
  let tracks = null, saved = {}, likes = null;
  const mine = [];                                                       // the user's playlists, in memory
  const mySmart = [];                                                    // …and the smart ones
  let madeLists = 0;
  const collections = async () => {                                      // what the program side answers: liked ids (copies of a liked song count) and playlists
    if (!tracks) tracks = makeTracks();
    if (!likes) likes = new Set(tracks.filter(t => t.kind === "liked").map(t => t.id));
    const identity = t => `${t.artist}|${t.title}`;
    const known = new Set([...likes].map(id => tracks.find(t => t.id === id)).filter(Boolean).map(identity));
    const text = (t, r) => { const h = String(t[r.field] || "").toLowerCase(), w = String(r.value).toLowerCase(); return r.op === "is" ? h === w : r.op === "not_contains" ? !h.includes(w) : h.includes(w); };
    const pick = d => { const rs = d.rules.filter(r => ["artist", "album", "title"].includes(r.field)); return tracks.filter(t => !rs.length || (d.match === "all" ? rs.every(r => text(t, r)) : rs.some(r => text(t, r)))).slice(0, d.limit || 999).map(t => t.id); };
    const builtin = [{ id: "recent", name: "Recién añadidas", match: "all", rules: [{ field: "added_days", op: "lt", value: 30 }], sort: "recent", limit: 50, builtin: true, ids: tracks.slice(0, 9).map(t => t.id) },
      { id: "top", name: "Más escuchadas", match: "all", rules: [{ field: "plays", op: "gt", value: 0 }], sort: "plays", limit: 50, builtin: true, ids: tracks.slice(10, 22).map(t => t.id) },
      { id: "forgotten", name: "Olvidadas", match: "all", rules: [{ field: "added_days", op: "gt", value: 30 }, { field: "last_played_days", op: "gt", value: 90 }], sort: "oldest", limit: 50, builtin: true, ids: tracks.slice(30, 33).map(t => t.id) }];
    return { liked: tracks.filter(t => likes.has(t.id) || known.has(identity(t))).map(t => t.id), playlists: mine.map(p => ({ ...p, ids: [...p.ids] })),
      smart: [...builtin, ...mySmart.map(d => ({ ...d, builtin: false, ids: pick(d) }))] };
  };
  const tones = [], toneFor = i => tones[i] || (tones[i] = tone(scales[i], 24));      // six sounds shared by all the demo songs
  const makeTracks = () => {
    const list = []; let n = 0;
    const add = (title, artist, album, kind, group, number, seed) => {
      list.push({ id: "demo" + n, title, artist, album, duration: 24, cover: true, complete: n % 3 !== 0, number, disc: 1, kind, group,
        added: 5000 - n, url: toneFor(n % 6), cover_url: cover(seed) });
      n++;
    };
    albums.forEach(([album, artist], a) => [1, 2, 3].forEach(k => add(`${album} · pista ${k}`, artist, album, "album", album, k, a + 1)));
    playlists.forEach(([name, songs], p) => songs.forEach((title, k) => add(title, "Varios artistas", "", "playlist", name, k + 1, 20 + p * 5 + k)));
    ["Blinding Lights", "Save Your Tears", "Volando", "Mala Mía", "Sin Miedo"].forEach((title, k) => add(k < 2 ? `After Hours · pista ${k + 1}` : title, k < 2 ? "The Weeknd" : "Mora", "", "liked", "", 0, 40 + k));
    ["Starboy", "Sin título"].forEach((title, k) => add(title, k ? "" : "The Weeknd", "", "track", "", 0, 50 + k));
    return list;
  };
  return {
    library_list: async () => {
      if (!tracks) tracks = makeTracks();
      return { tracks };
    },
    library_delete: async ids => {
      const gone = (tracks || []).filter(t => ids.includes(t.id));
      tracks = (tracks || []).filter(t => !ids.includes(t.id));
      likes.forEach(id => { if (ids.includes(id)) likes.delete(id); });
      mine.forEach(p => { p.ids = p.ids.filter(id => !ids.includes(id)); });
      return { ok: true, deleted: gone.length, failed: [] };
    },
    stats_play: async (id, seconds) => { demoPlays.push({ id, seconds }); return { ok: true }; },
    stats_summary: async period => {
      const n = { week: 7, month: 30, year: 12, all: 12 }[period] || 12, days = period === "week" || period === "month";
      const labels = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"], months = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
      const series = Array.from({ length: n }, (_, i) => ({ date: String(i), label: days ? (period === "week" ? labels[i % 7] : String(i + 1)) : months[i % 12], minutes: Math.round((Math.sin(i * 1.7) + 1.2) * 40 * (days ? 1 : 6)) / 1 }));
      const some = (tracks || []).slice(0, 10).map((t, i) => ({ id: t.id, title: t.title, artist: t.artist, album: t.album, plays: 40 - i * 3 + demoPlays.length, seconds: (40 - i * 3) * 190 }));
      const artists = [...new Set(some.map(s => s.artist))].map((a, i) => ({ artist: a, plays: 90 - i * 11, seconds: (90 - i * 11) * 190 }));
      const albums = [...new Set(some.map(s => s.album))].slice(0, 6).map((a, i) => ({ album: a, artist: (some.find(s => s.album === a) || {}).artist, plays: 60 - i * 7, seconds: (60 - i * 7) * 190 }));
      return { period, plays: 214, seconds: 214 * 190, songs: some, artists, albums, series, streak: 5 };
    },
    share_make: async (ids, name, by) => (ids.length && name ? { ok: true, qr: true, tone: "#2f6fe0", dark: "#0b1a45", light: "#eef2fd", qr_uri: "data:image/svg+xml;utf8," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 33 33" shape-rendering="crispEdges"><rect width="33" height="33" fill="#eef2fd"/>' + Array.from({ length: 33 * 33 }, (_, i) => { const x = i % 33, y = Math.floor(i / 33), edge = (x < 11 && y < 11) || (x > 21 && y < 11) || (x < 11 && y > 21); return (edge ? (x % 10 === 4 || y % 10 === 4 || x % 10 < 2 || y % 10 < 2) : ((x * 7 + y * 13 + x * y) % 5 < 2)) ? `<rect x="${x}" y="${y}" width="1" height="1" fill="#0b1a45"/>` : ""; }).join("") + "</svg>"), code: "BURDAMIX1:eJxdjMEKgzAQRH9F9tJL0jQxTSJC8Q8KwWyMSEXEoCj-e2dvPQjDMDPvg8AagyBqPoGv3tL7W0WYgGAXuPLYrt5XRCuoo9S0CNN3aeHs1_oKCwCWwPEgQmaDSQ-bzO0Y3Jkb0yMLPJJvV4qnnYgPoM_OyrLcz-YoL2qa0g1Hdkkd1JHNCm5cYwpU1-XL8vPnu8-vDz-FX0Y", count: ids.length, qr: true } : { ok: false, error: "Ponle un nombre a la playlist antes de compartirla." }),
    share_read: async text => (String(text).includes("BURDAMIX1:") ? { ok: true, name: "Para el gimnasio", by: "Ana", total: 8, ids: (tracks || []).slice(0, 5).map(t => t.id), missing: [["Drake", "One Dance"], ["Dua Lipa", "Levitating"], ["Feid", "Normal"]] } : { ok: false, error: "Eso no parece un código de Burdamix. Empieza por «BURDAMIX1:»." }),
    share_read_picture: async () => ({ ok: false, error: "Esa imagen no es una tarjeta de Burdamix." }),
    share_read_file: async () => ({ ok: false, cancelled: true }),
    share_card_file: async () => ({ ok: true, path: "/cache/share/Noche.png" }),
    share_card_save: async () => ({ ok: true, path: "C:\Users\demo\tarjeta.png" }),
    playlist_export_m3u: async () => ({ ok: true, path: "C:\Users\demo\lista.m3u8" }),
    smart_save: async (def, id) => {
      if (!def.name) return { ok: false, error: "Ponle un nombre de hasta 80 letras." };
      if (id) { const at = mySmart.findIndex(s => s.id === id); mySmart[at] = { ...def, id }; return { ok: true, id }; }
      const made = "s" + (mySmart.length + 1); mySmart.push({ ...def, id: made }); return { ok: true, id: made };
    },
    smart_delete: async id => { const at = mySmart.findIndex(s => s.id === id); if (at < 0) return { ok: false, error: "Esa playlist inteligente no existe." }; mySmart.splice(at, 1); return { ok: true }; },
    lyrics_get: async id => {
      const n = [...String(id)].reduce((a, c) => a + c.charCodeAt(0), 0) % 3;
      if (n === 1) return { ok: false, none: true, error: "No encontré la letra de esta canción." };
      const words = ["Bajo las luces de la ciudad", "el tiempo se detiene un momento", "y tu voz me lleva lejos", "más allá del último tren", "", "dime si todavía me esperas", "que yo vuelvo a casa esta noche", "con el corazón en la mano"];
      if (n === 2) return { ok: true, synced: [], plain: words.join("\n"), manual: false };
      return { ok: true, synced: words.map((l, i) => [i * 3, l]), plain: words.join("\n"), manual: false, offset: demoOffsets[id] || 0, scale: demoScales[id] || 1, version: demoVersions[id] || 0, versions: 2, label: "Demo · 0:24" };
    },
    lyrics_sync: async (id, offset, scale) => { demoOffsets[id] = Math.round(offset * 4) / 4; demoScales[id] = Math.round(scale * 10000) / 10000; return { ok: true, offset: demoOffsets[id], scale: demoScales[id] }; },
    lyrics_version: async (id, index) => { demoVersions[id] = index; return { ok: true, synced: [[0, "Otra versión"], [4, "de la misma letra"], [9, "con otros tiempos"]], plain: "x", manual: false, offset: demoOffsets[id] || 0, scale: demoScales[id] || 1, version: index, versions: 2, label: "Demo 2 · 0:24" }; },
    lyrics_offset: async (id, seconds) => { demoOffsets[id] = Math.max(-30, Math.min(30, seconds)); return { ok: true, offset: demoOffsets[id] }; },
    lyrics_save: async (id, text) => (text.trim() ? { ok: true, synced: [], plain: text, manual: true } : { ok: false, none: true, error: "No encontré la letra de esta canción." }),
    collections_get: collections,
    like_toggle: async id => {
      const t = (tracks || []).find(x => x.id === id);
      if (!t) return { ok: false, error: "Esa canción ya no está en la biblioteca." };
      if ((await collections()).liked.includes(id)) { tracks.filter(x => `${x.artist}|${x.title}` === `${t.artist}|${t.title}`).forEach(x => likes.delete(x.id)); return { ok: true, liked: false }; }
      likes.add(id); return { ok: true, liked: true };
    },
    playlist_create: async (name, ids) => {
      name = String(name || "").trim().replace(/\s+/g, " ");
      if (!name) return { ok: false, error: "Ponle un nombre a la playlist." };
      const id = "mine" + (++madeLists); mine.push({ id, name, ids: (ids || []).filter((x, i, a) => a.indexOf(x) === i) });
      return { ok: true, id };
    },
    playlist_rename: async (pid, name) => { const p = mine.find(x => x.id === pid); name = String(name || "").trim(); if (!p || !name) return { ok: false, error: "Ponle un nombre a la playlist." }; p.name = name; return { ok: true }; },
    playlist_delete: async pid => { const at = mine.findIndex(x => x.id === pid); if (at >= 0) mine.splice(at, 1); return { ok: true }; },
    playlist_add: async (pid, ids) => { const p = mine.find(x => x.id === pid); if (!p) return { ok: false, error: "Esa playlist ya no existe." }; ids.forEach(i => { if (!p.ids.includes(i)) p.ids.push(i); }); return { ok: true }; },
    playlist_remove: async (pid, id) => { const p = mine.find(x => x.id === pid); if (p) p.ids = p.ids.filter(i => i !== id); return { ok: true }; },
    library_paths: async ids => ids.map(id => tracks && tracks.find(t => t.id === id)).filter(Boolean).map(t => `C:/Música/${t.artist ? t.artist + " - " : ""}${t.title}.mp3`),
    get_player: async () => saved,
    save_player: async data => { saved = JSON.parse(JSON.stringify(data)); return { ok: true }; },
  };
}
