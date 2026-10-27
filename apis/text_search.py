"""Finds a song from free text ("badtrip mora"): the official title, artist, album, duration, year and cover.

Deezer first, then iTunes, then YouTube Music as the last resort. No account, no key. Deezer refuses some countries by IP
(Venezuela, for one) and some VPNs, so a service that refuses us is left alone for the rest of the session instead of being
asked again on every search. A timeout, an empty answer or a hiccup only skips that service for that one search."""
import threading

from apis.deezer import Deezer
from apis.itunes import ITunes
from apis.matching import similarity
from apis.metadata_http import MetadataClient
from apis.song_info import KINDS, SongInfo
from apis.youtube import UNWANTED_WORDS, normalize
from apis.ytmusic import YouTubeMusic
from exceptions import MetadataBadResponse, MetadataError, MetadataRefused

TIMEOUT_SECONDS = 10
MIN_COVERAGE = 0.5      # a result must contain at least this share of the words the user typed
KIND_RANK = {kind: position for position, kind in enumerate(KINDS)}   # album, ep, single... best first


def _words(text):
    return [w for w in normalize(text).split() if w]


def coverage(query, info):
    """Share (0..1) of the typed words found in the result's title, artist or album. 'badtrip' is found in 'Bad Trip':
    a long word is also looked for with the spaces taken out. A short one must be a whole word."""
    wanted = _words(query)
    long_enough = [w for w in wanted if len(w) >= 3] or wanted
    if not long_enough:
        return 0.0
    text = normalize(f"{info.title} {info.artist} {info.album}")
    compact = text.replace(" ", "")
    words = text.split()
    found = sum(1 for w in long_enough if w in words or (len(w) >= 5 and w in compact))   # 'mora' is not inside 'Morandi'
    return found / len(long_enough)


# A title with one of these is another version of the song, not the song itself. (Normalized: no accents, '8-bit' is '8 bit'.)
ALTERNATE_WORDS = UNWANTED_WORDS + ("version", "acustica", "acustico", "8 bit", "mashup", "tribute", "rendition",
                                    "originally performed", "made popular by", "edit")


def is_alternate(info, query):
    """A remix, live take, karaoke, 8D... of the song, unless the user typed that word. These are listed after the song itself."""
    if info.kind == "live" and "live" not in normalize(query).split():
        return True
    title, wanted = f" {normalize(info.title)} ", f" {normalize(query)} "
    return any(f" {word} " in title and f" {word} " not in wanted for word in ALTERNATE_WORDS)


def _same_song(a, b):
    return normalize(a.title) == normalize(b.title) and similarity(a.artist, b.artist) >= 0.8


def _distinct(infos):
    """One entry per song. Services list a song once per release (album, single, compilation); the studio album wins,
    and among equals the one the service listed first."""
    groups = []
    for info in infos:
        for group in groups:
            if _same_song(group[0], info):
                group.append(info)
                break
        else:
            groups.append([info])
    return [min(group, key=lambda i: KIND_RANK.get(i.kind, len(KINDS))) for group in groups]


class SongSearch:
    def __init__(self, services=None):
        # Deezer and iTunes ask for a pause between calls; a short timeout keeps a dead service from freezing the window.
        self.services = services or [
            ("deezer", Deezer(MetadataClient("Deezer", 0.15, timeout=TIMEOUT_SECONDS))),
            ("itunes", ITunes(MetadataClient("iTunes", 3, timeout=TIMEOUT_SECONDS))),
            ("ytmusic", YouTubeMusic(MetadataClient("YouTube Music", 1.0, timeout=TIMEOUT_SECONDS))),
        ]
        self._blocked = {}                  # service name -> why it refused us
        self._lock = threading.Lock()

    def blocked(self):
        with self._lock:
            return dict(self._blocked)

    def _block(self, name, error):
        with self._lock:
            self._blocked[name] = str(error)

    def lookup(self, query, limit=5):
        """([SongInfo], [problems]): the songs, best first, and why a service could not answer (for the user)."""
        query = " ".join((query or "").split())
        problems, found_songs = [], []
        if not query:
            return [], problems
        for name, service in self.services:
            with self._lock:
                if name in self._blocked:
                    problems.append(self._blocked[name])
                    continue
            try:
                found = service.search(query, None, max(limit * 2, 6))
            except (MetadataRefused, MetadataBadResponse) as error:    # Akamai's "Access Denied" page, a 403: it will not change
                self._block(name, error)
                problems.append(str(error))
                continue
            except MetadataError as error:                              # no connection, a timeout, a slow-down: next service
                problems.append(str(error))
                continue
            except Exception as error:                                  # a service that changed its answers must not break the search
                problems.append(f"{name} respondió algo que no entiendo ({type(error).__name__}).")
                continue
            relevant = [i for i in found if coverage(query, i) >= MIN_COVERAGE]
            if relevant:
                found_songs = _distinct(found_songs + relevant)
                # Only remixes, live takes... here? The next service may have the song itself: ask it too before settling.
                if any(not is_alternate(i, query) for i in found_songs):
                    break
        # Alternates go after the song itself, never instead of it: they are sorted down BEFORE the list is cut.
        return sorted(found_songs, key=lambda i: is_alternate(i, query))[:limit], problems


def to_dict(info):
    """The shape the search promises, whichever service answered. `anio` and `pista` are None when the service lacks them."""
    return {"titulo": info.title, "artista": info.artist, "album": info.album, "duracion": round(info.duration),
            "portada": info.cover_urls[0] if info.cover_urls else None, "anio": int(info.year) if str(info.year).isdigit() else None,
            "pista": info.track_number or None, "fuente": info.source}


_default = SongSearch()


def search_songs(query, limit=5, search=None):
    """([SongInfo], [problems]) using the session-wide search (so a blocked service stays blocked)."""
    return (search or _default).lookup(query, limit)


def buscar_metadatos(consulta, limite=5):
    """The official data of the songs `consulta` ("badtrip mora") may mean, best first, as plain dicts:
    {titulo, artista, album, duracion (segundos), portada, anio, pista, fuente}. Never raises: [] when nothing answers."""
    try:
        songs, _problems = search_songs(consulta, limite)
    except Exception:
        return []
    return [to_dict(song) for song in songs]
