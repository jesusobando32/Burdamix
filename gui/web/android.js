/* The Android side of window.pywebview. Inside the Android app the page is shown by a WebView that exposes `BurdamixAndroid`
   (methods() and call(), see MainActivity). This file builds the same `window.pywebview.api` the desktop window has, so app.js
   does not know the difference: each function returns a promise that the program answers later through __burdamixReply.
   Without `BurdamixAndroid` (desktop window, a browser, ?demo) it does nothing. Loaded before app.js. */
(function () {
  if (typeof window === "undefined" || !window.BurdamixAndroid) return;
  const host = window.BurdamixAndroid;
  const waiting = new Map();
  let last = 0;

  window.__burdamixReply = function (id, envelope) {
    const entry = waiting.get(String(id));
    if (!entry) return;
    waiting.delete(String(id));
    const answer = JSON.parse(envelope);
    if (answer.ok) return entry.resolve(answer.value);
    const error = new Error(answer.error.message);
    error.name = answer.error.name;
    entry.reject(error);
  };

  const api = {};
  for (const name of JSON.parse(host.methods())) {
    api[name] = (...args) => new Promise((resolve, reject) => {
      const id = String(++last);
      waiting.set(id, { resolve, reject });
      try { host.call(id, name, JSON.stringify(args)); }
      catch (error) { waiting.delete(id); reject(error); }
    });
  }
  // mobile.css hides what has no meaning on a phone (opening or choosing folders, picking files from disk).
  if (window.document && window.document.documentElement) window.document.documentElement.classList.add("android");
  window.pywebview = { platform: "android", api };
  window.dispatchEvent(new Event("pywebviewready"));
})();
