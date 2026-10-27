import math
import os
import re
import unicodedata
from dataclasses import dataclass

import tempdirs
from exceptions import ConfigVideoLowViewCount, YoutubeBlocked, YoutubeItemNotFound, YoutubeTransientError, YoutubeVideoUnavailable

SUPPORTED_BROWSERS = ("firefox", "chrome", "edge", "brave", "opera", "chromium")   # where yt-dlp can read a YouTube login from

SEARCH_RESULTS = 8          # videos looked at per song
MAX_FALLBACKS = 3           # best-ranked videos tried if one can't be downloaded
STRICT_TOLERANCE = 7        # seconds of difference from Spotify's duration
RELAXED_TOLERANCE = 20      # only accepted if the video title contains the song title

# Versions nobody asked for. Penalised unless the Spotify title itself contains the word.
UNWANTED_WORDS = ("live", "en vivo", "concert", "concierto", "cover", "remix", "slowed", "sped up", "speed up", "reverb",
                  "instrumental", "karaoke", "8d", "nightcore", "acoustic", "reaction", "tutorial", "mashup", "loop", "hour")

# Points of a video (see score_candidate). A channel that IS the artist is the strongest sign of the studio audio.
OFFICIAL_CHANNEL_POINTS = 35       # the channel is exactly the artist, or "Artist - Topic" (YouTube's own audio channel)
ARTIST_IN_CHANNEL_POINTS = 15      # the channel only contains the artist's name
TITLE_POINTS = 15
UNWANTED_POINTS = -40              # per word nobody asked for
GUEST_POINTS = -20                 # the video names a guest artist ('ft. Justin Bieber') the song does not have: another recording
# (seconds apart at most, points): the closer the duration is to the official one, the surer it is the same recording.
# Nobody knows what the extra minute of a longer video holds, so duration weighs more than the channel.
DURATION_POINTS = ((1, 51), (2, 42.5), (3, 34), (5, 21.25), (8, 8.5), (15, 1.7))   # further apart: DURATION_FAR_POINTS
DURATION_FAR_POINTS = -25.5

# What YouTube says when it flags the IP. Checked in lower case, with both kinds of apostrophe.
BLOCKED_MARKERS = ("not a bot", "rate-limited", "rate limited", "too many requests", "http error 429",
                   "try again later")

# Failures that usually disappear on another attempt (an expired link, a dropped connection).
TRANSIENT_MARKERS = ("http error 403", "http error 500", "http error 502", "http error 503", "http error 504",
                     "unable to download video data", "timed out", "connection reset", "connection aborted",
                     "incompleteread", "remote end closed", "unexpected eof", "temporary failure")

UNAVAILABLE_MARKERS = ("confirm your age", "age-restricted", "video unavailable", "private video",
                       "not available in your country", "members-only", "has been removed")


def translate_youtube_error(error):
    """Turn a yt-dlp DownloadError into our own exceptions when we know what it means; otherwise return it."""
    text = str(error).lower().replace("’", "'")
    if any(marker in text for marker in BLOCKED_MARKERS):
        return YoutubeBlocked(str(error).splitlines()[0][:160])
    if any(marker in text for marker in UNAVAILABLE_MARKERS):
        return YoutubeVideoUnavailable(str(error).splitlines()[0][:160])
    if any(marker in text for marker in TRANSIENT_MARKERS):
        return YoutubeTransientError(str(error).splitlines()[0][:160])
    return error


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


COLLABORATION = re.compile(r"\s*(?:,|&|\bfeat\.?|\bft\.?|\bx\b|\by\b|\bcon\b)\s*", re.I)


def artist_names(artists):
    """['Bad Bunny & Jhay Cortez'] -> the normalized names that may appear as a channel: the artist as written, and each
    artist of a collaboration."""
    names = []
    for artist in artists:
        names.append(normalize(artist))
        names.extend(normalize(part) for part in COLLABORATION.split(artist or ""))
    return [n for n in dict.fromkeys(names) if n]


def title_in(song_title, video_title):
    """Does the video's title name the song? 'badtrip :(' is written 'Bad Trip :(' by the artist, so the words are also
    compared with the spaces taken out (only for titles long enough not to match by chance)."""
    wanted, video = normalize(clean_song_title(song_title)), normalize(video_title)
    if not wanted:
        return False
    if wanted in video:
        return True
    compact = wanted.replace(" ", "")
    return len(compact) >= 5 and compact in video.replace(" ", "")


GUEST = re.compile(r"\b(?:ft|feat|featuring)\b\.?\s*([^()\[\]|\-–—]+)", re.I)


def unknown_guests(video_title, known_text):
    """Guest artists named in the video's title ('... ft. Justin Bieber') that are not in `known_text` (the song's own title and
    artists, and what the user typed). 'Despacito ft. Justin Bieber' is the remix: the duration is the same, the recording is not."""
    known = normalize(known_text)
    found = []
    for match in GUEST.finditer(video_title or ""):
        for name in COLLABORATION.split(match.group(1)):
            name = normalize(name)
            if name and name not in known:
                found.append(name)
    return found


def channel_points(channel, artists):
    """+50 when the channel is the artist or 'Artist - Topic', +25 when it only contains the name."""
    channel = normalize(channel)
    best = 0
    for name in artist_names(artists):
        if channel in (name, f"{name} topic"):
            return OFFICIAL_CHANNEL_POINTS
        if name in channel:
            best = ARTIST_IN_CHANNEL_POINTS
    return best


def duration_points(difference):
    for limit, points in DURATION_POINTS:
        if difference <= limit:
            return points
    return DURATION_FAR_POINTS


def score_candidate(candidate, title, artists, duration_seconds, asked=""):
    """Return (score, title_matches, duration_difference). Higher score = more likely the studio audio.

    `asked` is what the user typed: a word in it ('en vivo') is not held against a video. A `duration_seconds` of 0 or
    None means the duration is not known: it then neither helps nor hurts (the difference is None)."""
    video_title = normalize(candidate.title)
    wanted = f"{normalize(title)} {normalize(asked)}"
    difference = abs(candidate.duration - duration_seconds) if duration_seconds else None

    title_matches = title_in(title, candidate.title)
    score = float(channel_points(candidate.channel, artists))
    if title_matches:
        score += TITLE_POINTS
    if difference is not None:
        score += duration_points(difference)
    if any(name in video_title for name in artist_names(artists)):
        score += 4
    if "official audio" in video_title:
        score += 6
    for word in UNWANTED_WORDS:
        pattern = rf"\b{word}\b"
        if re.search(pattern, video_title) and not re.search(pattern, wanted):
            score += UNWANTED_POINTS
    if unknown_guests(candidate.title, f"{title} {' '.join(artists)} {asked}"):
        score += GUEST_POINTS

    score += math.log10(candidate.views + 1)  # tie-breaker only
    return score, title_matches, difference


def search_queries(title, artists):
    """Search wordings to try, in order. The first one favours the studio audio; the others are simpler
    and find songs the first one misses (obscure artists, several artists, titles made of symbols)."""
    wordings = [
        f"{title} {' '.join(artists[:2])} audio",
        f"{artists[0]} {title}",
        f"{title} {' '.join(artists)}",
    ]
    return list(dict.fromkeys(wordings))   # no repeats, order kept


def reduced_queries(title, artists, limit=4):
    """Last-resort wordings: the title with one word removed at a time, longest words first.

    YouTube's search silently returns nothing for some words (for example 'Graxxx', which its adult-content
    filter seems to catch), so a song whose title has one of them can only be found without it."""
    words = [w for w in clean_song_title(title).split() if len(normalize(w)) >= 2]
    if len(words) < 2:
        return []
    longest_first = sorted(range(len(words)), key=lambda i: -len(words[i]))[:limit]
    return [f"{artists[0]} {' '.join(w for j, w in enumerate(words) if j != i)}" for i in longest_first]


def rank_candidates(candidates, title, artists, duration_seconds, max_length=None, require_title=False, asked=""):
    """Best-first list of videos that plausibly are this song, judged against Spotify's data.

    With `require_title` a video is only accepted if its name contains the song's title: used for the
    last-resort searches, where the duration alone could match a different song."""
    scored = []
    for candidate in candidates:
        if candidate.duration is None or (max_length and candidate.duration > max_length):
            continue
        score, title_matches, difference = score_candidate(candidate, title, artists, duration_seconds, asked)
        if require_title and not title_matches:
            continue
        if difference is None or difference <= STRICT_TOLERANCE or (difference <= RELAXED_TOLERANCE and title_matches):
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
        try:
            with yt_dlp.YoutubeDL(self._options(extract_flat=True, skip_download=True)) as ydl:
                result = ydl.extract_info(f"ytsearch{count}:{query}", download=False)
        except yt_dlp.utils.DownloadError as e:
            raise translate_youtube_error(e) from None

        for entry in result.get('entries') or []:
            duration = entry.get('duration')
            yield Candidate(
                url=entry.get('url') or f"https://www.youtube.com/watch?v={entry['id']}",
                title=entry.get('title') or "",
                channel=entry.get('channel') or entry.get('uploader') or "",
                duration=int(duration) if duration else None,
                views=entry.get('view_count') or 0,
            )

    def search(self, title, artists, duration_seconds, max_length, min_view_count, asked=""):
        """Return up to MAX_FALLBACKS video links, best match first (see search_ranked)."""
        ranked = self.search_ranked(title, artists, duration_seconds, max_length, min_view_count, asked)
        return [c.url for c in ranked[:MAX_FALLBACKS]]

    def search_ranked(self, title, artists, duration_seconds, max_length, min_view_count, asked=""):
        """Every plausible video as a Candidate, best match first (so a window can offer the next one).

        Videos are judged against the song's official data (duration, title, artist), so the music-video
        cut with a long intro is rejected in favour of the audio that really is the song. `asked` is the text
        the user typed, when the song came from a search: words in it are not held against a video."""
        # YouTube's search is picky: a long query (title + several artists + "audio") can return a single
        # unrelated video, or nothing at all when the title is made of symbols. So if one wording does not
        # give a video with the right duration, the next one is tried, adding what was found to the pool.
        candidates = {}
        ranked = []
        for query in search_queries(title, artists):
            for candidate in self._search(query):
                candidates.setdefault(candidate.url, candidate)
            ranked = rank_candidates(list(candidates.values()), title, artists, duration_seconds, max_length, asked=asked)
            if ranked:
                break

        if not ranked:
            for query in reduced_queries(title, artists):
                for candidate in self._search(query):
                    candidates.setdefault(candidate.url, candidate)
                ranked = rank_candidates(list(candidates.values()), title, artists, duration_seconds, max_length, require_title=True, asked=asked)
                if ranked:
                    break

        candidates = list(candidates.values())
        if not candidates:
            raise YoutubeItemNotFound('Could not load results from YouTube')

        if not ranked:
            closest = min((c.duration for c in candidates if c.duration), key=lambda d: abs(d - (duration_seconds or 0)), default=None)
            hint = f" (closest video lasts {closest}s)" if closest else ""
            raise YoutubeItemNotFound(f"No YouTube video matches Spotify's duration of {duration_seconds}s{hint}")

        if ranked[0].views < min_view_count:
            raise ConfigVideoLowViewCount(f'View count {ranked[0].views} does not meet MIN_VIEW_COUNT value of {min_view_count} [{ranked[0].url}]')

        return ranked

    def download(self, url, audio_bitrate):
        """Download the audio of `url` into this run's temporary folder.

        `audio_bitrate` is the requested bitrate in bps. Returns (path, kbps)
        where kbps is the real bitrate of the stream that was downloaded.
        """
        import yt_dlp

        target_kbps = int(audio_bitrate / 1000)
        options = self._options(**{
            'format': f'bestaudio[abr<={target_kbps}]/worstaudio/best',
            'outtmpl': tempdirs.run_dir().replace('%', '%%').replace(os.sep, '/') + '/%(id)s.%(ext)s',  # video id: unique per video
            'noplaylist': True,
            'retries': 3,
        })
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            raise translate_youtube_error(e) from None

        return info['requested_downloads'][0]['filepath'], int(info.get('abr') or target_kbps)
