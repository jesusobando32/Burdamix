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


class YoutubeNetworkError(YoutubeTransientError):
    """The connection itself failed (no internet, a slow or unstable network, DNS): not YouTube's doing, and no sign of a block."""
    pass


class MetadataError(Exception):
    """Completing a song's tags failed. The message is written for the user, in Spanish."""
    pass


class MetadataNetworkError(MetadataError):
    """No internet, or the service answered something unexpected."""
    pass


class MetadataBadResponse(MetadataNetworkError):
    """A 200 that is not what the service sends: a block page ("Access Denied"), or a Wi-Fi login page."""
    pass


class MetadataRefused(MetadataNetworkError):
    """A service refused us on purpose (403): some block VPN and data-centre addresses. Asking again will not help."""
    pass


class MetadataRateLimited(MetadataError):
    """A metadata service asked us to slow down."""
    pass


class MetadataNotFound(MetadataError):
    """The services have no match for this song (or no cover for it)."""
    pass


class UnsupportedAudioFormat(MetadataError):
    """The file is not one of the formats whose tags can be written (mp3, flac, m4a, ogg, opus)."""
    pass


class TagWriteError(MetadataError):
    """The tags could not be written (file open in another program, no permission, damaged file)."""
    pass
