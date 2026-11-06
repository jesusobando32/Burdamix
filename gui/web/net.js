/* Connection awareness. The program works without internet as a player: the library, the player, the lyrics already saved, the
   statistics, the tags and the playlists all live on this device. Only four things need the network (searching, downloading,
   logging in to Spotify and updating yt-dlp); those are refused up front, with a clear message, when the device says it is offline.
   Everything else is never touched by the connection. A small notice says what is going on and goes away by itself. */
const NET_NEEDED = new Set(["preview", "preview_liked", "open_card", "start_download", "update_ytdlp", "login_spotify"]);
const OFFLINE_TEXT = "Sin conexión. Tu música sigue disponible, pero para buscar o descargar hace falta internet.";
const needsNet = name => NET_NEEDED.has(name);

(() => {
  if (typeof document === "undefined") return;     // the tests load this file without a page
  const html = document.documentElement;
  let notice = null, hideTimer = 0;

  function ensureNotice() {
    if (notice) return notice;
    notice = document.createElement("div");
    notice.id = "offline"; notice.setAttribute("role", "status"); notice.setAttribute("aria-live", "polite");
    notice.innerHTML = '<i aria-hidden="true"></i><span>Sin conexión · tu música sigue disponible</span>';
    document.body.append(notice);
    return notice;
  }

  function paint(announceBack) {
    const off = navigator.onLine === false;
    html.classList.toggle("offline", off);
    clearTimeout(hideTimer);
    if (off) { const n = ensureNotice(); void n.offsetWidth; n.classList.add("on"); return; }
    if (notice) notice.classList.remove("on");
    if (announceBack && typeof toast === "function") toast("Conexión recuperada.");
  }

  addEventListener("offline", () => paint(false));
  addEventListener("online", () => paint(true));
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => paint(false));
  else paint(false);
})();
