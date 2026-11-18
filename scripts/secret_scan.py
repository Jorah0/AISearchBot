"""Secret scan (engineering loop, P2): no credential may sit in a tracked file. Scans every file git tracks (and,
with --staged, the staged diff before a commit) for the shapes real keys take. Stdlib only, so it runs in CI and in
scripts/verify.py with no install. Exit 1 with file:line for each hit; the value itself is never printed.

usage: python scripts/secret_scan.py [--staged] [paths...]"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = {
    "Anthropic key": r"sk-ant-[A-Za-z0-9_-]{20,}",
    "OpenAI key": r"\bsk-(?!ant-|or-v1-)(?:proj-|svcacct-|admin-)?[A-Za-z0-9_-]{32,}",
    "OpenRouter key": r"sk-or-v1-[a-f0-9]{40,}",
    "Groq key": r"\bgsk_[A-Za-z0-9]{40,}",
    "xAI key": r"\bxai-[A-Za-z0-9]{40,}",
    "Hugging Face token": r"\bhf_[A-Za-z0-9]{30,}",
    "AWS access key": r"\bAKIA[0-9A-Z]{16}\b",
    "GitHub token": r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{60,})",
    "Slack token": r"\bxox[abprs]-[A-Za-z0-9-]{10,}",
    "Google API key": r"\bAIza[0-9A-Za-z_-]{35}\b",
    "Google OAuth client secret": r"\bGOCSPX-[A-Za-z0-9_-]{20,}",
    "private key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY-----",
    # NAME_PASSWORD="..." / password: '...' anywhere (a quoted literal of 8+ characters, not a __PLACEHOLDER__), and an
    # .env-style line SMTP_PASS=value (the name starts the line). A variable, a call or an env lookup is no literal.
    "password assignment": r"(?i)(?:^|[^A-Za-z0-9])[A-Za-z0-9_]*(?:password|passwd|_pass|secret|api_key|apikey|token)"
                           r"\s*[=:]\s*[\"'](?!__\w+__[\"'])[^\"'\s]{8,}[\"']",
    "env secret": r"^\s*(?:export\s+)?[A-Z0-9_]*(?:PASSWORD|PASSWD|_PASS|SECRET|API_KEY|TOKEN)\s*=\s*(?![\"'$%<])[^\s()\[\]{}]{8,}\s*$",
    "app password": r"(?i)(?:app[_ ]?password|smtp_pass)\w*\s*[=:]\s*[\"']?[a-z]{4} [a-z]{4} [a-z]{4} [a-z]{4}",
}
RX = {k: re.compile(v) for k, v in PATTERNS.items()}
# a test fixture holding a fake key on purpose: allowed only under tests/ and only with this marker on the line
ALLOW = "secret-scan: fake"
ALLOW_UNDER = ("tests/", "tests\\")
SKIP_SUFFIX = (".png", ".jpg", ".ico", ".gz", ".zip", ".pdf", ".docx", ".apk", ".jar", ".woff2")


def scan_text(name: str, text: str) -> list[str]:
    hits = []
    fixture = name.replace("\\", "/").startswith("tests/")
    for i, line in enumerate(text.splitlines(), 1):
        if ALLOW in line and fixture:
            continue
        for kind, rx in RX.items():
            if rx.search(line):
                hits.append(f"{name}:{i}: {kind}")
    return hits


def tracked() -> list[Path]:
    # tracked and new files alike (never ignored ones): a key is caught before `git add`, not after
    out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    return [ROOT / p for p in out.split("\0") if p]


def staged_text() -> str:
    return subprocess.run(["git", "diff", "--cached", "-U0"], cwd=ROOT, capture_output=True, text=True).stdout


def main(argv: list[str]) -> int:
    hits = []
    if "--staged" in argv:
        added = "\n".join(l[1:] for l in staged_text().splitlines() if l.startswith("+") and not l.startswith("+++"))
        hits += scan_text("(staged)", added)
    else:
        files = [Path(a) for a in argv if not a.startswith("--")] or tracked()
        for f in files:
            if f.suffix.lower() in SKIP_SUFFIX or not f.is_file():
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            hits += scan_text(str(f.relative_to(ROOT)) if f.is_absolute() else str(f), text)
    for h in hits:
        print(h)
    print(f"secret scan: {len(hits)} finding(s)" if hits else "secret scan: clean")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
