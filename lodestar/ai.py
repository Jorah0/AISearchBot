"""Multi-provider LLM layer. Anthropic native + anything OpenAI-compatible (OpenAI, Gemini, Groq,
OpenRouter, Mistral, Ollama). `council()` asks several providers and synthesizes the answers.
"""
import contextlib
import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

from .config import HOME, setting

USAGE = HOME / "usage.jsonl"

PROVIDERS = {
    "anthropic": dict(kind="anthropic", url="https://api.anthropic.com/v1/messages", model="claude-sonnet-5-5", key="ANTHROPIC_API_KEY"),
    "openai": dict(kind="openai", url="https://api.openai.com/v1/chat/completions", model="gpt-5", key="OPENAI_API_KEY"),
    "gemini": dict(kind="openai", url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", model="gemini-2.5-flash", key="GEMINI_API_KEY"),
    "groq": dict(kind="openai", url="https://api.groq.com/openai/v1/chat/completions", model="llama-3.3-70b-versatile", key="GROQ_API_KEY"),
    "openrouter": dict(kind="openai", url="https://openrouter.ai/api/v1/chat/completions", model="anthropic/claude-sonnet-4.5", key="OPENROUTER_API_KEY"),
    "mistral": dict(kind="openai", url="https://api.mistral.ai/v1/chat/completions", model="mistral-large-latest", key="MISTRAL_API_KEY"),
    "ollama": dict(kind="openai", url="http://localhost:11434/v1/chat/completions", model="llama3.1", key=None),
}


PREFERRED = {  # first match (substring, case-insensitive) in the provider's model list wins
    "anthropic": ["claude-sonnet-5", "claude-sonnet-4", "claude-3-7-sonnet", "claude-3-5-sonnet", "claude"],
    "openai": ["gpt-5", "gpt-4.1", "gpt-4o", "gpt-4"],
    "gemini": ["gemini-2.5-flash", "gemini-2.5", "gemini-2.0-flash", "gemini"],
    "groq": ["llama-3.3-70b", "llama-3.1-70b", "llama-3", "mixtral"],
    "mistral": ["mistral-large", "mistral-medium", "mistral"],
    "openrouter": ["anthropic/claude-sonnet", "anthropic/claude", "openai/gpt-4", "google/gemini"],
    "ollama": ["llama", "qwen", "mistral", "gemma"],
}


# the light model per provider: short structured judgements (sorting mail, the duplicate check, picking one link or
# occupation) run on it inside light(); writing (resumes, letters, replies) stays on model_for. Not listed: one model.
LIGHT = {"anthropic": "claude-haiku-5-5", "openai": "gpt-5-mini", "openrouter": "anthropic/claude-haiku-4.5"}
_TL = threading.local()


@contextlib.contextmanager
def light():
    """Inside: chat() asks the provider's light model (pref ai_light, on by default). A thread-local switch, so the
    callers' (and the tests') ask / ask_json signatures stay as they are."""
    old = getattr(_TL, "on", False)
    _TL.on = True
    try:
        yield
    finally:
        _TL.on = old


def light_model(name: str) -> str | None:
    """The light model for this provider (env <NAME>_LIGHT_MODEL first), or None: pref off, or none listed."""
    from . import settings

    if not settings.pref("ai_light"):
        return None
    return setting(f"{name.upper()}_LIGHT_MODEL") or LIGHT.get(name)


def model_for(name: str) -> str:
    """Env override, then (Ollama) the job model Lodestar built for you (jobmodel, pref jobmodel), then a model verified
    earlier (prefs.models), then the built-in default."""
    from . import settings

    if env := setting(f"{name.upper()}_MODEL"):
        return env
    if name == "ollama" and settings.pref("jobmodel"):
        from . import jobmodel

        if jobmodel.built():
            return jobmodel.NAME
    return settings.pref("models").get(name) or PROVIDERS[name]["model"]


MODEL_ID = re.compile(r"[\w.:/@+-]{1,200}")


def primary() -> dict | None:
    """The primary AI every call uses unless it names its own: {provider, model}; None with no provider linked."""
    try:
        name = default_provider()
    except SystemExit:
        return None
    return {"provider": name, "model": model_for(name)}


def set_primary(provider: str, model: str | None = None) -> dict:
    """Swap the primary AI (pref provider, and prefs.models for that provider). The provider must be linked (and inside
    council_providers when that allowlist is set); the model id is checked for shape only (a model the provider rejects
    falls back on the first call, as ever). For Ollama, choosing the job model switches pref jobmodel on (it must be
    built) and naming any other model switches it off, so your pick is the one used. Full AI cannot swap it."""
    from . import settings
    from .config import full_ai_check

    full_ai_check("changes the primary AI")
    name = str(provider or "").strip().lower()
    if name not in PROVIDERS:
        raise SystemExit(f"unknown AI provider '{name}'. Providers: {', '.join(PROVIDERS)}")
    if name not in available():
        raise SystemExit(f"{name} is not linked: Setup > Link an AI key first")
    if (allow := _allowlist()) and name not in allow:
        raise SystemExit(f"{name} is not in council_providers={','.join(allow)}: add it there first")
    if model is not None:
        model = str(model).strip()
        if not MODEL_ID.fullmatch(model):
            raise SystemExit("model id: letters, digits and . : / @ + - _ only (as the provider lists it), at most 200")
        if name == "ollama":
            from . import jobmodel

            if model == jobmodel.NAME:
                if not jobmodel.built():
                    raise SystemExit(f"{jobmodel.NAME} is not built yet: Setup > Local job model > Build now")
                settings.set_pref("jobmodel", True)
            else:
                settings.set_pref("jobmodel", False)
        if not (name == "ollama" and model.startswith("lodestar-jobs")):
            settings.set_model(name, model)
    settings.set_pref("provider", name)
    return {"provider": name, "model": model_for(name)}


@contextlib.contextmanager
def using(model: str):
    """Inside: chat() asks exactly this model (evaluation compares the job model with its base); never saved."""
    old = getattr(_TL, "model", None)
    _TL.model = model
    try:
        yield
    finally:
        _TL.model = old


def pick_model(name: str) -> str | None:
    """Choose a working model from what the provider advertises, by preference order; None if nothing matches."""
    try:
        models = list_models(name)
    except Exception:
        return None
    return pick_from(name, models)


def pick_from(name: str, models: list[str]) -> str | None:
    """The preferred model among the ids a provider listed (first PREFERRED pattern that matches), else the first id.
    Code and embedding models ('codellama' contains 'llama') come last: they write poor letters and judge fit badly."""
    special = re.compile(r"code|coder|embed")
    models = sorted(models, key=lambda m: bool(special.search(m.lower())))  # stable: the provider's order otherwise
    low = [(m.lower(), m) for m in models]
    for pat in PREFERRED.get(name, []):
        hit = next((m for lm, m in low if pat in lm), None)
        if hit:
            return hit
    return models[0] if models else None


def api_key(name: str) -> str | None:
    k = PROVIDERS[name]["key"]
    return setting(k) if k else "ollama"


def available() -> list[str]:
    from . import settings

    out = [n for n, p in PROVIDERS.items() if p["key"] and api_key(n)]
    if setting("OLLAMA_MODEL") or settings.pref("models").get("ollama") or settings.pref("provider") == "ollama":
        out.append("ollama")  # Ollama has no key: an env model, a model the local preset pinned, or the provider pref
    return out


def local_preset() -> str:
    """Ollama-only preset: single calls and the council stay local, and a model Ollama actually serves is pinned."""
    from . import settings

    head = "local-only preset: provider=ollama, council_providers=ollama"
    m = setting("OLLAMA_MODEL") or pick_model("ollama")
    if not m:  # nothing saved: a preset pointing at a dead Ollama would also switch off the offline templates
        return ("local-only preset NOT applied (nothing changed): Ollama is not reachable at localhost:11434 or serves no "
                "model. Start it, `ollama pull llama3.1`, and run this again.")
    settings.set_pref("provider", "ollama")
    settings.set_pref("council_providers", "ollama")
    if setting("OLLAMA_MODEL"):
        return f"{head}, model {m} (from OLLAMA_MODEL)"
    settings.set_model("ollama", m)
    return f"{head}, model {m} (saved in prefs.models)"


# the one no-key message, read in the UI and the terminal alike
NO_PROVIDER = ("No AI provider configured: Setup > Link an AI key (terminal: lodestar keys link anthropic), or click "
               "'Local only (Ollama)' in Setup")


def _allowlist() -> list[str]:
    """pref council_providers as names: trimmed and lower-cased like the provider pref ('Anthropic' = 'anthropic')."""
    from . import settings

    return [x.strip().lower() for x in str(settings.pref("council_providers") or "").split(",") if x.strip()]


def council_providers() -> list[str]:
    """Providers the council (and idea crafting) may send your data to: pref council_providers, else every configured one."""
    allow = _allowlist()
    avail = available()
    if not allow:
        return avail
    names = [n for n in allow if n in avail]
    if not names:  # an allowlist that matches nothing must never widen to everyone
        raise SystemExit(f"council_providers={','.join(allow)} but none of them is configured; run `lodestar providers`")
    return names


def default_provider() -> str:
    from . import settings

    p = str(setting("LODESTAR_PROVIDER") or settings.pref("provider") or "").strip().lower()
    allow = _allowlist()
    if p and allow and p not in allow:  # a hard boundary for the default too
        raise SystemExit(f"provider {p} is not in council_providers={','.join(allow)}: add it there, or set provider to one "
                         "of those (`lodestar tools set provider NAME`)")
    if p:
        return p
    if allow:  # with an allowlist, the default must come from it too
        return council_providers()[0]
    avail = available()
    if not avail:
        raise SystemExit(NO_PROVIDER)
    return avail[0]


def _post(url: str, headers: dict, body: dict, retries: int = 2) -> dict:
    data = json.dumps(body).encode()
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                out = json.loads(r.read())
                _record(url, body.get("model", ""), out)
                return out
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 529) and attempt < retries:
                time.sleep(2 ** attempt * 3)
                continue
            name = next((n for n, p in PROVIDERS.items() if p["url"] == url), "provider")
            if e.code in (400, 404) and "model" in msg.lower():
                raise SystemExit(f"{name}: the model '{body.get('model')}' was rejected ({msg[:160]}). "
                                 f"Pick one from `lodestar providers models` and set {name.upper()}_MODEL.") from None
            raise RuntimeError(f"{url} -> HTTP {e.code}: {msg}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:  # DNS blip, reset, timeout: same backoff
            if attempt < retries:
                time.sleep(2 ** attempt * 3)
                continue
            raise RuntimeError(f"{url} unreachable after {retries + 1} attempts: {getattr(e, 'reason', e)}") from None
    raise RuntimeError("unreachable")


def _record(url: str, model: str, resp: dict) -> None:
    """Append token counts per call to ~/.lodestar/usage.jsonl (counts only; prices change too often to hardcode)."""
    try:
        u = resp.get("usage") or {}
        name = next((n for n, p in PROVIDERS.items() if p["url"] == url), url)
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), "provider": name, "model": model,
               "input": u.get("input_tokens", u.get("prompt_tokens", 0)), "output": u.get("output_tokens", u.get("completion_tokens", 0))}
        with USAGE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def usage(days: int = 30) -> dict:
    """{provider/model: {calls, input, output}} over the last N days, plus a total."""
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    out: dict[str, dict] = {}
    if USAGE.is_file():
        for line in USAGE.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("ts", "") < since:
                continue
            k = f"{r['provider']}/{r['model']}"
            d = out.setdefault(k, {"calls": 0, "input": 0, "output": 0})
            d["calls"] += 1
            d["input"] += int(r.get("input") or 0)
            d["output"] += int(r.get("output") or 0)
    out["total"] = {"calls": sum(v["calls"] for v in out.values()), "input": sum(v["input"] for v in out.values()),
                    "output": sum(v["output"] for v in out.values())}
    return out


def chat(messages: list[dict], system: str | None = None, provider: str | None = None, max_tokens: int = 4000) -> str:
    """messages: [{"role": "user"|"assistant", "content": str}, ...]"""
    name = str(provider or default_provider()).strip().lower()
    if name not in PROVIDERS:  # a typo in -p, LODESTAR_PROVIDER or an old settings.json: one line, not a KeyError
        raise SystemExit(f"unknown AI provider '{name}'. Providers: {', '.join(PROVIDERS)}")
    p = PROVIDERS[name]
    key = api_key(name)
    if not key:
        raise SystemExit(f"{name}: missing {p['key']} (lodestar vault set {p['key']})")
    lite = light_model(name) if getattr(_TL, "on", False) else None
    forced = getattr(_TL, "model", None)
    model = forced or lite or model_for(name)
    for attempt in (1, 2):
        try:
            if p["kind"] == "anthropic":
                body = {"model": model, "max_tokens": max_tokens, "messages": messages}
                if system:
                    body["system"] = system
                r = _post(p["url"], {"x-api-key": key, "anthropic-version": "2023-06-01"}, body)
                text, cut = "".join(b.get("text", "") for b in r["content"]), r.get("stop_reason") == "max_tokens"
            else:
                msgs = ([{"role": "system", "content": system}] if system else []) + messages
                # ponytail: no temperature/max_tokens - newest OpenAI models reject them; defaults are fine for prose
                r = _post(p["url"], {"Authorization": f"Bearer {key}"}, {"model": model, "messages": msgs})
                text, cut = r["choices"][0]["message"]["content"], r["choices"][0].get("finish_reason") == "length"
            if cut:  # a half resume saved as if complete is worse than a clear failure
                raise RuntimeError(f"{name}: the reply hit the length limit and was cut off; nothing was saved. "
                                   "Retry, shorten the input, or pick another provider.")
            if model not in (model_for(name), lite, forced):
                from . import settings

                settings.set_model(name, model)  # remembered only once the replacement actually answered
                print(f"  {name}: switched to model '{model}' (saved in prefs.models)")
            return text
        except SystemExit as e:  # "model rejected": pick one the provider actually offers and retry once
            if forced:  # an evaluation asked for exactly this model: no substitute
                raise
            if attempt == 1 and name == "ollama" and "was rejected" in str(e) and model == model_for(name) and \
                    model.startswith("lodestar-jobs"):
                from . import jobmodel

                jobmodel.forget()  # deleted in Ollama: back to the base model until the next build
                model = model_for(name)
                continue
            if attempt == 1 and lite and model == lite and "was rejected" in str(e):
                print(f"  {name}: light model '{lite}' not offered; using '{model_for(name)}' for this call")
                model = model_for(name)  # the main model, never saved as the light one
                continue
            if attempt == 2 or "was rejected" not in str(e) or setting(f"{name.upper()}_MODEL"):
                raise
            new = pick_model(name)
            if not new or new == model:
                raise
            print(f"  {name}: model '{model}' not offered; trying '{new}'")
            model = new
    raise RuntimeError("unreachable")


def ask(prompt: str, system: str | None = None, provider: str | None = None, **kw) -> str:
    return chat([{"role": "user", "content": prompt}], system=system, provider=provider, **kw)


def ask_json_light(prompt: str, system: str | None = None, provider: str | None = None, **kw):
    """ask_json on the provider's light model (light()): for short structured judgements, never for writing."""
    if system is not None:
        kw["system"] = system
    with light():
        return ask_json(prompt, provider=provider, **kw)


def ask_json(prompt: str, system: str | None = None, provider: str | None = None, **kw):
    from .util import extract_json

    sys_ = (system or "") + "\nReply with valid JSON only. No prose, no markdown fences."
    return extract_json(ask(prompt, system=sys_, provider=provider, **kw))


def list_models(name: str) -> list[str]:
    """Model ids the provider advertises (OpenAI-compatible /models, Anthropic /v1/models)."""
    p, key = PROVIDERS[name], api_key(name)
    if p["kind"] == "anthropic":
        req = urllib.request.Request("https://api.anthropic.com/v1/models", headers={"x-api-key": key, "anthropic-version": "2023-06-01"})
    else:
        req = urllib.request.Request(p["url"].rsplit("/chat/completions", 1)[0] + "/models", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read()).get("data", [])
    return sorted(m.get("id", "") for m in data if isinstance(m, dict))


REVIEW = """You are fact-checking an answer another AI wrote. Check it only against the task and the source material inside
the task: flag invented facts (anything the source does not support), contradictions, wrong numbers or dates, and
instructions it missed. Do not flag style or wording you would merely prefer.

TASK (with its source material):
{task}

ANSWER TO CHECK:
{answer}

Reply as JSON: {{"agree": true or false, "issues": ["one short sentence per real problem"]}}"""

REVISE = """Original task:
{task}

Your answer:
{answer}

Other reviewers raised these points:
{issues}

Rewrite the answer: fix each point that is right (check it against the source material in the task), keep what is
correct, and never add a fact the source does not give. Output only the answer."""


def crosscheck(prompt: str, answer: str, writer: str | None = None, rounds: int | None = None,
               reviewers: list[str] | None = None) -> dict:
    """Other AIs fact-check an answer until they all agree. Each reviewer (council_providers minus the writer: the same
    allowlist decides who may see your data) checks `answer` against `prompt` and its sources; any objection goes back
    to the writer, who revises, and every reviewer checks again, up to `rounds` revisions (pref ai_crosscheck_rounds).
    {answer, status: agreed | disagreed | unchecked, rounds, issues: ["provider: problem"], reviews}. Never more than
    (rounds + 1) x reviewers + rounds calls. A reviewer that fails is not an agreement: unchecked when no one answered."""
    from . import settings

    writer = writer or default_provider()
    if reviewers is None:  # the council's members (pass 50), never the writer's own model
        own = model_for(writer)
        try:
            names = [(p, m) for p, m in council_members() if not (p == writer and m in (None, own))]
        except SystemExit:  # no allowed member: nothing to cross-check against
            names = []
    else:
        names = [(n, None) for n in reviewers if n != writer]
    rounds = int(settings.pref("ai_crosscheck_rounds")) if rounds is None else max(0, int(rounds))
    out = {"answer": answer, "status": "unchecked", "rounds": 0, "issues": [], "reviews": []}
    if not names:
        return out | {"issues": ["only one AI is linked: nothing to cross-check against"]}
    for r in range(rounds + 1):
        reviews = []
        for prov, mod in names:
            n = f"{prov}/{mod}" if mod else prov
            try:
                with using(mod) if mod else contextlib.nullcontext():
                    v = ask_json(REVIEW.format(task=prompt, answer=answer), provider=prov)
                v = v if isinstance(v, dict) else {}
                issues = [" ".join(str(i).split())[:200] for i in v.get("issues") or [] if str(i).strip()][:5]
                reviews.append({"provider": n, "agree": v.get("agree") is True and not issues, "issues": issues})
            except (Exception, SystemExit) as e:  # a dead reviewer neither agrees nor objects
                reviews.append({"provider": n, "agree": None, "issues": [f"no review ({str(e)[:100]})"]})
        objections = [f"{v['provider']}: {i}" for v in reviews if v["agree"] is False for i in v["issues"] or ["disagrees"]]
        out |= {"answer": answer, "rounds": r, "reviews": reviews}
        if not objections:
            answered = [v for v in reviews if v["agree"] is not None]
            return out | {"status": "agreed" if answered and len(answered) == len(reviews) else "unchecked",
                          "issues": [f"{v['provider']}: {v['issues'][0]}" for v in reviews if v["agree"] is None]}
        if r == rounds:
            return out | {"status": "disagreed", "issues": objections}
        answer = ask(REVISE.format(task=prompt, answer=answer, issues="\n".join(f"- {o}" for o in objections)),
                     provider=writer).strip() or answer
    return out


COUNCIL_MAX = 6


def _members(raw) -> list[tuple[str, str | None]]:
    """'provider=model, provider' -> [(provider, model or None)], shape-checked, each once."""
    out: list[tuple[str, str | None]] = []
    for part in str(raw or "").split(","):
        prov, sep, mod = (x.strip() for x in part.partition("="))
        prov = prov.lower()
        if not prov:
            continue
        if prov not in PROVIDERS:
            raise SystemExit(f"unknown AI provider '{prov}'. Providers: {', '.join(PROVIDERS)}")
        if sep and not MODEL_ID.fullmatch(mod):
            raise SystemExit("model id: letters, digits and . : / @ + - _ only (as the provider lists it), at most 200")
        if (m := (prov, mod or None)) not in out:
            out.append(m)
    return out


def council_members() -> list[tuple[str, str | None]]:
    """Who the council asks: pref council_members ('provider=model', several models of one provider are fine), else
    every allowed provider with its current model. council_providers stays the boundary: a member outside it, or not
    linked, is never asked; members that are all outside it are refused, never widened to everyone."""
    from . import settings

    allowed = council_providers()
    chosen = _members(settings.pref("council_members"))
    if not chosen:
        return [(n, None) for n in allowed]
    kept = [m for m in chosen if m[0] in allowed]
    if not kept:
        raise SystemExit("none of your council members is linked and inside council_providers: choose them again "
                         "(the AI switcher > Council)")
    return kept


def set_council(members: list[str]) -> list[str]:
    """Choose the council's models (the AI switcher, `lodestar council-set`): 'provider=model' each, at most
    COUNCIL_MAX, every provider linked and inside council_providers. [] goes back to every allowed provider."""
    from . import settings
    from .config import full_ai_check

    full_ai_check("changes the council")
    chosen = _members(",".join(str(m) for m in members or []))
    if len(chosen) > COUNCIL_MAX:
        raise SystemExit(f"a council has at most {COUNCIL_MAX} members")
    allowed, linked = _allowlist(), available()
    for prov, _ in chosen:
        if prov not in linked:
            raise SystemExit(f"{prov} is not linked: Setup > Link an AI key first")
        if allowed and prov not in allowed:
            raise SystemExit(f"{prov} is not in council_providers={','.join(allowed)}: add it there first")
    value = [f"{p}={m}" if m else p for p, m in chosen]
    settings.set_pref("council_members", ", ".join(value))
    return value


def council_view() -> list[str]:
    """The chosen members as the page shows them (no network, never raises)."""
    from . import settings

    try:
        return [f"{p}={m}" if m else p for p, m in _members(settings.pref("council_members"))]
    except SystemExit:
        return []


def _ask_as(member: tuple[str, str | None], prompt: str, system: str | None) -> str:
    prov, mod = member
    with using(mod) if mod else contextlib.nullcontext():
        return ask(prompt, system, provider=prov)


def council(prompt: str, system: str | None = None, providers: list[str] | None = None) -> dict:
    """Pool ideas: ask every council member (council_members: the models you chose, else every allowed provider), then
    the first member that answered merges the best parts; with council_judge another member checks it."""
    members = [(n, None) for n in providers] if providers else council_members()
    label = {m: f"{m[0]}/{m[1]}" if m[1] else m[0] for m in members}
    if len(members) < 2:
        answer = _ask_as(members[0], prompt, system) if members else ask(prompt, system)
        return {"answers": {label[members[0]] if members else "default": answer}, "synthesis": answer}
    answers, ok = {}, []
    for m in members:
        try:
            answers[label[m]] = _ask_as(m, prompt, system)
            ok.append(m)
        except (Exception, SystemExit) as e:  # one dead member (or rejected model: SystemExit) should not sink the council
            answers[label[m]] = f"(error: {e})"
    merged = "\n\n".join(f"### Answer from {n}\n{a}" for n, a in answers.items())
    lead = (ok or members)[0]  # inside the allowlist (synthesis sees every answer), and a member that answered
    synthesis = _ask_as(lead, f"Original task:\n{prompt}\n\nSeveral assistants answered independently:\n{merged}\n\n"
                        "Produce one final answer that combines the strongest elements, drops weak or contradictory points, "
                        "and is better than any single answer. Output only the final answer.", system)
    from . import settings

    judge = next((m for m in ok if m != lead), None)  # another member that answered, never the writer
    if settings.pref("council_judge") and judge:  # a second member checks the first one's synthesis
        try:
            synthesis = _ask_as(judge, f"Original task:\n{prompt}\n\nProposed final answer:\n{synthesis}\n\nAct as an "
                                "independent judge: find factual errors, omissions, or generic filler, then output the "
                                "improved final answer only (no commentary).", system)
        except (Exception, SystemExit):  # a failed judge keeps the synthesis already made
            pass
    return {"answers": answers, "synthesis": synthesis}


# --- untrusted text in prompts (moved from extras.py in pass 31; extras re-exports them) -----------------
def _fence(blocks) -> tuple[str, str]:
    """[(id, attrs, text)] -> (fenced text, nonce). Every block sits between '<<<nonce BLOCK id attrs>>>' and
    '<<<nonce END id>>>'; the nonce is removed from the material, so no block can close its own fence."""
    import secrets

    n = secrets.token_hex(6)
    out = [f"<<<{n} BLOCK {i}{' ' + a.replace(n, '') if a else ''}>>>\n{str(t or '').replace(n, '')}\n<<<{n} END {i}>>>"
           for i, a, t in blocks]
    return "\n".join(out), n


def clean_label(s, n: int = 120) -> str:
    """A label that reaches prompts, chips and the CLI (page <title>s are untrusted): one line of [\\w .,:/()-]."""
    return re.sub(r"[^\w .,:/()-]", "", " ".join(str(s or "").split()))[:n].strip()
