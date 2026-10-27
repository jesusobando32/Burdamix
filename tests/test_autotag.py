"""Tests for completing tags and covers: the metadata services, the ranking, and writing the tags.
No real network: the services are simulated. The tag-writing tests build tiny real audio files with the bundled ffmpeg."""
import io
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import autotag
import tagwriter
from apis.deezer import Deezer
from apis.itunes import ITunes, artwork
from apis.metadata_http import MetadataClient, RateLimiter
from apis.musicbrainz import MusicBrainz
from apis.song_info import SongInfo
from exceptions import (MetadataNetworkError, MetadataNotFound, MetadataRateLimited, TagWriteError,
                        UnsupportedAudioFormat)


# --- fakes -------------------------------------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status=200, payload=None, headers=None, body=b"", not_json=False):
        self.status_code, self._payload, self.headers, self._body, self._not_json = status, payload, headers or {}, body, not_json

    def json(self):
        if self._not_json:
            raise ValueError("not json")
        return self._payload

    def iter_content(self, size):
        for start in range(0, len(self._body), size):
            yield self._body[start:start + size]


class FakeSession:
    """`answer(url, params)` returns a FakeResponse (or raises); every call is recorded."""

    def __init__(self, answer):
        self.answer, self.calls, self.headers = answer, [], {}

    def get(self, url, params=None, timeout=None, stream=False):
        self.calls.append((url, params))
        return self.answer(url, params)


def client(answer, name="Servicio", interval=0):
    session = FakeSession(answer)
    return MetadataClient(name, interval, session=session, clock=lambda: 0, sleep=lambda s: None), session


# --- shared HTTP client ------------------------------------------------------------------------------------------

def test_the_rate_limiter_spaces_calls_apart():
    now, slept = [0.0], []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(1.0, clock=lambda: now[0], sleep=sleep)
    limiter.wait()
    now[0] += 0.25
    limiter.wait()
    limiter.wait()
    assert slept == [0.75, 1.0]          # the first call is free; the next ones wait out the rest of the second


def test_requests_identify_the_app_as_musicbrainz_asks():
    c, session = client(lambda url, params: FakeResponse(payload={}))
    c.get_json("https://x.test/a")
    agent = session.headers["User-Agent"]
    assert agent.startswith("Burdamix/") and "(https://github.com/jesusobando32/Burdamix)" in agent
    assert "@" not in agent                                   # no e-mail address


def test_no_internet_becomes_a_message_the_user_can_read():
    import requests

    def offline(url, params):
        raise requests.ConnectionError("down")

    c, _ = client(offline, name="MusicBrainz")
    with pytest.raises(MetadataNetworkError, match="MusicBrainz.*internet"):
        c.get_json("https://x.test/a")


def test_a_503_is_retried_once_and_two_in_a_row_mean_rate_limited():
    answers = iter([FakeResponse(503), FakeResponse(payload={"ok": 1})])
    c, session = client(lambda url, params: next(answers))
    assert c.get_json("https://x.test/a") == {"ok": 1} and len(session.calls) == 2
    c2, _ = client(lambda url, params: FakeResponse(429, headers={"Retry-After": "1"}), name="Deezer")
    with pytest.raises(MetadataRateLimited, match="Deezer.*despacio"):
        c2.get_json("https://x.test/a")


def test_a_404_and_a_non_json_answer_are_told_apart():
    c, _ = client(lambda url, params: FakeResponse(404))
    with pytest.raises(MetadataNotFound):
        c.get_json("https://x.test/a")
    c2, _ = client(lambda url, params: FakeResponse(not_json=True))
    with pytest.raises(MetadataNetworkError, match="inesperado"):
        c2.get_json("https://x.test/a")


def test_a_huge_image_is_refused(monkeypatch):
    import apis.metadata_http as http
    monkeypatch.setattr(http, "MAX_IMAGE_BYTES", 100)
    c, _ = client(lambda url, params: FakeResponse(body=b"x" * 500))
    with pytest.raises(MetadataNotFound, match="demasiado grande"):
        c.get_image("https://x.test/a.jpg")
    ok, _ = client(lambda url, params: FakeResponse(body=b"x" * 50))
    assert ok.get_image("https://x.test/a.jpg") == b"x" * 50


# --- SongInfo ----------------------------------------------------------------------------------------------------

def test_song_info_from_the_window_is_cleaned():
    info = SongInfo.from_dict({"title": "T", "artist": 5, "kind": "weird", "track_number": "abc", "disc_number": -3, "year": None,
                               "cover_urls": ["https://ok.test/a.jpg", "file:///C:/secret", 7], "evil": "x", "duration": "x"})
    assert info.title == "T" and info.artist == "5" and info.kind == "other"
    assert info.track_number == 0 and info.disc_number == 0 and info.year == "" and info.duration == 0.0
    assert info.cover_urls == ("https://ok.test/a.jpg",)         # only https pictures are ever downloaded
    assert not hasattr(info, "evil")


# --- MusicBrainz -------------------------------------------------------------------------------------------------

def release(title, kind="Album", secondary=(), date="2020-03-20", status="Official", rid="r1", number="9", count=14):
    group = {"primary-type": kind}
    if secondary:
        group["secondary-types"] = list(secondary)
    data = {"id": rid, "title": title, "status": status, "release-group": group, "artist-credit": [{"name": "The Weeknd"}],
            "media": [{"position": 1, "track-count": count, "track": [{"number": number}]}]}
    if date:
        data["date"] = date
    return data


def recording(releases, title="Blinding Lights", length=200000):
    return {"title": title, "length": length, "first-release-date": "2019-11-29",
            "artist-credit": [{"name": "The Weeknd", "joinphrase": ""}], "releases": releases}


def mb(recordings):
    c, session = client(lambda url, params: FakeResponse(payload={"recordings": recordings}), name="MusicBrainz")
    return MusicBrainz(c), session


def test_musicbrainz_prefers_the_official_studio_album_and_also_offers_the_single():
    found, _ = mb([recording([
        release("Hits 2020", "Album", ["Compilation"], date="2020-01-01", rid="c"),
        release("Blinding Lights", "Single", date="2019-11-29", rid="s"),
        release("After Hours", "Album", date="2020-03-20", rid="a"),
        release("Live at SoFi", "Album", ["Live"], date="2023-03-03", rid="l"),
    ])])
    infos = found.search("Blinding Lights", "The Weeknd")
    assert [(i.album, i.kind) for i in infos] == [("After Hours", "album"), ("Blinding Lights", "single")]
    first = infos[0]
    assert (first.year, first.track_number, first.track_total, first.disc_number, first.duration) == ("2020", 9, 14, 1, 200.0)
    assert first.album_artist == "The Weeknd" and first.release_id == "a"
    assert first.cover_urls[0].endswith("/release/a/front-1200") and first.thumb_url.endswith("/release/a/front-250")


def test_musicbrainz_ranks_releases_by_kind_then_official_then_date():
    found, _ = mb([recording([
        release("Bootleg", "Album", status="Bootleg", date="2018-01-01", rid="b"),
        release("Later", "Album", date="2021-01-01", rid="2"),
        release("Earlier", "Album", date="2020-01-01", rid="1"),
        release("Soundtrack", "Album", ["Soundtrack"], date="2019-01-01", rid="o"),
    ])])
    assert found.search("x")[0].album == "Earlier"


def test_musicbrainz_year_falls_back_to_the_first_release_and_vinyl_tracks_have_no_number():
    found, _ = mb([recording([release("Old LP", date=None, number="A1")])])
    info = found.search("x")[0]
    assert info.year == "2019" and info.track_number == 0


def test_musicbrainz_query_escapes_quotes_and_asks_for_json():
    found, session = mb([])
    found.search('Say "Hi" \\ now', 'Gu"ns')
    url, params = session.calls[0]
    assert url.endswith("/ws/2/recording") and params["fmt"] == "json"
    assert params["query"] == 'recording:"Say \\"Hi\\" \\\\ now" AND artist:"Gu\\"ns"'
    found.search("Only title")
    assert session.calls[1][1]["query"] == 'recording:"Only title"'


def test_musicbrainz_skips_recordings_without_a_release():
    found, _ = mb([recording([])])
    assert found.search("x") == []


# --- Deezer and iTunes -------------------------------------------------------------------------------------------

def deezer_routes(url, params):
    if url.endswith("search/track"):
        return FakeResponse(payload={"data": [
            {"id": 1, "title": "Blinding Lights", "duration": 200, "artist": {"name": "The Weeknd"},
             "album": {"id": 9, "title": "After Hours", "cover_xl": "https://cdn/x1000.jpg", "cover_big": "https://cdn/x500.jpg", "cover_medium": "https://cdn/x250.jpg"}}]})
    if url.endswith("track/1"):
        return FakeResponse(payload={"track_position": 9, "disk_number": 1, "release_date": "2020-03-20", "album": {"id": 9}})
    if url.endswith("album/9"):
        return FakeResponse(payload={"record_type": "album", "nb_tracks": 14, "release_date": "2020-03-20",
                                     "genres": {"data": [{"name": "R&B"}]}, "artist": {"name": "The Weeknd"}})
    if url.endswith("search/album"):
        return FakeResponse(payload={"data": [{"cover_xl": "https://cdn/album1000.jpg"}]})
    return FakeResponse(404)


def test_deezer_search_adds_year_genre_track_and_release_type():
    c, session = client(deezer_routes, name="Deezer")
    info = Deezer(c).search("Blinding Lights", "The Weeknd")[0]
    assert (info.kind, info.year, info.genre, info.track_number, info.track_total) == ("album", "2020", "R&B", 9, 14)
    assert info.cover_urls[0] == "https://cdn/x1000.jpg" and info.thumb_url == "https://cdn/x250.jpg"
    assert session.calls[0][1]["q"] == "The Weeknd Blinding Lights"      # a plain query: the advanced syntax finds nothing


def test_deezer_keeps_the_basic_data_when_the_details_fail():
    def routes(url, params):
        return deezer_routes(url, params) if url.endswith("search/track") else FakeResponse(503)

    c, _ = client(routes, name="Deezer")
    info = Deezer(c).search("Blinding Lights", "The Weeknd")[0]
    assert info.title == "Blinding Lights" and info.genre == "" and info.year == ""


def test_deezer_errors_inside_a_200_are_reported():
    c, _ = client(lambda url, params: FakeResponse(payload={"error": {"code": 4}}), name="Deezer")
    with pytest.raises(MetadataRateLimited):
        Deezer(c).search("x")
    c2, _ = client(lambda url, params: FakeResponse(payload={"error": {"code": 800}}), name="Deezer")
    with pytest.raises(MetadataNetworkError):
        Deezer(c2).search("x")


def test_deezer_finds_a_cover_by_album():
    c, _ = client(deezer_routes, name="Deezer")
    assert Deezer(c).find_cover("After Hours", "The Weeknd") == ("https://cdn/album1000.jpg",)


def test_itunes_asks_for_a_1000_pixel_cover_and_understands_singles():
    assert artwork("https://is1.test/a/b/100x100bb.jpg", 1000) == "https://is1.test/a/b/1000x1000bb.jpg"
    payload = {"results": [
        {"trackName": "Song", "artistName": "A", "collectionName": "Song - Single", "releaseDate": "2021-05-01T07:00:00Z",
         "primaryGenreName": "Pop", "trackNumber": 1, "trackCount": 1, "discNumber": 1, "trackTimeMillis": 180000,
         "artworkUrl100": "https://is1.test/a/100x100bb.jpg"},
        {"trackName": "Hit", "artistName": "A", "collectionName": "Now 60", "collectionArtistName": "Various Artists"}]}
    c, session = client(lambda url, params: FakeResponse(payload=payload), name="iTunes")
    single, compilation = ITunes(c).search("Song", "A")
    assert (single.album, single.kind, single.year, single.genre, single.duration) == ("Song", "single", "2021", "Pop", 180.0)
    assert single.cover_urls == ("https://is1.test/a/1000x1000bb.jpg",) and single.thumb_url.endswith("300x300bb.jpg")
    assert compilation.kind == "compilation"
    assert session.calls[0][1]["entity"] == "song"


# --- reading what the file says ----------------------------------------------------------------------------------

def test_a_file_name_is_read_in_both_orders():
    assert [(q.title, q.artist) for q in autotag.parse_filename("C:/m/The Weeknd - Blinding Lights.mp3")] == \
           [("Blinding Lights", "The Weeknd"), ("The Weeknd", "Blinding Lights")]
    assert [(q.title, q.artist) for q in autotag.parse_filename("07. Song_Name.flac")] == [("Song Name", None)]
    assert [(q.title, q.artist) for q in autotag.parse_filename("03 - A - B.mp3")] == [("B", "A"), ("A", "B")]


def test_the_users_words_win_over_the_tags_and_the_tags_over_the_name():
    tags = tagwriter.TagInfo(title="Tag Title", artist="Tag Artist")
    assert [(q.title, q.artist) for q in autotag.queries_for(tags, "x.mp3", "Mine", "Me")] == [("Mine", "Me")]
    assert [(q.title, q.artist) for q in autotag.queries_for(tags, "x.mp3", None, "Me")] == [("Tag Title", "Me")]
    assert [(q.title, q.artist) for q in autotag.queries_for(tags, "A - B.mp3")] == [("Tag Title", "Tag Artist")]
    assert [(q.title, q.artist) for q in autotag.queries_for(tagwriter.TagInfo(title="T"), "A - B.mp3")] == [("T", None)]
    assert len(autotag.queries_for(tagwriter.TagInfo(), "A - B.mp3")) == 2
    assert autotag.queries_for(tagwriter.TagInfo(), "x.mp3", None, "OnlyArtist") == []     # an artist alone is not enough


# --- ranking -----------------------------------------------------------------------------------------------------

def info(title="Blinding Lights", artist="The Weeknd", album="After Hours", kind="album", year="2020", duration=200.0, source="musicbrainz", **kw):
    return SongInfo(source=source, title=title, artist=artist, album=album, kind=kind, year=year, duration=duration, **kw)


def test_similarity_is_forgiving_with_accents_and_extra_artists_but_not_with_remixes():
    assert autotag.similarity("Tití Me Preguntó", "titi me pregunto") == 1.0
    assert autotag.similarity("The Weeknd", "The Weeknd feat. Daft Punk") >= 0.88
    assert autotag.similarity("Blinding Lights", "Blinding Lights (Remix)") < autotag.SURE_TITLE
    assert autotag.similarity("", "x") == 0.0


def test_studio_albums_beat_compilations_and_live_versions_and_the_original_year_wins_ties():
    q = autotag.Query("Blinding Lights", "The Weeknd")
    ranked = autotag.rank([(info(album="Hits", kind="compilation"), q), (info(album="Live", kind="live", duration=253), q),
                           (info(album="Deluxe", year="2021"), q), (info(), q)], 200)
    assert [i.album for i, _ in ranked][:2] == ["After Hours", "Deluxe"]
    assert [i.kind for i, _ in ranked][2:] == ["compilation", "live"]


def test_a_remix_nobody_asked_for_is_penalised_but_not_when_the_user_asked_for_it():
    plain = autotag.score(info(title="Blinding Lights (Remix)"), autotag.Query("Blinding Lights", "The Weeknd"), 200)
    asked = autotag.score(info(title="Blinding Lights (Remix)"), autotag.Query("Blinding Lights (Remix)", "The Weeknd"), 200)
    assert asked > plain + 10


def test_duplicates_across_sources_are_listed_once():
    q = autotag.Query("Blinding Lights", "The Weeknd")
    ranked = autotag.rank([(info(), q), (info(source="deezer"), q), (info(title="Blinding Lights ", source="itunes"), q)], 200)
    assert len(ranked) == 1 and ranked[0][0].source == "musicbrainz"       # the first source wins the tie (it also gets a bonus)


def test_at_most_five_candidates_are_offered():
    q = autotag.Query("Song", "A")
    many = [(info(title="Song", artist="A", album=f"Album {n}"), q) for n in range(9)]
    assert len(autotag.rank(many, 200)) == autotag.MAX_CANDIDATES


@pytest.mark.parametrize("candidate,query,seconds,sure", [
    (dict(), autotag.Query("Blinding Lights", "The Weeknd"), 200, True),
    (dict(), autotag.Query("Blinding Lights", "The Weeknd"), 0, True),                  # no duration known: the names decide
    (dict(), autotag.Query("Blinding Lights"), 200, False),                              # no artist: never sure
    (dict(kind="live"), autotag.Query("Blinding Lights", "The Weeknd"), 200, False),
    (dict(kind="compilation"), autotag.Query("Blinding Lights", "The Weeknd"), 200, False),
    (dict(duration=262), autotag.Query("Blinding Lights", "The Weeknd"), 200, False),    # a different cut of the song
    (dict(artist="Someone Else"), autotag.Query("Blinding Lights", "The Weeknd"), 200, False),
    (dict(title="Blinding Lights (Remix)"), autotag.Query("Blinding Lights", "The Weeknd"), 200, False),
])
def test_only_clear_matches_are_applied_without_asking(candidate, query, seconds, sure):
    assert autotag.is_sure(info(**candidate), query, seconds) is sure


# --- identifying a file ------------------------------------------------------------------------------------------

class FakeSource:
    def __init__(self, results=(), error=None):
        self.results, self.error, self.calls = list(results), error, []

    def search(self, title, artist=None, limit=5):
        self.calls.append((title, artist))
        if self.error:
            raise self.error
        return [r for r in self.results]

    def find_cover(self, album, artist):
        if self.error:
            raise self.error
        return ("https://cdn/fallback.jpg",)


def tagger(mb_results=(), deezer_results=(), itunes_results=(), tags=None, **sources):
    t = autotag.AutoTagger(musicbrainz=sources.get("mb") or FakeSource(mb_results), deezer=sources.get("deezer") or FakeSource(deezer_results),
                           itunes=sources.get("itunes") or FakeSource(itunes_results), images=sources.get("images"),
                           reader=lambda path: tags or tagwriter.TagInfo(path=path, duration=200.0),
                           writer=sources.get("writer"), renamer=sources.get("renamer"))
    return t


def test_a_clear_match_is_found_by_musicbrainz_alone_and_no_fallback_is_asked():
    t = tagger(mb_results=[info()])
    result = t.identify("The Weeknd - Blinding Lights.mp3")
    assert result.sure and result.candidates[0].album == "After Hours" and result.error is None
    assert t.deezer.calls == [] and t.itunes.calls == []


def test_the_name_is_tried_in_both_orders_and_the_right_one_wins():
    def only_right(title, artist=None, limit=5):
        return [info()] if (title, artist) == ("Blinding Lights", "The Weeknd") else []

    mb_source = FakeSource()
    mb_source.search = only_right
    result = tagger(mb=mb_source).identify("Blinding Lights - The Weeknd.mp3")
    assert result.sure and result.candidates[0].title == "Blinding Lights"


def test_when_musicbrainz_is_unsure_deezer_and_itunes_are_asked_and_may_settle_it():
    t = tagger(mb_results=[info(kind="live", album="Live")], deezer_results=[info(source="deezer")])
    result = t.identify("The Weeknd - Blinding Lights.mp3")
    assert result.sure and result.candidates[0].source == "deezer"
    assert t.itunes.calls == []                                   # Deezer settled it


def test_with_no_artist_the_best_guesses_are_listed_for_the_user_to_choose():
    result = tagger(mb_results=[info()]).identify("Blinding Lights.mp3")
    assert not result.sure and len(result.candidates) == 1


def test_nothing_found_anywhere_is_an_answer_not_a_crash():
    result = tagger().identify("Unknown - Nothing.mp3")
    assert result.candidates == [] and "No encontré" in result.error and not result.sure


def test_a_failing_backup_is_ignored_when_there_are_candidates_and_reported_when_there_are_none():
    broken = FakeSource(error=MetadataNetworkError("sin conexión"))
    assert tagger(mb_results=[info(kind="live")], deezer=broken, itunes=FakeSource()).identify("A - B.mp3").candidates
    with pytest.raises(MetadataNetworkError):
        tagger(deezer=broken).identify("A - B.mp3")


def test_a_file_without_title_or_artist_to_go_on_explains_what_to_do():
    result = tagger().identify("...mp3", artist="OnlyArtist")
    assert "Escríbelos tú" in result.error


def test_an_unreadable_file_is_reported_not_raised():
    def broken_reader(path):
        raise tagwriter.MetadataError("No pude leer el archivo de audio (¿está dañado?).")

    t = autotag.AutoTagger(musicbrainz=FakeSource(), deezer=FakeSource(), itunes=FakeSource(), reader=broken_reader)
    assert "dañado" in t.identify("x.mp3").error


def test_a_file_that_already_has_everything_is_flagged_complete():
    full = tagwriter.TagInfo(title="T", artist="A", album="B", year="2020", track=1, has_cover=True)
    assert tagger(mb_results=[info()], tags=full).identify("x.mp3").complete is True
    assert tagwriter.is_complete(tagwriter.TagInfo(title="T", artist="A", album="B", year="2020", track=1)) is False   # no cover


# --- what will change, and writing it ----------------------------------------------------------------------------

def test_the_changes_list_only_what_differs_and_never_blanks_a_field():
    tags = tagwriter.TagInfo(title="Blinding Lights", artist="Old", album="", year="2020", genre="Pop", track=9, track_total=14, has_cover=True)
    candidate = info(genre="", track_number=9, track_total=14, cover_urls=("https://c/a.jpg",))
    rows = {r["field"]: r for r in autotag.AutoTagger.changes(tags, candidate)}
    assert set(rows) == {"artist", "album", "cover"}      # same title/year/track are not listed; empty genre and album artist are not changes
    assert rows["artist"]["old"] == "Old" and rows["artist"]["new"] == "The Weeknd" and rows["cover"]["old"] == "sí"


def test_applying_enriches_the_genre_downloads_the_cover_writes_and_renames_in_that_order():
    log = []
    images = type("Img", (), {"get_image": lambda self, url: log.append(("cover", url)) or b"JPEG"})()
    written = {}

    def writer(path, song, cover):
        log.append("write")
        written.update(song=song, cover=cover)

    def renamer(path, title):
        log.append(("rename", title))
        return "C:/music/Blinding Lights.mp3"

    t = tagger(deezer_results=[info(source="deezer", genre="R&B")], images=images, writer=writer, renamer=renamer)
    result = t.apply("C:/music/x.mp3", info(cover_urls=("https://c/a.jpg",)), rename=True)
    assert log == [("cover", "https://c/a.jpg"), "write", ("rename", "Blinding Lights")]
    assert written["song"].genre == "R&B" and written["cover"] == b"JPEG"
    assert result == {"path": "C:/music/Blinding Lights.mp3", "cover": True, "genre": "R&B"}


def test_apply_does_not_rename_unless_asked_and_survives_a_missing_cover():
    calls = []
    images = type("Img", (), {"get_image": lambda self, url: (_ for _ in ()).throw(MetadataNotFound("404"))})()
    t = tagger(images=images, itunes=FakeSource(error=MetadataNetworkError("x")), deezer=FakeSource(error=MetadataNetworkError("x")),
               writer=lambda p, s, c: calls.append(c), renamer=lambda p, title: calls.append("renamed"))
    result = t.apply("x.mp3", info(cover_urls=("https://c/a.jpg",)))
    assert calls == [None] and result["cover"] is False and result["path"] == "x.mp3"


def test_the_cover_falls_back_to_deezer_when_the_cover_archive_has_none():
    fetched = []

    def get_image(self, url):
        fetched.append(url)
        if "coverartarchive" in url:
            raise MetadataNotFound("404")
        return b"IMG"

    images = type("Img", (), {"get_image": get_image})()
    t = tagger(images=images)
    assert t.fetch_cover(info(cover_urls=("https://coverartarchive.org/release/a/front-1200",))) == b"IMG"
    assert fetched[-1] == "https://cdn/fallback.jpg"


def test_folders_are_searched_for_supported_audio_only(tmp_path):
    (tmp_path / "sub").mkdir()
    for name in ("b.mp3", "a.FLAC", "notes.txt", "sub/c.m4a", "sub/d.jpg"):
        (tmp_path / name).write_bytes(b"x")
    found = autotag.collect_audio_files([str(tmp_path), str(tmp_path / "b.mp3"), str(tmp_path / "notes.txt"), str(tmp_path / "nope.mp3")])
    assert [os.path.basename(p) for p in found] == ["a.FLAC", "b.mp3", "c.m4a"]      # no repeats, no other file types


# --- tag writing on real audio files ----------------------------------------------------------------------------

def ffmpeg():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def make_audio(folder, name):
    codec = {".m4a": ["-c:a", "aac"], ".ogg": ["-c:a", "libvorbis"], ".opus": ["-c:a", "libopus"]}.get(os.path.splitext(name)[1], [])
    path = os.path.join(str(folder), name)
    done = subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", *codec, path],
                          capture_output=True)
    if done.returncode != 0:
        pytest.skip("this ffmpeg cannot make " + name)
    return path


def png(width, height):
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 90)).save(buffer, "PNG")
    return buffer.getvalue()


SONG = SongInfo(title="Tití Me Preguntó", artist="Bad Bunny", album="Un Verano Sin Ti", album_artist="Bad Bunny", year="2022",
                genre="Reggaeton", track_number=14, track_total=23, disc_number=1)


@pytest.mark.skipif(ffmpeg() is None, reason="needs the bundled ffmpeg")
@pytest.mark.parametrize("name", ["a.mp3", "a.flac", "a.m4a", "a.ogg", "a.opus"])
def test_tags_and_cover_are_written_and_read_back_in_every_format(tmp_path, name):
    path = make_audio(tmp_path, name)
    assert tagwriter.is_complete(tagwriter.read_tags(path)) is False
    tagwriter.write_tags(path, SONG, png(1600, 1200))
    t = tagwriter.read_tags(path)
    assert (t.title, t.artist, t.album, t.album_artist, t.year, t.genre) == \
           ("Tití Me Preguntó", "Bad Bunny", "Un Verano Sin Ti", "Bad Bunny", "2022", "Reggaeton")      # accents survive exactly
    assert (t.track, t.track_total, t.disc, t.has_cover) == (14, 23, 1, True)
    assert tagwriter.is_complete(t) and 1.5 < t.duration < 2.5
    assert not [f for f in os.listdir(tmp_path) if f.endswith(tagwriter.PART_SUFFIX)]


@pytest.mark.skipif(ffmpeg() is None, reason="needs the bundled ffmpeg")
def test_an_mp3_is_really_id3v2_3_with_the_year_in_tyer(tmp_path):
    """Regression: saving as v2.3 alone left the year in the v2.4 frame TDRC, which v2.3 players ignore."""
    from mutagen.id3 import ID3
    path = make_audio(tmp_path, "a.mp3")
    tagwriter.write_tags(path, SONG, png(300, 300))
    raw = ID3(path, translate=False)           # translate=False: do not let mutagen hide what is really stored
    assert raw.version == (2, 3, 0)
    assert [str(y) for y in raw["TYER"].text] == ["2022"] and "TDRC" not in raw
    assert raw["TIT2"].encoding == 1           # UTF-16: what v2.3 players read for accents
    apic = [frame for key, frame in raw.items() if key.startswith("APIC")][0]
    assert apic.type == 3 and apic.mime == "image/jpeg"


@pytest.mark.skipif(ffmpeg() is None, reason="needs the bundled ffmpeg")
def test_empty_fields_leave_existing_tags_alone_and_other_frames_survive(tmp_path):
    from mutagen.id3 import ID3, TXXX
    path = make_audio(tmp_path, "a.mp3")
    tagwriter.write_tags(path, SONG, png(300, 300))
    extra = ID3(path)
    extra.add(TXXX(encoding=1, desc="mine", text=["keep"]))
    extra.save(path, v2_version=3)
    tagwriter.write_tags(path, SongInfo(title="New Title"))           # nothing else, no cover
    t = tagwriter.read_tags(path)
    assert (t.title, t.artist, t.year, t.genre, t.track, t.has_cover) == ("New Title", "Bad Bunny", "2022", "Reggaeton", 14, True)
    assert "TXXX:mine" in ID3(path)


def test_a_big_cover_is_shrunk_to_a_jpeg_of_at_most_1000_pixels_and_a_small_jpeg_is_left_alone():
    from PIL import Image
    data, size = tagwriter.prepare_cover(png(3000, 2000))
    image = Image.open(io.BytesIO(data))
    assert image.format == "JPEG" and max(image.size) == 1000 and size == image.size
    jpeg = io.BytesIO()
    Image.new("RGB", (500, 500)).save(jpeg, "JPEG")
    kept, kept_size = tagwriter.prepare_cover(jpeg.getvalue())
    assert kept == jpeg.getvalue() and kept_size == (500, 500)
    with pytest.raises(tagwriter.MetadataError, match="no es una imagen"):
        tagwriter.prepare_cover(b"not an image")


def test_an_unsupported_file_is_refused_clearly(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    with pytest.raises(UnsupportedAudioFormat, match="mp3, flac, m4a, ogg y opus"):
        tagwriter.read_tags(str(wav))
    with pytest.raises(UnsupportedAudioFormat):
        tagwriter.write_tags(str(wav), SONG)


def test_a_damaged_file_is_left_exactly_as_it_was(tmp_path):
    damaged = tmp_path / "broken.flac"
    damaged.write_bytes(b"this is not flac data" * 10)
    before = damaged.read_bytes()
    with pytest.raises(TagWriteError, match="dañado"):
        tagwriter.write_tags(str(damaged), SONG)
    assert damaged.read_bytes() == before and os.listdir(tmp_path) == ["broken.flac"]
    with pytest.raises(tagwriter.MetadataError, match="dañado"):
        tagwriter.read_tags(str(damaged))


@pytest.mark.skipif(ffmpeg() is None, reason="needs the bundled ffmpeg")
def test_a_file_open_in_a_player_gives_a_clear_message_and_is_untouched(tmp_path, monkeypatch):
    path = make_audio(tmp_path, "a.mp3")
    before = open(path, "rb").read()

    def locked(src, dst):
        raise PermissionError("in use")

    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(TagWriteError, match="abierto en otro programa"):
        tagwriter.write_tags(path, SONG)
    monkeypatch.undo()
    assert open(path, "rb").read() == before and os.listdir(tmp_path) == ["a.mp3"]    # the work copy was cleaned up


def test_renaming_uses_only_the_title_and_never_overwrites(tmp_path):
    first = tmp_path / "x.mp3"
    first.write_bytes(b"1")
    (tmp_path / "Tití Me Preguntó.mp3").write_bytes(b"other song")
    new = tagwriter.rename_to_title(str(first), "Tití Me Preguntó")
    assert os.path.basename(new) == "Tití Me Preguntó (2).mp3"
    assert (tmp_path / "Tití Me Preguntó.mp3").read_bytes() == b"other song" and (tmp_path / "Tití Me Preguntó (2).mp3").read_bytes() == b"1"
    assert tagwriter.rename_to_title(new, "Tití Me Preguntó (2)") == new                # already named so: nothing to do
    odd = tmp_path / "y.mp3"
    odd.write_bytes(b"2")
    renamed = tagwriter.rename_to_title(str(odd), 'A/B: "C"?')
    assert os.path.basename(renamed) == "AB C.mp3" and os.path.exists(renamed) and not (tmp_path / "y.mp3").exists()   # forbidden characters are dropped


def _window_api(tmp_path, monkeypatch):
    import const
    import downloader
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path))                  # never touch the real settings
    monkeypatch.setattr(downloader, "DOWNLOADS_DIR", downloader.DOWNLOADS_DIR)    # restored after the test
    from gui.backend import Api
    return Api()


# --- The window's tag jobs (gui/tags_jobs.py) ---------------------------------------------------------------------

def wait_until_idle(jobs, seconds=5):
    import time
    end = time.time() + seconds
    while jobs.busy and time.time() < end:
        time.sleep(0.01)
    assert not jobs.busy, "the job never finished"


class FakeTagger:
    """Stands in for AutoTagger: `plan[path]` is an Identification, an exception to raise, or a SongInfo-less 'not found'."""

    def __init__(self, plan=None, apply_plan=None):
        self.plan, self.apply_plan, self.identified, self.applied = plan or {}, apply_plan or {}, [], []

    def identify(self, path, title=None, artist=None):
        self.identified.append((os.path.basename(path), title, artist))
        outcome = self.plan[os.path.basename(path)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @staticmethod
    def changes(tags, info):
        return [{"field": "title", "label": "Título", "old": tags.title, "new": info.title}]

    def enrich(self, info):
        info.genre = info.genre or "Pop"
        return info

    def apply(self, path, info, rename=False):
        self.applied.append((os.path.basename(path), rename))
        outcome = self.apply_plan.get(os.path.basename(path))
        if isinstance(outcome, Exception):
            raise outcome
        return {"path": os.path.join(os.path.dirname(path), info.title + ".mp3") if rename else path, "cover": True, "genre": "Pop"}


def ident(path, candidates=(), sure=False, error=None, complete=False):
    return autotag.Identification(path=path, tags=tagwriter.TagInfo(path=path), candidates=list(candidates), sure=sure, error=error, complete=complete)


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    from gui.tags_jobs import TagJobs
    monkeypatch.setattr(tagwriter, "read_tags", lambda path: tagwriter.TagInfo(path=path, title="Done" if "done" in path else "",
                        artist="A" if "done" in path else "", album="B" if "done" in path else "", year="2020" if "done" in path else "",
                        track=1 if "done" in path else 0, has_cover="done" in path))
    for name in ("sure.mp3", "review.mp3", "none.mp3", "done.mp3"):
        (tmp_path / name).write_bytes(b"x")
    return TagJobs(FakeTagger({"sure.mp3": ident("sure.mp3", [info()], sure=True), "review.mp3": ident("review.mp3", [info(title="Other")]),
                               "none.mp3": ident("none.mp3", error="No encontré esta canción")})), tmp_path


def paths_of(folder, *names):
    return [str(folder / n) for n in names]


def test_scanning_lists_the_audio_files_with_their_current_tags(jobs, monkeypatch):
    tagger_jobs, folder = jobs
    (folder / "notes.txt").write_text("no")
    entries = tagger_jobs.scan([str(folder)])
    assert [e["name"] for e in entries] == ["done.mp3", "none.mp3", "review.mp3", "sure.mp3"]
    assert entries[0]["tags"]["complete"] is True and entries[1]["tags"]["complete"] is False

    def unreadable(path):
        raise tagwriter.MetadataError("No pude leer el archivo de audio (¿está dañado?).")

    monkeypatch.setattr(tagwriter, "read_tags", unreadable)
    assert "dañado" in tagger_jobs.scan([str(folder / "sure.mp3")])[0]["error"]


def test_identifying_reports_each_file_then_a_summary_and_skips_the_complete_ones(jobs):
    tagger_jobs, folder = jobs
    assert tagger_jobs.identify(paths_of(folder, "sure.mp3", "review.mp3", "none.mp3", "done.mp3"))["ok"]
    wait_until_idle(tagger_jobs)
    events = tagger_jobs.get_events()
    done = {e["path"].split(os.sep)[-1]: e for e in events if e["kind"] == "identified"}
    assert {k: v["status"] for k, v in done.items()} == {"sure.mp3": "sure", "review.mp3": "review", "none.mp3": "notfound", "done.mp3": "complete"}
    assert done["sure.mp3"]["candidates"][0]["kind_label"] == "Álbum de estudio" and done["sure.mp3"]["changes"]      # the clear match lists its changes
    assert done["review.mp3"]["changes"] == [] and "No encontré" in done["none.mp3"]["error"]
    last = events[-1]
    assert last["kind"] == "finished" and last["counts"] == {"sure": 1, "review": 1, "notfound": 1, "complete": 1, "error": 0}
    assert [e["kind"] for e in events].count("identifying") == 4
    assert ("done.mp3",) not in [(n,) for n, _t, _a in tagger_jobs.tagger.identified]                              # the complete one was never looked up


def test_the_complete_ones_are_searched_when_asked_or_when_the_user_types_a_title(jobs):
    tagger_jobs, folder = jobs
    tagger_jobs.tagger.plan["done.mp3"] = ident("done.mp3", [info()], sure=True)
    tagger_jobs.identify(paths_of(folder, "done.mp3"), skip_complete=False)
    wait_until_idle(tagger_jobs)
    tagger_jobs.identify(paths_of(folder, "done.mp3"), title="My title", skip_complete=True)
    wait_until_idle(tagger_jobs)
    assert [(t, a) for _n, t, a in tagger_jobs.tagger.identified] == [(None, None), ("My title", None)]


def test_no_internet_stops_the_whole_run_with_one_clear_message(jobs):
    tagger_jobs, folder = jobs
    tagger_jobs.tagger.plan["sure.mp3"] = MetadataNetworkError("No pude conectar con MusicBrainz. Revisa tu conexión a internet.")
    tagger_jobs.identify(paths_of(folder, "sure.mp3", "review.mp3", "none.mp3"))
    wait_until_idle(tagger_jobs)
    events = tagger_jobs.get_events()
    assert [e["kind"] for e in events if e["kind"] == "identified"] == ["identified"]            # the others were not even tried
    assert "internet" in events[-1]["error"] and events[-1]["kind"] == "finished"
    assert [n for n, _t, _a in tagger_jobs.tagger.identified] == ["sure.mp3"]


def test_one_bad_file_does_not_stop_the_others(jobs):
    tagger_jobs, folder = jobs
    tagger_jobs.tagger.plan["sure.mp3"] = tagwriter.MetadataError("No pude leer el archivo de audio (¿está dañado?).")
    tagger_jobs.identify(paths_of(folder, "sure.mp3", "review.mp3"))
    wait_until_idle(tagger_jobs)
    statuses = [e["status"] for e in tagger_jobs.get_events() if e["kind"] == "identified"]
    assert statuses == ["error", "review"]


def test_cancelling_stops_after_the_file_in_progress(jobs):
    import threading
    tagger_jobs, folder = jobs
    started, release = threading.Event(), threading.Event()
    original = tagger_jobs.tagger.identify

    def slow(path, title=None, artist=None):
        started.set()
        release.wait(3)
        return original(path, title, artist)

    tagger_jobs.tagger.identify = slow
    tagger_jobs.identify(paths_of(folder, "sure.mp3", "review.mp3", "none.mp3"))
    assert started.wait(3) and tagger_jobs.cancel() is True
    release.set()
    wait_until_idle(tagger_jobs)
    events = tagger_jobs.get_events()
    assert [e["kind"] for e in events].count("identified") == 1 and events[-1]["cancelled"] is True


def test_a_second_job_cannot_start_while_one_is_running(jobs):
    import threading
    tagger_jobs, folder = jobs
    release = threading.Event()
    original = tagger_jobs.tagger.identify
    tagger_jobs.tagger.identify = lambda path, title=None, artist=None: (release.wait(3), original(path, title, artist))[1]
    assert tagger_jobs.identify(paths_of(folder, "sure.mp3"))["ok"]
    second = tagger_jobs.identify(paths_of(folder, "review.mp3"))
    assert second["ok"] is False and "en marcha" in second["error"]
    release.set()
    wait_until_idle(tagger_jobs)


def test_preparing_shows_the_enriched_candidate_and_what_would_change(jobs):
    tagger_jobs, folder = jobs
    result = tagger_jobs.prepare(str(folder / "sure.mp3"), info(genre="").to_dict())
    assert result["ok"] and result["candidate"]["genre"] == "Pop" and result["changes"][0]["new"] == "Blinding Lights"


def test_applying_writes_each_file_renames_on_request_and_keeps_going_after_a_failure(jobs):
    tagger_jobs, folder = jobs
    tagger_jobs.tagger.apply_plan["review.mp3"] = TagWriteError("No pude cambiar «review.mp3»: está abierto en otro programa (cierra el reproductor) o no tienes permiso para modificarlo.")
    items = [{"path": str(folder / n), "candidate": info().to_dict()} for n in ("sure.mp3", "review.mp3", "none.mp3")]
    assert tagger_jobs.apply(items, rename=True)["ok"]
    wait_until_idle(tagger_jobs)
    events = tagger_jobs.get_events()
    applied = [e for e in events if e["kind"] == "applied"]
    assert [os.path.basename(e["new_path"]) for e in applied] == ["Blinding Lights.mp3", "Blinding Lights.mp3"]
    failed = [e for e in events if e["kind"] == "failed"]
    assert len(failed) == 1 and "abierto en otro programa" in failed[0]["error"]
    assert events[-1] == {**events[-1], "kind": "finished", "done": 2, "failed": 1, "error": None}
    assert all(rename for _n, rename in tagger_jobs.tagger.applied)


def test_applying_stops_when_the_internet_goes_away(jobs):
    tagger_jobs, folder = jobs
    tagger_jobs.tagger.apply_plan["sure.mp3"] = MetadataRateLimited("Deezer pide ir más despacio. Espera un minuto e inténtalo de nuevo.")
    items = [{"path": str(folder / n), "candidate": info().to_dict()} for n in ("sure.mp3", "review.mp3")]
    tagger_jobs.apply(items)
    wait_until_idle(tagger_jobs)
    events = tagger_jobs.get_events()
    assert [n for n, _r in tagger_jobs.tagger.applied] == ["sure.mp3"] and "despacio" in events[-1]["error"]


def test_applying_ignores_unsupported_files_and_an_empty_list(jobs):
    tagger_jobs, folder = jobs
    assert tagger_jobs.apply([])["ok"] is False
    assert tagger_jobs.apply([{"path": str(folder / "x.wav"), "candidate": {}}, {"path": None}, None])["ok"] is False
    assert tagger_jobs.tagger.applied == []


def test_files_dropped_on_the_window_are_forwarded_with_their_paths(tmp_path, monkeypatch):
    api = _window_api(tmp_path, monkeypatch)
    api._on_drop({"type": "drop", "dataTransfer": {"files": [{"name": "a.mp3", "pywebviewFullPath": "C:/m/a.mp3"}, {"name": "b.mp3"}, "junk"]}})
    api._on_drop({"type": "drop", "dataTransfer": {"files": []}})       # nothing usable: no event
    api._on_drop(None)
    events = api.get_tag_events()
    assert [(e["kind"], e["paths"]) for e in events] == [("dropped", ["C:/m/a.mp3"])]


def test_the_window_methods_for_tags_are_safe_with_bad_input(tmp_path, monkeypatch):
    api = _window_api(tmp_path, monkeypatch)
    assert api.tags_scan("not a list") == [] and api.tags_pick_files() == [] and api.tags_pick_folder() == []
    assert api.tags_cancel() is False and api.get_tag_events() == []
