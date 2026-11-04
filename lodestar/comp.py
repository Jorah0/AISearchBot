"""Your own market-rate table: ~/.lodestar/comp.json  {"<title keyword>": {"<city or *>": [low, high]}} (annual).
Lodestar never guesses pay; it uses figures stated in postings plus what you record here."""
import json

from .config import HOME

PATH = HOME / "comp.json"


def load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8")) if PATH.is_file() else {}


def set_range(title: str, city: str, low: int, high: int) -> None:
    data = load()
    data.setdefault(title.strip().lower(), {})[(city or "*").strip().lower()] = [int(low), int(high)]
    PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


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
