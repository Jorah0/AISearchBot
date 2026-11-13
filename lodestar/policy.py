"""The central policy service (blueprint 17.2, pass 25): one deterministic decision for every proposed action, never an
LLM's. authorize() -> ALLOW (the tool is on auto and nothing needs you) | REQUIRE_APPROVAL (the Inbox) | BLOCK, with
reason codes and the policy version; approvals.propose acts on it and every decision and executor run is written to the
append-only audit table. The older guards (full_ai_check, the floor screen, attachment and slot checks) stay where they
are: defence in depth, not replaced."""
import json

from . import config, db, settings

VERSION = "1"
# blueprint 9.4 / 10.5: never sent on Lodestar's own initiative, whatever the tool's auto switch says
REASONS = {
    "full_ai": "Full AI never sends, moves or adds anything",
    "tool_disabled": "the tool is off (Tools)",
    "withdrawal_or_acceptance": "a withdrawal or acceptance always waits for you",
    "scheduling_commitment": "a scheduling commitment always waits for you",
    "unverified_sender": "it answers mail from a sender Lodestar could not verify",
    "attachments": "files only leave after you have seen the mail",
    "offer_correspondence": "offer and negotiation mail always waits for you",
    "requested_review": "the caller asked for your review",
    "tool_manual": "the tool is on manual (Tools)",
    "tool_auto": "the tool is on auto and nothing needs you",
}


def authorize(tool: str, kind: str, payload: dict, job_id: int | None = None, force_pending: bool = False) -> dict:
    """{result, reasons, policy_version} for one proposed action. Deterministic: same input, same decision."""
    def out(result, reasons):
        return {"result": result, "reasons": reasons, "policy_version": VERSION}

    if getattr(config.FULL_AI, "on", False):
        return out("BLOCK", ["full_ai"])
    if not settings.enabled(tool):
        return out("BLOCK", ["tool_disabled"])
    p, why = payload or {}, []
    if kind == "send_email":
        if p.get("new_status") in ("withdrawn", "accepted", "rejected"):
            why.append("withdrawal_or_acceptance")
        if p.get("chosen_time"):
            why.append("scheduling_commitment")
        if p.get("unverified"):
            why.append("unverified_sender")
        if p.get("attachments"):
            why.append("attachments")
        if job_id and db.get_job(job_id)["status"] in ("offer", "accepted"):
            why.append("offer_correspondence")
    # submit_application: blueprint 9.3 allows narrow, opted-in automation; apply_agent.auto_blockers holds its gates
    if force_pending:
        why.append("requested_review")
    if not settings.auto(tool):
        why.append("tool_manual")
    return out("REQUIRE_APPROVAL", why) if why else out("ALLOW", ["tool_auto"])


def record(action: str, tool: str | None, job_id: int | None, result: str, reasons=(), approval_id: int | None = None) -> None:
    """One append-only audit row (the triggers refuse UPDATE and DELETE)."""
    db.con().execute("INSERT INTO audit(action, tool, target, result, reasons, policy_version, approval_id) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?)",
                     (action, tool, f"job #{job_id}" if job_id else None, result, json.dumps(list(reasons)), VERSION,
                      approval_id))
    db.con().commit()


def log(limit: int = 100) -> list[dict]:
    """The audit trail, newest first."""
    return [dict(r) for r in db.con().execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (int(limit),))]
