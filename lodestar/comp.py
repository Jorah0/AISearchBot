"""Your own market-rate table: ~/.lodestar/comp.json  {"<title keyword>": {"<city or *>": [low, high]}} (annual).
Lodestar never guesses pay; it uses figures stated in postings plus what you record here."""
import json

from .config import HOME

PATH = HOME / "comp.json"


def load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8")) if PATH.is_file() else {}


def _save(data: dict) -> None:
    PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_range(title: str, city: str, low: int, high: int) -> None:
    t, low, high = (title or "").strip().lower(), int(low), int(high)
    if not t:  # an empty keyword is contained in every title and would answer for all of them
        raise ValueError("a title keyword is required")
    if low > high:
        raise ValueError("low must not exceed high")
    data = load()
    data.setdefault(t, {})[(city or "*").strip().lower()] = [low, high]
    _save(data)


def delete(title: str, city: str = "*") -> bool:
    data, t, c = load(), (title or "").strip().lower(), (city or "*").strip().lower()
    if c not in data.get(t, {}):
        return False
    del data[t][c]
    if not data[t]:
        del data[t]
    _save(data)
    return True


def lookup(title: str, text: str = "") -> dict | None:
    """Best entry for a job: the longest title keyword contained in the title, then a city mentioned in the text, else '*'."""
    data, t, body = load(), (title or "").lower(), (text or "").lower()
    keys = sorted((k for k in data if k in t), key=len, reverse=True)
    if not keys:
        return None
    cities = data[keys[0]]
    city = next((c for c in cities if c != "*" and c in body), "*" if "*" in cities else None)
    if city is None:
        return None
    low, high = cities[city]
    return {"title": keys[0], "city": city, "low": low, "high": high}


# ----------------------------------------------------------------------------- offers
def total(o: dict) -> dict:
    """Pure: an offer's money by year from its structured fields (db.OFFER_FIELDS; missing = 0). Equity vests evenly by
    month after the cliff, at the value you estimated, no growth; match is a share of base. Only base and sign-on are
    certain: 'estimates' names every assumption behind the other figures."""
    def n(k):
        return float(o.get(k) or 0)

    base, sign, grant = n("base"), n("sign_on"), n("equity_value_estimate")
    bonus, match = base * n("bonus_pct") / 100, base * n("retirement_match_pct") / 100
    years, cliff = int(o.get("vest_years") or 4), int(o.get("cliff_months") or 0)
    months = years * 12

    def vested(m):
        return 0.0 if m < cliff else grant * min(m, months) / months

    equity = [round(vested(12 * (y + 1)) - vested(12 * y)) for y in range(4)]
    est = [x for x, on in (("bonus at its target percentage", bonus), ("retirement match if you contribute enough", match),
                           ("equity at your estimated grant value, no growth", grant),
                           ("4-year vesting (none stated)", grant and not o.get("vest_years")),
                           ("no cliff (none stated)", grant and o.get("cliff_months") is None)) if on]
    r = round
    return {"base": r(base), "bonus": r(bonus), "sign_on": r(sign), "match": r(match), "equity_by_year": equity,
            "year1_cash": r(base + bonus + sign), "year1_total": r(base + bonus + sign + match + equity[0]),
            "four_year_cash": r(4 * (base + bonus) + sign), "four_year_total": r(4 * (base + bonus + match) + sign + sum(equity)),
            "estimates": est}


COMPARE = ("base", "bonus", "sign_on", "match", "equity_year1", "year1_cash", "year1_total", "four_year_total")  # higher = better


def compare() -> dict:
    """Live offers (status offer / accepted) side by side: totals, the best value per row, your recorded market range,
    and the gap to your private salary floor. For Lodestar's own views only: the floor never leaves them."""
    from . import db
    from .profile import salary_floor

    floor, rows = salary_floor(), []
    for j in db.list_jobs():
        if j["status"] not in ("offer", "accepted"):
            continue
        o = db.get_offer(j["id"]) or {}
        t = total(o)
        t["equity_year1"] = t["equity_by_year"][0]
        m, base = lookup(j["title"], j["jd"] or ""), t["base"]
        if m and base:
            m["delta"] = base - m["low"] if base < m["low"] else base - m["high"] if base > m["high"] else 0
        rows.append({"job_id": j["id"], "company": j["company"], "title": j["title"], "status": j["status"], "offer": o,
                     "total": t, "market": m, "vs_floor": base - floor if floor and base else None})
    best = {}
    for k in COMPARE:
        top = max((r["total"][k] for r in rows), default=0)
        if len(rows) > 1 and top > 0:
            best[k] = [r["job_id"] for r in rows if r["total"][k] == top]
    return {"offers": rows, "best": best, "floor": floor}
