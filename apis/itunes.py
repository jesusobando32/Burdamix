"""Apple's iTunes Search API: the second back-up, with large covers and the genre. Free, no account."""
import re

from apis.matching import same_artist, same_name
from apis.metadata_http import MetadataClient
from apis.catalog_info import AlbumInfo, ArtistInfo
from apis.song_info import SongInfo

URL = "https://itunes.apple.com/search"
LOOKUP_URL = "https://itunes.apple.com/lookup"
MIN_INTERVAL_SECONDS = 3      # Apple allows about 20 requests per minute


def artwork(url, size):
    """Apple serves the same picture at any size: .../100x100bb.jpg -> .../1000x1000bb.jpg"""
    return re.sub(r"/\d+x\d+(bb)?\.(jpg|png)$", f"/{size}x{size}bb.jpg", url or "")


def _album_and_kind(name, artist):
    """Apple names singles 'Title - Single' and EPs 'Title - EP'."""
    name = name or ""
    if re.search(r"\s-\s(Single)$", name, re.I):
        return re.sub(r"\s-\s(Single)$", "", name, flags=re.I), "single"
    if re.search(r"\s-\s(EP)$", name, re.I):
        return re.sub(r"\s-\s(EP)$", "", name, flags=re.I), "ep"
    if (artist or "").lower() == "various artists":
        return name, "compilation"
    return name, "album"


class ITunes:
    def __init__(self, client=None):
        self.client = client or MetadataClient("iTunes", MIN_INTERVAL_SECONDS)

    def _search(self, term, entity, limit, attribute=None):
        params = {"term": term, "media": "music", "entity": entity, "limit": limit, "country": "US"}
        if attribute:
            params["attribute"] = attribute
        data = self.client.get_json(URL, params)
        return [r for r in data.get("results") or [] if isinstance(r, dict)]

    def _lookup(self, identifier, entity, limit):
        """What belongs to an artist or an album. The first item of the answer is that artist or album itself: callers pick by wrapperType."""
        data = self.client.get_json(LOOKUP_URL, {"id": identifier, "entity": entity, "limit": limit, "country": "US"})
        return [r for r in data.get("results") or [] if isinstance(r, dict)]

    @staticmethod
    def _info(item):
        album, kind = _album_and_kind(item.get("collectionName"), item.get("collectionArtistName"))
        art = item.get("artworkUrl100") or ""
        return SongInfo(
            source="itunes",
            title=item.get("trackName") or "",
            artist=item.get("artistName") or "",
            album=album,
            album_artist=item.get("collectionArtistName") or item.get("artistName") or "",
            year=(item.get("releaseDate") or "")[:4],
            genre=item.get("primaryGenreName") or "",
            track_number=int(item.get("trackNumber") or 0),
            track_total=int(item.get("trackCount") or 0),
            disc_number=int(item.get("discNumber") or 0),
            kind=kind,
            duration=(item.get("trackTimeMillis") or 0) / 1000,
            track_id=str(item.get("trackId") or ""),
            cover_urls=(artwork(art, 1000),) if art else (),
            thumb_url=artwork(art, 300),
        )

    def search(self, title, artist=None, limit=10):
        term = f"{artist} {title}" if artist else title
        return [self._info(item) for item in self._search(term, "song", limit)]

    # --- albums and artists ---

    def artists(self, query, limit=5):
        """Artists matching the name. Apple gives no popularity, and several artists share a name, so the artists of the songs
        found for that name are counted: the one with most songs is the one people mean."""
        counts = {}
        for item in self._search(query, "song", 25, attribute="artistTerm"):
            if item.get("artistId"):
                found = counts.setdefault(str(item["artistId"]), [0, item.get("artistName") or ""])
                found[0] += 1
                if len(item.get("artistName") or "") < len(found[1]) or not found[1]:   # 'Mora' rather than 'Mora & JHAYCO'
                    found[1] = item.get("artistName") or ""
        ordered = sorted(counts.items(), key=lambda pair: -pair[1][0])[:limit]
        return [ArtistInfo(source="itunes", id=identifier, name=name, popularity=count) for identifier, (count, name) in ordered]

    @staticmethod
    def _album(item, artist=""):
        name, kind = _album_and_kind(item.get("collectionName"), item.get("artistName"))
        art = item.get("artworkUrl100") or ""
        return AlbumInfo(source="itunes", id=str(item.get("collectionId")), title=name, artist=artist or item.get("artistName") or "",
                         year=(item.get("releaseDate") or "")[:4], track_total=int(item.get("trackCount") or 0), kind=kind,
                         cover_urls=(artwork(art, 1000),) if art else ())

    def albums(self, query, limit=10):
        return [self._album(i) for i in self._search(query, "album", limit) if i.get("collectionId")]

    def artist_albums(self, artist):
        return [self._album(i, artist.name) for i in self._lookup(artist.id, "album", 200)
                if i.get("wrapperType") == "collection" and i.get("collectionId")]

    def artist_top(self, artist, limit=50):
        """The songs Apple lists first for the artist (its most played)."""
        return [self._info(i) for i in self._lookup(artist.id, "song", limit) if i.get("wrapperType") == "track"][:limit]

    def album_tracks(self, album):
        """The songs of an album with the album's own tags. Apple's answer starts with the album itself, then its songs."""
        items = self._lookup(album.id, "song", 200)
        tracks = [self._info(i) for i in items if i.get("wrapperType") == "track"]
        wrapper = next((i for i in items if i.get("wrapperType") == "collection"), {})
        genre = wrapper.get("primaryGenreName") or ""
        for song in tracks:
            song.album_artist = wrapper.get("artistName") or album.artist or song.album_artist
            song.genre = song.genre or genre
            song.track_total = song.track_total or len(tracks)
        return tracks

    def cover_urls(self, title, artist, album):
        """The 1000 px cover of this album (or, failing that, of this song) by this artist, or ()."""
        if album:
            for item in self._search(f"{artist} {album}", "album", 5):
                name, _kind = _album_and_kind(item.get("collectionName"), item.get("artistName"))
                if item.get("artworkUrl100") and same_name(album, name) and same_artist(artist, item.get("artistName")):
                    return (artwork(item["artworkUrl100"], 1000),)
        for item in self._search(f"{artist} {title}", "song", 5):
            if item.get("artworkUrl100") and same_name(title, item.get("trackName")) and same_artist(artist, item.get("artistName")):
                return (artwork(item["artworkUrl100"], 1000),)
        return ()
