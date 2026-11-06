"""JD coverage: which of a posting's keywords a resume mentions. Deterministic and offline (no AI).

A tailoring guide, not an ATS verdict: real applicant-tracking systems parse and rank in their own ways. The lexicon
(data/skills.json) holds hard skills across many fields, certifications, soft skills, degrees, aliases and the weights.
"""
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "skills.json"  # beside the module, like web.STATIC: works inside the PyInstaller exe
NOTE = ("JD coverage is the share of this posting's keywords your resume mentions. It is a guide for tailoring, not a "
        "pass/fail ATS verdict: real systems parse and rank differently. Only add a keyword you can back up.")
OTHER_CAP = 15
STUFF_MIN, STUFF_RATIO = 6, 3  # a JD keyword repeated 6+ times and over 3x as often as the posting uses it reads as stuffing
SENIORITY = {"senior", "sr", "junior", "jr", "lead", "principal", "staff", "head", "chief", "intern", "internship", "trainee",
             "entry", "level", "mid", "i", "ii", "iii", "iv", "v", "1", "2", "3", "remote", "hybrid", "onsite", "contract",
             "temporary", "temp", "full", "part", "time", "fulltime", "parttime"}
CONNECTORS = {"of", "and", "the", "for", "to", "in", "a", "an", "at", "with", "&"}
STOP = set("""a about above across after again against all also am among an and any apply applicants applications are as at
available based be because been before being below benefits best between both but by can candidate candidates career careers
company could day days did do does doing done during each eg either employee employees employer employment equal etc even
ever every excellent experience experienced familiar familiarity few first following for from full further get gets getting
give good great has have having help helping high highly hire hiring how however ideal ie if in include includes including
into is it its job jobs join just know knowledge large like looking make makes making many may more most must need needs new
next no nor not now of off offer offered offering offers on one only open opportunities opportunity or other others our ours
out over own part people per perks plus position positions preferred professional provide provides providing qualification
qualifications qualified related required requirement requirements responsibilities responsibility responsible role roles
salary same see seeking should skill skills so some status strong such take team teams than that the their them then there
these they this those through time to together too top under understanding up upon us using very want was way ways we well
were what when where whether which while who whom why will with within without work working works would year years yet you
your yours youll youre weve were well wed ability able across additional apply around ask based build building company
create creating day deliver delivering demonstrated desire develop developing development drive driving duties ensure
ensuring environment exciting expected expertise focus great grow growing growth help hours impact include individual
industry key lead leading learn level location manage managing meet member members mission must nice operate own part
perform plus proven range related remote help hybrid office onsite opportunity organization passionate play please position
problems product products quality range real role run seeking service services set solution solutions solve start success
successful support supporting systems tasks technical technology tools type understand use users value values world wide
week weekly daily monthly annual annually including within million billion today plus key core""".split())
_B = r"(?<![a-z0-9+#&.])"           # a term starts at a word boundary ("asp.net" holds no ".net", "node.js" no "js")
_E = r"(?![a-z0-9+#&]|\.[a-z0-9])"  # ...and ends at one; a sentence-ending period is fine, "vue.js" continues the token


def norm(s) -> str:
    """Lowercase; curly quotes and apostrophes dropped; hyphens, dashes and slashes become spaces (so "full-stack" and
    "full stack", "ci/cd" and "ci cd" are the same); whitespace collapsed. Terms and texts both go through this."""
    s = str(s or "").lower().replace("’", "").replace("‘", "").replace("'", "")
    return re.sub(r"\s+", " ", re.sub(r"[‐-―/\-]+", " ", s)).strip()


def _rx(variants) -> re.Pattern:
    vs = sorted({norm(v) for v in variants}, key=len, reverse=True)  # longest first: "ms excel" is one hit, not two
    plural = "s?" if all(" " in v for v in vs) else ""  # "rest apis", "user stories"; single words list their plurals
    return re.compile(_B + "(?:" + "|".join(re.escape(v) for v in vs) + ")" + plural + _E)


@lru_cache(maxsize=1)
def lexicon() -> dict:
    """{weights, terms: [(term, kind, level, rx, needles)], canon: {spelling: term}}; level is set for degrees only."""
    d = json.loads(DATA.read_text(encoding="utf-8"))
    kinds = {t: "hard" for g in d["hard"].values() for t in g} | {t: "hard" for t in d["certifications"]}
    kinds |= {t: "soft" for t in d["soft"]}
    levels = {t: lvl for t, lvl in d["degrees"]}
    kinds |= {t: "education" for t in levels}
    variants: dict[str, list[str]] = {t: [t] for t in kinds}
    for alias, t in d["aliases"].items():
        variants[t].append(alias)  # a KeyError here means skills.json maps an alias to an unknown term
    terms = [(t, k, levels.get(t), _rx(variants[t]), tuple({norm(v) for v in variants[t]})) for t, k in kinds.items()]
    return {"weights": d["weights"], "terms": terms, "canon": {norm(v): t for t, vs in variants.items() for v in vs}}


def canonical(term) -> str:
    """The lexicon's name for a term typed any known way ('k8s' -> 'kubernetes'); anything else comes back normalised."""
    return lexicon()["canon"].get(norm(term), norm(term))


def spans(term, text) -> list[tuple[int, int]]:
    """Where `text` names `term` in any known spelling, as offsets into `text` itself (for highlighting). Only a
    length-preserving clean-up runs first, so the offsets stay valid; collapse whitespace beforehand if needed."""
    t, name = re.sub(r"[‐-―/\-]", " ", str(text or "").lower()), canonical(term)
    rx = next((x[3] for x in lexicon()["terms"] if x[0] == name), None) or _rx([name])
    return [m.span() for m in rx.finditer(t)]


def mentions(term, text) -> bool:
    """True when `text` names `term` in any known spelling ('k8s' counts for kubernetes)."""
    return bool(spans(term, norm(text)))


def claims_in(text) -> set[str]:
    """Lexicon terms `text` names that are checkable claims: hard skills, certifications, degrees (not soft skills)."""
    t = norm(text)
    return {x[0] for x in lexicon()["terms"] if x[1] != "soft" and _spans(x[3], x[4], t)}


def _spans(rx, needles, text) -> list[tuple[int, int]]:
    return [m.span() for m in rx.finditer(text)] if any(n in text for n in needles) else []  # substring test first: fast


def _count(phrase: str, text: str) -> int:
    return len(_rx([phrase]).findall(text))


def core_title(title) -> str:
    """'Senior Data Engineer II (Remote) - Payments' -> 'data engineer'."""
    t = re.split(r"\s[-|,]\s|\s[–—]\s|,|\|", re.sub(r"\(.*?\)|\[.*?\]", " ", str(title or "")))[0]
    return " ".join(w for w in (x.rstrip(".") for x in norm(t).split()) if w and w not in SENIORITY)


def _other(jd: str, covered: list[tuple[int, int]], exclude: set[str], title_words: set[str]) -> Counter:
    """Phrases of 1-3 words the posting repeats (2+ times) that the lexicon does not know: no stopwords, nothing already
    matched as a lexicon term, nothing from the company name, nothing made only of job-title words (the title is scored apart). A phrase is dropped when a longer one with the same count
    holds it ("data platform" x3 makes "platform" x3 redundant)."""
    grams: Counter = Counter()
    run: list[str | None] = []
    prev_end = 0

    def flush():
        for n in (1, 2, 3):
            for i in range(len(run) - n + 1):
                g = run[i:i + n]
                if all(g) and (n > 1 or len(g[0]) >= 4):
                    grams[" ".join(g)] += 1

    for m in re.finditer(r"[a-z][a-z0-9+#&]*", jd):
        if run and jd[prev_end:m.start()].strip():  # punctuation or a bullet between words ends a phrase
            flush(); run = []
        w, s, e = m.group(), m.start(), m.end()
        lexical = any(a < e and s < b for a, b in covered)
        run.append(None if lexical or w in STOP or w in exclude or len(w) < 3 else w)
        prev_end = e
    flush()
    keep = {g: n for g, n in grams.items() if n >= 2 and not set(g.split()) <= title_words}
    keep = {g: n for g, n in keep.items()
            if not any(len(h) > len(g) and n == m and re.search(rf"(?<!\S){re.escape(g)}(?!\S)", h) for h, m in keep.items())}
    return Counter(dict(sorted(keep.items(), key=lambda x: (-x[1], -len(x[0]), x[0]))[:OTHER_CAP]))


def _cat(matched: int, total: int) -> dict:
    return {"score": round(100 * matched / total) if total else 0, "matched": matched, "total": total}


def match(resume_text, jd, job_title=None, skip=(), company=None) -> dict:
    """Score how much of the posting the resume covers, 0-100, by category (hard, soft, title, education, other).
    skip: terms the user marked as not theirs; they stay listed but leave every denominator. company: kept out of the
    'other' phrases (a posting names its company over and over)."""
    lex, r, j = lexicon(), norm(resume_text), norm(jd)
    skip = {norm(s) for s in skip or ()}
    kws, covered, req, have = [], [], {}, set()
    for term, kind, level, rx, needles in lex["terms"]:
        js = _spans(rx, needles, j)
        covered += js
        if kind == "education":
            if js:
                req[term] = level
            if _spans(rx, needles, r):
                have.add(level)
        elif js:
            kws.append({"term": term, "kind": kind, "jd_count": len(js), "resume_count": len(_spans(rx, needles, r))})
    title = core_title(job_title)
    words = [w for w in title.split() if w not in CONNECTORS]
    exclude = set(norm(company).split()) - STOP if company else set()
    kws += [{"term": g, "kind": "other", "jd_count": n, "resume_count": _count(g, r)}
            for g, n in _other(j, covered, exclude, set(words)).items()]
    for k in kws:
        k["matched"], k["skipped"] = k["resume_count"] > 0, norm(k["term"]) in skip
    cats = {}
    for kind in ("hard", "soft", "other"):
        live = [k for k in kws if k["kind"] == kind and not k["skipped"]]
        cats[kind] = _cat(sum(k["matched"] for k in live), len(live))
    title_found = False
    if words:
        title_found = _count(title, r) > 0
        got = sum(_count(w, r) > 0 for w in words)
        cats["title"] = {"score": 100 if title_found else round(50 * got / len(words)), "matched": len(words) if title_found else got,
                         "total": len(words)}
    else:
        cats["title"] = _cat(0, 0)
    ok = bool(req) and bool(have) and max(have) >= min(req.values())  # a master's covers a posting that asks for a bachelor's
    cats["education"] = _cat(int(ok), 1) if req else _cat(0, 0)
    live = {k: w for k, w in lex["weights"].items() if cats[k]["total"]}  # empty categories hand their weight to the rest
    score = round(sum(cats[k]["score"] * w for k, w in live.items()) / sum(live.values())) if live else 0
    kws.sort(key=lambda k: (-k["jd_count"], k["kind"] == "other", k["term"]))
    return {"score": score, "categories": cats, "keywords": kws,
            "title_match": {"title": title, "found": title_found} if words else None,
            "education_required": sorted(req, key=req.get),
            "stuffing": [k["term"] for k in kws if k["resume_count"] >= STUFF_MIN and k["resume_count"] > STUFF_RATIO * k["jd_count"]],
            "note": NOTE}
