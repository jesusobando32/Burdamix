"""YouTube Music's public search, used only to find the cover of a song. No account, no key.

It is YouTube's own web interface, not an official API, so it can change without notice. If it does, this source simply
returns nothing and the other sources carry on."""
import re

from apis.metadata_http import MetadataClient

SEARCH_URL = "https://music.youtube.com/youtubei/v1/search?prettyPrint=false"
SONGS_FILTER = "EgWKAQIIAWoQEAMQBBAJEAoQBRAQEBUQEQ=="     # "only songs" in YouTube Music's search
CLIENT_VERSION = "1.20241104.01.00"
SQUARE_SIZE = 1000                                         # the picture is asked at this size (Google's image server resizes)


def _text(runs):
    return "".join(run.get("text", "") for run in runs or [])


def parse_songs(data):
    """[(title, artist, album, thumbnail url)] from a YouTube Music search answer. Anything unexpected is skipped."""
    songs = []

    def walk(node):
        if isinstance(node, dict):
            item = node.get("musicResponsiveListItemRenderer")
            if item:
                songs.append(item)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    found = []
    for item in songs:
        try:
            columns = [_text(((c.get("musicResponsiveListItemFlexColumnRenderer") or {}).get("text") or {}).get("runs"))
                       for c in item.get("flexColumns") or []]
            thumbs = (((item.get("thumbnail") or {}).get("musicThumbnailRenderer") or {}).get("thumbnail") or {}).get("thumbnails") or []
            if len(columns) < 2 or not thumbs:
                continue
            parts = [p.strip() for p in columns[1].split("•")]     # "Artist • Album • 1:45"
            artist = parts[0] if parts else ""
            album = parts[1] if len(parts) >= 3 else ""
            found.append((columns[0].strip(), artist, album, thumbs[-1]["url"]))
        except (KeyError, TypeError, AttributeError):
            continue
    return found


def square(url, size=SQUARE_SIZE):
    """Google's image server takes the size from the end of the address: ...=w120-h120-l90-rj -> ...=w1000-h1000-l90-rj"""
    return re.sub(r"=w\d+-h\d+", f"=w{size}-h{size}", url)


class YouTubeMusic:
    def __init__(self, client=None, similar=None):
        self.client = client or MetadataClient("YouTube Music", 1.0)
        self._similar = similar

    @property
    def similar(self):
        if self._similar is None:     # imported here: autotag imports this module, and the ranking helpers live there
            from autotag import similarity
            self._similar = similarity
        return self._similar

    def find_cover(self, album, artist):
        """Picture urls (biggest first) of the song or album that matches `album` and `artist`, or ()."""
        body = {"context": {"client": {"clientName": "WEB_REMIX", "clientVersion": CLIENT_VERSION, "hl": "es", "gl": "US"}},
                "query": f"{artist} {album}", "params": SONGS_FILTER}
        data = self.client.post_json(SEARCH_URL, body, headers={"Origin": "https://music.youtube.com", "Referer": "https://music.youtube.com/"})
        for title, found_artist, found_album, thumbnail in parse_songs(data):
            same_name = max(self.similar(album, found_album), self.similar(album, title)) >= 0.9
            same_artist = self.similar(artist, found_artist) >= 0.8
            if same_name and same_artist:
                return (square(thumbnail), thumbnail)
        return ()
