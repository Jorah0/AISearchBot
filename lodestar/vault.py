"""Credential vault backed by the OS keyring (Windows Credential Manager, macOS Keychain, Secret Service).

Secrets never touch disk in plain text. A name index (no secrets) lives in ~/.lodestar/vault_index.json
because keyring cannot enumerate entries.
"""
import json

import keyring

from .config import HOME

SERVICE = "lodestar"
INDEX = HOME / "vault_index.json"


def _index() -> dict:
    return json.loads(INDEX.read_text()) if INDEX.is_file() else {}


def _save_index(idx: dict) -> None:
    INDEX.write_text(json.dumps(idx, indent=2))


def set(name: str, secret: str, user: str | None = None) -> None:
    keyring.set_password(SERVICE, name, secret)
    idx = _index()
    idx[name] = {"user": user or ""}
    _save_index(idx)


def get(name: str) -> str | None:
    try:
        val = keyring.get_password(SERVICE, name)
        if val is None:  # secrets stored before the rename live under the old service name: copy once
            val = keyring.get_password("jobbot", name)
            if val is not None:
                keyring.set_password(SERVICE, name, val)
        return val
    except keyring.errors.KeyringError:
        return None


def user(name: str) -> str:
    return _index().get(name, {}).get("user", "")


def delete(name: str) -> None:
    for service in (SERVICE, "jobbot"):  # the old-name copy too, or get() would copy it straight back
        try:
            keyring.delete_password(service, name)
        except keyring.errors.PasswordDeleteError:  # not stored under that name
            pass
    idx = _index()
    idx.pop(name, None)
    _save_index(idx)


def names() -> list[tuple[str, str]]:
    return [(n, v.get("user", "")) for n, v in sorted(_index().items())]
