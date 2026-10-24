from const import colours, DOWNLOADS_DIR
from exceptions import (SpotifyAlbumNotFound, SpotifyTrackNotFound, SpotifyPlaylistNotFound, SpotifyRetrievalError,
                        InvalidSpotifyURL, ConfigVideoLowViewCount, YoutubeItemNotFound, YoutubeVideoUnavailable, YoutubeBlocked, YoutubeTransientError)
from apis.spotify import Spotify, SpotifyNetworkError, SpotifyRateLimited
from apis.youtube import YouTube
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


CANCEL_PRESSES = 3       # Ctrl+C presses needed to cancel a download in progress
CTRL_C_POLL_SECONDS = 0.05  # how often the waiting main thread looks for a Ctrl+C
BLOCK_STREAK_LIMIT = 5   # songs in a row that YouTube refuses before we stop asking
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


def plan_filenames(tracks):
    """Decide the file name of every track before downloading anything.

    Returns (plan, repeated, renamed):
    - plan: [(index, track, file name)] to download;
    - repeated: [track] that are the very same Spotify song as an earlier one (downloaded once);
    - renamed: [(track, file name)] different songs whose name collides with another one (the file
      system ignores case, so 'Song' and 'SONG' are the same file); they get ' (2)', ' (3)'...

    Names depend on the Spotify ids, not on the playlist order, so a second run gives the same names."""
    groups = {}
    for index, track in enumerate(tracks):
        groups.setdefault(track.get_filename().casefold(), []).append((index, track))

    names = {}
    repeated = []
    renamed = []
    for entries in groups.values():
        by_id = {}
        for index, track in entries:
            by_id.setdefault(getattr(track, "resource_id", None) or id(track), []).append((index, track))
        for rank, track_id in enumerate(sorted(by_id, key=str), start=1):
            first_index, first_track = by_id[track_id][0]
            base = first_track.get_filename()
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
                 intro_outro_max_seconds=DEFAULT_INTRO_OUTRO_MAX_SECONDS, short_max_seconds=DEFAULT_SHORT_MAX_SECONDS):
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

        print(f"\n{colours.OKBLUE}[!] Found {len(tracks)} downloadable tracks in {kind}.")

        if self.skip_interludes:
            interludes = [t for t in tracks if is_interlude(t.get_title(), t.get_metadata()["duration_ms"] / 1000,
                                                     self.interlude_max_seconds, self.intro_outro_max_seconds, self.short_max_seconds)]
            if interludes:
                tracks = [t for t in tracks if t not in interludes]
                print(f"{colours.OKBLUE}[!] Skipping {len(interludes)} short track(s) (use --keep-interludes to keep them): "
                      f"{', '.join(t.get_title() for t in interludes)}{colours.ENDC}")

        if not tracks:
            return False

        self.last_output_path = output_path
        self.prep_folder(output_path)
        skipped = self.download_tracks(output_path, tracks)

        return not self.blocked and len(skipped) < self.planned

    def download_album(self, album_url):
        return self._download_collection(
            "album", "albums", lambda: self.spotify_client.album(album_url),
            "It's probably that this album does not exist.")

    def download_liked_songs(self):
        return self._download_collection(
            "liked songs", "liked", self.spotify_client.likedSongs,
            "Could not load your liked songs.")

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
            if abort.is_set():
                return _NOT_STARTED
            try:
                self.download_track(None, track, i, idx_max, output_path, True, filename)
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
        plan, repeated, renamed = plan_filenames(tracks)
        self.planned = len(plan)
        if repeated:
            print(f"{colours.OKBLUE}[!] {len(repeated)} repeated song(s) in the list, downloaded once: "
                  f"{', '.join(sorted({t.get_filename() for t in repeated}))}{colours.ENDC}")
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

        if len(skipped_tracks) > 0:

            print(f"\n{colours.WARNING}[!] Skipped {len(skipped_tracks)} songs.{colours.ENDC}\n")

            for (track, reason) in skipped_tracks:
                print(f"    {track.get_filename()} {colours.WARNING}[{reason}]{colours.ENDC}")

        if self.blocked:
            print(f"\n{colours.FAIL}YouTube te está bloqueando{colours.ENDC} ({BLOCK_STREAK_LIMIT} canciones seguidas rechazadas). "
                  f"Paré para no empeorarlo: faltan {not_started} canciones por intentar.\n"
                  f"Espera un rato (a veces hasta una hora) o cambia de red, y vuelve a ejecutar el {colours.BOLD}mismo enlace{colours.ENDC}: "
                  f"lo que ya se descargó se salta y continúa donde quedó.\n")

        return skipped_tracks

    @staticmethod
    def _describe_error(error):
        if isinstance(error, YoutubeItemNotFound):
            return f"{colours.WARNING}[!] Skipped - found on Spotify but not on YouTube."
        if isinstance(error, ConfigVideoLowViewCount):
            return f"{colours.WARNING}[!] Skipped - video has fewer views than the minimum (use --min-views)."
        if isinstance(error, YoutubeBlocked):
            return f"{colours.FAIL}[!] YouTube rejected the request (bot check / too many requests)."
        if isinstance(error, YoutubeTransientError):
            return f"{colours.WARNING}[!] Skipped - temporary YouTube error that kept happening. Run the same link again to retry it."
        if isinstance(error, YoutubeVideoUnavailable):
            return f"{colours.FAIL}[!] Skipped - every matching video is restricted or unavailable (age restricted? see README: --cookies-from-browser)."
        if isinstance(error, SpotifyTrackNotFound):
            return f"{colours.WARNING}[!] Skipped - song not found on Spotify. {error}"
        return f"{colours.FAIL}[!] Skipped - something went wrong. {type(error).__name__}: {error}"

    def _download_audio(self, tag, track, links):
        """Try the matching videos best first. A video that is restricted or fails for a temporary reason
        (403, dropped connection) is replaced by the next one; if every video failed at least once for a
        temporary reason, everything is tried one more time after a short pause."""
        last_error = None
        had_temporary_error = False

        for round_number in (1, 2):
            for link in links:
                self._log(tag, f"Downloading: {track.get_title()}")
                try:
                    return self.youtube_client.download(link, self.audio_quality)
                except YoutubeVideoUnavailable as e:
                    last_error = e
                    self._log(tag, f"{colours.WARNING}Video not available, trying another match...")
                except YoutubeTransientError as e:
                    last_error = e
                    had_temporary_error = True
                    self._log(tag, f"{colours.WARNING}Temporary YouTube error, trying another match...")

            if round_number == 1 and had_temporary_error:
                self._log(tag, f"{colours.WARNING}Every match failed; trying again in {RETRY_DELAY_SECONDS}s...")
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
            self._log(tag, f"{colours.OKGREEN}Searching{colours.ENDC}: {track.get_title()} by {track.get_artist()}")

            track_path = output_path + (filename or track.get_filename()) + ".mp3"

            if is_hard_to_open(track_path):
                self._log(tag, f"{colours.WARNING}[!] Long file name: it will be saved, but some Windows programs may not open it.")

            self.prep_folder(output_path)
            if self.file_exists(track_path):
                self._log(tag, f"{colours.OKCYAN}File exists, skipping.")
                return True

            metadata = track.get_metadata()
            links = self.youtube_client.search(metadata["title"], metadata["artist"], round(metadata["duration_ms"] / 1000),
                                               self.max_length, self.min_view_count)

            video_downloaded_path, source_kbps = self._download_audio(tag, track, links)

            self._log(tag, f"Converting and tagging: {track.get_title()}")

            # Never encode above the source: upscaling 128 kbps audio to 256 only wastes space.
            target_kbps = mp3_bitrate_for(source_kbps, self.audio_quality // 1000)
            resave_audio_clip_with_metadata(video_downloaded_path, track.get_metadata(), track_path, target_kbps)

            self._log(tag, f"{colours.OKGREEN}Done!{colours.ENDC} {track.get_title()}")

            return True

        except Exception as e:
            if as_sub_function:
                raise

            print(f"\n{colours.FAIL}Error: {colours.ENDC}{self._describe_error(e)}{colours.ENDC}\n")
            return False

    def prep_folder(self, folder_name):
        Path(long_path(folder_name)).mkdir(parents=True, exist_ok=True)

    def file_exists(self, file_path):
        return Path(long_path(file_path)).exists()

    def rm_tmp_folder(self):
        tempdirs.remove_run_dir()
