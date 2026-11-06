/* Motion only, no app logic. Splits titles for the rise-out-of-a-mask reveal, counts numbers up on the statistics screen
   and drives the depth of the background. */
(() => {
  const app = document.getElementById("app");
  const calm = matchMedia("(prefers-reduced-motion: reduce)");
  const fine = matchMedia("(hover: hover) and (pointer: fine)");
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  /* ---- intro: it removes itself, and never blocks a click (pointer-events: none) ---- */
  const splash = document.getElementById("splash");
  if (splash) { const gone = () => splash.remove(); splash.addEventListener("animationend", e => { if (e.target === splash) gone(); }); setTimeout(gone, 2200); }

  /* ---- titles ---- */
  const split = h => {
    if (h.dataset.split || h.children.length) return;
    const text = h.textContent.trim();
    if (!text) return;
    h.dataset.split = "1"; h.setAttribute("aria-label", text);
    h.innerHTML = text.split(/\s+/).map((w, k) => `<span class="w" aria-hidden="true"><i style="--k:${k}">${w.replace(/[<>&]/g, "")}</i></span>`).join(" ");
  };
  const reveal = () => {
    if (calm.matches) return;
    const h = document.querySelector(".view.active h1");
    if (!h) return;
    split(h);
    if (!h.dataset.split) return;
    h.classList.remove("rv"); void h.offsetWidth; h.classList.add("rv");
  };

  /* ---- sections: the new title rises as soon as the section changes ---- */
  const plainShow = window.show;
  if (typeof plainShow === "function") {
    window.show = view => {
      const same = typeof S !== "undefined" && S.view === view;
      plainShow(view);
      if (!same) reveal();
    };
  }

  /* ---- statistics: staggered entrance and numbers that count up ---- */
  const countUp = el => {
    const text = el.textContent, nums = [...text.matchAll(/\d+/g)];
    if (!nums.length || calm.matches) return;
    const t0 = performance.now(), dur = 900;
    (function tick(now) {
      const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
      let i = 0;
      el.textContent = text.replace(/\d+/g, n => Math.round(+n * e));
      if (p < 1) requestAnimationFrame(tick); else el.textContent = text;
    })(t0);
  };
  const body = document.getElementById("st-body");
  if (body) new MutationObserver(() => {
    ["st-tile", "st-bar", "st-list"].forEach(c => $$("." + c, body).forEach((el, k) => el.style.setProperty("--k", k)));
    $$(".st-list li", body).forEach((li, k) => li.style.setProperty("--k", k % 10));
    $$(".st-tile b", body).forEach(countUp);
  }).observe(body, { childList: true });

  /* ---- depth: the colour blobs lean away from the cursor ---- */
  if (!fine.matches || calm.matches) return;
  let tx = 0, ty = 0, dx = 0, dy = 0, raf = 0;
  document.addEventListener("pointermove", e => {
    tx = (e.clientX / innerWidth - .5) * 2; ty = (e.clientY / innerHeight - .5) * 2;
    if (!raf) raf = requestAnimationFrame(loop);
  }, { passive: true });
  function loop() {
    dx += (tx - dx) * .06; dy += (ty - dy) * .06;
    app.style.setProperty("--px", dx.toFixed(3)); app.style.setProperty("--py", dy.toFixed(3));
    raf = (Math.abs(tx - dx) > .002 || Math.abs(ty - dy) > .002) && !document.hidden ? requestAnimationFrame(loop) : 0;
  }
})();
