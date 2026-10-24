# PyInstaller recipe for Burdamix. Build it with build_exe.bat (or: pyinstaller Burdamix.spec --noconfirm).
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
for package in ("yt_dlp", "yt_dlp_ejs", "imageio_ffmpeg", "moviepy", "eyed3", "tekore"):
    d, b, h = collect_all(package)     # code that is loaded by name (extractors, plugins, bundled ffmpeg) is invisible to the scan
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("flask")

icon = "assets/burdamix.ico" if os.path.exists("assets/burdamix.ico") else None

a = Analysis(
    ["spotify2mp3.py"],
    pathex=["."],
    datas=datas + [("assets", "assets")],
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "matplotlib", "scipy", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Burdamix",
    console=True,          # the guided mode is a text window for now; it goes away with the graphical interface
    icon=icon,
    upx=False,             # UPX-packed programs trigger more antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, name="Burdamix", upx=False)
