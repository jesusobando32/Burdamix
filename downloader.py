import const
import updater
from const import colours, DOWNLOADS_DIR
from exceptions import (SpotifyAlbumNotFound, SpotifyTrackNotFound, SpotifyPlaylistNotFound, SpotifyRetrievalError,
                        InvalidSpotifyURL, ConfigVideoLowViewCount, YoutubeItemNotFound, YoutubeVideoUnavailable, YoutubeBlocked, YoutubeTransientError,
                        YoutubeNetworkError, MetadataError, TagWriteError)
from apis.spotify import Spotify, SpotifyNetworkError, SpotifyRateLimited
from apis.youtube import YouTube, SUPPORTED_BROWSERS
from pathutils import sanitize_filename, long_path, is_hard_to_open
import tempdirs
from utils import resave_audio_clip_with_metadata
import contextlib
import os
import signal
import sys
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from pathlib import Path
import re
import time

DEFAULT_SHORT_MAX_SECONDS = 50           # any track this short, whatever its name
DEFAULT_INTERLUDE_MAX_SECONDS = 70       # interlude / skit / prelude
DEFAULT_INTRO_OUTRO_MAX_SECONDS = 95     # intro / outro: above this it is a real song and is kept
INTERLUDE_WORDS = re.compile(r"\b(interlude|interludio|skit|prelude|preludio)\b", re.IGNORECASE)
INTRO_OUTRO_WORDS = re.compile(r"\b(intro|outro)\b", re.IGNORECASE)


PREVIEW_LINES = 300        # a preview lists at most this many songs
CANCEL_PRESSES = 3       # Ctrl+C presses needed to cancel a download in progress
CTRL_C_POLL_SECONDS = 0.05  # how often the waiting main thread looks for a Ctrl+C
BLOCK_STREAK_LIMIT = 5   # songs in a row that YouTube refuses before we stop asking
RETRY_PASS_DELAY_SECONDS = 15   # before the end-of-run retry of songs YouTube rejected
RETRY_DELAY_SECONDS = 3  # pause before the second round of attempts after a temporary error
_NOT_STARTED = object()  # returned by a song that was dropped because the run was aborted

MP3_BITRATES = (48, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320)


def mp3_bitrate_for(source_kbps, requested_kbps):
    """The MP3 bitrate (kbps) to encode with: never above what YouTube gave us, never above what was
    asked, and a real MP3 rate (the encoder would round an odd value like 132 down to 128 anyway)."""
    wanted = min(source_kbps, requested_kbps)
    return min(MP3_BITRATES, key=lambda rate: abs(rate - wanted))


@contextlib.contextmanager
def ctrl_c_needs_three_presses():
    """While songs are downloading, Ctrl+C has to be pressed CANCEL_PRESSES times to cancel: a stray press
    (or one meant for another window) must not throw away a long download. Only works in the main thread."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    presses = [0]

    def handler(signum, frame):
        presses[0] += 1
        if presses[0] >= CANCEL_PRESSES:
            raise KeyboardInterrupt
        remaining = CANCEL_PRESSES - presses[0]
        # plain print: this runs between two instructions of the main thread, so it must not take our log lock
        print(f"\n{colours.WARNING}[!] Ctrl+C {presses[0]}/{CANCEL_PRESSES}: sigo descargando. "
              f"Pulsa Ctrl+C {remaining} vez/veces más para cancelar.{colours.ENDC}")

    previous = signal.signal(signal.SIGINT, handler)
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, previous)


def reason_category(error):
    """What kind of problem an error is, to group the songs and say what to do about each group."""
    text = str(error).lower()
    if isinstance(error, YoutubeBlocked):
        return "robot"
    if isinstance(error, YoutubeNetworkError):
        return "red"
    if isinstance(error, YoutubeTransientError):
        return "temporal"
    if isinstance(error, YoutubeVideoUnavailable):
        return "edad" if ("age" in text or "inappropriate" in text) else "no_disponible"
    if isinstance(error, YoutubeItemNotFound):
        return "no_encontrada"
    if isinstance(error, ConfigVideoLowViewCount):
        return "pocas_vistas"
    if isinstance(error, SpotifyTrackNotFound):
        return "no_en_spotify"
    if "cookie" in text:
        return "cookies"
    return "otro"


OUTDATED_YTDLP_MARKERS = ("unable to extract", "requested format is not available", "nsig", "signature",
                          "please report this issue", "player response")


def suggests_outdated_ytdlp(error):
    """Errors yt-dlp itself cannot explain (not a block, not a private video) usually mean YouTube changed."""
    if reason_category(error) != "otro":
        return False
    return any(marker in str(error).lower() for marker in OUTDATED_YTDLP_MARKERS)


def friendly_reason(error):
    """One sentence, in plain Spanish, saying why a song was not downloaded."""
    category = reason_category(error)
    if category == "no_encontrada":
        if "duration" in str(error).lower():
            return ("No encontré en YouTube una versión con la misma duración que en Spotify "
                    "(prefiero saltarla antes que bajar una equivocada).")
        return "YouTube no devolvió resultados para esta canción."
    if category == "otro":
        return f"Algo salió mal ({type(error).__name__}). Vuelve a ejecutar el mismo enlace para reintentarla."
    return REASONS[category]


REASONS = {
    "edad": "YouTube marca este video para mayores de edad y pide iniciar sesión.",
    "robot": "YouTube pidió comprobar que no eres un robot (demasiadas solicitudes seguidas).",
    "temporal": "YouTube falló varias veces seguidas con esta canción (error temporal).",
    "red": "No pude conectar bien con YouTube: la conexión a internet falló o va muy lenta.",
    "no_disponible": "Este video no está disponible (privado, retirado o bloqueado en tu país).",
    "pocas_vistas": "El video tiene menos vistas que el mínimo que pediste (--min-views).",
    "no_en_spotify": "Spotify no tiene los datos de esta canción.",
    "cookies": "No pude leer tu sesión del navegador. Cierra el navegador por completo y reintenta, o prueba con Firefox.",
}

# What to do, in the order they are shown.
ADVICE = {
    "edad": "Las de mayores de edad: YouTube exige iniciar sesión. Ejecuta con tu sesión de YouTube: "
            "--cookies-from-browser firefox (o chrome, edge). En el modo guiado, el programa te lo ofrece al terminar.",
    "robot": "Las del aviso de robot: YouTube recibió muchas solicitudes. Espera unos minutos y ejecuta de nuevo "
             "el mismo enlace: solo bajará las que faltan.",
    "red": "Las de conexión: tu internet falló o va muy lento. Revisa la conexión (o cambia de red) y vuelve a intentarlo: "
           "solo bajará las que faltan.",
    "temporal": "Las de error temporal: vuelve a ejecutar el mismo enlace en un rato; solo bajará las que faltan.",
    "no_encontrada": "Las que no se encontraron: no hay en YouTube una versión con la misma duración (quizá solo "
                     "existen en Spotify). Prefiero saltarlas antes que bajar una equivocada.",
    "no_disponible": "Las no disponibles: el video está privado, retirado o bloqueado; no hay otra versión que sirva.",
    "pocas_vistas": "Las de pocas vistas: baja el mínimo con --min-views.",
    "no_en_spotify": "Las que Spotify no reconoce: puede que hayan sido retiradas de Spotify.",
    "cookies": "No se pudo usar tu sesión del navegador: ciérralo por completo y reintenta, o prueba con Firefox.",
    "otro": "Las demás: vuelve a ejecutar el mismo enlace para reintentarlas. Si se repite, escribe el error en "
            "https://github.com/jesusobando32/Burdamix/issues",
}


def ask_browser():
    """Which browser holds the user's YouTube session? Returns its name, or None to leave those songs out."""
    print("Si en tu navegador tienes YouTube abierto con tu cuenta, el programa puede usar esa sesión para bajarlas.")
    print("(Firefox es el que mejor funciona; si usas Chrome o Edge, ciérralo por completo antes.)")
    while True:
        answer = input(f"{colours.OKGREEN}Escribe el navegador ({', '.join(SUPPORTED_BROWSERS)}) "
                       f"o pulsa Enter para dejarlas:{colours.ENDC} ").strip().lower()
        if not answer:
            return None
        if answer in SUPPORTED_BROWSERS:
            return answer
        print(f"{colours.WARNING}Escribe uno de estos: {', '.join(SUPPORTED_BROWSERS)}.{colours.ENDC}")


YES_WORDS = ("yes", "y", "s", "si", "sí")
NO_WORDS = ("no", "n")


def ask_yes_no(prompt):
    """Ask until the answer is yes or no (also s/si/sí/y/n)."""
    while True:
        answer = input(prompt).strip().lower()
        if answer in YES_WORDS:
            return True
        if answer in NO_WORDS:
            return False
        print(f"{colours.WARNING}Responde yes o no.{colours.ENDC}")


def plan_filenames(tracks, style=const.DEFAULT_NAME_STYLE):
    """Decide the file name of every track before downloading anything, written in the chosen style (const.NAME_STYLES).

    Returns (plan, repeated, renamed):
    - plan: [(index, track, file name)] to download;
    - repeated: [track] that are the very same Spotify song as an earlier one (downloaded once);
    - renamed: [(track, file name)] different songs whose name collides with another one (the file
      system ignores case, so 'Song' and 'SONG' are the same file); they get ' (2)', ' (3)'...

    Names depend on the Spotify ids, not on the playlist order, so a second run gives the same names."""
    groups = {}
    for index, track in enumerate(tracks):
        groups.setdefault(track.get_filename(style).casefold(), []).append((index, track))

    names = {}
    repeated = []
    renamed = []
    for entries in groups.values():
        by_id = {}
        for index, track in entries:
            by_id.setdefault(getattr(track, "resource_id", None) or id(track), []).append((index, track))
        for rank, track_id in enumerate(sorted(by_id, key=str), start=1):
            first_index, first_track = by_id[track_id][0]
            base = first_track.get_filename(style)
            names[first_index] = base if rank == 1 else f"{base} ({rank})"
            if rank > 1:
                renamed.append((first_track, names[first_index]))
            repeated.extend(track for _, track in by_id[track_id][1:])

    plan = [(index, tracks[index], name) for index, name in sorted(names.items())]
    return plan, repeated, renamed


def is_interlude(title, duration_seconds, max_seconds=DEFAULT_INTERLUDE_MAX_SECONDS,
                 intro_outro_max_seconds=DEFAULT_INTRO_OUTRO_MAX_SECONDS, short_max_seconds=DEFAULT_SHORT_MAX_SECONDS):
    """True for tracks that are not really songs:
    - anything up to `short_max_seconds`, whatever its name (a 12-second track is never a song);
    - an interlude/skit up to `max_seconds`;
    - an intro/outro up to `intro_outro_max_seconds`.

    The name only matters between those limits: a 3-minute song called "Intro" is a real song."""
    if duration_seconds <= short_max_seconds:
        return True
    if INTERLUDE_WORDS.search(title) and duration_seconds <= max_seconds:
        return True
    return bool(INTRO_OUTRO_WORDS.search(title)) and duration_seconds <= intro_outro_max_seconds


class SpotifyDownloader:
    def __init__(self, spotify: Spotify, youtube: YouTube, audio_quality=1000000, max_length=60*30, min_view_count=10000, workers=5,
                 skip_interludes=True, interlude_max_seconds=DEFAULT_INTERLUDE_MAX_SECONDS,
                 intro_outro_max_seconds=DEFAULT_INTRO_OUTRO_MAX_SECONDS, short_max_seconds=DEFAULT_SHORT_MAX_SECONDS,
                 dry_run=False, ask_before_download=False, offer_browser_login=False, on_event=None,
                 name_style=const.DEFAULT_NAME_STYLE):
        self.name_style = name_style if name_style in const.NAME_STYLES else const.DEFAULT_NAME_STYLE
        self.on_event = on_event   # graphical interface: called with (kind, **data) as each song progresses
        self.cancelled = threading.Event()   # set to stop starting new songs
        self.dry_run = dry_run   # list what would be downloaded and stop
        self.ask_before_download = ask_before_download   # list it, then ask yes/no
        self.offer_browser_login = offer_browser_login   # guided mode: offer the user's YouTube login for adult-only videos
        self.declined = False    # the user answered no to "download them?"
        self.spotify_client = spotify
        self.youtube_client = youtube
        self.audio_quality = audio_quality  # requested bitrate in bps; never modified after construction
        self.max_length = max_length  # seconds
        self.min_view_count = min_view_count
        self.workers = max(1, workers)  # songs downloaded at the same time
        self.skip_interludes = skip_interludes
        self.interlude_max_seconds = interlude_max_seconds
        self.intro_outro_max_seconds = intro_outro_max_seconds
        self.short_max_seconds = short_max_seconds
        self._print_lock = threading.Lock()
        self.blocked = False   # set when YouTube made us stop mid-run
        self.planned = 0       # songs actually attempted in the last download_tracks call
        self.last_output_path = None   # folder where the songs of the last request were saved
        self._tagger = None            # tags songs found by typing their name (created when the first one needs it)
        self._tagger_lock = threading.Lock()

    def split_interludes(self, tracks):
        """(songs to download, short interludes left out). Nothing is left out when skipping is off."""
        if not self.skip_interludes:
            return tracks, []
        interludes = [t for t in tracks if is_interlude(t.get_title(), t.get_metadata()["duration_ms"] / 1000,
                                                        self.interlude_max_seconds, self.intro_outro_max_seconds, self.short_max_seconds)]
        return [t for t in tracks if t not in interludes], interludes

    def _emit(self, kind, track=None, **data):
        """Tell the graphical interface what happened; a bug in the interface must never stop a download."""
        if self.on_event is None:
            return
        try:
            self.on_event(kind, key=getattr(track, "resource_id", None), **data)
        except Exception:
            pass

    def _download_collection(self, kind, folder, retrieve, not_found_message):
        """Shared flow for albums, playlists and liked songs. Returns True if at least one track was saved."""
        print(f"\n{colours.OKBLUE}[!] Retrieving spotify {kind} (large collections will take time)")

        try:
            collection = retrieve()
            output_path = os.path.join(DOWNLOADS_DIR, folder, sanitize_filename(collection.get_title())) + os.sep
            tracks = collection.get_tracks()
        except (SpotifyAlbumNotFound, SpotifyPlaylistNotFound):
            print(f"\n{colours.FAIL}Error: {colours.ENDC}{colours.WARNING}{not_found_message}{colours.ENDC}\n")
            sys.exit(1)
        except (SpotifyNetworkError, SpotifyRateLimited) as e:
            print(f"\n{colours.FAIL}Error: {colours.ENDC}{e}{colours.ENDC}\n")
            sys.exit(1)
        except (SpotifyRetrievalError, InvalidSpotifyURL) as e:
            print(f"\n{colours.FAIL}Error: {colours.ENDC}Could not read the {kind} from Spotify. {e}{colours.ENDC}\n")
            sys.exit(1)

        total = getattr(collection, "total", None)
        recent = f" (the {len(tracks)} most recent of the {total} you have)" if getattr(collection, "limit", None) and total and total > len(tracks) else ""
        print(f"\n{colours.OKBLUE}[!] Found {len(tracks)} downloadable tracks in {kind}{recent}.")

        tracks, interludes = self.split_interludes(tracks)
        if interludes:
            print(f"{colours.OKBLUE}[!] Skipping {len(interludes)} short track(s) (use --keep-interludes to keep them): "
                  f"{', '.join(t.get_title() for t in interludes)}{colours.ENDC}")

        if not tracks:
            return False

        if self.dry_run or self.ask_before_download:
            self._show_plan(tracks, output_path, total)
            if self.dry_run:
                return True
            if not ask_yes_no(f"\n{colours.OKGREEN}¿Quieres descargarlas?{colours.ENDC} (yes/no): "):
                self.declined = True
                return True

        self.last_output_path = output_path
        self.prep_folder(output_path)
        skipped = self.download_tracks(output_path, tracks)

        return not self.blocked and len(skipped) < self.planned

    def download_album(self, album_url):
        return self._download_collection(
            "album", "albums", lambda: self.spotify_client.album(album_url),
            "It's probably that this album does not exist.")

    def download_liked_songs(self, last=None):
        """`last`: only the N most recently liked songs (Spotify lists them newest first)."""
        return self._download_collection(
            "liked songs", "liked", lambda: self.spotify_client.likedSongs(last),
            "Could not load your liked songs.")

    def _show_plan(self, tracks, output_path, total=None):
        """Preview for --dry-run: what would be downloaded, and how much of it is already on disk."""
        plan, repeated, renamed = plan_filenames(tracks, self.name_style)
        already = sum(1 for _, track, name in plan if self.already_downloaded(track, name, output_path))

        print(f"\n{colours.HEADER}=== Vista previa (no se descarga nada) ==={colours.ENDC}")
        for number, track in enumerate(tracks[:PREVIEW_LINES], start=1):
            seconds = round(track.get_metadata()["duration_ms"] / 1000)
            saved = f"  (guardada {track.added_at[:10]})" if getattr(track, "added_at", None) else ""
            print(f"{number:4}. {', '.join(track.get_metadata()['artist'])} - {track.get_title()}  [{seconds // 60}:{seconds % 60:02d}]{saved}")
        if len(tracks) > PREVIEW_LINES:
            print(f"      ... y {len(tracks) - PREVIEW_LINES} más")

        header = f"Canciones en la lista: {len(tracks)}"
        if total and total > len(tracks):
            header += f" (de {total} en total)"
        print(f"\n{header} | ya descargadas: {already} | por descargar: {len(plan) - already}")
        if repeated:
            print(f"Repetidas en la lista (se bajarían una sola vez): {len(repeated)}")
        print(f"Carpeta: {os.path.abspath(output_path)}")

    def download_playlist(self, playlist_url):
        return self._download_collection(
            "playlist", "playlists", lambda: self.spotify_client.playlist(playlist_url),
            "It's probably that this playlist does not exist.")

    def _log(self, tag, message):
        with self._print_lock:
            print(f"{tag} {message}{colours.ENDC}")

    def download_tracks(self, output_path, tracks):
        """Download `tracks` with up to `self.workers` songs in flight at once.
        As soon as one finishes, the next waiting song starts. Returns [(track, reason)] of skipped ones.

        If YouTube rejects BLOCK_STREAK_LIMIT songs in a row it is blocking this connection: carrying on
        would fail every remaining song too (and make the block worse). So the worker that sees the
        limit reached raises a flag, songs that have not started yet do not start, `self.blocked` is
        set, and the unfinished songs are left for the next run."""

        skipped_tracks = []
        idx_max = len(tracks)
        self.blocked = False
        abort = threading.Event()
        streak_lock = threading.Lock()
        streak = [0]

        def run_one(i, track, filename):
            if abort.is_set() or self.cancelled.is_set():
                return _NOT_STARTED
            try:
                self.download_track(None, track, i, idx_max, output_path, True, filename)
            except YoutubeNetworkError:
                raise   # the connection failed: that says nothing about YouTube blocking us, so it does not count towards the block streak
            except (YoutubeBlocked, YoutubeTransientError):
                # A song that kept failing with temporary errors (403...) after trying every match twice is
                # how an IP flagged by YouTube looks too; counting it stops the run instead of hammering on.
                with streak_lock:
                    streak[0] += 1
                    if streak[0] >= BLOCK_STREAK_LIMIT:
                        abort.set()
                raise
            except Exception:
                with streak_lock:
                    streak[0] = 0
                raise
            with streak_lock:
                streak[0] = 0
            return True

        not_started = 0
        plan, repeated, renamed = plan_filenames(tracks, self.name_style)
        self.planned = len(plan)
        if repeated:
            print(f"{colours.OKBLUE}[!] {len(repeated)} repeated song(s) in the list, downloaded once: "
                  f"{', '.join(sorted({t.get_filename(self.name_style) for t in repeated}))}{colours.ENDC}")
        for _track, name in renamed:
            print(f"{colours.OKBLUE}[!] Different song with the same file name, saved as '{name}'{colours.ENDC}")

        executor = ThreadPoolExecutor(max_workers=self.workers)
        try:
            with ctrl_c_needs_three_presses():
                futures = {executor.submit(run_one, i, track, name): (i, track) for i, track, name in plan}

                # Wait in short slices instead of until a song finishes: on Windows a thread blocked in a long
                # wait does not notice Ctrl+C, so presses would only be seen once the next song ended.
                pending = set(futures)
                while pending:
                    done, pending = wait(pending, timeout=CTRL_C_POLL_SECONDS, return_when=FIRST_COMPLETED)
                    for future in done:
                        i, track = futures[future]
                        error = future.exception()
                        if error is not None:
                            self._log(f"[{i + 1}/{idx_max}]", self._describe_error(error))
                            self._emit("failed", track, reason=friendly_reason(error), category=reason_category(error))
                            skipped_tracks.append((track, error))
                        elif future.result() is _NOT_STARTED:
                            not_started += 1
        except KeyboardInterrupt:
            abort.set()                                         # songs that have not started never will
            executor.shutdown(wait=False, cancel_futures=True)  # do not wait for downloads that cannot be interrupted
            raise
        else:
            executor.shutdown(wait=True)

        self.blocked = abort.is_set()

        info = {track: (i, name) for i, track, name in plan}
        if not self.blocked and not self.cancelled.is_set():   # if YouTube is blocking us, asking again right away only makes it worse
            self._retry_pass(skipped_tracks, info, idx_max, output_path)
        self._offer_login_retry(skipped_tracks, info, idx_max, output_path)

        self._print_skipped_summary(skipped_tracks)

        if self.blocked:
            print(f"\n{colours.FAIL}YouTube te está bloqueando{colours.ENDC} ({BLOCK_STREAK_LIMIT} canciones seguidas rechazadas). "
                  f"Paré para no empeorarlo: faltan {not_started} canciones por intentar.\n"
                  f"Espera un rato (a veces hasta una hora) o cambia de red, y vuelve a ejecutar el {colours.BOLD}mismo enlace{colours.ENDC}: "
                  f"lo que ya se descargó se salta y continúa donde quedó.\n")

        self._offer_ytdlp_update(skipped_tracks)
        return skipped_tracks

    def _offer_ytdlp_update(self, skipped_tracks):
        """Compiled program, guided mode: when songs failed in a way that looks like an out-of-date yt-dlp
        (YouTube changed something), offer to download the newest one. It is used the next time the program starts."""
        if not (const.IS_FROZEN and self.offer_browser_login):
            return
        if not any(suggests_outdated_ytdlp(error) for _, error in skipped_tracks):
            return
        print(f"\n{colours.WARNING}[!] Algunas fallas parecen de un yt-dlp desactualizado (YouTube cambió algo).{colours.ENDC}")
        if not ask_yes_no("¿Buscar y descargar la versión nueva ahora? (yes/no): "):
            return
        try:
            result = updater.download_latest_ytdlp()
        except updater.UpdateError as error:
            print(f"{colours.FAIL}{error}{colours.ENDC} Tu versión actual sigue igual.")
            return
        if result is None:
            print(f"{colours.OKBLUE}Ya tienes la versión más nueva de yt-dlp; el problema es otro.{colours.ENDC}")
        else:
            print(f"{colours.OKGREEN}yt-dlp actualizado: {result[0]} -> {result[1]}.{colours.ENDC} "
                  f"Cierra Burdamix, ábrelo otra vez y ejecuta el mismo enlace: solo bajará las que faltan.")

    def _retry_tracks(self, pairs, info, idx_max, output_path, skipped_tracks):
        """Download each (track, error) of `pairs` again, one at a time. Songs that now work leave
        `skipped_tracks`; the others keep it, with the newest error."""
        for track, _old_error in pairs:
            i, name = info[track]
            try:
                self.download_track(None, track, i, idx_max, output_path, True, name)
            except Exception as error:
                self._emit("failed", track, reason=friendly_reason(error), category=reason_category(error))
                skipped_tracks[:] = [(t, error if t is track else e) for t, e in skipped_tracks]
            else:
                skipped_tracks[:] = [(t, e) for t, e in skipped_tracks if t is not track]

    def _retry_pass(self, skipped_tracks, info, idx_max, output_path):
        """The "are you a robot" check and temporary errors come and go: songs that failed that way get
        one more try at the end, calmly, one by one."""
        pairs = [(t, e) for t, e in skipped_tracks if reason_category(e) in ("robot", "temporal")]
        if not pairs:
            return
        print(f"\n{colours.OKBLUE}[!] Reintentando {len(pairs)} canción(es) que YouTube rechazó, de una en una, "
              f"en {RETRY_PASS_DELAY_SECONDS} s...{colours.ENDC}")
        time.sleep(RETRY_PASS_DELAY_SECONDS)
        self._retry_tracks(pairs, info, idx_max, output_path, skipped_tracks)

    def _offer_login_retry(self, skipped_tracks, info, idx_max, output_path):
        """Videos marked for adults need a YouTube login. In the guided mode, offer to use the one the user
        already has in their browser (nothing is read unless they choose a browser)."""
        pairs = [(t, e) for t, e in skipped_tracks if reason_category(e) == "edad"]
        if not self.offer_browser_login or not pairs:
            return
        print(f"\n{colours.WARNING}[!] {len(pairs)} canción(es) están en videos que YouTube marca para mayores de edad "
              f"y solo deja bajar con una sesión iniciada.{colours.ENDC}")
        browser = ask_browser()
        if browser is None:
            return
        self.youtube_client = YouTube(cookies_from_browser=browser)
        print(f"{colours.OKBLUE}[!] Reintentando esas con tu sesión de {browser}...{colours.ENDC}")
        self._retry_tracks(pairs, info, idx_max, output_path, skipped_tracks)

    def _print_skipped_summary(self, skipped_tracks):
        """Songs that could not be downloaded, each with its reason in plain words, and what to do about it."""
        if not skipped_tracks:
            return
        print(f"\n{colours.WARNING}[!] {len(skipped_tracks)} canción(es) no se pudieron descargar:{colours.ENDC}\n")
        for track, error in skipped_tracks:
            print(f"    {track.get_filename(self.name_style)}")
            print(f"        {colours.WARNING}-> {friendly_reason(error)}{colours.ENDC}")

        present = {reason_category(error) for _, error in skipped_tracks}
        print(f"\n{colours.BOLD}Qué hacer:{colours.ENDC}")
        for category in ADVICE:
            if category in present:
                print(f"  - {ADVICE[category]}")

    @staticmethod
    def _describe_error(error):
        return f"{colours.WARNING}[!] Saltada: {friendly_reason(error)}"

    def _download_audio(self, tag, track, links):
        """Try the matching videos best first. A video that is restricted, gets the "are you a robot" check
        (it happens per video: the next upload of the same song is usually fine) or fails for a temporary
        reason (403, dropped connection) is replaced by the next one; if every video failed at least once for
        a temporary reason, everything is tried one more time after a short pause."""
        last_error = None
        had_temporary_error = False

        for round_number in (1, 2):
            for link in links:
                self._log(tag, f"Downloading: {track.get_title()}")
                try:
                    return self.youtube_client.download(link, self.audio_quality)
                except YoutubeVideoUnavailable as e:
                    last_error = e
                    self._log(tag, f"{colours.WARNING}Ese video no se puede bajar; pruebo otra versión...")
                except YoutubeBlocked as e:
                    last_error = e
                    self._log(tag, f"{colours.WARNING}YouTube pidió comprobar que no soy un robot con ese video; pruebo otra versión...")
                except YoutubeTransientError as e:
                    last_error = e
                    had_temporary_error = True
                    self._log(tag, f"{colours.WARNING}Error temporal de YouTube; pruebo otra versión...")

            if round_number == 1 and had_temporary_error:
                self._log(tag, f"{colours.WARNING}Ninguna versión funcionó; reintento en {RETRY_DELAY_SECONDS} s...")
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                break

        raise last_error

    def download_track(self, track_url = None, track = None, idx = 0, idx_max = 1, output_path = None, as_sub_function = False, filename = None):
        """Download one track. Returns True on success (or if the file already exists).

        As a sub function (used by the worker threads), errors propagate so the caller can list
        skipped tracks. Standalone, they are reported here and False is returned."""

        try:
            output_path = output_path if output_path else os.path.join(DOWNLOADS_DIR, "tracks") + os.sep
            self.last_output_path = output_path

            if track_url:
                track = self.spotify_client.track(track_url)
            elif track is None:
                raise ValueError("No Track was supplied to download track!")

            tag = f"[{idx+1}/{idx_max}]"
            self._emit("stage", track, stage="searching")
            self._log(tag, f"{colours.OKGREEN}Searching{colours.ENDC}: {track.get_title()} by {track.get_artist()}")

            track_path = output_path + (filename or track.get_filename(self.name_style)) + ".mp3"

            if is_hard_to_open(track_path):
                self._log(tag, f"{colours.WARNING}[!] Long file name: it will be saved, but some Windows programs may not open it.")

            self.prep_folder(output_path)
            if self.already_downloaded(track, filename or track.get_filename(self.name_style), output_path):
                self._log(tag, f"{colours.OKCYAN}File exists, skipping.")
                self._emit("done", track, existed=True)
                return True

            metadata = track.get_metadata()
            links = self.youtube_client.search(metadata["title"], metadata["artist"], round(metadata["duration_ms"] / 1000),
                                               self.max_length, self.min_view_count, asked=getattr(track, "asked", ""))

            self._emit("stage", track, stage="downloading")
            video_downloaded_path, source_kbps = self._download_audio(tag, track, links)

            self._emit("stage", track, stage="converting")
            self._log(tag, f"Converting and tagging: {track.get_title()}")

            # Never encode above the source: upscaling 128 kbps audio to 256 only wastes space.
            target_kbps = mp3_bitrate_for(source_kbps, self.audio_quality // 1000)
            song_info = getattr(track, "song_info", None)   # a song found by typing its name: tagged from what the service said
            resave_audio_clip_with_metadata(video_downloaded_path, track.get_metadata(), track_path, target_kbps, tag=song_info is None)
            if song_info is not None:
                self._tag_from_song_info(tag, track_path, song_info)

            self._log(tag, f"{colours.OKGREEN}Done!{colours.ENDC} {track.get_title()}")
            self._emit("done", track, existed=False)

            return True

        except Exception as e:
            if as_sub_function:
                raise

            if self._explain_single_failure(e):   # the user chose a browser login: try once more with it
                return self.download_track(track_url, track, idx, idx_max, output_path, as_sub_function, filename)
            return False

    def _tag_from_song_info(self, tag, track_path, song_info):
        """Write the official tags and the cover of a searched song. The song is already saved: if the tags cannot be
        written (a service is down, the cover cannot be found) it stays as it is and the user is told."""
        with self._tagger_lock:
            if self._tagger is None:
                from autotag import AutoTagger
                self._tagger = AutoTagger()
        try:
            result = self._tagger.apply(track_path, song_info)
        except (MetadataError, TagWriteError) as error:
            self._log(tag, f"{colours.WARNING}[!] Se guardó, pero sin etiquetas: {error}")
            return
        if result.get("cover_problem") and not result.get("cover"):
            self._log(tag, f"{colours.WARNING}[!] Se guardó sin portada: {result['cover_problem']}")

    def _explain_single_failure(self, error):
        """Say, in plain words, why a lone song failed and what to do. Returns True when it should be tried
        again because the user chose to use the YouTube login of their browser."""
        print(f"\n{colours.FAIL}Error: {colours.ENDC}{friendly_reason(error)}")
        category = reason_category(error)
        print(f"{colours.BOLD}Qué hacer:{colours.ENDC} {ADVICE[category]}\n")
        if category == "edad" and self.offer_browser_login:
            browser = ask_browser()
            if browser:
                self.youtube_client = YouTube(cookies_from_browser=browser)
                self.offer_browser_login = False   # one retry only; never loop
                print(f"{colours.OKBLUE}[!] Reintentando con tu sesión de {browser}...{colours.ENDC}")
                return True
        return False

    def prep_folder(self, folder_name):
        Path(long_path(folder_name)).mkdir(parents=True, exist_ok=True)

    def already_downloaded(self, track, name, output_path):
        """Is this song already in the folder? Also under the other two full-name styles, so changing how songs are
        named does not download everything again. A file named with the title alone is never taken for another song's
        (many songs share a title), and a name that got a " (2)" because of a clash is only matched exactly."""
        if self.file_exists(output_path + name + ".mp3"):
            return True
        if name != track.get_filename(self.name_style):
            return False
        return any(self.file_exists(output_path + track.get_filename(style) + ".mp3")
                   for style in ("artist_title", "title_artist") if style != self.name_style)

    def file_exists(self, file_path):
        return Path(long_path(file_path)).exists()

    def rm_tmp_folder(self):
        tempdirs.remove_run_dir()
