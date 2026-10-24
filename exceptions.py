class InvalidSpotifyURL(Exception):
    pass

class ConfigVideoMaxLength(Exception):
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
