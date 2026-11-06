import os
import socket
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "android", "app", "src", "main", "python"))

import burdamix_spike as spike  # noqa: E402


class FakeYoutubeDL:
    """Stands in for yt_dlp.YoutubeDL: reads a title and 'downloads' a small file."""
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        if download:
            with open(self.prepare_filename({}), "wb") as f:
                f.write(b"x" * 2048)
        return {"title": "Prueba", "duration": 19}

    def prepare_filename(self, info):
        return os.path.join(self.options["outtmpl"].rsplit(os.sep, 1)[0], "prueba.webm")


@pytest.fixture
def online(monkeypatch):
    """The network is faked: the test of the stages must not depend on the machine running it."""
    import yt_dlp
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: socket.socket())
    monkeypatch.setattr(yt_dlp, "YoutubeDL", FakeYoutubeDL)


def names(result):
    return [s["name"] for s in result["stages"]]


def test_without_internet_the_test_stops_at_the_network_stage(monkeypatch, tmp_path):
    def refuse(*args, **kwargs):
        raise OSError("sin red")
    monkeypatch.setattr(socket, "create_connection", refuse)
    result = spike.probe("https://example.org/v", str(tmp_path))
    assert result["ok"] is False
    assert names(result)[-1] == "Internet"
    assert result["stages"][-1]["ok"] is False and "sin red" in result["stages"][-1]["detail"]


def test_a_missing_ffmpeg_is_reported_not_raised(online, tmp_path):
    result = spike.probe("https://example.org/v", str(tmp_path), ffmpeg_path="")
    assert result["ok"] is False
    assert names(result) == ["Python", "Importar yt-dlp", "Internet", "Leer el video", "Descargar el audio", "Convertir a MP3"]
    assert [s["ok"] for s in result["stages"]] == [True, True, True, True, True, False]
    assert "ffmpeg" in result["stages"][-1]["detail"]


def test_the_whole_job_passes_when_every_stage_works(online, monkeypatch, tmp_path):
    def fake_ffmpeg(command, **kwargs):
        with open(command[-1], "wb") as f:
            f.write(b"y" * 4096)
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)
    result = spike.probe("https://example.org/v", str(tmp_path), ffmpeg_path="/fake/ffmpeg")
    assert result["ok"] is True and all(s["ok"] for s in result["stages"])
    assert os.path.exists(tmp_path / "prueba.mp3")


def test_ffmpeg_gets_the_library_folders_it_needs(online, monkeypatch, tmp_path):
    seen = {}

    def fake_ffmpeg(command, **kwargs):
        seen["ld"] = kwargs["env"]["LD_LIBRARY_PATH"]
        with open(command[-1], "wb") as f:
            f.write(b"y" * 4096)
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setenv("LD_LIBRARY_PATH", "/already/there")
    monkeypatch.setattr(subprocess, "run", fake_ffmpeg)
    spike.probe("https://example.org/v", str(tmp_path), ffmpeg_path="/fake/ffmpeg", lib_dirs="/a/lib:/b/lib")
    assert seen["ld"] == "/a/lib:/b/lib:/already/there"


def test_a_failing_ffmpeg_says_why(online, monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda c, **k: subprocess.CompletedProcess(c, 126, "", "Permission denied"))
    result = spike.probe("https://example.org/v", str(tmp_path), ffmpeg_path="/fake/ffmpeg")
    assert result["ok"] is False
    assert "126" in result["stages"][-1]["detail"] and "Permission denied" in result["stages"][-1]["detail"]


def test_the_screen_text_marks_each_stage_and_the_verdict():
    text = spike.render({"ok": False, "stages": [{"name": "Python", "ok": True, "detail": "3.13", "seconds": 0.0},
                                                {"name": "Internet", "ok": False, "detail": "OSError: x", "seconds": 1.2}]})
    lines = text.splitlines()
    assert lines[0].startswith("✔ Python") and lines[1].startswith("✘ Internet")
    assert lines[-1].startswith("RESULTADO: se detuvo")
