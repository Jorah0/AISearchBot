"""Idea crafting: diverge (every provider brainstorms), critique, converge (merge, score, rank), refine, track.

Grounded in your real data: profile, tracker stats, resume-variant outcomes, gap verdicts, preferences. Ideas are
saved with a status so they turn into a plan instead of a chat transcript.
"""
import json
from datetime import datetime

from . import ai, db, settings
from .config import APPS_DIR
from .resume import candidate_text
from .util import slug

TOPICS = {
    "strategy": "a job-search strategy for the next two weeks: where to apply, how many, which channels, what to stop doing",
    "resume": "positioning angles, headline and summary variants that make the candidate obviously right for the target role",
    "gap": "projects, certifications, or deliberate practice that close the biggest skill gaps for the target role, fastest first",
    "outreach": "angles, openers and warm-path tactics for reaching hiring managers and employees at target companies",
    "stories": "STAR interview stories mined from the candidate's actual experience, each tied to a competency interviewers probe",
    "pivot": "adjacent roles, titles and industries the candidate already qualifies for, with the reframing each needs",
    "questions": "sharp questions to ask interviewers that signal seniority and surface red flags",
    "negotiation": "levers, asks and scripts for negotiating the next offer given the candidate's position",
    "tools": "automation, tooling or habits that would most improve this specific candidate's search (be concrete, not generic)",
    "custom": "whatever the user asks for",
}

IDEA_SCHEMA = ('[{"title": "short name", "idea": "2-4 sentences", "why_it_works": "evidence or reasoning", '
               '"effort": 1-5, "impact": 1-5, "first_step": "one concrete action"}]')


def context(job=None, role: str = "") -> str:
    st = db.stats()
    gaps = []
    for j in db.list_jobs()[:30]:
        g = APPS_DIR / f"{j['id']}-{slug(j['company'])}-{slug(j['title'])}" / "gap.json"
        if g.is_file():
            try:
                d = json.loads(g.read_text(encoding="utf-8"))
                gaps.append(f"{j['company']} {j['title']}: score {d.get('match_score')} {d.get('verdict')} "
                            f"missing {', '.join(d.get('missing_keywords', [])[:5])}")
            except Exception:
                pass
    variants = db.variant_stats()
    prefs = settings.load()["prefs"]
    parts = [
        f"TRACKER: {st['counts']} | applied {st['applied_total']} | response {st['response_rate']:.0%} | interview {st['interview_rate']:.0%}",
        "RESUME VARIANT OUTCOMES: " + ("; ".join(f"{v['variant']} sent {v['applied']} interview {v['interview_rate']:.0%}" for v in variants) or "none yet"),
        "RECENT FIT CHECKS:\n" + ("\n".join(gaps[-8:]) or "none yet"),
        f"PREFERENCES: availability={prefs['availability']}, weekly target={prefs.get('weekly_target', 10)} applications",
    ]
    if role:
        parts.append(f"TARGET ROLE: {role}")
    if job:
        parts.append(f"JOB IN FOCUS: {job['title']} at {job['company']}\n{(job['jd'] or '')[:2500]}")
    parts.append("CANDIDATE PROFILE:\n" + candidate_text(6000, strict=False))
    return "\n\n".join(parts)


def craft(topic: str, extra: str = "", job=None, role: str = "", n: int = 8, use_council: bool = True,
          provider: str | None = None) -> list[dict]:
    """Diverge -> critique -> converge. Saves the ranked ideas and returns them."""
    brief = TOPICS.get(topic, TOPICS["custom"])
    if topic == "custom" and not extra:
        raise SystemExit('custom topic needs text: lodestar ideas craft custom --extra "..."')
    ctx = context(job, role)
    ask = (f"Propose {n} distinct, specific ideas for {brief}. {extra}\nGround every idea in the data below; "
           f"reject generic advice. Return JSON only: {IDEA_SCHEMA}\n\n{ctx}")
    pools: list[dict] = []
    providers = ai.council_providers() if use_council else [provider or ai.default_provider()]
    for p in providers[:4]:
        try:
            pools += [i | {"source": p} for i in ai.ask_json(ask, provider=p) if isinstance(i, dict)]
        except Exception as e:
            print(f"  {p}: {e}")
    if len(providers) == 1:  # single provider: a critic pass stands in for the second opinion
        try:
            pools += [i | {"source": "critic"} for i in ai.ask_json(
                f"Here are draft ideas:\n{json.dumps(pools)[:6000]}\n\nFind what is weak, obvious, or wrong, then add 4 "
                f"better ideas the drafts missed. Return JSON only (the new ideas): {IDEA_SCHEMA}\n\n{ctx[:4000]}",
                provider=provider) if isinstance(i, dict)]
        except Exception as e:
            print(f"  critic pass skipped: {e}")
    if not pools:
        raise SystemExit("no provider produced ideas (check `lodestar providers --test`)")
    final = ai.ask_json(
        f"""You are converging a brainstorm on {brief}. Candidate ideas (from several sources, may overlap):
{json.dumps(pools)[:12000]}

Merge duplicates, drop weak or generic ones, keep the best {n}. For each return JSON:
[{{"title": "...", "idea": "...", "why_it_works": "...", "effort": 1-5, "impact": 1-5, "fit": 0-100,
  "plan": ["step 1", "step 2", "step 3"], "metric": "how we will know it worked", "time": "e.g. 3 hours / 2 weeks"}}]
Order by (impact * fit) / effort, best first. Fit = how well it matches THIS candidate's data below.

{ctx[:5000]}""",
        provider=provider or providers[0],
    )
    out = []
    for i in (final if isinstance(final, list) else [final])[:n]:
        if not isinstance(i, dict) or not i.get("title"):
            continue
        score = round(float(i.get("impact", 3)) * float(i.get("fit", 50)) / max(float(i.get("effort", 3)), 1), 1)
        iid = db.add_idea(topic, str(i["title"]), json.dumps(i), score, job["id"] if job else None,
                          ",".join(filter(None, [role, job["company"] if job else ""])))
        out.append({"id": iid, "topic": topic, "score": score, "status": "new", **i})
    return out


def refine(idea_id: int, feedback: str, provider: str | None = None) -> dict:
    row = db.get_idea(idea_id)
    body = json.loads(row["body"])
    new = ai.ask_json(
        f"""Refine this idea using the user's feedback. Keep what works, change what they asked, make the plan more
concrete. Return the same JSON shape with every field present:
{json.dumps(body)}

FEEDBACK: {feedback}

CONTEXT:
{context()[:4000]}""",
        provider=provider,
    )
    if isinstance(new, list):
        new = new[0]
    new["history"] = body.get("history", []) + [{"at": datetime.now().isoformat(timespec="minutes"), "feedback": feedback}]
    db.update_idea(idea_id, title=str(new.get("title", row["title"])), body=json.dumps(new))
    return {"id": idea_id, "topic": row["topic"], "score": row["score"], "status": row["status"], **new}


def rows() -> list[dict]:
    return [dict(r) | json.loads(r["body"]) for r in db.list_ideas()]


def render(idea: dict) -> str:
    plan = "\n".join(f"    {k + 1}. {s}" for k, s in enumerate(idea.get("plan", [])))
    return (f"#{idea.get('id', '?')} [{idea.get('topic', '')}/{idea.get('status', 'new')}] {idea.get('title')}  "
            f"(score {idea.get('score', '?')}, impact {idea.get('impact', '?')}, effort {idea.get('effort', '?')}, fit {idea.get('fit', '?')})\n"
            f"  {idea.get('idea', '')}\n  why: {idea.get('why_it_works', '')}\n{plan}\n"
            f"  metric: {idea.get('metric', '')}  |  time: {idea.get('time', '')}")
