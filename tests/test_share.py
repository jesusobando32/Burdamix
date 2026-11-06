"""Sharing a playlist between two people with the app: a code (text that carries the whole list), a card (a picture with the code
hidden inside and a QR drawn on it) and a .m3u8 for other players. Nothing goes through a server. No real network."""
import io
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import share  # noqa: E402

SONGS = [["Feid", "Normal"], ["Mora", "Memorias"], ["Chino & Nacho", "Mi Niña Bonita"], ["Beyoncé", "Halo"]]


def png(color):
    out = io.BytesIO()
    Image.new("RGB", (300, 300), color).save(out, "PNG")
    return out.getvalue()


# --- the code -------------------------------------------------------------------------------------------------------------------

def test_a_code_round_trips_with_accents_and_symbols():
    code = share.encode("Fiesta ñandú ★", SONGS, by="Yisus")
    assert code.startswith("BURDAMIX1:") and "\n" not in code and " " not in code
    assert share.decode(code) == {"name": "Fiesta ñandú ★", "by": "Yisus", "songs": SONGS}


def test_a_pasted_code_may_carry_line_breaks_spaces_and_text_around_it():
    code = share.encode("Lista", SONGS)
    wrapped = "¡Mira mi lista! " + code[:30] + "\n" + code[30:60] + "  \r\n" + code[60:] + " ¿La oyes?"
    assert share.decode(wrapped)["songs"] == SONGS


def test_a_code_stays_small_enough_for_a_chat():
    songs = [[f"Artista número {i}", f"Una canción con título largo {i}"] for i in range(100)]
    assert len(share.encode("Cien", songs)) < 4500


@pytest.mark.parametrize("bad", ["", "hola", "BURDAMIX1:", "BURDAMIX1:%%%%", "BURDAMIX2:eJwDAAAAAAE", "BURDAMIX1:eJwDAAAAAAE"])
def test_garbage_is_refused_with_a_message(bad):
    with pytest.raises(share.ShareError) as error:
        share.decode(bad)
    assert str(error.value)


def test_a_truncated_code_is_refused_not_half_read():
    code = share.encode("Lista", SONGS)
    with pytest.raises(share.ShareError):
        share.decode(code[:-12])


def test_a_decompression_bomb_is_refused():
    import base64
    import json
    import zlib
    raw = zlib.compress(json.dumps({"v": 1, "name": "x", "songs": [["a" * 100, "b"]] * 1}).encode() + b" " * 30_000_000, 9)
    code = "BURDAMIX1:" + base64.urlsafe_b64encode(raw).decode().rstrip("=")
    with pytest.raises(share.ShareError):
        share.decode(code)


@pytest.mark.parametrize("payload", [
    {"v": 1, "name": "x", "songs": "no"},
    {"v": 1, "name": "x", "songs": [["a"]]},
    {"v": 1, "name": "x", "songs": [["a", 5]]},
    {"v": 1, "name": "", "songs": [["a", "b"]]},
    {"v": 1, "name": "x", "songs": []},
    {"v": 1, "name": "x", "songs": [["a", "b"]] * (share.MAX_SONGS + 1)},
    {"v": 2, "name": "x", "songs": [["a", "b"]]},
    [1, 2, 3],
])
def test_a_well_compressed_but_wrong_payload_is_refused(payload):
    import base64
    import json
    import zlib
    code = "BURDAMIX1:" + base64.urlsafe_b64encode(zlib.compress(json.dumps(payload).encode())).decode().rstrip("=")
    with pytest.raises(share.ShareError):
        share.decode(code)


def test_encoding_trims_and_limits_what_goes_in():
    code = share.encode("  " + "N" * 200 + "  ", [["  A  ", "  T  "], ["", "sin artista"], ["sin título", ""], ["x" * 500, "y" * 500]], by="B" * 100)
    got = share.decode(code)
    assert len(got["name"]) == 80 and len(got["by"]) == 40
    assert got["songs"][0] == ["A", "T"] and len(got["songs"]) == 2 and len(got["songs"][1][0]) == 200


def test_encoding_without_a_name_or_without_songs_is_refused():
    with pytest.raises(share.ShareError):
        share.encode("", SONGS)
    with pytest.raises(share.ShareError):
        share.encode("Vacía", [["", ""]])


# --- matching with the library --------------------------------------------------------------------------------------------------

def item(i, artist, title, kind="album"):
    return {"id": f"s{i}", "artist": artist, "title": title, "kind": kind}


def test_songs_are_matched_by_artist_and_title_ignoring_case_and_accents_and_the_rest_are_missing():
    library = [item(1, "FEID", "normal"), item(2, "Beyonce", "Halo"), item(3, "Otro", "Otra")]
    ids, missing = share.match(SONGS, library)
    assert ids == ["s1", "s2"] and missing == [["Mora", "Memorias"], ["Chino & Nacho", "Mi Niña Bonita"]]


def test_a_song_kept_as_two_files_matches_the_album_copy_once():
    library = [item(1, "Feid", "Normal", "liked"), item(2, "Feid", "Normal", "album")]
    ids, missing = share.match([["Feid", "Normal"], ["feid", "NORMAL"]], library)
    assert ids == ["s2"] and missing == []


# --- the card ---------------------------------------------------------------------------------------------------------------------

def module_grid(img, geometry, size):
    x0, y0, scale = geometry
    px = img.convert("L").load()
    return [[px[x0 + (c + .5) * scale, y0 + (r + .5) * scale] < 128 for c in range(size)] for r in range(size)]


def test_the_card_is_a_picture_that_carries_the_code_and_the_qr_of_that_same_code():
    import segno
    code = share.encode("Para correr", SONGS, by="Yisus")
    data = share.render_card("Para correr", "Yisus", 4, 840, [png("red"), png("blue"), png((0, 160, 90)), png("orange")], code)
    img = Image.open(io.BytesIO(data))
    assert img.format == "PNG" and img.size == (share.CARD_W, share.CARD_H)
    assert share.code_from_png(data) == code
    matrix = segno.make(code, error="l", micro=False, boost_error=False).matrix
    size = len(matrix)
    assert module_grid(img, share.qr_geometry(size), size) == [[bool(v) for v in row] for row in matrix]
    other = segno.make(share.encode("Otra", [["A", "B"]]), error="l", micro=False, boost_error=False).matrix       # control: a different code is a different drawing
    assert [[bool(v) for v in row] for row in other][:5] != [[bool(v) for v in row] for row in matrix][:5]


def test_the_card_works_without_any_cover():
    code = share.encode("Sin portadas", SONGS)
    data = share.render_card("Sin portadas", "", 4, 600, [], code)
    assert Image.open(io.BytesIO(data)).size == (share.CARD_W, share.CARD_H) and share.code_from_png(data) == code


def test_a_playlist_too_long_for_a_qr_still_gets_a_card_with_the_code_inside_and_says_so():
    songs = [[f"Artista número {i} de la lista", f"Una canción con un título bastante largo {i}"] for i in range(400)]
    code = share.encode("Enorme", songs)
    assert not share.fits_qr(code)
    data = share.render_card("Enorme", "", 400, 90000, [], code)
    assert share.code_from_png(data) == code


def test_code_from_png_gives_none_for_pictures_without_a_code_and_for_junk():
    assert share.code_from_png(png("red")) is None
    assert share.code_from_png(b"no es una imagen") is None


def test_a_card_title_that_is_huge_does_not_break_the_drawing():
    code = share.encode("W" * 80, SONGS)
    data = share.render_card("W" * 80, "Y" * 40, 4, 800, [png("red")], code)
    assert Image.open(io.BytesIO(data)).size == (share.CARD_W, share.CARD_H)


# --- m3u8 -------------------------------------------------------------------------------------------------------------------------

def test_the_m3u8_lists_the_files_with_their_titles_and_lengths():
    text = share.m3u8([{"path": r"C:\Musica\Feid - Normal.mp3", "artist": "Feid", "title": "Normal", "duration": 200}, {"path": "/m/b.mp3", "artist": "", "title": "", "duration": 0}])
    lines = text.splitlines()
    assert lines[0] == "#EXTM3U" and lines[1] == "#EXTINF:200,Feid - Normal" and lines[2] == r"C:\Musica\Feid - Normal.mp3"
    assert lines[3] == "#EXTINF:-1,b" and lines[4] == "/m/b.mp3"


# --- through the window's API ---------------------------------------------------------------------------------------

@pytest.fixture
def api(tmp_path, monkeypatch):
    import const
    import library
    from gui import backend
    from tagwriter import TagInfo
    monkeypatch.setattr(const, "data_dir", lambda: str(tmp_path / "datos"))
    songs = tmp_path / "songs"
    songs.mkdir()
    names = {"a.mp3": ("Feid", "Normal"), "b.mp3": ("Mora", "Memorias"), "c.mp3": ("Otro", "Otra")}
    for file in names:
        (songs / file).write_bytes(b"x")
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda path: TagInfo(title=names[os.path.basename(path)][1], artist=names[os.path.basename(path)][0], album="Álbum", duration=200))
    instance = backend.Api()
    monkeypatch.setattr(instance, "_downloads_dir", lambda: str(songs))
    instance.ids = {t["title"]: t["id"] for t in instance.library_list()["tracks"]}
    instance.tmp = tmp_path
    return instance


def test_the_api_makes_a_code_from_ids_in_order_and_refuses_an_empty_one(api):
    made = api.share_make([api.ids["Memorias"], api.ids["Normal"], "no-existe"], "Mis temas", "Yisus")
    assert made["ok"] and made["count"] == 2 and made["qr"] is True
    assert share.decode(made["code"])["songs"] == [["Mora", "Memorias"], ["Feid", "Normal"]]
    assert api.share_make([], "Vacía")["ok"] is False and api.share_make([api.ids["Normal"]], "")["ok"] is False


def test_the_friends_side_reads_the_code_and_finds_what_they_have_and_what_they_lack(api):
    code = share.encode("De mi amigo", [["Feid", "Normal"], ["Desconocido", "Sin copia"], ["mora", "memorias"]], by="Ana")
    got = api.share_read("mira: " + code)
    assert got["ok"] and got["name"] == "De mi amigo" and got["by"] == "Ana" and got["total"] == 3
    assert got["ids"] == [api.ids["Normal"], api.ids["Memorias"]] and got["missing"] == [["Desconocido", "Sin copia"]]
    assert api.share_read("hola")["ok"] is False and api.share_read(5)["ok"] is False


def test_a_saved_card_carries_the_code_and_importing_it_gives_the_same_playlist(api, monkeypatch):
    target = str(api.tmp / "tarjeta.png")
    monkeypatch.setattr(api, "_ask_save", lambda filename, types: target)
    saved = api.share_card_save([api.ids["Normal"], api.ids["Memorias"]], "Mi lista", "Yisus")
    assert saved == {"ok": True, "path": target}
    monkeypatch.setattr(api, "_ask_open", lambda types: target)
    from_file = api.share_read_file()
    assert from_file["ok"] and from_file["name"] == "Mi lista" and len(from_file["ids"]) == 2
    import base64
    from_drag = api.share_read_picture(base64.b64encode(open(target, "rb").read()).decode())
    assert from_drag == from_file


def test_a_picture_that_is_not_a_card_and_a_cancelled_dialog_are_reported(api, monkeypatch):
    import base64
    assert api.share_read_picture(base64.b64encode(png("red")).decode())["ok"] is False
    assert api.share_read_picture(12)["ok"] is False
    monkeypatch.setattr(api, "_ask_open", lambda types: None)
    assert api.share_read_file() == {"ok": False, "cancelled": True}
    monkeypatch.setattr(api, "_ask_save", lambda filename, types: None)
    assert api.share_card_save([api.ids["Normal"]], "X") == {"ok": False, "cancelled": True}


def test_the_m3u8_export_writes_the_files_of_the_playlist(api, monkeypatch):
    target = str(api.tmp / "lista.m3u8")
    monkeypatch.setattr(api, "_ask_save", lambda filename, types: target)
    assert api.playlist_export_m3u([api.ids["Normal"]], "Lista")["ok"]
    text = open(target, encoding="utf-8").read()
    assert text.startswith("#EXTM3U") and "Feid - Normal" in text and text.rstrip().endswith("a.mp3")
    assert api.playlist_export_m3u([], "Lista")["ok"] is False


def test_an_unwritable_destination_is_reported_not_raised(api, monkeypatch):
    monkeypatch.setattr(api, "_ask_save", lambda filename, types: str(api.tmp / "no" / "hay" / "x.png"))
    assert api.share_card_save([api.ids["Normal"]], "X")["ok"] is False
