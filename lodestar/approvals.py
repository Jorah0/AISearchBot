"""Approvals inbox: every automatic AI action is proposed here. If its tool is set to auto it executes at once;
otherwise it waits for `lodestar approve ID` (or the Inbox tab). Executors are the only code paths that send
mail, change status, or add jobs on lodestar's own initiative, so the rule lives in one place.
"""
import json

from . import db, settings
from .config import full_ai_check
from .util import send_email


def propose(tool: str, kind: str, payload: dict, summary: str, job_id: int | None = None,
            force_pending: bool = False) -> dict:
    """Returns {"status": "disabled" | "pending" | "done" | "error", ...}.
    force_pending: ignore the tool's auto flag (used for actions triggered by unauthenticated mail)."""
    full_ai_check("proposes sends, status changes or new jobs")
    if not settings.enabled(tool):
        return {"status": "disabled", "tool": tool}
    if kind in ("send_email", "save_answer"):  # the one choke point: no AI draft naming the salary floor is ever proposed
        from .drafts import screen

        screen({"subject": payload.get("subject"), "body": payload.get("body") or payload.get("answer")},
               payload.get("cited") or ())  # cited: competing-offer figures you ticked for a counter (apply.counter)
    if kind == "send_email" and payload.get("attachments"):  # files only ever leave after you have seen the mail
        from .mailfiles import resolve

        if not force_pending:
            raise SystemExit("a mail with attachments always waits in the Inbox for your review")
        if not job_id or payload.get("job_id") != job_id:
            raise SystemExit("attachments need a job: they come from that job's folder")
        n = len(resolve(db.get_job(job_id), payload["attachments"]))  # refused before the row exists
        summary = f"{summary} + {n} attachment{'s' if n > 1 else ''}"
    if kind == "set_status" and payload.get("job_id") and "from_status" not in payload:
        payload = payload | {"from_status": db.get_job(payload["job_id"])["status"]}  # _status refuses it once the job moves
    src = kind == "send_email" and payload.get("in_reply_to") and db.mail_by_message_id(payload["in_reply_to"])
    if src and src["direction"] == "in" and not src["trusted"]:
        payload = payload | {"unverified": True}
    if payload.get("unverified"):  # a reply to unverified mail: the Inbox card says so, and sending it moves no job
        payload = {k: v for k, v in payload.items() if k != "new_status"}
    from . import policy

    decision = policy.authorize(tool, kind, payload, job_id, force_pending)  # the one deterministic gate (pass 25)
    pid = db.add_pending(tool, kind, job_id, summary, json.dumps(payload))
    policy.record(f"propose:{kind}", tool, job_id, decision["result"], decision["reasons"], pid)
    if decision["result"] == "ALLOW":
        try:
            return approve(pid, _auto=True)
        except SystemExit as e:  # refused before the claim (a clashing slot): it waits in the Inbox, nothing sent
            return {"id": pid, "status": "pending", "summary": summary, "result": str(e)}
    if job_id:
        db.add_event(job_id, "proposed", f"inbox #{pid}: {summary[:90]}")
    return {"id": pid, "status": "pending", "summary": summary}


# what an Inbox email card edits; job, status, trust stay as proposed. attachments: re-validated by _precheck and _send
MAIL_EDITS = ("to", "subject", "body", "chosen_time", "attachments")


def approve(pid: int, edits: dict | None = None, _auto: bool = False) -> dict:
    """Run an Inbox item: your approval, or (_auto) the policy's ALLOW from propose. Both leave audit rows."""
    from . import policy

    full_ai_check("approves an Inbox item")
    if edits is not None and not isinstance(edits, dict):  # checked before the claim, or the item would stick claimed
        raise ValueError("edits must be a JSON object")
    row = db.get_pending(pid)
    if row["kind"] == "submit_application":  # a submission is never edited through the payload (Fix answers refills)
        edits = None
    if edits and row["kind"] == "send_email":  # the Inbox textarea path: only what the card lets you edit
        edits = {k: v for k, v in edits.items() if k in MAIL_EDITS}
    if row["status"] == "pending":
        _precheck(row, edits)  # before the claim, like the type check: a refused item stays pending with your edits
    if row["status"] != "pending" or not db.claim_pending(pid):
        row = db.get_pending(pid)
        return {"id": pid, "status": row["status"], "result": row["result"]}
    if not _auto:
        policy.record(f"approve:{row['kind']}", row["tool"], row["job_id"], "APPROVED_BY_YOU", ["your approval"], pid)
    payload = json.loads(row["payload"]) | (edits or {})
    try:
        result = EXECUTORS[row["kind"]](payload | {"_pid": pid, "_tool": row["tool"]})  # who and which item, for the record
        status = "done"
    except BaseException as e:  # SystemExit from helpers carries the user-facing message
        db.release(close=False)  # a half-done executor write is undone, not committed by the bookkeeping below
        result, status = str(e) or type(e).__name__, "rejected" if isinstance(e, Stale) else "error"
        if row["kind"] == "send_email" and not isinstance(e, Stale):
            # nothing was sent (_send contains every failure after the mail is out): the item stays in the Inbox with
            # your edited subject and body and the error, for a retry once mail works.
            # ponytail: an SMTP error after the server accepted the message would also land here; rare, see Sent first
            db.requeue_pending(pid, json.dumps(payload), f"send failed: {result}")
            policy.record(f"execute:{row['kind']}", row["tool"], row["job_id"], "send_failed", [result[:200]], pid)
            if row["job_id"]:
                db.add_event(row["job_id"], "send_failed", f"inbox #{pid}: {result[:180]}")
            return {"id": pid, "status": "pending", "result": f"not sent, kept in the Inbox to retry: {result}"}
    db.decide_pending(pid, status, str(result))
    policy.record(f"execute:{row['kind']}", row["tool"], row["job_id"], status, [str(result)[:200]] if status != "done" else [], pid)
    if row["job_id"]:
        db.add_event(row["job_id"], row["kind"], str(result)[:200])
    if status != "done":  # done: the run itself refreshes the summary
        _pipe_refresh(row)
    return {"id": pid, "status": status, "result": result}


def _precheck(row, edits: dict | None) -> None:
    """Refusals decided before an item is claimed (SystemExit; nothing is sent or saved, the item stays pending): the
    salary-floor guard on edited mail and answers, as for options/rewrites, and an interview slot that clashes."""
    p = json.loads(row["payload"]) | (edits or {})
    if row["kind"] == "send_email":
        if edits:
            from .drafts import screen

            screen({"subject": p.get("subject"), "body": p.get("body")}, p.get("cited") or ())
        if p.get("attachments") not in (None, []):  # the row's job folder, never a path or job from the payload
            from .mailfiles import resolve

            resolve(db.get_job(row["job_id"]) if row["job_id"] else None, p["attachments"])
        if p.get("chosen_time") and p.get("job_id"):  # checked before the acceptance goes out, not after
            from .extras import conflicts, parse_when

            when = parse_when(p["chosen_time"])
            if clash := conflicts(when, job_id=p["job_id"]):
                raise SystemExit(f"{when:%Y-%m-%d %H:%M} clashes with {clash[0]['company']} at {clash[0]['when']:%H:%M}: "
                                 "pick another slot or clear it")
    elif row["kind"] == "save_answer" and edits:
        db.check_answer(p.get("question"), p.get("answer"))


def edit(pid: int, subject: str | None = None, body: str | None = None) -> dict:
    """Replace the subject and/or body of a pending email (draft options, rewrites). Recipient, In-Reply-To, job and
    everything else stay as proposed, and the item stays pending: it still waits for your approval."""
    from .drafts import screen

    row = db.get_pending(pid)
    if row["status"] != "pending" or row["kind"] != "send_email":
        raise SystemExit(f"inbox #{pid} is not an email waiting for approval")
    new = {k: str(v) for k, v in (("subject", subject), ("body", body)) if v is not None}
    screen(new, json.loads(row["payload"]).get("cited") or ())
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
    _pipe_refresh(row)


def _pipe_refresh(row) -> None:
    """A run_to decided without running (rejected, stale): the board's step summary stops reading 'waiting on you'."""
    if row["kind"] == "run_to" and row["job_id"]:
        from . import pipeline

        try:
            pipeline.status(row["job_id"])
        except (Exception, SystemExit):  # bookkeeping: never fails the decision
            db.release(close=False)


# ----------------------------------------------------------------------------- executors
class Stale(Exception):
    """A proposal the world has moved past (the job's status changed since): closed as rejected, never executed."""


def _send(p: dict) -> str:
    paths = []
    if p.get("attachments"):  # checked again: a file may have changed or gone since approval (nothing is sent then)
        from .mailfiles import resolve

        paths = resolve(db.get_job(p["job_id"]) if p.get("job_id") else None, p["attachments"])
    mid = send_email(p["to"], p["subject"], p["body"], in_reply_to=p.get("in_reply_to"),
                     **({"attachments": paths} if paths else {}))
    note = ""
    try:  # the mail is out; bookkeeping failures must not turn a sent item into an "error"
        from .util import mail_settings

        # its Message-ID is what a reply's In-Reply-To names: email_monitor._thread files the reply under this job
        if mid:  # (a faked sender in tests returns None)
            db.add_mail(message_id=mid, in_reply_to=p.get("in_reply_to"), refs=p.get("in_reply_to"),
                        job_id=p.get("job_id"), direction="out", from_addr=mail_settings()["user"], to_addr=p["to"],
                        subject=p["subject"], sent_at=db._now(), category=p.get("purpose") or "sent",
                        snippet=p["body"], trusted=True, linked_by="auto" if p.get("job_id") else None,
                        attachments=[{"name": f.name, "size": f.stat().st_size} for f in paths])
        if p.get("purpose") in ("followup", "thanks") and p.get("job_id"):  # the checklist counts these as done
            db.add_event(p["job_id"], p["purpose"], f"sent to {p['to']}")
        while p.get("purpose") == "followup" and p.get("job_id") and (dup := db.followup_waiting(p["job_id"])):
            db.decide_pending(dup["id"], "rejected", "stale: a follow-up for this job was just sent")  # never twice
        from .contacts import touch

        touch(p["to"])  # a contact with exactly this address: last_touch = today
        if p.get("chosen_time") and p.get("job_id") and settings.enabled("calendar"):
            from .extras import conflicts, ics, parse_when

            when = parse_when(p["chosen_time"])
            clash = conflicts(when, job_id=p["job_id"])
            if clash:
                note = f" (WARNING: {when:%Y-%m-%d %H:%M} clashes with {clash[0]['company']} at {clash[0]['when']:%H:%M}; no .ics written)"
            else:
                ics(db.get_job(p["job_id"]), when)
        if p.get("job_id") and p.get("new_status"):
            job = db.get_job(p["job_id"])
            if db.STATUSES.index(p["new_status"]) > db.STATUSES.index(job["status"]):
                db.set_status(p["job_id"], p["new_status"], "(after reply)", actor="agent", actor_id=p.get("_tool"),
                              evidence={"mail_sent": p.get("subject", "")}, approval_id=p.get("_pid"))
    except BaseException as e:
        note += f" (sent; follow-up step failed: {e})"
    return f"sent to {p['to']}: {p['subject']}{note}"


def _status(p: dict) -> str:
    now = db.get_job(p["job_id"])["status"]
    if p.get("from_status") and now != p["from_status"]:
        raise Stale(f"stale: #{p['job_id']} moved from {p['from_status']} to {now} since this was proposed; nothing changed")
    db.set_status(p["job_id"], p["status"], p.get("note", ""), actor="agent", actor_id=p.get("_tool"),
                  evidence=p.get("evidence"), approval_id=p.get("_pid"))
    return f"#{p['job_id']} -> {p['status']}"


def _add_job(p: dict) -> str:
    jid = db.add_job(p["company"], p["title"], p.get("url"), p.get("jd"), p.get("notes"), p.get("ats_feed"),
                     **{k: p[k] for k in ("location", "posted_at") if p.get(k)})  # validated: an edited bad date fails here
    if p.get("posting_key"):  # auto_track: the All jobs row it came from (its text key: a rowid can be handed out again)
        db.con().execute("UPDATE postings SET job_id=? WHERE key=? AND job_id IS NULL", (jid, str(p["posting_key"])))
        db.con().commit()
    if p.get("contact_email"):
        db.update_job(jid, contact_email=p["contact_email"], contact_name=p.get("contact_name", ""))
    m = p.get("message_id") and db.mail_by_message_id(p["message_id"])
    if m and m["job_id"] is None:  # proposed from mail: file that mail under the new job (it leaves Unmatched)
        db.link_mail(m["id"], jid)
    return f"tracked #{jid} {p['company']} - {p['title']}"


def _answer(p: dict) -> str:
    db.save_answer(p["question"], p["answer"], p.get("tags", ""), source=p.get("source"))
    return f"saved answer for '{p['question'][:60]}'"


def _run_to(p: dict) -> str:
    """An approved Autopilot batch: runs the listed pipeline steps of one job (a thread in the app, inline in the CLI).
    Manual steps (apply, offer, close) never run, whatever an edited payload lists."""
    from . import pipeline

    job = db.get_job(p["job_id"])
    if p.get("from_status") and job["status"] != p["from_status"]:
        raise Stale(f"stale: #{p['job_id']} moved to {job['status']}; nothing ran")
    if p.get("to") not in pipeline.REGISTRY:
        raise SystemExit(f"unknown step {str(p.get('to'))[:30]!r}")
    stages = [s for s in p.get("stages") or [] if s in pipeline.REGISTRY]
    pipeline.kick(p["job_id"], None, origin="approved", to=p["to"], only=set(stages))
    return f"started #{p['job_id']} to {p['to']}: {' -> '.join(stages)} (outcome in the drawer's run log)"


def _note(p: dict) -> str:
    db.add_event(p["job_id"], "note", p["text"])
    return "noted"


def _submit_app(p: dict) -> str:
    """Approve a filled application: the agent window that holds it submits it (apply_agent._watch sees 'approved')."""
    from . import apply_agent

    run = db.get_run(int(p["run_id"]))
    if run["job_id"] != p.get("job_id") or run["plan_hash"] != p.get("plan_hash"):
        raise Stale("stale: the form changed since this was proposed; the newer version is in the Inbox")
    if not apply_agent.alive(run):
        raise Stale(f"stale: the agent window for run #{run['id']} is closed; use Apply for me again (your answers are kept)")
    if why := apply_agent.already_submitted(run["job_id"], but=run["id"]):
        raise Stale(f"stale: {why}; nothing was sent")
    by = "auto" if run["mode"] == "auto" else "approved"
    if not db.claim_run(run["id"], "awaiting_approval", "approved", submitted_by=by):
        raise Stale(f"stale: run #{run['id']} is {db.get_run(run['id'])['state']}")
    job = db.get_job(run["job_id"])
    return (f"approved: Lodestar submits #{job['id']} {job['company']} in the agent window; it moves to applied when the "
            "employer's confirmation page appears")


def record_submission(run_id: int) -> str:
    """After the agent saw the confirmation page of a submission whose Inbox item was approved (by you, or by the auto
    tool): the job moves to applied with the evidence. Reachable only for an approved submit_application item."""
    run = db.get_run(run_id)
    item = db.get_pending(run["pending_id"]) if run["pending_id"] else None
    if run["state"] != "confirmed" or not item or item["kind"] != "submit_application" or item["status"] != "done":
        raise SystemExit(f"run #{run_id} has no approved, confirmed submission to record")
    job = db.get_job(run["job_id"])
    note = (f"(apply agent run #{run_id}, {'automatic' if run['submitted_by'] == 'auto' else 'approved by you'}: "
            f"{('confirmation ' + run['confirmation']) if run['confirmation'] else 'confirmation page seen'})")
    if db.STATUSES.index(job["status"]) < db.STATUSES.index("applied"):  # saved only: never moves a closed job
        db.set_status(job["id"], "applied", note, actor="agent", actor_id="apply_agent", evidence={"apply_run": run_id},
                      approval_id=run["pending_id"])
    db.add_event(job["id"], "apply_evidence", run["evidence"] or "")
    return note


EXECUTORS = {"send_email": _send, "set_status": _status, "add_job": _add_job, "save_answer": _answer, "note": _note,
             "run_to": _run_to, "submit_application": _submit_app}
