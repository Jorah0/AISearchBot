"""Approvals inbox: every automatic AI action is proposed here. If its tool is set to auto it executes at once;
otherwise it waits for `lodestar approve ID` (or the Inbox tab). Executors are the only code paths that send
mail, change status, or add jobs on lodestar's own initiative, so the rule lives in one place.
"""
import json

from . import db, settings
from .util import send_email


def propose(tool: str, kind: str, payload: dict, summary: str, job_id: int | None = None,
            force_pending: bool = False) -> dict:
    """Returns {"status": "disabled" | "pending" | "done" | "error", ...}.
    force_pending: ignore the tool's auto flag (used for actions triggered by unauthenticated mail)."""
    if not settings.enabled(tool):
        return {"status": "disabled", "tool": tool}
    if kind == "set_status" and payload.get("job_id") and "from_status" not in payload:
        payload = payload | {"from_status": db.get_job(payload["job_id"])["status"]}  # _status refuses it once the job moves
    src = kind == "send_email" and payload.get("in_reply_to") and db.mail_by_message_id(payload["in_reply_to"])
    if src and src["direction"] == "in" and not src["trusted"]:
        payload = payload | {"unverified": True}
    if payload.get("unverified"):  # a reply to unverified mail: the Inbox card says so, and sending it moves no job
        payload = {k: v for k, v in payload.items() if k != "new_status"}
    pid = db.add_pending(tool, kind, job_id, summary, json.dumps(payload))
    if settings.auto(tool) and not force_pending:
        return approve(pid)
    if job_id:
        db.add_event(job_id, "proposed", f"inbox #{pid}: {summary[:90]}")
    return {"id": pid, "status": "pending", "summary": summary}


def approve(pid: int, edits: dict | None = None) -> dict:
    if edits is not None and not isinstance(edits, dict):  # checked before the claim, or the item would stick claimed
        raise ValueError("edits must be a JSON object")
    row = db.get_pending(pid)
    if row["status"] != "pending" or not db.claim_pending(pid):
        row = db.get_pending(pid)
        return {"id": pid, "status": row["status"], "result": row["result"]}
    payload = json.loads(row["payload"]) | (edits or {})
    try:
        result = EXECUTORS[row["kind"]](payload)
        status = "done"
    except BaseException as e:  # SystemExit from helpers carries the user-facing message
        db.release(close=False)  # a half-done executor write is undone, not committed by the bookkeeping below
        result, status = str(e) or type(e).__name__, "rejected" if isinstance(e, Stale) else "error"
        if row["kind"] == "send_email" and not isinstance(e, Stale):
            # nothing was sent (_send contains every failure after the mail is out): the item stays in the Inbox with
            # your edited subject and body and the error, for a retry once mail works.
            # ponytail: an SMTP error after the server accepted the message would also land here; rare, see Sent first
            db.requeue_pending(pid, json.dumps(payload), f"send failed: {result}")
            if row["job_id"]:
                db.add_event(row["job_id"], "send_failed", f"inbox #{pid}: {result[:180]}")
            return {"id": pid, "status": "pending", "result": f"not sent, kept in the Inbox to retry: {result}"}
    db.decide_pending(pid, status, str(result))
    if row["job_id"]:
        db.add_event(row["job_id"], row["kind"], str(result)[:200])
    return {"id": pid, "status": status, "result": result}


def edit(pid: int, subject: str | None = None, body: str | None = None) -> dict:
    """Replace the subject and/or body of a pending email (draft options, rewrites). Recipient, In-Reply-To, job and
    everything else stay as proposed, and the item stays pending: it still waits for your approval."""
    from .drafts import screen

    row = db.get_pending(pid)
    if row["status"] != "pending" or row["kind"] != "send_email":
        raise SystemExit(f"inbox #{pid} is not an email waiting for approval")
    new = {k: str(v) for k, v in (("subject", subject), ("body", body)) if v is not None}
    screen(new)
    payload = json.loads(row["payload"]) | new
    if not db.edit_pending(pid, json.dumps(payload)):
        raise SystemExit(f"inbox #{pid} was decided meanwhile; nothing changed")
    return {"id": pid, "status": "pending", "payload": payload}


def reject(pid: int, reason: str = "") -> None:
    row = db.get_pending(pid)
    if row["status"] != "pending":  # never overwrite the record of something that already ran
        return
    db.decide_pending(pid, "rejected", reason)
    if row["job_id"]:
        db.add_event(row["job_id"], "rejected_proposal", f"inbox #{pid} {reason}".strip())


# ----------------------------------------------------------------------------- executors
class Stale(Exception):
    """A proposal the world has moved past (the job's status changed since): closed as rejected, never executed."""


def _send(p: dict) -> str:
    mid = send_email(p["to"], p["subject"], p["body"], in_reply_to=p.get("in_reply_to"))
    note = ""
    try:  # the mail is out; bookkeeping failures must not turn a sent item into an "error"
        from .util import mail_settings

        # its Message-ID is what a reply's In-Reply-To names: email_monitor._thread files the reply under this job
        if mid:  # (a faked sender in tests returns None)
            db.add_mail(message_id=mid, in_reply_to=p.get("in_reply_to"), refs=p.get("in_reply_to"),
                        job_id=p.get("job_id"), direction="out", from_addr=mail_settings()["user"], to_addr=p["to"],
                        subject=p["subject"], sent_at=db._now(), category=p.get("purpose") or "sent",
                        snippet=p["body"], trusted=True, linked_by="auto" if p.get("job_id") else None)
        if p.get("purpose") in ("followup", "thanks") and p.get("job_id"):  # the checklist counts these as done
            db.add_event(p["job_id"], p["purpose"], f"sent to {p['to']}")
        from .contacts import touch

        touch(p["to"])  # a contact with exactly this address: last_touch = today
        if p.get("chosen_time") and p.get("job_id") and settings.enabled("calendar"):
            from .extras import conflicts, ics, parse_when

            when = parse_when(p["chosen_time"])
            clash = conflicts(when)
            if clash:
                note = f" (WARNING: {when:%Y-%m-%d %H:%M} clashes with {clash[0]['company']} at {clash[0]['when']:%H:%M}; no .ics written)"
            else:
                ics(db.get_job(p["job_id"]), when)
        if p.get("job_id") and p.get("new_status"):
            job = db.get_job(p["job_id"])
            if db.STATUSES.index(p["new_status"]) > db.STATUSES.index(job["status"]):
                db.set_status(p["job_id"], p["new_status"], "(after reply)")
    except BaseException as e:
        note += f" (sent; follow-up step failed: {e})"
    return f"sent to {p['to']}: {p['subject']}{note}"


def _status(p: dict) -> str:
    now = db.get_job(p["job_id"])["status"]
    if p.get("from_status") and now != p["from_status"]:
        raise Stale(f"stale: #{p['job_id']} moved from {p['from_status']} to {now} since this was proposed; nothing changed")
    db.set_status(p["job_id"], p["status"], p.get("note", ""))
    return f"#{p['job_id']} -> {p['status']}"


def _add_job(p: dict) -> str:
    jid = db.add_job(p["company"], p["title"], p.get("url"), p.get("jd"), p.get("notes"), p.get("ats_feed"),
                     **{k: p[k] for k in ("location", "posted_at") if p.get(k)})  # validated: an edited bad date fails here
    if p.get("contact_email"):
        db.update_job(jid, contact_email=p["contact_email"], contact_name=p.get("contact_name", ""))
    m = p.get("message_id") and db.mail_by_message_id(p["message_id"])
    if m and m["job_id"] is None:  # proposed from mail: file that mail under the new job (it leaves Unmatched)
        db.link_mail(m["id"], jid)
    return f"tracked #{jid} {p['company']} - {p['title']}"


def _answer(p: dict) -> str:
    db.save_answer(p["question"], p["answer"], p.get("tags", ""))
    return f"saved answer for '{p['question'][:60]}'"


def _note(p: dict) -> str:
    db.add_event(p["job_id"], "note", p["text"])
    return "noted"


EXECUTORS = {"send_email": _send, "set_status": _status, "add_job": _add_job, "save_answer": _answer, "note": _note}
