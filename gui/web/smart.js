/* Smart playlists: rules instead of songs. The backend works the songs out (collections_get answers L.smart with their ids); this file
   is the editor of the rules and the small text that tells what a smart playlist does. Uses crate.js (L, refreshCollections) and app.js. */
const SMART_FIELDS = {
  artist: ["Artista", "text"], album: ["Álbum", "text"], title: ["Título", "text"], liked: ["Me gusta", "bool"],
  duration_min: ["Duración (min)", "number"], added_days: ["Añadida hace (días)", "number"], plays: ["Escuchas", "number"], last_played_days: ["Escuchada hace (días)", "number"],
};
const SMART_OPS = { text: [["contains", "contiene"], ["is", "es"], ["not_contains", "no contiene"]], number: [["gt", "más de"], ["lt", "menos de"], ["eq", "exactamente"]], bool: [["is", "es"]] };
const SMART_SORTS = [["recent", "Más recientes primero"], ["oldest", "Más antiguas primero"], ["plays", "Más escuchadas primero"], ["title", "Por título"], ["artist", "Por artista"], ["random", "Al azar"]];
const ICON_BOLT = '<svg viewBox="0 0 24 24"><path d="M13 3 5 14h6l-1 7 8-11h-6z"/></svg>';

/* What a smart playlist does, in a sentence the detail page shows. */
function describeSmart(def) {
  const rule = r => {
    const [label, kind] = SMART_FIELDS[r.field] || [r.field, "text"];
    if (kind === "bool") return `${label}: ${r.value ? "sí" : "no"}`;
    const op = (SMART_OPS[kind].find(o => o[0] === r.op) || [0, r.op])[1];
    return `${label} ${op} ${r.value}`;
  };
  const sort = (SMART_SORTS.find(s => s[0] === def.sort) || [0, ""])[1].toLowerCase();
  const rules = def.rules.length ? `Cumple ${def.match === "all" ? "todo esto" : "al menos una"}: ${def.rules.map(rule).join(" · ")}.` : "Todas las canciones.";
  return `${rules} ${sort[0].toUpperCase() + sort.slice(1)}${def.limit ? `, hasta ${def.limit}` : ""}.`;
}

/* ---------- the editor ---------- */
function ruleRowHTML(r) {
  const [, kind] = SMART_FIELDS[r.field];
  const fields = Object.entries(SMART_FIELDS).map(([k, [label]]) => `<option value="${k}"${k === r.field ? " selected" : ""}>${label}</option>`).join("");
  const ops = SMART_OPS[kind].map(([k, label]) => `<option value="${k}"${k === r.op ? " selected" : ""}>${label}</option>`).join("");
  const value = kind === "bool"
    ? `<select class="sm-value" aria-label="Valor"><option value="true"${r.value === true ? " selected" : ""}>sí</option><option value="false"${r.value === false ? " selected" : ""}>no</option></select>`
    : `<input class="sm-value" type="${kind === "number" ? "number" : "text"}" ${kind === "number" ? 'min="0" step="any" inputmode="decimal"' : 'maxlength="100"'} value="${esc(r.value)}" aria-label="Valor" autocomplete="off">`;
  return `<div class="sm-rule"><select class="sm-field" aria-label="Campo">${fields}</select><select class="sm-op" aria-label="Condición">${ops}</select>${value}
    <button class="icon-btn sm-del" type="button" aria-label="Quitar la regla" title="Quitar la regla"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>`;
}

const newRule = () => ({ field: "artist", op: "contains", value: "" });
const defaultValue = kind => (kind === "bool" ? true : kind === "number" ? 1 : "");

function openSmartEditor(existing = null) {
  const box = $("#smart-dialog");
  if (!box.classList.contains("hidden")) return;
  const def = existing ? { ...existing, rules: existing.rules.map(r => ({ ...r })) } : { name: "", match: "all", rules: [newRule()], sort: "recent", limit: 0 };
  box.innerHTML = `<div class="dialog-card sm-card"><h3>${existing ? "Editar playlist inteligente" : "Nueva playlist inteligente"}</h3>
    <p class="muted small">Se actualiza sola: las canciones se eligen cada vez que la abres.</p>
    <input id="sm-name" class="dialog-input" type="text" maxlength="80" autocomplete="off" spellcheck="false" placeholder="Nombre" aria-label="Nombre" value="${esc(def.name)}">
    <div class="sm-match">Cumplir <select id="sm-match" aria-label="Cuántas reglas"><option value="all">todas las reglas</option><option value="any">cualquiera de las reglas</option></select></div>
    <div id="sm-rules" class="sm-rules"></div>
    <button class="btn small-btn" id="sm-add" type="button">+ Añadir regla</button>
    <div class="sm-order"><label>Orden <select id="sm-sort">${SMART_SORTS.map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></label>
      <label>Máximo <input id="sm-limit" type="number" min="0" max="500" step="1" inputmode="numeric" placeholder="sin límite" aria-label="Máximo de canciones"></label></div>
    <p class="sm-error" id="sm-error" role="alert" hidden></p>
    <div class="btn-row"><button class="btn" id="sm-cancel" type="button">Cancelar</button><button class="btn primary" id="sm-save" type="button">Guardar</button></div></div>`;
  $("#sm-match").value = def.match; $("#sm-sort").value = def.sort; $("#sm-limit").value = def.limit || "";
  const redraw = () => {
    $("#sm-rules").innerHTML = def.rules.map(ruleRowHTML).join("") || '<p class="muted small">Sin reglas: entran todas las canciones.</p>';
    $$(".sm-rule", box).forEach((row, i) => {
      const r = def.rules[i];
      $(".sm-field", row).onchange = ev => { r.field = ev.target.value; const kind = SMART_FIELDS[r.field][1]; r.op = SMART_OPS[kind][0][0]; r.value = defaultValue(kind); redraw(); };
      $(".sm-op", row).onchange = ev => { r.op = ev.target.value; };
      $(".sm-value", row).oninput = ev => { r.value = SMART_FIELDS[r.field][1] === "bool" ? ev.target.value === "true" : ev.target.value; };
      $(".sm-value", row).onchange = $(".sm-value", row).oninput;
      $(".sm-del", row).onclick = () => { def.rules.splice(i, 1); redraw(); };
    });
    $("#sm-add").disabled = def.rules.length >= 12;
  };
  redraw();
  const close = () => { box.classList.add("hidden"); box.innerHTML = ""; document.removeEventListener("keydown", onKey, true); };
  const onKey = ev => { if (ev.key === "Escape") { ev.preventDefault(); ev.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
  $("#sm-add").onclick = () => { def.rules.push(newRule()); redraw(); const last = $$(".sm-value", box).pop(); if (last) last.focus(); };
  $("#sm-cancel").onclick = close;
  box.onclick = ev => { if (ev.target === box) close(); };
  $("#sm-save").onclick = async () => {
    const payload = { name: $("#sm-name").value.trim(), match: $("#sm-match").value, sort: $("#sm-sort").value, limit: Math.max(0, Math.round(Number($("#sm-limit").value) || 0)),
      rules: def.rules.map(r => ({ ...r, value: SMART_FIELDS[r.field][1] === "number" ? (r.value === "" ? "" : Number(r.value)) : r.value })) };
    const answer = await call("smart_save", payload, existing ? existing.id : null);
    if (!answer || !answer.ok) { const err = $("#sm-error"); err.textContent = (answer && answer.error) || "No pude guardar la playlist inteligente."; err.hidden = false; return; }
    close();
    await refreshCollections();
    toast(`Playlist inteligente «${payload.name}» ${existing ? "guardada" : "creada"}.`, false, { label: "Abrir", run: () => { L.tab = "playlists"; L.open = "smart:" + answer.id; P.q = ""; $("#lib-q").value = ""; show("library"); renderLibrary(); } });
  };
  box.classList.remove("hidden");
  $("#sm-name").focus();
}

async function deleteSmart(group) {
  const sure = await confirmDialog({ title: `¿Eliminar «${group.title}»?`, text: "Solo se borran las reglas; tus canciones no se tocan.", ok: "Eliminar", danger: true });
  if (!sure) return;
  const answer = await call("smart_delete", group.sid);
  if (!answer || !answer.ok) return toast((answer && answer.error) || "No pude eliminarla.", true);
  closeGroup();
  await refreshCollections();
  toast("Playlist inteligente eliminada.");
}
