"""Albums and artists as the metadata services describe them: the same shape whichever service it came from."""
from dataclasses import dataclass

from apis.song_info import KINDS


@dataclass
class AlbumInfo:
    source: str = ""          # "deezer" or "itunes"
    id: str = ""              # the service's own id: only meaningful together with `source`
    title: str = ""
    artist: str = ""
    year: str = ""
    track_total: int = 0      # 0 when the service does not say
    kind: str = "album"       # one of apis.song_info.KINDS
    cover_urls: tuple = ()    # best first

    @property
    def key(self):
        return f"album:{self.source}:{self.id}"

    def __post_init__(self):
        if self.kind not in KINDS:
            self.kind = "other"


@dataclass
class ArtistInfo:
    source: str = ""
    id: str = ""
    name: str = ""
    popularity: int = 0       # fans (Deezer) or how many of the found songs are theirs (iTunes): only to choose between homonyms

    @property
    def key(self):
        return f"artist:{self.source}:{self.id}"
