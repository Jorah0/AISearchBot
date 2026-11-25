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
QUIT = False  # set by quit() / relaunch(): the next close really closes (else close_to_taskbar minimizes)
_MIN_THREADS: list = []  # the minimize threads _on_closing starts (tests join the last one)
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # per user: no admin rights, removed by toggling off


def _on_closing(window):
    """The main window's close button: with pref close_to_taskbar (on by default) it minimizes to the taskbar and the
    server, loop and alerts keep running; Quit Lodestar (Setup) or a Restart really closes it. False cancels the close.
    pywebview runs this on the UI thread, so the minimize goes to its own thread."""
    from . import settings

    if QUIT or _session_ending() or not settings.pref("close_to_taskbar"):
        return None  # a sign-out / shutdown always closes: never block Windows from ending the session
    t = __import__("threading").Thread(target=window.minimize, daemon=True)
    _MIN_THREADS[:] = [t]
    t.start()
    return False


def _session_ending() -> bool:
    """Windows is signing out or shutting down (GetSystemMetrics SM_SHUTTINGDOWN). With _watch_session_end's
    SessionEnding hook, a close Windows sends at session end is never turned into a minimize."""
    if os.name != "nt":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.user32.GetSystemMetrics(0x2000))  # SM_SHUTTINGDOWN
    except Exception:
        return False


def _watch_session_end() -> None:
    """SessionEnding (pythonnet, which pywebview's WinForms backend already loads) marks the app as quitting, so the
    close Windows sends next goes through. ponytail: best effort; _session_ending() covers a missing pythonnet."""
    try:
        __import__("clr")  # pythonnet: makes the .NET namespaces importable
        from Microsoft.Win32 import SystemEvents

        def ending(sender, args):
            global QUIT
            QUIT = True
        SystemEvents.SessionEnding += ending
    except Exception:
        pass


def quit() -> None:  # noqa: A001 (the desktop app's own Quit, not the builtin)
    """Setup > Quit Lodestar: close the window for real (the process then ends like a closed window always did)."""
    global QUIT
    QUIT = True
    try:
        import webview

        for w in list(webview.windows):
            w.destroy()
    except Exception:
        pass


def autostart_command() -> str:
    """What Windows runs at sign-in: the console-less launcher with `desktop --minimized` (the window waits on the
    taskbar). The standalone exe runs itself; an install runs lodestarw.exe beside its python, else pythonw -m."""
    import sys

    exe = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return f'"{exe}" desktop --minimized'
    if (w := exe.parent / "lodestarw.exe").is_file() or (w := exe.parent / "Scripts" / "lodestarw.exe").is_file():
        return f'"{w}" desktop --minimized'
    pyw = exe.with_name("pythonw.exe")
    return f'"{pyw if pyw.is_file() else exe}" -m lodestar desktop --minimized'


def _own_home() -> bool:
    """The data folder is the default one (~/.lodestar, or ~/.jobbot): the startup entry runs `lodestar desktop`
    without LODESTAR_HOME, so only that home may write it (like vault.namespace keeps temp homes off the real keys)."""
    from .config import HOME

    here, *default = (os.path.normcase(os.path.realpath(p)) for p in (HOME, Path.home() / ".lodestar", Path.home() / ".jobbot"))
    return here in default


def set_autostart(on: bool) -> None:
    """Pref start_on_boot: add or remove the 'Lodestar' value under the per-user Run key. Raises SystemExit with the
    reason when Windows refuses (settings.set_pref then keeps the old value)."""
    if os.name != "nt":
        raise SystemExit("start on boot is set up on Windows only (use your desktop's startup applications elsewhere)")
    if not _own_home():
        raise SystemExit("start on boot is for your own data folder (~/.lodestar): this Lodestar runs with another "
                         "LODESTAR_HOME (a test or a sandbox), so the Windows startup entry is left alone")
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, "Lodestar", 0, winreg.REG_SZ, autostart_command())
            else:
                try:
                    winreg.DeleteValue(k, "Lodestar")
                except FileNotFoundError:
                    pass  # already off
    except OSError as e:
        raise SystemExit(f"could not change the Windows startup entry: {e}") from None


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


def open_window(port: int, title: str = "Lodestar", minimized: bool = False) -> None:
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
        win = webview.create_window(title, url, width=1320, height=860, min_size=(960, 640), text_select=True,
                                    background_color="#0f1115",  # the UI's own dark tile, so no white flash on launch
                                    minimized=minimized)  # started at sign-in (start_on_boot): waits on the taskbar
        if win is not None:
            if os.name == "nt":
                _watch_session_end()
            win.events.closing += _on_closing  # the main window only: Lodestar's job-site browser windows close normally
        from . import browser

        browser.ON = True  # job-site links now open in Lodestar's own browser window (pass 52)
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
    global QUIT
    QUIT = True  # close for real, not to the taskbar
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
