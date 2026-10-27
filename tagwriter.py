"""Reads and writes the tags and the cover of audio files: mp3 (ID3v2.3), flac, m4a, ogg and opus, with mutagen.

Writing never edits the user's file in place: the tags go on a copy next to it, and the copy replaces the original
only when it is complete, so a failure halfway can never leave a damaged song."""
import base64
import contextlib
import io
import os
import re
import shutil
from dataclasses import dataclass

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TPOS, TRCK, ID3NoHeaderError
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from PIL import Image, JpegImagePlugin, UnidentifiedImageError

from exceptions import MetadataError, TagWriteError, UnsupportedAudioFormat
from pathutils import long_path, sanitize_filename

SUPPORTED = (".mp3", ".flac", ".m4a", ".ogg", ".oga", ".opus")
MAX_COVER_PIXELS = 1000       # bigger covers only make the file heavy; players show them small anyway
PART_SUFFIX = ".burdamix.part"


@dataclass
class TagInfo:
    """What a file says about itself right now."""
    path: str = ""
    format: str = ""
    title: str = ""
    artist: str = ""
    album: str = ""
    album_artist: str = ""
    year: str = ""
    genre: str = ""
    track: int = 0
    track_total: int = 0
    disc: int = 0
    has_cover: bool = False
    duration: float = 0.0

    def to_dict(self):
        return {**self.__dict__, "complete": is_complete(self)}


def is_complete(tags):
    """Enough for a player to show the song properly: title, artist, album, year, track number and a cover."""
    return bool(tags.title and tags.artist and tags.album and tags.year and tags.track and tags.has_cover)


def is_supported(path):
    return os.path.splitext(path)[1].lower() in SUPPORTED


def _check_format(path):
    extension = os.path.splitext(path)[1].lower()
    if extension not in SUPPORTED:
        raise UnsupportedAudioFormat(f"No puedo etiquetar archivos «{extension or 'sin extensión'}». "
                                     "Los formatos compatibles son mp3, flac, m4a, ogg y opus.")
    return extension


def _split_number(text):
    """'9/18' -> (9, 18); '9' -> (9, 0); anything else -> (0, 0)."""
    found = re.match(r"\s*(\d+)(?:\s*/\s*(\d+))?", str(text or ""))
    return (int(found.group(1)), int(found.group(2) or 0)) if found else (0, 0)


def _first(values):
    if isinstance(values, (list, tuple)):
        values = values[0] if values else ""
    return str(values or "").strip()


def _open_ogg(path, extension):
    """An .ogg can hold Vorbis or Opus: try the likelier one first."""
    order = (OggOpus, OggVorbis) if extension == ".opus" else (OggVorbis, OggOpus)
    for cls in order:
        with contextlib.suppress(mutagen.MutagenError):
            return cls(path)
    raise MetadataError("No pude leer el archivo de audio (¿está dañado?).")


def read_tags(path):
    extension = _check_format(path)
    real = long_path(path)
    info = TagInfo(path=path, format=extension.lstrip("."))
    try:
        if extension == ".mp3":
            audio = MP3(real)
            tags = audio.tags
            if tags is not None:
                text = lambda key: _first([str(t) for t in tags[key].text]) if key in tags else ""
                info.title, info.artist, info.album = text("TIT2"), text("TPE1"), text("TALB")
                info.album_artist, info.genre = text("TPE2"), text("TCON")
                info.year = text("TDRC")[:4] or text("TYER")[:4]
                info.track, info.track_total = _split_number(text("TRCK"))
                info.disc = _split_number(text("TPOS"))[0]
                info.has_cover = any(key.startswith("APIC") for key in tags.keys())
        elif extension == ".m4a":
            audio = MP4(real)
            tags = audio.tags or {}
            info.title, info.artist, info.album = _first(tags.get("\xa9nam")), _first(tags.get("\xa9ART")), _first(tags.get("\xa9alb"))
            info.album_artist, info.genre, info.year = _first(tags.get("aART")), _first(tags.get("\xa9gen")), _first(tags.get("\xa9day"))[:4]
            track = (tags.get("trkn") or [(0, 0)])[0]
            info.track, info.track_total = int(track[0] or 0), int(track[1] or 0)
            info.disc = int(((tags.get("disk") or [(0, 0)])[0])[0] or 0)
            info.has_cover = bool(tags.get("covr"))
        else:   # flac and ogg share Vorbis comments
            audio = FLAC(real) if extension == ".flac" else _open_ogg(real, extension)
            tags = audio.tags or {}
            info.title, info.artist, info.album = _first(tags.get("title")), _first(tags.get("artist")), _first(tags.get("album"))
            info.album_artist, info.genre, info.year = _first(tags.get("albumartist")), _first(tags.get("genre")), _first(tags.get("date"))[:4]
            info.track, info.track_total = _split_number(_first(tags.get("tracknumber")))
            info.track_total = info.track_total or _split_number(_first(tags.get("tracktotal") or tags.get("totaltracks")))[0]
            info.disc = _split_number(_first(tags.get("discnumber")))[0]
            info.has_cover = bool(getattr(audio, "pictures", None)) or "metadata_block_picture" in tags
        info.duration = float(audio.info.length or 0)
    except MetadataError:
        raise
    except (mutagen.MutagenError, OSError, KeyError, ValueError):
        raise MetadataError("No pude leer el archivo de audio (¿está dañado?).") from None
    return info


def _plays_everywhere(image):
    """A JPEG every player can show: RGB, baseline (not progressive), 4:2:0 colour like the ones Spotify and Apple serve,
    and small enough. Players that choke on the other kinds (4:4:4, progressive, CMYK) show no cover at all."""
    return (image.format == "JPEG" and image.mode == "RGB" and max(image.size) <= MAX_COVER_PIXELS
            and not image.info.get("progressive") and JpegImagePlugin.get_sampling(image) == 2)


def prepare_cover(data):
    """JPEG bytes that any player can show, no bigger than 1000x1000 px, and its size. A JPEG that already is such a
    picture is kept byte for byte; anything else is re-encoded as baseline 4:2:0 RGB."""
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError):
        raise MetadataError("El archivo de la portada no es una imagen válida o está dañado.") from None
    if _plays_everywhere(image):
        return data, image.size
    image = image.convert("RGB")
    image.thumbnail((MAX_COVER_PIXELS, MAX_COVER_PIXELS), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, "JPEG", quality=92, optimize=True, subsampling=2, progressive=False)
    return out.getvalue(), image.size


def _picture(cover, size):
    picture = Picture()
    picture.type, picture.mime, picture.desc = 3, "image/jpeg", "Cover"   # 3 = front cover
    picture.data = cover
    picture.width, picture.height, picture.depth = size[0], size[1], 24
    return picture


def _write_mp3(path, song, cover, size):
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    frames = [("TIT2", TIT2, song.title), ("TPE1", TPE1, song.artist), ("TALB", TALB, song.album),
              ("TPE2", TPE2, song.album_artist), ("TDRC", TDRC, song.year), ("TCON", TCON, song.genre)]
    for key, frame, value in frames:
        if value:
            tags.delall(key)
            tags.add(frame(encoding=1, text=[value]))   # UTF-16 with BOM: the only Unicode text v2.3 players all read
    if song.track_number:
        tags.delall("TRCK")
        tags.add(TRCK(encoding=1, text=[f"{song.track_number}/{song.track_total}" if song.track_total else str(song.track_number)]))
    if song.disc_number:
        tags.delall("TPOS")
        tags.add(TPOS(encoding=1, text=[str(song.disc_number)]))
    if cover:
        tags.delall("APIC")
        tags.add(APIC(encoding=1, mime="image/jpeg", type=3, desc="Cover", data=cover))
    # v2.3, not the newer v2.4: old car radios and players only read accents correctly in v2.3.
    # save(v2_version=3) alone leaves the year in the v2.4 frame TDRC, which v2.3 players ignore;
    # update_to_v23() is what turns it into TYER.
    tags.update_to_v23()
    tags.save(path, v2_version=3, v1=1)


def _write_m4a(path, song, cover, size):
    audio = MP4(path)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags
    for key, value in (("\xa9nam", song.title), ("\xa9ART", song.artist), ("\xa9alb", song.album),
                       ("aART", song.album_artist), ("\xa9day", song.year), ("\xa9gen", song.genre)):
        if value:
            tags[key] = [value]
    if song.track_number:
        tags["trkn"] = [(song.track_number, song.track_total)]
    if song.disc_number:
        tags["disk"] = [(song.disc_number, 0)]
    if cover:
        tags["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
    audio.save()


def _write_vorbis(path, extension, song, cover, size):
    audio = FLAC(path) if extension == ".flac" else _open_ogg(path, extension)
    if audio.tags is None:
        audio.add_tags()
    for key, value in (("title", song.title), ("artist", song.artist), ("album", song.album),
                       ("albumartist", song.album_artist), ("date", song.year), ("genre", song.genre)):
        if value:
            audio[key] = [value]
    if song.track_number:
        audio["tracknumber"] = [str(song.track_number)]
        if song.track_total:
            audio["tracktotal"] = [str(song.track_total)]
    if song.disc_number:
        audio["discnumber"] = [str(song.disc_number)]
    if cover:
        picture = _picture(cover, size)
        if extension == ".flac":
            audio.clear_pictures()
            audio.add_picture(picture)
        else:   # ogg and opus carry the picture as base64 text inside a comment
            audio["metadata_block_picture"] = [base64.b64encode(picture.write()).decode("ascii")]
    audio.save()


def write_tags(path, song, cover_bytes=None):
    """Write the fields `song` has (empty ones leave the file's current value alone) and, if given, the cover.

    `song` is an apis.song_info.SongInfo. Raises TagWriteError when the file cannot be changed."""
    extension = _check_format(path)
    cover, size = prepare_cover(cover_bytes) if cover_bytes else (None, (0, 0))
    final = long_path(path)
    work = final + PART_SUFFIX
    try:
        shutil.copy2(final, work)
        try:
            if extension == ".mp3":
                _write_mp3(work, song, cover, size)
            elif extension == ".m4a":
                _write_m4a(work, song, cover, size)
            else:
                _write_vorbis(work, extension, song, cover, size)
        except mutagen.MutagenError:
            raise TagWriteError("No pude escribir las etiquetas: el archivo parece dañado.") from None
        os.replace(work, final)
    except PermissionError:
        raise TagWriteError(f"No pude cambiar «{os.path.basename(path)}»: está abierto en otro programa (cierra el reproductor) "
                            "o no tienes permiso para modificarlo.") from None
    except OSError as error:
        raise TagWriteError(f"No pude guardar «{os.path.basename(path)}» ({type(error).__name__}).") from None
    finally:
        with contextlib.suppress(OSError):
            os.remove(work)


def rename_to_title(path, title):
    """Rename the file to '<Title>.<ext>' (the artist is in the tags). Never overwrites: a taken name gets ' (2)'.
    Returns the new path."""
    folder, current = os.path.split(path)
    extension = os.path.splitext(current)[1]
    base = sanitize_filename(title, fallback=os.path.splitext(current)[0])
    candidate, number = base + extension, 2
    while os.path.normcase(candidate) != os.path.normcase(current) and os.path.exists(long_path(os.path.join(folder, candidate))):
        candidate, number = f"{base} ({number}){extension}", number + 1
    if os.path.normcase(candidate) == os.path.normcase(current):
        return path
    target = os.path.join(folder, candidate)
    try:
        os.rename(long_path(path), long_path(target))
    except PermissionError:
        raise TagWriteError(f"No pude renombrar «{current}»: está abierto en otro programa.") from None
    except OSError as error:
        raise TagWriteError(f"No pude renombrar «{current}» ({type(error).__name__}).") from None
    return target
