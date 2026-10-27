"""Tests for finding a song by typing its name: the metadata search, the choice of the YouTube video, and the window.
No real network: the services are simulated."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apis import text_search
from apis.song_info import SongInfo
from apis.text_search import SongSearch, buscar_metadatos, coverage, to_dict
from apis.text_track import TextTrack
from apis.youtube import Candidate, rank_candidates, score_candidate
from apis.ytmusic import parse_song_details
from exceptions import MetadataBadResponse, MetadataNetworkError, MetadataRefused


class Source:
    def __init__(self, results=(), error=None):
        self.results, self.error, self.calls = list(results), error, 0

    def search(self, title, artist=None, limit=5):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.results)


def song(title="badtrip :(", artist="Mora", album="MICRODOSIS", **extra):
    return SongInfo(source=extra.pop("source", "itunes"), title=title, artist=artist, album=album, duration=extra.pop("duration", 191.6),
                    cover_urls=extra.pop("cover_urls", ("https://img/1000.jpg",)), **extra)


def search_with(**sources):
    return SongSearch([(name, source) for name, source in sources.items()])


# --- the metadata search -------------------------------------------------------------------------------------------

def test_typed_words_are_found_even_when_the_artist_writes_them_apart():
    assert coverage("badtrip mora", song("Bad Trip :(")) == 1.0
    assert coverage("badtrip mora", song("Bad Tribe", "Vortek's", "Un asile")) == 0.0


def test_a_short_word_must_be_a_whole_word():
    assert coverage("calenton mora", song("Ti Penso E Cambia Il Mondo", "Adriano Celentano, Gianni Morandi", "")) == 0.0
    assert coverage("calenton mora", song("CALENTÓN", "Mora", "")) == 1.0


def test_deezer_answers_and_itunes_is_not_asked():
    deezer, itunes = Source([song(source="deezer")]), Source([song()])
    found, problems = search_with(deezer=deezer, itunes=itunes).lookup("badtrip mora")
    assert found[0].source == "deezer" and itunes.calls == 0 and problems == []


@pytest.mark.parametrize("error", [MetadataRefused("Deezer negó el acceso (403)."), MetadataBadResponse("Deezer respondió algo inesperado.")])
def test_a_refusing_deezer_falls_back_to_itunes_and_is_not_asked_again_this_session(error):
    deezer, itunes = Source(error=error), Source([song()])
    search = search_with(deezer=deezer, itunes=itunes)
    assert search.lookup("badtrip mora")[0][0].source == "itunes"
    assert search.lookup("badtrip mora")[0][0].source == "itunes"
    assert deezer.calls == 1 and itunes.calls == 2 and "deezer" in search.blocked()


def test_a_timeout_or_an_empty_answer_skips_deezer_only_for_that_search():
    deezer = Source(error=MetadataNetworkError("No pude conectar con Deezer."))
    search = search_with(deezer=deezer, itunes=Source([song()]))
    assert search.lookup("badtrip mora")[0] and search.lookup("badtrip mora")[0]
    assert deezer.calls == 2 and search.blocked() == {}
    empty = Source([])
    assert search_with(deezer=empty, itunes=Source([song()])).lookup("badtrip mora")[0] and empty.calls == 1


def test_results_that_have_nothing_to_do_with_the_words_do_not_count():
    junk = Source([song("Bad Tribe", "Vortek's", "Un asile"), song("Moja Ljubav", "Nina Badric", "LJUBAV")])
    found, _ = search_with(deezer=junk, itunes=Source([song()])).lookup("badtrip mora")
    assert [s.source for s in found] == ["itunes"]


def test_every_service_failing_gives_an_empty_list_and_never_an_exception():
    down = lambda: Source(error=MetadataNetworkError("sin internet"))
    search = search_with(deezer=down(), itunes=down(), ytmusic=Source(error=RuntimeError("changed")))
    found, problems = search.lookup("badtrip mora")
    assert found == [] and len(problems) == 3
    text_search._default = search
    assert buscar_metadatos("badtrip mora") == [] and buscar_metadatos("") == []


def test_the_same_song_on_several_releases_is_listed_once_with_the_studio_album():
    found, _ = search_with(deezer=Source([song("Song", "A", "Hits 2020", kind="compilation"), song("Song", "A", "The Album", kind="album"),
                                          song("Other", "A", "The Album", kind="album")])).lookup("song a")
    assert [(s.title, s.album) for s in found] == [("Song", "The Album"), ("Other", "The Album")] or found[0].album == "The Album"
    assert len([s for s in found if s.title == "Song"]) == 1


def test_the_result_has_the_promised_shape_and_none_for_what_is_missing():
    assert to_dict(song(year="2023", track_number=6, source="deezer")) == {
        "titulo": "badtrip :(", "artista": "Mora", "album": "MICRODOSIS", "duracion": 192, "portada": "https://img/1000.jpg",
        "anio": 2023, "pista": 6, "fuente": "deezer"}
    bare = to_dict(song(cover_urls=()))
    assert bare["anio"] is None and bare["pista"] is None and bare["portada"] is None


def test_youtube_music_results_carry_the_duration():
    row = {"musicResponsiveListItemRenderer": {
        "flexColumns": [{"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": "badtrip :("}]}}},
                        {"musicResponsiveListItemFlexColumnRenderer": {"text": {"runs": [{"text": "Mora • MICRODOSIS • 3:12"}]}}}],
        "thumbnail": {"musicThumbnailRenderer": {"thumbnail": {"thumbnails": [{"url": "https://x/a=w120-h120-l90-rj"}]}}}}}
    assert parse_song_details({"contents": [row]}) == [{"title": "badtrip :(", "artist": "Mora", "album": "MICRODOSIS", "duration": 192,
                                                         "thumbnail": "https://x/a=w120-h120-l90-rj"}]


# --- choosing the video ---------------------------------------------------------------------------------------------

REAL = [  # what YouTube gave for "Mora badtrip :(" (captured), plus the concert cut the feature must push down
    Candidate("official", "Mora - Bad Trip :( (Visualizer) | MICRODOSIS", "Mora", 186, 5_000_000),
    Candidate("lyrics", "Mora - Bad Trip (Letra/Lyrics)", "Monday", 192, 900_000),
    Candidate("audio", "Mora - Badtrip (Audio)", "Temazos de Reggaeton & Trap", 192, 800_000),
    Candidate("lyricvideo", "Mora - Bad Trip :( (Lyric Video) S&R", "vfh", 237, 40_000),
    Candidate("clean", "Bad Trip :( (Clean Version) - Mora", "YayoClean", 190, 30_000),
    Candidate("letra", "Mora - Bad Trip :( || LETRA", "Status Music", 192, 60_000),
    Candidate("festival", "Mora - Bad Trip :( (Coca Cola Flow Fest 2022 GDL)", "Wiki Concerts", 331, 20_000),
    Candidate("8d", "Mora - badtrip :( (8D AUDIO)", "axlmvtias", 192, 10_000),
    Candidate("concert", "Mora - Bad Trip :( (Intro Concert Version)", "Mora", 190, 3_000_000),
]


def test_the_exact_duration_beats_the_official_channel_and_the_channel_decides_between_equals():
    ranked = rank_candidates(REAL, "badtrip :(", ["Mora"], 192, 1800, asked="badtrip mora")
    urls = [c.url for c in ranked]
    assert urls[0] in ("audio", "lyrics") and urls.index("official") > 1       # 192 s on the dot beats the official video, 6 s off
    assert urls.index("concert") > urls.index("official")            # "concert" costs 40 points
    assert "festival" not in urls                                    # 331 s: far too long to be this song
    same = [Candidate("a", "Mora - Bad Trip", "Mora", 192, 0), Candidate("b", "Mora - Bad Trip", "Reupload", 192, 0)]
    assert rank_candidates(same, "Bad Trip", ["Mora"], 192)[0].url == "a"


def test_the_points_follow_the_rules():
    def pts(duration, channel="Someone", title="Song"):
        return score_candidate(Candidate("v", title, channel, duration, 0), "Song", ["Artist"], 200)[0]
    far = pts(216)
    assert [round(pts(200 + d) - far, 2) for d in (0, 2, 3, 5, 8, 15)] == [51 + 25.5, 42.5 + 25.5, 34 + 25.5, 21.25 + 25.5, 8.5 + 25.5, 1.7 + 25.5]   # the bands
    assert pts(200) == pts(201) and pts(200) > pts(202) > pts(203) > pts(205) > pts(208) > pts(215) > pts(216)
    assert pts(200, "Artist - Topic") - pts(200) == 35 and pts(200, "Artist Fans") - pts(200) == 15      # official channel / name inside it
    assert pts(208, "Artist") < pts(200, "Someone") < pts(205, "Artist")   # exact beats the official channel 8 s off, not 5 s off


def test_a_word_the_user_typed_is_not_held_against_a_video_but_otherwise_it_costs_40():
    live = Candidate("l", "Mora - Bad Trip en vivo", "Mora", 192, 0)
    plain = Candidate("p", "Mora - Bad Trip", "Mora", 192, 0)
    assert score_candidate(plain, "Bad Trip", ["Mora"], 192)[0] - score_candidate(live, "Bad Trip", ["Mora"], 192)[0] >= 40
    assert score_candidate(live, "Bad Trip", ["Mora"], 192, asked="bad trip mora en vivo")[0] >= score_candidate(plain, "Bad Trip", ["Mora"], 192)[0] - 1


def test_each_artist_of_a_collaboration_can_be_the_channel():
    video = Candidate("v", "Despacito", "Daddy Yankee", 229, 0)
    assert score_candidate(video, "Despacito", ["Luis Fonsi & Daddy Yankee"], 229)[0] > score_candidate(video, "Despacito", ["Luis Fonsi"], 229)[0] + 30


def test_an_unknown_duration_does_not_reject_every_video():
    assert rank_candidates([Candidate("v", "Mora - Bad Trip", "Mora", 186, 1)], "Bad Trip", ["Mora"], 0)


# --- the song as the downloader sees it -----------------------------------------------------------------------------

def test_a_searched_song_looks_like_a_spotify_track():
    track = TextTrack(song(year="2023", track_number=6), asked="badtrip mora")
    meta = track.get_metadata()
    assert track.resource_id.isalnum() and "_" not in track.resource_id            # the window and the planner split ids on "_"
    assert meta["artist"] == ["Mora"] and meta["duration_ms"] == 191600 and meta["image_url"] == "https://img/1000.jpg"
    assert meta["release_date"] == "2023" and meta["track_num"] == 6
    assert track.get_filename() == "Mora - badtrip (" and track.get_filename("title") == "badtrip ("   # ':' is not allowed in a name


def test_a_song_without_cover_gets_the_placeholder():
    assert TextTrack(song(cover_urls=())).get_metadata()["image_url"].startswith("https://")


# --- the window -----------------------------------------------------------------------------------------------------

def window(tmp_path, monkeypatch):
    import const
    import downloader
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(downloader, "DOWNLOADS_DIR", str(tmp_path / "dl"))
    from gui.backend import Api
    api = Api()
    api._settings["downloads_dir"] = str(tmp_path / "dl")
    return api


def test_typing_a_name_needs_no_spotify_and_marks_only_the_first_result(tmp_path, monkeypatch):
    import login
    monkeypatch.setattr(login, "is_client_configured", lambda: False)             # no Spotify app: the text path must not care
    api = window(tmp_path, monkeypatch)
    api._cover_tagger = type("T", (), {"preview_cover": lambda self, info: ("data:image/jpeg;base64,AA", None)})()
    monkeypatch.setattr("gui.backend.search_songs", lambda text, limit: ([song(), song("Otra", "Mora", "X", source="deezer")], []))
    result = api.preview("badtrip mora")
    assert "error" not in result and result["kind"] == "search" and len(result["items"]) == 2
    assert result["preselect"] == [result["items"][0]["key"]]
    assert all(i["cover"].startswith("data:image") for i in result["items"])     # pictures come through the cover chain, not the blocked CDN
    assert api._pending["spotify"] is None and set(api._pending["tracks"]) == {i["key"] for i in result["items"]}


def test_nothing_found_and_services_down_are_told_apart(tmp_path, monkeypatch):
    api = window(tmp_path, monkeypatch)
    monkeypatch.setattr("gui.backend.search_songs", lambda text, limit: ([], []))
    assert "No encontré" in api.preview("zzzz qqqq")["error"]
    monkeypatch.setattr("gui.backend.search_songs", lambda text, limit: ([], ["Deezer negó el acceso (403)."]))
    assert "No pude buscar" in api.preview("zzzz qqqq")["error"]


def test_a_link_still_goes_the_spotify_way(tmp_path, monkeypatch):
    api = window(tmp_path, monkeypatch)
    assert "error" in api.preview("https://example.com/hola")                       # not a Spotify link: the old message, not a search
    assert api.preview("https://example.com/hola")["error"].startswith("Eso no parece")


def test_a_searched_song_is_tagged_from_what_the_service_said(tmp_path):
    from downloader import SpotifyDownloader
    calls = []
    d = SpotifyDownloader(None, None)
    d._tagger = type("T", (), {"apply": lambda self, path, info: calls.append((path, info.album)) or {"cover": True}})()
    d._tag_from_song_info("[1/1]", "x.mp3", song())
    assert calls == [("x.mp3", "MICRODOSIS")]
    d._tagger = type("T", (), {"apply": lambda self, path, info: (_ for _ in ()).throw(MetadataNetworkError("sin internet"))})()
    d._tag_from_song_info("[1/1]", "x.mp3", song())                                  # a failed tagging never fails the download


def test_a_guest_the_song_does_not_have_marks_another_recording():
    from apis.youtube import unknown_guests
    assert unknown_guests("Luis Fonsi - Despacito (Audio) ft. Justin Bieber", "Despacito Luis Fonsi") == ["justin bieber"]
    assert unknown_guests("Song (feat. A & B)", "Song X") == ["a", "b"]
    assert unknown_guests("Despacito ft. Daddy Yankee", "Despacito Luis Fonsi Daddy Yankee") == []     # a guest the song does have
    assert unknown_guests("Dancing with Myself", "Dancing with Myself Billy Idol") == []                # "with" is not a guest marker
    remix = Candidate("remix", "Luis Fonsi - Despacito (Audio) ft. Justin Bieber", "Luis Fonsi", 229, 0)
    plain = Candidate("plain", "Despacito", "Luis Fonsi", 228, 0)
    assert rank_candidates([remix, plain], "Despacito", ["Luis Fonsi"], 228)[0].url == "plain"
    assert rank_candidates([remix, plain], "Despacito", ["Luis Fonsi"], 228, asked="despacito justin bieber")[0].url == "remix"   # unless the user asked for it


def test_deezer_keeps_the_credited_artists_of_a_song():
    from apis.deezer import Deezer
    deezer = Deezer(client=object())
    answers = {"track/1": {"track_position": 1, "release_date": "2017-01-12", "album": {"id": 9},
                           "contributors": [{"name": "Luis Fonsi"}, {"name": "Daddy Yankee"}, {"name": "Daddy Yankee"}]},
               "album/9": {"genres": {"data": []}, "record_type": "album", "nb_tracks": 1, "artist": {"name": "Luis Fonsi"}}}
    deezer._get = lambda path, params=None: answers[path]
    info = SongInfo(title="Despacito", artist="Luis Fonsi")
    deezer._add_details(info, {"id": 1})
    assert info.contributors == ("Luis Fonsi", "Daddy Yankee")                         # no repeats
    assert SongInfo.from_dict(info.to_dict()).contributors == info.contributors      # survives the trip to the window and back


def test_a_real_guest_is_not_taken_for_a_remix_but_a_stranger_still_is():
    original = TextTrack(song("Despacito", "Luis Fonsi", "VIDA", contributors=("Luis Fonsi", "Daddy Yankee")))
    names = original.get_metadata()["artist"]
    assert names == ["Luis Fonsi", "Daddy Yankee"] and original.get_artist() == "Luis Fonsi" and original.get_filename() == "Luis Fonsi - Despacito"
    yankee = Candidate("y", "Luis Fonsi - Despacito ft. Daddy Yankee (Audio)", "Luis Fonsi", 228, 0)
    bieber = Candidate("b", "Luis Fonsi - Despacito (Audio) ft. Justin Bieber", "Luis Fonsi", 228, 0)
    assert score_candidate(yankee, "Despacito", names, 228)[0] > score_candidate(bieber, "Despacito", names, 228)[0] + 15
    assert rank_candidates([bieber, yankee], "Despacito", names, 228)[0].url == "y"


# --- remixes and other versions go after the song, never instead of it ------------------------------------------------

def titles(found):
    return [s.title for s in found]


def test_a_remix_listed_first_goes_below_the_song_and_nothing_is_dropped():
    deezer = Source([song("Mi Gente (Busta K Remix)", "J. Balvin", "Mi Gente"), song("Mi Gente", "J. Balvin", "Vibras"),
                     song("Mi Gente (Live)", "J. Balvin", "Concierto"), song("Mi Gente (Acoustic)", "J. Balvin", "Acustico")])
    found, _ = search_with(deezer=deezer).lookup("mi gente j balvin")
    assert titles(found) == ["Mi Gente", "Mi Gente (Busta K Remix)", "Mi Gente (Live)", "Mi Gente (Acoustic)"]


def test_the_cut_happens_after_the_sort_so_a_flood_of_remixes_cannot_push_the_song_out():
    remixes = [song(f"Mi Gente (Remix {n})", "J Balvin", f"R{n}") for n in range(8)]
    found, _ = search_with(deezer=Source(remixes + [song("Mi Gente", "J Balvin", "Original")])).lookup("mi gente j balvin", limit=3)
    assert titles(found)[0] == "Mi Gente" and len(found) == 3


def test_when_a_service_has_only_versions_the_next_one_is_asked_for_the_song_itself():
    deezer = Source([song("Mi Gente (Busta K Remix)", "J. Balvin", "Mi Gente")])
    itunes = Source([song("Mi Gente", "J Balvin & Willy William", "Vibras", source="itunes")])
    found, _ = search_with(deezer=deezer, itunes=itunes).lookup("mi gente j balvin")
    assert titles(found) == ["Mi Gente", "Mi Gente (Busta K Remix)"] and itunes.calls == 1


def test_the_next_service_is_not_asked_when_the_song_itself_is_already_there():
    itunes = Source([song()])
    found, _ = search_with(deezer=Source([song("Mi Gente", "J. Balvin", "Vibras")]), itunes=itunes).lookup("mi gente j balvin")
    assert itunes.calls == 0 and titles(found) == ["Mi Gente"]


def test_a_version_the_user_asked_for_is_not_an_alternate():
    from apis.text_search import is_alternate
    assert is_alternate(song("Despacito (Versión Salsa)", "Luis Fonsi"), "despacito luis fonsi")
    assert not is_alternate(song("Despacito (Versión Salsa)", "Luis Fonsi"), "despacito version salsa")
    assert not is_alternate(song("Mi Gente (Busta K Remix)", "J Balvin"), "mi gente remix")
    assert is_alternate(song("Song", "A", kind="live"), "song a") and not is_alternate(song("Song", "A", kind="album"), "song a")
    assert not is_alternate(song("Calentón", "Mora"), "calenton mora")
