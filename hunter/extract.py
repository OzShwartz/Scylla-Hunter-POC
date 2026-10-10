"""LLM-based signal extraction (PRD §11.3) and champion detection (FR-5)."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from hunter import db
from hunter.llm import LLMResult, PromptSpec, call_llm, load_prompt_spec
from hunter.models import Config, ExtractionResult, FixturePerson, FixtureRawSignal, Fixtures

PROMPT_PATH = "prompts/extract_signals.md"


@dataclass
class ExtractionStats:
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    flagged: list[str] = field(default_factory=list)  # signal ids whose grounding check failed


def _render_user_message(spec: PromptSpec, raw: FixtureRawSignal) -> str:
    return spec.user_template.format(
        source_type=raw.type,
        source_url=raw.source_url,
        published_at=raw.published_at.isoformat(),
        text=raw.text,
    )


def _apply_grounding(result: ExtractionResult, source_text: str) -> ExtractionResult:
    """PRD §11.4: evidence_quote must be verbatim; named_people must appear in the text."""
    data = result.model_dump()

    if data["evidence_quote"] is not None and data["evidence_quote"] not in source_text:
        data["confidence"] = "low"
        data["evidence_quote"] = None

    data["named_people"] = [
        p for p in data["named_people"] if p["name"] in source_text
    ]

    return ExtractionResult.model_validate(data)


def _resolve_person_id(name: str, people: list[FixturePerson]) -> str | None:
    normalized = name.strip().lower()
    for p in people:
        if f"{p.first_name} {p.last_name}".strip().lower() == normalized:
            return p.id
    return None


def extract_signals(
    conn: sqlite3.Connection,
    fixtures: Fixtures,
    config: Config,
    *,
    llm_mode: str,
) -> ExtractionStats:
    spec = load_prompt_spec(PROMPT_PATH)
    stats = ExtractionStats()

    for raw in fixtures.raw_signals:
        user_message = _render_user_message(spec, raw)
        result: LLMResult = call_llm(
            mode=llm_mode,
            system=spec.system,
            user=user_message,
            model=config.llm.models.extraction,
            max_tokens=config.llm.max_tokens.extraction,
            temperature=config.llm.temperature,
            prompt_version=spec.version,
            replay_dir=config.llm.replay_dir,
            output_schema=ExtractionResult.model_json_schema(),
            effort=config.llm.effort.extraction,
        )
        stats.llm_calls += 1
        stats.tokens_in += result.tokens_in
        stats.tokens_out += result.tokens_out

        extraction = ExtractionResult.model_validate(json.loads(result.text))
        grounded = _apply_grounding(extraction, raw.text)
        if grounded.confidence != extraction.confidence:
            stats.flagged.append(raw.id)

        person_id = None
        for named in grounded.named_people:
            person_id = _resolve_person_id(named.name, fixtures.people)
            if person_id:
                break

        db.insert_signal(
            conn,
            id=raw.id,
            account_id=raw.account_id,
            person_id=person_id,
            type=raw.type,
            source_url=raw.source_url,
            published_at=raw.published_at,
            raw_text=raw.text,
            uses_competitor=grounded.uses_competitor,
            uses_cassandra=grounded.uses_cassandra,
            product=grounded.product,
            use_case=grounded.use_case,
            why_now=grounded.why_now,
            confidence=grounded.confidence,
            evidence_quote=grounded.evidence_quote,
            value=0.0,  # computed by hunter/scoring.py
        )

    return stats


def detect_champion_moves(conn: sqlite3.Connection, fixtures: Fixtures) -> list[str]:
    """FR-5: a person named in a signal at a company they've since left becomes a
    champion_move signal at their current company. Confidence, product and the
    evidence quote are inherited from the signal that named them (PRD §9.2/FR-5);
    the new signal's date is the person's left_at.
    """
    created: list[str] = []
    accounts_by_id = {a.id: a for a in fixtures.accounts}

    for person in fixtures.people:
        for prev in person.previous_companies:
            source = conn.execute(
                "SELECT * FROM signals WHERE account_id = ? AND person_id = ? ORDER BY id LIMIT 1",
                (prev.account_id, person.id),
            ).fetchone()
            if source is None:
                continue

            new_id = f"champ_{person.id}_{prev.account_id}"
            prev_account = accounts_by_id.get(prev.account_id)
            current_account = accounts_by_id.get(person.account_id)
            why_now = (
                f"Champion move: {person.first_name} {person.last_name} joined "
                f"{current_account.name if current_account else person.account_id} on "
                f"{prev.left_at.isoformat()} (previously at "
                f"{prev_account.name if prev_account else prev.account_id})."
            )

            db.insert_signal(
                conn,
                id=new_id,
                account_id=person.account_id,
                person_id=person.id,
                type="champion_move",
                source_url=source["source_url"],
                published_at=prev.left_at,
                raw_text=source["raw_text"],
                uses_competitor=bool(source["uses_competitor"]) if source["uses_competitor"] is not None else None,
                uses_cassandra=bool(source["uses_cassandra"]) if source["uses_cassandra"] is not None else None,
                product=source["product"],
                use_case=source["use_case"],
                why_now=why_now,
                confidence=source["confidence"],
                evidence_quote=source["evidence_quote"],
                value=0.0,  # computed by hunter/scoring.py
            )
            created.append(new_id)

    return created
