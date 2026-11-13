"""The occupation ontology (blueprint section 5): the bundled O*NET database (data/onet.json.gz, built by
scripts/build_onet.py; CC BY 4.0, credit in meta()). Read-only, offline, versioned: careers.py names meta()["version"]
on every suggestion. A title maps to occupations by O*NET's own title lists; nothing here is AI."""
import gzip
import json
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "onet.json.gz"
ZONE_PREP = {1: "little or no preparation", 2: "some preparation: usually a high school diploma",
             3: "medium preparation: vocational training, on-the-job experience or an associate's degree",
             4: "considerable preparation: usually a bachelor's degree and several years of experience",
             5: "extensive preparation: usually a graduate degree and extensive experience"}


@lru_cache(maxsize=4)
def _read(path: str, mtime: float) -> dict:
    from .web_monitor import norm_title

    try:
        data = json.loads(gzip.decompress(Path(path).read_bytes()))
        occ = data["occ"]
    except (OSError, ValueError, KeyError, EOFError) as e:
        raise SystemExit(f"occupation data missing or unreadable: {path} ({e.__class__.__name__}); reinstall Lodestar "
                         "or run scripts/build_onet.py") from None
    index: dict[str, set] = {}
    for code, o in occ.items():
        for t in [o.get("title") or ""] + list(o.get("titles") or []):
            if n := norm_title(t):
                index.setdefault(n, set()).add(code)
    return {"meta": data.get("meta") or {}, "occ": occ, "index": index}


def load() -> dict:
    """{"meta", "occ": {code: occupation}, "index": {normalised title: codes}}, cached until the file changes."""
    try:
        mtime = DATA.stat().st_mtime
    except OSError:
        raise SystemExit(f"occupation data missing or unreadable: {DATA}; reinstall Lodestar or run "
                         "scripts/build_onet.py") from None
    return _read(str(DATA), mtime)


def meta() -> dict:
    return load()["meta"]


def get(code: str) -> dict | None:
    return load()["occ"].get(code)


def related(code: str) -> list[str]:
    return list((get(code) or {}).get("related") or [])


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", s) if len(w) >= 3}


def match_title(title: str, n: int = 5) -> list[tuple[str, float]]:
    """Occupations whose O*NET titles name this title: an exact normalised title scores 1.0, else word overlap
    (Jaccard over words of 3+ letters) of at least 0.5. Best first; [] when nothing is close (never a guess)."""
    from .web_monitor import norm_title

    d, t = load(), norm_title(title)
    if not t:
        return []
    best: dict[str, float] = {c: 1.0 for c in d["index"].get(t, ())}
    want = _words(t)
    if want:
        for name, codes in d["index"].items():
            have = _words(name)
            s = len(want & have) / len(want | have) if have else 0.0
            if s >= 0.5:
                for c in codes:
                    best[c] = max(best.get(c, 0.0), round(s, 3))
    return sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
