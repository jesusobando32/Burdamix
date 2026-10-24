# PyInstaller recipe for Burdamix. Build it with build_exe.bat (or: pyinstaller Burdamix.spec --noconfirm).
# Two programs share one folder: Burdamix.exe (the window) and Burdamix-consola.exe (text mode, for commands).
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

datas, binaries, hiddenimports = [], [], []
for package in ("yt_dlp", "yt_dlp_ejs", "imageio_ffmpeg", "moviepy", "eyed3", "tekore", "webview", "clr_loader", "pythonnet"):
    d, b, h = collect_all(package)     # code that is loaded by name (extractors, plugins, bundled ffmpeg, WebView2 DLLs) is invisible to the scan
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("flask") + collect_submodules("gui")
datas += [("assets", "assets"), ("gui/web", "gui/web")]

icon = "assets/burdamix.ico" if os.path.exists("assets/burdamix.ico") else None
excludes = ["tkinter", "pytest", "matplotlib", "scipy", "IPython"]

gui_a = Analysis(["gui_app.py"], pathex=["."], datas=datas, binaries=binaries, hiddenimports=hiddenimports, excludes=excludes)
cli_a = Analysis(["spotify2mp3.py"], pathex=["."], datas=datas, binaries=binaries, hiddenimports=hiddenimports, excludes=excludes)
MERGE((gui_a, "gui_app", "Burdamix"), (cli_a, "spotify2mp3", "Burdamix-consola"))   # one copy of the shared libraries

gui_exe = EXE(PYZ(gui_a.pure), gui_a.scripts, [], exclude_binaries=True, name="Burdamix",
              console=False, icon=icon, upx=False)           # upx=False: packed programs trigger more antivirus false positives
cli_exe = EXE(PYZ(cli_a.pure), cli_a.scripts, [], exclude_binaries=True, name="Burdamix-consola",
              console=True, icon=icon, upx=False)

coll = COLLECT(gui_exe, gui_a.binaries, gui_a.datas, cli_exe, cli_a.binaries, cli_a.datas, name="Burdamix", upx=False)
