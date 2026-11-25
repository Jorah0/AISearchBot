"""The local job model (pass 46): an Ollama model Lodestar builds for you ('lodestar-jobs') from a general base model,
carrying what a job-search assistant needs on every local call: your employer-safe profile, your preferences with the
salary floor withheld, and what you pursued and passed on (learned from your decisions). It is rebuilt when any of
that changes (the loop's 'job model' step, at most daily) and, once built, is the Ollama model Lodestar uses
(ai.model_for, pref jobmodel). Everything stays on this machine: the model lives in your Ollama.

What it learns from (decisions): jobs you moved to applied or beyond (interviews and offers weigh most) are pursued;
Inbox auto-track proposals you rejected and jobs you withdrew are passed on. Every fourth decision is held out of the
model so evaluate() can score it on decisions it never saw (pairwise: does it rank a pursued job above a passed one?).

The knowledge goes in as the model's message history (Modelfile MESSAGE), not its SYSTEM prompt: Ollama replaces a
model's system prompt whenever a request sends its own, and Lodestar's calls do; the message history stays.
ponytail: examples are a few-shot memory, not fine-tuning; enough to steer a 3-8B model's ranking and tone."""
import hashlib
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import ai, db, log, settings

NAME = "lodestar-jobs"
KEY = "jobmodel"  # meta: {base, fp, built_at, examples, held}
EVAL_KEY = "jobmodel:eval"
MAX_EXAMPLES = 10
PURSUED = ("applied", "screening", "interview", "offer", "accepted")
STRONG = ("interview", "offer", "accepted")


def _meta(key: str) -> dict | None:
    row = db.con().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    try:
        v = json.loads(row["value"]) if row and isinstance(row["value"], str) else None
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def _set_meta(key: str, value: dict | None) -> None:
    if value is None:
        db.con().execute("DELETE FROM meta WHERE key=?", (key,))
    else:
        db.con().execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, json.dumps(value)))
    db.con().commit()


def _utc() -> str:  # stored UTC, as every other timestamp the page shows (localTs)
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def built() -> dict | None:
    """The build record while the model is built (and not dropped), else None."""
    return _meta(KEY)


def forget() -> None:
    """The model is gone (Ollama rejected it): Lodestar goes back to the base model until the next build."""
    _set_meta(KEY, None)


# ----------------------------------------------------------------------------- what it learns from
def _snippet(text, n: int = 200) -> str:
    return " ".join(str(text or "").split())[:n]


def decisions() -> list[dict]:
    """Your decisions, oldest first: {id, label: pursued | passed, strength: 2 interview/offer, 1 otherwise, title,
    company, location, jd}. Jobs past saved are pursued; rejected auto-track proposals and withdrawn jobs are passed."""
    out = []
    for j in db.con().execute("SELECT id, title, company, location, jd, status FROM jobs WHERE status IN (%s) ORDER BY id"
                              % ",".join("?" * (len(PURSUED) + 1)), (*PURSUED, "withdrawn")).fetchall():
        out.append({"id": f"job:{j['id']}", "label": "passed" if j["status"] == "withdrawn" else "pursued",
                    "strength": 2 if j["status"] in STRONG else 1, "title": j["title"], "company": j["company"],
                    "location": j["location"] or "", "jd": j["jd"] or ""})
    for p in db.con().execute("SELECT id, payload FROM pending WHERE tool='auto_track' AND kind='add_job' AND "
                              "status='rejected' ORDER BY id").fetchall():
        try:
            d = json.loads(p["payload"] or "{}")
        except ValueError:
            continue
        if d.get("title"):
            out.append({"id": f"proposal:{p['id']}", "label": "passed", "strength": 1, "title": str(d["title"]),
                        "company": str(d.get("company") or ""), "location": str(d.get("location") or ""),
                        "jd": str(d.get("jd") or "")})
    return out


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(learned, held out): every fourth decision is held out for evaluate(); the model learns the newest of the rest."""
    held = [r for i, r in enumerate(rows) if i % 4 == 3]
    learn = [r for i, r in enumerate(rows) if i % 4 != 3]
    return learn[-MAX_EXAMPLES:], held


PLAYBOOK = Path(__file__).with_name("data") / "playbook.json"


def playbook() -> list[dict]:
    """The evidence-graded strategies (data/playbook.json): {id, grade, do, effect, source, url}."""
    return json.loads(PLAYBOOK.read_text(encoding="utf-8"))["strategies"]


def _playbook_text() -> str:
    """What the model learns from the playbook: strong and moderate findings as advice (with their evidence), myths as
    claims to correct; weak ones (surveys, vendor blogs) are left out, so the model never states them as fact."""
    rows = playbook()
    advice = [f"- {r['do']} ({r['grade']} evidence: {r['effect']}; {r['source']})"
              for r in rows if r["grade"] in ("strong", "moderate")]
    myths = [f"- {r['do']}" for r in rows if r["grade"] == "myth"]
    return ("PROVEN JOB-SEARCH METHODS (apply them; name the evidence when it helps):\n" + "\n".join(advice)
            + "\n\nMYTHS TO CORRECT (never repeat them as fact):\n" + "\n".join(myths))


def messages() -> list[dict]:
    """The model's built-in message history: your background (never the salary floor, private answers, EEO or
    readiness) and the decisions it learns from."""
    from .profile import preferences_text, redact_floor
    from .resume import candidate_text

    try:
        cand = candidate_text(3000, private=False)
    except SystemExit:  # the starter template: nothing to learn from yet
        cand = ""
    prefs = _snippet(redact_floor(preferences_text()), 800)
    learn, _ = split(decisions())
    lines = [f"- {'Pursued' if r['label'] == 'pursued' else 'Passed on'}{' (got an interview)' if r['strength'] > 1 else ''}"
             f": {_snippet(r['title'], 80)} @ {_snippet(r['company'], 60)} ({_snippet(r['location'], 40) or 'place not stated'})"
             f" - {_snippet(r['jd'])}" for r in learn]
    background = ("Background for every task in this conversation. You assist one job seeker with searching, judging "
                  "fit and applying. Never invent facts about them: use only this background and what a task gives you.\n\n"
                  f"THEIR PROFILE (as employers may see it):\n{cand or '(not filled in yet)'}\n\n"
                  f"THEIR PREFERENCES (pay figures withheld):\n{prefs or '(none stated)'}\n\n"
                  "JOBS THEY PURSUED OR PASSED ON (learn their taste from these; never quote them to an employer):\n"
                  + ("\n".join(lines) or "(no decisions yet)") + "\n\n" + _playbook_text())
    try:  # pass 59: examples you accepted under Model lab > Learning (taught by a premium AI, labelled by you)
        from .teacher import few_shot

        shots = few_shot()
    except Exception:
        shots = []
    return [{"role": "user", "content": background},
            {"role": "assistant", "content": "Understood. I will use this background, never invent facts about the "
                                             "candidate, and judge fit by what they pursued and passed on."}] + shots


SYSTEM = ("You are Lodestar's local job-search assistant. Be accurate and concise, follow the output format each task "
          "asks for, and never invent facts about the candidate.")


# ----------------------------------------------------------------------------- Ollama
def _base_url() -> str:
    return ai.PROVIDERS["ollama"]["url"].split("/v1/", 1)[0]


urlopen = urllib.request.build_opener(urllib.request.ProxyHandler({})).open  # loopback, never via HTTP_PROXY (the E2E harness swaps it)


def _post(path: str, body: dict, timeout: int = 600) -> dict:
    """POST to the local Ollama API (localhost: not util.fetch, whose SSRF guard refuses loopback by design). No proxy:
    a configured HTTP_PROXY would otherwise receive your profile and decisions."""
    req = urllib.request.Request(_base_url() + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def base() -> str:
    """The general model it is built on: pref jobmodel_base, else the best general model your Ollama offers (code and
    embedding models last), never the job model itself."""
    if b := str(settings.pref("jobmodel_base") or "").strip():
        return b
    models = [m for m in ai.list_models("ollama") if not m.startswith(NAME)]
    b = ai.pick_from("ollama", models)
    if not b:
        raise SystemExit("Ollama has no model to build on: `ollama pull llama3.2` (or qwen3), then build again")
    return b


def build(force: bool = False, tag: str = NAME, base_model: str | None = None, num_ctx: int = 8192) -> dict:
    """Create or update the job model in Ollama; skipped when nothing it carries changed (force: rebuild anyway).
    Pass 59: Model lab builds candidates under another tag (lodestar-jobs:cand-N) from the selection's base and
    context; only the live tag (NAME) is recorded here, a candidate is the lab's record (modellab)."""
    cur = built() if tag == NAME else None
    if cur and cur.get("promoted_from") and not force:  # checked first: no Ollama call for a refusal
        # pass 59: a Model lab release is live under this tag (maybe trained weights): never rebuild it from base()
        return cur | {"changed": False, "note": f"{NAME} is the Model lab release {cur['promoted_from']}: change it "
                                                "there (or roll back); Build now with force rebuilds it from the base"}
    b, msgs = base_model or base(), messages()
    fp = hashlib.sha256(json.dumps([b, SYSTEM, msgs, num_ctx]).encode()).hexdigest()[:16]
    if cur and cur.get("fp") == fp and not force:
        return cur | {"changed": False}
    learn, held = split(decisions())
    try:
        _post("/api/create", {"model": tag, "from": b, "system": SYSTEM, "messages": msgs, "stream": False,
                              "parameters": {"temperature": 0.2, "num_ctx": int(num_ctx)}})
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Ollama refused to build {NAME}: {e.read().decode(errors='replace')[:200]}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SystemExit(f"Ollama is not answering at {_base_url()} ({e}): start Ollama, then build again") from None
    rec = {"base": b, "fp": fp, "built_at": _utc(), "examples": len(learn),
           "held": len(held), "num_ctx": int(num_ctx), "tag": tag}
    if tag == NAME:
        _set_meta(KEY, rec)
    return rec | {"changed": True}


def copy(source: str, destination: str) -> None:
    """Ollama /api/copy (Model lab promote / rollback): the destination tag now points at the source's weights."""
    try:
        _post("/api/copy", {"source": source, "destination": destination}, timeout=120)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Ollama could not copy {source} to {destination}: {e.read().decode(errors='replace')[:200]}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        raise SystemExit(f"Ollama is not answering at {_base_url()} ({e})") from None


def accuracy(model: str) -> dict:
    """One model on the held-out decisions: the share of (pursued, passed) pairs ranked the right way round."""
    _, held = split(decisions())
    pos, neg = [r for r in held if r["label"] == "pursued"], [r for r in held if r["label"] == "passed"]
    if not pos or not neg:
        raise SystemExit(f"not enough held-out decisions to evaluate ({len(pos)} pursued, {len(neg)} passed on; every "
                         "fourth decision is held out): apply to or pass on more jobs first")
    s = _scores(model, pos + neg)
    pairs = [(s.get(p["id"]), s.get(n["id"])) for p in pos for n in neg]
    pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
    acc = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a, b in pairs) / len(pairs) if pairs else None
    return {"accuracy": None if acc is None else round(acc, 2), "scored": len(pairs), "pairs": len(pos) * len(neg)}


def tick() -> dict | None:
    """The loop step: rebuild when what it carries changed, at most once a day; only with pref jobmodel on and Ollama
    configured. Never raises (a cycle must go on)."""
    if not settings.pref("jobmodel") or "ollama" not in ai.available():
        return None
    cur = built()
    if cur and cur.get("promoted_from"):  # a Model lab release is live: the lab owns this tag now
        return None
    if cur and datetime.now(timezone.utc).replace(tzinfo=None) - datetime.fromisoformat(cur["built_at"]) < timedelta(days=1):
        return None
    try:
        return build()
    except (Exception, SystemExit) as e:
        log.get("jobmodel").warning("job model build skipped: %s", e)
        return None


# ----------------------------------------------------------------------------- evaluation
def _scores(model: str, rows: list[dict]) -> dict[str, int]:
    from .web_monitor import rank

    listings = [{"title": r["title"], "company": r["company"], "location": r["location"], "desc": r["jd"][:600],
                 "_id": r["id"]} for r in rows]
    with ai.using(model):
        ranked = rank(listings, "ollama")
    return {j["_id"]: j["score"] for j in ranked if "score" in j}


def evaluate() -> dict:
    """Score the job model and its base on the decisions held out of the model: the share of (pursued, passed) pairs
    each ranks the right way round (0.5 = coin flip). Stored for the Setup card. Needs 1+ of each held out."""
    _, held = split(decisions())
    pos, neg = [r for r in held if r["label"] == "pursued"], [r for r in held if r["label"] == "passed"]
    if not pos or not neg:
        raise SystemExit(f"not enough held-out decisions to evaluate ({len(pos)} pursued, {len(neg)} passed on; every "
                         "fourth decision is held out): apply to or pass on more jobs first")
    cur = built()
    models = [m for m in ((cur or {}).get("base") or base(), NAME if cur else None) if m]
    out = {"at": _utc(), "pairs": len(pos) * len(neg), "models": {}}
    for m in models:
        s = _scores(m, pos + neg)
        pairs = [(s.get(p["id"]), s.get(n["id"])) for p in pos for n in neg]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        acc = sum(1.0 if a > b else 0.5 if a == b else 0.0 for a, b in pairs) / len(pairs) if pairs else None
        out["models"][m] = {"accuracy": None if acc is None else round(acc, 2), "scored": len(pairs)}
    _set_meta(EVAL_KEY, out)
    return out


def status() -> dict:
    """The Setup card and `lodestar jobmodel status`: no network."""
    rows = decisions()
    learn, held = split(rows)
    return {"name": NAME, "on": bool(settings.pref("jobmodel")), "built": built(), "eval": _meta(EVAL_KEY),
            "decisions": {"pursued": sum(r["label"] == "pursued" for r in rows),
                          "passed": sum(r["label"] == "passed" for r in rows), "learned": len(learn), "held": len(held)}}
