import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import utils  # noqa: E402


def test_the_host_can_choose_the_ffmpeg(monkeypatch):
    monkeypatch.setenv("BURDAMIX_FFMPEG", "/data/app/lib/libffmpeg.so")
    assert utils.ffmpeg_command() == "/data/app/lib/libffmpeg.so"


def test_the_conversion_asks_ffmpeg_for_the_bitrate_and_drops_the_video(monkeypatch):
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setenv("BURDAMIX_FFMPEG", "ffmpeg")
    monkeypatch.setattr(subprocess, "run", fake_run)
    utils.convert_to_mp3("in.webm", "out.mp3", 192)
    assert seen["command"] == ["ffmpeg", "-y", "-i", "in.webm", "-vn", "-codec:a", "libmp3lame", "-b:a", "192k", "out.mp3"]


def test_a_failed_conversion_says_what_ffmpeg_said(monkeypatch):
    monkeypatch.setenv("BURDAMIX_FFMPEG", "ffmpeg")
    monkeypatch.setattr(subprocess, "run", lambda c, **k: subprocess.CompletedProcess(c, 1, "", "no such file"))
    with pytest.raises(RuntimeError, match="no such file"):
        utils.convert_to_mp3("in.webm", "out.mp3", 128)
