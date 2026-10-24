"use strict";
/* Burdamix window. The program side is gui/backend.py (window.pywebview.api). Opened in a normal browser with
   ?demo it uses a fake program side, to look at and adjust the design without downloading anything. */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = sec => `${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}`;
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

let api = null;
const S = { view: "home", state: {}, cur: null, running: false, poll: null, rows: {}, favCount: 200 };

async function call(name, ...args) {
  try { return await api[name](...args); }
  catch (e) { return { error: "Algo salió mal dentro del programa." }; }
}

function toast(text, bad = false) {
  const el = document.createElement("div");
  el.className = "toast" + (bad ? " bad" : "");
  el.textContent = text;
  $("#toasts").append(el);
  setTimeout(() => el.remove(), 4200);
}

/* ---------- navigation ---------- */
function show(view) {
  S.view = view;
  $$(".view").forEach(v => v.classList.toggle("active", v.id === "view-" + view));
  $$(".nav").forEach(n => n.classList.toggle("active", n.dataset.view === view));
  if (view === "tutorial") refreshState();
  if (view === "settings") loadSettings();
  if (innerWidth <= 760) $("#app").classList.remove("sidebar-open");
}

function setSidebar(open) {
  $("#app").classList.toggle("sidebar-open", open);
  try { localStorage.setItem("sidebar", open ? "1" : "0"); } catch (e) { /* private mode: not remembered */ }
}

/* ---------- connection state ---------- */
async function refreshState() {
  S.state = await call("get_state");
  const st = S.state, conn = $("#conn");
  conn.className = "conn " + (!st.configured ? "bad" : "ok");
  $("span", conn).textContent = !st.configured ? "Spotify sin conectar" : st.logged_in ? "Spotify conectado" : "App conectada · sin sesión";
  $("#version").textContent = `v${st.version || ""}${st.ytdlp ? " · yt-dlp " + st.ytdlp : ""}`;
  $("#redirect").textContent = st.redirect_uri || "";
  $("#step1-ok").classList.toggle("hidden", !st.configured);
  $("#step2-ok").classList.toggle("hidden", !st.logged_in);
  $("#about").textContent = `Burdamix ${st.version || ""} · yt-dlp ${st.ytdlp || "?"} · Carpeta de datos del programa aparte de tus canciones.`;
  return st;
}

/* ---------- home: paste a link ---------- */
function setHero(view, compact) {
  $(view === "home" ? "#home-hero" : "#fav-hero").classList.toggle("compact", compact);
  if (view === "home") $("#home-dock").classList.toggle("has-results", compact);
}

function showLoading(view, text) {
  $(view === "home" ? "#home-results" : "#fav-results").innerHTML =
    `<div class="panel"><div class="state busy" style="justify-content:flex-start"><i class="spin"></i> ${esc(text)}</div></div>`;
}

async function submitLink() {
  const url = $("#link").value.trim();
  if (!url) return;
  if (S.running) return toast("Hay una descarga en curso. Espera a que termine o cancélala.", true);
  $("#send").disabled = true;
  setHero("home", true);
  clearOther("home");
  showLoading("home", "Leyendo el enlace en Spotify…");
  const r = await call("preview", url);
  $("#send").disabled = false;
  handlePreview("home", r);
}

async function submitFavorites() {
  if (S.running) return toast("Hay una descarga en curso. Espera a que termine o cancélala.", true);
  const custom = parseInt($("#fav-custom").value, 10);
  const n = custom > 0 ? custom : S.favCount;
  $("#fav-go").disabled = true;
  setHero("favorites", true);
  clearOther("favorites");
  showLoading("favorites", "Leyendo tus favoritas en Spotify (con muchas puede tardar unos segundos)…");
  const r = await call("preview_liked", n || null);
  $("#fav-go").disabled = false;
  handlePreview("favorites", r);
}

function clearOther(view) {
  if (S.cur && S.cur.view !== view && S.cur.phase !== "running") S.cur = null;
  $(view === "home" ? "#fav-results" : "#home-results").innerHTML = "";
}

function handlePreview(view, r) {
  const box = $(view === "home" ? "#home-results" : "#fav-results");
  if (r.error) {
    S.cur = null;
    const needsSetup = r.error === "login_required" || r.error === "setup_required";
    box.innerHTML = `<div class="panel ${needsSetup ? "warn" : "bad"}"><h3>${needsSetup ? "Falta un paso" : "No se pudo leer"}</h3>
      <p>${esc(r.message || r.error)}</p>
      ${needsSetup ? '<div class="btn-row"><button class="btn primary" id="go-tutorial">Ir al tutorial</button></div>' : ""}</div>`;
    const go = $("#go-tutorial", box);
    if (go) go.onclick = () => show("tutorial");
    return;
  }
  S.cur = { view, data: r, selected: new Set(r.items.filter(i => !i.already).map(i => i.key)), status: {}, phase: "idle", summary: null };
  renderResults();
  const scroller = $(view === "home" ? "#home-scroll" : "#fav-scroll");
  scroller.scrollTop = 0;
}

/* ---------- the list ---------- */
const KIND = { song: "Canción", album: "Álbum", playlist: "Playlist", liked: "Mis favoritos" };
const STATE_TEXT = { queued: "En cola", searching: "Buscando…", downloading: "Descargando…", converting: "Convirtiendo…" };

function renderResults() {
  const c = S.cur;
  if (!c) return;
  const d = c.data, box = $(c.view === "home" ? "#home-results" : "#fav-results");
  const cover = c.view === "favorites" || d.kind === "liked"
    ? '<div class="cover-lg fav"><svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg></div>'
    : `<img class="cover-lg" src="${esc(d.cover)}" alt="">`;
  const title = d.kind === "liked" ? "Tus canciones favoritas" : d.title;
  const meta = d.limited ? `Las ${d.items.length} más recientes de ${d.total}` : plural(d.items.length, "canción", "canciones");

  let notes = "";
  if (d.interludes.length) notes += `<p class="note">Se omiten ${plural(d.interludes.length, "pista corta", "pistas cortas")} (intros, interludios): ${esc(d.interludes.join(", "))}.</p>`;
  if (d.repeated) notes += `<p class="note">${plural(d.repeated, "canción repetida", "canciones repetidas")} en la lista: se baja una sola vez.</p>`;

  box.innerHTML = `
    <div class="list-head">${cover}<div>
      <div class="kind">${KIND[d.kind]}</div><h2>${esc(title)}</h2>
      <div class="muted">${esc(meta)} · <span title="${esc(d.folder)}">se guarda en ${esc(d.folder)}</span></div></div></div>
    <div id="summary-slot"></div>${notes}
    <div class="list-tools"><span class="muted small" id="sel-count"></span>
      <span><button class="linkish" id="sel-all">Marcar todas</button><button class="linkish" id="sel-none">Ninguna</button></span></div>
    <div class="tracks" id="tracks"></div>
    <div class="bar-wrap"><div class="action-bar" id="bar"></div></div>`;

  const list = $("#tracks", box);
  S.rows = {};
  d.items.forEach(item => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = `<input type="checkbox" aria-label="Marcar">
      <img src="${esc(item.cover)}" alt="" loading="lazy">
      <div class="t"><b>${esc(item.title)}</b><span>${esc(item.artists)}${item.saved ? " · guardada " + esc(item.saved) : ""}</span><span class="why hidden"></span></div>
      <div class="dur">${fmt(item.seconds)}</div><div class="state"></div>`;
    $("input", row).onchange = ev => { ev.target.checked ? c.selected.add(item.key) : c.selected.delete(item.key); paintBar(); paintRow(item.key); };
    S.rows[item.key] = row;
    list.append(row);
    paintRow(item.key);
  });
  $("#sel-all", box).onclick = () => setAll(true);
  $("#sel-none", box).onclick = () => setAll(false);
  if (c.summary) paintSummary();
  paintBar();
}

function setAll(on) {
  const c = S.cur;
  if (!c || c.phase === "running") return;
  c.selected = new Set(on ? c.data.items.map(i => i.key) : []);
  c.data.items.forEach(i => paintRow(i.key));
  paintBar();
}

function paintRow(key) {
  const c = S.cur, row = S.rows[key];
  if (!c || !row) return;
  const item = c.data.items.find(i => i.key === key);
  const st = c.status[key], box = $("input", row), state = $(".state", row), why = $(".why", row);
  const running = c.phase === "running";
  box.checked = c.selected.has(key);
  box.disabled = running || c.phase === "finished";
  row.classList.toggle("off", !c.selected.has(key) && !st);
  state.className = "state";
  why.classList.add("hidden");
  if (!st) { state.textContent = item.already ? "Ya descargada" : ""; return; }
  if (st.state === "done") { state.className = "state ok"; state.textContent = st.existed ? "✓ Ya estaba" : "✓ Listo"; }
  else if (st.state === "failed") {
    state.className = "state bad"; state.textContent = "✕ No se pudo";
    why.textContent = st.reason || ""; why.classList.remove("hidden");
  } else { state.className = "state busy"; state.innerHTML = `<i class="spin"></i>${STATE_TEXT[st.state] || ""}`; }
}

function counts() {
  const c = S.cur, vals = Object.values(c.status);
  return { total: Object.keys(c.status).length, ok: vals.filter(v => v.state === "done").length, bad: vals.filter(v => v.state === "failed").length };
}

function paintBar() {
  const c = S.cur;
  if (!c) return;
  const bar = $("#bar"), n = c.selected.size, all = c.data.items.length;
  if (!bar) return;
  const already = c.data.items.filter(i => i.already).length;
  const selCount = $("#sel-count");
  if (selCount) selCount.textContent = `${n} de ${all} marcadas${already ? ` · ${already} ya descargadas` : ""}`;

  if (c.phase === "idle") {
    bar.innerHTML = `<div class="grow"><b>${plural(n, "canción", "canciones")}</b> para descargar<div class="muted small">MP3 con la mejor calidad que da YouTube</div></div>
      <button class="btn primary big" style="margin:0" id="go" ${n ? "" : "disabled"}>Descargar ${n || ""}</button>`;
    $("#go").onclick = startDownload;
  } else if (c.phase === "running") {
    const k = counts(), done = k.ok + k.bad, total = Object.keys(c.status).length;
    bar.innerHTML = `<div class="grow"><b>Descargando</b> · ${done} de ${total}${k.bad ? ` · ${k.bad} con problemas` : ""}
      <div class="progress"><i style="width:${total ? Math.round(done / total * 100) : 0}%"></i></div></div>
      <button class="btn danger" id="cancel">Cancelar</button>`;
    $("#cancel").onclick = async () => { await call("cancel_download"); toast("Cancelando: terminan las que ya empezaron."); };
  } else {
    const k = counts();
    bar.innerHTML = `<div class="grow"><b>${plural(k.ok, "canción descargada", "canciones descargadas")}</b>${k.bad ? ` · ${k.bad} con problemas` : ""}</div>
      <button class="btn" id="again">Otra búsqueda</button><button class="btn primary" id="open">Abrir carpeta</button>`;
    $("#open").onclick = () => call("open_folder", c.data.folder);
    $("#again").onclick = newSearch;
  }
}

function newSearch() {
  const view = S.cur ? S.cur.view : "home";
  S.cur = null;
  $(view === "home" ? "#home-results" : "#fav-results").innerHTML = "";
  setHero(view, false);
  if (view === "home") { $("#link").value = ""; $("#link").focus(); }
}

function paintSummary() {
  const c = S.cur, s = c.summary, slot = $("#summary-slot");
  if (!s || !slot) return;
  const k = counts();
  let html = "";
  if (s.error) html = `<div class="panel bad"><h3>La descarga se detuvo</h3><p>${esc(s.error)}</p></div>`;
  else {
    const kind = s.failed.length || s.blocked || s.cancelled ? "warn" : "good";
    html = `<div class="panel ${kind}"><h3>${s.cancelled ? "Descarga cancelada" : s.blocked ? "YouTube te está bloqueando" : s.failed.length ? "Listo, con algunos problemas" : "¡Listo!"}</h3>
      <p>${plural(k.ok, "canción descargada", "canciones descargadas")} en <b>${esc(s.folder)}</b>.</p>`;
    if (s.blocked) html += `<p class="muted">Paré para no empeorarlo. Espera un rato (a veces una hora) o cambia de red, y pega el mismo enlace: lo que ya se bajó se salta.</p>`;
    if (s.failed.length) {
      html += `<p>No se pudieron descargar ${s.failed.length}:</p><ul>${s.failed.map(f => `<li><b>${esc(f.artists)} – ${esc(f.title)}</b>: ${esc(f.reason)}</li>`).join("")}</ul>`;
      if (s.advice.length) html += `<p style="margin-top:12px"><b>Qué hacer</b></p><ul>${s.advice.map(a => `<li>${esc(a)}</li>`).join("")}</ul>`;
    }
    if (s.outdated_ytdlp) html += `<div class="btn-row"><button class="btn primary" id="sum-update">Actualizar yt-dlp</button></div>`;
    html += "</div>";
  }
  slot.innerHTML = html;
  const up = $("#sum-update", slot);
  if (up) up.onclick = updateYtdlp;
}

/* ---------- downloading ---------- */
async function startDownload() {
  const c = S.cur;
  if (!c || !c.selected.size) return;
  const keys = [...c.selected];
  const r = await call("start_download", keys);
  if (!r.ok) return toast(r.error || "No se pudo empezar.", true);
  c.phase = "running";
  c.status = {};
  keys.forEach(k => { c.status[k] = { state: "queued" }; });
  S.running = true;
  c.data.items.forEach(i => paintRow(i.key));
  paintBar();
  S.poll = setInterval(pollEvents, 500);
}

let polling = false;
async function pollEvents() {
  if (polling) return;
  polling = true;
  try {
    const events = await call("get_events");
    (Array.isArray(events) ? events : []).forEach(onEvent);
  } finally { polling = false; }
}

function onEvent(e) {
  const c = S.cur;
  if (!c) return;
  if (e.kind === "finished") {
    clearInterval(S.poll); S.poll = null;
    S.running = false;
    c.phase = "finished";
    c.summary = e;
    c.data.items.forEach(i => paintRow(i.key));
    paintSummary();
    paintBar();
    $(c.view === "home" ? "#home-scroll" : "#fav-scroll").scrollTop = 0;   // the summary is at the top
    return;
  }
  if (!e.key) return;
  if (e.kind === "stage") c.status[e.key] = { state: e.stage };
  else if (e.kind === "done") c.status[e.key] = { state: "done", existed: e.existed };
  else if (e.kind === "failed") c.status[e.key] = { state: "failed", reason: e.reason };
  paintRow(e.key);
  paintBar();
}

async function updateYtdlp() {
  toast("Buscando una versión nueva de yt-dlp…");
  const r = await call("update_ytdlp");
  toast(r.message || r.error || "Listo.", !r.ok);
  refreshState();
  return r;
}

/* ---------- tutorial ---------- */
function copyText(text) {
  const fallback = () => { const t = document.createElement("textarea"); t.value = text; document.body.append(t); t.select(); document.execCommand("copy"); t.remove(); };
  (navigator.clipboard ? navigator.clipboard.writeText(text).catch(fallback) : Promise.resolve(fallback())).then(() => toast("Copiado."));
}

function formMsg(el, text, kind) { el.textContent = text; el.className = "form-msg " + (kind || ""); }

async function saveCreds(ev) {
  ev.preventDefault();
  const msg = $("#creds-msg"), btn = $("#save-creds");
  btn.disabled = true; formMsg(msg, "Comprobando con Spotify…");
  const r = await call("save_spotify_app", $("#client-id").value, $("#client-secret").value);
  btn.disabled = false;
  if (r.ok) {
    formMsg(msg, "Guardado. No tendrás que repetir esto.", "ok");
    $("#client-secret").value = ""; $("#client-id").value = "";
    await refreshState();
  } else formMsg(msg, r.error || "No se pudo guardar.", "bad");
}

async function doLogin() {
  const msg = $("#login-msg"), btn = $("#do-login");
  const st = await refreshState();
  if (!st.configured) return formMsg(msg, "Primero completa el paso 1.", "bad");
  btn.disabled = true;
  formMsg(msg, "Esperando en tu navegador… elige tu cuenta y pulsa Aceptar (3 minutos).");
  await call("login_spotify");
  const timer = setInterval(async () => {
    const r = await call("get_login_state");
    if (r.state === "waiting") return;
    clearInterval(timer);
    btn.disabled = false;
    if (r.state === "ok") { formMsg(msg, `Listo. Sesión iniciada${r.message ? " como " + r.message : ""}.`, "ok"); refreshState(); }
    else formMsg(msg, r.message || "No se pudo iniciar sesión.", "bad");
  }, 1000);
}

/* ---------- faq ---------- */
const FAQ = [
  ["¿De dónde sale el audio?", "<p>Spotify no deja bajar su música. Burdamix busca en YouTube el audio que coincide con cada canción (comparando la duración con la de Spotify para no elegir una versión equivocada) y lo convierte a MP3 con sus etiquetas y su portada.</p>"],
  ["¿Qué calidad tienen los MP3?", "<p>La mejor que YouTube ofrece: unos 128 kbps. Pedir más no mejora nada, porque YouTube no tiene más; por eso nunca se ven 320 kbps.</p>"],
  ["¿Dónde se guardan las canciones?", "<p>En la carpeta que ves en <b>Configuración</b> (por defecto, <code>Música\\Burdamix</code>). Dentro hay una subcarpeta por álbum o playlist. Puedes cambiarla cuando quieras.</p>"],
  ["¿Por qué me pide iniciar sesión en Spotify?", "<p>Spotify solo entrega el contenido de las playlists a quien inició sesión, y solo las que son <b>tuyas</b> (o colaborativas). Para una canción suelta o un álbum no hace falta. Tu contraseña nunca se pide aquí.</p>"],
  ["Una canción se saltó. ¿Por qué?", "<p>Cada una dice su motivo. Los más comunes:</p><ul><li><b>No hay una versión con la misma duración:</b> prefiero saltarla antes que bajar una equivocada.</li><li><b>Mayores de edad:</b> YouTube exige sesión; puedes usar tu navegador en Configuración.</li><li><b>Aviso de robot:</b> YouTube recibió muchas solicitudes; espera unos minutos y pega el mismo enlace.</li></ul>"],
  ["¿Qué significa «YouTube te está bloqueando»?", "<p>Si YouTube rechaza varias canciones seguidas, paro para no empeorarlo. Espera un rato (a veces una hora) o cambia de red y vuelve a pegar el mismo enlace: lo ya descargado se salta y continúa donde quedó.</p>"],
  ["¿Por qué no se bajan las intros y los interludios?", "<p>Por defecto se omiten las pistas muy cortas (menos de 50 s, o intro/outro de menos de 95 s). Se puede desactivar en Configuración.</p>"],
  ["Dejó de funcionar de repente", "<p>YouTube cambia cada pocas semanas. En <b>Configuración → Actualizar yt-dlp</b> se baja la versión nueva (hace falta internet). Después cierra y abre el programa.</p>"],
  ["¿Es seguro?", "<p>Todo se hace en tu computadora. Las claves de tu app de Spotify se guardan en una carpeta privada de tu usuario. Windows puede avisar de «editor desconocido» porque el programa no está firmado: es normal en programas gratuitos.</p>"],
];

function buildFaq() {
  $("#faq-list").innerHTML = FAQ.map(([q, a]) => `<details><summary>${esc(q)}</summary>${a}</details>`).join("");
}

/* ---------- settings ---------- */
let saveTimer = null;
async function loadSettings() {
  const s = await call("get_settings");
  if (s.error) return;
  $("#set-folder-path").textContent = s.effective_downloads_dir;
  $("#set-workers").value = s.workers; $("#set-workers-out").textContent = s.workers;
  $("#set-interludes").checked = s.skip_interludes;
  const sel = $("#set-browser");
  sel.innerHTML = '<option value="">No usar</option>' + s.browsers.map(b => `<option value="${esc(b)}">${esc(b[0].toUpperCase() + b.slice(1))}</option>`).join("");
  sel.value = s.browser;
  const st = await refreshState();
  $("#set-ytdlp").textContent = `yt-dlp ${st.ytdlp || "?"}. YouTube cambia cada pocas semanas: si una descarga falla de repente, actualiza esto.`;
}

function saveSettingsSoon() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    const r = await call("save_settings", {
      workers: +$("#set-workers").value, skip_interludes: $("#set-interludes").checked, browser: $("#set-browser").value,
    });
    if (r.ok === false) toast(r.error, true);
  }, 300);
}

/* ---------- demo mode (browser only) ---------- */
function demoApi() {
  const art = (a, b) => "data:image/svg+xml," + encodeURIComponent(`<svg xmlns='http://www.w3.org/2000/svg' width='96' height='96'><defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='${a}'/><stop offset='1' stop-color='${b}'/></linearGradient></defs><rect width='96' height='96' fill='url(#g)'/></svg>`);
  const names = ["Blinding Lights", "Save Your Tears", "Starboy", "Heartless", "Die For You", "Take My Breath", "In Your Eyes", "Out of Time"];
  let queue = [], cfg = { configured: true, logged_in: true }, settings = { downloads_dir: "", workers: 5, skip_interludes: true, browser: "" };
  const items = names.map((t, i) => ({ key: "k" + i, title: t, artists: "The Weeknd", album: "After Hours", seconds: 190 + i * 7,
    cover: art(["#3a1c71", "#134e5e", "#7b2d26", "#1f4037"][i % 4], ["#d76d77", "#71b280", "#f0a500", "#99f2c8"][i % 4]), saved: "", already: i === 3 }));
  const push = (kind, data) => queue.push({ kind, t: Date.now(), ...data });
  return {
    get_state: async () => ({ version: "0.2.0-pre", ytdlp: "2026.10.21", frozen: false, configured: cfg.configured, logged_in: cfg.logged_in,
      redirect_uri: "http://127.0.0.1:5000/callback", dashboard_url: "", busy: false, downloads_dir: "C:\\Users\\Tú\\Music\\Burdamix" }),
    get_settings: async () => ({ ...settings, effective_downloads_dir: "C:\\Users\\Tú\\Music\\Burdamix", browsers: ["firefox", "chrome", "edge"] }),
    save_settings: async s => { settings = { ...settings, ...s }; return { ok: true }; },
    preview: async url => { await new Promise(r => setTimeout(r, 900)); return /spotify/.test(url) ? { kind: "album", title: "After Hours", cover: art("#7b2d26", "#f0a500"), items, total: 8, folder: "C:\\Users\\Tú\\Music\\Burdamix\\albums\\After Hours\\", interludes: ["Intro"], repeated: 0, limited: false } : { error: "Eso no parece un enlace de Spotify de una canción, playlist o álbum." }; },
    preview_liked: async n => { await new Promise(r => setTimeout(r, 900)); return { kind: "liked", title: "Liked Songs", cover: null, items, total: 1036, folder: "C:\\Users\\Tú\\Music\\Burdamix\\liked\\Liked Songs\\", interludes: [], repeated: 0, limited: true }; },
    start_download: async keys => {
      keys.forEach((k, i) => {
        const at = ms => 700 + i * 900 + ms;
        setTimeout(() => push("stage", { key: k, stage: "searching" }), at(0));
        setTimeout(() => push("stage", { key: k, stage: "downloading" }), at(500));
        setTimeout(() => push("stage", { key: k, stage: "converting" }), at(1300));
        setTimeout(() => push(i === 2 ? "failed" : "done", i === 2 ? { key: k, reason: "YouTube pidió comprobar que no eres un robot (demasiadas solicitudes seguidas)." } : { key: k, existed: false }), at(1800));
      });
      setTimeout(() => push("finished", { folder: "C:\\Users\\Tú\\Music\\Burdamix\\albums\\After Hours\\", blocked: false, cancelled: false, outdated_ytdlp: false, error: null,
        failed: [{ key: keys[2], title: names[2], artists: "The Weeknd", reason: "YouTube pidió comprobar que no eres un robot (demasiadas solicitudes seguidas).", category: "robot" }],
        advice: ["Las del aviso de robot: YouTube recibió muchas solicitudes. Espera unos minutos y ejecuta de nuevo el mismo enlace: solo bajará las que faltan."] }), 1200 + keys.length * 900 + 1800);
      return { ok: true, count: keys.length };
    },
    get_events: async () => { const e = queue; queue = []; return e; },
    cancel_download: async () => true, open_folder: async () => true, choose_folder: async () => null, open_external: async () => true,
    save_spotify_app: async (id, sec) => (id && sec ? (cfg.configured = true, { ok: true }) : { ok: false, error: "Los dos datos son obligatorios." }),
    login_spotify: async () => { setTimeout(() => { cfg.logged_in = true; }, 1500); return { ok: true }; },
    get_login_state: async () => (cfg.logged_in ? { state: "ok", message: "Demo" } : { state: "waiting", message: "" }),
    update_ytdlp: async () => ({ ok: true, message: "Ya tienes la versión más nueva de yt-dlp." }),
  };
}

/* ---------- start ---------- */
function init() {
  $$(".nav").forEach(n => n.onclick = () => show(n.dataset.view));
  $("#toggle").onclick = () => setSidebar(!$("#app").classList.contains("sidebar-open"));
  $("#toggle2").onclick = () => setSidebar(true);
  $("#conn").onclick = () => show("tutorial");
  try { if (localStorage.getItem("sidebar") === "0") setSidebar(false); } catch (e) { /* default: open */ }

  $("#composer").onsubmit = ev => { ev.preventDefault(); submitLink(); };
  $("#paste").onclick = async () => {
    try { $("#link").value = (await navigator.clipboard.readText()).trim(); submitLink(); }
    catch (e) { $("#link").focus(); toast("Pulsa Ctrl+V dentro del cuadro para pegar."); }
  };
  $("#link").addEventListener("paste", ev => {
    const text = ((ev.clipboardData || window.clipboardData).getData("text") || "").trim();
    if (/spotify/.test(text)) { ev.preventDefault(); $("#link").value = text; submitLink(); }
  });

  $$("#fav-counts button").forEach(b => b.onclick = () => {
    $$("#fav-counts button").forEach(x => x.classList.toggle("on", x === b));
    S.favCount = +b.dataset.n; $("#fav-custom").value = "";
  });
  $("#fav-custom").oninput = () => { if ($("#fav-custom").value) $$("#fav-counts button").forEach(x => x.classList.remove("on")); };
  $("#fav-go").onclick = submitFavorites;

  $("#open-dash").onclick = () => call("open_external", S.state.dashboard_url || "https://developer.spotify.com/dashboard");
  $("#copy-redirect").onclick = () => copyText($("#redirect").textContent);
  $("#creds").onsubmit = saveCreds;
  $("#do-login").onclick = doLogin;

  $("#set-folder-open").onclick = () => call("open_folder");
  $("#set-folder-change").onclick = async () => {
    const chosen = await call("choose_folder");
    if (!chosen) return;
    const r = await call("save_settings", { downloads_dir: chosen });
    if (r.ok) { $("#set-folder-path").textContent = r.effective_downloads_dir; toast("Carpeta cambiada."); }
  };
  $("#set-workers").oninput = () => { $("#set-workers-out").textContent = $("#set-workers").value; saveSettingsSoon(); };
  $("#set-interludes").onchange = saveSettingsSoon;
  $("#set-browser").onchange = saveSettingsSoon;
  $("#set-update").onclick = updateYtdlp;

  buildFaq();
  refreshState().then(st => {
    if (st && st.configured === false) { show("tutorial"); toast("Primero conecta el programa con Spotify."); }
  });
}

(function boot() {
  const start = realApi => { if (api) return; api = realApi; init(); };
  if (location.search.includes("demo")) return start(demoApi());
  if (window.pywebview && window.pywebview.api) return start(window.pywebview.api);
  window.addEventListener("pywebviewready", () => start(window.pywebview.api));
})();
