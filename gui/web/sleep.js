/* The sleep timer: after some minutes (or at the end of the song) the music fades out over a few seconds and pauses.
   It does not turn the computer off or close the app, and it is not remembered between runs: a timer you forgot should not wake up days later. */
const SLEEP_FADE = 30;          // seconds the volume goes down before the end of a timer
const SLEEP_FADE_SONG = 6;      // …and before the end of the song, when that is what was asked
const SL = { mode: null, endAt: 0, timer: 0 };       // mode: null | "time" | "song"

const sleepActive = () => !!SL.mode;

function startSleep(minutes) {
  stopSleep(false);
  SL.mode = "time"; SL.endAt = Date.now() + minutes * 60000;
  SL.timer = setInterval(tickSleep, 250);
  paintSleep();
  toast(`La música se pausará en ${minutes} min, bajando el volumen poco a poco.`);
}

function startSleepAtSongEnd() {
  stopSleep(false);
  SL.mode = "song"; SL.endAt = 0;
  SL.timer = setInterval(tickSleep, 250);
  paintSleep();
  toast("La música se pausará al terminar esta canción.");
}

function stopSleep(say = true) {
  clearInterval(SL.timer);
  const was = SL.mode;
  SL.mode = null; SL.endAt = 0; SL.timer = 0;
  P.fade = 1; applyVolume();
  paintSleep();
  if (was && say) toast("Temporizador cancelado.");
}

// the seconds left: of the timer, or of the song when the timer waits for its end
function sleepLeft() {
  if (SL.mode === "time") return Math.max(0, (SL.endAt - Date.now()) / 1000);
  if (SL.mode === "song" && P.decks.length) { const el = deck().el; return isFinite(el.duration) ? Math.max(0, el.duration - el.currentTime) : Infinity; }
  return Infinity;
}

function tickSleep() {
  if (!SL.mode) return;
  const left = sleepLeft(), span = SL.mode === "time" ? SLEEP_FADE : SLEEP_FADE_SONG;
  if (left <= 0.25) { finishSleep(); return; }
  P.fade = left < span ? left / span : 1;
  applyVolume();
  paintSleep();
}

function finishSleep() {
  stopSleep(false);
  if (P.decks.length && isPlaying()) toggle();
  P.fade = 1; applyVolume();       // the next play starts at the volume the user set
  toast("Temporizador: música en pausa. Que descanses.");
}

const clock = seconds => `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

function paintSleep() {
  const button = $("#pl-sleep"), pill = $("#sl-left");
  button.setAttribute("aria-pressed", sleepActive());
  const left = sleepLeft();
  const text = SL.mode === "time" ? clock(left) : SL.mode === "song" ? "fin" : "";
  pill.textContent = text; pill.hidden = !text;
  button.title = SL.mode === "time" ? `Temporizador: quedan ${clock(left)}` : SL.mode === "song" ? "Temporizador: al terminar la canción" : "Temporizador para dormir";
}

async function askSleepMinutes() {
  const answer = await confirmDialog({ title: "Temporizador personalizado", text: "¿Cuántos minutos? (de 1 a 600)", ok: "Empezar", input: { value: "20" } });
  if (answer === null) return;
  const minutes = Math.round(Number(String(answer).replace(",", ".")));
  if (!(minutes >= 1 && minutes <= 600)) { toast("Escribe un número de minutos entre 1 y 600.", true); return; }
  startSleep(minutes);
}

function openSleepMenu() {
  const box = $("#pl-sleep").getBoundingClientRect(), items = [];
  const moon = '<svg viewBox="0 0 24 24"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></svg>';
  if (sleepActive()) items.push({ label: SL.mode === "time" ? `Cancelar el temporizador (quedan ${clock(sleepLeft())})` : "Cancelar el temporizador", icon: moon, run: () => stopSleep() }, { sep: true });
  [15, 30, 45, 60].forEach(m => items.push({ label: `${m} minutos`, icon: moon, run: () => startSleep(m) }));
  items.push({ label: "Al terminar esta canción", icon: moon, run: startSleepAtSongEnd }, { label: "Personalizado…", icon: moon, run: askSleepMinutes });
  openMenu(box.left, box.top - (items.length * 40 + 24), items);
}

function wireSleep() {
  $("#pl-sleep").onclick = ev => { ev.stopPropagation(); openSleepMenu(); };
}
