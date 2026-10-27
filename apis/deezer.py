"""Deezer: the back-up for songs MusicBrainz does not know, and the source of the genre. Free, no account."""
from apis.matching import same_artist, same_name
from apis.metadata_http import MetadataClient
from apis.song_info import SongInfo
from exceptions import MetadataError, MetadataNetworkError, MetadataRateLimited

BASE = "https://api.deezer.com"
DETAILED_RESULTS = 3          # only the first few get their album looked up (genre, release type): one extra request each
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
