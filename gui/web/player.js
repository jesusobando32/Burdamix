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

const P = {
  tracks: [], byId: new Map(), queue: [], original: null, pos: -1,
  shuffle: false, repeat: "off", volume: .8, muted: false, xf: 0,
  eq: { on: true, bands: [...FLAT], preset: "flat" },
  custom: [1, 2, 3].map(n => ({ id: "c" + n, name: "Personalizado " + n, bands: [...FLAT] })),
  seen: new Map(), q: "", sort: "artist", viz: "off", discId: "", swapToken: 0, armAngle: null, armLifted: true, armBusy: false, ready: false, dragging: false, errors: 0,
  ctx: null, decks: [], active: 0, pre: null, filters: [], analyser: null, master: null,
  fading: null, timer: 0, saveTimer: 0, lastSaved: 0, accent: "", bars: 0, wired: false,
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
    el.addEventListener("ended", () => { if (d === deck()) advance(true); });
    el.addEventListener("error", () => { if (d === deck() && el.getAttribute("src")) onBroken(); });
    el.addEventListener("play", () => { if (d === deck()) render(); });
    el.addEventListener("playing", () => { if (d === deck()) P.errors = 0; });   // a song that plays ends the run of broken ones
    el.addEventListener("pause", () => { if (d === deck()) { render(); saveSoon(); } });
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
  if (P.master) P.master.gain.value = P.muted ? 0 : P.volume * P.volume;
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

function trackChanged() {
  const track = current();
  if (!track) extractAccent({});
  paintCover(track);
  render();
  paintLibraryMarks();
  renderQueue();
  setMediaSession(track);
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
    artwork: track.cover_url ? [{ src: track.cover_url, sizes: "320x320", type: "image/jpeg" }] : [],
  });
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
      const c = document.createElement("canvas"); c.width = c.height = 12;
      const x = c.getContext("2d", { willReadFrequently: true });
      x.drawImage(img, 0, 0, 12, 12);
      const d = x.getImageData(0, 0, 12, 12).data;
      let r = 0, g = 0, b = 0, w = 0;
      for (let i = 0; i < d.length; i += 4) {
        const max = Math.max(d[i], d[i + 1], d[i + 2]), min = Math.min(d[i], d[i + 1], d[i + 2]);
        const weight = 0.05 + (max - min) / 255;
        r += d[i] * weight; g += d[i + 1] * weight; b += d[i + 2] * weight; w += weight;
      }
      apply(tonesOf(r / w, g / w, b / w));
    } catch (e) { apply(null); }
  };
  img.onerror = () => apply(null);
  img.src = track.cover_url;
}

/* A cover's average can be muddy or nearly black: bring it to a colour that reads on the dark bar. The three blobs of the
   background take neighbouring hues, so the whole window changes with the song and not just one corner. */
function tonesOf(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
  let h = 0;
  if (d) h = max === r ? ((g - b) / d) % 6 : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  h = Math.round(((h * 60) + 360) % 360);
  const s = clamp(d ? d / (1 - Math.abs(max + min - 1)) : 0, .45, .85) * 100;
  const hsl = (hue, light) => `hsl(${(hue + 360) % 360} ${Math.round(s)}% ${light}%)`;
  return { accent: hsl(h, 62), b1: hsl(h, 52), b2: hsl(h + 55, 56), b3: hsl(h - 50, 58) };
}

/* ---------- spectrum ---------- */
/* The bars grow from the middle line up and down. Each one eases towards its level (quickly up, slowly down), so a pause
   lets them sink to a flat line instead of vanishing; the loop stops by itself once they are flat. */
const VIZ_MODES = ["off", "wave", "center", "pulse"];
const sizes = new WeakMap();   // canvas -> the css size it was last fitted to

/* Fits a canvas to the pixels it really covers (css size x screen density, or a fraction of it for the blurred ones), so
   the bars stay sharp on any window size and screen. */
function fitCanvas(canvas, scale = 1) {
  const w = Math.max(1, Math.round(canvas.clientWidth * scale)), h = Math.max(1, Math.round(canvas.clientHeight * scale));
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  return [w, h];
}

function withAlpha(color, alpha) {
  if (color.startsWith("hsl")) return color.replace(/\)$/, ` / ${alpha})`);
  const n = parseInt(color.slice(1), 16);
  return `rgba(${n >> 16}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
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

/* The big, blurred layers behind the window (blur and opacity come from the css of each mode). */
function drawBig(data, live) {
  const canvas = $("#viz"), mode = P.viz;
  if (mode === "wave" || mode === "center") {
    const [w, h] = fitCanvas(canvas, .35);
    const n = clamp(Math.round(w / 9), 24, 80), slot = w / n;
    const { lv, moving } = easeLevels(viz.store, "big", n, data, live);
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, w, h);
    const color = P.accent || DEFAULT_ACCENT;
    const fill = ctx.createLinearGradient(0, mode === "wave" ? h : 0, 0, mode === "wave" ? 0 : h);
    if (mode === "wave") { fill.addColorStop(0, withAlpha(color, .95)); fill.addColorStop(1, withAlpha(color, 0)); }
    else { fill.addColorStop(0, withAlpha(color, 0)); fill.addColorStop(.5, withAlpha(color, .95)); fill.addColorStop(1, withAlpha(color, 0)); }
    ctx.fillStyle = fill;
    for (let i = 0; i < n; i++) {
      const bar = Math.max(h * .02, lv[i] * h * (mode === "wave" ? .75 : .55));
      if (mode === "wave") ctx.fillRect(i * slot, h - bar, slot - 1, bar);
      else ctx.fillRect(i * slot, (h - bar) / 2, slot - 1, bar);
    }
    return moving;
  }
  if (mode === "pulse") return drawPulse(data, live);
  return false;
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
    const small = drawSmall(data, live), big = drawBig(data, live);
    if (live || small || big) P.bars = requestAnimationFrame(draw);
  };
  P.bars = requestAnimationFrame(draw);
}

function setViz(mode) {
  P.viz = VIZ_MODES.includes(mode) ? mode : "off";
  $("#app").dataset.viz = P.viz;
  const canvas = $("#viz");
  canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height);
  $$(".bg i:not(.glow)").forEach(blob => { blob.style.scale = ""; blob.style.translate = ""; });
  viz.store.big = null; viz.spring = null;
  $$("#viz-chips [data-viz]").forEach(b => b.classList.toggle("on", b.dataset.viz === P.viz));
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
    volume: P.volume, muted: P.muted, xf: P.xf, shuffle: P.shuffle, repeat: P.repeat, viz: P.viz,
    eq: { on: P.eq.on, bands: P.eq.bands, preset: P.eq.preset },
    custom: P.custom.map(c => ({ id: c.id, name: c.name, bands: c.bands })),
    queue: P.queue.slice(0, MAX_SAVED_QUEUE), pos: P.pos, track: P.queue[P.pos] || "",
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
  P.viz = VIZ_MODES.includes(saved.viz) ? saved.viz : "off";
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

function visibleTracks() {
  const q = P.q.trim().toLocaleLowerCase();
  const list = q ? P.tracks.filter(t => `${t.title} ${t.artist} ${t.album}`.toLocaleLowerCase().includes(q)) : [...P.tracks];
  const by = {
    artist: (a, b) => (!a.artist - !b.artist) || a.artist.localeCompare(b.artist) || a.title.localeCompare(b.title),   // songs without artist go last
    title: (a, b) => a.title.localeCompare(b.title),
    recent: (a, b) => b.added - a.added,
  }[P.sort];
  return list.sort(by);
}

const ICON_NEXT = '<svg viewBox="0 0 24 24"><path d="M4 6h11M4 12h6M4 18h6"/><path d="M14 11.5v9l7-4.5z" class="fill"/></svg>';
const ICON_TAG = '<svg viewBox="0 0 24 24"><path d="M3 12V4h8l9 9-8 8z"/><circle cx="7.5" cy="8.5" r="1"/></svg>';
const ICON_ADD ='<svg viewBox="0 0 24 24"><path d="M4 6h12M4 12h12M4 18h6M18 14v6M15 17h6"/></svg>';

function renderLibrary() {
  const list = visibleTracks(), box = $("#lib-list"), empty = $("#lib-empty");
  const total = P.tracks.reduce((s, t) => s + t.duration, 0);
  $("#lib-count").textContent = P.tracks.length
    ? `${plural(P.tracks.length, "canción", "canciones")}${total ? " · " + durationText(total) : ""}${P.q && list.length !== P.tracks.length ? ` · ${list.length} coinciden` : ""}`
    : "";
  $$("#lib-play-all, #lib-shuffle").forEach(b => b.disabled = !list.length);
  empty.classList.toggle("hidden", !!list.length);
  if (!list.length) {
    box.innerHTML = "";
    empty.innerHTML = P.tracks.length
      ? `<div class="panel-ic">${ICONS.search}</div><div class="panel-body"><h3>Nada coincide con «${esc(P.q)}»</h3><p class="muted">Prueba con otra parte del título, el artista o el álbum.</p></div>`
      : `<div class="panel-ic">${ICONS.search}</div><div class="panel-body"><h3>Aún no hay canciones en tu biblioteca</h3><p class="muted">Aquí aparece todo lo que descargues en tu carpeta de descargas, listo para escuchar.</p><div class="btn-row"><button class="btn primary" id="lib-go-home" type="button">Descargar canciones</button></div></div>`;
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
      <button type="button" class="icon-btn" data-act="tags" title="Completar etiquetas de esta canción" aria-label="Completar etiquetas de esta canción">${ICON_TAG}</button></span>
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
  return true;
}

async function openLibrary() {
  if (await loadLibrary()) renderLibrary();
}

function wireLibrary() {
  const list = $("#lib-list");
  const play = id => playList(visibleTracks().map(t => t.id), id);
  list.addEventListener("click", ev => {
    const row = ev.target.closest(".lib-row");
    if (!row) return;
    const act = ev.target.closest("[data-act]");
    if (act && act.dataset.act === "tags") return sendToTags([row.dataset.id]);
    if (act) return enqueue(row.dataset.id, act.dataset.act === "next", $(".lib-cover", row));
    play(row.dataset.id);
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
    if (ev.ctrlKey || ev.metaKey || ev.altKey || !current()) return;
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
    set("play", toggle); set("pause", toggle); set("previoustrack", previous); set("nexttrack", () => advance(false));
    set("seekto", d => seek(d.seekTime));
  }
}

/* ---------- start ---------- */
function wireBar() {
  $("#pl-play").onclick = toggle;
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
  $("#viz-chips").addEventListener("click", ev => { const b = ev.target.closest("[data-viz]"); if (b) setViz(b.dataset.viz); });
  // the big layer ends where the bar begins, whatever height the bar has in a narrow window
  new ResizeObserver(() => $("#main").style.setProperty("--ph", $("#player").offsetHeight + "px")).observe($("#player"));
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
    wireBar(); wireQueue(); wireLibrary(); wireKeys();
    setViz(P.viz);
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
  const names = [["Blinding Lights", "The Weeknd", "After Hours"], ["Save Your Tears", "The Weeknd", "After Hours"], ["Volando", "Mora", "MICRODOSIS"],
    ["Starboy", "The Weeknd", "Starboy"], ["Cabernet", "Mora", "Cabernet"], ["Sin título.mp3", "", ""]];
  const colors = [["#7b2d26", "#f0a500"], ["#134e5e", "#71b280"], ["#3a1c71", "#d76d77"], ["#1f4037", "#99f2c8"], ["#42275a", "#734b6d"], ["#333", "#666"]];
  const scales = [[220, 277, 330, 277], [196, 247, 294, 247], [262, 330, 392, 330], [174, 220, 262, 220], [233, 294, 349, 294], [247, 311, 370, 311]];
  let tracks = null, saved = {};
  return {
    library_list: async () => {
      if (!tracks) tracks = names.map(([title, artist, album], i) => ({
        id: "demo" + i, title, artist, album, duration: 24, cover: i < 5, complete: i % 2 === 0, added: 1000 - i,
        url: tone(scales[i], 24), cover_url: i < 5 ? art(...colors[i]) : "",
      }));
      return { tracks };
    },
    library_paths: async ids => ids.map(id => tracks && tracks.find(t => t.id === id)).filter(Boolean).map(t => `C:/Música/${t.artist ? t.artist + " - " : ""}${t.title}.mp3`),
    get_player: async () => saved,
    save_player: async data => { saved = JSON.parse(JSON.stringify(data)); return { ok: true }; },
  };
}
