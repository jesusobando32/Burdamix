/* Phone layout (window narrower than 761 px). It adds what only the phone has: the tab bar with the download button in the middle,
   a start page (last songs and albums, search bar, the week), a "More" page, and the full-screen player that opens from the small
   bar. The rest is the same program: the same views, the same player and the same vinyl, restyled by mobile.css. */
(() => {
  const mq = matchMedia("(max-width: 760px)");
  const calm = matchMedia("(prefers-reduced-motion: reduce)");
  const app = document.getElementById("app");
  const player = document.getElementById("player");
  const q = (s, r = document) => r.querySelector(s);
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html) e.innerHTML = html; return e; };

  const ic = {
    start: '<svg viewBox="0 0 24 24"><path d="M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z"/></svg>',
    lib: '<svg viewBox="0 0 24 24"><path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/></svg>',
    dl: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 11l5 5 5-5M5 20h14"/></svg>',
    heart: '<svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>',
    more: '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.6" class="fill"/><circle cx="12" cy="12" r="1.6" class="fill"/><circle cx="19" cy="12" r="1.6" class="fill"/></svg>',
    search: '<svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
    arrow: '<svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    shuffle: '<svg viewBox="0 0 24 24"><path d="M3 7h3.5c5 0 5 10 10 10H21M3 17h3.5c1.7 0 2.9-.9 3.8-2.2M21 7h-4.5c-1.7 0-2.9.9-3.8 2.2M18 4l3 3-3 3M18 14l3 3-3 3"/></svg>',
    chart: '<svg viewBox="0 0 24 24"><path d="M5 20V10M12 20V4M19 20v-7"/></svg>',
    tag: '<svg viewBox="0 0 24 24"><path d="M3 12V4h8l9 9-8 8z"/><circle cx="7.5" cy="8.5" r="1"/></svg>',
    gear: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9L7 7M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/></svg>',
    book: '<svg viewBox="0 0 24 24"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v15H5.5A1.5 1.5 0 0 0 4 20.5zM20 5.5A1.5 1.5 0 0 0 18.5 4H13v15h5.5a1.5 1.5 0 0 1 1.5 1.5z"/></svg>',
    help: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5M12 17h.01"/></svg>',
    chev: '<svg viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>',
    down: '<svg viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
  };

  /* ---------- the tab bar ---------- */
  const TABS = [["start", "Inicio", ic.start], ["library", "Biblioteca", ic.lib], ["dl", "Descargar canciones", ic.dl], ["likes", "Me gusta", ic.heart], ["more", "Más", ic.more]];
  const bar = el("nav", "", TABS.map(([k, name, icon]) => k === "dl"
    ? `<button type="button" class="fab" data-tab="dl" aria-label="${name}">${icon}</button>`
    : `<button type="button" class="tab" data-tab="${k}">${icon}<span>${name}</span></button>`).join(""));
  bar.id = "tabbar"; bar.setAttribute("aria-label", "Navegación");
  app.append(bar);

  const toLibrary = tab => {
    if (S.view === "library") showTab(tab);
    else { L.tab = tab; L.open = null; show("library"); }
  };
  bar.addEventListener("click", ev => {
    const b = ev.target.closest("[data-tab]");
    if (!b) return;
    const k = b.dataset.tab;
    if (k === "start") show("start");
    else if (k === "dl") { if (S.view === "home" && (S.cur || q("#link").value)) clearSearch(); else show("home"); }
    else if (k === "more") show("more");
    else if (k === "likes") toLibrary("likes");
    else if (S.view === "library" && L.tab !== "likes") libraryHome();
    else toLibrary(L.tab === "likes" ? "albums" : L.tab);
    paintTabs();
  });

  function paintTabs() {
    const on = S.view === "start" ? "start" : S.view === "home" ? "dl" : S.view === "library" ? (L.tab === "likes" ? "likes" : "library") : "more";
    bar.querySelectorAll("[data-tab]").forEach(b => b.classList.toggle("on", b.dataset.tab === on));
  }
  q("#lib-tabs").addEventListener("click", () => setTimeout(paintTabs, 0));

  /* ---------- the start page ---------- */
  const greeting = () => { const h = new Date().getHours(); return h < 6 ? "Buenas noches" : h < 13 ? "Buenos días" : h < 20 ? "Buenas tardes" : "Buenas noches"; };
  const card = (t, extra = "") => `<button type="button" class="ms-card" data-play="${esc(t.id)}"><span class="ms-cov">${sleeveArt(t)}${extra}</span><b>${esc(t.title)}</b><small>${esc(t.artist || "Artista desconocido")}</small></button>`;
  const sleeve = g => `<button type="button" class="ms-card ms-sleeve" data-album="${esc(g.key)}"><span class="ms-wrap"><i class="ms-rec"${g.cover && g.cover.cover_url ? ` style="--cover:url('${esc(g.cover.cover_url)}')"` : ""}></i><span class="ms-cov">${sleeveArt(g.cover)}</span></span><b>${esc(g.title)}</b><small>${esc(g.artist)}</small></button>`;
  let listed = [], tries = 0;

  function renderStart() {
    const box = q("#start-scroll");
    const loading = !P.ready;
    if (!loading && P.tracks.length) buildGroups();
    const recent = P.recent.map(trackOf).filter(Boolean);
    const fresh = [...P.tracks].sort((a, b) => b.added - a.added);
    const songs = (recent.length ? recent : fresh).slice(0, 12);
    listed = songs.map(t => t.id);
    const albums = [], seen = new Set();
    for (const t of (recent.length ? recent : fresh)) {
      const g = t.kind === "album" && t.group && L.byKey.get("album:" + t.group);
      if (g && !seen.has(g.key)) { seen.add(g.key); albums.push(g); }
      if (albums.length >= 8) break;
    }
    const empty = !loading && !P.tracks.length;
    box.innerHTML = `
      <div class="ms-top ms-in"><span class="ms-logo"><img src="logo.png" alt=""></span><div class="ms-hi"><small>${greeting()}</small><b>Burdamix</b></div>
        <button type="button" class="ms-round" data-go="stats" aria-label="Estadísticas">${ic.chart}</button></div>
      <button type="button" class="ms-search ms-in" style="--k:1" data-go="search">${ic.search}<span>Buscar o pegar un enlace…</span><i>${ic.arrow}</i></button>
      <div class="ms-chips ms-in" style="--k:2">
        <button type="button" class="ms-chip" data-act="shuffle">${ic.shuffle}Aleatorio</button>
        <button type="button" class="ms-chip" data-go="likes">${ic.heart}Me gusta</button>
        <button type="button" class="ms-chip" data-go="home">${ic.dl}Descargar</button></div>
      ${loading ? '<div class="ms-wait ms-in" style="--k:3"><i></i><i></i><i></i></div>' : empty ? `
      <div class="ms-empty ms-in" style="--k:3"><b>Aún no tienes canciones</b><p>Pulsa el botón de descarga, busca una canción o pega un enlace de Spotify, y aquí aparecerá lo que escuches.</p></div>` : `
      <div class="ms-sec ms-in" style="--k:3"><h2>${recent.length ? "Seguir escuchando" : "Añadidas hace poco"}</h2><button type="button" data-go="library">Ver todo</button></div>
      <div class="ms-hs ms-in" style="--k:4">${songs.map(t => card(t)).join("")}</div>
      ${albums.length ? `<div class="ms-sec ms-in" style="--k:5"><h2>${recent.length ? "Álbumes recientes" : "Álbumes"}</h2><button type="button" data-go="albums">Ver todo</button></div>
      <div class="ms-hs ms-in" style="--k:6">${albums.map(sleeve).join("")}</div>` : ""}
      <div id="ms-week"></div>`}`;
    if (loading && tries++ < 60) setTimeout(() => { if (S.view === "start") renderStart(); }, 400);
    if (!loading && !empty) paintWeek();
  }

  async function paintWeek() {
    let d = null;
    try { d = await call("stats_summary", "week"); } catch (e) { return; }
    const slot = q("#ms-week");
    if (!d || !d.plays || !slot) return;
    const max = Math.max(1, ...d.series.map(b => b.minutes));
    slot.innerHTML = `<div class="ms-sec ms-in" style="--k:7"><h2>Tu semana</h2></div>
      <button type="button" class="ms-week ms-in" style="--k:8" data-go="stats"><span class="muted small">Tiempo escuchado</span>
        <b>${esc(hoursText(d.seconds))}</b><span class="muted small">${esc(plural(d.plays, "escucha", "escuchas"))}${d.streak ? " · racha de " + esc(plural(d.streak, "día", "días")) : ""}</span>
        <span class="ms-bars" aria-hidden="true">${d.series.map((b, i) => `<i style="--h:${Math.max(6, b.minutes / max * 100)}%;--k:${i}"></i>`).join("")}</span></button>`;
  }

  q("#start-scroll").addEventListener("click", ev => {
    const t = ev.target.closest("[data-play],[data-album],[data-go],[data-act]");
    if (!t) return;
    if (t.dataset.play) playList(listed, t.dataset.play);
    else if (t.dataset.album) { L.tab = "albums"; L.open = null; show("library"); openGroup(t.dataset.album); }
    else if (t.dataset.act === "shuffle") { const ids = shuffled(P.tracks.map(x => x.id)); if (ids.length) playList(ids); else toast("Todavía no hay canciones en la biblioteca."); }
    else if (t.dataset.go === "search") { show("home"); setTimeout(() => q("#link").focus(), 200); }
    else if (t.dataset.go === "likes") toLibrary("likes");
    else if (t.dataset.go === "albums") toLibrary("albums");
    else if (t.dataset.go === "library") toLibrary(L.tab === "likes" ? "albums" : L.tab);
    else show(t.dataset.go);
  });

  /* ---------- the "More" page ---------- */
  const MORE = [
    [ic.heart, "Mis favoritos de Spotify", "Tus «Me gusta» de Spotify para bajarlos", "favorites"],
    [ic.chart, "Estadísticas", "Tiempo escuchado, racha y lo más oído", "stats"],
    [ic.tag, "Completar etiquetas", "Título, álbum, año y portada de tus archivos", "tags"],
    [ic.gear, "Configuración", "Carpeta, calidad y nombre de los archivos", "settings"],
    [ic.book, "Tutorial · Iniciar sesión", "Conecta Burdamix con Spotify", "tutorial"],
    [ic.help, "Preguntas frecuentes", "Las dudas más comunes", "faq"],
  ];
  function renderMore() {
    const row = ([icon, name, sub, view]) => `<button type="button" class="ms-item" data-go="${view}"><i class="ms-ic">${icon}</i><span>${name}<small>${sub}</small></span>${ic.chev}</button>`;
    const version = S.state && S.state.version ? `Burdamix ${esc(S.state.version)}` : "Burdamix";
    q("#more-scroll").innerHTML = `<h1 class="ms-title ms-in">Más</h1>
      <div class="ms-list ms-in" style="--k:1">${MORE.slice(0, 3).map(row).join("")}</div>
      <div class="ms-list ms-in" style="--k:2">${MORE.slice(3).map(row).join("")}</div>
      <p class="muted small ms-foot">${version}</p>`;
  }
  q("#more-scroll").addEventListener("click", ev => { const b = ev.target.closest("[data-go]"); if (b) show(b.dataset.go); });

  /* ---------- show(): fill the two phone-only pages and light the tab ---------- */
  const plainShow = window.show;
  const cameFrom = {};                       // the screen each one was opened from, for the way back
  window.show = view => {
    const before = S.view;
    plainShow(view);
    if (view !== before) cameFrom[view] = before;
    if (view === "start") renderStart();
    if (view === "more") renderMore();
    paintTabs();
  };

  /* ---------- the full-screen player ---------- */
  const head = el("div", "mp-head", `<button type="button" class="icon-btn" id="mp-close" aria-label="Cerrar el reproductor">${ic.down}</button>
    <div class="mp-ctx"><small>Reproduciendo desde</small><b id="mp-ctx">Biblioteca</b></div><span></span>`);
  const stage = el("div", "mp-stage");
  const scrim = el("div", "mp-scrim");
  const line = el("i", "mp-line");
  line.setAttribute("aria-hidden", "true"); stage.setAttribute("aria-hidden", "true");
  player.prepend(head, stage);
  player.append(scrim, line);
  const now = q(".pl-now", player);
  now.setAttribute("role", "button"); now.setAttribute("tabindex", "0"); now.setAttribute("aria-label", "Abrir el reproductor");

  const isFull = () => player.classList.contains("full");
  function fit() {
    const w = innerWidth, h = innerHeight;
    let top = 0;
    if (isFull()) top = now.getBoundingClientRect().top;
    const from = isFull() ? stage.getBoundingClientRect().top : 66;
    const room = (top || h - 300) - from - 10;
    const s = Math.max(.5, Math.min(.9, (w - 56) / 360, room / 360));
    app.style.setProperty("--ms", s.toFixed(3));
    if (top) {
      app.style.setProperty("--mp-ctl", Math.ceil(h - top + 4) + "px");
      app.style.setProperty("--mt", Math.round(from + Math.max(0, room - 360 * s) / 2) + "px");     // the record sits in the middle of the free space
    }
  }
  function openFull() {
    if (!mq.matches || isFull() || player.classList.contains("hidden")) return;
    player.classList.add("full"); app.classList.add("mfull");
    fit(); requestAnimationFrame(fit);
  }
  function closeFull(now = false) {
    if (!isFull()) return;
    closePanels(); closeLyrics(); closeLyrics();
    const done = () => { player.classList.remove("full", "closing"); app.classList.remove("mfull"); app.style.removeProperty("--mdy"); };
    if (now || calm.matches) return done();
    player.classList.add("closing");
    let finished = false;
    const end = () => { if (!finished) { finished = true; done(); } };
    player.addEventListener("animationend", end, { once: true });
    setTimeout(end, 450);
  }
  q("#mp-close").onclick = () => closeFull();
  player.addEventListener("click", ev => {
    if (!mq.matches || isFull() || ev.target.closest("button, input, a")) return;
    openFull();
  });
  now.addEventListener("keydown", ev => { if ((ev.key === "Enter" || ev.key === " ") && !isFull() && ev.target === now) { ev.preventDefault(); openFull(); } });
  addEventListener("keydown", ev => {
    if (ev.key !== "Escape" || !isFull() || LY.open || q("#ctx")) return;
    if (!q("#pl-queue-panel").classList.contains("hidden") || !q("#pl-eq-panel").classList.contains("hidden")) return;
    closeFull();
  });

  // drag the top of the player down to close it; the vinyl and the needle go with it
  [head, stage].forEach(zone => {
    let y0 = null, dy = 0;
    zone.addEventListener("pointerdown", ev => { if (ev.target.closest("button")) return; y0 = ev.clientY; dy = 0; app.classList.add("mdrag"); zone.setPointerCapture(ev.pointerId); });
    zone.addEventListener("pointermove", ev => { if (y0 === null) return; dy = Math.max(0, ev.clientY - y0); app.style.setProperty("--mdy", dy + "px"); });
    const end = () => {
      if (y0 === null) return;
      y0 = null; app.classList.remove("mdrag");
      if (dy > 100) closeFull(true); else app.style.removeProperty("--mdy");
    };
    zone.addEventListener("pointerup", end); zone.addEventListener("pointercancel", end);
  });

  // where the song comes from, and a thin line of progress on the small bar
  const ctx = () => {
    const t = current();
    q("#mp-ctx").textContent = !t ? "Biblioteca" : t.kind === "playlist" ? (t.group || "Playlist") : t.kind === "album" ? (t.album || t.group || "Álbum") : "Biblioteca";
  };
  new MutationObserver(ctx).observe(q("#pl-title"), { childList: true, characterData: true, subtree: true });
  new MutationObserver(() => {
    const p = parseFloat(q("#pl-progress").style.getPropertyValue("--p")) || 0;
    player.style.setProperty("--mp", (p / 100).toFixed(4));
  }).observe(q("#pl-progress"), { attributes: true, attributeFilter: ["style"] });
  // a panel or the lyrics opening changes how much room the controls leave
  new MutationObserver(() => { if (isFull()) fit(); }).observe(q("#lyrics"), { attributes: true, attributeFilter: ["class"] });
  new MutationObserver(() => { if (!player.classList.contains("hidden")) return; closeFull(true); }).observe(player, { attributes: true, attributeFilter: ["class"] });

  /* ---------- the way back (the phone's back gesture, see WebActivity.onBackPressed) ---------- */
  // One step per call, from the top of the stack of things that can be open down to the start page. It answers true when it did
  // something and false when there is nothing left to go back to: only then the app lets the phone leave it.
  const shown = id => { const e = document.getElementById(id); return !!e && !e.classList.contains("hidden"); };
  const startView = () => (mq.matches ? "start" : "home");
  // library, download and "More" go back to the start; a page opened from "More" or from the start goes back to where it was opened
  const backTarget = view => ((view === "stats" || view === "favorites" || view === "tags" || view === "settings" || view === "tutorial" || view === "faq")
    && (cameFrom[view] === "more" || cameFrom[view] === "start") ? cameFrom[view] : startView());
  function back() {
    if (document.getElementById("ctx")) { closeMenu(); return true; }
    if (shown("dialog")) { q("#dialog-no").click(); return true; }
    for (const [box, cancel] of [["smart-dialog", "#sm-cancel"], ["share-dialog", "#sh-close"], ["import-dialog", "#im-close"]]) {
      if (shown(box)) { q(cancel).click(); return true; }
    }
    if (LY.open) { if (LY.editing) q("#ly-cancel").click(); else if (LY.picking) stopPicking(); else closeLyrics(); return true; }
    if (shown("pl-queue-panel") || shown("pl-eq-panel")) { closePanels(); return true; }
    if (isFull()) { closeFull(); return true; }
    if (app.classList.contains("sidebar-open") && innerWidth <= 760) { setSidebar(false); return true; }
    if (S.view === "library" && libraryBack()) return true;                          // an album or a playlist open, or a search typed
    if (S.view === "home") {
      if (S.stack.length && !S.running) { goBack(); return true; }                      // an album opened from the results
      if (S.cur && !S.running) { clearSearch(); return true; }                          // the results of a search or a link
    }
    if (S.view !== startView()) { show(backTarget(S.view)); return true; }
    return false;
  }
  window.burdamixBack = back;

  /* ---------- crossing the width of the phone layout ---------- */
  const hint = q(".crate-hint"), hintText = hint ? hint.textContent : "";
  function sync() {
    app.classList.toggle("mobile", mq.matches);
    if (hint) hint.textContent = mq.matches ? "Desliza para pasar los discos" : hintText;
    if (mq.matches) { if (S.view === "home" && !sync.started) show("start"); sync.started = true; paintTabs(); fit(); }
    else { closeFull(true); if (S.view === "start" || S.view === "more") show("home"); }
    if (sync.started && S.view === "library") renderLibrary();      // the tabs and the shelf measure themselves again for the new width
  }
  mq.addEventListener("change", sync);
  addEventListener("resize", () => { if (mq.matches) fit(); });
  sync();
})();
