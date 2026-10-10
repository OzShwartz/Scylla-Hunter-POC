"""LLM-based LinkedIn invite and email drafting (PRD §11.5)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import ValidationError

from hunter import db, hitl, validators
from hunter.llm import PromptSpec, call_llm, load_prompt_spec
from hunter.models import Config, DraftResult
from hunter.scoring import evidence_signals_for_account

PROMPT_PATH = "prompts/personalize.md"


@dataclass
class PersonalizationStats:
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    forced_review: list[int] = field(default_factory=list)  # message ids forced to review


def _render_evidence_block(evidence_signals: list[sqlite3.Row]) -> str:
    if not evidence_signals:
        return "(none)"
    lines = []
    for row in evidence_signals:
        lines.append(
            f"- {row['id']} | {row['type']} | {row['published_at']} | {row['confidence']} | "
            f"excerpt (verbatim fragment, NOT a title - see system rules): \"{row['evidence_quote'] or ''}\" | "
            f"use_case: {row['use_case'] or 'n/a'} | why_now: {row['why_now'] or 'n/a'}"
        )
    return "\n".join(lines)


def _render_value_props_block(persona: str, config: Config) -> str:
    allowed_ids = (
        config.personas.decision_maker.angles if persona == "decision_maker" else config.personas.practitioner.angles
    )
    by_id = {vp.id: vp.text for vp in config.messaging.value_props}
    return "\n".join(f"- {vp_id}: {by_id[vp_id]}" for vp_id in allowed_ids if vp_id in by_id)


def _render_context_facts_block(config: Config) -> str:
    return "\n".join(f"- {cf.id}: {cf.text}" for cf in config.messaging.context_facts)


def _render_system(spec: PromptSpec, config: Config) -> str:
    rules_block = "\n".join(f"- {r}" for r in config.messaging.rules)
    return spec.system.format(
        sender_name=config.messaging.sender.name,
        sender_title=config.messaging.sender.title,
        sender_company=config.messaging.sender.company,
        rules_block=rules_block,
        banned_phrases=", ".join(repr(p) for p in config.messaging.banned_phrases),
        linkedin_max_chars=config.messaging.linkedin_invite_max_chars,
        email_max_words=config.messaging.email_max_words,
    )


def _render_user(
    spec: PromptSpec,
    *,
    lead: sqlite3.Row,
    account: sqlite3.Row,
    evidence_signals: list[sqlite3.Row],
    config: Config,
    variant: str,
    previous_interaction: str,
) -> str:
    return spec.user_template.format(
        first_name=lead["first_name"],
        title=lead["title"],
        persona=lead["persona"],
        company=account["name"],
        variant=variant,
        previous_interaction=previous_interaction,
        evidence_block=_render_evidence_block(evidence_signals),
        value_props_block=_render_value_props_block(lead["persona"], config),
        context_facts_block=_render_context_facts_block(config),
    )


def draft_message(
    conn: sqlite3.Connection,
    *,
    lead: sqlite3.Row,
    account: sqlite3.Row,
    config: Config,
    variant: str,
    llm_mode: str,
    run_id: int | None,
    now: datetime,
    previous_interaction: str = "",
    stats: PersonalizationStats,
) -> int:
    spec = load_prompt_spec(PROMPT_PATH)
    system = _render_system(spec, config)
    evidence_signals = evidence_signals_for_account(conn, account["id"])
    user = _render_user(
        spec, lead=lead, account=account, evidence_signals=evidence_signals,
        config=config, variant=variant, previous_interaction=previous_interaction,
    )

    def call_once(user_text: str) -> tuple[DraftResult, str, list[str]]:
        result = call_llm(
            mode=llm_mode,
            system=system,
            user=user_text,
            model=config.llm.models.personalization,
            max_tokens=config.llm.max_tokens.personalization,
            prompt_version=spec.version,
            replay_dir=config.llm.replay_dir,
            output_schema=DraftResult.model_json_schema(),
            effort=config.llm.effort.personalization,
        )
        stats.llm_calls += 1
        stats.tokens_in += result.tokens_in
        stats.tokens_out += result.tokens_out
        try:
            return DraftResult.model_validate(json.loads(result.text)), result.model, []
        except (json.JSONDecodeError, ValidationError) as e:
            # PRD §11.7: invalid JSON is a failure like any other - retry once, then
            # force human review, never crash the run over one bad response.
            fallback = DraftResult(body=result.text[:2000])
            return fallback, result.model, [f"LLM response was not valid JSON matching the schema: {e}"]

    def validate(draft: DraftResult) -> list[str]:
        return validators.validate_message(
            draft, variant=variant, persona=lead["persona"], first_name=lead["first_name"],
            company_name=account["name"], evidence_signals=evidence_signals, config=config,
        )

    draft, model_used, errors = call_once(user)
    errors = errors or validate(draft)

    if errors and config.llm.max_retries_on_validation_fail > 0:
        retry_user = (
            user
            + "\n\nYour previous attempt failed validation for these reasons:\n"
            + "\n".join(f"- {e}" for e in errors)
            + "\n\nFix all of these issues and return corrected JSON."
        )
        draft, model_used, errors = call_once(retry_user)
        errors = errors or validate(draft)

    has_high_confidence_evidence = any(
        row["id"] in draft.evidence_ids and row["confidence"] == "high" for row in evidence_signals
    )
    approval_route, status, route_reason = hitl.determine_route(
        account_score=account["account_score"],
        validators_passed=not errors,
        has_high_confidence_evidence=has_high_confidence_evidence,
        has_sensitive_content=validators.is_sensitive_content(draft),
        config=config,
    )

    channel = "linkedin" if variant == "invite" else "email"
    message_id = db.insert_message(
        conn,
        lead_id=lead["id"],
        run_id=run_id,
        channel=channel,
        variant=variant,
        subject=draft.subject,
        body=draft.body,
        evidence_ids=draft.evidence_ids,
        value_prop_ids=draft.value_prop_ids,
        approval_route=approval_route,
        status=status,
        prompt_version=spec.version,
        model=model_used,
        tokens=stats.tokens_in + stats.tokens_out,
        created_at=now,
    )
    if errors:
        db.update_message_status(conn, message_id, status=status, reviewer_note="; ".join(errors))
        stats.forced_review.append(message_id)

    db.insert_event(
        conn, lead_id=lead["id"], run_id=run_id, type="message_drafted",
        payload={
            "message_id": message_id, "variant": variant, "approval_route": approval_route,
            "status": status, "reason": route_reason,
        },
        occurred_at=now,
    )
    return message_id


def draft_invites_for_qualified_leads(
    conn: sqlite3.Connection, config: Config, *, llm_mode: str, run_id: int | None, now: datetime
) -> PersonalizationStats:
    """R1: a qualified lead with no prior invite gets a LinkedIn invite drafted and routed."""
    stats = PersonalizationStats()
    for lead in db.list_leads(conn):
        if lead["status"] != "QUALIFIED":
            continue
        existing = [m for m in db.list_messages_for_lead(conn, lead["id"]) if m["variant"] == "invite"]
        if existing:
            continue
        account = db.get_account(conn, lead["account_id"])
        draft_message(
            conn, lead=lead, account=account, config=config, variant="invite",
            llm_mode=llm_mode, run_id=run_id, now=now, stats=stats,
        )
    return stats
