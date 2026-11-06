"use strict";
/* The library as collections: albums and playlists as record sleeves in a crate you flip through, the songs you like, and every
   song. A collection is only a way of looking at the same files: nothing is moved or copied.
   Uses player.js (P, trackOf, playList, renderSongList, ...) and the helpers of app.js ($, $$, esc, fmt, plural, call, toast, placeInd). */

const L = { tab: "albums", open: null, groups: { albums: [], playlists: [] }, byKey: new Map(), focus: "", moved: false,
  liked: new Set(), mine: [] };            // the ids of the songs you like; your own playlists ({ id, name, ids })
const TABS = [["albums", "Álbumes"], ["playlists", "Playlists"], ["likes", "Me gusta"], ["songs", "Canciones"]];
const CRATE_TABS = ["albums", "playlists"];

const norm = text => String(text || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
const songKeys = new WeakMap();                                                  // normalizing is slow: a song's key is worked out once
const songKey = track => songKeys.get(track) || (songKeys.set(track, norm(track.artist) + "|" + norm(track.title)), songKeys.get(track));   // the same song kept as two files has one key

/* The most repeated value, if at least `share` of the values agree on it. */
function mostCommon(values, share) {
  const counts = new Map();
  values.forEach(v => { if (v) counts.set(v, (counts.get(v) || 0) + 1); });
  let best = "", most = 0;
  counts.forEach((n, v) => { if (n > most) { best = v; most = n; } });
  return most / (values.length || 1) >= share ? best : "";
}

/* `order`: an album goes by disc and track number; a playlist downloaded from Spotify by the order it was downloaded in; one of
   your own keeps the order you put its songs in. */
function makeGroup(kind, name, tracks, order = "tracks", extra = {}) {
  if (order === "tracks") tracks.sort((a, b) => (a.disc || 1) - (b.disc || 1) || (a.number || 999) - (b.number || 999) || a.title.localeCompare(b.title));
  else if (order === "added") tracks.sort((a, b) => a.added - b.added);
  return {
    ...extra, key: (extra.mine ? "mine" : kind) + ":" + (extra.pid || name), kind, name, tracks, ids: tracks.map(t => t.id), count: tracks.length,
    seconds: tracks.reduce((s, t) => s + (t.duration || 0), 0),
    title: kind === "album" ? mostCommon(tracks.map(t => t.album), .5) || name : name,                  // the album's own name when the songs agree on it
    artist: kind === "album" ? mostCommon(tracks.map(t => t.artist), .6) || "Varios artistas" : "",
    cover: tracks.find(t => t.cover_url) || tracks[0], mosaic: tracks.slice(0, 4),
  };
}

function buildGroups() {
  const albums = new Map(), lists = new Map();
  for (const t of P.tracks) {
    const bucket = t.kind === "album" ? albums : t.kind === "playlist" ? lists : null;
    if (bucket && t.group) (bucket.get(t.group) || bucket.set(t.group, []).get(t.group)).push(t);
  }
  const mine = L.mine.map(p => makeGroup("playlist", p.name, p.ids.map(id => P.byId.get(id)).filter(Boolean), "keep", { mine: true, pid: p.id }));
  L.groups = {
    albums: [...albums].map(([name, tracks]) => makeGroup("album", name, tracks)).sort((a, b) => a.artist.localeCompare(b.artist) || a.title.localeCompare(b.title)),
    playlists: [...mine, ...[...lists].map(([name, tracks]) => makeGroup("playlist", name, tracks, "added")).sort((a, b) => a.title.localeCompare(b.title))],   // yours first
  };
  L.byKey = new Map([...L.groups.albums, ...L.groups.playlists].map(g => [g.key, g]));
  if (L.open && !L.byKey.has(L.open)) L.open = null;
}

/* Songs the user likes (the program side decides: hearts given, the liked/ folder, and every copy of a liked song). One row per
   song even if it exists as several files. */
const isLiked = track => L.liked.has(track.id);
const KIND_RANK = { album: 0, playlist: 1, track: 2, liked: 3, other: 4 };
let likedMemo = null;                                    // { tracks, liked, result }: the same answer while neither list has been replaced
function likedTracks() {
  if (likedMemo && likedMemo.tracks === P.tracks && likedMemo.liked === L.liked) return likedMemo.result;
  const best = new Map();
  for (const t of P.tracks) {
    if (!isLiked(t)) continue;
    const key = songKey(t), kept = best.get(key);
    if (!kept || KIND_RANK[t.kind] < KIND_RANK[kept.kind]) best.set(key, t);
  }
  likedMemo = { tracks: P.tracks, liked: L.liked, result: [...best.values()] };
  return likedMemo.result;
}

/* The songs the list below the tabs shows (before the search): those of the open album or playlist, the liked ones, or all. */
function baseTracks() {
  if (L.open) return (L.byKey.get(L.open) || { tracks: [] }).tracks;
  return L.tab === "likes" ? likedTracks() : P.tracks;
}

const inCrate = () => CRATE_TABS.includes(L.tab) && !L.open;

/* ---------- covers ---------- */
function sleeveArt(track) {
  if (!track) return '<span class="cover-ph ph" style="--h:200"><span class="initial">♪</span></span>';
  return track.cover_url ? `<img src="${esc(track.cover_url)}" alt="" loading="lazy" decoding="async">`
    : `<span class="cover-ph ph" style="--h:${hueOf(track)}"><span class="initial">${esc((track.title || "♪").trim().charAt(0).toUpperCase())}</span></span>`;
}

/* A playlist's cover: its first four songs' covers together. */
function mosaicArt(group) {
  const tile = i => group.mosaic[i] ? sleeveArt(group.mosaic[i]) : '<span class="cover-ph ph" style="--h:120"></span>';
  return `<span class="mosaic">${[0, 1, 2, 3].map(tile).join("")}</span>`;
}

const groupArt = g => g.kind === "playlist" ? mosaicArt(g) : sleeveArt(g.cover);
const labelStyle = g => g.cover && g.cover.cover_url ? ` style="--cover:url('${esc(g.cover.cover_url)}')"` : "";
const groupSub = g => g.kind === "album" ? `${g.artist} · ${plural(g.count, "canción", "canciones")}` : plural(g.count, "canción", "canciones");

/* ---------- tabs ---------- */
function tabCount(tab) {
  return tab === "albums" ? L.groups.albums.length : tab === "playlists" ? L.groups.playlists.length : tab === "likes" ? likedTracks().length : P.tracks.length;
}

function renderTabs() {
  const bar = $("#lib-tabs");
  bar.querySelectorAll("button").forEach(b => b.remove());
  TABS.forEach(([id, label]) => {
    const b = document.createElement("button");
    b.type = "button"; b.dataset.tab = id; b.setAttribute("role", "tab"); b.setAttribute("aria-selected", id === L.tab);
    b.classList.toggle("on", id === L.tab);
    b.innerHTML = `${label}<span class="tab-n">${tabCount(id)}</span>`;
    bar.append(b);
  });
  requestAnimationFrame(() => placeInd($("#tab-ind"), $(".on", bar), false));
}

function showTab(tab) {
  L.tab = tab; L.open = null;
  P.q = ""; $("#lib-q").value = "";
  renderLibrary();
  saveSoon();
}

/* ---------- the whole view ---------- */
function renderLibrary() {
  buildGroups();
  renderTabs();
  const crate = inCrate(), detail = !!L.open;
  $("#crate-box").classList.toggle("hidden", !crate);
  $("#lib-detail").classList.toggle("hidden", !detail);
  $("#lib-list").classList.toggle("hidden", crate);
  $$("#lib-play-all, #lib-shuffle").forEach(b => b.classList.toggle("hidden", crate || detail));
  $(".dd", $(".lib-tools")).classList.toggle("hidden", crate || detail);       // the sort only orders lists of songs
  $("#lib-q").placeholder = crate ? (L.tab === "albums" ? "Buscar álbumes" : "Buscar playlists") : "Buscar canciones";
  if (crate) { $("#lib-empty").classList.add("hidden"); renderCrate(); }
  else if (detail) { renderDetail(); renderSongList(); }
  else renderSongList();
  paintCount();
}

function paintCount() {
  const text = $("#lib-count");
  if (L.open) { const g = L.byKey.get(L.open); text.textContent = g ? `${plural(g.count, "canción", "canciones")}${g.seconds ? " · " + durationText(g.seconds) : ""}` : ""; return; }
  if (inCrate()) { const n = visibleGroups().length; text.textContent = n ? plural(n, L.tab === "albums" ? "álbum" : "playlist", L.tab === "albums" ? "álbumes" : "playlists") : ""; return; }
  const all = baseTracks(), shown = visibleTracks(), total = all.reduce((s, t) => s + (t.duration || 0), 0);
  text.textContent = all.length ? `${plural(all.length, "canción", "canciones")}${total ? " · " + durationText(total) : ""}${P.q && shown.length !== all.length ? ` · ${shown.length} coinciden` : ""}` : "";
}

/* ---------- the crate ---------- */
function visibleGroups() {
  const q = norm(P.q);
  return (L.groups[L.tab] || []).filter(g => !q || norm(`${g.title} ${g.artist} ${g.name}`).includes(q));
}

function renderCrate() {
  const crate = $("#crate"), list = visibleGroups(), empty = $("#lib-empty");
  const addTile = L.tab === "playlists" && !P.q.trim();         // the first sleeve of the playlists makes a new one
  empty.classList.toggle("hidden", !!list.length || addTile);
  $("#crate-box").classList.toggle("hidden", !list.length && !addTile);
  if (!list.length && !addTile) {
    crate.innerHTML = "";
    const none = !(L.groups[L.tab] || []).length;
    empty.innerHTML = `<div class="panel-ic">${ICONS.search}</div><div class="panel-body"><h3>${none ? (L.tab === "albums" ? "Todavía no tienes álbumes" : "Todavía no tienes playlists") : `Nada coincide con «${esc(P.q)}»`}</h3>
      <p class="muted">${none ? (L.tab === "albums" ? "Los álbumes que descargues aparecen aquí como discos, con su portada." : "Las playlists que descargues aparecen aquí, con las portadas de sus primeras canciones.") : "Prueba con otro nombre."}</p>
      ${none ? '<div class="btn-row"><button class="btn primary" id="lib-go-home" type="button">Descargar canciones</button></div>' : ""}</div>`;
    const go = $("#lib-go-home"); if (go) go.onclick = () => show("home");
    return;
  }
  const playing = current() && current().id;
  const newTile = addTile ? `<button type="button" class="crate-item new" role="option" data-key="new" title="Crear una playlist">
      <span class="sleeve"><span class="new-art"><svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg></span></span><b>Nueva playlist</b><span class="muted small">Con las canciones que quieras</span></button>` : "";
  crate.innerHTML = newTile + list.map(g => `<button type="button" class="crate-item${g.ids.includes(playing) ? " playing" : ""}" role="option" data-key="${esc(g.key)}" title="${esc(g.title)}">
      <span class="sleeve"${labelStyle(g)}>${DISC}${groupArt(g)}</span><b>${esc(g.title)}</b><span class="muted small">${esc(groupSub(g))}</span></button>`).join("");
  const target = L.focus && $$(".crate-item", crate).find(el => el.dataset.key === L.focus);
  crate.scrollLeft = target ? target.offsetLeft + target.offsetWidth / 2 - crate.clientWidth / 2 : 0;
  layoutCrate();
}

/* Each sleeve leans and sinks according to how far it is from the middle of the crate, like records seen from above in a box;
   the one in the middle stands up and its record slides out a little. The numbers go to css variables, the css does the drawing. */
let crateFrame = 0;
function layoutCrate() {
  cancelAnimationFrame(crateFrame);
  crateFrame = requestAnimationFrame(() => {
    const crate = $("#crate");
    if (!crate || !crate.clientWidth) return;
    const middle = crate.scrollLeft + crate.clientWidth / 2;
    let nearest = null, nearestGap = Infinity;
    for (const el of crate.children) {
      const d = (el.offsetLeft + el.offsetWidth / 2 - middle) / (el.offsetWidth * .7), gap = Math.abs(d);      // in steps from one sleeve to the next
      el.style.setProperty("--d", clamp(d, -2.4, 2.4).toFixed(3));
      el.style.setProperty("--a", Math.min(gap, 3).toFixed(3));
      el.style.zIndex = String(100 - Math.round(Math.min(gap, 9) * 10));
      if (gap < nearestGap) { nearestGap = gap; nearest = el; }
    }
    for (const el of crate.children) el.classList.toggle("focus", el === nearest);
    if (nearest) L.focus = nearest.dataset.key;
  });
}

function crateStep(by) {
  const crate = $("#crate"), items = [...crate.children], at = items.findIndex(el => el.dataset.key === L.focus);
  const next = items[clamp((at < 0 ? 0 : at) + by, 0, items.length - 1)];
  if (next) crate.scrollTo({ left: next.offsetLeft + next.offsetWidth / 2 - crate.clientWidth / 2, behavior: "smooth" });
}

function wireCrate() {
  const crate = $("#crate");
  crate.addEventListener("scroll", layoutCrate, { passive: true });
  addEventListener("resize", layoutCrate);
  // the wheel turns the page of the records, not the page of the window
  crate.addEventListener("wheel", ev => {
    if (Math.abs(ev.deltaY) <= Math.abs(ev.deltaX)) return;
    ev.preventDefault();
    crate.scrollLeft += ev.deltaY * .9;
  }, { passive: false });
  crate.addEventListener("keydown", ev => {
    if (ev.key === "ArrowRight") { ev.preventDefault(); crateStep(1); }
    else if (ev.key === "ArrowLeft") { ev.preventDefault(); crateStep(-1); }
    else if (ev.key === "Home") { ev.preventDefault(); crateStep(-1e6); }
    else if (ev.key === "End") { ev.preventDefault(); crateStep(1e6); }
    else if (ev.key === "Enter" && L.focus) { ev.preventDefault(); openGroup(L.focus); }
  });
  // dragging with the mouse; a drag is not a click
  let down = null;
  crate.addEventListener("pointerdown", ev => { if (ev.pointerType === "mouse" && ev.button === 0) { down = { x: ev.clientX, left: crate.scrollLeft }; L.moved = false; } });
  crate.addEventListener("pointermove", ev => {
    if (!down) return;
    const dx = ev.clientX - down.x;
    if (Math.abs(dx) > 6) { L.moved = true; crate.classList.add("dragging"); }
    if (L.moved) crate.scrollLeft = down.left - dx;
  });
  const end = () => { down = null; crate.classList.remove("dragging"); };
  addEventListener("pointerup", end); crate.addEventListener("pointerleave", end);
  crate.addEventListener("click", ev => {
    const item = ev.target.closest(".crate-item");
    if (!item || L.moved) { L.moved = false; return; }
    openGroup(item.dataset.key);
  });
  // the tab you are already on takes you back to its shelf, out of any album you have open
  $("#lib-tabs").addEventListener("click", ev => {
    const b = ev.target.closest("[data-tab]");
    if (!b) return;
    if (b.dataset.tab !== L.tab) showTab(b.dataset.tab); else if (L.open) closeGroup();
  });
  wireLibraryBack();
}

/* ---------- ways back: Esc, Backspace, Alt+←, the mouse's back button, the sidebar entry ---------- */
const libraryVisible = () => S.view === "library";
function libraryBack() {
  if (!libraryVisible()) return false;
  if (L.open) { closeGroup(); return true; }
  if (P.q) { P.q = ""; $("#lib-q").value = ""; renderLibrary(); return true; }
  return false;
}
// clicking "Biblioteca" while already in it: leave any album and clear the search; a tab with nothing to leave scrolls to the top
function libraryHome() {
  if (!libraryBack()) $("#lib-scroll").scrollTo({ top: 0, behavior: "smooth" });
}
function wireLibraryBack() {
  // capture phase: look at what is open before the player closes its own panels on the same key
  document.addEventListener("keydown", ev => {
    if (!libraryVisible() || ev.ctrlKey || ev.metaKey) return;
    const t = ev.target, typing = t.closest && t.closest("input:not([type=range]), textarea, select, [contenteditable]");
    const covered = $("#ctx") || !$("#dialog").classList.contains("hidden") || !$("#pl-queue-panel").classList.contains("hidden") || !$("#pl-eq-panel").classList.contains("hidden");
    if (covered) { if (ev.key === "Escape" && !$("#ctx") && $("#dialog").classList.contains("hidden")) closePanels(); return; }
    if (ev.key === "/" && !typing) { ev.preventDefault(); $("#lib-q").focus(); return; }
    const back = ev.key === "Escape" || (ev.altKey && ev.key === "ArrowLeft") || (ev.key === "Backspace" && !typing);
    if (!back) return;
    if (typing && ev.key === "Escape" && t.id === "lib-q" && t.value) { P.q = ""; t.value = ""; renderLibrary(); ev.preventDefault(); return; }
    if (typing && t.id === "lib-q") { if (ev.key === "Escape") t.blur(); return; }
    if (typing) return;
    if (libraryBack()) ev.preventDefault();
  }, true);
  addEventListener("mouseup", ev => { if (ev.button === 3 && libraryBack()) ev.preventDefault(); });
}

/* ---------- the page of an album or a playlist ---------- */
function openGroup(key) {
  if (key === "new") return newPlaylist();
  if (!L.byKey.has(key)) return;
  L.open = key; P.q = ""; $("#lib-q").value = "";
  renderLibrary();
  $("#lib-scroll").scrollTop = 0;
}

function closeGroup() {
  L.open = null; P.q = ""; $("#lib-q").value = "";
  renderLibrary();
}

function renderDetail() {
  const g = L.byKey.get(L.open), box = $("#lib-detail");
  if (!g) return;
  const album = g.kind === "album";
  box.innerHTML = `<button class="linkish back" id="detail-back" type="button">← ${album ? "Álbumes" : "Playlists"}</button>
    <div class="detail-top">
      <div class="detail-art"><span class="sleeve big"${labelStyle(g)}>${DISC}${groupArt(g)}</span></div>
      <div class="detail-info">
        <span class="kind">${album ? "Álbum" : "Playlist"}</span>
        <h2>${esc(g.title)}</h2>
        <p class="muted">${esc([album ? g.artist : "", plural(g.count, "canción", "canciones"), g.seconds ? durationText(g.seconds) : ""].filter(Boolean).join(" · "))}</p>
        <div class="btn-row"><button class="btn primary" id="detail-play" type="button"${g.count ? "" : " disabled"}>Reproducir</button><button class="btn" id="detail-shuffle" type="button"${g.count ? "" : " disabled"}>Aleatorio</button>
          ${g.mine ? '<button class="btn" id="detail-rename" type="button">Cambiar el nombre</button><button class="btn danger" id="detail-delete" type="button">Eliminar playlist</button>' : ""}</div>
      </div>
    </div>`;
  $("#detail-back").onclick = closeGroup;
  $("#detail-play").onclick = () => playList(g.ids);
  $("#detail-shuffle").onclick = () => { P.shuffle = true; playList(g.ids, g.ids[Math.floor(Math.random() * g.ids.length)]); render(); };
  if (g.mine) { $("#detail-rename").onclick = () => renamePlaylist(g); $("#detail-delete").onclick = () => deletePlaylist(g); }
}

/* ---------- likes and your playlists ---------- */
const ICON_PLUS = '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>';

async function loadCollections() {
  const state = await call("collections_get");
  if (!state || state.error) return;
  L.liked = new Set(Array.isArray(state.liked) ? state.liked : []);
  L.mine = Array.isArray(state.playlists) ? state.playlists : [];
}

async function refreshCollections() {
  await loadCollections();
  renderLibrary();
  render();                                    // the heart of the bar
}

/* Hearts: the program side decides what changes (a song kept as two files is liked in both). */
async function toggleLike(id, button) {
  const result = await call("like_toggle", id);
  if (!result || !result.ok) return toast((result && result.error) || "No pude cambiarlo.", true);
  await refreshCollections();
  toast(result.liked ? "Añadida a Me gusta." : "Quitada de Me gusta.");
  if (result.liked && !reduced()) [$(`.lib-row[data-id="${CSS.escape(id)}"] .heart`), current() && current().id === id ? $("#pl-like") : null].forEach(el => {
    if (el) el.animate([{ transform: "scale(1)" }, { transform: "scale(1.45)" }, { transform: "scale(1)" }], { duration: 380, easing: "cubic-bezier(.23, 1, .32, 1)" });
  });
}

function openPlaylistMenu(x, y, ids) {
  const items = L.mine.map(p => ({ label: p.name, icon: ICON_PLAYLIST, run: () => addToPlaylist(p.id, ids) }));
  if (items.length) items.push({ sep: true });
  items.push({ label: "Nueva playlist…", icon: ICON_PLUS, run: () => newPlaylist(ids) });
  openMenu(x, y, items);
}

async function addToPlaylist(playlistId, ids) {
  const playlist = L.mine.find(p => p.id === playlistId);
  const result = await call("playlist_add", playlistId, ids);
  if (!result || !result.ok) return toast((result && result.error) || "No pude añadirla.", true);
  await refreshCollections();
  toast(ids.length === 1 ? `Añadida a «${playlist ? playlist.name : "la playlist"}».` : `${ids.length} canciones añadidas a «${playlist ? playlist.name : "la playlist"}».`);
}

async function newPlaylist(ids = []) {
  const name = await confirmDialog({ title: "Nueva playlist", ok: "Crear", input: { value: "" } });
  if (name === null) return;
  if (!name) return toast("Ponle un nombre a la playlist.", true);
  const result = await call("playlist_create", name, ids);
  if (!result || !result.ok) return toast((result && result.error) || "No pude crear la playlist.", true);
  await refreshCollections();
  toast(ids.length ? `Playlist «${name}» creada con ${plural(ids.length, "canción", "canciones")}.` : `Playlist «${name}» creada.`, false,
        { label: "Abrir", run: () => { L.tab = "playlists"; L.open = "mine:" + result.id; P.q = ""; $("#lib-q").value = ""; show("library"); renderLibrary(); } });
}

async function removeFromPlaylist(playlistId, ids) {
  for (const id of ids) await call("playlist_remove", playlistId, id);
  await refreshCollections();
  toast(ids.length === 1 ? "Quitada de la playlist." : `${ids.length} canciones quitadas de la playlist.`);
}

async function renamePlaylist(group) {
  const name = await confirmDialog({ title: "Cambiar el nombre", ok: "Guardar", input: { value: group.title } });
  if (name === null || name === group.title) return;
  const result = await call("playlist_rename", group.pid, name);
  if (!result.ok) return toast(result.error || "No pude cambiar el nombre.", true);
  await refreshCollections();
}

async function deletePlaylist(group) {
  const ok = await confirmDialog({ title: "¿Eliminar la playlist?", text: `«${group.title}» desaparece, pero sus canciones se quedan en tu biblioteca.`, ok: "Eliminar playlist", danger: true });
  if (!ok) return;
  const result = await call("playlist_delete", group.pid);
  if (!result.ok) return toast(result.error || "No pude eliminarla.", true);
  L.open = null;
  await refreshCollections();
}
