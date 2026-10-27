"""Apple's iTunes Search API: the second back-up, with large covers and the genre. Free, no account."""
import re

from apis.metadata_http import MetadataClient
from apis.song_info import SongInfo

URL = "https://itunes.apple.com/search"
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

    def _search(self, term, entity, limit):
        data = self.client.get_json(URL, {"term": term, "media": "music", "entity": entity, "limit": limit, "country": "US"})
        return [r for r in data.get("results") or [] if isinstance(r, dict)]

    def search(self, title, artist=None, limit=10):
        term = f"{artist} {title}" if artist else title
        infos = []
        for item in self._search(term, "song", limit):
            album, kind = _album_and_kind(item.get("collectionName"), item.get("collectionArtistName"))
            art = item.get("artworkUrl100") or ""
            infos.append(SongInfo(
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
                cover_urls=(artwork(art, 1000),) if art else (),
                thumb_url=artwork(art, 300),
            ))
        return infos

    def find_cover(self, album, artist):
        for item in self._search(f"{artist} {album}", "album", 1):
            art = item.get("artworkUrl100")
            if art:
                return (artwork(art, 1000),)
        return ()
