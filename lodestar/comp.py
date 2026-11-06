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
