"""The test of the phone: can Python (inside the app, through Chaquopy) run yt-dlp, download an audio and turn it into an MP3?

Every stage is reported on its own, so one run says exactly where it stops (no network, yt-dlp cannot read the video, the audio
cannot be downloaded, the ffmpeg binary cannot be run on this Android) instead of one vague failure. Nothing here raises:
`probe` always comes back with a list of stages.
"""
import os
import platform
import socket
import subprocess
import sys
import time


def _stage(stages, name, fn):
    """Runs one stage; its outcome (ok, a short detail, the seconds it took) is appended to `stages`."""
    started = time.monotonic()
    try:
        detail = fn()
        stages.append({"name": name, "ok": True, "detail": str(detail), "seconds": round(time.monotonic() - started, 1)})
        return True
    except Exception as error:   # every kind of failure is a result of the test, not a crash
        stages.append({"name": name, "ok": False, "detail": f"{type(error).__name__}: {error}"[:400], "seconds": round(time.monotonic() - started, 1)})
        return False


def _run_ffmpeg(ffmpeg, source, target, lib_dirs=""):
    # The ffmpeg executable needs its shared libraries (libc++_shared.so, libav*.so) and Android does not look for them next to it.
    env = dict(os.environ)
    if lib_dirs:
        env["LD_LIBRARY_PATH"] = lib_dirs + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    done = subprocess.run([ffmpeg, "-y", "-i", source, "-vn", "-codec:a", "libmp3lame", "-q:a", "2", target],
                          capture_output=True, text=True, timeout=300, env=env)
    if done.returncode != 0:
        raise RuntimeError(f"ffmpeg exited with {done.returncode}: {(done.stderr or '').strip()[-300:]}")
    return f"{os.path.basename(target)} ({os.path.getsize(target) // 1024} KB)"


def probe(url, out_dir, ffmpeg_path="", lib_dirs=""):
    """Returns {"ok": bool, "stages": [...]}. `ffmpeg_path` is where the app found an ffmpeg executable ("" if it found none);
    `lib_dirs` are the folders (":"-separated) with the shared libraries that executable loads."""
    stages, state = [], {}
    os.makedirs(out_dir, exist_ok=True)

    _stage(stages, "Python", lambda: f"{platform.python_version()} en {platform.machine()} · {sys.platform}")

    def import_ytdlp():
        import yt_dlp
        from yt_dlp.version import __version__
        state["yt_dlp"] = yt_dlp
        return f"yt-dlp {__version__}"
    if not _stage(stages, "Importar yt-dlp", import_ytdlp):
        return {"ok": False, "stages": stages}

    def reach_internet():
        socket.create_connection(("www.youtube.com", 443), timeout=10).close()
        return "www.youtube.com:443 responde"
    if not _stage(stages, "Internet", reach_internet):
        return {"ok": False, "stages": stages}

    def read_video():
        with state["yt_dlp"].YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            info = ydl.extract_info(url, download=False)
        state["title"] = info.get("title") or "audio"
        return f"{state['title']} · {info.get('duration', '?')} s"
    if not _stage(stages, "Leer el video", read_video):
        return {"ok": False, "stages": stages}

    def download_audio():
        options = {"quiet": True, "no_warnings": True, "format": "bestaudio/best", "outtmpl": os.path.join(out_dir, "prueba.%(ext)s")}
        with state["yt_dlp"].YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
            state["audio"] = ydl.prepare_filename(info)
        return f"{os.path.basename(state['audio'])} ({os.path.getsize(state['audio']) // 1024} KB)"
    if not _stage(stages, "Descargar el audio", download_audio):
        return {"ok": False, "stages": stages}

    if not ffmpeg_path:
        stages.append({"name": "Convertir a MP3", "ok": False, "detail": "la app no encontró un ejecutable de ffmpeg", "seconds": 0})
        return {"ok": False, "stages": stages}
    ok = _stage(stages, "Convertir a MP3", lambda: _run_ffmpeg(ffmpeg_path, state["audio"], os.path.join(out_dir, "prueba.mp3"), lib_dirs))
    return {"ok": ok, "stages": stages}


def render(result):
    """The stages as text for the screen."""
    lines = [f"{'✔' if s['ok'] else '✘'} {s['name']} ({s['seconds']} s): {s['detail']}" for s in result["stages"]]
    lines.append("")
    lines.append("RESULTADO: todo funciona en este teléfono" if result["ok"] else "RESULTADO: se detuvo; lee la línea ✘")
    return "\n".join(lines)
