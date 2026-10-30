"""Deezer: the back-up for songs MusicBrainz does not know, and the source of the genre. Free, no account."""
from apis.matching import same_artist, same_name
from apis.metadata_http import MetadataClient
from apis.catalog_info import AlbumInfo, ArtistInfo
from apis.song_info import SongInfo
from exceptions import MetadataError, MetadataNetworkError, MetadataRateLimited

BASE = "https://api.deezer.com"
PAGE = 100                    # items per page of a Deezer list
MAX_ITEMS = 500               # a list longer than this is cut: nobody downloads more in one go
DETAILED_RESULTS = 3         # only the first few get their album looked up (genre, release type): one extra request each
KINDS = {"album": "album", "single": "single", "ep": "ep", "compile": "compilation"}


def _check(data):
    """Deezer answers 200 with an 'error' object when something is wrong."""
    if isinstance(data, dict) and data.get("error"):
        code = (data["error"] or {}).get("code")
        if code == 4:   # quota exceeded
            raise MetadataRateLimited("Deezer pide ir más despacio. Espera un minuto e inténtalo de nuevo.")
        raise MetadataNetworkError("Deezer respondió con un error.")
    return data


class Deezer:
    def __init__(self, client=None):
        self.client = client or MetadataClient("Deezer", 0.15)   # the service allows 50 requests per 5 seconds

    def _get(self, path, params=None):
        return _check(self.client.get_json(f"{BASE}/{path}", params))

    def search(self, title, artist=None, limit=5):
        """The advanced syntax (artist:"x" track:"y") returns nothing for many songs; a plain query works."""
        query = f"{artist} {title}" if artist else title
        data = self._get("search/track", {"q": query, "limit": limit})
        infos = []
        for position, item in enumerate(data.get("data") or []):
            album = item.get("album") or {}
            info = SongInfo(
                source="deezer",
                title=item.get("title") or "",
                artist=(item.get("artist") or {}).get("name") or "",
                album=album.get("title") or "",
                duration=float(item.get("duration") or 0),
                track_id=str(item.get("id") or ""),
                cover_urls=tuple(u for u in (album.get("cover_xl"), album.get("cover_big")) if u),
                thumb_url=album.get("cover_medium") or album.get("cover_big") or "",
            )
            info.album_artist = info.artist
            if position < DETAILED_RESULTS:
                self._add_details(info, item)
            infos.append(info)
        return infos

    def _add_details(self, info, item):
        """Track number, year, genre and release type. If the extra requests fail the basic data still stands."""
        try:
            track = self._get(f"track/{item['id']}")
            info.track_number = int(track.get("track_position") or 0)
            info.disc_number = int(track.get("disk_number") or 0)
            info.year = (track.get("release_date") or "")[:4]
            names = [c.get("name") for c in track.get("contributors") or [] if isinstance(c, dict) and c.get("name")]
            info.contributors = tuple(dict.fromkeys(names))   # "Luis Fonsi", "Daddy Yankee": the guests of the song
            album_id = (track.get("album") or item.get("album") or {}).get("id")
            if album_id:
                album = self._get(f"album/{album_id}")
                genres = (album.get("genres") or {}).get("data") or []
                info.genre = genres[0]["name"] if genres else ""
                info.kind = KINDS.get(album.get("record_type"), "other")
                info.track_total = int(album.get("nb_tracks") or 0)
                info.year = info.year or (album.get("release_date") or "")[:4]
                info.album_artist = (album.get("artist") or {}).get("name") or info.artist
        except (MetadataError, KeyError, TypeError, ValueError):
            pass

    # --- albums and artists ---

    def _paged(self, path):
        """Every item of a Deezer list, page after page (the answer says how many there are in total)."""
        items, index = [], 0
        while index < MAX_ITEMS:
            data = self._get(path, {"limit": PAGE, "index": index})
            chunk = [i for i in data.get("data") or [] if isinstance(i, dict)]
            items.extend(chunk)
            index += len(chunk)
            if not chunk or index >= int(data.get("total") or 0):
                break
        return items

    @staticmethod
    def _covers(item):
        return tuple(u for u in (item.get("cover_xl"), item.get("cover_big")) if u)

    def artists(self, query, limit=5):
        """Artists matching the name, the most followed first (several artists share a name: 'M.O.R.A.' and 'Mora')."""
        found = [ArtistInfo(source="deezer", id=str(i["id"]), name=i.get("name") or "", popularity=int(i.get("nb_fan") or 0))
                 for i in self._get("search/artist", {"q": query, "limit": limit}).get("data") or [] if isinstance(i, dict) and i.get("id")]
        return sorted(found, key=lambda a: -a.popularity)

    def albums(self, query, limit=10):
        return [AlbumInfo(source="deezer", id=str(i["id"]), title=i.get("title") or "", artist=(i.get("artist") or {}).get("name") or "",
                          track_total=int(i.get("nb_tracks") or 0), kind=KINDS.get(i.get("record_type"), "other"), cover_urls=self._covers(i))
                for i in self._get("search/album", {"q": query, "limit": limit}).get("data") or [] if isinstance(i, dict) and i.get("id")]

    def artist_albums(self, artist):
        return [AlbumInfo(source="deezer", id=str(i["id"]), title=i.get("title") or "", artist=artist.name,
                          year=(i.get("release_date") or "")[:4], kind=KINDS.get(i.get("record_type"), "other"), cover_urls=self._covers(i))
                for i in self._paged(f"artist/{artist.id}/albums") if i.get("id")]

    def artist_top(self, artist, limit=50):
        """The artist's most played songs. They come without year or track number: `complete` fills those in when one is downloaded."""
        songs = []
        for item in self._get(f"artist/{artist.id}/top", {"limit": limit}).get("data") or []:
            album = item.get("album") or {}
            songs.append(SongInfo(source="deezer", title=item.get("title") or "", artist=(item.get("artist") or {}).get("name") or artist.name,
                                  album=album.get("title") or "", album_artist=artist.name, duration=float(item.get("duration") or 0),
                                  track_id=str(item.get("id") or ""), cover_urls=self._covers(album), thumb_url=album.get("cover_medium") or ""))
        return songs

    def album_tracks(self, album):
        """The songs of an album, all carrying the album's own tags (title, artist, year, genre, track and disc numbers) so that a
        player groups them as one album."""
        detail = self._get(f"album/{album.id}")
        tracks = self._paged(f"album/{album.id}/tracks")
        genres = (detail.get("genres") or {}).get("data") or []
        album_artist = (detail.get("artist") or {}).get("name") or album.artist
        songs = []
        for position, item in enumerate(tracks, start=1):
            songs.append(SongInfo(
                source="deezer", title=item.get("title") or "", artist=(item.get("artist") or {}).get("name") or album_artist,
                album=detail.get("title") or album.title, album_artist=album_artist, year=(detail.get("release_date") or "")[:4],
                genre=genres[0]["name"] if genres else "", track_number=int(item.get("track_position") or position),
                track_total=int(detail.get("nb_tracks") or len(tracks)), disc_number=int(item.get("disk_number") or 1),
                kind=KINDS.get(detail.get("record_type"), "other"), duration=float(item.get("duration") or 0),
                track_id=str(item.get("id") or ""), cover_urls=self._covers(detail) or album.cover_urls,
                thumb_url=detail.get("cover_medium") or ""))
        return songs

    def complete(self, info):
        """Fill in what a song found in its artist's popular list lacks (the credited artists, year, track number, genre).
        Best effort: the song stays as it is when Deezer does not answer."""
        if info.source != "deezer" or not info.track_id:
            return info
        if not (info.year and info.track_number and info.genre):
            self._add_details(info, {"id": info.track_id})
            if info.contributors:
                return info
        try:
            track = self._get(f"track/{info.track_id}")
            names = [c.get("name") for c in track.get("contributors") or [] if isinstance(c, dict) and c.get("name")]
            info.contributors = tuple(dict.fromkeys(names))
        except (MetadataError, KeyError, TypeError, ValueError):
            pass
        return info

    def cover_urls(self, title, artist, album):
        """Cover urls (biggest first) of this album (or, failing that, of this song) by this artist, or ()."""
        def covers(item):
            return tuple(u for u in (item.get("cover_xl"), item.get("cover_big")) if u)

        if album:
            for item in self._get("search/album", {"q": f"{artist} {album}", "limit": 5}).get("data") or []:
                if same_name(album, item.get("title")) and same_artist(artist, (item.get("artist") or {}).get("name")) and covers(item):
                    return covers(item)
        for item in self._get("search/track", {"q": f"{artist} {title}", "limit": 5}).get("data") or []:
            found = item.get("album") or {}
            if same_name(title, item.get("title")) and same_artist(artist, (item.get("artist") or {}).get("name")) and covers(found):
                return covers(found)
        return ()
