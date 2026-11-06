"""Lyrics: the LRC text is read into timed lines, the answer of LRCLIB is chosen with care, and what was found (or not found) is kept
on disk so the service is not asked twice. No real network."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import lyrics  # noqa: E402
from exceptions import MetadataNetworkError, MetadataNotFound  # noqa: E402


# --- reading LRC ----------------------------------------------------------------------------------------------------

def test_lrc_lines_are_read_with_their_second():
    assert lyrics.parse_lrc("[00:12.50] Hola\n[01:02.00]Adiós") == [[12.5, "Hola"], [62.0, "Adiós"]]


def test_a_line_with_several_stamps_is_repeated_and_the_lines_come_sorted():
    assert lyrics.parse_lrc("[00:30.00][00:10.00]Coro\n[00:20.00]Verso") == [[10.0, "Coro"], [20.0, "Verso"], [30.0, "Coro"]]


def test_tags_comments_and_garbage_are_ignored_but_the_offset_is_applied():
    text = "[ar:Alguien]\n[ti:Algo]\n[offset:+500]\nsin tiempo\n[00:10.00]Línea\n[mal:10]x"
    assert lyrics.parse_lrc(text) == [[9.5, "Línea"]]


def test_two_digit_and_three_digit_fractions_and_a_stamp_without_fraction():
    assert lyrics.parse_lrc("[00:01.5]a\n[00:02.250]b\n[00:03]c") == [[1.5, "a"], [2.25, "b"], [3.0, "c"]]


def test_empty_lines_are_kept_as_pauses_but_not_at_the_start():
    assert lyrics.parse_lrc("[00:01.00]\n[00:05.00]Uno\n[00:09.00]") == [[5.0, "Uno"], [9.0, ""]]


# --- asking the service ---------------------------------------------------------------------------------------------

class FakeClient:
    def __init__(self, get=None, search=None, error=None):
        self.answers = {"/api/get": get, "/api/search": search}
        self.error, self.calls = error, []

    def get_json(self, url, params=None):
        self.calls.append((url.rsplit("lrclib.net", 1)[-1], params))
        if self.error:
            raise self.error
        answer = self.answers[self.calls[-1][0]]
        if callable(answer):
            answer = answer(params)
        if answer is None:
            raise MetadataNotFound("x")
        return answer


@pytest.fixture
def cache_file(tmp_path):
    return str(tmp_path / "lyrics.json")


def make(cache_file, client, now=1_000_000):
    return lyrics.Lyrics(cache_file, client=client, clock=lambda: now)


SYNCED = {"syncedLyrics": "[00:05.00]Hola", "plainLyrics": "Hola", "duration": 200}


def test_an_exact_match_returns_the_synced_lines(cache_file):
    found = make(cache_file, FakeClient(get=SYNCED)).get("Feid", "Normal", "Feliz Cumpleaños Ferxxo", 200)
    assert found == {"ok": True, "synced": [[5.0, "Hola"]], "plain": "Hola", "manual": False, "offset": 0}


def test_without_timed_lyrics_only_the_plain_text_is_returned(cache_file):
    found = make(cache_file, FakeClient(get={"syncedLyrics": None, "plainLyrics": "Solo texto"})).get("A", "B", "", 100)
    assert found["ok"] and found["synced"] == [] and found["plain"] == "Solo texto"


def test_if_the_exact_lookup_fails_the_search_picks_the_one_with_timed_lines_and_the_closest_length(cache_file):
    near = {"syncedLyrics": "[00:01.00]cerca", "plainLyrics": "cerca", "duration": 201}
    far = {"syncedLyrics": "[00:01.00]lejos", "plainLyrics": "lejos", "duration": 260}
    plain_only = {"syncedLyrics": None, "plainLyrics": "solo texto", "duration": 200}
    found = make(cache_file, FakeClient(get=None, search=[far, plain_only, near])).get("A", "B", "", 200)
    assert found["synced"] == [[1.0, "cerca"]]


def test_a_search_result_of_a_very_different_length_is_not_taken(cache_file):
    other = {"syncedLyrics": "[00:01.00]otra", "plainLyrics": "otra", "duration": 400}
    found = make(cache_file, FakeClient(get=None, search=[other])).get("A", "B", "", 200)
    assert found["ok"] is False and found["none"] is True


def test_nothing_found_is_remembered_for_a_week_and_then_asked_again(cache_file):
    client = FakeClient(get=None, search=[])
    make(cache_file, client).get("A", "B", "", 100)
    asked = len(client.calls)
    make(cache_file, client, now=1_000_000 + 3600).get("A", "B", "", 100)
    assert len(client.calls) == asked
    make(cache_file, client, now=1_000_000 + 8 * 86400).get("A", "B", "", 100)
    assert len(client.calls) > asked


def test_found_lyrics_are_kept_on_disk_and_survive_a_restart(cache_file):
    make(cache_file, FakeClient(get=SYNCED)).get("Feid", "Normal", "", 200)
    again = make(cache_file, FakeClient(error=MetadataNetworkError("sin red"))).get("feid", "NORMAL", "", 200)
    assert again["ok"] and again["synced"] == [[5.0, "Hola"]]


def test_a_network_failure_is_reported_but_not_remembered(cache_file):
    result = make(cache_file, FakeClient(error=MetadataNetworkError("No pude conectar"))).get("A", "B", "", 100)
    assert result["ok"] is False and "none" not in result and "conectar" in result["error"]
    assert not os.path.exists(cache_file) or "a|b" not in open(cache_file, encoding="utf-8").read()


def test_a_song_without_artist_or_title_is_not_looked_up(cache_file):
    client = FakeClient(get=SYNCED)
    assert make(cache_file, client).get("", "Titulo", "", 100)["ok"] is False
    assert client.calls == []


# --- lyrics the user pastes -----------------------------------------------------------------------------------------

def test_lyrics_pasted_by_the_user_win_over_the_service_and_can_carry_times(cache_file):
    store = make(cache_file, FakeClient(get=SYNCED))
    store.set_manual("Feid", "Normal", "[00:03.00]Mi letra\n[00:06.00]Otra")
    found = store.get("Feid", "Normal", "", 200)
    assert found["manual"] is True and found["synced"] == [[3.0, "Mi letra"], [6.0, "Otra"]]


def test_pasted_text_without_times_is_shown_as_plain_and_an_empty_paste_removes_it(cache_file):
    store = make(cache_file, FakeClient(get=None, search=[]))
    store.set_manual("A", "B", "Línea uno\nLínea dos")
    assert store.get("A", "B", "", 10)["plain"] == "Línea uno\nLínea dos"
    store.set_manual("A", "B", "   ")
    assert store.get("A", "B", "", 10)["ok"] is False


def test_a_damaged_cache_file_is_ignored_not_fatal(cache_file):
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write("{no es json")
    assert make(cache_file, FakeClient(get=SYNCED)).get("A", "B", "", 200)["ok"]
    json.load(open(cache_file, encoding="utf-8"))   # and what is written afterwards is valid


# --- through the window's API ---------------------------------------------------------------------------------------

def test_the_api_looks_up_a_library_song_by_its_id_and_keeps_pasted_lyrics(tmp_path, monkeypatch):
    import const
    import library
    from gui import backend
    from tagwriter import TagInfo
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path / "datos"))
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "Feid - Normal.mp3").write_bytes(b"x")
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda path: TagInfo(title="Normal", artist="Feid", album="FERXXO", duration=200))
    api = backend.Api()
    monkeypatch.setattr(api, "_downloads_dir", lambda: str(songs))
    api._lyrics.client = FakeClient(get=SYNCED)
    track = api.library_list()["tracks"][0]
    assert api.lyrics_get(track["id"])["synced"] == [[5.0, "Hola"]]
    assert api.lyrics_save(track["id"], "[00:01.00]Mía")["manual"] is True
    assert api.lyrics_get("no-existe")["ok"] is False
    assert api.lyrics_save(track["id"], 5)["ok"] is False


# --- more ways to find it ---------------------------------------------------------------------------------------------

def only_for(artist, title, entry):
    """A search that answers only when asked for exactly this artist and title."""
    return lambda params: [entry] if (params.get("artist_name"), params.get("track_name")) == (artist, title) else []


def test_a_song_with_several_artists_is_also_searched_by_the_first_one(cache_file):
    client = FakeClient(get=None, search=only_for("El Chombo", "El Gato Volador", {"syncedLyrics": "[00:01.00]Toasty", "plainLyrics": "Toasty", "duration": 114}))
    found = make(cache_file, client).get("El Chombo, Cracker Jack & Jr Crack", "El Gato Volador", "", 114)
    assert found["ok"] and found["synced"] == [[1.0, "Toasty"]]


def test_the_whole_name_is_tried_before_the_pieces(cache_file):
    duo = {"syncedLyrics": "[00:01.00]dúo", "plainLyrics": "dúo", "duration": 200}
    client = FakeClient(get=None, search=lambda params: [duo] if params.get("artist_name") == "Chino & Nacho" else [])
    assert make(cache_file, client).get("Chino & Nacho", "Mi Niña Bonita", "", 200)["synced"] == [[1.0, "dúo"]]
    assert [c[1].get("artist_name") for c in client.calls if c[0] == "/api/search"][0] == "Chino & Nacho"


@pytest.mark.parametrize("artist,expected", [
    ("SAIKO, ULI", "SAIKO"), ("Mora feat. Feid", "Mora"), ("Mora ft. Feid", "Mora"), ("Mora; Feid", "Mora"), ("Mora x Feid", "Mora"), ("Mora & Feid", "Mora"),
])
def test_the_first_artist_is_taken_from_the_usual_ways_of_joining_names(cache_file, artist, expected):
    client = FakeClient(get=None, search=only_for(expected, "Tema", {"syncedLyrics": "[00:01.00]x", "plainLyrics": "x", "duration": 100}))
    assert make(cache_file, client).get(artist, "Tema", "", 100)["ok"]


@pytest.mark.parametrize("title", ["Tema (feat. Feid)", "Tema [with Feid]", "Tema - Remastered 2011", "Tema - Single Version", "Tema (Remastered)"])
def test_credits_and_remaster_labels_are_taken_off_the_title(cache_file, title):
    client = FakeClient(get=None, search=only_for("Mora", "Tema", {"syncedLyrics": "[00:01.00]x", "plainLyrics": "x", "duration": 100}))
    assert make(cache_file, client).get("Mora", title, "", 100)["ok"]


def test_a_remix_or_a_live_version_keeps_its_label_because_it_is_another_recording(cache_file):
    client = FakeClient(get=None, search=only_for("Mora", "Tema", {"syncedLyrics": "[00:01.00]x", "plainLyrics": "x", "duration": 100}))
    assert make(cache_file, client).get("Mora", "Tema (Remix)", "", 100)["ok"] is False


def test_a_miss_costs_a_few_requests_not_dozens(cache_file):
    client = FakeClient(get=None, search=[])
    make(cache_file, client).get("A, B, C & D feat. E", "Título (feat. F) - Remastered 2011", "", 100)
    assert len(client.calls) <= 8


# --- the offset of each song -----------------------------------------------------------------------------------------

def test_an_offset_is_kept_per_song_and_comes_with_the_lyrics(cache_file):
    store = make(cache_file, FakeClient(get=SYNCED))
    assert store.get("Feid", "Normal", "", 200)["offset"] == 0
    assert store.set_offset("Feid", "Normal", 1.25) == 1.25
    assert make(cache_file, FakeClient(error=MetadataNetworkError("x"))).get("FEID", "normal", "", 200)["offset"] == 1.25


def test_the_offset_is_limited_rounded_and_zero_removes_it(cache_file):
    store = make(cache_file, FakeClient(get=SYNCED))
    assert store.set_offset("A", "B", 999) == 30 and store.set_offset("A", "B", -999) == -30
    assert store.set_offset("A", "B", 0.3) == 0.25
    assert store.set_offset("A", "B", 0) == 0 and "|" not in json.dumps(json.load(open(cache_file, encoding="utf-8")).get("_offsets", {}))


def test_nonsense_offsets_and_songs_without_names_are_refused(cache_file):
    store = make(cache_file, FakeClient(get=SYNCED))
    assert store.set_offset("A", "B", "mucho") is None and store.set_offset("A", "B", float("nan")) is None and store.set_offset("", "B", 1) is None


def test_an_offset_survives_new_lyrics_being_pasted_and_missing_lyrics(cache_file):
    store = make(cache_file, FakeClient(get=None, search=[]))
    store.set_offset("A", "B", 2)
    assert store.get("A", "B", "", 10)["offset"] == 2          # the miss answer also carries it, so the buttons keep their value
    store.set_manual("A", "B", "[00:01.00]hola")
    assert store.get("A", "B", "", 10)["offset"] == 2


def test_the_api_keeps_an_offset_per_song(tmp_path, monkeypatch):
    import const
    import library
    from gui import backend
    from tagwriter import TagInfo
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path / "datos"))
    songs = tmp_path / "songs"
    songs.mkdir()
    (songs / "a.mp3").write_bytes(b"x")
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda path: TagInfo(title="Normal", artist="Feid", album="FERXXO", duration=200))
    api = backend.Api()
    monkeypatch.setattr(api, "_downloads_dir", lambda: str(songs))
    api._lyrics.client = FakeClient(get=SYNCED)
    track = api.library_list()["tracks"][0]
    assert api.lyrics_offset(track["id"], 1.3) == {"ok": True, "offset": 1.25}
    assert api.lyrics_get(track["id"])["offset"] == 1.25
    assert api.lyrics_offset(track["id"], "mucho")["ok"] is False and api.lyrics_offset("no-existe", 1)["ok"] is False
