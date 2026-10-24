class InvalidSpotifyURL(Exception):
    pass

class ConfigVideoLowViewCount(Exception):
    pass

class YoutubeItemNotFound(Exception):
    pass

class SpotifyTrackNotFound(Exception):
    pass

class SpotifyPlaylistNotFound(Exception):
    pass

class SpotifyAlbumNotFound(Exception):
    pass

class SpotifyRetrievalError(Exception):
    pass

class YoutubeVideoUnavailable(Exception):
    """The video exists but cannot be downloaded (age restricted, private, region locked...)."""
    pass


class YoutubeBlocked(Exception):
    """YouTube is refusing our requests (bot check, rate limit). Retrying immediately makes it worse."""
    pass


class YoutubeTransientError(Exception):
    """A download failed in a way that usually works on another try (403, dropped connection...)."""
    pass
