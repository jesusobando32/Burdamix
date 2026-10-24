"""Draws the Burdamix logo and the installer icon from shapes (no image editor needed).

Run it from the project folder with the build environment:  .venv\\Scripts\\python assets\\make_icons.py
It writes assets/burdamix.ico, assets/installer.ico, assets/logo.png and gui/web/logo.png.
Change the colours below and run it again to restyle everything."""
import os

from PIL import Image, ImageDraw

BG = (35, 44, 37)        # the square behind the disc (a bit lighter than the window's near-black)
DARK = (16, 20, 15)
LIME = (180, 240, 60)
MINT = (43, 217, 160)
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SS = 4                   # draw 4x bigger and shrink: smooth edges


def blend(a, b, t):
    return tuple(round(x * (1 - t) + y * t) for x, y in zip(a, b))


def stroke(draw, points, width, color, k):
    """A polyline with round ends and round corners."""
    pts = [(x * k, y * k) for x, y in points]
    draw.line(pts, fill=color, width=round(width * k), joint="curve")
    r = width * k / 2
    for x, y in pts:
        draw.ellipse((x - r, y - r, x + r, y + r), fill=color)


def disc(draw, cx, cy, r, color, k):
    draw.ellipse(((cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k), fill=color)


def ring(draw, cx, cy, r, color, k, width=2):
    draw.ellipse(((cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k), outline=color, width=round(width * k))


def tile(size, kind):
    """kind 'app': the disc with the download arrow. kind 'installer': the same disc dropping into a tray."""
    k = size * SS / 130
    img = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size * SS - 1, size * SS - 1), radius=30 * k, fill=BG)
    groove = blend(LIME, BG, 0.55)
    if kind == "app":
        disc(d, 65, 65, 46, LIME, k)
        ring(d, 65, 65, 36, groove, k)
        disc(d, 65, 65, 25, BG, k)
        stroke(d, [(65, 53), (65, 75)], 6, LIME, k)
        stroke(d, [(55, 66), (65, 76), (75, 66)], 6, LIME, k)
    else:
        disc(d, 65, 54, 35, LIME, k)
        ring(d, 65, 54, 27, groove, k)
        disc(d, 65, 54, 19, BG, k)
        stroke(d, [(65, 45), (65, 62)], 5, LIME, k)
        stroke(d, [(58, 56), (65, 63), (72, 56)], 5, LIME, k)
        stroke(d, [(28, 94), (28, 108), (102, 108), (102, 94)], 7, MINT, k)
    return img.resize((size, size), Image.LANCZOS)


def save_ico(path, kind):
    tile(256, kind).save(path, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])


if __name__ == "__main__":
    save_ico(os.path.join(HERE, "burdamix.ico"), "app")
    save_ico(os.path.join(HERE, "installer.ico"), "installer")
    tile(512, "app").save(os.path.join(HERE, "logo.png"))
    tile(360, "app").save(os.path.join(ROOT, "gui", "web", "logo.png"))
    print("icons written")
