"""Sharing a playlist with a friend who also has the app, with no server in between.

The CODE is text that carries the whole list (artist and title of each song, compressed): it can be pasted in any chat. The CARD is a
picture of the playlist with a QR of that same code, and the code hidden inside the file, so dragging the card into the app imports it.
(A chat app that turns the picture into a JPEG loses the hidden code: send the card as a file, or send the code.) A .m3u8 is also
possible, for other players. Songs travel as artist and title, never as files: the friend gets the ones they already have and a list of
the ones they do not."""
import base64
import colorsys
import io
import json
import os
import re
import zlib

from PIL import Image, ImageDraw, ImageFont
from PIL.PngImagePlugin import PngInfo

from apis.youtube import normalize

PREFIX = "BURDAMIX1:"
TEXT_KEY = "burdamix-share"
MAX_SONGS = 2000
MAX_RAW = 2_000_000           # what a code may unpack to: more than this is a decompression bomb, not a playlist
MAX_PICTURE = 30_000_000
CARD_W, CARD_H = 1080, 1350
PANEL = (80, 600, 1000, 1270)  # the white panel of the card that holds the QR
KIND_RANK = {"album": 0, "playlist": 1, "track": 2, "liked": 3, "other": 4}
INK, PAPER, FALLBACK = (11, 15, 12), (255, 255, 255), (60, 140, 70)


class ShareError(ValueError):
    """The code or the card is not a playlist of Burdamix; the message says why, in Spanish, for the window."""


# --- the code -------------------------------------------------------------------------------------------------------------------

def encode(name, songs, by=""):
    name = name.strip()[:80] if isinstance(name, str) else ""
    if not name:
        raise ShareError("Ponle un nombre a la playlist antes de compartirla.")
    kept = []
    for pair in songs:
        if isinstance(pair, (list, tuple)) and len(pair) >= 2 and all(isinstance(p, str) for p in pair[:2]):
            artist, title = pair[0].strip()[:200], pair[1].strip()[:200]
            if artist and title:
                kept.append([artist, title])
    if not kept:
        raise ShareError("La playlist no tiene canciones con artista y título, así que no hay nada que compartir.")
    payload = {"v": 1, "name": name, "songs": kept[:MAX_SONGS]}
    if isinstance(by, str) and by.strip():
        payload["by"] = by.strip()[:40]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return PREFIX + base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")


def decode(text):
    """{name, by, songs: [[artist, title], ...]} from a pasted code; it may have line breaks, spaces and words around it."""
    start = text.find(PREFIX) if isinstance(text, str) else -1
    if start < 0:
        raise ShareError("Eso no parece un código de Burdamix. Empieza por «BURDAMIX1:».")
    tokens = text[start + len(PREFIX):].split()
    last = ShareError("El código está vacío o dañado. ¿Se cortó al copiarlo?")
    for count in range(len(tokens), 0, -1):          # words that follow the code in a chat are not part of it: drop them from the end
        body = re.match(r"[A-Za-z0-9_\-]*", "".join(tokens[:count])).group()
        if not body:
            continue
        try:
            return _read(body)
        except ShareError as error:
            last = error
    raise last


def _read(body):
    try:
        packed = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
    except ValueError:
        raise ShareError("El código está dañado. ¿Se cortó al copiarlo?") from None
    unpacker = zlib.decompressobj()
    try:
        raw = unpacker.decompress(packed, MAX_RAW)
    except zlib.error:
        raise ShareError("El código está dañado. ¿Se cortó al copiarlo?") from None
    if not unpacker.eof:
        raise ShareError("El código está incompleto o es demasiado grande. ¿Se cortó al copiarlo?")
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        raise ShareError("El código no contiene una playlist.") from None
    if not isinstance(data, dict) or data.get("v") != 1:
        raise ShareError("Ese código es de una versión de Burdamix que no entiendo. ¿Tienes la última?")
    name, songs, by = data.get("name"), data.get("songs"), data.get("by", "")
    if not isinstance(name, str) or not name.strip() or not isinstance(by, str):
        raise ShareError("El código no tiene nombre de playlist.")
    if not isinstance(songs, list) or not 1 <= len(songs) <= MAX_SONGS:
        raise ShareError("El código no trae canciones, o trae demasiadas.")
    clean = []
    for pair in songs:
        if not (isinstance(pair, list) and len(pair) == 2 and all(isinstance(p, str) and p.strip() for p in pair)):
            raise ShareError("Una de las canciones del código no es válida.")
        clean.append([pair[0].strip()[:200], pair[1].strip()[:200]])
    return {"name": name.strip()[:80], "by": by.strip()[:40], "songs": clean}


def match(songs, items):
    """(ids of the songs of the library that are in the list, the songs of the list that are not), in the order of the list."""
    best = {}
    for it in items:
        identity = (normalize(it.get("artist")), normalize(it.get("title")))
        if identity[0] and identity[1] and (identity not in best or KIND_RANK.get(it.get("kind"), 4) < KIND_RANK.get(best[identity].get("kind"), 4)):
            best[identity] = it
    ids, missing, seen = [], [], set()
    for artist, title in songs:
        identity = (normalize(artist), normalize(title))
        if identity in seen:
            continue
        seen.add(identity)
        if identity in best:
            ids.append(best[identity]["id"])
        else:
            missing.append([artist, title])
    return ids, missing


# --- the card -------------------------------------------------------------------------------------------------------------------

def _font(size, bold=False):
    for path in (rf"C:\Windows\Fonts\{'segoeuib' if bold else 'segoeui'}.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _qr(code):
    import segno
    return segno.make(code, error="l", micro=False, boost_error=False)


def fits_qr(code):
    """Whether the code can be drawn as a QR. False too when the drawing library is missing: the card and the code still work."""
    try:
        import segno
    except ImportError:
        return False
    try:
        _qr(code)
        return True
    except segno.DataOverflowError:
        return False


def _has_segno():
    try:
        import segno  # noqa: F401
        return True
    except ImportError:
        return False


def qr_geometry(size):
    """(left, top, pixels per module) of the QR drawn on the card: as big as the white panel allows, centred."""
    left, top, right, bottom = PANEL
    scale = max(1, min((right - left - 40) // (size + 8), (bottom - top - 40) // (size + 8)))
    return left + (right - left - scale * size) // 2, top + (bottom - top - scale * size) // 2, scale


def _tone(covers):
    """The main colour of the covers (the most vivid average), to tint the card."""
    best, score = FALLBACK, -1
    for data in covers:
        try:
            r, g, b = Image.open(io.BytesIO(data)).convert("RGB").resize((1, 1), Image.LANCZOS).getpixel((0, 0))
        except Exception:
            continue
        vivid = max(r, g, b) - min(r, g, b)
        if vivid > score:
            best, score = (r, g, b), vivid
    return best


def _hex(rgb):
    return "#%02x%02x%02x" % tuple(rgb)


def _luminance(rgb):
    def channel(v):
        v /= 255
        return v / 12.92 if v <= .03928 else ((v + .055) / 1.055) ** 2.4
    r, g, b = (channel(v) for v in rgb)
    return .2126 * r + .7152 * g + .0722 * b


def palette(covers):
    """The colours of a playlist for its QR: a deep shade of the covers' main colour for the modules and a pale tint of it for the
    plate. Whatever the cover, they keep a contrast of at least 7:1, which is what a phone camera needs to read the code."""
    tone = _tone(covers)
    hue, _, sat = colorsys.rgb_to_hls(*(v / 255 for v in tone))
    colourful = sat > .15
    dark = light = None
    for lightness in (.17, .14, .11, .08, .05):
        dark = tuple(round(v * 255) for v in colorsys.hls_to_rgb(hue, lightness, .6 if colourful else 0))
        if _luminance(dark) < .1:
            break
    for lightness in (.95, .96, .97, .98, .99):
        light = tuple(round(v * 255) for v in colorsys.hls_to_rgb(hue, lightness, .7 if colourful else 0))
        if (_luminance(light) + .05) / (_luminance(dark) + .05) >= 7:
            break
    return {"tone": tone, "dark": dark, "light": light}


def qr_uri(code, colours):
    """The QR of the code as a picture the window can show (an SVG as a data address), in the colours of the playlist; None when the code
    does not fit in a QR or the drawing library is missing."""
    if not fits_qr(code):
        return None
    return _qr(code).svg_data_uri(scale=1, border=4, dark=_hex(colours["dark"]), light=_hex(colours["light"]), xmldecl=False, nl=False)


def _fit(draw, text, font_for, width, sizes):
    """The biggest size of `sizes` at which `text` fits in `width`; if none does, the smallest with an ellipsis."""
    for size in sizes:
        font = font_for(size)
        if draw.textlength(text, font=font) <= width:
            return text, font
    font = font_for(sizes[-1])
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…", font


def _rounded(image, radius):
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius, fill=255)
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    return out


def render_card(name, by, count, seconds, covers, code):
    colours = palette(covers)
    tone = colours["tone"]
    top = tuple(int(c * .55 + 14 * .45) for c in tone)
    image = Image.composite(Image.new("RGB", (CARD_W, CARD_H), top), Image.new("RGB", (CARD_W, CARD_H), (9, 12, 10)),
                            Image.linear_gradient("L").rotate(180).resize((CARD_W, CARD_H))).convert("RGBA")
    draw = ImageDraw.Draw(image)
    # the sleeve: the covers of the first songs, four tiles (or one big if there is only one)
    box, tiles = 380, []
    for data in covers[:4]:
        try:
            tiles.append(Image.open(io.BytesIO(data)).convert("RGB"))
        except Exception:
            continue
    mosaic = Image.new("RGB", (box, box), tuple(int(c * .6) for c in tone))
    if len(tiles) == 1 or (tiles and len(tiles) < 4):
        mosaic.paste(tiles[0].resize((box, box), Image.LANCZOS), (0, 0))
    elif tiles:
        for i, tile in enumerate(tiles):
            mosaic.paste(tile.resize((box // 2, box // 2), Image.LANCZOS), ((i % 2) * box // 2, (i // 2) * box // 2))
    image.alpha_composite(_rounded(mosaic.convert("RGBA"), 36), (80, 120))
    # the words
    left, width = 500, CARD_W - 500 - 80
    draw.text((left, 130), "PLAYLIST", font=_font(30, True), fill=tuple(min(255, int(c * .5 + 140)) for c in tone))
    words, font = _fit(draw, name, lambda s: _font(s, True), width, (76, 64, 54, 46, 40))
    if words != name:      # too long for one line at the smallest size: two lines
        font = _font(46, True)
        first = name
        while first and draw.textlength(first, font=font) > width:
            first = first[:first.rfind(" ")] if " " in first else first[:-1]
        rest = name[len(first):].strip()
        rest, _ = _fit(draw, rest, lambda s: _font(46, True), width, (46,))
        draw.text((left, 180), first, font=font, fill=(255, 255, 255))
        draw.text((left, 240), rest, font=font, fill=(255, 255, 255))
        y = 310
    else:
        draw.text((left, 180), words, font=font, fill=(255, 255, 255))
        y = 180 + font.size + 26
    hours, minutes = divmod(round(seconds / 60), 60)
    sub = f"{count} {'canción' if count == 1 else 'canciones'}" + (f" · {hours} h {minutes} min" if hours else f" · {minutes} min" if seconds else "")
    draw.text((left, y), sub, font=_font(32), fill=(225, 232, 226))
    if by:
        line, f2 = _fit(draw, f"Compartida por {by}", lambda s: _font(s), width, (30, 26, 22))
        draw.text((left, y + 52), line, font=f2, fill=(190, 200, 192))
    # the panel with the QR
    draw.rounded_rectangle(PANEL, 40, fill=colours["light"])
    if fits_qr(code):
        matrix = _qr(code).matrix
        size = len(matrix)
        x0, y0, scale = qr_geometry(size)
        for r, row in enumerate(matrix):
            for c, dark in enumerate(row):
                if dark:
                    draw.rectangle((x0 + c * scale, y0 + r * scale, x0 + (c + 1) * scale - 1, y0 + (r + 1) * scale - 1), fill=colours["dark"])
    else:
        mid = (PANEL[0] + PANEL[2]) // 2
        reason = ("Esta playlist es muy grande", "para caber en un QR.") if _has_segno() else ("Este equipo no tiene", "el dibujante de QR instalado.")
        for i, (text, size) in enumerate(((reason[0], 44), (reason[1], 44), ("Usa el código de texto o arrastra", 32), ("esta imagen a Burdamix.", 32))):
            font = _font(size, i < 2)
            draw.text((mid - draw.textlength(text, font=font) / 2, PANEL[1] + 230 + i * (58 if i < 2 else 46)), text, font=font, fill=INK)
    foot, ff = _fit(draw, "Burdamix · Playlists → Importar, o arrastra esta imagen a la app", lambda s: _font(s), CARD_W - 160, (26, 22, 18))
    draw.text(((CARD_W - draw.textlength(foot, font=ff)) / 2, 1290), foot, font=ff, fill=(190, 200, 192))
    info = PngInfo()
    info.add_text(TEXT_KEY, code)
    out = io.BytesIO()
    image.convert("RGB").save(out, "PNG", pnginfo=info, optimize=True)
    return out.getvalue()


def code_from_png(data):
    """The code hidden in a card, or None for any other picture (or for something that is not a picture)."""
    if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_PICTURE:
        return None
    try:
        with Image.open(io.BytesIO(data)) as image:
            code = (getattr(image, "text", None) or {}).get(TEXT_KEY)
    except Exception:
        return None
    return code if isinstance(code, str) and code.startswith(PREFIX) else None


# --- for other players ---------------------------------------------------------------------------------------------------------------

def m3u8(items):
    """An extended M3U playlist (UTF-8). `items`: dicts with path, artist, title, duration (seconds)."""
    lines = ["#EXTM3U"]
    for it in items:
        label = " - ".join(p for p in (it.get("artist"), it.get("title")) if p) or os.path.splitext(os.path.basename(str(it["path"]).replace("\\", "/")))[0]
        lines += [f"#EXTINF:{int(it.get('duration') or -1)},{label}", str(it["path"])]
    return "\n".join(lines) + "\n"
