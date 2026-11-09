/* Reading the QR of a shared playlist with the phone's camera (the "Escanear QR" button of the import window).
   The camera comes through getUserMedia (the app answers the WebView's permission request, see WebActivity.onPermissionRequest) and
   every frame goes to jsQR (jsqr.js, loaded only when the scanner opens: nobody else needs its 250 KB). Nothing leaves the phone. */

let qrScannerClose = null;

const canScanQr = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia);

function loadQrLibrary() {
  if (window.jsQR) return Promise.resolve();
  return new Promise((ok, fail) => {
    const script = document.createElement("script");
    script.src = "jsqr.js";
    script.onload = ok;
    script.onerror = () => fail(new Error("jsqr"));
    document.head.appendChild(script);
  });
}

function qrCameraError(error) {
  const name = error && error.name;
  if (name === "NotAllowedError" || name === "SecurityError") return "Burdamix no tiene permiso para usar la cámara. Actívalo en los ajustes de Android.";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "Este teléfono no tiene una cámara disponible.";
  return "No pude abrir la cámara.";
}

/* Opens the scanner over the whole screen and calls `onCode(text)` once with the first QR it reads, closing itself. */
async function openQrScanner(onCode) {
  if (document.getElementById("qr-scan")) return;
  const box = document.createElement("div");
  box.id = "qr-scan"; box.className = "qr-scan"; box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "Escanear código QR");
  box.innerHTML = `<video playsinline muted autoplay></video><div class="qr-frame" aria-hidden="true"></div>
    <div class="qr-bar"><p class="qr-hint" role="status">Apunta al código QR de la playlist</p><button class="btn" type="button" id="qr-cancel">Cancelar</button></div>`;
  document.body.appendChild(box);
  const video = box.querySelector("video"), hint = box.querySelector(".qr-hint");
  let stream = null, timer = 0, closed = false;
  const close = () => {
    if (closed) return;
    closed = true; clearInterval(timer);
    if (stream) stream.getTracks().forEach(track => track.stop());       // the camera light goes off
    video.srcObject = null; box.remove(); qrScannerClose = null;
    document.removeEventListener("visibilitychange", onHide);
  };
  const onHide = () => { if (document.hidden) close(); };                  // leaving the app must not keep the camera on
  document.addEventListener("visibilitychange", onHide);
  qrScannerClose = close;
  box.querySelector("#qr-cancel").onclick = close;
  try {
    await loadQrLibrary();
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } }, audio: false });
  } catch (error) { hint.textContent = qrCameraError(error); return; }
  if (closed) { stream.getTracks().forEach(track => track.stop()); return; }
  video.srcObject = stream;
  try { await video.play(); } catch (error) { /* autoplay already started it */ }
  const canvas = document.createElement("canvas"), context = canvas.getContext("2d", { willReadFrequently: true });
  timer = setInterval(() => {
    if (video.readyState < 2 || !video.videoWidth) return;
    const scale = Math.min(1, 960 / video.videoWidth);                    // a dense QR (a long playlist) needs the detail
    canvas.width = Math.round(video.videoWidth * scale); canvas.height = Math.round(video.videoHeight * scale);
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const frame = context.getImageData(0, 0, canvas.width, canvas.height);
    const found = window.jsQR(frame.data, frame.width, frame.height, { inversionAttempts: "attemptBoth" });
    if (found && found.data) { close(); onCode(found.data); }
  }, 180);
}

function closeQrScanner() { if (qrScannerClose) qrScannerClose(); }
