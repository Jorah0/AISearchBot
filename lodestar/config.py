"""Paths and settings. Settings resolve: env var -> .env files -> keyring vault -> default."""
import os
from pathlib import Path

HOME = Path(os.environ.get("LODESTAR_HOME") or os.environ.get("JOBBOT_HOME") or Path.home() / ".lodestar")
_legacy = Path.home() / ".jobbot"
if not HOME.exists() and _legacy.is_dir() and HOME == Path.home() / ".lodestar":
    import shutil as _shutil

    try:  # one-time migration from the pre-rename data folder; copy, then drop the old folder if nothing holds it
        _shutil.copytree(_legacy, HOME)
        _shutil.rmtree(_legacy, ignore_errors=True)
    except OSError as _e:
        _shutil.rmtree(HOME, ignore_errors=True)
        HOME = _legacy
        import sys as _sys

        _sys.stderr.write("[lodestar] could not migrate ~/.jobbot to ~/.lodestar (" + str(_e.strerror) + "); using the "
                          "old folder for now." + chr(10))
HOME.mkdir(parents=True, exist_ok=True)
DB_PATH = HOME / "lodestar.db"
if (HOME / "jobbot.db").exists() and not DB_PATH.exists():
    (HOME / "jobbot.db").rename(DB_PATH)  # migrated data keeps its old file name until first run
PROFILE = HOME / "profile.md"
APPS_DIR = HOME / "applications"
SNAPSHOTS = HOME / "snapshots"
ALERTS = HOME / "alerts.log"


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


_load_dotenv(Path.cwd() / ".env")
# the install folder's .env (install.ps1 / install.sh create it there): a scheduled task or cron job starts in system32
# or $HOME, so cwd alone would miss it. ponytail: a site-packages install looks for site-packages/.env, harmlessly
_load_dotenv(Path(__file__).resolve().parent.parent / ".env")
_load_dotenv(HOME / ".env")


FULL_AI = __import__("threading").local()  # advisor.auto sets .on while Full AI writes (this thread only)


def full_ai_check(what: str) -> None:
    """Called first by every path that sends, submits, moves or adds a job, proposes or approves an action, or writes
    settings or the vault: refused while Full AI (advisor.auto) is applying changes on this thread."""
    if getattr(FULL_AI, "on", False):
        raise SystemExit(f"Full AI never {what}: that stays your click")


def setting(name: str, default=None):
    """Non-secret or secret setting. Checks env first, then the vault."""
    val = os.environ.get(name)
    if val:
        return val
    from . import vault  # lazy: keyring import is slow

    val = vault.get(name)
    return val if val else default
