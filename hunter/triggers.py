"""Trigger rules R1-R3, simulated clock and scripted events (PRD §12).

R1 (lead_qualified -> draft invite) already runs inside personalize.draft_invites_for_qualified_leads,
called from `hunter run`. This module is R2 and R3, plus the simulated clock
that drives them in the PoC (PRD §12.2): `hunter event connection-accepted`
and `hunter simulate --days N`. Every drafted message goes through the same
personalize.draft_message -> validators -> hitl.determine_route path as R1,
so routing and grounding are identical regardless of which rule fired.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from hunter import db, personalize
from hunter.models import Config, SimulatedEvent


@dataclass
class TriggerStats:
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    warm_drafted: list[str] = field(default_factory=list)  # lead ids
    cold_drafted: list[str] = field(default_factory=list)
    forced_review: list[int] = field(default_factory=list)  # message ids


def _rule(config: Config, rule_id: str):
    return next(r for r in config.sequence if r.id == rule_id)


def _has_message(conn: sqlite3.Connection, lead_id: str, variant: str) -> bool:
    return any(m["variant"] == variant for m in db.list_messages_for_lead(conn, lead_id))


def _draft_follow_up(
    conn: sqlite3.Connection, config: Config, lead_id: str, *, variant: str, previous_interaction: str,
    llm_mode: str, run_id: int | None, now: datetime, stats: TriggerStats,
) -> int:
    lead = db.get_lead(conn, lead_id)
    account = db.get_account(conn, lead["account_id"])
    personalize_stats = personalize.PersonalizationStats()
    message_id = personalize.draft_message(
        conn, lead=lead, account=account, config=config, variant=variant,
        llm_mode=llm_mode, run_id=run_id, now=now, previous_interaction=previous_interaction,
        stats=personalize_stats,
    )
    stats.llm_calls += personalize_stats.llm_calls
    stats.tokens_in += personalize_stats.tokens_in
    stats.tokens_out += personalize_stats.tokens_out
    stats.forced_review.extend(personalize_stats.forced_review)
    return message_id


def handle_connection_accepted(
    conn: sqlite3.Connection, config: Config, lead_id: str, *, llm_mode: str, run_id: int | None, now: datetime,
    stats: TriggerStats,
) -> int | None:
    """R2: an INVITED lead's connection is accepted -> ACCEPTED, draft a warm
    email. A no-op (idempotent) for any lead not currently INVITED - already
    accepted, already emailed, or never invited.
    """
    lead = db.get_lead(conn, lead_id)
    if lead is None or lead["status"] != "INVITED" or _has_message(conn, lead_id, "warm"):
        return None

    db.update_lead_status(conn, lead_id, status="ACCEPTED", reason="connection_accepted", updated_at=now)
    db.insert_event(
        conn, lead_id=lead_id, run_id=run_id, type="connection_accepted", payload={}, occurred_at=now
    )

    previous_interaction = (
        f"Previous interaction: you sent {lead['first_name']} a LinkedIn invite, and they just accepted it."
    )
    message_id = _draft_follow_up(
        conn, config, lead_id, variant="warm", previous_interaction=previous_interaction,
        llm_mode=llm_mode, run_id=run_id, now=now, stats=stats,
    )
    stats.warm_drafted.append(lead_id)
    return message_id


def handle_no_accept_after_days(
    conn: sqlite3.Connection, config: Config, lead_id: str, *, llm_mode: str, run_id: int | None, now: datetime,
    stats: TriggerStats,
) -> int | None:
    """R3: an INVITED lead with no acceptance after `sequence.R3.days` -> draft
    a cold email. A no-op (idempotent) for any lead not currently INVITED.
    """
    lead = db.get_lead(conn, lead_id)
    if lead is None or lead["status"] != "INVITED" or _has_message(conn, lead_id, "cold"):
        return None

    r3_days = _rule(config, "R3").days
    previous_interaction = (
        f"Previous interaction: you sent {lead['first_name']} a LinkedIn invite {r3_days} days ago; "
        "there has been no response."
    )
    message_id = _draft_follow_up(
        conn, config, lead_id, variant="cold", previous_interaction=previous_interaction,
        llm_mode=llm_mode, run_id=run_id, now=now, stats=stats,
    )
    stats.cold_drafted.append(lead_id)
    return message_id


def simulate(
    conn: sqlite3.Connection, config: Config, *, days: int, llm_mode: str, run_id: int | None, now: datetime,
    scripted_events: list[SimulatedEvent],
) -> TriggerStats:
    """PRD §12.2/§12.3: advance the simulated clock to `days` days after each
    lead's invite was sent. Scripted `connection_accepted` events due by then
    fire R2 in day order; any lead still INVITED once `days` reaches
    `sequence.R3.days` gets R3's cold email. Calling this again with a larger
    `days` only processes what's newly due - already-ACCEPTED/EMAILED leads
    are skipped by the same status guard `handle_*` always uses, so repeated
    or overlapping `simulate` calls are idempotent.
    """
    stats = TriggerStats()
    r3_days = _rule(config, "R3").days

    due = sorted(
        (e for e in scripted_events if e.event == "connection_accepted" and e.day is not None and e.day <= days),
        key=lambda e: e.day,
    )
    for e in due:
        handle_connection_accepted(
            conn, config, e.lead_id, llm_mode=llm_mode, run_id=run_id,
            now=now + timedelta(days=e.day), stats=stats,
        )

    if days >= r3_days:
        for lead in db.list_leads(conn):
            if lead["status"] == "INVITED":
                handle_no_accept_after_days(
                    conn, config, lead["id"], llm_mode=llm_mode, run_id=run_id,
                    now=now + timedelta(days=r3_days), stats=stats,
                )

    return stats
