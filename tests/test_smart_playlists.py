"""Smart playlists: rules that pick songs out of the library and are worked out again every time they are looked at. They only point at
songs by what the songs are (artist, title, dates, listens), never at files, so nothing is copied and nothing goes stale."""
import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import smart_playlists as sp  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400


def song(i, artist="Mora", title=None, album="Cabernet", duration=200, added_days=10, kind="album"):
    return {"id": f"s{i}", "artist": artist, "title": title or f"Canción {i}", "album": album, "duration": duration, "added": NOW - added_days * DAY, "kind": kind}


def run(defn, items, liked=(), counts=None, seed=1):
    return sp.evaluate(sp.clean(defn), items, set(liked), counts or {}, NOW, rng=random.Random(seed))


def rule(field, op, value):
    return {"field": field, "op": op, "value": value}


def named(match="all", rules=(), sort="recent", limit=0):
    return {"name": "Prueba", "match": match, "rules": list(rules), "sort": sort, "limit": limit}


# --- the rules --------------------------------------------------------------------------------------------------------

def test_text_rules_ignore_case_and_accents():
    items = [song(1, "Féid"), song(2, "Mora"), song(3, "Fe id")]
    assert run(named(rules=[rule("artist", "contains", "FEID")]), items) == ["s1"]
    assert run(named(rules=[rule("artist", "is", "feid")]), items) == ["s1"]
    assert sorted(run(named(rules=[rule("artist", "not_contains", "feid")]), items)) == ["s2", "s3"]


def test_all_needs_every_rule_and_any_needs_one():
    items = [song(1, "Mora", album="A"), song(2, "Mora", album="B"), song(3, "Feid", album="A")]
    both = [rule("artist", "is", "mora"), rule("album", "is", "a")]
    assert run(named("all", both), items) == ["s1"]
    assert sorted(run(named("any", both), items)) == ["s1", "s2", "s3"]


def test_the_heart_rule_follows_the_liked_ids():
    items = [song(1), song(2)]
    assert run(named(rules=[rule("liked", "is", True)]), items, liked={"s2"}) == ["s2"]
    assert run(named(rules=[rule("liked", "is", False)]), items, liked={"s2"}) == ["s1"]


def test_length_rule_is_in_minutes():
    items = [song(1, duration=120), song(2, duration=300)]
    assert run(named(rules=[rule("duration_min", "gt", 4)]), items) == ["s2"]
    assert run(named(rules=[rule("duration_min", "lt", 4)]), items) == ["s1"]


def test_added_rule_counts_days_since_the_file_arrived():
    items = [song(1, added_days=3), song(2, added_days=40)]
    assert run(named(rules=[rule("added_days", "lt", 30)]), items) == ["s1"]
    assert run(named(rules=[rule("added_days", "gt", 30)]), items) == ["s2"]


def test_listens_come_from_the_statistics_and_a_song_never_heard_has_zero():
    items = [song(1, "Mora", "Uno"), song(2, "Mora", "Dos")]
    counts = {("mora", "uno"): (5, NOW - DAY)}
    assert run(named(rules=[rule("plays", "gt", 3)]), items, counts=counts) == ["s1"]
    assert run(named(rules=[rule("plays", "eq", 0)]), items, counts=counts) == ["s2"]


def test_last_heard_rule_treats_never_heard_as_forgotten():
    items = [song(1, "Mora", "Uno"), song(2, "Mora", "Dos"), song(3, "Mora", "Tres")]
    counts = {("mora", "uno"): (1, NOW - 2 * DAY), ("mora", "dos"): (1, NOW - 200 * DAY)}
    assert sorted(run(named(rules=[rule("last_played_days", "gt", 90)]), items, counts=counts)) == ["s2", "s3"]
    assert run(named(rules=[rule("last_played_days", "lt", 7)]), items, counts=counts) == ["s1"]


def test_without_rules_every_song_is_picked():
    assert len(run(named(rules=[]), [song(1), song(2)])) == 2


# --- order, limit, copies --------------------------------------------------------------------------------------------

def test_orders():
    items = [song(1, title="B", added_days=5), song(2, title="A", added_days=1), song(3, title="C", added_days=9)]
    assert run(named(sort="recent"), items) == ["s2", "s1", "s3"]
    assert run(named(sort="oldest"), items) == ["s3", "s1", "s2"]
    assert run(named(sort="title"), items) == ["s2", "s1", "s3"]
    counts = {("mora", "c"): (9, NOW), ("mora", "b"): (2, NOW)}
    assert run(named(sort="plays"), items, counts=counts)[:2] == ["s3", "s1"]


def test_random_order_is_a_shuffle_of_the_same_songs():
    items = [song(i) for i in range(20)]
    out = run(named(sort="random"), items)
    assert sorted(out) == sorted(i["id"] for i in items) and out != [i["id"] for i in items]


def test_the_limit_cuts_after_the_order():
    items = [song(i, added_days=i) for i in range(10)]
    assert run(named(sort="recent", limit=3), items) == ["s0", "s1", "s2"]


def test_the_same_song_kept_as_two_files_appears_once():
    items = [song(1, "Mora", "Uno", kind="liked"), song(2, "Mora", "Uno", kind="album"), song(3, "", "", kind="other"), song(4, "", "", kind="other")]
    out = run(named(sort="title"), items)
    assert "s2" in out and "s1" not in out            # the album copy is the one kept
    assert "s3" in out and "s4" in out                # songs without tags are only themselves


# --- what the user may write ------------------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    {"name": "", "match": "all", "rules": [], "sort": "recent", "limit": 0},
    {"name": "x" * 81, "match": "all", "rules": [], "sort": "recent", "limit": 0},
    {"name": "x", "match": "nope", "rules": [], "sort": "recent", "limit": 0},
    {"name": "x", "match": "all", "rules": [], "sort": "nope", "limit": 0},
    {"name": "x", "match": "all", "rules": [], "sort": "recent", "limit": -1},
    {"name": "x", "match": "all", "rules": [], "sort": "recent", "limit": 99999},
    {"name": "x", "match": "all", "rules": [rule("color", "is", "rojo")], "sort": "recent", "limit": 0},
    {"name": "x", "match": "all", "rules": [rule("artist", "gt", "a")], "sort": "recent", "limit": 0},
    {"name": "x", "match": "all", "rules": [rule("plays", "gt", "muchas")], "sort": "recent", "limit": 0},
    {"name": "x", "match": "all", "rules": [rule("plays", "gt", float("nan"))], "sort": "recent", "limit": 0},
    {"name": "x", "match": "all", "rules": [rule("liked", "is", "si")], "sort": "recent", "limit": 0},
    {"name": "x", "match": "all", "rules": [rule("artist", "is", "")] , "sort": "recent", "limit": 0},
    {"name": "x", "match": "all", "rules": [rule("artist", "is", "a")] * 13, "sort": "recent", "limit": 0},
    "no es un diccionario",
])
def test_nonsense_definitions_are_refused(bad):
    with pytest.raises(sp.SmartError):
        sp.clean(bad)


def test_a_clean_definition_has_only_known_keys_and_a_trimmed_name():
    out = sp.clean({"name": "  Mi lista  ", "match": "any", "rules": [rule("plays", "gt", "3")], "sort": "plays", "limit": 20, "extra": 1})
    assert out == {"name": "Mi lista", "match": "any", "rules": [rule("plays", "gt", 3.0)], "sort": "plays", "limit": 20}


# --- the three that come ready ------------------------------------------------------------------------------------------

def test_the_ready_made_ones_are_always_there_and_work():
    assert [b["name"] for b in sp.BUILTIN] == ["Recién añadidas", "Más escuchadas", "Olvidadas"]
    items = [song(1, "Mora", "Nueva", added_days=2), song(2, "Mora", "Vieja", added_days=300), song(3, "Mora", "Oída", added_days=100)]
    counts = {("mora", "oida"): (8, NOW - DAY)}
    by_name = {b["name"]: sp.evaluate(sp.clean(b), items, set(), counts, NOW, rng=random.Random(1)) for b in sp.BUILTIN}
    assert by_name["Recién añadidas"] == ["s1"]
    assert by_name["Más escuchadas"] == ["s3"]
    assert by_name["Olvidadas"] == ["s2"]


# --- the store -------------------------------------------------------------------------------------------------------

@pytest.fixture
def store(tmp_path):
    return sp.SmartStore(str(tmp_path / "smart.json"))


def test_the_store_creates_updates_deletes_and_survives_a_restart(store, tmp_path):
    made = store.save(named(rules=[rule("artist", "is", "mora")]))
    assert store.save({**named(), "name": "Otra"}, made) == made
    assert [d["name"] for d in sp.SmartStore(str(tmp_path / "smart.json")).all()] == ["Otra"]
    assert store.delete(made) is True and store.all() == [] and store.delete(made) is False


def test_saving_an_unknown_id_is_refused_and_a_bad_file_is_kept_aside_not_lost(store, tmp_path):
    with pytest.raises(sp.SmartError):
        store.save(named(), "no-existe")
    path = tmp_path / "smart.json"
    path.write_text("{roto", encoding="utf-8")
    fresh = sp.SmartStore(str(path))
    assert fresh.all() == []
    fresh.save(named())
    assert (tmp_path / "smart.json.bad").read_text(encoding="utf-8") == "{roto"
    assert json.loads(path.read_text(encoding="utf-8"))["lists"]


# --- through the window's API ---------------------------------------------------------------------------------------

def test_the_api_returns_ready_made_and_own_smart_playlists_with_the_ids_of_their_songs(tmp_path, monkeypatch):
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
    track = api.library_list()["tracks"][0]
    got = api.collections_get()["smart"]
    assert [s["name"] for s in got][:3] == ["Recién añadidas", "Más escuchadas", "Olvidadas"] and all(s["builtin"] for s in got)
    saved = api.smart_save(named(rules=[rule("artist", "is", "feid")]), None)
    assert saved["ok"]
    mine = [s for s in api.collections_get()["smart"] if not s["builtin"]]
    assert len(mine) == 1 and mine[0]["ids"] == [track["id"]] and mine[0]["rules"][0]["field"] == "artist"
    assert api.smart_save({"name": ""}, None)["ok"] is False
    assert api.smart_delete(saved["id"]) == {"ok": True} and api.smart_delete("no-existe")["ok"] is False
    assert api.smart_delete("recent")["ok"] is False        # the ready-made ones cannot be deleted
