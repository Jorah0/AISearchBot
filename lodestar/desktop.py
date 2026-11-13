"""Native desktop window for Lodestar: the local server and the monitor loop run in this process, the UI opens in an
Edge WebView2 window (pywebview). `lodestar desktop` is what the Desktop shortcut runs. If the window cannot be
created, the UI opens in the default browser instead so the app is never dead on arrival.
"""
import os
import socket
import webbrowser
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"
APP_ID = "Lodestar.Desktop"      # explicit AppUserModelID so the taskbar shows our emblem, not python.exe's


def window_icon() -> str | None:
    """The emblem in the format each backend accepts: WinForms wants an .ico, GTK / Qt take the PNG."""
    p = ASSETS / ("lodestar.ico" if os.name == "nt" else "lodestar.png")
    return str(p) if p.is_file() else None


def free_port(start: int = 8765, tries: int = 50) -> int:
    """First free loopback port at or above `start`, so a second instance does not collide with the first."""
    for p in range(start, start + tries):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise SystemExit("no free port between 8765 and 8815")


def open_window(port: int, title: str = "Lodestar") -> None:
    """Blocks until the window is closed. Falls back to the browser when pywebview or WebView2 is unavailable."""
    url = f"http://127.0.0.1:{port}/"
    try:
        import webview
    except ImportError:
        print("desktop window needs pywebview (pip install pywebview, or pip install -e .[desktop]); opening the browser")
        _browser(url)
        return
    try:
        if os.name == "nt":
            try:  # own taskbar identity: our emblem, our grouping, not python.exe's
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
            except Exception:
                pass
        if isinstance(getattr(webview, "settings", None), dict):
            webview.settings["ALLOW_DOWNLOADS"] = True  # the document viewer's Download buttons (a blob link) save files
        webview.create_window(title, url, width=1320, height=860, min_size=(960, 640), text_select=True,
                              background_color="#0f1115")  # the UI's own dark tile, so no white flash on launch
        webview.start(icon=window_icon(), private_mode=False)  # the emblem: .ico on Windows, PNG on GTK / Qt
    except Exception as e:  # missing WebView2 runtime, headless session, etc.
        print(f"desktop window failed ({e}); opening the browser instead")
        _browser(url)


def relaunch() -> None:
    """Setup > Updates > Restart: start a fresh `lodestar desktop` (same arguments, the updated code), then close this
    window so this process ends. The browser fallback has no window to close: the process ends after a few seconds."""
    import subprocess
    import sys
    import threading

    cmd = [sys.executable, *sys.argv[1:]] if getattr(sys, "frozen", False) else [sys.executable, "-m", "lodestar", *sys.argv[1:]]
    from .util import NO_WINDOW

    subprocess.Popen(cmd, cwd=str(Path(__file__).resolve().parent.parent), creationflags=NO_WINDOW)  # the new window, no console
    from . import updater

    updater.unregister()  # os._exit below skips atexit; the new process must not wait on this one
    try:
        import webview

        for w in list(webview.windows):
            w.destroy()
    except Exception:  # no pywebview: the browser fallback
        pass
    t = threading.Timer(5, os._exit, (0,))
    t.daemon = True  # a closed window ends the process sooner; this is the backstop
    t.start()


def _browser(url: str) -> None:
    webbrowser.open(url)
    try:
        input("Lodestar is running in your browser. Press Enter here to stop it. ")
    except (EOFError, KeyboardInterrupt):
        pass
