"""Burdamix with a window. Start it with: python gui_app.py (the compiled Burdamix.exe does the same)."""
import multiprocessing
import os
import sys


def _give_streams_a_place_to_write():
    """A program without a console has no stdout/stderr; anything that prints would crash."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


_give_streams_a_place_to_write()   # at import time: the Spotify login child process starts here too


def _tell_user(text):
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, "Burdamix", 0x10)
    else:
        print(text, file=sys.stderr)


def main():
    import const
    import updater
    updater.use_downloaded_ytdlp()   # compiled program: use the yt-dlp the user downloaded, before anything imports it

    try:
        import webview
        from gui.backend import Api
        api = Api()
        page = os.path.join(const.resource_dir(), "gui", "web", "index.html")
        window = webview.create_window("Burdamix", page, js_api=api, width=1120, height=760, min_size=(760, 540),
                                       background_color="#0e110f")
        api.attach_window(window)
        webview.start()
    except Exception as error:
        _tell_user(f"Burdamix no pudo abrir su ventana ({type(error).__name__}: {error}).\n\n"
                   "Necesita Microsoft Edge WebView2, que viene con Windows 10 y 11. "
                   "Si no lo tienes, instálalo desde https://go.microsoft.com/fwlink/p/?LinkId=2124703")
        sys.exit(1)


if __name__ == "__main__":
    multiprocessing.freeze_support()   # the compiled program starts the Spotify login server as a child process
    main()
