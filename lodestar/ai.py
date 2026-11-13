"""Multi-provider LLM layer. Anthropic native + anything OpenAI-compatible (OpenAI, Gemini, Groq,
OpenRouter, Mistral, Ollama). `council()` asks several providers and synthesizes the answers.
"""
import json
import re
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


def model_for(name: str) -> str:
    """Env override, then a model verified earlier (prefs.models), then the built-in default."""
    from . import settings

    return setting(f"{name.upper()}_MODEL") or settings.pref("models").get(name) or PROVIDERS[name]["model"]


def pick_model(name: str) -> str | None:
    """Choose a working model from what the provider advertises, by preference order; None if nothing matches."""
    try:
        models = list_models(name)
    except Exception:
        return None
    return pick_from(name, models)


def pick_from(name: str, models: list[str]) -> str | None:
    """The preferred model among the ids a provider listed (first PREFERRED pattern that matches), else the first id."""
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
    model = model_for(name)
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
            if model != model_for(name):
                from . import settings

                settings.set_model(name, model)  # remembered only once the replacement actually answered
                print(f"  {name}: switched to model '{model}' (saved in prefs.models)")
            return text
        except SystemExit as e:  # "model rejected": pick one the provider actually offers and retry once
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


def council(prompt: str, system: str | None = None, providers: list[str] | None = None) -> dict:
    """Pool ideas: ask every configured provider, then have the default provider merge the best parts."""
    names = providers or council_providers()
    if len(names) < 2:
        answer = ask(prompt, system, provider=names[0] if names else None)
        return {"answers": {names[0] if names else "default": answer}, "synthesis": answer}
    answers, ok = {}, []
    for n in names:
        try:
            answers[n] = ask(prompt, system, provider=n)
            ok.append(n)
        except (Exception, SystemExit) as e:  # one dead provider (or rejected model: SystemExit) should not sink the council
            answers[n] = f"(error: {e})"
    merged = "\n\n".join(f"### Answer from {n}\n{a}" for n, a in answers.items())
    synthesis = ask(
        f"Original task:\n{prompt}\n\nSeveral assistants answered independently:\n{merged}\n\n"
        "Produce one final answer that combines the strongest elements, drops weak or contradictory points, "
        "and is better than any single answer. Output only the final answer.",
        system,
        provider=(ok or names)[0],  # inside the allowlist (synthesis sees every answer), and a provider that answered
    )
    from . import settings

    judge = next((n for n in ok if n != (ok or names)[0]), None)  # another provider that answered, never the writer
    if settings.pref("council_judge") and judge:  # a second provider checks the first one's synthesis
        try:
            synthesis = ask(
                f"Original task:\n{prompt}\n\nProposed final answer:\n{synthesis}\n\nAct as an independent judge: find factual "
                "errors, omissions, or generic filler, then output the improved final answer only (no commentary).",
                system, provider=judge,
            )
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
