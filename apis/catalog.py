"""Albums and artists by name: when a search deserves a card, and what is inside an album or an artist.

It asks the same services as the song search (Deezer, then iTunes) and shares its memory of which service refused us."""
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher

from apis import text_search
from apis.song_info import SongInfo
from apis.youtube import normalize
from exceptions import MetadataBadResponse, MetadataError, MetadataRefused

ALBUM_KINDS = ("album", "ep")      # a single is the song itself: it never gets an album card
MIN_ALBUM_TRACKS = 3
MAX_ALBUM_CARDS = 2
ARTIST_NAME_MATCH = 0.85           # how alike the whole query and the artist's name must be
FILLER = {"album", "disco", "ep", "completo", "full", "discografia"}   # words that say "the album" without naming it
TOP_SONGS = 50


def _words(text):
    return [w for w in normalize(text).split() if len(w) >= 2 or w.isdigit()]


def same_name(a, b):
    """The whole of one is the other (not 'contains it'): 'mora' is Mora, 'badtrip mora' is not. A letter or two off still counts."""
    a, b = normalize(a), normalize(b)
    return bool(a) and bool(b) and SequenceMatcher(None, a, b).ratio() >= ARTIST_NAME_MATCH


def _alternate(title, query):
    return text_search.is_alternate(SongInfo(title=title), query)


def album_matches(album, query):
    """Is `query` the name of this album (and maybe its artist)? 'microdosis mora' and 'microdosis' are; 'calenton mora' is not
    (CALENTÓN is a single), and neither is 'badtrip mora' (a song of that album, not the album)."""
    if album.kind not in ALBUM_KINDS or (album.track_total and album.track_total < MIN_ALBUM_TRACKS):
        return False
    if _alternate(album.title, query):
        return False
    asked = {w for w in _words(query) if w not in FILLER}
    title, artist = set(_words(album.title)), set(_words(album.artist))
    return bool(title) and title <= asked and asked <= title | artist


def artist_matches(artist, query):
    """The whole query is the artist's name ('mora'), not just part of it ('badtrip mora' is a song)."""
    return same_name(query, artist.name)


def tidy_albums(albums):
    """One entry per album (explicit and clean editions are listed twice: the one with more songs stays), the newest first;
    live albums, remixes and the like go after the rest, never hidden."""
    best = {}
    for album in albums:
        key = (normalize(album.title), normalize(album.artist))
        if key not in best or album.track_total > best[key].track_total:
            best[key] = album
    kept = list(best.values())
    kept.sort(key=lambda a: a.year or "0000", reverse=True)
    return sorted(kept, key=lambda a: _alternate(a.title, ""))


class Catalog:
    def __init__(self, search=None):
        self._search = search

    @property
    def search(self):
        return self._search or text_search._default

    def _service(self, name):
        return next((service for service_name, service in self.search.services if service_name == name), None)

    def _guard(self, name, call):
        """Run `call` on one service. A refusal is remembered for the session, exactly as in the song search."""
        blocked = self.search.blocked()
        if name in blocked:
            raise MetadataRefused(blocked[name])
        try:
            return call()
        except (MetadataRefused, MetadataBadResponse) as error:
            self.search._block(name, error)
            raise

    def _ask(self, method, *args):
        """(result, problems): the first service that has `method` and gives a non-empty answer."""
        problems = []
        for name, service in self.search.services:
            function = getattr(service, method, None)
            if function is None:
                continue
            try:
                result = self._guard(name, lambda: function(*args))
            except MetadataError as error:
                problems.append(str(error))
                continue
            if result:
                return result, problems
        return [], problems

    # --- what a search offers besides songs ---

    def cards(self, query, songs):
        """(albums, artist or None, problems): up to two albums named by the query, and the artist when the whole query is a
        name. The artist is only looked up when the songs found are already by someone with that name: one request saved."""
        wants_artist = any(same_name(query, s.artist) for s in songs[:3])
        with ThreadPoolExecutor(max_workers=2) as pool:
            albums = pool.submit(self._ask, "albums", query, 10)
            artists = pool.submit(self._ask, "artists", query, 5) if wants_artist else None
            found_albums, problems = albums.result()
            found_artists, more = artists.result() if artists else ([], [])
        chosen = [a for a in tidy_albums(found_albums) if album_matches(a, query)][:MAX_ALBUM_CARDS]
        artist = next((a for a in found_artists if artist_matches(a, query)), None)
        return chosen, artist, problems + more

    # --- inside an album or an artist ---

    def album_tracks(self, album):
        service = self._service(album.source)
        if service is None:
            raise MetadataError("Ese servicio ya no está disponible. Busca de nuevo.")
        return self._guard(album.source, lambda: service.album_tracks(album))

    def artist_view(self, artist):
        """(popular songs, the artist's albums tidied up). The albums may fail while the songs work, and the other way round."""
        service = self._service(artist.source)
        if service is None:
            raise MetadataError("Ese servicio ya no está disponible. Busca de nuevo.")
        top = self._guard(artist.source, lambda: service.artist_top(artist, TOP_SONGS))
        try:
            albums = self._guard(artist.source, lambda: service.artist_albums(artist))
        except MetadataError:
            albums = []                    # the popular songs are still worth showing
        return top, tidy_albums(albums)

    def complete(self, info):
        """Fill in what a popular-list song lacks, before it is searched on YouTube. Never raises."""
        service = self._service(info.source)
        if service is None or not hasattr(service, "complete") or info.source in self.search.blocked():
            return info
        try:
            return self._guard(info.source, lambda: service.complete(info))
        except MetadataError:
            return info
