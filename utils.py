from const import colours, BASE62
import logging
import string
import sys
import random
import eyed3
from eyed3.id3.frames import ImageFrame
import moviepy.editor as mp
from moviepy.editor import *
import requests
import shutil
import os
import functools

logging.getLogger('moviepy').setLevel(logging.CRITICAL)


def print_splash_screen():
    print(colours.SPOTIFYGREEN + '''

        ██████╗ ██╗   ██╗██████╗ ██████╗  █████╗ ███╗   ███╗██╗██╗  ██╗
        ██╔══██╗██║   ██║██╔══██╗██╔══██╗██╔══██╗████╗ ████║██║╚██╗██╔╝
        ██████╔╝██║   ██║██████╔╝██║  ██║███████║██╔████╔██║██║ ╚███╔╝ 
        ██╔══██╗██║   ██║██╔══██╗██║  ██║██╔══██║██║╚██╔╝██║██║ ██╔██╗ 
        ██████╔╝╚██████╔╝██║  ██║██████╔╝██║  ██║██║ ╚═╝ ██║██║██╔╝ ██╗
        ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═════╝ ╚═╝  ╚═╝╚═╝     ╚═╝╚═╝╚═╝  ╚═╝
                                                                       

    ''' + colours.ENDC + colours.BOLD + '''     Tus playlists de Spotify, en MP3.  ''' + colours.ENDC + "\n")


def random_string(length=10):
    """Generate a random string of fixed length."""
    letters = string.ascii_letters  # This includes both lowercase and uppercase letters.
    return ''.join(random.choice(letters) for i in range(length))

@functools.lru_cache(maxsize=32)  # an album's tracks share one cover
def _fetch_cover(image_url):
    response = requests.get(image_url, timeout=15)
    response.raise_for_status()
    return response.content


def resave_audio_clip_with_metadata(audio_input_path, song_metadata, song_output_path, audio_quality):
    """Convert `audio_input_path` to mp3 at `audio_quality` kbps, tag it and write it to
    `song_output_path` atomically. The input file is always removed afterwards."""

    temporary_audio_path = "./temp/" + random_string(20) + ".mp3"
    partial_output_path = song_output_path + ".part"

    try:
        clip = AudioFileClip(audio_input_path)
        try:
            clip.write_audiofile(temporary_audio_path, logger=None, bitrate=f'{int(audio_quality)}k')
        finally:
            clip.close()  # releases the ffmpeg handle; otherwise Windows can't delete the file

        audiofile = eyed3.load(temporary_audio_path)

        if audiofile.tag is None:
            audiofile.initTag()

        try:
            audiofile.tag.images.set(ImageFrame.FRONT_COVER, _fetch_cover(song_metadata['image_url']), 'image/jpeg', "Cover Image from Spotify")
        except requests.RequestException as e:
            print(f"   - {colours.WARNING}[!] Could not download cover art, continuing without it.{colours.ENDC} {e}")

        audiofile.tag.title = song_metadata['title']
        audiofile.tag.artist = ", ".join(song_metadata['artist'])
        audiofile.tag.album = song_metadata['album']
        audiofile.tag.track_num = (song_metadata['track_num'], 0)
        audiofile.tag.release_date = song_metadata['release_date'][:4]  # only the year

        audiofile.tag.save()

        shutil.copy(temporary_audio_path, partial_output_path)
        os.replace(partial_output_path, song_output_path)  # a half-written .mp3 can never look finished
    finally:
        for leftover in (temporary_audio_path, partial_output_path, audio_input_path):
            try:
                os.remove(leftover)
            except OSError:
                pass
