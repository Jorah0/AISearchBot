"""The Board's map (pass 53): offline place lookup (data/places.json.gz, built by scripts/build_places.py from the U.S.
Census Bureau's Gazetteer, public domain) and miles from your home place. No network, no geocoding service.
ponytail: US cities and ZIP codes only; another country's places stay "not placed" (add its gazetteer if needed)."""
import gzip
import json
import math
import re
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "places.json.gz"
REMOTE = re.compile(r"\b(remote|anywhere|work from home|wfh)\b", re.I)


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads(gzip.decompress(DATA.read_bytes()))


def locate(text) -> tuple[float, float, str] | None:
    """'Austin, TX', 'Austin, Texas', 'Portland, OR (hybrid)' or a 5-digit ZIP -> (lat, lon, label); else None."""
    from .web_monitor import STATES

    s = " ".join(str(text or "").split())
    if not s or (REMOTE.search(s) and "," not in s):
        return None
    d = _data()
    if m := re.search(r"\b(\d{5})(?:-\d{4})?\b", s):
        if hit := d["z"].get(m[1]):
            return hit[0], hit[1], m[1]
    names = {v: k for k, v in STATES.items()}
    for part in re.split(r"\s*[;|/]\s*|\s+or\s+", s):
        m = re.match(r"\s*([A-Za-z .'-]+?)\s*,\s*([A-Za-z .]+?)\b(?:\s*\d{5})?(?:\s*[,(].*)?$", part)
        if not m:
            continue
        city, st = m[1].strip().lower(), m[2].strip().lower()
        st = st if st in STATES else names.get(st, "")
        city = re.sub(r"^(st|ft|mt)\.?\s", lambda x: {"st": "st. ", "ft": "fort ", "mt": "mount "}[x[1]], city)
        for c in (city, city.replace("st. ", "saint "), city.replace(".", "")):
            if st and (hit := d["p"].get(f"{c}|{st}")):
                return hit[0], hit[1], f"{m[1].strip()}, {st.upper()}"
    return None


def miles(a, b) -> float:
    """Great-circle miles between two (lat, lon) points."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def board_map() -> dict:
    """Open jobs placed on a map with miles from home (the Jobs tab's search profile place), remote ones listed apart.
    Candidate-only: never in employer text or prompts."""
    from . import db
    from .web_monitor import defaults

    try:
        here = locate(defaults().get("location") or "")
    except (Exception, SystemExit):  # a template profile: no home, the map still shows the jobs
        here = None
    out = {"home": {"lat": here[0], "lon": here[1], "label": here[2]} if here else None, "jobs": [], "remote": [],
           "unplaced": [], "source": _data()["source"]}
    for j in db.list_jobs():
        if j["status"] in ("rejected", "withdrawn"):
            continue
        row = {"id": j["id"], "company": j["company"], "title": j["title"], "status": j["status"], "place": j["location"] or ""}
        if (hit := locate(j["location"])) is not None:
            out["jobs"].append(row | {"lat": hit[0], "lon": hit[1], "miles": round(miles(here, hit)) if here else None})
        elif REMOTE.search(row["place"]):
            out["remote"].append(row)
        else:
            out["unplaced"].append(row)
    out["jobs"].sort(key=lambda r: (r["miles"] is None, r["miles"] or 0))
    return out
