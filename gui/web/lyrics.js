/* The lyrics screen: a panel over the whole window, with the line being sung lit and following the song. Click a line to jump there.
   The lyrics come from the backend (LRCLIB, kept on disk); the user can paste their own. */
const LY = { open: false, id: "", data: null, lines: [], at: -1, timer: 0, userScrolled: 0, editing: false, asking: 0, picking: false };
const lyricOffset = () => (LY.data && LY.data.ok && LY.data.offset) || 0;
const lyricScale = () => (LY.data && LY.data.ok && LY.data.scale) || 1;
// a line sung at second t of the lyrics sounds at second t * scale + offset of the file (scale: the lyrics may run faster than the song)
const lyricToAudio = t => t * lyricScale() + lyricOffset();
const audioToLyric = a => (a - lyricOffset()) / lyricScale();

const lyricsPanel = () => $("#lyrics");

function openLyrics() {
  if (!current()) return;
  LY.open = true;
  const panel = lyricsPanel();
  panel.classList.remove("hidden");
  fitLyrics();
  $("#pl-lyrics").setAttribute("aria-pressed", "true");
  loadLyrics(true);
  clearInterval(LY.timer);
  LY.timer = setInterval(tickLyrics, 120);
  requestAnimationFrame(() => $("#ly-close").focus({ preventScroll: true }));
}

function closeLyrics() {
  if (!LY.open) return;
  LY.open = false; LY.editing = false; LY.picking = false; LY.anchor = null;
  clearInterval(LY.timer);
  lyricsPanel().classList.add("hidden");
  $("#pl-lyrics").setAttribute("aria-pressed", "false");
}

const toggleLyrics = () => (LY.open ? closeLyrics() : openLyrics());

// the panel stops where the bar starts
function fitLyrics() { lyricsPanel().style.bottom = ($("#player").offsetHeight || 0) + "px"; }

/* ---------- asking for the lyrics ---------- */
async function loadLyrics(force) {
  const track = current();
  if (!track || !LY.open) return;
  if (!force && LY.id === track.id && LY.data) return;
  LY.id = track.id; LY.data = null; LY.editing = false; LY.picking = false; LY.anchor = null;
  $("#ly-sync").hidden = true;
  const ask = ++LY.asking;
  paintLyricsHead(track);
  paintLyricsBody("Buscando la letra…", "wait");
  let answer;
  try { answer = await call("lyrics_get", track.id); } catch (e) { answer = { ok: false, error: "No pude pedir la letra." }; }
  if (ask !== LY.asking || !LY.open) return;      // another song, or the panel closed, in the meantime
  LY.data = answer;
  paintLyrics();
}

function paintLyricsHead(track) {
  $("#ly-title").textContent = track.title || "";
  $("#ly-artist").textContent = track.artist || "";
}

function paintLyricsBody(text, kind) {
  LY.lines = []; LY.at = -1; $("#ly-body").classList.remove("editing");
  $("#ly-body").innerHTML = `<p class="ly-note ${kind || ""}">${esc(text)}</p>`;
}

function paintLyrics() {
  const d = LY.data, body = $("#ly-body");
  body.classList.remove("editing");
  $("#ly-edit").hidden = false;
  $("#ly-sync").hidden = !(d && d.ok && d.synced.length);
  const more = $("#ly-version");
  more.hidden = !(d && d.ok && d.synced.length && d.versions > 1);
  if (!more.hidden) { more.textContent = `Otra versión ${d.version + 1}/${d.versions}`; more.title = d.label ? `Esta letra viene de: ${d.label}. Clic para probar la siguiente.` : "Probar la siguiente versión de la letra"; }
  paintLyricOffset();
  if (!d || !d.ok) {
    LY.lines = []; LY.at = -1;
    const none = d && d.none;
    body.innerHTML = `<div class="ly-note"><h3>${none ? "Sin letra todavía" : "No pude traer la letra"}</h3>
      <p class="muted">${esc((d && d.error) || "")}</p>
      <div class="btn-row">${none ? "" : '<button class="btn" id="ly-retry" type="button">Reintentar</button>'}<button class="btn primary" id="ly-paste" type="button">Pegar mi letra</button></div></div>`;
    const retry = $("#ly-retry"); if (retry) retry.onclick = () => loadLyrics(true);
    $("#ly-paste").onclick = editLyrics;
    return;
  }
  if (d.synced.length) {
    LY.lines = d.synced;
    body.innerHTML = '<div class="ly-pad"></div>' + d.synced.map(([t, line], i) => `<div class="ly-line${line ? "" : " gap"}" data-i="${i}" data-t="${t}" tabindex="-1">${esc(line) || "♪"}</div>`).join("") + '<div class="ly-pad"></div>';
    LY.at = -1;
    tickLyrics(true);
  } else {
    LY.lines = []; LY.at = -1;
    body.innerHTML = `<pre class="ly-plain">${esc(d.plain)}</pre><p class="ly-hint muted small">Esta letra no trae tiempos, así que no se mueve sola.</p>`;
  }
}

/* ---------- following the song ---------- */
function lyricLineAt(second) {
  let lo = 0, hi = LY.lines.length - 1, found = -1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (LY.lines[mid][0] <= second) { found = mid; lo = mid + 1; } else hi = mid - 1;
  }
  return found;
}

function tickLyrics(jump) {
  if (!LY.open || !LY.lines.length || !P.decks.length) return;
  const at = lyricLineAt(audioToLyric(deck().el.currentTime + .15));     // a hair early: the eye reads before the ear is done
  if (at === LY.at && jump !== true) return;
  const lines = $$(".ly-line", $("#ly-body"));
  lines.forEach((el, i) => { el.classList.toggle("on", i === at); el.classList.toggle("past", i < at); });
  LY.at = at;
  const el = lines[Math.max(at, 0)], box = $("#ly-body");
  if (!el || (Date.now() - LY.userScrolled < 3000 && jump !== true)) return;   // the reader is looking around: do not fight them
  // the line that plays goes in the middle of the box: with the box as offsetParent (position: relative) offsetTop is measured from its top,
  // and the padding above and below is half the box so even the first and the last lines can reach the middle
  const half = Math.round(box.clientHeight / 2);
  $$(".ly-pad", box).forEach(pad => { if (pad.style.height !== half + "px") pad.style.height = half + "px"; });
  const top = el.offsetTop - half + el.offsetHeight / 2;
  box.scrollTo({ top, behavior: jump === true ? "auto" : "smooth" });
}

/* ---------- the user's own lyrics ---------- */
function editLyrics() {
  const track = current();
  if (!track) return;
  LY.editing = true;
  $("#ly-body").classList.add("editing");
  const manual = LY.data && LY.data.ok && LY.data.manual;
  const text = manual ? (LY.data.synced.length ? LY.data.synced.map(([t, l]) => `[${String(Math.floor(t / 60)).padStart(2, "0")}:${(t % 60).toFixed(2).padStart(5, "0")}]${l}`).join("\n") : LY.data.plain) : (LY.data && LY.data.ok ? LY.data.plain : "");
  $("#ly-body").innerHTML = `<div class="ly-editor"><p class="muted small">Pega la letra. Si trae tiempos tipo <code>[01:23.45]</code> se moverá sola; si no, se verá fija.</p>
    <textarea id="ly-text" spellcheck="false" aria-label="Letra de la canción"></textarea>
    <div class="btn-row"><button class="btn primary" id="ly-save" type="button">Guardar</button><button class="btn" id="ly-cancel" type="button">Cancelar</button>
    ${manual ? '<button class="btn danger" id="ly-remove" type="button">Quitar mi letra</button>' : ""}</div></div>`;
  const field = $("#ly-text");
  field.value = text;
  field.focus();
  const save = async value => {
    const answer = await call("lyrics_save", track.id, value);
    LY.editing = false;
    if (!LY.open || current() === null || current().id !== track.id) return;
    LY.data = value.trim() ? answer : null;
    if (value.trim()) paintLyrics(); else loadLyrics(true);
    if (answer && !answer.ok && value.trim()) toast(answer.error || "No pude guardar la letra.", true);
  };
  $("#ly-save").onclick = () => save(field.value);
  $("#ly-cancel").onclick = () => { LY.editing = false; if (LY.data) paintLyrics(); else loadLyrics(true); };
  const remove = $("#ly-remove"); if (remove) remove.onclick = () => save("");
  field.onkeydown = ev => { if (ev.key === "Escape") { ev.stopPropagation(); $("#ly-cancel").click(); } };
}

/* ---------- matching the lyrics to the file you have ---------- */
// positive: the lyrics run later. Shown with a comma, as the rest of the window writes numbers
const offsetText = value => `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2).replace(".", ",")} s`;

function paintLyricOffset() {
  const value = lyricOffset(), scale = lyricScale(), out = $("#ly-off");
  out.textContent = offsetText(value) + (scale !== 1 ? ` · ×${scale.toFixed(2).replace(".", ",")}` : "");
  out.classList.toggle("set", value !== 0 || scale !== 1);
  out.title = value || scale !== 1 ? "Clic para volver a como venía" : "Desfase y velocidad de esta canción";
}

async function setLyricSync(offset, scale) {
  const track = current();
  if (!track || !LY.data || !LY.data.ok) return;
  const answer = await call("lyrics_sync", track.id, offset, scale);
  if (!answer || !answer.ok) return toast((answer && answer.error) || "No pude ajustar la letra.", true);
  if (!LY.data || current() === null || current().id !== track.id) return;
  LY.data.offset = answer.offset; LY.data.scale = answer.scale;
  paintLyricOffset();
  tickLyrics(true);
}
const setLyricOffset = value => setLyricSync(Math.round(value * 4) / 4, lyricScale());

/* "This is the line I hear now". The first click fixes the shift. A second one, on a line far from the first, also fixes the speed
   (two points make a line): that is what a lyric that runs faster or slower than the song needs. */
function pickLyricLine(lineTime) {
  const heard = deck().el.currentTime - .15, anchor = LY.anchor;
  if (anchor && Math.abs(lineTime - anchor.line) >= 8 && Math.abs(heard - anchor.heard) >= 8) {
    const scale = (heard - anchor.heard) / (lineTime - anchor.line);
    if (scale >= .5 && scale <= 2) {
      setLyricSync(anchor.heard - scale * anchor.line, scale);
      toast(`Listo: la letra va ${scale > 1 ? "más despacio" : "más deprisa"} que antes (×${scale.toFixed(2).replace(".", ",")}).`);
      LY.anchor = null;
      return;
    }
    toast("Esas dos líneas no cuadran con la misma canción. Prueba con otras.", true);
  }
  LY.anchor = { line: lineTime, heard };
  setLyricSync(heard - lyricScale() * lineTime, lyricScale());
  toast("Ajustado. Si más adelante vuelve a descuadrarse, pulsa «Ajustar» otra vez y toca una línea lejos de esta: así también arreglo la velocidad.");
}

async function nextLyricVersion() {
  const track = current();
  if (!track || !LY.data || !LY.data.ok) return;
  const answer = await call("lyrics_version", track.id, (LY.data.version + 1) % LY.data.versions);
  if (!answer || !answer.ok) return toast((answer && answer.error) || "No pude cambiar de versión.", true);
  if (current() === null || current().id !== track.id) return;
  LY.data = answer; LY.anchor = null;
  paintLyrics();
}

function startPicking() {
  LY.picking = true;
  $("#ly-pick").classList.add("on"); $("#ly-body").classList.add("picking");
  toast("Haz clic en la línea que estás oyendo ahora mismo.");
}

function stopPicking() {
  LY.picking = false;
  $("#ly-pick").classList.remove("on"); $("#ly-body").classList.remove("picking");
}

/* ---------- wiring ---------- */
function lyricsTrackChanged() {
  if (!LY.open) return;
  if (!current()) { closeLyrics(); return; }
  loadLyrics(true);
}

function wireLyrics() {
  $("#pl-lyrics").onclick = ev => { ev.stopPropagation(); toggleLyrics(); };
  $("#ly-close").onclick = closeLyrics;
  $("#ly-edit").onclick = editLyrics;
  $("#ly-earlier").onclick = () => setLyricOffset(lyricOffset() - .25);
  $("#ly-later").onclick = () => setLyricOffset(lyricOffset() + .25);
  $("#ly-off").onclick = () => { LY.anchor = null; setLyricSync(0, 1); };
  $("#ly-version").onclick = nextLyricVersion;
  $("#ly-pick").onclick = () => { LY.picking ? stopPicking() : startPicking(); };
  $("#ly-body").addEventListener("click", ev => {
    const line = ev.target.closest(".ly-line");
    if (!line) return;
    if (LY.picking) { pickLyricLine(+line.dataset.t); stopPicking(); return; }   // "this is the line I hear now"
    seek(lyricToAudio(+line.dataset.t)); LY.userScrolled = 0;
  });
  const looked = () => { LY.userScrolled = Date.now(); };
  $("#ly-body").addEventListener("wheel", looked, { passive: true });
  $("#ly-body").addEventListener("touchmove", looked, { passive: true });
  document.addEventListener("keydown", ev => {
    if (ev.key !== "Escape" || !LY.open) return;
    if (LY.editing) return;                        // the editor handles its own Esc
    if (LY.picking) { ev.preventDefault(); ev.stopPropagation(); stopPicking(); return; }
    if ($("#ctx") || !$("#dialog").classList.contains("hidden")) return;
    ev.preventDefault(); ev.stopPropagation(); closeLyrics();
  }, true);
  addEventListener("resize", () => { if (LY.open) fitLyrics(); });
}
