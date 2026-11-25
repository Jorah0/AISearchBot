"""Evidence broker (pass 59, plan docs/superpowers/plans/2026-11-24-model-lab.md section F).

Evidence is a versioned record (workspace, evidence_id, revision) under a policy that names what it may be used for
(PURPOSES). Every change mints the next revision and its EvidenceEvent v1 (data/evidence_event.schema.json) in one
transaction; consumers read the outbox through consume() with a receipt per event. A retracted record is gone for
every purpose, an old revision is never served as current, and an upsert older than the record (a delayed delivery)
never revives it. Teachers and dataset builders read through resolve(..., "train") / export("train")."""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

from . import db

PURPOSES = ("discover", "store", "display", "derive", "embed", "retrieve", "train")
OPS = ("upsert", "retract")
FIELDS = ("schema_version", "event_id", "op", "workspace_id", "evidence_id", "revision", "provider_id", "source_id",
          "occurred_at", "policy_id")
_STRINGS = ("event_id", "workspace_id", "evidence_id", "provider_id", "source_id", "policy_id")
_RFC3339_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", re.ASCII)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ev_policy(policy_id TEXT NOT NULL, version INTEGER NOT NULL, provider TEXT, flags TEXT NOT NULL,
  expiry TEXT, retention TEXT, PRIMARY KEY(policy_id, version));
CREATE TABLE IF NOT EXISTS evidence(workspace TEXT NOT NULL, evidence_id TEXT NOT NULL, revision INTEGER NOT NULL,
  state TEXT NOT NULL, provider_id TEXT, source_id TEXT, body TEXT, observed_at TEXT, policy_id TEXT,
  PRIMARY KEY(workspace, evidence_id, revision));
CREATE TABLE IF NOT EXISTS ev_outbox(event_id TEXT PRIMARY KEY, event TEXT NOT NULL, delivered INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS ev_receipts(consumer TEXT NOT NULL, event_id TEXT NOT NULL, PRIMARY KEY(consumer, event_id));
"""


def _con():
    c = db.con()
    c.executescript(_SCHEMA)
    return c


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_event(e) -> list[str]:
    """Problems with an EvidenceEvent v1 (empty list = valid). Same rules as data/evidence_event.schema.json."""
    if not isinstance(e, dict):
        return ["event must be an object"]
    errs = [f"missing {k}" for k in FIELDS if k not in e] + [f"unknown field {k}" for k in e if k not in FIELDS]
    if "schema_version" in e and (e["schema_version"] != 1 or isinstance(e["schema_version"], bool)):
        errs.append("schema_version must be 1")
    for k in _STRINGS:
        if k in e and not (isinstance(e[k], str) and 0 < len(e[k]) <= 200):
            errs.append(f"{k} must be a non-empty string (at most 200)")
    if "op" in e and e["op"] not in OPS:
        errs.append("op must be upsert or retract")
    r = e.get("revision")
    if "revision" in e and (isinstance(r, bool) or not isinstance(r, int) or r < 1):
        errs.append("revision must be a positive integer")
    t = e.get("occurred_at")
    if "occurred_at" in e:
        ok = isinstance(t, str) and bool(_RFC3339_UTC.match(t))
        if ok:
            try:
                datetime.strptime(t[:19], "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                ok = False
        if not ok:
            errs.append("occurred_at must be an RFC 3339 UTC time (…Z)")
    return errs


def set_policy(policy_id: str, provider: str, flags: dict, expiry: str | None = None,
               retention: str | None = None) -> int:
    """A new version of a policy (versions are never edited). flags: purpose -> bool; unknown purposes refused."""
    bad = [k for k in flags if k not in PURPOSES]
    if bad:
        raise ValueError(f"unknown purpose(s): {', '.join(bad)}")
    clean = {p: bool(flags.get(p)) for p in PURPOSES}
    c = _con()
    with c:
        v = (c.execute("SELECT MAX(version) FROM ev_policy WHERE policy_id=?", (policy_id,)).fetchone()[0] or 0) + 1
        c.execute("INSERT INTO ev_policy VALUES(?,?,?,?,?,?)",
                  (policy_id, v, provider, json.dumps(clean), expiry, retention))
    return v


def policy(policy_id: str) -> dict | None:
    r = _con().execute("SELECT * FROM ev_policy WHERE policy_id=? ORDER BY version DESC LIMIT 1", (policy_id,)).fetchone()
    return None if r is None else dict(r) | {"flags": json.loads(r["flags"])}


def allowed(policy_id: str | None, purpose: str) -> bool:
    p = policy(policy_id) if policy_id else None
    if p is None or not p["flags"].get(purpose):
        return False
    return not (p["expiry"] and p["expiry"] <= now())


def _apply(event: dict, body) -> dict:
    """Store one validated event. event['revision'] None = mint the next one. Runs in one transaction with the outbox
    row: either both land or neither does."""
    c = _con()
    ws, eid = event["workspace_id"], event["evidence_id"]
    if not c.in_transaction:
        c.execute("BEGIN IMMEDIATE")  # the revision read and the inserts below hold the write lock together
    with c:
        if c.execute("SELECT 1 FROM ev_outbox WHERE event_id=?", (event["event_id"],)).fetchone():
            return {"status": "duplicate", "event_id": event["event_id"]}
        top = c.execute("SELECT revision, state FROM evidence WHERE workspace=? AND evidence_id=? "
                        "ORDER BY revision DESC LIMIT 1", (ws, eid)).fetchone()
        cur = top["revision"] if top else 0
        if event["revision"] is None:
            if event["op"] == "retract" and (top is None or top["state"] == "retracted"):
                return {"status": "gone", "evidence_id": eid}
            event["revision"] = cur + 1
        elif event["revision"] <= cur:  # a delayed or replayed event: never moves a record backwards or revives it
            return {"status": "stale", "evidence_id": eid, "current_revision": cur}
        if errs := validate_event(event):
            raise ValueError("; ".join(errs))
        if event["op"] == "upsert":
            c.execute("UPDATE evidence SET state='superseded' WHERE workspace=? AND evidence_id=? AND state='current'",
                      (ws, eid))
            stored = json.dumps(body, sort_keys=True)
            state = "current"
        else:  # a retraction removes the content of every revision, not just the newest
            c.execute("UPDATE evidence SET state='retracted', body=NULL WHERE workspace=? AND evidence_id=?", (ws, eid))
            stored, state = None, "retracted"
        c.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?)",
                  (ws, eid, event["revision"], state, event["provider_id"], event["source_id"], stored,
                   event["occurred_at"], event["policy_id"]))
        c.execute("INSERT INTO ev_outbox(event_id, event) VALUES(?,?)", (event["event_id"], json.dumps(event)))
    return {"status": "ok", "evidence_id": eid, "revision": event["revision"], "event_id": event["event_id"]}


def _event(op, workspace, evidence_id, provider_id, source_id, policy_id, revision=None, event_id=None,
           occurred_at=None) -> dict:
    return {"schema_version": 1, "event_id": event_id or uuid.uuid4().hex, "op": op, "workspace_id": workspace,
            "evidence_id": evidence_id, "revision": revision, "provider_id": provider_id, "source_id": source_id,
            "occurred_at": occurred_at or now(), "policy_id": policy_id}


def upsert(workspace: str, evidence_id: str, body: dict, provider_id: str, source_id: str, policy_id: str,
           event_id: str | None = None) -> dict:
    """Store body as the next revision. -> {status ok|duplicate, evidence_id, revision, event_id}."""
    if not isinstance(body, dict):
        raise ValueError("body must be an object")
    return _apply(_event("upsert", workspace, evidence_id, provider_id, source_id, policy_id, event_id=event_id), body)


def retract(workspace: str, evidence_id: str, event_id: str | None = None) -> dict:
    """Retract a record (its next revision, content of every revision removed). -> {status ok|gone|duplicate, ...}."""
    r = _con().execute("SELECT provider_id, source_id, policy_id FROM evidence WHERE workspace=? AND evidence_id=? "
                       "ORDER BY revision DESC LIMIT 1", (workspace, evidence_id)).fetchone()
    if r is None:
        return {"status": "gone", "evidence_id": evidence_id}
    return _apply(_event("retract", workspace, evidence_id, r["provider_id"], r["source_id"], r["policy_id"],
                         event_id=event_id), None)


def ingest(event: dict, body: dict | None = None) -> dict:
    """An event from a provider that minted its own revision (delivery may repeat or arrive late).
    -> {status ok|duplicate|stale, ...}; an invalid event raises ValueError."""
    if errs := validate_event(event):
        raise ValueError("; ".join(errs))
    if event["op"] == "upsert" and not isinstance(body, dict):
        raise ValueError("an upsert needs a body object")
    return _apply(dict(event), body if event["op"] == "upsert" else None)


def resolve(workspace: str, evidence_id: str, purpose: str, revision: int | None = None) -> dict:
    """-> {status: ok (body, revision) | superseded (current_revision) | denied (reason) | gone}.
    A retracted or unknown record is gone; a policy without the purpose (or expired, or missing) is denied; asking
    for an older revision gives superseded, never its text."""
    if purpose not in PURPOSES:
        return {"status": "denied", "reason": f"unknown purpose {purpose!r}"}
    top = _con().execute("SELECT * FROM evidence WHERE workspace=? AND evidence_id=? ORDER BY revision DESC LIMIT 1",
                         (workspace, evidence_id)).fetchone()
    if top is None or top["state"] == "retracted":
        return {"status": "gone", "evidence_id": evidence_id}
    if not allowed(top["policy_id"], purpose):
        return {"status": "denied", "evidence_id": evidence_id, "reason": f"policy {top['policy_id']} does not allow {purpose}"}
    if revision is not None and revision != top["revision"]:
        return {"status": "superseded", "evidence_id": evidence_id, "current_revision": top["revision"]}
    return {"status": "ok", "evidence_id": evidence_id, "revision": top["revision"], "body": json.loads(top["body"]),
            "provider_id": top["provider_id"], "source_id": top["source_id"], "policy_id": top["policy_id"]}


def records(workspace: str = "me", provider_id: str | None = None) -> list[dict]:
    """Current and retracted heads (no bodies), for listing."""
    q = ("SELECT workspace, evidence_id, revision, state, provider_id, source_id, observed_at, policy_id FROM evidence e "
         "WHERE workspace=? AND revision=(SELECT MAX(revision) FROM evidence WHERE workspace=e.workspace AND "
         "evidence_id=e.evidence_id)")
    args = [workspace]
    if provider_id:
        q, args = q + " AND provider_id=?", args + [provider_id]
    return [dict(r) for r in _con().execute(q + " ORDER BY evidence_id", args)]


def export(purpose: str = "train", workspace: str = "me") -> list[dict]:
    """Every record resolve() serves for purpose right now (current revision only)."""
    out = []
    for r in records(workspace):
        if r["state"] == "current" and (x := resolve(workspace, r["evidence_id"], purpose))["status"] == "ok":
            out.append(x)
    return out


def consume(consumer: str, handler, limit: int = 500) -> dict:
    """Hand outbox events this consumer has no receipt for to handler(event), oldest first. A receipt is written only
    after handler returns, so a raising handler leaves the event to be retried next call (and stops this call, keeping
    order). -> {handled, failed: event_id | None, error}."""
    c = _con()
    rows = c.execute("SELECT event_id, event FROM ev_outbox o WHERE NOT EXISTS (SELECT 1 FROM ev_receipts r WHERE "
                     "r.consumer=? AND r.event_id=o.event_id) ORDER BY rowid LIMIT ?", (consumer, limit)).fetchall()
    n = 0
    for r in rows:
        try:
            handler(json.loads(r["event"]))
        except Exception as e:  # noqa: BLE001 - any handler failure means "not delivered"
            return {"handled": n, "failed": r["event_id"], "error": str(e)[:300]}
        with c:
            c.execute("INSERT OR IGNORE INTO ev_receipts VALUES(?,?)", (consumer, r["event_id"]))
            c.execute("UPDATE ev_outbox SET delivered=1 WHERE event_id=?", (r["event_id"],))
        n += 1
    return {"handled": n, "failed": None, "error": None}


# ---- adapters: name -> (provider_id, {policy_id: flags}, records(workspace) -> [(evidence_id, source_id, policy_id, body)])

def _fixture(workspace: str) -> list[tuple]:
    """Deterministic demo records (tests, the lab's demo button)."""
    return [(f"fx-{i}", f"fixture/{i}", "fixture-demo",
             {"kind": "note", "title": f"Fixture record {i}", "text": f"Deterministic evidence number {i}."})
            for i in range(1, 4)]


_JOB_FIELDS = ("title", "company", "location")
_PROFILE_KINDS = {"skills": ("name", "category"), "certifications": ("name", "issuer", "date"),
                  "experience": ("title", "company", "start", "end"), "education": ("degree", "field", "school", "end")}


def _owner(workspace: str) -> list[tuple]:
    """Lodestar's own data as evidence, employer-safe readers only: job postings (title, company, location, a JD
    snippet; never notes) and profile facts from profile.structured(employer=True) (never contact, Preferences or the
    floor). Every body passes drafts.leaks; one that trips it is dropped. Private answers, EEO, readiness and codes are
    never read here."""
    from . import drafts

    out = []
    for r in _con().execute("SELECT id, title, company, location, jd FROM jobs ORDER BY id"):
        body = {"kind": "job_posting"} | {k: str(r[k] or "")[:200] for k in _JOB_FIELDS}
        body["jd"] = " ".join(str(r["jd"] or "").split())[:600]
        if not drafts.leaks(json.dumps(body)):
            out.append((f"job:{r['id']}", f"jobs/{r['id']}", "owner-jobs", body))
    try:
        from . import profile

        doc = profile.structured(employer=True)
    except (Exception, SystemExit):  # template or unreadable profile: jobs only
        doc = {}
    for kind, keys in _PROFILE_KINDS.items():
        for e in doc.get(kind) or []:
            body = {"kind": kind[:-1] if kind.endswith("s") else kind} | {k: str(e.get(k) or "")[:200] for k in keys}
            if not any(body[k] for k in keys) or drafts.leaks(json.dumps(body)):
                continue
            key = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:16]
            out.append((f"profile:{key}", f"profile/{kind}", "owner-profile", body))
    return out


_OWNER_FLAGS = {"retrieve": True, "train": True, "display": True}
ADAPTERS = {
    "fixture": ("fixture", {"fixture-demo": {p: True for p in PURPOSES}}, _fixture),
    "owner": ("owner", {"owner-jobs": _OWNER_FLAGS, "owner-profile": _OWNER_FLAGS}, _owner),
}


def publish(adapter: str, workspace: str = "me") -> dict:
    """Run an adapter: policies set (a new version only when the flags changed), changed records upserted, unchanged
    ones left at their revision, records the source no longer has retracted. -> {upserted, unchanged, retracted}."""
    if adapter not in ADAPTERS:
        raise ValueError(f"unknown adapter {adapter!r}")
    provider, policies, read = ADAPTERS[adapter]
    for pid, flags in policies.items():
        p = policy(pid)
        if p is None or p["flags"] != {k: bool(flags.get(k)) for k in PURPOSES} or p["provider"] != provider:
            set_policy(pid, provider, flags)
    seen, up, same = set(), 0, 0
    for eid, source, pid, body in read(workspace):
        seen.add(eid)
        r = _con().execute("SELECT body, state, policy_id FROM evidence WHERE workspace=? AND evidence_id=? "
                           "ORDER BY revision DESC LIMIT 1", (workspace, eid)).fetchone()
        if r is not None and r["state"] == "current" and r["policy_id"] == pid and \
                r["body"] == json.dumps(body, sort_keys=True):
            same += 1
            continue
        upsert(workspace, eid, body, provider, source, pid)
        up += 1
    gone = 0
    for r in records(workspace, provider):
        if r["state"] == "current" and r["evidence_id"] not in seen:
            gone += retract(workspace, r["evidence_id"])["status"] == "ok"
    return {"upserted": up, "unchanged": same, "retracted": gone}
