"""Android emulator end-to-end test for Lodestar's phone app (android/). Stdlib only.

Boots the `lodestar_test` AVD headless (or reuses a running emulator), starts a REAL Lodestar in a throwaway home with
phone access on, installs android/lodestar.apk and drives the app with `adb shell input` + `uiautomator dump`:

  refuse   a non-private address typed on the setup screen is refused (the app never loads it)
  pair     type this computer's LAN address, get a pairing code (phone.new_code, what Setup's button calls), type it
           in the WebView's pairing page, and Lodestar's page (Today) loads
  persist  force-stop + relaunch: still paired (the cookie survived), Today again
  deny     a phone session asking for a phone-denied route (/api/keys) is answered 403
  update   a newer build offered by the computer (/phone/app.json) makes the app show its "Update Lodestar" dialog

The emulator reaches this computer's LAN address through its NAT (the app loads private addresses only; 10.0.2.2 is
the host's loopback, where the phone listener never binds). On failure: screenshot, uiautomator XML and logcat in
tests/e2e/_artifacts/android/. Exit 0 with "SKIPPED: <reason>" when the SDK, AVD or emulator is missing.

  .venv\\Scripts\\python.exe scripts\\android_e2e.py          (env LODESTAR_AVD to use another AVD)
"""
import http.client
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / "android"
APK = ANDROID / "lodestar.apk"
ARTIFACTS = ROOT / "tests" / "e2e" / "_artifacts" / "android"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # same as util.NO_WINDOW: no console window pops up
PKG, ACTIVITY = "app.lodestar.mobile", "app.lodestar.mobile/.MainActivity"
BOOT_TIMEOUT, UI_TIMEOUT = 240, 45


# ----------------------------------------------------------------------------- pure parts (unit tested)
def sdk_dir() -> Path:
    env = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    return Path(env) if env else Path(os.environ.get("USERPROFILE", Path.home())) / "Android" / "sdk"


def avd_home() -> Path:
    env = os.environ.get("ANDROID_AVD_HOME")
    return Path(env) if env else Path(os.environ.get("USERPROFILE", Path.home())) / ".android" / "avd"


def exe(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


def skip_reason(sdk: Path, avd: str, avds: Path) -> str:
    """Why this machine cannot run the test ('' when it can)."""
    if not sdk.is_dir():
        return f"no Android SDK at {sdk}"
    if not (sdk / "platform-tools" / exe("adb")).is_file():
        return "no adb (SDK platform-tools)"
    if not (sdk / "emulator" / exe("emulator")).is_file():
        return "no Android emulator in the SDK"
    if not (avds / f"{avd}.ini").is_file():
        return f"no AVD named {avd} under {avds}"
    return ""


def safe_home(path) -> Path:
    """The throwaway LODESTAR_HOME, refused when it is (or is inside) a real data folder: never ~/.lodestar."""
    p = Path(path).resolve()
    for real in (Path.home() / ".lodestar", Path.home() / ".jobbot"):
        r = real.resolve()
        if p == r or r in p.parents:
            raise SystemExit(f"refusing to use the real data folder {p} as the test home")
    if Path(tempfile.gettempdir()).resolve() not in p.parents:
        raise SystemExit(f"the test home must be a temp folder, not {p}")
    return p


def wait_boot(getprop, timeout: float = BOOT_TIMEOUT, sleep=time.sleep, clock=time.monotonic) -> float:
    """Poll getprop() (sys.boot_completed) until it says '1'; seconds waited, TimeoutError after timeout. getprop may
    raise OSError / return '' while the device is still coming up."""
    t0 = clock()
    while True:
        try:
            if str(getprop() or "").strip() == "1":
                return clock() - t0
        except (OSError, subprocess.SubprocessError):
            pass
        if clock() - t0 > timeout:
            raise TimeoutError(f"emulator did not finish booting in {timeout:.0f} s")
        sleep(2)


def parse_nodes(xml_text: str) -> list[dict]:
    """uiautomator dump XML -> [{text, id, cls, desc, x, y, ...}] with the centre of each node's bounds."""
    out = []
    start = xml_text.find("<?xml")
    root = ET.fromstring(xml_text[start if start >= 0 else 0:].strip())
    for n in root.iter("node"):
        m = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", n.get("bounds", ""))
        x1, y1, x2, y2 = (int(v) for v in m.groups()) if m else (0, 0, 0, 0)
        out.append({"text": n.get("text", ""), "id": n.get("resource-id", ""), "cls": n.get("class", ""),
                    "desc": n.get("content-desc", ""), "hint": n.get("hint", ""), "pkg": n.get("package", ""),
                    "x": (x1 + x2) // 2, "y": (y1 + y2) // 2})
    return out


def find(nodes: list[dict], text: str | None = None, rid: str | None = None, cls: str | None = None,
         contains: bool = False) -> dict | None:
    """First node matching every given field (text / content-desc, resource id, class); contains = substring text."""
    for n in nodes:
        if rid is not None and n["id"] != rid:
            continue
        if cls is not None and n["cls"] != cls:
            continue
        if text is not None:
            t, hay = text.casefold(), (n["text"].casefold(), n["desc"].casefold())  # a Material button may say CONNECT
            if not any((t in h) if contains else (h == t) for h in hay):
                continue
        return n
    return None


def apk_stale(apk: Path, sources: list[Path]) -> bool:
    """Build again when the APK is missing or older than any source file."""
    if not apk.is_file():
        return True
    built = apk.stat().st_mtime
    return any(f.stat().st_mtime > built for d in sources for f in ([d] if d.is_file() else d.rglob("*")) if f.is_file())


# ----------------------------------------------------------------------------- processes
# our own adb server port: another tool's adb on the default 5037 (a different SDK version) replaces a server started
# there mid-run and the device vanishes; kill-server at the end then stops only ours. Emulators are found on any port.
ENV = os.environ | {"ANDROID_ADB_SERVER_PORT": os.environ.get("LODESTAR_ADB_PORT", "5039")}


def run(cmd: list, timeout: float = 60, binary: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], capture_output=True, timeout=timeout, creationflags=NO_WINDOW, env=ENV,
                          **({} if binary else {"text": True, "encoding": "utf-8", "errors": "replace"}))


class Device:
    def __init__(self, adb: Path, serial: str):
        self.adb, self.serial = adb, serial

    def __call__(self, *args, timeout: float = 60, binary: bool = False):
        return run([self.adb, "-s", self.serial, *args], timeout, binary)

    def sh(self, *args, timeout: float = 60) -> str:
        return self("shell", *args, timeout=timeout).stdout

    def nodes(self) -> list[dict]:
        self.sh("uiautomator", "dump", "/sdcard/ui.xml", timeout=30)
        xml = self("exec-out", "cat", "/sdcard/ui.xml", timeout=30).stdout
        self.last_xml = xml
        return parse_nodes(xml) if "<hierarchy" in xml else []

    def wait_for(self, timeout: float = UI_TIMEOUT, **match) -> dict:
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            n = find(self.nodes(), **match)
            if n:
                return n
            time.sleep(1)
        raise AssertionError(f"not on screen after {timeout:.0f} s: {match}")

    def tap(self, n: dict) -> None:
        self.sh("input", "tap", str(n["x"]), str(n["y"]))

    def type(self, text: str) -> None:
        self.sh("input", "text", text.replace(" ", "%s"))

    def launch(self) -> None:
        self.sh("am", "start", "-W", "-n", ACTIVITY, timeout=60)

    def version_code(self) -> int:
        m = re.search(r"versionCode=(\d+)", self.sh("dumpsys", "package", PKG))
        return int(m.group(1)) if m else -1


def devices(adb: Path) -> list[str]:
    out = run([adb, "devices"], 30).stdout
    return [ln.split()[0] for ln in out.splitlines()[1:] if ln.strip().endswith("\tdevice") and ln.startswith("emulator-")]


def boot(sdk: Path, adb: Path, avd: str):
    """(Device, Popen or None, seconds): a running emulator is reused, else the AVD boots headless."""
    have = devices(adb)
    if have:
        return Device(adb, have[0]), None, 0.0
    port = next(p for p in range(5554, 5586, 2) if f"emulator-{p}" not in have)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    log = open(ARTIFACTS / "emulator.log", "w", encoding="utf-8")
    cmd = [sdk / "emulator" / exe("emulator"), "-avd", avd, "-port", str(port), "-no-window", "-no-audio",
           "-no-boot-anim", "-no-snapshot-save", "-gpu", os.environ.get("LODESTAR_AVD_GPU", "swiftshader_indirect")]
    proc = subprocess.Popen([str(c) for c in cmd], stdout=log, stderr=subprocess.STDOUT, creationflags=NO_WINDOW,
                            env=ENV)
    dev = Device(adb, f"emulator-{port}")
    t0 = time.monotonic()

    def prop():
        if proc.poll() is not None:
            raise RuntimeError(f"the emulator exited ({proc.returncode}): see {ARTIFACTS / 'emulator.log'}")
        return dev.sh("getprop", "sys.boot_completed", timeout=15)

    try:
        wait_boot(prop)
    except BaseException:
        stop_emulator(dev, proc)
        raise
    return dev, proc, time.monotonic() - t0


def stop_emulator(dev: Device, proc) -> None:
    try:
        dev("emu", "kill", timeout=30)
        proc.wait(timeout=60)
    except (subprocess.SubprocessError, OSError):
        pass
    if proc.poll() is None or os.name == "nt":  # emulator.exe starts qemu as a child: take the whole tree down
        if os.name == "nt":
            run(["taskkill", "/T", "/F", "/PID", proc.pid], 30)
        proc.kill()


def build_apk() -> float:
    t0 = time.monotonic()
    p = run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ANDROID / "build.ps1"], 1200)
    if p.returncode != 0:
        raise RuntimeError("android/build.ps1 failed:\n" + (p.stdout + p.stderr)[-2000:])
    return time.monotonic() - t0


# ----------------------------------------------------------------------------- Lodestar, in a throwaway home
def start_lodestar(home: Path):
    """A real Lodestar phone listener over fictional data. Env is set before the first lodestar import."""
    os.environ["LODESTAR_HOME"] = str(safe_home(home))
    os.environ["LODESTAR_VAULT_SERVICE"] = ""  # the temp home's own keyring namespace, never the real one
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    os.environ["LODESTAR_NO_STARTUP_CHECK"] = "1"
    env = ROOT / ".env"  # nothing real from the repo .env (config loads it with setdefault: "" set here wins)
    if env.is_file():
        for ln in env.read_text(encoding="utf-8").splitlines():
            k = ln.split("=", 1)[0].lstrip("# ").strip()
            if "=" in ln and re.fullmatch(r"[A-Z][A-Z0-9_]*", k) and k != "LODESTAR_HOME":
                os.environ[k] = ""
    sys.path.insert(0, str(ROOT))
    from lodestar import config, db, phone, profile, settings

    assert Path(config.HOME).resolve() == Path(home).resolve(), config.HOME
    profile.write_master("# Pat Rivera\nPat Rivera | Portland, OR | pat.rivera@example.com\n\n## Summary\n"
                         "Data engineer building pipelines.\n\n## Skills\nPython, SQL, Airflow\n")
    for company, title in (("Northwind Analytics", "Senior Data Engineer"), ("Bluefin Labs", "Analytics Engineer")):
        db.add_job(company, title, f"https://jobs.example.com/{company.split()[0].lower()}", f"{title}. Python, SQL.",
                   "via android e2e seed")
    settings.set_pref("phone_access", True)  # what Setup > Phone access > Turn on does (web.py /api/phone/on)
    st = phone.start()
    return phone, st


def phone_session(url: str, code: str) -> str:
    """Pair a second 'phone' over HTTP like the pairing page does; its session cookie."""
    u = urllib.parse.urlsplit(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    c.request("POST", "/phone", urllib.parse.urlencode({"code": code, "label": "e2e probe"}),
              {"Content-Type": "application/x-www-form-urlencoded"})
    r = c.getresponse()
    cookie = (r.getheader("Set-Cookie") or "").split(";")[0]
    c.close()
    if r.status != 303 or not cookie:
        raise AssertionError(f"pairing over HTTP answered {r.status}")
    return cookie


def get(url: str, path: str, cookie: str = "") -> tuple[int, str]:
    u = urllib.parse.urlsplit(url)
    c = http.client.HTTPConnection(u.hostname, u.port, timeout=10)
    c.request("GET", path, headers={"Cookie": cookie} if cookie else {})
    r = c.getresponse()
    body = r.read().decode("utf-8", "replace")
    c.close()
    return r.status, body


# ----------------------------------------------------------------------------- the checks
def scenario(dev: Device, phone, base: str, results: list, timings: dict) -> None:
    def check(name, fn):
        t0 = time.monotonic()
        try:
            detail = fn() or ""
        except BaseException as e:
            results.append((name, "FAIL", f"{type(e).__name__}: {e}"))
            raise
        timings[name] = round(time.monotonic() - t0, 1)
        results.append((name, "PASS", detail))

    host = urllib.parse.urlsplit(base).netloc

    def install():
        p = dev("install", "-r", APK, timeout=180)
        if "Success" not in p.stdout:
            raise AssertionError((p.stdout + p.stderr).strip()[-500:])
        dev.sh("pm", "clear", PKG)  # a fresh app: no saved address, no pairing cookie
        dev.launch()
        dev.wait_for(text="Connect to Lodestar")
        return f"versionCode {dev.version_code()}"

    def addr_field():
        return dev.wait_for(cls="android.widget.EditText")

    def refuse():
        dev.tap(addr_field())
        dev.type("8.8.8.8:8780")
        dev.tap(dev.wait_for(text="Connect"))
        dev.wait_for(text="not an address on your own network", contains=True)
        return "8.8.8.8 refused on the setup screen"

    def pair():
        f = addr_field()
        dev.tap(f)
        dev.sh("input", "keyevent", "KEYCODE_MOVE_END")
        dev.sh("input", "keyevent", "--longpress", *(["KEYCODE_DEL"] * 40))
        dev.type(host)
        dev.tap(dev.wait_for(text="Connect"))
        dev.wait_for(text="Pair this phone", timeout=60)  # the WebView shows the computer's pairing page
        code = phone.new_code()["code"]  # what Setup > Phone access > New pairing code calls
        dev.tap(dev.wait_for(cls="android.widget.EditText"))
        dev.type(code)
        dev.sh("input", "keyevent", "KEYCODE_ENTER")  # submits the form
        dev.wait_for(text="Today", timeout=90)
        n = len(phone.status()["phones"])
        if n != 1:
            raise AssertionError(f"{n} phones paired on the computer, expected 1")
        return f"paired with {host}; Today loaded in the WebView"

    def persist():
        dev.sh("am", "force-stop", PKG)
        dev.launch()
        dev.wait_for(text="Today", timeout=90)
        if find(dev.nodes(), text="Pair this phone"):
            raise AssertionError("the pairing page came back after a relaunch")
        return "force-stop + relaunch: still paired"

    def deny():
        cookie = phone_session(base, phone.new_code()["code"])
        status, body = get(base, "/api/keys", cookie)
        if status != 403 or "not available from a phone" not in body:
            raise AssertionError(f"/api/keys answered {status}: {body[:200]}")
        status, _ = get(base, "/api/keys")
        if status != 401:
            raise AssertionError(f"unpaired /api/keys answered {status}")
        return "/api/keys -> 403 for a paired phone, 401 unpaired"

    def update():
        mine = dev.version_code()
        d = Path(tempfile.mkdtemp(prefix="lodestar-apk-"))
        shutil.copy2(APK, d / "lodestar.apk")
        (d / "lodestar.version.json").write_text(f'{{"code": {mine + 1}, "name": "e2e-newer"}}', encoding="utf-8")
        old = phone.APP_DIR
        phone.APP_DIR = d
        try:
            status, body = get(base, "/phone/app.json")
            if status != 200 or f'"code": {mine + 1}' not in body:
                raise AssertionError(f"/phone/app.json answered {status}: {body[:200]}")
            dev.sh("am", "force-stop", PKG)
            dev.launch()  # the app checks the computer once per launch
            dev.wait_for(text="Update Lodestar", timeout=90)
            dev.wait_for(text="e2e-newer", contains=True)
            dev.tap(dev.wait_for(text="Later"))
        finally:
            phone.APP_DIR = old
            shutil.rmtree(d, ignore_errors=True)
        return f"installed {mine}, computer offers {mine + 1}: Update dialog shown"

    for name, fn in (("install", install), ("refuse", refuse), ("pair", pair), ("persist", persist),
                     ("deny", deny), ("update", update)):
        check(name, fn)


def save_artifacts(dev: Device | None) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if dev is None:
        return
    try:
        (ARTIFACTS / "screen.png").write_bytes(dev("exec-out", "screencap", "-p", binary=True, timeout=30).stdout)
        dev.nodes()
        (ARTIFACTS / "ui.xml").write_text(getattr(dev, "last_xml", ""), encoding="utf-8")
        (ARTIFACTS / "logcat.txt").write_text(dev("logcat", "-d", "-t", "3000", timeout=60).stdout, encoding="utf-8")
    except (subprocess.SubprocessError, OSError) as e:
        print(f"(could not save every artifact: {e})")


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    sdk, avd = sdk_dir(), os.environ.get("LODESTAR_AVD", "lodestar_test")
    if why := skip_reason(sdk, avd, avd_home()):
        print(f"SKIPPED: {why}\n\nandroid e2e: SKIPPED ({why})")
        return 0
    adb = sdk / "platform-tools" / exe("adb")
    results, timings, dev, proc, ok = [], {}, None, None, False
    home = Path(tempfile.mkdtemp(prefix="lodestar-android-e2e-"))
    try:
        if apk_stale(APK, [ANDROID / "app" / "src" / "main", ANDROID / "app" / "build.gradle.kts"]):
            timings["build"] = round(build_apk(), 1)
        dev, proc, secs = boot(sdk, adb, avd)
        timings["boot"] = round(secs, 1)
        results.append(("emulator", "PASS", f"{dev.serial} {'booted' if proc else 'reused'}"))
        phone, st = start_lodestar(home)
        base = st["url"].rsplit("/phone", 1)[0]
        results.append(("lodestar", "PASS", f"phone listener {', '.join(st['urls'])}"))
        scenario(dev, phone, base, results, timings)
        ok = True
    except BaseException as e:  # noqa: BLE001  (every failure is reported, artifacts saved)
        if not results or results[-1][1] != "FAIL":
            results.append(("setup", "FAIL", f"{type(e).__name__}: {e}"))
        save_artifacts(dev)
    finally:
        if "lodestar.phone" in sys.modules:
            sys.modules["lodestar.phone"].stop()
            from lodestar import db
            db.release()
        if proc is not None:
            stop_emulator(dev, proc)
        run([adb, "kill-server"], 30)  # our own adb server (ENV's port): nothing keeps running after the test
        shutil.rmtree(home, ignore_errors=True)
    print("\nandroid e2e:")
    for name, status, detail in results:
        print(f"  {status:<5} {name:<9} {detail}")
    print("timings (s): " + ", ".join(f"{k} {v}" for k, v in timings.items()))
    print(f"android e2e: {'PASS' if ok else 'FAIL (artifacts in ' + str(ARTIFACTS) + ')'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
