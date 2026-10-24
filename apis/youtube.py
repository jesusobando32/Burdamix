import math
import re
import unicodedata
from dataclasses import dataclass

from exceptions import ConfigVideoLowViewCount, YoutubeItemNotFound, YoutubeVideoUnavailable

SEARCH_RESULTS = 8          # videos looked at per song
MAX_FALLBACKS = 3           # best-ranked videos tried if one can't be downloaded
STRICT_TOLERANCE = 7        # seconds of difference from Spotify's duration
RELAXED_TOLERANCE = 20      # only accepted if the video title contains the song title

# Versions nobody asked for. Penalised unless the Spotify title itself contains the word.
UNWANTED_WORDS = ("live", "cover", "remix", "slowed", "sped up", "speed up", "reverb", "instrumental",
                  "karaoke", "8d", "nightcore", "acoustic", "reaction", "tutorial", "mashup", "loop", "hour")

UNAVAILABLE_MARKERS = ("confirm your age", "age-restricted", "video unavailable", "private video",
                       "not available in your country", "members-only", "has been removed")


@dataclass
class Candidate:
    url: str
    title: str
    channel: str
    duration: int
    views: int


def normalize(text):
    """Lowercase, no accents, no punctuation: 'Tití Me Preguntó!' -> 'titi me pregunto'."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def clean_song_title(title):
    """'Song (feat. X) - Remastered 2011' -> 'Song'."""
    title = re.sub(r"\s*[\(\[][^\)\]]*\b(feat|ft|with|prod)\b[^\)\]]*[\)\]]", "", title, flags=re.I)
    title = re.sub(r"\s+-\s+(remaster|\d{4}\b|live|single version|radio edit|mono|stereo|bonus).*$", "", title, flags=re.I)
    return title.strip()


def score_candidate(candidate, title, artists, duration_seconds):
    """Return (score, title_matches, duration_difference). Higher score = more likely the studio audio."""
    video_title = normalize(candidate.title)
    channel = normalize(candidate.channel)
    spotify_title = normalize(title)
    difference = abs(candidate.duration - duration_seconds)

    title_matches = normalize(clean_song_title(title)) in video_title
    score = -float(difference)

    if title_matches:
        score += 5
    main_artist = normalize(artists[0])
    if main_artist and (main_artist in video_title or main_artist in channel):
        score += 4
    if channel.endswith("topic"):           # YouTube's auto-generated "Artist - Topic" channel = the studio audio
        score += 8
    if "official audio" in video_title:
        score += 6
    for word in UNWANTED_WORDS:
        pattern = rf"\b{word}\b"
        if re.search(pattern, video_title) and not re.search(pattern, spotify_title):
            score -= 15

    score += math.log10(candidate.views + 1)  # tie-breaker only
    return score, title_matches, difference


def rank_candidates(candidates, title, artists, duration_seconds, max_length=None):
    """Best-first list of videos that plausibly are this song, judged against Spotify's data."""
    scored = []
    for candidate in candidates:
        if candidate.duration is None or (max_length and candidate.duration > max_length):
            continue
        score, title_matches, difference = score_candidate(candidate, title, artists, duration_seconds)
        if difference <= STRICT_TOLERANCE or (difference <= RELAXED_TOLERANCE and title_matches):
            scored.append((score, candidate))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [candidate for _, candidate in scored]


class YouTube:
    def __init__(self, cookies_from_browser=None):
        """`cookies_from_browser` ('firefox', 'chrome', 'edge'...) lets yt-dlp use your YouTube login,
        which is the only way to download age-restricted videos."""
        self.cookies_from_browser = cookies_from_browser

    def _options(self, **extra):
        options = {'quiet': True, 'no_warnings': True, 'noprogress': True}
        if self.cookies_from_browser:
            options['cookiesfrombrowser'] = (self.cookies_from_browser,)
        options.update(extra)
        return options

    def _search(self, query, count=SEARCH_RESULTS):
        import yt_dlp
        with yt_dlp.YoutubeDL(self._options(extract_flat=True, skip_download=True)) as ydl:
            result = ydl.extract_info(f"ytsearch{count}:{query}", download=False)

        for entry in result.get('entries') or []:
            duration = entry.get('duration')
            yield Candidate(
                url=entry.get('url') or f"https://www.youtube.com/watch?v={entry['id']}",
                title=entry.get('title') or "",
                channel=entry.get('channel') or entry.get('uploader') or "",
                duration=int(duration) if duration else None,
                views=entry.get('view_count') or 0,
            )

    def search(self, title, artists, duration_seconds, max_length, min_view_count):
        """Return up to MAX_FALLBACKS video links, best match first.

        Videos are judged against Spotify's own data (duration, title, artist), so the music-video
        cut with a long intro is rejected in favour of the audio that really is the song."""
        candidates = list(self._search(f"{title} {' '.join(artists[:2])} audio"))
        if not candidates:
            raise YoutubeItemNotFound('Could not load results from YouTube')

        ranked = rank_candidates(candidates, title, artists, duration_seconds, max_length)
        if not ranked:
            closest = min((c.duration for c in candidates if c.duration), key=lambda d: abs(d - duration_seconds), default=None)
            hint = f" (closest video lasts {closest}s)" if closest else ""
            raise YoutubeItemNotFound(f"No YouTube video matches Spotify's duration of {duration_seconds}s{hint}")

        if ranked[0].views < min_view_count:
            raise ConfigVideoLowViewCount(f'View count {ranked[0].views} does not meet MIN_VIEW_COUNT value of {min_view_count} [{ranked[0].url}]')

        return [c.url for c in ranked[:MAX_FALLBACKS]]

    def download(self, url, audio_bitrate):
        """Download the audio of `url` into ./temp/.

        `audio_bitrate` is the requested bitrate in bps. Returns (path, kbps)
        where kbps is the real bitrate of the stream that was downloaded.
        """
        import yt_dlp

        target_kbps = int(audio_bitrate / 1000)
        options = self._options(**{
            'format': f'bestaudio[abr<={target_kbps}]/worstaudio/best',
            'outtmpl': './temp/%(id)s.%(ext)s',  # video id: unique, so parallel downloads never collide
            'noplaylist': True,
            'retries': 3,
        })
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            if any(marker in str(e).lower() for marker in UNAVAILABLE_MARKERS):
                raise YoutubeVideoUnavailable(str(e).splitlines()[0][:160])
            raise

        return info['requested_downloads'][0]['filepath'], int(info.get('abr') or target_kbps)
