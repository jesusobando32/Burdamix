/* The Android side of the player and of the background work: the notification with controls, the lock screen and the headset buttons,
   and keeping the app alive while it downloads. Android's WebView plays the songs but shows no media notification of its own, so the app
   keeps a service (PlaybackService.kt) that mirrors what is playing and hands the buttons back here; another one (KeepAliveService.kt)
   stops Android from freezing a download when the user leaves the app. Without `BurdamixAndroid` (desktop window, a browser, ?demo)
   this file does nothing. */
(() => {
  const host = window.BurdamixAndroid;
  if (!host) return;
  const has = name => { try { return typeof host[name] === "function" || !!host[name]; } catch (e) { return false; } };

  /* ---------- the player's notification ---------- */
  let last = "", asked = false;

  const state = () => {
    const t = current();
    if (!t) return { has: false };
    const el = P.decks.length ? deck().el : null;
    const duration = el && isFinite(el.duration) && el.duration > 0 ? el.duration : (t.duration || 0);
    return {
      has: true, title: t.title || "", artist: t.artist || "", album: t.album || "", cover: t.cover_url || "",
      playing: isPlaying(), position: el ? Math.round(el.currentTime * 1000) : 0, duration: Math.round(duration * 1000), shuffle: !!P.shuffle,
      // paused on purpose (a tap, the notification, the headset, the end of the song), not by Android because another app played a sound
      userPaused: !isPlaying() && (!!(el && el.ended) || Date.now() - (P.askedAt || 0) < 2000),
    };
  };

  // Android 13 and later hide notifications until the user allows them, and a "no" is easy to give by accident: say it once,
  // with a button that opens the right screen. Without this the player's controls simply never show and nothing explains why.
  const checkNotifications = () => {
    if (asked || !has("notificationsEnabled")) return;
    asked = true;
    try {
      if (!host.notificationsEnabled()) {
        toast("Las notificaciones están desactivadas, así que no verás los controles de la música fuera de la app.", true,
          has("openNotificationSettings") ? { label: "Activar", run: () => host.openNotificationSettings() } : null);
      }
    } catch (e) { /* the notification is a convenience */ }
  };

  // called by player.js whenever the song, the play state, the position (a jump) or the shuffle changes; the same state is not sent twice
  window.__nativeMedia = () => {
    if (!has("media")) return;
    let s;
    try { s = state(); } catch (e) { return; }
    if (s.has && s.playing) checkNotifications();
    const key = JSON.stringify({ ...s, position: Math.round(s.position / 1500) });
    if (key === last) return;
    last = key;
    try { host.media(JSON.stringify(s)); } catch (e) { /* playing never depends on the notification */ }
  };

  // the buttons of the notification, the lock screen and the headset come back as words
  window.__burdamixMedia = action => {
    if (!current()) return;
    if (action === "play") { if (!isPlaying()) toggle(); }
    else if (action === "pause") { if (isPlaying()) toggle(); }
    else if (action === "toggle") toggle();
    else if (action === "next") advance(false);
    else if (action === "previous") previous();
    else if (action === "shuffle") setShuffle(!P.shuffle);
    else if (action.startsWith("seek:")) { const ms = Number(action.slice(5)); if (isFinite(ms)) seek(ms / 1000); }
  };

  /* ---------- downloads and tag jobs keep going when the app is left ---------- */
  // The page only says "there is work" (and what); the service watches Python itself and stops when it ends.
  if (has("keepAlive")) {
    let keeping = "";
    setInterval(() => {
      let text = "";
      try {
        if (S.running) { const k = counts(); text = k && k.ok ? `Descargando canciones… ${k.ok} listas` : "Descargando canciones…"; }
        else if (typeof T !== "undefined" && (T.running || T.applying)) text = "Completando etiquetas…";
      } catch (e) { text = S.running ? "Descargando canciones…" : text; }
      if (text === keeping) return;
      keeping = text;
      try { host.keepAlive(!!text, text); } catch (e) { /* worst case the download pauses when the app is left, as before */ }
    }, 1500);
  }
})();
