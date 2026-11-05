import os
import sys
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import library  # noqa: E402
from exceptions import MetadataError  # noqa: E402
from tagwriter import TagInfo  # noqa: E402


def make(folder, name, data=b"x" * 1000):
    path = os.path.join(folder, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


@pytest.fixture
def no_tags(monkeypatch):
    def boom(path):
        raise MetadataError("sin etiquetas")
    monkeypatch.setattr(library.tagwriter, "read_tags", boom)


# --- scanning -----------------------------------------------------------------

def test_scan_lists_supported_files_in_subfolders_and_skips_the_rest(tmp_path, no_tags):
    make(tmp_path, "Mora - Volando.mp3")
    make(tmp_path, "album/Starboy.flac")
    make(tmp_path, "notas.txt")
    make(tmp_path, "Mora - Roto.mp3.burdamix.part")
    tracks = library.Library().scan(str(tmp_path))
    assert sorted(t["title"] for t in tracks) == ["Starboy", "Volando"]


def test_scan_falls_back_to_the_file_name_when_the_file_has_no_tags(tmp_path, no_tags):
    make(tmp_path, "Mora - Volando.mp3")
    [track] = library.Library().scan(str(tmp_path))
    assert (track["title"], track["artist"]) == ("Volando", "Mora")
    assert track["duration"] == 0


def test_scan_uses_the_tags_when_there_are_some(tmp_path, monkeypatch):
    make(tmp_path, "cualquiera.mp3")
    monkeypatch.setattr(library.tagwriter, "read_tags", lambda path: TagInfo(
        path=path, title="Blinding Lights", artist="The Weeknd", album="After Hours", duration=200.4, has_cover=True))
    [track] = library.Library().scan(str(tmp_path))
    assert (track["title"], track["artist"], track["album"]) == ("Blinding Lights", "The Weeknd", "After Hours")
    assert track["duration"] == 200 and track["cover"] is True


def test_a_second_scan_does_not_read_unchanged_files_again(tmp_path, monkeypatch):
    make(tmp_path, "a.mp3")
    calls = []
    def read(path):
        calls.append(path)
        return TagInfo(path=path, title="A", artist="B", duration=10)
    monkeypatch.setattr(library.tagwriter, "read_tags", read)
    lib = library.Library()
    lib.scan(str(tmp_path))
    lib.scan(str(tmp_path))
    assert len(calls) == 1
    make(tmp_path, "a.mp3", b"y" * 2000)    # the file changed: read again
    lib.scan(str(tmp_path))
    assert len(calls) == 2


def test_scan_of_a_missing_folder_is_empty(tmp_path):
    assert library.Library().scan(str(tmp_path / "no-existe")) == []


def test_ids_are_stable_between_scans_and_differ_between_files(tmp_path, no_tags):
    make(tmp_path, "a.mp3")
    make(tmp_path, "b.mp3")
    lib = library.Library()
    first = {t["title"]: t["id"] for t in lib.scan(str(tmp_path))}
    second = {t["title"]: t["id"] for t in lib.scan(str(tmp_path))}
    assert first == second and first["a"] != first["b"]


def test_path_of_only_knows_scanned_files(tmp_path, no_tags):
    path = make(tmp_path, "a.mp3")
    lib = library.Library()
    [track] = lib.scan(str(tmp_path))
    assert lib.path_of(track["id"]) == path
    assert lib.path_of("no-existe") is None


# --- serving ------------------------------------------------------------------

@pytest.fixture
def served(tmp_path, no_tags):
    data = bytes(range(256)) * 8                    # 2048 bytes
    make(tmp_path, "song.mp3", data)
    lib = library.Library()
    [track] = lib.scan(str(tmp_path))
    server = library.MediaServer(lib)
    server.start()
    yield server, track["id"], data
    server.stop()


def fetch(url, headers=None):
    request = urllib.request.Request(url, headers=headers or {})
    try:
        return urllib.request.urlopen(request, timeout=5)
    except urllib.error.HTTPError as error:
        return error


def test_serves_the_whole_file(served):
    server, track_id, data = served
    response = fetch(server.audio_url(track_id))
    assert response.status == 200
    assert response.read() == data
    assert response.headers["Accept-Ranges"] == "bytes"
    assert response.headers["Content-Type"] == "audio/mpeg"


def test_serves_a_byte_range_so_the_progress_bar_can_jump(served):
    server, track_id, data = served
    response = fetch(server.audio_url(track_id), {"Range": "bytes=100-199"})
    assert response.status == 206
    assert response.read() == data[100:200]
    assert response.headers["Content-Range"] == f"bytes 100-199/{len(data)}"


def test_open_ended_and_suffix_ranges(served):
    server, track_id, data = served
    assert fetch(server.audio_url(track_id), {"Range": "bytes=2000-"}).read() == data[2000:]
    assert fetch(server.audio_url(track_id), {"Range": "bytes=-48"}).read() == data[-48:]


def test_range_beyond_the_end_is_refused(served):
    server, track_id, data = served
    assert fetch(server.audio_url(track_id), {"Range": "bytes=5000-6000"}).status == 416


def test_a_wrong_token_or_an_unknown_id_gets_nothing(served):
    server, track_id, _ = served
    assert fetch(server.audio_url(track_id).replace(server.token, "otro")).status == 404
    assert fetch(server.audio_url("no-existe")).status == 404


def test_audio_can_be_read_from_the_file_page(served):
    """The window is a file:// page: without this header the browser silences the equalizer."""
    server, track_id, _ = served
    assert fetch(server.audio_url(track_id)).headers["Access-Control-Allow-Origin"] == "*"


def test_starting_the_server_twice_keeps_the_same_one(tmp_path, no_tags):
    server = library.MediaServer(library.Library())
    server.start()
    try:
        port = server.port
        server.start()
        assert server.port == port
    finally:
        server.stop()


def test_a_cover_that_changed_is_read_again(tmp_path, monkeypatch):
    import io
    from PIL import Image
    path = make(tmp_path, "a.mp3")
    def jpeg(color):
        out = io.BytesIO()
        Image.new("RGB", (8, 8), color).save(out, "JPEG")
        return out.getvalue()
    covers = [jpeg("red"), jpeg("blue")]
    monkeypatch.setattr(library.tagwriter, "read_cover", lambda p: covers[0])
    server = library.MediaServer(library.Library())
    first = server._small_cover(path)
    monkeypatch.setattr(library.tagwriter, "read_cover", lambda p: covers[1])
    assert server._small_cover(path) == first          # same file version: remembered
    os.utime(path, (1_000_000, 1_000_000))              # the tags were rewritten: new version
    assert server._small_cover(path) != first
