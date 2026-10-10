"""Dry-run dispatch of approved messages to console and outbox.jsonl (PRD FR-9).

Never makes a real network call - "sending" means printing a [DRY RUN] block
and appending one JSON line to outbox.jsonl. FR-9a's idempotency falls out of
sweeping only status=="APPROVED" rows: once dispatched a message is SENT and
is never selected again.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from hunter import db
from hunter.models import Config

# PRD §14.4's lead lifecycle: an invite being sent advances QUALIFIED -> INVITED;
# a warm or cold email being sent advances ACCEPTED/INVITED -> EMAILED.
LEAD_STATUS_AFTER_DISPATCH = {"invite": "INVITED", "warm": "EMAILED", "cold": "EMAILED"}


@dataclass
class DispatchStats:
    sent_message_ids: list[int] = field(default_factory=list)


def _recipient(message: sqlite3.Row, lead: sqlite3.Row) -> str:
    return lead["linkedin_url"] if message["channel"] == "linkedin" else (lead["email"] or "(no email on file)")


def _console_block(message: sqlite3.Row, lead: sqlite3.Row, account: sqlite3.Row) -> str:
    width = 72
    lines = [
        "┌" + "─" * (width - 1),
        f"│ [DRY RUN] would send - {message['channel']}/{message['variant']}",
        f"│ to:      {lead['first_name']} {lead['last_name']} @ {account['name']} <{_recipient(message, lead)}>",
        f"│ route:   {message['approval_route']}",
    ]
    if message["subject"]:
        lines.append(f"│ subject: {message['subject']}")
    lines.append("│ text:")
    for line in message["body"].splitlines() or [""]:
        lines.append(f"│   {line}")
    lines.append("└" + "─" * (width - 1))
    return "\n".join(lines)


def dispatch_approved(
    conn: sqlite3.Connection, config: Config, *, run_id: int | None, now: datetime
) -> DispatchStats:
    """FR-9: "send" every currently APPROVED message - console + outbox.jsonl,
    status -> SENT, lead status advances. Safe to call after any command that
    may have produced new APPROVED rows (run, approve, edit, event, simulate);
    it is a no-op when there is nothing to send.
    """
    if not config.runtime.dry_run:
        raise RuntimeError("dispatch_approved called with dry_run=false - PRD §17.2 forbids real sending in the PoC")

    stats = DispatchStats()
    outbox_path = Path(config.runtime.outbox_path)
    outbox_path.parent.mkdir(parents=True, exist_ok=True)

    for message in db.list_messages(conn, status="APPROVED"):
        lead = db.get_lead(conn, message["lead_id"])
        account = db.get_account(conn, lead["account_id"])

        print(_console_block(message, lead, account))

        record = {
            "message_id": message["id"],
            "lead_id": lead["id"],
            "lead_name": f"{lead['first_name']} {lead['last_name']}",
            "account": account["name"],
            "channel": message["channel"],
            "variant": message["variant"],
            "recipient": _recipient(message, lead),
            "approval_route": message["approval_route"],
            "subject": message["subject"],
            "body": message["body"],
            "evidence_ids": json.loads(message["evidence_ids"]),
            "sent_at": now.isoformat(),
        }
        with open(outbox_path, "a") as f:
            f.write(json.dumps(record) + "\n")

        db.update_message_status(conn, message["id"], status="SENT", sent_at=now)
        db.update_lead_status(
            conn, lead["id"],
            status=LEAD_STATUS_AFTER_DISPATCH[message["variant"]],
            reason=f"{message['variant']} {message['channel']} dispatched (dry-run)",
            updated_at=now,
        )
        db.insert_event(
            conn, lead_id=lead["id"], run_id=run_id, type="message_sent",
            payload={"message_id": message["id"], "channel": message["channel"], "variant": message["variant"]},
            occurred_at=now,
        )
        stats.sent_message_ids.append(message["id"])

    return stats
