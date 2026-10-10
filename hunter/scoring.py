"""Deterministic account scoring and lead selection (PRD §9). No LLM calls here."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime

from hunter import db
from hunter.models import Config


@dataclass
class AccountScore:
    evidence_points: float
    icp_points: int
    why_now_points: int
    account_score: int
    status: str
    reason: str


def signal_age_months(published_at: date, as_of: date) -> float:
    return (as_of - published_at).days / 30.44


def compute_signal_value(
    *, type_: str, published_at: date, confidence: str | None, as_of: date, config: Config
) -> float:
    if confidence is None:
        return 0.0
    weight = config.signals.weights.get(type_, 0.0)
    confidence_factor = config.signals.confidence.get(confidence, 0.0)
    age_months = signal_age_months(published_at, as_of)
    decay = 0.5 ** (age_months / config.signals.recency_half_life_months)
    return weight * decay * confidence_factor


def is_evidence_signal(row: sqlite3.Row) -> bool:
    return bool(row["uses_competitor"]) or bool(row["uses_cassandra"])


def evidence_signals_for_account(conn: sqlite3.Connection, account_id: str) -> list[sqlite3.Row]:
    return [row for row in db.list_signals_for_account(conn, account_id) if is_evidence_signal(row)]


def _shows_intent(row: sqlite3.Row, config: Config) -> bool:
    if row["why_now"]:
        return True
    text = (row["raw_text"] or "").lower()
    if any(kw in text for kw in config.signals.why_now.migration_keywords):
        return True
    return row["type"] == "champion_move"


def _size_band_points(employees: int, config: Config) -> int:
    for band in config.icp.employee_bands:
        if employees >= band.min and (band.max is None or employees <= band.max):
            return band.points
    return 0


def score_account(
    conn: sqlite3.Connection, account_row: sqlite3.Row, config: Config, as_of: date
) -> AccountScore:
    domain = account_row["domain"]

    # 1. Suppression gates (PRD §9.1 step 1)
    if domain in config.suppression.competitor_domains:
        return AccountScore(0, 0, 0, 0, "SUPPRESSED", "Competitor domain")
    if domain in config.suppression.existing_customer_domains:
        return AccountScore(0, 0, 0, 0, "SUPPRESSED", "Existing ScyllaDB customer domain")

    # 2. Account gates (PRD §9.1 step 2)
    employees = account_row["employees"]
    signals = db.list_signals_for_account(conn, account_row["id"])
    evidence_signals = [s for s in signals if is_evidence_signal(s)]

    if employees is None:
        return AccountScore(0, 0, 0, 0, "NEEDS_ENRICHMENT", "Employees unknown (live source)")
    if employees < config.icp.min_employees:
        return AccountScore(
            0, 0, 0, 0, "REJECTED",
            f"Gate: {employees} employees, below ICP min_employees={config.icp.min_employees}",
        )
    if not evidence_signals:
        return AccountScore(0, 0, 0, 0, "REJECTED", "Gate: no technology evidence")

    # Update and collect each evidence signal's decayed value.
    values: list[float] = []
    for row in evidence_signals:
        value = compute_signal_value(
            type_=row["type"],
            published_at=date.fromisoformat(row["published_at"]),
            confidence=row["confidence"],
            as_of=as_of,
            config=config,
        )
        db.update_signal_value(conn, row["id"], value)
        values.append(value)

    top_values = sorted(values, reverse=True)[: config.signals.top_n_signals]
    evidence_points = min(config.signals.max_evidence_points, sum(top_values))

    icp_points = _size_band_points(employees, config)
    if account_row["industry"] in config.icp.priority_industries:
        icp_points += config.icp.industry_bonus

    why_now_points = 0
    for row in evidence_signals:
        age = signal_age_months(date.fromisoformat(row["published_at"]), as_of)
        if age <= config.signals.why_now.window_months and _shows_intent(row, config):
            why_now_points = config.signals.why_now.bonus
            break

    account_score = round(evidence_points + icp_points + why_now_points)

    # 3. Score threshold (PRD §9.1 step 3)
    if account_score >= config.scoring.account_threshold:
        reason = (
            f"Account score {account_score} >= threshold {config.scoring.account_threshold} "
            f"(evidence={evidence_points:.1f}, icp={icp_points}, why_now={why_now_points})"
        )
        return AccountScore(evidence_points, icp_points, why_now_points, account_score, "QUALIFIED", reason)

    reason = f"Account score {account_score} below threshold {config.scoring.account_threshold}"
    return AccountScore(evidence_points, icp_points, why_now_points, account_score, "REJECTED", reason)


def generate_people_query(account_row: sqlite3.Row, config: Config) -> dict:
    """FR-4: the exact people-API request the system would send for a qualified account."""
    return {
        "company_domain": account_row["domain"],
        "company_name": account_row["name"],
        "target_titles": {
            "decision_maker": config.personas.decision_maker.titles,
            "practitioner": config.personas.practitioner.titles,
        },
        "exclude_departments": config.personas.excluded_departments,
        "limit": config.scoring.max_leads_per_account,
    }


def score_accounts(conn: sqlite3.Connection, config: Config, as_of: date) -> None:
    for account_row in db.list_accounts(conn):
        result = score_account(conn, account_row, config, as_of)
        people_query = None
        if result.status == "QUALIFIED":
            people_query = generate_people_query(account_row, config)
        db.update_account_score(
            conn,
            account_row["id"],
            evidence_points=result.evidence_points,
            icp_points=result.icp_points,
            why_now_points=result.why_now_points,
            account_score=result.account_score,
            status=result.status,
            reason=result.reason,
            people_query=people_query,
        )


def _is_named_in_signal(conn: sqlite3.Connection, lead_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM signals WHERE person_id = ? LIMIT 1", (lead_id,)).fetchone()
    return row is not None


def _has_profile_skill_match(skills: list[str], config: Config) -> bool:
    keywords = config.personas.profile_skill_keywords
    return any(kw in s.lower() for s in skills for kw in keywords)


def _persona_for_title(title: str, config: Config) -> str | None:
    if title in config.personas.decision_maker.titles:
        return "decision_maker"
    if title in config.personas.practitioner.titles:
        return "practitioner"
    return None


def select_leads(conn: sqlite3.Connection, config: Config, now: datetime) -> None:
    for account_row in db.list_accounts(conn):
        leads = db.list_leads_for_account(conn, account_row["id"])

        if account_row["status"] == "SUPPRESSED":
            for lead in leads:
                db.update_lead_status(
                    conn, lead["id"], status="SUPPRESSED",
                    reason=f"Account suppressed: {account_row['reason']}", updated_at=now,
                )
            continue

        if account_row["status"] != "QUALIFIED":
            for lead in leads:
                db.update_lead_status(
                    conn, lead["id"], status="REJECTED",
                    reason=f"Account not qualified: {account_row['reason']}", updated_at=now,
                )
            continue

        eligible = []
        for lead in leads:
            if lead["email"] in config.suppression.opted_out_emails:
                db.update_lead_status(
                    conn, lead["id"], status="SUPPRESSED", reason="Email is on the opt-out list", updated_at=now,
                )
                continue
            if config.suppression.already_contacted and any(
                m["status"] == "SENT" for m in db.list_messages_for_lead(conn, lead["id"])
            ):
                db.update_lead_status(
                    conn, lead["id"], status="SUPPRESSED",
                    reason="Already contacted (has a SENT message)", updated_at=now,
                )
                continue
            if lead["department"] in config.personas.excluded_departments:
                db.update_lead_status(
                    conn, lead["id"], status="REJECTED",
                    reason=f"Gate: excluded department ({lead['department']})", updated_at=now,
                )
                continue
            persona = _persona_for_title(lead["title"], config)
            if persona is None:
                db.update_lead_status(
                    conn, lead["id"], status="REJECTED",
                    reason=f"Gate: title '{lead['title']}' matches no persona", updated_at=now,
                )
                continue
            eligible.append((lead, persona))

        def sort_key(item):
            lead, persona = item
            priority = (
                config.personas.decision_maker.priority
                if persona == "decision_maker"
                else config.personas.practitioner.priority
            )
            named = _is_named_in_signal(conn, lead["id"])
            skill_match = _has_profile_skill_match(json.loads(lead["skills"]), config)
            return (priority, 0 if named else 1, 0 if skill_match else 1)

        eligible.sort(key=sort_key)

        for rank, (lead, persona) in enumerate(eligible, start=1):
            if rank <= config.scoring.max_leads_per_account:
                db.update_lead_status(
                    conn, lead["id"], status="QUALIFIED",
                    reason=f"Selected: rank {rank} at a qualified account (score {account_row['account_score']})",
                    persona=persona, rank=rank, updated_at=now,
                )
            else:
                db.update_lead_status(
                    conn, lead["id"], status="DEPRIORITIZED",
                    reason=f"Qualified but rank {rank} exceeds max_leads_per_account={config.scoring.max_leads_per_account}",
                    persona=persona, rank=rank, updated_at=now,
                )
