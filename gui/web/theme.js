/* The colour of the interface. The logo's lime is the one accent of the whole window (buttons, rings, the active tab, the lyrics that are
   playing...); Settings lets the user pick another from sixteen tones that keep its softness (the same lightness and chroma, only the
   hue changes), so none of them shouts louder than the lime. The choice is remembered on this device and applied before anything is drawn. */

const ACCENT_HUES = [
  ["Rojo", 25], ["Coral", 45], ["Naranja", 60], ["Ámbar", 82], ["Amarillo", 100], ["Lima", 128], ["Verde", 150], ["Menta", 168],
  ["Turquesa", 188], ["Cian", 208], ["Celeste", 235], ["Azul", 262], ["Violeta", 290], ["Morado", 318], ["Magenta", 340], ["Rosa", 358],
];
// OKLCH: the same lightness and chroma for every tone, so they look equally soft to the eye (a blue and a yellow of the same HSL
// lightness do not); only the hue changes. The light, low-contrast style of the lime, in every colour.
const ACCENT_LIGHTNESS = .86, ACCENT_CHROMA = .17;   // the lightest a tone may be, and the chroma it keeps (the lime has about .2)

function oklchRgb(lightness, chroma, hue) {
  const h = hue * Math.PI / 180, a = chroma * Math.cos(h), b = chroma * Math.sin(h);
  const l = (lightness + .3963377774 * a + .2158037573 * b) ** 3, m = (lightness - .1055613458 * a - .0638541728 * b) ** 3, s = (lightness - .0894841775 * a - 1.291485548 * b) ** 3;
  return [4.0767416621 * l - 3.3077115913 * m + .2309699292 * s, -1.2684380046 * l + 2.6097574011 * m - .3413193965 * s, -.0041960863 * l - .7034186147 * m + 1.707614701 * s];
}

// a tone that does not fit in sRGB loses chroma (not hue) until it does, instead of being cut flat and turning harsh (cyan, turquoise)
function oklchHex(lightness, chroma, hue) {
  let rgb = oklchRgb(lightness, chroma, hue);
  for (let c = chroma; c > 0 && rgb.some(v => v < -.002 || v > 1.002); c -= .004) rgb = oklchRgb(lightness, c, hue);
  const encode = v => { v = Math.max(0, Math.min(1, v)); return Math.round(255 * (v <= .0031308 ? 12.92 * v : 1.055 * v ** (1 / 2.4) - .055)); };
  return "#" + rgb.map(v => encode(v).toString(16).padStart(2, "0")).join("");
}

// Each hue is as light as it can be while keeping the chroma: a red or a blue cannot be both light and vivid, so they come out a bit
// darker than the lime and the yellows, but every one of them is as strong as the lime, not a pastel.
function accentLightness(hue) {
  for (let l = ACCENT_LIGHTNESS; l >= .72; l -= .01) if (oklchRgb(l, ACCENT_CHROMA, hue).every(v => v >= -.002 && v <= 1.002)) return l;
  return .72;                      // not lighter-and-vivid at once (cyans, blues): this light, with all the chroma that fits
}

// the lime keeps its exact tones: nobody who never opens Settings sees any difference
const ACCENTS = ACCENT_HUES.map(([name, hue]) => {
  if (name === "Lima") return { name, hex: "#b5ef4a", strong: "#c8f56e" };
  const l = accentLightness(hue);
  return { name, hex: oklchHex(l, ACCENT_CHROMA, hue), strong: oklchHex(Math.min(.95, l + .06), ACCENT_CHROMA, hue) };
});

function savedAccent() {
  try { return localStorage.getItem("accent") || "Lima"; } catch (e) { return "Lima"; }
}

function applyAccent(name, remember = false) {
  const tone = ACCENTS.find(a => a.name === name) || ACCENTS.find(a => a.name === "Lima");
  const style = document.documentElement.style;
  style.setProperty("--accent", tone.hex); style.setProperty("--accent-strong", tone.strong);
  style.setProperty("--accent-text", tone.hex); style.setProperty("--lime", tone.hex);
  if (remember) { try { localStorage.setItem("accent", tone.name); } catch (e) { /* applied, only not remembered */ } }
  document.querySelectorAll("#accent-swatches button").forEach(b => b.setAttribute("aria-checked", String(b.dataset.name === tone.name)));
  return tone;
}

/* The sixteen round buttons of Settings. */
function renderAccentPicker() {
  const box = document.getElementById("accent-swatches");
  if (!box || box.childElementCount) return;
  box.innerHTML = ACCENTS.map(a => `<button type="button" role="radio" class="swatch" data-name="${a.name}" aria-label="${a.name}" title="${a.name}" style="--sw:${a.hex}"></button>`).join("");
  box.onclick = ev => { const b = ev.target.closest(".swatch"); if (b) applyAccent(b.dataset.name, true); };
  applyAccent(savedAccent());
}

applyAccent(savedAccent());
