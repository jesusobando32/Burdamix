/* Visual effects only (no app logic): cursor light, magnetic buttons, pause when hidden. */
(() => {
  const app = document.getElementById("app");
  const calm = matchMedia("(prefers-reduced-motion: reduce)");
  const fine = matchMedia("(hover: hover) and (pointer: fine)");
  document.addEventListener("visibilitychange", () => app.classList.toggle("paused", document.hidden));
  if (!fine.matches) return;

  const MAGNETIC = ".btn.primary, .send";
  let frame = 0, ev = null, held = null;
  const release = el => { if (el) el.style.translate = ""; };
  document.addEventListener("pointermove", e => {
    ev = e;
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      app.style.setProperty("--mx", ev.clientX + "px");
      app.style.setProperty("--my", ev.clientY + "px");
      if (calm.matches) return;
      const el = ev.target.closest && ev.target.closest(MAGNETIC);
      if (held && held !== el) release(held);
      held = el;
      if (el && !el.disabled) {
        const r = el.getBoundingClientRect();
        el.style.translate = `${(ev.clientX - r.left - r.width / 2) * .2}px ${(ev.clientY - r.top - r.height / 2) * .28}px`;
      }
    });
  }, { passive: true });
  document.addEventListener("pointerleave", () => release(held));
})();
