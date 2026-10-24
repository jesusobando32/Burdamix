import argparse
import contextlib
import os
import sys

# Windows consoles/pipes may default to a legacy encoding that cannot draw the logo or accents.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, 'reconfigure'):
        _stream.reconfigure(encoding='utf-8', errors='replace')

import login
import utils
from apis.spotify import Spotify
from apis.youtube import YouTube
from const import colours, DOWNLOADS_DIR, SpotifyAuthType, DEFAULT_MIN_VIEWS_FOR_DOWNLOAD, DEFAULT_MAX_LENGTH_FOR_DOWNLOAD, LIKED_KEYWORD, HELP_URL
import tempdirs
import updater
from pathutils import long_path
from downloader import ctrl_c_needs_three_presses, SpotifyDownloader, DEFAULT_INTERLUDE_MAX_SECONDS, DEFAULT_INTRO_OUTRO_MAX_SECONDS, DEFAULT_SHORT_MAX_SECONDS

DEFAULT_WORKERS = 5  # songs downloaded at the same time
MAX_WORKERS = 8

MIN_BITRATE_BPS = 48000
MAX_BITRATE_BPS = 320000
YOUTUBE_MAX_KBPS = 130  # what YouTube normally offers at best (Opus ~132 kbps, AAC ~130 kbps)

# "high" means "the best YouTube has": the cap is the top of the range, and the real bitrate is
# whatever the best stream is (about 130 kbps), never more.
QUALITY_PRESETS = {"low": 50000, "medium": 80000, "high": MAX_BITRATE_BPS}


def describe_quality(quality):
    """One line telling the user what quality they will really get."""
    if quality == "high":
        return f"high = the best YouTube offers (about {YOUTUBE_MAX_KBPS} kbps)"
    kbps = get_bitrate_from_quality(quality) // 1000
    if kbps > YOUTUBE_MAX_KBPS:
        return f"{quality}: {kbps} kbps requested, but YouTube offers about {YOUTUBE_MAX_KBPS} at most, so that is what you get"
    return f"{quality} (up to {kbps} kbps)"


def get_bitrate_from_quality(quality):
    """Return the bitrate in bps. Accepts a preset name, kbps ('192') or bps ('192000')."""
    if quality in QUALITY_PRESETS:
        return QUALITY_PRESETS[quality]

    value = int(quality)
    return value * 1000 if value <= 1000 else value


def validate_quality(quality):
    if quality in QUALITY_PRESETS:
        return quality
    try:
        bitrate = get_bitrate_from_quality(quality)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError(f"Invalid quality/bitrate: {quality}") from None

    if MIN_BITRATE_BPS <= bitrate <= MAX_BITRATE_BPS:
        return quality
    raise argparse.ArgumentTypeError(
        f"Bitrate must be between {MIN_BITRATE_BPS // 1000} and {MAX_BITRATE_BPS // 1000} kbps: {quality}")


def validate_spotify_url(url):
    """Validate the Spotify URL and infer the type: 'song', 'playlist', 'album' or 'liked'."""
    url = url.strip()
    if url == LIKED_KEYWORD:
        return url
    elif 'spotify.link' in url:
        raise ValueError("Los enlaces cortos (spotify.link) no funcionan. Ábrelo en el navegador y copia el enlace largo de la barra de direcciones.")
    elif 'track/' in url:
        return 'song'
    elif 'playlist/' in url:
        return 'playlist'
    elif 'album/' in url:
        return 'album'
    else:
        raise ValueError("Eso no parece un enlace de Spotify de una canción, playlist o álbum.")


def get_user_input():
    """Ask, in plain Spanish, what to download. Returns (type, url, quality)."""
    print(f"{colours.BOLD}Copia el enlace en Spotify:{colours.ENDC} clic derecho en la canción, playlist o álbum > Compartir > Copiar enlace.")
    print(f"(Las playlists tienen que ser {colours.BOLD}tuyas{colours.ENDC}; es una limitación de Spotify.)\n")

    while True:
        url = input(f"{colours.OKGREEN}Pega el enlace aquí y pulsa Enter:{colours.ENDC}\n> ").strip()
        try:
            choice = validate_spotify_url(url)
            break
        except ValueError as e:
            print(f"{colours.FAIL}{e}{colours.ENDC}\n")

    while True:
        quality = input(f"\n{colours.OKGREEN}¿Qué calidad?{colours.ENDC} low / medium / {colours.BOLD}high{colours.ENDC} "
                        f"(high = la mejor que da YouTube, ~{YOUTUBE_MAX_KBPS} kbps; pedir más no mejora nada). Enter = high: ").strip() or "high"
        try:
            validate_quality(quality)
            break
        except argparse.ArgumentTypeError as e:
            print(f"{colours.WARNING}{e}{colours.ENDC}")

    return choice, url, quality


def main(authtype=None, playlist=None, song=None, album=None, liked=False, quality=None, min_views=None,
         max_length=None, workers=DEFAULT_WORKERS, cookies_from_browser=None,
         skip_interludes=True, interlude_max_seconds=DEFAULT_INTERLUDE_MAX_SECONDS,
         intro_outro_max_seconds=DEFAULT_INTRO_OUTRO_MAX_SECONDS, short_max_seconds=DEFAULT_SHORT_MAX_SECONDS):

    url = song or playlist or album

    if not (url or liked):
        print(f"{colours.FAIL}Error: You must specify a song, playlist, album, or '{LIKED_KEYWORD}' to download.{colours.ENDC}")
        build_parser().print_help()
        sys.exit(1)

    url_type = validate_spotify_url(url) if url is not None else LIKED_KEYWORD

    if (song and url_type != 'song') or (playlist and url_type != 'playlist') or (album and url_type != 'album'):
        print(f"{colours.FAIL}Error: that link is a {url_type}, not what the option expects.{colours.ENDC}")
        sys.exit(1)

    # Spotify only returns playlist contents and liked songs to a logged-in user.
    authtype = SpotifyAuthType.USER if (playlist or liked) else SpotifyAuthType.ANONYMOUS

    if authtype == SpotifyAuthType.USER and not login.is_user_logged_in():
        print(f"\n{colours.OKCYAN}[i] Para leer playlists hay que iniciar sesión en Spotify (solo la primera vez).{colours.ENDC}")
        login.do_user_login()

    print(f"\n{colours.CVIOLETBG2}Chosen Settings{colours.ENDC}\n")

    for label, value in (("Playlist", playlist), ("Song", song), ("Album", album)):
        if value:
            print(f"{colours.OKGREEN}{label}{colours.ENDC}: {value}")

    if liked:
        print(f"{colours.OKGREEN}Liked Songs{colours.ENDC}")

    quality = quality or "high"
    print(f"{colours.OKGREEN}Quality{colours.ENDC}: {describe_quality(quality)}")

    if min_views != DEFAULT_MIN_VIEWS_FOR_DOWNLOAD:
        print(f"{colours.OKGREEN}Minimum view count{colours.ENDC}: {min_views}")

    if max_length != DEFAULT_MAX_LENGTH_FOR_DOWNLOAD:
        print(f"{colours.OKGREEN}Maximum video length{colours.ENDC}: {max_length // 60} min")

    print(f"{colours.OKGREEN}Songs at the same time{colours.ENDC}: {workers}")

    if not song:
        print(f"{colours.OKGREEN}Interludes{colours.ENDC}: " + (f"skipped: any track <= {short_max_seconds}s, interlude/skit <= {interlude_max_seconds}s, intro/outro <= {intro_outro_max_seconds}s" if skip_interludes else "kept"))

    try:
        spotify = Spotify(authtype)
    except Exception as e:
        print(f"\n{colours.FAIL}No pude conectarme a Spotify:{colours.ENDC} {type(e).__name__}. "
              f"Si cambiaste o borraste tu app de Spotify, ejecuta: python spotify2mp3.py --setup")
        sys.exit(1)

    tempdirs.clean_stale()   # leftovers of runs that were closed by force
    youtube = YouTube(cookies_from_browser)
    downloader = SpotifyDownloader(spotify, youtube, get_bitrate_from_quality(quality), max_length, min_views, workers,
                                  skip_interludes, interlude_max_seconds, intro_outro_max_seconds, short_max_seconds)

    success = False

    try:
        if song:
            with ctrl_c_needs_three_presses():   # a single song needs the 3 presses too
                success = downloader.download_track(song)
        elif playlist:
            success = downloader.download_playlist(playlist)
        elif album:
            success = downloader.download_album(album)
        elif liked:
            success = downloader.download_liked_songs()
    finally:
        downloader.rm_tmp_folder()

    if success:
        print(f"\n{colours.OKGREEN}Download complete!{colours.ENDC} Your songs are in:\n  {os.path.abspath(downloader.last_output_path)}\n")
    else:
        print(f"\n{colours.FAIL}Download failed!{colours.ENDC} If you need help, please visit {HELP_URL}\n\n")
        sys.exit(1)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Burdamix: download songs from Spotify by finding the matching audio on YouTube. "
                    "Run without options for a guided mode. First time? python spotify2mp3.py --setup")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("-p", "--playlist", "--list", help="Link of one of YOUR playlists", type=str)
    group.add_argument("-s", "--song", "--single", "-t", "--track", help="Song link", type=str)
    group.add_argument("-a", "--album", help="Album link", type=str)
    group.add_argument("-l", f"--{LIKED_KEYWORD}", help=f"Your {LIKED_KEYWORD} songs", action="store_true")

    parser.add_argument("-q", "--quality", help="low, medium, high (= the best YouTube offers, ~130 kbps) or a bitrate in kbps (48-320)", type=validate_quality, default="high")
    parser.add_argument("--workers", help=f"Songs downloaded at the same time (default {DEFAULT_WORKERS})", type=int,
                        choices=range(1, MAX_WORKERS + 1), metavar=f"1-{MAX_WORKERS}", default=DEFAULT_WORKERS)
    parser.add_argument("--min-views", help="Minimum view count on YouTube (default: off)", type=int, default=DEFAULT_MIN_VIEWS_FOR_DOWNLOAD)
    parser.add_argument("--max-length", help="Maximum video length on YouTube in minutes", type=int, default=DEFAULT_MAX_LENGTH_FOR_DOWNLOAD // 60)
    parser.add_argument("--keep-interludes", help="Also download short interludes/skits/intros (skipped by default)", action="store_true")
    parser.add_argument("--short-max", metavar="SECONDS", type=int, default=DEFAULT_SHORT_MAX_SECONDS,
                        help=f"Any track this many seconds or shorter is skipped, whatever its name (default {DEFAULT_SHORT_MAX_SECONDS})")
    parser.add_argument("--interlude-max", metavar="SECONDS", type=int, default=DEFAULT_INTERLUDE_MAX_SECONDS,
                        help=f"A track named interlude/skit is skipped if it lasts this many seconds or less (default {DEFAULT_INTERLUDE_MAX_SECONDS})")
    parser.add_argument("--intro-outro-max", metavar="SECONDS", type=int, default=DEFAULT_INTRO_OUTRO_MAX_SECONDS,
                        help=f"A track named intro/outro is skipped if it lasts this many seconds or less; longer ones are kept as songs (default {DEFAULT_INTRO_OUTRO_MAX_SECONDS})")
    parser.add_argument("--no-update", help="Do not check for a newer yt-dlp (it is checked once a day)", action="store_true")
    parser.add_argument("--cookies-from-browser", metavar="BROWSER", choices=["firefox", "chrome", "edge", "brave", "opera", "chromium"],
                        help="Use your YouTube login from this browser, to download age-restricted videos")
    return parser


def run_guided():
    utils.print_splash_screen()
    updater.update_ytdlp_if_due()

    if not login.is_client_configured():
        print(f"{colours.OKCYAN}Es la primera vez que lo usas: hay que conectar el programa con Spotify.{colours.ENDC}")
        login.do_client_login()
        print()

    while True:
        choice, url, quality = get_user_input()
        kwargs = dict(quality=quality, min_views=DEFAULT_MIN_VIEWS_FOR_DOWNLOAD,
                      max_length=DEFAULT_MAX_LENGTH_FOR_DOWNLOAD, workers=DEFAULT_WORKERS)

        with contextlib.suppress(SystemExit):   # the reason was already printed; offer to try again instead of closing the window
            main(**{'song': {'song': url}, 'playlist': {'playlist': url}, 'album': {'album': url}, LIKED_KEYWORD: {'liked': True}}[choice], **kwargs)

        if input(f"\n{colours.OKGREEN}¿Descargar otra cosa? (s/n):{colours.ENDC} ").strip().lower() not in ("s", "si", "sí", "y", "yes"):
            break
        print()


def say_goodbye_and_exit(code=130):
    """Used when the user cancels. Downloads running in worker threads cannot be interrupted, so the process
    ends right away instead of waiting for them; unfinished '.part' files are removed so they never look like songs."""
    print(f"\n{colours.OKBLUE}Cancelado. Lo que ya se descargó se conserva. ¡Hasta luego!{colours.ENDC}")
    for folder, _dirs, files in os.walk(DOWNLOADS_DIR):
        for name in files:
            if name.endswith(".part"):
                with contextlib.suppress(OSError):
                    os.remove(long_path(os.path.join(folder, name)))
    tempdirs.remove_run_dir()
    sys.stdout.flush()
    os._exit(code)


def run():
    if sys.argv[1:] == ["--setup"]:
        login.do_client_login()
    elif len(sys.argv) > 1:
        args = build_parser().parse_args()
        if not args.no_update:
            updater.update_ytdlp_if_due()   # before anything imports yt_dlp
        main(playlist=args.playlist, song=args.song, album=args.album, liked=args.liked, quality=args.quality,
             min_views=args.min_views, max_length=args.max_length * 60, workers=args.workers,
             cookies_from_browser=args.cookies_from_browser,
             skip_interludes=not args.keep_interludes, interlude_max_seconds=args.interlude_max, intro_outro_max_seconds=args.intro_outro_max, short_max_seconds=args.short_max)
    else:
        run_guided()


if __name__ == "__main__":
    try:
        run()
    except (KeyboardInterrupt, EOFError):   # Ctrl+C or a closed input at any question: say goodbye, no traceback
        say_goodbye_and_exit()
