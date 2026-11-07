/* The Android side of the player: the notification with controls, the lock screen and the headset buttons. Android's WebView plays the
   songs but shows no media notification of its own, so the app keeps a service (PlaybackService.kt) that mirrors what is playing and
   hands the buttons back here. Without `BurdamixAndroid.media` (desktop window, a browser, ?demo) this file does nothing. */
(() => {
  const host = window.BurdamixAndroid;
  if (!host || typeof host.media !== "function") return;
  let last = "";

  const state = () => {
    const t = current();
    if (!t) return { has: false };
    const el = P.decks.length ? deck().el : null;
    const duration = el && isFinite(el.duration) && el.duration > 0 ? el.duration : (t.duration || 0);
    return {
      has: true, title: t.title || "", artist: t.artist || "", album: t.album || "", cover: t.cover_url || "",
      playing: isPlaying(), position: el ? Math.round(el.currentTime * 1000) : 0, duration: Math.round(duration * 1000), shuffle: !!P.shuffle,
    };
  };

  // called by player.js whenever the song, the play state, the position (a jump) or the shuffle changes; the same state is not sent twice
  window.__nativeMedia = () => {
    let s;
    try { s = state(); } catch (e) { return; }
    const key = JSON.stringify({ ...s, position: Math.round(s.position / 1500) });
    if (key === last) return;
    last = key;
    try { host.media(JSON.stringify(s)); } catch (e) { /* the notification is a convenience: playing never depends on it */ }
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
})();
