"""YouTube Music's public search, used to find the cover of a song and, as a last resort, the song itself. No account, no key.

It is YouTube's own web interface, not an official API, so it can change without notice. If it does, this source simply
returns nothing and the other sources carry on."""
import re

from apis.matching import same_artist, same_name
from apis.metadata_http import MetadataClient
from apis.song_info import SongInfo
from apis.youtube import normalize

SEARCH_URL = "https://music.youtube.com/youtubei/v1/search?prettyPrint=false"
SONGS_FILTER = "EgWKAQIIAWoQEAMQBBAJEAoQBRAQEBUQEQ=="     # "only songs" in YouTube Music's search
ALBUMS_FILTER = "EgWKAQIYAWoMEA4QChADEAQQCRAF"            # "only albums"
CLIENT_VERSION = "1.20241104.01.00"
SQUARE_SIZE = 1000                                         # the picture is asked at this size (Google's image server resizes)


def _text(runs):
    return "".join(run.get("text", "") for run in runs or [])


def _items(data):
    """[(columns, thumbnail url)] of every result in a YouTube Music search answer. Anything unexpected is skipped."""
    raw = []

    def walk(node):
        if isinstance(node, dict):
            item = node.get("musicResponsiveListItemRenderer")
            if item:
                raw.append(item)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    found = []
    for item in raw:
        try:
            columns = [_text(((c.get("musicResponsiveListItemFlexColumnRenderer") or {}).get("text") or {}).get("runs"))
                       for c in item.get("flexColumns") or []]
            thumbs = (((item.get("thumbnail") or {}).get("musicThumbnailRenderer") or {}).get("thumbnail") or {}).get("thumbnails") or []
            if len(columns) >= 2 and thumbs:
                found.append((columns, thumbs[-1]["url"]))
        except (KeyError, TypeError, AttributeError):
            continue
    return found


def parse_songs(data):
    """[(title, artist, album, thumbnail url)]: the details line of a song reads "Artist • Album • 1:45"."""
    songs = []
    for columns, thumbnail in _items(data):
        parts = [p.strip() for p in columns[1].split("•")]
        songs.append((columns[0].strip(), parts[0], parts[1] if len(parts) >= 3 else "", thumbnail))
    return songs


def _clock_seconds(text):
    """'3:12' -> 192, '1:02:03' -> 3723; anything else -> 0."""
    if not re.fullmatch(r"\d{1,2}(:\d{2}){1,2}", text or ""):
        return 0
    seconds = 0
    for part in text.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def parse_song_details(data):
    """[SongInfo-like dicts] of a songs search: title, artist, album, duration in seconds and the picture.
    YouTube Music has no year or track number, so those stay empty."""
    songs = []
    for columns, thumbnail in _items(data):
        parts = [p.strip() for p in columns[1].split("•")]
        duration = _clock_seconds(parts[-1]) if len(parts) >= 2 else 0
        if duration:
            parts = parts[:-1]
        songs.append({"title": columns[0].strip(), "artist": parts[0], "album": parts[1] if len(parts) >= 2 else "",
                      "duration": duration, "thumbnail": thumbnail})
    return songs


def parse_albums(data):
    """[(title, artist, thumbnail url)]: the details line of an album reads "Álbum • Artist • 2024" (or "EP", "Single")."""
    albums = []
    for columns, thumbnail in _items(data):
        parts = [p.strip() for p in columns[1].split("•")]
        if len(parts) >= 2:
            albums.append((columns[0].strip(), parts[1], thumbnail))
    return albums


def square(url, size=SQUARE_SIZE):
    """Google's image server takes the size from the end of the address: ...=w120-h120-l90-rj -> ...=w1000-h1000-l90-rj"""
    return re.sub(r"=w\d+-h\d+", f"=w{size}-h{size}", url)


class YouTubeMusic:
    def __init__(self, client=None):
        self.client = client or MetadataClient("YouTube Music", 1.0)

    def _search(self, query, params):
        body = {"context": {"client": {"clientName": "WEB_REMIX", "clientVersion": CLIENT_VERSION, "hl": "es", "gl": "US"}},
                "query": query, "params": params}
        return self.client.post_json(SEARCH_URL, body, headers={"Origin": "https://music.youtube.com", "Referer": "https://music.youtube.com/"})

    def search(self, title, artist=None, limit=5):
        """Songs matching free text, as SongInfo. It is the last resort of the text search: it knows the album, the
        duration and the picture, but not the year or the track number."""
        query = f"{artist} {title}" if artist else title
        infos = []
        for found in parse_song_details(self._search(query, SONGS_FILTER))[:limit]:
            infos.append(SongInfo(source="ytmusic", title=found["title"], artist=found["artist"], album=found["album"],
                                  album_artist=found["artist"], duration=float(found["duration"]),
                                  cover_urls=(square(found["thumbnail"]), found["thumbnail"]), thumb_url=found["thumbnail"]))
        return infos

    def cover_urls(self, title, artist, album):
        """Picture urls (biggest first), or (). A song on an album gets the ALBUM's cover (what the tags say it belongs to);
        a single, or an album that is not found, gets the cover of the song."""
        if album and normalize(album) != normalize(title):
            for found_album, found_artist, thumbnail in parse_albums(self._search(f"{artist} {album}", ALBUMS_FILTER)):
                if same_name(album, found_album) and same_artist(artist, found_artist):
                    return (square(thumbnail), thumbnail)
        for found_title, found_artist, found_album, thumbnail in parse_songs(self._search(f"{artist} {title or album}", SONGS_FILTER)):
            same = same_name(title, found_title) if title else same_name(album, found_album, found_title)
            if same and same_artist(artist, found_artist):
                return (square(thumbnail), thumbnail)
        return ()
