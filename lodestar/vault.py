"""Credential vault backed by the OS keyring (Windows Credential Manager, macOS Keychain, Secret Service).

Secrets never touch disk in plain text. A name index (no secrets) lives in ~/.lodestar/vault_index.json
because keyring cannot enumerate entries.
"""
import hashlib
import json
import os
import re
from pathlib import Path

import keyring

from .config import HOME


def namespace(home=HOME) -> tuple[str, str]:
    """(keyring service, legacy service read as a fallback or "") for a data folder. Only the default folder (~/.lodestar, or
    ~/.jobbot when that migration could not run) uses 'lodestar' and the pre-rename 'jobbot' fallback; any other
    LODESTAR_HOME (a test, a doc writer's sandbox, a second profile) gets its own service from its resolved path, so it
    can never read or overwrite the real keys and mail password. LODESTAR_VAULT_SERVICE names a fixed service instead."""
    fixed = os.environ.get("LODESTAR_VAULT_SERVICE", "").strip()
    if fixed:
        return fixed, ""
    here, *default = (os.path.normcase(os.path.realpath(p))  # resolved, case-insensitive on Windows
                      for p in (home, Path.home() / ".lodestar", Path.home() / ".jobbot"))
    if here in default:
        return "lodestar", "jobbot"
    return "lodestar:" + hashlib.sha256(here.encode()).hexdigest()[:12], ""


SERVICE, LEGACY = namespace()
INDEX = HOME / "vault_index.json"
CHUNK = 1000  # ponytail: Windows Credential Manager caps a blob at 2560 bytes (1280 UTF-16 chars); keyring does not split


def _index() -> dict:
    try:
        return json.loads(INDEX.read_text()) if INDEX.is_file() else {}
    except ValueError:  # a corrupt name index must not break /api/state (the whole page); the secrets stay in the keyring
        return {}


def _save_index(idx: dict) -> None:
    tmp = INDEX.with_suffix(".tmp")
    tmp.write_text(json.dumps(idx, indent=2))
    os.replace(tmp, INDEX)  # atomic: a crash leaves the old index or the new one, never half of one


# A secret longer than CHUNK is stored as a head "MARK<n>:<h>:<first piece>" under NAME plus NAME~<h>~1 .. NAME~<h>~<n-1>,
# h = a hash of the whole secret. The head is written last and names its own pieces, so a crash mid-write leaves the old
# head pointing at the old pieces (still whole), and a mixed or missing piece fails the hash: no secret, never a wrong one.
MARK = "lodestar-chunked:"
_HEAD = re.compile(r"(\d+):([0-9a-f]{16}):")


def _h(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()[:16]


def _pieces(name: str) -> tuple[int, str]:
    """(piece count, hash) of the chunked secret stored under name; (1, '') for a plain one or none."""
    try:
        head = keyring.get_password(SERVICE, name) or ""
    except keyring.errors.KeyringError:
        return 1, ""
    m = _HEAD.match(head, len(MARK)) if head.startswith(MARK) else None
    return (int(m[1]), m[2]) if m else (1, "")


def set(name: str, secret: str, user: str | None = None) -> None:
    name, secret = str(name or "").strip(), str(secret or "").strip()  # a pasted key's trailing space or newline too
    if not name or not secret:  # a nameless, empty or blank entry is a mis-click, not a secret
        raise ValueError("give both a name (e.g. ANTHROPIC_API_KEY) and the secret to store")
    parts = [secret[i:i + CHUNK] for i in range(0, len(secret), CHUNK)]
    old_n, old_h = _pieces(name)
    head, h = parts[0], ""
    if len(parts) > 1:
        h = _h(secret)
        for i, part in enumerate(parts[1:], 1):
            keyring.set_password(SERVICE, f"{name}~{h}~{i}", part)
        head = f"{MARK}{len(parts)}:{h}:{parts[0]}"
    keyring.set_password(SERVICE, name, head)  # last: until here the old head still names the old, whole pieces
    if old_h and old_h != h:
        _drop_pieces(name, old_n, old_h)
    idx = _index()
    idx[name] = {"user": user or ""}
    _save_index(idx)


def _drop_pieces(name: str, n: int, h: str) -> None:
    for i in range(1, n):
        try:
            keyring.delete_password(SERVICE, f"{name}~{h}~{i}")
        except keyring.errors.PasswordDeleteError:
            pass


def get(name: str) -> str | None:
    try:
        val = keyring.get_password(SERVICE, name)
        if val is None and LEGACY:  # secrets stored before the rename live under the old service name: copy once
            val = keyring.get_password(LEGACY, name)
            if val is not None:
                keyring.set_password(SERVICE, name, val)
        if val is None or not val.startswith(MARK):
            return val
        m = _HEAD.match(val, len(MARK))
        if not m:
            return None
        n, h, out = int(m[1]), m[2], val[m.end():]
        for i in range(1, n):  # a long secret (a Microsoft refresh token)
            part = keyring.get_password(SERVICE, f"{name}~{h}~{i}")
            if part is None:  # a missing piece is no secret at all, never a truncated one
                return None
            out += part
        return out if _h(out) == h else None
    except keyring.errors.KeyringError:
        return None


def user(name: str) -> str:
    return _index().get(name, {}).get("user", "")


def delete(name: str) -> None:
    n, h = _pieces(name)
    if h:
        _drop_pieces(name, n, h)
    for service in filter(None, (SERVICE, LEGACY)):  # the old-name copy too, or get() would copy it straight back
        try:
            keyring.delete_password(service, name)
        except keyring.errors.PasswordDeleteError:  # not stored under that name
            pass
    idx = _index()
    idx.pop(name, None)
    _save_index(idx)


def names() -> list[tuple[str, str]]:
    return [(n, v.get("user", "")) for n, v in sorted(_index().items())]
