"""Finds the cover of a song, as a step of its own after the tags are known.

The tags can come from any service; the cover does not depend on which one. The finder asks a chain of services,
most likely first, with the song's title, artist and album, and stops at the first picture that downloads. The user
only ever sees one flow."""
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass

from apis.youtube import normalize
from exceptions import MetadataError, MetadataNotFound, MetadataRateLimited, MetadataRefused

# Which service's own pictures a candidate carries, by where its tags came from. Those exact urls are used at that
# service's turn in the chain instead of searching it again.
OWN_COVERS_OF = {"musicbrainz": "caa", "deezer": "deezer", "itunes": "itunes"}
CACHE_SIZE = 64       # the songs of an album share one cover: it is found and downloaded once, not once per song
PAUSE_SECONDS = 600   # a service that refused us (403, too many requests) is left alone for ten minutes: asking again in a batch only wastes time


@dataclass
class CoverResult:
    data: bytes = None      # the picture, or None
    source: str = ""        # which service it came from
    problem: str = None     # why nothing came, when a service refused us or the connection failed (None = nobody has it)


class CoverFinder:
    def __init__(self, providers, images, clock=time.monotonic, cache_size=CACHE_SIZE):
        self.providers = list(providers)     # [(name, object with cover_urls(title, artist, album))] in the order they are asked
        self.images = images
        self._clock = clock
        self._cache_size = cache_size
        self._cache = OrderedDict()
        self._paused = {}                    # name -> (until, message)
        self._lock = threading.Lock()

    def _pause(self, name, error):
        with self._lock:
            self._paused[name] = (self._clock() + PAUSE_SECONDS, str(error))

    def _pause_message(self, name):
        with self._lock:
            until, message = self._paused.get(name, (0, None))
        return message if until > self._clock() else None

    @staticmethod
    def _key(info):
        return (normalize(info.artist), normalize(info.album) or normalize(info.title))

    def find(self, info):
        """The cover of the song `info` describes (an apis.song_info.SongInfo), found with its tags. The covers found are
        remembered by artist and album, so the songs of one album do not each search and download it again."""
        key = self._key(info)
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
                return hit
        result = self._search(info)
        if result.data and self._cache_size:
            with self._lock:
                self._cache[key] = result
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
        return result

    def _search(self, info):
        problems = []
        for name, provider in self.providers:
            paused = self._pause_message(name)
            if paused:
                problems.append(paused)
                continue
            own = tuple(info.cover_urls) if OWN_COVERS_OF.get(info.source) == name else ()
            try:
                urls = own or provider.cover_urls(info.title, info.artist, info.album)
            except (MetadataRefused, MetadataRateLimited) as error:
                self._pause(name, error)
                problems.append(str(error))
                continue
            except MetadataError as error:        # no connection, an answer we do not understand: try the next service
                problems.append(str(error))
                continue
            for url in urls:
                try:
                    return CoverResult(data=self.images.get_image(url), source=name)
                except MetadataNotFound:
                    continue                      # that size does not exist, or no picture there
                except (MetadataRefused, MetadataRateLimited) as error:
                    self._pause(name, error)
                    problems.append(str(error))
                    break                         # its other sizes live on the same server: they would be refused too
                except MetadataError as error:
                    problems.append(str(error))
        return CoverResult(problem=problems[0] if problems else None)
