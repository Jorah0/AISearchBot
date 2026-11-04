"""Multi-provider LLM layer. Anthropic native + anything OpenAI-compatible (OpenAI, Gemini, Groq,
OpenRouter, Mistral, Ollama). `council()` asks several providers and synthesizes the answers.
"""
import json
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


def model_for(name: str) -> str:
    return setting(f"{name.upper()}_MODEL", PROVIDERS[name]["model"])


def api_key(name: str) -> str | None:
    k = PROVIDERS[name]["key"]
    return setting(k) if k else "ollama"


def available() -> list[str]:
    out = [n for n, p in PROVIDERS.items() if p["key"] and api_key(n)]
    if setting("OLLAMA_MODEL"):
        out.append("ollama")
    return out


def council_providers() -> list[str]:
    """Providers the council (and idea crafting) may send your data to: pref council_providers, else every configured one."""
    from . import settings

    allow = [x.strip() for x in str(settings.pref("council_providers") or "").split(",") if x.strip()]
    avail = available()
    return [n for n in allow if n in avail] or avail


def default_provider() -> str:
    from . import settings

    p = setting("LODESTAR_PROVIDER") or settings.pref("provider")
    if p:
        return p
    avail = available()
    if not avail:
        raise SystemExit("No AI provider configured. Run: lodestar vault set ANTHROPIC_API_KEY  (or OPENAI_API_KEY, GEMINI_API_KEY, ...)")
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
    name = provider or default_provider()
    p = PROVIDERS[name]
    key = api_key(name)
    if not key:
        raise SystemExit(f"{name}: missing {p['key']} (lodestar vault set {p['key']})")
    if p["kind"] == "anthropic":
        body = {"model": model_for(name), "max_tokens": max_tokens, "messages": messages}
        if system:
            body["system"] = system
        r = _post(p["url"], {"x-api-key": key, "anthropic-version": "2023-06-01"}, body)
        return "".join(b.get("text", "") for b in r["content"])
    msgs = ([{"role": "system", "content": system}] if system else []) + messages
    # ponytail: no temperature/max_tokens - newest OpenAI models reject them; defaults are fine for prose
    r = _post(p["url"], {"Authorization": f"Bearer {key}"}, {"model": model_for(name), "messages": msgs})
    return r["choices"][0]["message"]["content"]


def ask(prompt: str, system: str | None = None, provider: str | None = None, **kw) -> str:
    return chat([{"role": "user", "content": prompt}], system=system, provider=provider, **kw)


def ask_json(prompt: str, system: str | None = None, provider: str | None = None):
    from .util import extract_json

    sys_ = (system or "") + "\nReply with valid JSON only. No prose, no markdown fences."
    return extract_json(ask(prompt, system=sys_, provider=provider))


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
        answer = ask(prompt, system)
        return {"answers": {names[0] if names else "default": answer}, "synthesis": answer}
    answers = {}
    for n in names:
        try:
            answers[n] = ask(prompt, system, provider=n)
        except Exception as e:  # one dead provider should not sink the council
            answers[n] = f"(error: {e})"
    merged = "\n\n".join(f"### Answer from {n}\n{a}" for n, a in answers.items())
    synthesis = ask(
        f"Original task:\n{prompt}\n\nSeveral assistants answered independently:\n{merged}\n\n"
        "Produce one final answer that combines the strongest elements, drops weak or contradictory points, "
        "and is better than any single answer. Output only the final answer.",
        system,
    )
    return {"answers": answers, "synthesis": synthesis}
