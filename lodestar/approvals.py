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
    pid = db.add_pending(tool, kind, job_id, summary, json.dumps(payload))
    if settings.auto(tool) and not force_pending:
        return approve(pid)
    if job_id:
        db.add_event(job_id, "proposed", f"inbox #{pid}: {summary[:90]}")
    return {"id": pid, "status": "pending", "summary": summary}


def approve(pid: int, edits: dict | None = None) -> dict:
    row = db.get_pending(pid)
    if row["status"] != "pending" or not db.claim_pending(pid):
        row = db.get_pending(pid)
        return {"id": pid, "status": row["status"], "result": row["result"]}
    payload = json.loads(row["payload"]) | (edits or {})
    try:
        result = EXECUTORS[row["kind"]](payload)
        status = "done"
    except BaseException as e:  # SystemExit from helpers carries the user-facing message
        result, status = f"error: {e}", "error"
    db.decide_pending(pid, status, str(result))
    if row["job_id"]:
        db.add_event(row["job_id"], row["kind"], str(result)[:200])
    return {"id": pid, "status": status, "result": result}


def reject(pid: int, reason: str = "") -> None:
    row = db.get_pending(pid)
    if row["status"] != "pending":  # never overwrite the record of something that already ran
        return
    db.decide_pending(pid, "rejected", reason)
    if row["job_id"]:
        db.add_event(row["job_id"], "rejected_proposal", f"inbox #{pid} {reason}".strip())


# ----------------------------------------------------------------------------- executors
def _send(p: dict) -> str:
    send_email(p["to"], p["subject"], p["body"], in_reply_to=p.get("in_reply_to"))
    note = ""
    try:  # the mail is out; bookkeeping failures must not turn a sent item into an "error"
        if p.get("chosen_time") and p.get("job_id") and settings.enabled("calendar"):
            from .extras import ics, parse_when

            ics(db.get_job(p["job_id"]), parse_when(p["chosen_time"]))
        if p.get("job_id") and p.get("new_status"):
            job = db.get_job(p["job_id"])
            if db.STATUSES.index(p["new_status"]) > db.STATUSES.index(job["status"]):
                db.set_status(p["job_id"], p["new_status"], "(after reply)")
    except BaseException as e:
        note = f" (sent; follow-up step failed: {e})"
    return f"sent to {p['to']}: {p['subject']}{note}"


def _status(p: dict) -> str:
    db.set_status(p["job_id"], p["status"], p.get("note", ""))
    return f"#{p['job_id']} -> {p['status']}"


def _add_job(p: dict) -> str:
    jid = db.add_job(p["company"], p["title"], p.get("url"), p.get("jd"), p.get("notes"))
    if p.get("contact_email"):
        db.update_job(jid, contact_email=p["contact_email"], contact_name=p.get("contact_name", ""))
    return f"tracked #{jid} {p['company']} - {p['title']}"


def _answer(p: dict) -> str:
    db.save_answer(p["question"], p["answer"], p.get("tags", ""))
    return f"saved answer for '{p['question'][:60]}'"


def _note(p: dict) -> str:
    db.add_event(p["job_id"], "note", p["text"])
    return "noted"


EXECUTORS = {"send_email": _send, "set_status": _status, "add_job": _add_job, "save_answer": _answer, "note": _note}
