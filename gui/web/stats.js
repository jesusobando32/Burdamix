/* Listening statistics. The player reports a listen after 30 seconds or half of the song (this file counts the time actually heard, so
   pausing or skipping around does not inflate it); the backend keeps them; this screen shows the summary of a week, a month, a year or all. */
const ST = { period: "week", asking: 0 };
const LISTEN = { id: "", seconds: 0, counted: false, last: 0 };

/* ---------- counting what is heard ---------- */
function resetListening() { LISTEN.id = ""; LISTEN.seconds = 0; LISTEN.counted = false; LISTEN.last = 0; }

function countListening(el) {
  const track = current(), now = Date.now();
  if (!track) { resetListening(); return; }
  if (LISTEN.id !== track.id) { resetListening(); LISTEN.id = track.id; }
  const dt = LISTEN.last ? Math.min((now - LISTEN.last) / 1000, 1.5) : 0;    // a gap (the window was asleep) is not listening
  LISTEN.last = now;
  if (el.paused || LISTEN.counted) return;
  LISTEN.seconds += dt;
  const need = Math.min(30, Math.max(5, (isFinite(el.duration) ? el.duration : 60) / 2));
  if (LISTEN.seconds >= need) { LISTEN.counted = true; call("stats_play", track.id, Math.round(LISTEN.seconds)); }
}

/* ---------- the screen ---------- */
const PERIODS = [["week", "Semana"], ["month", "Mes"], ["year", "Año"], ["all", "Siempre"]];

function wireStats() {
  const seg = $("#st-periods");
  seg.addEventListener("click", ev => {
    const b = ev.target.closest("[data-p]");
    if (b && b.dataset.p !== ST.period) { ST.period = b.dataset.p; loadStats(); }
  });
}

async function loadStats() {
  const seg = $("#st-periods");
  $$("button", seg).forEach(b => { b.classList.toggle("on", b.dataset.p === ST.period); b.setAttribute("aria-pressed", b.dataset.p === ST.period); });
  requestAnimationFrame(() => placeInd($(".seg-ind", seg), $("button.on", seg), false));
  const ask = ++ST.asking;
  let data;
  try { data = await call("stats_summary", ST.period); } catch (e) { data = null; }
  if (ask !== ST.asking) return;
  paintStats(data);
}

const hoursText = seconds => {
  const h = Math.floor(seconds / 3600), m = Math.round(seconds % 3600 / 60);
  return h ? `${h} h ${m} min` : seconds ? `${Math.max(1, m)} min` : "0 min";
};

function paintStats(d) {
  const body = $("#st-body");
  if (!d) { body.innerHTML = '<div class="panel bad"><div class="panel-body"><h3>No pude leer las estadísticas</h3><p class="muted">Cierra y abre la ventana e inténtalo otra vez.</p></div></div>'; return; }
  if (!d.plays) {
    body.innerHTML = `<div class="panel"><div class="panel-ic">${ICONS.search}</div><div class="panel-body"><h3>${ST.period === "all" ? "Todavía no hay escuchas" : "Nada escuchado en este periodo"}</h3>
      <p class="muted">Lo que escuches en la Biblioteca se cuenta aquí. Una canción cuenta cuando la oyes 30 segundos o la mitad. Todo se queda en tu ordenador.</p></div></div>`;
    return;
  }
  const top = d.artists[0];
  const tiles = [["Escuchas", String(d.plays)], ["Tiempo", hoursText(d.seconds)], ["Racha", d.streak ? plural(d.streak, "día", "días") : "—"], ["Artista del periodo", top ? top.artist : "—"]];
  const max = Math.max(1, ...d.series.map(b => b.minutes));
  const dense = d.series.length > 14;
  const bars = d.series.map(b => `<div class="st-bar${b.minutes ? "" : " none"}" title="${esc(b.label)} · ${b.minutes ? hoursText(b.minutes * 60) : "nada"}">
      <i style="height:${Math.max(b.minutes ? 4 : 2, b.minutes / max * 100)}%"></i><span${dense ? ' class="thin"' : ""}>${esc(b.label)}</span></div>`).join("");
  const list = (title, rows, line, play) => `<section class="st-list"><h3>${title}</h3>${rows.length ? "<ol>" + rows.map((r, i) => `<li${play && play(r) ? ` data-id="${esc(play(r))}" tabindex="0" role="button"` : ""}>
      <span class="st-n">${i + 1}</span><span class="st-name">${line(r)}</span><span class="st-c">${plural(r.plays, "vez", "veces")}</span></li>`).join("") + "</ol>" : '<p class="muted small">Sin datos.</p>'}</section>`;
  body.innerHTML = `<div class="st-tiles">${tiles.map(([k, v]) => `<div class="st-tile"><span class="muted small">${k}</span><b>${esc(v)}</b></div>`).join("")}</div>
    <section class="st-chart" aria-label="Minutos escuchados"><h3>Minutos escuchados</h3><div class="st-bars${dense ? " dense" : ""}" role="img" aria-label="${esc(`${hoursText(d.seconds)} en total`)}">${bars}</div></section>
    <div class="st-lists">
      ${list("Canciones más escuchadas", d.songs, r => `<b>${esc(r.title)}</b><small class="muted">${esc(r.artist)}</small>`, r => r.id)}
      ${list("Artistas", d.artists, r => `<b>${esc(r.artist)}</b><small class="muted">${esc(hoursText(r.seconds))}</small>`)}
      ${list("Álbumes", d.albums, r => `<b>${esc(r.album)}</b><small class="muted">${esc(r.artist)}</small>`)}
    </div>`;
  // the library may not have been opened yet in this run: load it first, then play
  const play = async el => { const id = el.dataset.id; if (!id) return; if (!P.byId.has(id)) await loadLibrary(); if (P.byId.has(id)) playList([id]); };
  $$(".st-list li[data-id]", body).forEach(li => { li.onclick = () => play(li); li.onkeydown = ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); play(li); } }; });
}
