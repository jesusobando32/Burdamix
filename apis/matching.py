"""How alike two names are, shared by the ranking of tags and by the cover search (which must not accept the cover
of a different album just because it came first)."""
from difflib import SequenceMatcher

from apis.youtube import normalize

ALBUM_MATCH = 0.9     # a title or album must be this alike to count as the same
ARTIST_MATCH = 0.8


def similarity(a, b):
    """0..1. Words of the shorter text all appearing in the longer one counts as 0.88: close, but never 'the same'."""
    a, b = normalize(a), normalize(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    ratio = SequenceMatcher(None, a, b).ratio()
    if set(a.split()) <= set(b.split()) or set(b.split()) <= set(a.split()):
        ratio = max(ratio, 0.88)
    return ratio


def same_artist(wanted, found):
    return similarity(wanted, found) >= ARTIST_MATCH


def same_name(wanted, *found):
    """The title or album we look for against what a service calls it (a service may name an album after the song)."""
    return any(similarity(wanted, name) >= ALBUM_MATCH for name in found if name)
