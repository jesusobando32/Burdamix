"""Tests for downloading a whole album and browsing an artist: the cards, the services' album and artist calls, and the window's lists.
No real network: the services are simulated."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apis.catalog import Catalog, album_matches, artist_matches, tidy_albums
from apis.catalog_info import AlbumInfo, ArtistInfo
from apis.deezer import Deezer
from apis.itunes import ITunes
from apis.song_info import SongInfo
from apis.text_search import SongSearch
from apis.text_track import TextTrack
from exceptions import MetadataNetworkError, MetadataRefused


def album(title="MICRODOSIS", artist="Mora", tracks=15, kind="album", year="2022", source="deezer", ident="1"):
    return AlbumInfo(source=source, id=ident, title=title, artist=artist, track_total=tracks, kind=kind, year=year, cover_urls=("https://c/1.jpg",))


# --- when a card deserves to appear ----------------------------------------------------------------------------------

@pytest.mark.parametrize("query, wanted", [
    ("microdosis mora", True), ("microdosis", True), ("MICRODOSIS Mora álbum", True), ("mora microdosis completo", True),
    ("badtrip mora", False),            # a song of that album, not the album
    ("microdosis", True), ("mora", False), ("microdosis piano", False)])
def test_an_album_card_needs_the_album_to_be_named(query, wanted):
    assert album_matches(album(), query) is wanted


def test_singles_short_releases_and_alternate_versions_never_get_an_album_card():
    assert not album_matches(album("CALENTÓN", tracks=1, kind="single"), "calenton mora")
    assert not album_matches(album("Pocas", tracks=2, kind="ep"), "pocas mora")
    assert album_matches(album("Seis", tracks=6, kind="ep"), "seis mora")
    assert not album_matches(album("MICRODOSIS (Live)"), "microdosis mora")
    assert album_matches(album("MICRODOSIS (Live)"), "microdosis live mora")
    assert not album_matches(album("MICRODOSIS (Piano Version)"), "microdosis mora")
    assert album_matches(album("MICRODOSIS (Piano Version)"), "microdosis piano version mora")        # unless it was asked for


def test_an_artist_card_needs_the_whole_query_to_be_the_name():
    mora = ArtistInfo(source="deezer", id="1", name="Mora")
    assert artist_matches(mora, "mora") and artist_matches(mora, "MORA") and artist_matches(ArtistInfo(name="RMAND"), "remand")
    assert not artist_matches(mora, "badtrip mora") and not artist_matches(mora, "microdosis mora")


def test_the_discography_lists_each_album_once_newest_first_and_versions_last():
    found = tidy_albums([album("Uno", tracks=10, year="2020", ident="1"), album("Uno", tracks=12, year="2020", ident="2"),   # clean and explicit
                         album("Dos", tracks=9, year="2023", ident="3"), album("Dos (Live)", tracks=9, year="2024", ident="4"),
                         album("Tres", tracks=8, year="2021", ident="5")])
    assert [(a.title, a.track_total) for a in found] == [("Dos", 9), ("Tres", 8), ("Uno", 12), ("Dos (Live)", 9)]      # one Uno: the longer edition


# --- the services -------------------------------------------------------------------------------------------------------

def deezer_with(answers):
    deezer = Deezer(client=object())
    calls = []

    def get(path, params=None):
        calls.append((path, dict(params or {})))
        return answers(path, params or {})

    deezer._get = get
    return deezer, calls


def test_the_songs_of_a_deezer_album_share_the_albums_own_tags():
    detail = {"title": "MICRODOSIS", "artist": {"name": "Mora"}, "release_date": "2022-11-04", "nb_tracks": 3, "record_type": "album",
              "genres": {"data": [{"name": "Latin Music"}]}, "cover_xl": "https://c/xl.jpg"}
    tracks = [{"id": 10, "title": "badtrip :(", "track_position": 1, "disk_number": 1, "duration": 191, "artist": {"name": "Mora"}},
              {"id": 11, "title": "Intro", "track_position": 2, "disk_number": 1, "duration": 30, "artist": {"name": "Mora"}},
              {"id": 12, "title": "Intro", "track_position": 1, "disk_number": 2, "duration": 31, "artist": {"name": "Mora & Jhayco"}}]
    deezer, _ = deezer_with(lambda path, params: detail if path == "album/1" else {"data": tracks, "total": 3})
    songs = deezer.album_tracks(album())
    assert {(s.album, s.album_artist, s.year, s.genre, s.track_total, s.cover_urls) for s in songs} == {
        ("MICRODOSIS", "Mora", "2022", "Latin Music", 3, ("https://c/xl.jpg",))}
    assert [(s.disc_number, s.track_number) for s in songs] == [(1, 1), (1, 2), (2, 1)] and songs[2].artist == "Mora & Jhayco"
    ids = {TextTrack(s).resource_id for s in songs}
    assert len(ids) == 3                                       # two songs called "Intro" must not be taken for a repeat


def test_deezer_lists_are_read_page_after_page():
    pages = {0: {"data": [{"id": i, "title": f"A{i}", "record_type": "album", "release_date": "2020-01-01"} for i in range(1, 101)], "total": 130},
             100: {"data": [{"id": i, "title": f"A{i}", "record_type": "album", "release_date": "2021-01-01"} for i in range(101, 131)], "total": 130}}
    deezer, calls = deezer_with(lambda path, params: pages[params["index"]])
    found = deezer.artist_albums(ArtistInfo(source="deezer", id="9", name="Mora"))
    assert len(found) == 130 and [c[1]["index"] for c in calls] == [0, 100]


def test_deezer_homonymous_artists_are_ordered_by_followers():
    deezer, _ = deezer_with(lambda path, params: {"data": [{"id": 1, "name": "M.O.R.A.", "nb_fan": 30}, {"id": 2, "name": "Mora", "nb_fan": 244937}]})
    assert [a.name for a in deezer.artists("mora")] == ["Mora", "M.O.R.A."]


def test_popular_songs_get_their_missing_data_and_credited_artists_when_downloaded():
    answers = {"track/7": {"track_position": 4, "release_date": "2022-11-04", "album": {"id": 5},
                           "contributors": [{"name": "Mora"}, {"name": "Jhayco"}]},
               "album/5": {"genres": {"data": [{"name": "Latin"}]}, "record_type": "album", "nb_tracks": 15, "artist": {"name": "Mora"}}}
    deezer, _ = deezer_with(lambda path, params: answers[path])
    info = SongInfo(source="deezer", title="MEMORIAS", artist="Mora", track_id="7")
    track = TextTrack(info)
    assert track.get_metadata()["artist"] == ["Mora"]
    deezer.complete(info)
    track.refresh()
    assert (info.year, info.track_number, info.genre) == ("2022", 4, "Latin")
    assert track.get_metadata()["artist"] == ["Mora", "Jhayco"] and track.get_metadata()["track_num"] == 4       # the guest penalty knows the guest
    failing, _ = deezer_with(lambda path, params: (_ for _ in ()).throw(MetadataNetworkError("sin internet")))
    failing.complete(SongInfo(source="deezer", title="X", track_id="1"))                                           # best effort: never raises


def test_itunes_reads_lookups_by_what_each_item_is_not_by_position():
    class Client:
        def get_json(self, url, params=None):
            if params.get("entity") == "song":
                return {"results": [{"wrapperType": "collection", "collectionName": "MICRODOSIS", "artistName": "Mora", "primaryGenreName": "Latin"},
                                    {"wrapperType": "track", "trackName": "badtrip :(", "artistName": "Mora", "collectionName": "MICRODOSIS",
                                     "trackNumber": 1, "trackCount": 15, "discNumber": 1, "trackId": 55, "releaseDate": "2022-11-04T00:00:00Z"},
                                    {"wrapperType": "track", "trackName": "2010", "artistName": "Mora", "collectionName": "MICRODOSIS",
                                     "trackNumber": 2, "trackCount": 15, "discNumber": 1, "trackId": 56, "releaseDate": "2022-11-04T00:00:00Z"}]}
            return {"results": []}
    songs = ITunes(client=Client()).album_tracks(album(source="itunes", ident="9"))
    assert [(s.title, s.track_number, s.genre, s.album_artist, s.track_id) for s in songs] == [
        ("badtrip :(", 1, "Latin", "Mora", "55"), ("2010", 2, "Latin", "Mora", "56")]


def test_itunes_picks_the_artist_with_most_songs_and_names_it_by_its_shortest_name():
    class Client:
        def get_json(self, url, params=None):
            rows = [{"artistId": 1, "artistName": "Mora"}] * 3 + [{"artistId": 1, "artistName": "Mora & JHAYCO"}] + [{"artistId": 2, "artistName": "Mora"}]
            return {"results": rows}
    found = ITunes(client=Client()).artists("mora")
    assert [(a.id, a.name, a.popularity) for a in found] == [("1", "Mora", 4), ("2", "Mora", 1)]


# --- the catalog shares the session's memory of refusals -------------------------------------------------------------------

class Service:
    def __init__(self, **methods):
        self.calls = 0
        for name, value in methods.items():
            setattr(self, name, value)


def test_a_refusing_service_is_skipped_for_the_rest_of_the_session():
    def refuse(*args):
        raise MetadataRefused("Deezer negó el acceso (403).")
    deezer, itunes = Service(albums=refuse), Service(albums=lambda *a: [album(source="itunes")])
    catalog = Catalog(SongSearch([("deezer", deezer), ("itunes", itunes)]))
    assert catalog._ask("albums", "x")[0][0].source == "itunes"
    assert "deezer" in catalog.search.blocked()
    with pytest.raises(MetadataRefused):
        catalog.album_tracks(album(source="deezer"))        # an album of the refusing service cannot be opened: said, not hung


def test_cards_ask_for_the_artist_only_when_a_song_found_is_by_someone_with_that_name():
    asked = []
    service = Service(albums=lambda q, n: [album()], artists=lambda q, n: asked.append(q) or [ArtistInfo(source="deezer", id="1", name="Mora")])
    catalog = Catalog(SongSearch([("deezer", service)]))
    albums, artist, _ = catalog.cards("badtrip mora", [SongInfo(title="badtrip :(", artist="Mora")])
    assert artist is None and albums == [] and asked == []
    albums, artist, _ = catalog.cards("mora", [SongInfo(title="badtrip :(", artist="Mora")])
    assert artist.name == "Mora" and asked == ["mora"]


# --- the window: every list has its own songs and folder ---------------------------------------------------------------------

def window(tmp_path, monkeypatch):
    import const
    import downloader
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(downloader, "DOWNLOADS_DIR", str(tmp_path / "dl"))
    from gui.backend import Api
    api = Api()
    api._settings["downloads_dir"] = str(tmp_path / "dl")
    api._cover_tagger = type("T", (), {"preview_cover": lambda self, info: ("data:image/jpeg;base64,AA", None)})()
    return api


def songs_of(prefix, n, **extra):
    return [SongInfo(source="deezer", title=f"{prefix}{i}", artist="Mora", album="MICRODOSIS", album_artist="Mora", track_number=i + 1,
                     track_total=n, duration=200.0 + i, track_id=f"{prefix}{i}", **extra) for i in range(n)]


class FakeCatalog:
    def __init__(self):
        self.mora = ArtistInfo(source="deezer", id="1", name="Mora")
        self.record = album()

    def cards(self, query, songs):
        return [self.record], self.mora, []

    def album_tracks(self, found):
        return songs_of("pista", 3) + [SongInfo(source="deezer", title="Intro", artist="Mora", album="MICRODOSIS", duration=20.0, track_number=4, track_id="i")]

    def artist_view(self, found):
        return songs_of("popular", 3), [album("Uno", ident="2"), album("Sencillo", kind="single", tracks=1, ident="3")]

    def complete(self, info):
        return info


def test_opening_an_album_gives_its_numbered_songs_in_its_own_folder_and_skips_interludes(tmp_path, monkeypatch):
    api = window(tmp_path, monkeypatch)
    api._catalog = FakeCatalog()
    monkeypatch.setattr("gui.backend.search_songs", lambda text, limit: (songs_of("s", 2), []))
    found = api.preview("microdosis mora")
    assert [c["type"] for c in found["cards"]] == ["artist", "album"] and len(found["items"]) == 2
    opened = api.open_card(next(c["key"] for c in found["cards"] if c["type"] == "album"))
    assert opened["kind"] == "album" and opened["back"] and opened["subtitle"] == "Mora · 2022"
    assert [i["number"] for i in opened["items"]] == [1, 2, 3] and opened["interludes"] == ["Intro"]     # the 20-second "Intro" is left out
    assert opened["folder"].endswith(os.path.join("albums", "Mora - MICRODOSIS") + os.sep) and opened["cover"] == "data:image/jpeg;base64,AA"


def test_download_goes_to_the_list_the_user_is_looking_at_even_after_going_back(tmp_path, monkeypatch):
    api = window(tmp_path, monkeypatch)
    api._catalog = FakeCatalog()
    monkeypatch.setattr("gui.backend.search_songs", lambda text, limit: (songs_of("s", 2), []))
    started = []
    monkeypatch.setattr(api, "_run_download", lambda pending, chosen: started.append((pending["output_path"], [t.get_title() for t in chosen])))
    search = api.preview("mora")
    artist = api.open_card(next(c["key"] for c in search["cards"] if c["type"] == "artist"))
    album_card = artist["albums"][0]["key"]
    opened = api.open_card(album_card)                                      # artist -> album: the album is now the latest list
    assert opened["view"] not in (artist["view"], search["view"])

    api.start_download([artist["items"][0]["key"]], artist["view"])         # ...but the window is back on the artist's popular songs
    api._busy = False
    api.start_download([search["items"][0]["key"]], search["view"])
    api._busy = False
    api.start_download([opened["items"][0]["key"]], opened["view"])
    import time
    time.sleep(0.2)
    assert [(os.path.basename(os.path.dirname(p)), t) for p, t in started] == [
        ("tracks", ["popular0"]), ("tracks", ["s0"]), ("Mora - Uno", ["pista0"])]
    api._busy = False
    assert api.start_download([artist["items"][0]["key"]], "v999")["ok"] is False        # an unknown list is refused, not guessed


def test_the_artist_view_has_popular_songs_unmarked_and_the_discography(tmp_path, monkeypatch):
    api = window(tmp_path, monkeypatch)
    api._catalog = FakeCatalog()
    monkeypatch.setattr("gui.backend.search_songs", lambda text, limit: (songs_of("s", 1), []))
    search = api.preview("mora")
    artist = api.open_card(next(c["key"] for c in search["cards"] if c["type"] == "artist"))
    assert artist["kind"] == "artist" and artist["preselect"] == [] and len(artist["items"]) == 3                   # nothing is marked by itself
    assert all(i["cover"] is None for i in artist["items"])                                                         # pictures come afterwards
    assert [(a["title"], a["kind"]) for a in artist["albums"]] == [("Uno", "album"), ("Sencillo", "single")]
    assert api.item_cover(artist["view"], artist["items"][0]["key"]) == "data:image/jpeg;base64,AA"                  # the picture of one song
    assert api.item_cover(artist["view"], artist["albums"][0]["key"]) == "data:image/jpeg;base64,AA"                 # and of an album card
    assert api.item_cover(artist["view"], "nope") is None


def test_cards_cannot_be_opened_during_a_download_or_when_unknown(tmp_path, monkeypatch):
    api = window(tmp_path, monkeypatch)
    assert "ya no está disponible" in api.open_card("album:deezer:404")["error"]
    api._busy = True
    assert "descarga en curso" in api.open_card("album:deezer:1")["error"]


def test_an_album_search_with_no_matching_songs_still_shows_its_card(tmp_path, monkeypatch):
    api = window(tmp_path, monkeypatch)
    api._catalog = FakeCatalog()
    monkeypatch.setattr("gui.backend.search_songs", lambda text, limit: ([], []))
    result = api.preview("microdosis mora")
    assert "error" not in result and result["items"] == [] and len(result["cards"]) == 2


def test_a_failing_catalog_never_breaks_the_song_search(tmp_path, monkeypatch):
    api = window(tmp_path, monkeypatch)
    api._catalog = type("Broken", (), {"cards": lambda self, q, s: (_ for _ in ()).throw(RuntimeError("changed"))})()
    monkeypatch.setattr("gui.backend.search_songs", lambda text, limit: (songs_of("s", 2), []))
    result = api.preview("mora")
    assert result["cards"] == [] and len(result["items"]) == 2
