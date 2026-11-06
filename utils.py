import contextlib
import functools
import os
import shutil
import subprocess
import sys
import tempfile

import eyed3
import requests
from eyed3.id3.frames import ImageFrame

import tempdirs
from const import colours
from pathutils import long_path


def ffmpeg_command():
    """The ffmpeg that converts the audio: the one the host gives (BURDAMIX_FFMPEG, on Android) or the one imageio-ffmpeg carries."""
    given = os.environ.get("BURDAMIX_FFMPEG")
    if given:
        return given
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def convert_to_mp3(source_path, target_path, kbps):
    """Writes `source_path` as an mp3 of `kbps` kbps (video, if any, is dropped). Raises RuntimeError with ffmpeg's last words."""
    command = [ffmpeg_command(), "-y", "-i", source_path, "-vn", "-codec:a", "libmp3lame", "-b:a", f"{int(kbps)}k", target_path]
    done = subprocess.run(command, capture_output=True, text=True, errors="replace",
                          creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
    if done.returncode != 0:
        raise RuntimeError(f"ffmpeg salió con {done.returncode}: {(done.stderr or '').strip()[-300:]}")


def print_splash_screen():
    print(colours.SPOTIFYGREEN + '''

        ██████╗ ██╗   ██╗██████╗ ██████╗  █████╗ ███╗   ███╗██╗██╗  ██╗
        ██╔══██╗██║   ██║██╔══██╗██╔══██╗██╔══██╗████╗ ████║██║╚██╗██╔╝
        ██████╔╝██║   ██║██████╔╝██║  ██║███████║██╔████╔██║██║ ╚███╔╝ 
        ██╔══██╗██║   ██║██╔══██╗██║  ██║██╔══██║██║╚██╔╝██║██║ ██╔██╗ 
        ██████╔╝╚██████╔╝██║  ██║██████╔╝██║  ██║██║ ╚═╝ ██║██║██╔╝ ██╗
        ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝╚═╝  ╚═╝
                                                                       

    ''' + colours.ENDC + colours.BOLD + '''     Tus playlists de Spotify, en MP3.  ''' + colours.ENDC + "\n")


@functools.lru_cache(maxsize=32)  # an album's tracks share one cover
def _fetch_cover(image_url):
    response = requests.get(image_url, timeout=15)
    response.raise_for_status()
    return response.content


def _image_mime_type(data):
    """Spotify covers are JPEG but the fallback cover is a PNG; label each one correctly."""
    png_signature = bytes([137, 80, 78, 71])   # the first four bytes of every PNG file
    return "image/png" if data[:4] == png_signature else "image/jpeg"


def resave_audio_clip_with_metadata(audio_input_path, song_metadata, song_output_path, audio_quality, tag=True):
    """Convert `audio_input_path` to mp3 at `audio_quality` kbps, tag it and write it to
    `song_output_path` atomically. The input file is always removed afterwards.
    With `tag=False` the mp3 is left without tags: the caller writes them afterwards (tagwriter)."""

    handle, temporary_audio_path = tempfile.mkstemp(suffix=".mp3", dir=tempdirs.run_dir())   # unique name
    os.close(handle)
    final_path = long_path(song_output_path)    # works past 260 characters on Windows
    partial_output_path = final_path + ".part"

    try:
        convert_to_mp3(audio_input_path, temporary_audio_path, audio_quality)

        if tag:
            audiofile = eyed3.load(temporary_audio_path)

            if audiofile.tag is None:
                audiofile.initTag()

            try:
                cover = _fetch_cover(song_metadata['image_url'])
                audiofile.tag.images.set(ImageFrame.FRONT_COVER, cover, _image_mime_type(cover), "Cover Image from Spotify")
            except requests.RequestException as e:
                print(f"   - {colours.WARNING}[!] Could not download cover art, continuing without it.{colours.ENDC} {e}")

            audiofile.tag.title = song_metadata['title']
            audiofile.tag.artist = ", ".join(song_metadata['artist'])
            audiofile.tag.album = song_metadata['album']
            audiofile.tag.track_num = (song_metadata['track_num'], 0)
            year = (song_metadata.get('release_date') or "")[:4]
            if year:
                audiofile.tag.recording_date = year   # ID3v2.3 stores the year in TYER; 'release_date' would be dropped

            # v2.3 (not the newer v2.4): old car radios and players only read accents correctly in v2.3
            audiofile.tag.save(version=eyed3.id3.ID3_V2_3)

        shutil.copy(temporary_audio_path, partial_output_path)
        os.replace(partial_output_path, final_path)  # a half-written .mp3 can never look finished
    finally:
        for leftover in (temporary_audio_path, partial_output_path, audio_input_path):
            with contextlib.suppress(OSError):
                os.remove(leftover)
