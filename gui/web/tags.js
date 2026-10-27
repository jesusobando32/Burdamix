"use strict";
/* "Completar etiquetas": pick audio files, look their songs up, choose the right one, see what will change, write it.
   Uses the helpers of app.js ($, esc, call, toast, show, plural); the program side is Api.tags_* in gui/backend.py. */

const T = { files: [], running: false, applying: false, confirm: false, jobTotal: 0, jobDone: 0, wiredOnce: false };

const TAG_STATUS = {
  pending: ["Sin buscar", ""], queued: ["En cola", "busy"], searching: ["Buscando…", "busy"],
  complete: ["Ya está completo", "good"], sure: ["Coincidencia clara", "good"], review: ["Elige la correcta", "warn"],
  notfound: ["No encontrada", "bad"], error: ["Error", "bad"], writing: ["Escribiendo…", "busy"],
  applied: ["Listo", "good"], failed: ["No se pudo escribir", "bad"],
};
const FINISHED = ["applied"];

const tagFile = path => T.files.find(f => f.path === path);
const baseName = p => String(p).split(/[\\/]/).pop();

function tagSummary(t) {
  if (!t) return "";
  const main = [t.title, t.artist].filter(Boolean).join(" — ");
  const rest = [t.album, t.year, t.genre].filter(Boolean).join(" · ");
  const bits = [main || "Sin título ni artista", rest, t.has_cover ? "con portada" : "sin portada"].filter(Boolean);
  return bits.join(" · ");
}

async function addPaths(paths) {
  if (!paths || !paths.length) return;
  show("tags");
  const scanned = await call("tags_scan", paths);
  if (!Array.isArray(scanned)) return;
  let added = 0;
  for (const e of scanned) {
    if (tagFile(e.path)) continue;
    T.files.push({ path: e.path, name: e.name, tags: e.tags || null, status: e.error ? "error" : "pending", error: e.error || "",
                   candidates: [], sel: 0, prepared: null, include: true, done: null });
    added++;
  }
  if (!added) toast(scanned.length ? "Esos archivos ya estaban en la lista." : "No encontré canciones compatibles (mp3, flac, m4a, ogg u opus).", !scanned.length);
  renderTags();
}

/* ---------- drawing ---------- */
function candidatesHTML(f) {
  const rows = f.candidates.map((c, i) => `
    <label class="cand ${i === f.sel ? "on" : ""}" data-i="${i}">
      <input type="radio" name="c-${esc(f.path)}" ${i === f.sel ? "checked" : ""} data-act="pick" data-i="${i}">
      <img src="${esc(c.thumb_url)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">
      <div><b>${esc(c.title)}</b> — ${esc(c.artist)}
        <span><i class="tag-kind ${c.kind === "album" ? "studio" : ""}">${esc(c.kind_label)}</i>${esc([c.album, c.year].filter(Boolean).join(" · "))}</span>
        <span>${esc(c.source === "musicbrainz" ? "MusicBrainz" : c.source === "deezer" ? "Deezer" : "iTunes")}${c.genre ? " · " + esc(c.genre) : ""}${c.track_number ? " · pista " + c.track_number : ""}</span></div>
    </label>`).join("");
  const include = f.status === "sure" && T.files.length > 1
    ? `<label class="check"><input type="checkbox" data-act="include" ${f.include ? "checked" : ""}> Incluir en «Aplicar las coincidencias claras»</label>` : "";
  return `${rows}${include}<div class="btn-row"><button class="btn primary" data-act="review">Revisar cambios</button></div>`;
}

function diffHTML(f) {
  const p = f.prepared, rename = $("#tags-rename").checked;
  const rows = p.changes.map(r => r.field === "cover"
    ? `<tr><td class="lab">Portada</td><td class="old">${esc(r.old)}</td><td>→</td><td class="new"><img src="${esc(p.candidate.thumb_url)}" alt="" onerror="this.style.display='none'"></td></tr>`
    : `<tr><td class="lab">${esc(r.label)}</td><td class="old">${esc(r.old)}</td><td>→</td><td class="new">${esc(r.new)}</td></tr>`).join("");
  return `${p.changes.length ? `<table class="diff">${rows}</table>` : '<p class="muted">No hay nada que cambiar: el archivo ya tiene esos datos.</p>'}
    <p class="warn-note">Los cambios se escriben en el archivo y no se pueden deshacer.${rename ? ` El archivo se renombrará a «${esc(p.file_name || "")}».` : ""}</p>
    <div class="btn-row"><button class="btn primary" data-act="confirm1">Confirmar y escribir</button><button class="btn" data-act="cancel1">Cancelar</button></div>`;
}

function retryHTML(f, message) {
  return `<p class="${f.status === "notfound" ? "muted" : "form-msg bad"}">${esc(message)}</p>
    <div class="inline-form"><label>Título<input data-f="title" type="text" value="${esc(f.tags && f.tags.title)}" autocomplete="off"></label>
    <label>Artista<input data-f="artist" type="text" value="${esc(f.tags && f.tags.artist)}" autocomplete="off"></label>
    <button class="btn" data-act="retry">Buscar de nuevo</button></div>`;
}

function bodyHTML(f) {
  if ((f.status === "sure" || f.status === "review") && f.candidates.length) return f.prepared ? diffHTML(f) : candidatesHTML(f);
  if (f.status === "applied") {
    const d = f.done || {};
    return `<p>✓ Etiquetas escritas${d.genre ? " · género " + esc(d.genre) : ""}.${d.cover ? "" : ` <span class="warn-note">${esc(d.problem || "No encontré portada para esta canción.")}</span>`}</p>
      ${d.cover ? "" : `<div class="btn-row"><button class="btn" data-act="pickcover">Elegir una imagen…</button></div>
        <p class="muted small">${d.problem ? "También puedes volver a buscar esta canción cuando se resuelva. " : ""}La imagen se reduce a 1000 × 1000 y se escribe en el archivo.</p>`}`;
  }
  if (f.status === "failed") return retryHTML(f, f.error || "No se pudo escribir el archivo.");
  if (f.status === "notfound") return retryHTML(f, f.error || "No encontré esta canción.");
  if (f.status === "error") return f.error && !f.tags ? `<p class="form-msg bad">${esc(f.error)}</p>` : retryHTML(f, f.error);
  if (f.status === "complete") return '<p class="muted">Ya tiene todas las etiquetas y la portada. Si quieres cambiarlas, desmarca «Saltar los que ya tienen todo» y busca de nuevo.</p>';
  return "";
}

function cardHTML(f) {
  const [label, kind] = TAG_STATUS[f.status] || ["", ""];
  const spin = kind === "busy" ? '<i class="spin"></i>' : "";
  const body = bodyHTML(f);
  return `<div class="tcard" data-path="${esc(f.path)}">
    <div class="thead"><div class="tmain"><b title="${esc(f.path)}">${esc(f.name)}</b><span>${esc(tagSummary(f.tags))}</span></div>
      <div class="tstat ${kind}">${spin}${label}</div>
      <button class="icon-btn small" data-act="remove" title="Quitar de la lista" aria-label="Quitar"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg></button></div>
    ${body ? `<div class="tbody">${body}</div>` : ""}</div>`;
}

function renderTags() {
  const has = T.files.length > 0;
  $("#tags-options").classList.toggle("hidden", !has);
  $("#tags-one").classList.toggle("hidden", T.files.length !== 1);
  $("#tags-dock").classList.toggle("hidden", !has);
  $("#tags-list").innerHTML = T.files.map(cardHTML).join("");
  renderTagBar();
}

function updateCard(f) {
  const el = [...$$("#tags-list .tcard")].find(c => c.dataset.path === f.path);
  if (el) el.outerHTML = cardHTML(f); else renderTags();
  renderTagBar();
}

function renderTagBar() {
  const bar = $("#tags-bar");
  if (!bar) return;
  const count = s => T.files.filter(f => f.status === s).length;
  const sure = T.files.filter(f => f.status === "sure" && f.include && f.candidates.length);
  if (T.running || T.applying) {
    const pct = T.jobTotal ? Math.round(T.jobDone / T.jobTotal * 100) : 0;
    bar.innerHTML = `<div class="grow"><b>${T.applying ? "Escribiendo" : "Buscando"}</b> · ${T.jobDone} de ${T.jobTotal}
      <div class="progress"><i style="width:${pct}%"></i></div></div><button class="btn danger" data-act="cancel">Cancelar</button>`;
  } else if (T.confirm) {
    const rename = $("#tags-rename").checked;
    bar.innerHTML = `<div class="grow"><b>Se escribirán etiquetas en ${plural(sure.length, "archivo", "archivos")}</b>
      <div class="muted small">Se cambian los archivos de verdad y no se puede deshacer.${rename ? " Se renombran con el estilo de Configuración." : ""}</div></div>
      <button class="btn" data-act="confirm-no">Cancelar</button><button class="btn primary" data-act="confirm-yes">Confirmar y escribir</button>`;
  } else {
    const parts = [];
    if (sure.length) parts.push(`${sure.length} con coincidencia clara`);
    if (count("review")) parts.push(`${count("review")} por revisar`);
    if (count("notfound")) parts.push(`${count("notfound")} no encontradas`);
    if (count("complete")) parts.push(`${count("complete")} ya completas`);
    if (count("applied")) parts.push(`${count("applied")} listas`);
    if (count("failed") + count("error")) parts.push(`${count("failed") + count("error")} con problemas`);
    bar.innerHTML = `<div class="grow"><b>${plural(T.files.length, "canción", "canciones")}</b>${parts.length ? `<div class="muted small">${esc(parts.join(" · "))}</div>` : ""}</div>
      ${sure.length ? `<button class="btn primary" data-act="apply-sure">Aplicar ${sure.length === 1 ? "la coincidencia clara" : "las " + sure.length + " coincidencias claras"}</button>` : ""}`;
  }
}

/* ---------- the rename option shows what the chosen file-name style looks like ---------- */
async function refreshRenameExample() {
  const s = await call("get_settings");
  const label = $("#tags-rename-example");
  if (!s || s.error || !label) return;
  const style = (s.name_styles || []).find(n => n.id === s.name_style);
  label.textContent = style ? `(ahora: ${style.label}, por ejemplo «${NAMING_EXAMPLES[s.name_style] || ""}»)` : "";
}

/* ---------- actions ---------- */
async function searchAll() {
  if (T.running || T.applying) return;
  const paths = T.files.filter(f => !FINISHED.includes(f.status)).map(f => f.path);
  if (!paths.length) return toast("No hay canciones pendientes.");
  const one = T.files.length === 1;
  const r = await call("tags_identify", paths, one ? $("#tags-title").value.trim() : "", one ? $("#tags-artist").value.trim() : "", $("#tags-skip").checked);
  if (!r.ok) return toast(r.error || "No se pudo empezar.", true);
  T.running = true; T.jobTotal = paths.length; T.jobDone = 0;
  paths.forEach(p => { const f = tagFile(p); f.status = "queued"; f.prepared = null; f.candidates = []; });
  renderTags();
}

async function onTagsClick(ev) {
  const el = ev.target.closest("[data-act]");
  if (!el) return;
  const card = el.closest(".tcard"), f = card && tagFile(card.dataset.path), act = el.dataset.act;
  if (act === "pick") { f.sel = +el.dataset.i; $$(".cand", card).forEach(c => c.classList.toggle("on", +c.dataset.i === f.sel)); }
  else if (act === "include") f.include = el.checked, renderTagBar();
  else if (act === "remove") { if (T.running || T.applying) return toast("Espera a que termine o cancela.", true); T.files = T.files.filter(x => x !== f); renderTags(); }
  else if (act === "review") {
    el.disabled = true;
    const r = await call("tags_prepare", f.path, f.candidates[f.sel]);
    if (!r.ok) { el.disabled = false; return toast(r.error || "No se pudo preparar.", true); }
    f.prepared = r; updateCard(f);
  } else if (act === "cancel1") { f.prepared = null; updateCard(f); }
  else if (act === "pickcover") {
    const image = await call("tags_pick_image");
    if (!image) return;
    const r = await call("tags_set_cover", f.path, image);
    if (!r.ok) return toast(r.error || "No se pudo poner la portada.", true);
    f.done = { ...f.done, cover: true, problem: null }; if (r.tags) f.tags = r.tags;
    toast("Portada puesta."); updateCard(f);
  } else if (act === "confirm1") {
    const r = await call("tags_apply", [{ path: f.path, candidate: f.prepared.candidate }], $("#tags-rename").checked);
    if (!r.ok) return toast(r.error || "No se pudo escribir.", true);
    T.applying = true; T.jobTotal = 1; T.jobDone = 0; f.status = "writing"; updateCard(f);
  } else if (act === "retry") {
    const title = $("[data-f=title]", card).value.trim(), artist = $("[data-f=artist]", card).value.trim();
    if (!title && !artist) return toast("Escribe al menos el título o el artista.", true);
    const r = await call("tags_identify", [f.path], title, artist, false);
    if (!r.ok) return toast(r.error || "No se pudo buscar.", true);
    T.running = true; T.jobTotal = 1; T.jobDone = 0; f.status = "queued"; updateCard(f);
  }
}

async function onBarClick(ev) {
  const act = (ev.target.closest("[data-act]") || {}).dataset && ev.target.closest("[data-act]").dataset.act;
  if (act === "cancel") { await call("tags_cancel"); toast("Cancelando: termina lo que ya empezó."); }
  else if (act === "apply-sure") { T.confirm = true; renderTagBar(); }
  else if (act === "confirm-no") { T.confirm = false; renderTagBar(); }
  else if (act === "confirm-yes") {
    const items = T.files.filter(f => f.status === "sure" && f.include && f.candidates.length).map(f => ({ path: f.path, candidate: f.candidates[f.sel] }));
    T.confirm = false;
    const r = await call("tags_apply", items, $("#tags-rename").checked);
    if (!r.ok) { renderTagBar(); return toast(r.error || "No se pudo escribir.", true); }
    T.applying = true; T.jobTotal = items.length; T.jobDone = 0;
    items.forEach(i => { tagFile(i.path).status = "writing"; });
    renderTags();
  }
}

/* ---------- news from the program side ---------- */
function onTagEvent(e) {
  if (e.kind === "dropped") return addPaths(e.paths);
  if (e.kind === "finished") {
    T.running = T.applying = false;
    if (e.error) toast(e.error, true); else if (e.cancelled) toast("Cancelado.");
    else if (e.job === "apply") toast(e.failed ? `Listo: ${e.done} escritas, ${e.failed} con problemas.` : `Listo: ${plural(e.done, "canción escrita", "canciones escritas")}.`);
    T.files.forEach(f => { if (f.status === "queued" || f.status === "searching") f.status = "pending"; });
    return renderTags();
  }
  const f = tagFile(e.path);
  if (!f) return;
  if (e.kind === "identifying") f.status = "searching";
  else if (e.kind === "identified") {
    T.jobDone++;
    f.status = e.status; f.error = e.error || ""; f.candidates = e.candidates || []; f.sel = 0; f.prepared = null; f.include = e.status === "sure";
    if (e.tags) f.tags = e.tags;
  } else if (e.kind === "applying") f.status = "writing";
  else if (e.kind === "applied") {
    T.jobDone++;
    f.status = "applied"; f.done = { cover: e.cover, genre: e.genre, problem: e.cover_problem }; f.prepared = null;
    if (e.tags) f.tags = e.tags;
    if (e.new_path && e.new_path !== f.path) { f.path = e.new_path; f.name = baseName(e.new_path); }
    return renderTags();   // the card's identity (its path) may have changed
  } else if (e.kind === "failed") { T.jobDone++; f.status = "failed"; f.error = e.error; f.prepared = null; }
  updateCard(f);
}

let tagPolling = false;
async function pollTagEvents() {
  if (tagPolling) return;
  tagPolling = true;
  try {
    const events = await call("get_tag_events");
    (Array.isArray(events) ? events : []).forEach(onTagEvent);
  } finally { tagPolling = false; }
}

/* ---------- start ---------- */
function initTags() {
  if (T.wiredOnce) return;
  T.wiredOnce = true;
  $("#tags-pick-files").onclick = async () => addPaths(await call("tags_pick_files"));
  $("#tags-pick-folder").onclick = async () => addPaths(await call("tags_pick_folder"));
  $("#tags-search").onclick = searchAll;
  $("#tags-clear").onclick = () => { if (T.running || T.applying) return toast("Espera a que termine o cancela.", true); T.files = []; renderTags(); };
  $("#tags-list").addEventListener("click", onTagsClick);
  $("#tags-list").addEventListener("change", ev => { if (ev.target.dataset.act === "pick" || ev.target.dataset.act === "include") onTagsClick(ev); });
  $("#tags-bar").addEventListener("click", onBarClick);
  try { if (localStorage.getItem("tags-rename") === "0") $("#tags-rename").checked = false; } catch (e) { /* default: on */ }
  $("#tags-rename").onchange = () => {
    try { localStorage.setItem("tags-rename", $("#tags-rename").checked ? "1" : "0"); } catch (e) { /* not remembered */ }
    $$("#tags-list .tcard").forEach(c => { const f = tagFile(c.dataset.path); if (f && f.prepared) updateCard(f); });
  };

  // Files dropped onto the window are picked up by the program side (it knows their paths); the page only has to allow the drop.
  const drop = $("#tags-drop");
  document.addEventListener("dragover", ev => { ev.preventDefault(); drop.classList.toggle("over", S.view === "tags"); });
  document.addEventListener("dragleave", ev => { if (!ev.relatedTarget) drop.classList.remove("over"); });
  document.addEventListener("drop", ev => { ev.preventDefault(); drop.classList.remove("over"); });
  setInterval(pollTagEvents, 500);
  renderTags();
}
