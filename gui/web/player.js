"use strict";
/* Player: the library view, the bar that stays at the bottom, the queue.
   Uses the helpers of app.js ($, $$, esc, fmt, call, toast, show); the program side is Api.library_list / get_player / save_player.
   Audio graph: two decks (so that two songs can overlap) -> analyser -> volume -> speakers. */

const MAX_SAVED_QUEUE = 2000;
const QUICK_FADE = .35;     // seconds: when the user skips by hand
const TICK = 150;

const P = {
  tracks: [], byId: new Map(), queue: [], original: null, pos: -1,
  shuffle: false, repeat: "off", volume: .8, muted: false,
  seen: new Map(), q: "", sort: "artist", ready: false, dragging: false, errors: 0,
  ctx: null, decks: [], active: 0, analyser: null, master: null,
  fading: null, timer: 0, saveTimer: 0, lastSaved: 0, wired: false,
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
  P.analyser = P.ctx.createAnalyser(); P.analyser.fftSize = 128; P.analyser.smoothingTimeConstant = .8;
  P.master = P.ctx.createGain();
  P.decks = [0, 1].map(() => {
    const el = new Audio();
    el.crossOrigin = "anonymous"; el.preload = "auto";
    const gain = P.ctx.createGain();
    P.ctx.createMediaElementSource(el).connect(gain);
    gain.connect(P.analyser);
    const d = { el, gain };
    el.addEventListener("ended", () => { if (d === deck()) advance(true); });
    el.addEventListener("error", () => { if (d === deck() && el.getAttribute("src")) onBroken(); });
    el.addEventListener("play", () => { if (d === deck()) render(); });
    el.addEventListener("playing", () => { if (d === deck()) P.errors = 0; });   // a song that plays ends the run of broken ones
    el.addEventListener("pause", () => { if (d === deck()) { render(); saveSoon(); } });
    return d;
  });
  P.decks[1].gain.gain.value = 0;
  [P.analyser, P.master].reduce((a, b) => (a.connect(b), b));
  P.master.connect(P.ctx.destination);
  applyVolume();
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
  goTo(next, auto ? 0 : QUICK_FADE);
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
  if (deck().el.paused) { P.ctx.resume().catch(() => {}); deck().el.play().catch(onPlayRefused); }
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

function enqueue(id, asNext) {
  if (!trackOf(id)) return;
  if (!P.queue.length) return playList([id], id);
  P.original = null;
  P.queue.splice(asNext ? P.pos + 1 : P.queue.length, 0, id);
  toast(asNext ? "Sonará a continuación." : "Añadida a la cola.");
  renderQueue(); saveSoon();
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
function coverHTML(track) {
  return track.cover_url ? `<img src="${esc(track.cover_url)}" alt="" loading="lazy" decoding="async">` : "";
}

function trackChanged() {
  const track = current();
  paintCover(track);
  render();
  paintLibraryMarks();
  renderQueue();
  setMediaSession(track);
  saveSoon(true);
}

function render() {
  const track = current(), playing = isPlaying();
  $("#player").classList.toggle("hidden", !track);
  $("#app").classList.toggle("has-player", !!track);
  document.body.classList.toggle("has-player", !!track);   // the toasts rise above the bar
  $("#player").classList.toggle("is-playing", playing);
  if (!track) return;
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
}

function paintCover(track) {
  const img = $("#pl-cover");
  $("#pl-initial").textContent = track ? (track.title || "♪").trim().charAt(0).toUpperCase() : "♪";
  if (track && track.cover_url) { img.src = track.cover_url; img.hidden = false; }
  else { img.hidden = true; img.removeAttribute("src"); }
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

/* ---------- panels ---------- */
function togglePanel(which) {
  const panels = { queue: ["#pl-queue-panel", "#pl-queue"] };
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
      <span class="q-cover"><span class="initial">${esc((t.title || "♪").trim().charAt(0).toUpperCase())}</span>${coverHTML(t)}<i class="q-eq" aria-hidden="true"><b></b><b></b><b></b></i></span>
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

/* ---------- remembering ---------- */
function snapshot() {
  const el = P.decks.length ? deck().el : null;
  return {
    volume: P.volume, muted: P.muted, shuffle: P.shuffle, repeat: P.repeat,
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
  P.volume = num(saved.volume, 0, 1, .8); P.muted = !!saved.muted;
  P.shuffle = !!saved.shuffle; P.repeat = ["off", "all", "one"].includes(saved.repeat) ? saved.repeat : "off";
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

const ICON_NEXT = '<svg viewBox="0 0 24 24"><path d="M5 6h11M5 12h11M5 18h6M18 14v6M15 17h6"/></svg>';
const ICON_ADD = '<svg viewBox="0 0 24 24"><path d="M4 6h12M4 12h12M4 18h6M18 14v6M15 17h6"/></svg>';

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
  box.innerHTML = list.map((t, i) => `<div class="lib-row${t.id === playing ? " playing" : ""}" role="listitem" tabindex="0" data-id="${esc(t.id)}">
    <span class="lib-n">${i + 1}</span>
    <span class="lib-cover"><span class="initial">${esc((t.title || "♪").trim().charAt(0).toUpperCase())}</span>${coverHTML(t)}<i class="q-eq" aria-hidden="true"><b></b><b></b><b></b></i></span>
    <span class="lib-t"><b>${esc(t.title)}</b><span class="muted small">${esc(t.artist || "Artista desconocido")}</span></span>
    <span class="lib-album muted">${esc(t.album)}</span>
    <span class="lib-act"><button type="button" class="icon-btn" data-act="next" title="Reproducir a continuación" aria-label="Reproducir a continuación">${ICON_NEXT}</button>
      <button type="button" class="icon-btn" data-act="add" title="Añadir a la cola" aria-label="Añadir a la cola">${ICON_ADD}</button></span>
    <span class="lib-dur muted">${t.duration ? fmt(t.duration) : "—"}</span></div>`).join("");
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
    if (act) return enqueue(row.dataset.id, act.dataset.act === "next");
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
  $("#lib-sort").onchange = ev => { P.sort = ev.target.value; renderLibrary(); };
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
  $("#pl-mute").onclick = () => { P.muted = !P.muted; applyVolume(); paintVolume(); saveSoon(); };
  $("#pl-volume").oninput = ev => setVolume(+ev.target.value);
  const bar = $("#pl-progress");
  bar.addEventListener("input", () => { P.dragging = true; paint(); });   // the thumb is the user's until they let go
  bar.addEventListener("change", () => { P.dragging = false; seek(+bar.value); });
  document.addEventListener("click", ev => {
    // the path is taken at the click: a button the panel redraws is already out of the page when this runs
    const inside = ev.composedPath().some(n => n.classList && (n.classList.contains("pl-panel") || n.id === "pl-queue"));
    if (!inside) closePanels();
  });
  addEventListener("pagehide", () => { call("save_player", snapshot()); });
}

const Player = {
  async init() {
    if (P.wired) return;
    P.wired = true;
    restore(await call("get_player"));
    paintVolume();
    wireBar(); wireQueue(); wireLibrary(); wireKeys();
    P.timer = setInterval(tick, TICK);
    if (await loadLibrary()) restoreQueue(await call("get_player"));
    P.ready = true;
  },
  open: openLibrary,
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
        id: "demo" + i, title, artist, album, duration: 24, cover: i < 5, added: 1000 - i,
        url: tone(scales[i], 24), cover_url: i < 5 ? art(...colors[i]) : "",
      }));
      return { tracks };
    },
    get_player: async () => saved,
    save_player: async data => { saved = JSON.parse(JSON.stringify(data)); return { ok: true }; },
  };
}
