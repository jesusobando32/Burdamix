/* Motion only, no app logic. Wraps show() with a circular curtain, splits titles for the rise-out-of-a-mask reveal,
   counts numbers up on the statistics screen and drives the cursor ring and the depth of the background. */
(() => {
  const app = document.getElementById("app");
  const calm = matchMedia("(prefers-reduced-motion: reduce)");
  const fine = matchMedia("(hover: hover) and (pointer: fine)");
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const born = performance.now();

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

  /* ---- curtain ---- */
  const curtain = document.createElement("div");
  curtain.id = "curtain"; curtain.setAttribute("aria-hidden", "true"); curtain.innerHTML = '<i class="c1"></i><i class="c2"></i>';
  app.append(curtain);
  let busy = false, target = null, origin = [innerWidth / 2, innerHeight / 2];
  document.addEventListener("pointerdown", e => { origin = [e.clientX, e.clientY]; }, true);
  document.addEventListener("keydown", () => { origin = [innerWidth / 2, innerHeight / 2]; }, true);

  const plainShow = window.show;
  if (typeof plainShow === "function") {
    window.show = view => {
      const same = typeof S !== "undefined" && S.view === view;
      if (busy) { target = view; return; }
      if (calm.matches || same || performance.now() - born < 1700 || document.hidden) { plainShow(view); requestAnimationFrame(reveal); return; }
      busy = true; target = view;
      curtain.style.setProperty("--cx", origin[0] + "px"); curtain.style.setProperty("--cy", origin[1] + "px");
      curtain.className = "on in";
      setTimeout(() => {
        plainShow(target); reveal();
        curtain.className = "on out";
        setTimeout(() => { curtain.className = ""; busy = false; }, 520);
      }, 400);
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

  /* ---- cursor ring and depth ---- */
  if (!fine.matches || calm.matches) return;
  const ring = document.createElement("div");
  ring.id = "cursor"; ring.setAttribute("aria-hidden", "true"); document.body.append(ring);
  let mx = innerWidth / 2, my = innerHeight / 2, rx = mx, ry = my, dx = 0, dy = 0, awake = false, raf = 0;
  const HOT = "a, button, input, select, summary, [role=button], .row, .lib-row, .q-row, .st-list li, .chip-btn, .pill, .switch";
  document.addEventListener("pointermove", e => {
    mx = e.clientX; my = e.clientY;
    if (!awake) { awake = true; ring.classList.add("on"); }
    const t = e.target.closest ? e.target : null;
    ring.classList.toggle("hot", !!(t && t.closest(HOT)));
    ring.classList.toggle("text", !!(t && t.closest("input[type=text], input[type=search], input[type=number]")));
    if (!raf) raf = requestAnimationFrame(loop);
  }, { passive: true });
  document.addEventListener("pointerdown", () => ring.classList.add("down"), true);
  document.addEventListener("pointerup", () => ring.classList.remove("down"), true);
  document.documentElement.addEventListener("pointerleave", () => ring.classList.remove("on"));
  document.documentElement.addEventListener("pointerenter", () => awake && ring.classList.add("on"));
  function loop() {
    rx += (mx - rx) * .2; ry += (my - ry) * .2;
    dx += ((mx / innerWidth - .5) * 2 - dx) * .06; dy += ((my / innerHeight - .5) * 2 - dy) * .06;
    ring.style.transform = `translate3d(${rx}px, ${ry}px, 0)`;
    app.style.setProperty("--px", dx.toFixed(3)); app.style.setProperty("--py", dy.toFixed(3));
    raf = (Math.abs(mx - rx) > .3 || Math.abs(my - ry) > .3 || Math.abs((mx / innerWidth - .5) * 2 - dx) > .002) && !document.hidden ? requestAnimationFrame(loop) : 0;
  }
})();
