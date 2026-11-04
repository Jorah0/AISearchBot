"""One rotating log file for everything: ~/.lodestar/lodestar.log (2 MB x 3). Call setup() once per process."""
import logging
from logging.handlers import RotatingFileHandler

from .config import HOME

_done = False


def setup(level: int = logging.INFO) -> logging.Logger:
    global _done
    root = logging.getLogger("lodestar")
    if not _done:
        h = RotatingFileHandler(HOME / "lodestar.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(h)
        root.setLevel(level)
        _done = True
    return root


def get(name: str) -> logging.Logger:
    return setup().getChild(name)
