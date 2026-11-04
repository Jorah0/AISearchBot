"""Native desktop window for Lodestar: the local server and the monitor loop run in this process, the UI opens in an
Edge WebView2 window (pywebview). `lodestar desktop` is what the Desktop shortcut runs. If the window cannot be
created, the UI opens in the default browser instead so the app is never dead on arrival.
"""
import os
import socket
import webbrowser
from pathlib import Path

ICON = Path(__file__).resolve().parent.parent / "assets" / "lodestar.png"


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
        webview.create_window(title, url, width=1320, height=860, min_size=(960, 640), text_select=True)
        # the icon argument is GTK/Qt only; on Windows the .NET backend rejects a PNG, and the shortcut already carries
        # the .ico, so pass it only where it is honoured
        webview.start(icon=str(ICON) if ICON.is_file() and os.name != "nt" else None, private_mode=False)
    except Exception as e:  # missing WebView2 runtime, headless session, etc.
        print(f"desktop window failed ({e}); opening the browser instead")
        _browser(url)


def _browser(url: str) -> None:
    webbrowser.open(url)
    try:
        input("Lodestar is running in your browser. Press Enter here to stop it. ")
    except (EOFError, KeyboardInterrupt):
        pass
