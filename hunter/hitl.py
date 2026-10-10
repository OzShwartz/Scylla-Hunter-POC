"""Human-in-the-loop approval routing and review decisions (PRD §9.6, FR-7)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from hunter import db, validators
from hunter.models import Config, DraftResult
from hunter.scoring import evidence_signals_for_account


def determine_route(
    *,
    account_score: int,
    validators_passed: bool,
    has_high_confidence_evidence: bool,
    has_sensitive_content: bool,
    config: Config,
) -> tuple[str, str, str]:
    """Returns (approval_route, status, reason) per PRD §9.6's routing table.

    Score reflects lead *quality*; it says nothing about message *risk*. A
    high-scoring account can still produce a draft that references a
    competitor product, the IBM/DataStax acquisition, or contract/renewal
    terms - that always goes to a human, regardless of score or approval_mode.
    """
    if config.runtime.approval_mode == "all":
        return "human", "PENDING_APPROVAL", "approval_mode=all: every draft requires human review, regardless of score"

    if not validators_passed:
        return "human", "PENDING_APPROVAL", "forced: validator failed after one retry"

    if has_sensitive_content:
        return (
            "human",
            "PENDING_APPROVAL",
            "forced: mentions a competitor product, the IBM/DataStax acquisition, or a renewal/contract - "
            "overrides account score and approval_mode (PRD §9.6)",
        )

    if config.runtime.approval_mode == "off":
        return "auto", "APPROVED", "approval_mode=off: auto-approved (testing only)"

    if not has_high_confidence_evidence:
        return "human", "PENDING_APPROVAL", "forced: no high-confidence evidence item cited"

    threshold = config.hitl.auto_send_min_account_score
    if account_score >= threshold:
        return "auto", "APPROVED", f"account score {account_score} >= auto-approve threshold {threshold}"
    return (
        "human",
        "PENDING_APPROVAL",
        f"account score {account_score} is below the auto-approve threshold of {threshold}",
    )


def _route_inputs_for_message(conn: sqlite3.Connection, message: sqlite3.Row) -> tuple[bool, bool, bool]:
    """Recomputes determine_route's inputs from a stored message, for `review` display.

    Messages have no persisted "reason" column (PRD §13's ERD gives one to
    accounts and leads, not messages), so the routing reason shown in `review`
    is recomputed from what *is* stored: the confidence of cited evidence, a
    recorded validator failure, and a text-based sensitivity check. This can't
    see context_fact_ids (not persisted on messages either), so the cf_ibm
    sensitivity trigger isn't recoverable here - only the body/subject regex
    checks (competitor product, renewal/contract) are.
    """
    evidence_ids = json.loads(message["evidence_ids"])
    has_high_confidence_evidence = any(
        row is not None and row["confidence"] == "high" for row in (db.get_signal(conn, eid) for eid in evidence_ids)
    )
    validators_passed = not bool(message["reviewer_note"])
    text = f"{message['subject'] or ''} {message['body']}"
    has_sensitive_content = bool(
        validators.COMPETITOR_MENTION_PATTERN.search(text) or validators.RENEWAL_CONTRACT_PATTERN.search(text)
    )
    return has_high_confidence_evidence, validators_passed, has_sensitive_content


def explain_route(conn: sqlite3.Connection, message: sqlite3.Row, account: sqlite3.Row, config: Config) -> str:
    """The human-readable reason a draft was routed where it was - score band vs
    content-sensitivity override (PRD §9.6), for FR-7's `review` output."""
    has_high_confidence_evidence, validators_passed, has_sensitive_content = _route_inputs_for_message(conn, message)
    _, _, reason = determine_route(
        account_score=account["account_score"],
        validators_passed=validators_passed,
        has_high_confidence_evidence=has_high_confidence_evidence,
        has_sensitive_content=has_sensitive_content,
        config=config,
    )
    return reason


def list_pending(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """FR-7: drafts waiting on a human decision."""
    return db.list_messages(conn, status="PENDING_APPROVAL")


def _require_pending(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row:
    message = db.get_message(conn, message_id)
    if message is None:
        raise ValueError(f"No message #{message_id}")
    if message["status"] != "PENDING_APPROVAL":
        raise ValueError(f"Message #{message_id} is {message['status']}, not PENDING_APPROVAL")
    return message


def approve(conn: sqlite3.Connection, message_id: int, *, now: datetime) -> sqlite3.Row:
    """FR-7: approve a pending draft."""
    message = _require_pending(conn, message_id)
    db.update_message_status(conn, message_id, status="APPROVED")
    db.insert_event(
        conn,
        lead_id=message["lead_id"],
        run_id=message["run_id"],
        type="message_approved",
        payload={"message_id": message_id},
        occurred_at=now,
    )
    return db.get_message(conn, message_id)


def reject(conn: sqlite3.Connection, message_id: int, *, reason: str, now: datetime) -> sqlite3.Row:
    """FR-7: reject a pending draft with a reason."""
    message = _require_pending(conn, message_id)
    db.update_message_status(conn, message_id, status="REJECTED", reviewer_note=reason)
    db.insert_event(
        conn,
        lead_id=message["lead_id"],
        run_id=message["run_id"],
        type="message_rejected",
        payload={"message_id": message_id, "reason": reason},
        occurred_at=now,
    )
    return db.get_message(conn, message_id)


def edit(
    conn: sqlite3.Connection, message_id: int, *, text: str, config: Config, now: datetime
) -> tuple[sqlite3.Row, list[str]]:
    """FR-7: edit a pending draft's body, keeping the original, and re-run the
    validators on the edited text. Validators passing is treated as the human's
    approval of their own edit; a draft that still fails stays PENDING_APPROVAL
    so it can be edited again or rejected.
    """
    message = _require_pending(conn, message_id)
    lead = db.get_lead(conn, message["lead_id"])
    account = db.get_account(conn, lead["account_id"])
    evidence_signals = evidence_signals_for_account(conn, account["id"])

    draft = DraftResult(
        subject=message["subject"],
        body=text,
        evidence_ids=json.loads(message["evidence_ids"]),
        value_prop_ids=json.loads(message["value_prop_ids"]),
    )
    errors = validators.validate_message(
        draft,
        variant=message["variant"],
        persona=lead["persona"],
        first_name=lead["first_name"],
        company_name=account["name"],
        evidence_signals=evidence_signals,
        config=config,
    )

    original_body = message["original_body"] or message["body"]
    status = "PENDING_APPROVAL" if errors else "APPROVED"
    db.update_message_status(
        conn,
        message_id,
        status=status,
        original_body=original_body,
        body=text,
        reviewer_note="; ".join(errors),
    )
    db.insert_event(
        conn,
        lead_id=message["lead_id"],
        run_id=message["run_id"],
        type="message_edited",
        payload={"message_id": message_id, "status": status, "errors": errors},
        occurred_at=now,
    )
    return db.get_message(conn, message_id), errors
