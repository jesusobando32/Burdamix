/* Sharing playlists between people who have the app: the share window (a code to copy, a card picture, a .m3u8) and the import window
   (paste a code or drop a card, see what you have and what you lack, create the playlist). The backend does the coding and the matching
   (share.py); this file is only the two windows. Uses crate.js (L, refreshCollections) and app.js ($, esc, call, toast, show, submitLink). */
const ICON_SHARE = '<svg viewBox="0 0 24 24"><path d="M12 15V3M8 7l4-4 4 4M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>';
const ICON_IMPORT = '<svg viewBox="0 0 24 24"><path d="M12 3v12M8 11l4 4 4-4M5 17v2a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2"/></svg>';

const anyDialogOpen = () => ["#smart-dialog", "#share-dialog", "#import-dialog"].some(id => !$(id).classList.contains("hidden"));

function shareName() { try { return localStorage.getItem("shareName") || ""; } catch (e) { return ""; } }
function rememberShareName(value) { try { localStorage.setItem("shareName", value); } catch (e) { /* not remembered */ } }

/* Opens a window of this file in `box`; Esc and a click outside close it. Answers the function that closes it. */
function openShareBox(box, html) {
  box.innerHTML = html;
  box.classList.remove("hidden");
  const close = () => { box.classList.add("hidden"); box.innerHTML = ""; document.removeEventListener("keydown", onKey, true); box.onclick = null; };
  const onKey = ev => { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
  box.onclick = ev => { if (ev.target === box) close(); };
  return close;
}

async function copyToClipboard(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { /* the old way below */ }
  const field = document.createElement("textarea");
  field.value = text; field.style.position = "fixed"; field.style.opacity = "0";
  document.body.append(field); field.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
  field.remove();
  return ok;
}

/* ---------- share ---------- */
function openShare(group) {
  const box = $("#share-dialog");
  if (!box.classList.contains("hidden") || !group.ids.length) return;
  const close = openShareBox(box, `<div class="dialog-card sh-card"><h3>Compartir «${esc(group.title)}»</h3>
    <p class="muted small">${plural(group.count, "canción", "canciones")}. Tu amigo necesita Burdamix: recibe los nombres, no los archivos.</p>
    <label class="sh-field">Tu nombre en la tarjeta (opcional)<input id="sh-by" class="dialog-input" type="text" maxlength="40" autocomplete="off" spellcheck="false" placeholder="Por ejemplo, Yisus"></label>
    <div class="sh-qr" id="sh-qr" aria-live="polite"></div>
    <p class="sh-error" id="sh-error" role="alert" hidden></p>
    <div class="sh-actions"><button class="btn primary" id="sh-copy" type="button">Copiar código</button><button class="btn" id="sh-card" type="button">Guardar tarjeta con QR</button><button class="btn" id="sh-m3u" type="button">Para otros reproductores (.m3u8)</button></div>
    <p class="muted small sh-tip">La tarjeta es una imagen: mándala como <b>archivo</b> o documento. Si el chat la convierte en foto pierde el código; en ese caso manda el código de texto.</p>
    <div class="btn-row"><button class="btn" id="sh-close" type="button">Cerrar</button></div></div>`);
  const by = $("#sh-by"), qr = $("#sh-qr"), err = $("#sh-error");
  let code = "";                                    // the code is long and meant for machines: it is never shown, only copied
  by.value = shareName();
  let ask = 0, timer = 0;
  const refresh = async () => {
    const mine = ++ask;
    const made = await call("share_make", group.ids, group.title, by.value);
    if (mine !== ask) return;
    err.hidden = !!made.ok; err.textContent = made.ok ? "" : (made.error || "No pude preparar el código.");
    code = made.ok ? made.code : "";
    paintShareQr(qr, made);
    $("#sh-copy").disabled = !made.ok;
    $("#sh-card").title = made.ok && !made.qr ? "La lista es muy grande para un QR: la tarjeta lleva el código dentro y lo explica" : "";
  };
  by.oninput = () => { rememberShareName(by.value); clearTimeout(timer); timer = setTimeout(refresh, 250); };
  $("#sh-copy").onclick = async () => toast(await copyToClipboard(code) ? "Código copiado. Pégalo en un chat." : "No pude copiarlo: selecciónalo y copia a mano.", false);
  $("#sh-card").onclick = async () => {
    const answer = await call("share_card_save", group.ids, group.title, by.value);
    if (answer && answer.ok) toast("Tarjeta guardada. Mándala como archivo.", false, { label: "Ver carpeta", run: () => call("open_folder", answer.path.replace(/[\/][^\/]*$/, "")) });
    else if (answer && !answer.cancelled) toast((answer && answer.error) || "No pude guardar la tarjeta.", true);
  };
  $("#sh-m3u").onclick = async () => {
    const answer = await call("playlist_export_m3u", group.ids, group.title);
    if (answer && answer.ok) toast("Lista guardada. Solo sirve en este ordenador: lleva rutas de tus archivos.");
    else if (answer && !answer.cancelled) toast((answer && answer.error) || "No pude guardar la lista.", true);
  };
  $("#sh-close").onclick = close;
  refresh();
  $("#sh-copy").focus();
}

/* The QR of the playlist, drawn in its own colours (the backend picks a dark and a pale shade of the covers that a camera can still read).
   Click it to make it bigger. */
function paintShareQr(box, made) {
  if (!made.ok) { box.innerHTML = ""; return; }
  box.style.setProperty("--tone", made.tone); box.style.setProperty("--qr-light", made.light);
  if (!made.qr_uri) {
    box.innerHTML = '<p class="sh-noqr">Esta playlist es demasiado grande para un QR. Usa «Copiar código» o la tarjeta.</p>';
    return;
  }
  box.innerHTML = `<button type="button" class="sh-qr-plate" title="Clic para ampliar o reducir" aria-label="Código QR de la playlist. Clic para ampliar"><img alt="" src="${made.qr_uri}"></button>
    <p class="muted small">Escanéalo con el móvil: sale el código para pegarlo en Burdamix.</p>`;
  $(".sh-qr-plate", box).onclick = () => box.classList.toggle("big");
}

/* ---------- import ---------- */
function openImport() {
  const box = $("#import-dialog");
  if (!box.classList.contains("hidden")) return;
  const close = openShareBox(box, `<div class="dialog-card sh-card"><h3>Importar una playlist</h3>
    <p class="muted small">Pega el código que te mandaron, o arrastra aquí la tarjeta (imagen) o elígela.</p>
    <div class="sh-drop" id="im-drop"><textarea id="im-code" rows="4" spellcheck="false" placeholder="BURDAMIX1:…" aria-label="Código de la playlist"></textarea>
      <button class="btn small-btn" id="im-file" type="button">Elegir tarjeta…</button></div>
    <p class="sh-error" id="im-error" role="alert" hidden></p>
    <div id="im-result"></div>
    <div class="btn-row"><button class="btn" id="im-close" type="button">Cancelar</button><button class="btn primary" id="im-make" type="button" disabled>Crear playlist</button></div></div>`);
  const code = $("#im-code"), err = $("#im-error"), result = $("#im-result"), make = $("#im-make");
  let found = null, ask = 0;
  const showResult = answer => {
    found = answer && answer.ok ? answer : null;
    err.hidden = !!found || !answer; err.textContent = found || !answer ? "" : (answer.error || "No pude leer eso.");
    make.disabled = !found || !found.ids.length;
    make.textContent = found ? (found.ids.length ? `Crear con las ${found.ids.length} que tengo` : "No tengo ninguna") : "Crear playlist";
    if (!found) { result.innerHTML = ""; return; }
    const lack = found.missing;
    result.innerHTML = `<div class="im-summary"><b>${esc(found.name)}</b>${found.by ? `<span class="muted"> · de ${esc(found.by)}</span>` : ""}
      <p class="muted small">Tienes <b>${found.ids.length}</b> de ${found.total} canciones${lack.length ? ` y te ${lack.length === 1 ? "falta 1" : `faltan ${lack.length}`}.` : ". ¡Las tienes todas!"}</p></div>
      ${lack.length ? `<ul class="im-missing" aria-label="Canciones que te faltan">${lack.map(([a, t], i) => `<li><span><b>${esc(t)}</b><small class="muted">${esc(a)}</small></span><button class="btn small-btn" type="button" data-i="${i}">Buscar</button></li>`).join("")}</ul>` : ""}`;
    $$(".im-missing button", result).forEach(b => b.onclick = () => { const [a, t] = lack[+b.dataset.i]; close(); show_home_search(`${a} ${t}`); });
  };
  const readCode = async text => { const mine = ++ask; const answer = await call("share_read", text); if (mine === ask) showResult(answer); };
  let timer = 0;
  code.oninput = () => { clearTimeout(timer); if (!code.value.trim()) { showResult(null); return; } timer = setTimeout(() => readCode(code.value), 250); };
  $("#im-file").onclick = async () => { const answer = await call("share_read_file"); if (answer && answer.cancelled) return; code.value = ""; showResult(answer); };
  const drop = $("#im-drop");
  drop.ondragover = ev => { ev.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = ev => {
    ev.preventDefault(); ev.stopPropagation(); drop.classList.remove("over");
    const file = ev.dataTransfer && ev.dataTransfer.files && ev.dataTransfer.files[0];
    if (!file) return;
    if (file.size > 30e6) return showResult({ ok: false, error: "Ese archivo es demasiado grande para ser una tarjeta." });
    const reader = new FileReader();
    reader.onload = async () => { code.value = ""; showResult(await call("share_read_picture", String(reader.result).split(",")[1] || "")); };
    reader.readAsDataURL(file);
  };
  make.onclick = async () => {
    if (!found || !found.ids.length) return;
    make.disabled = true;
    const created = await call("playlist_create", found.name, found.ids);
    if (!created || !created.ok) { make.disabled = false; err.hidden = false; err.textContent = (created && created.error) || "No pude crear la playlist."; return; }
    close();
    await refreshCollections();
    toast(`Playlist «${found.name}» creada con ${plural(found.ids.length, "canción", "canciones")}.`, false,
      { label: "Abrir", run: () => { L.tab = "playlists"; L.open = "mine:" + created.id; P.q = ""; $("#lib-q").value = ""; show_view("library"); renderLibrary(); } });
  };
  $("#im-close").onclick = close;
  code.focus();
}

const show_view = view => show(view);
function show_home_search(text) { show("home"); $("#link").value = text; if (typeof syncClear === "function") syncClear(); submitLink(); }
