"""Scorecard comparing pipeline output to fixture _expected values (PRD FR-13).

Only this module and tests/ may read `_expected` fields - see CLAUDE.md.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from hunter import db, validators
from hunter.models import Config, DraftResult
from hunter.scoring import evidence_signals_for_account

EXTRACTION_FIELDS = ("uses_competitor", "uses_cassandra", "product", "confidence")
STATUS_MAP = {"QUALIFIED": "SELECTED", "DEPRIORITIZED": "DEPRIORITIZED", "REJECTED": "REJECTED", "SUPPRESSED": "SUPPRESSED"}


@dataclass
class ScoreCard:
    extraction_correct: int = 0
    extraction_total: int = 0
    false_positive_signal_id: str | None = None
    false_positive_rejected: bool | None = None
    selection_correct: int = 0
    selection_total: int = 0
    selection_mismatches: list[str] = field(default_factory=list)
    grounding_correct: int | None = None
    grounding_total: int | None = None
    grounding_mismatches: list[str] = field(default_factory=list)

    @property
    def extraction_accuracy(self) -> float:
        return self.extraction_correct / self.extraction_total if self.extraction_total else 0.0

    @property
    def selection_accuracy(self) -> float:
        return self.selection_correct / self.selection_total if self.selection_total else 0.0

    @property
    def grounding_rate(self) -> float | None:
        if not self.grounding_total:
            return None
        return self.grounding_correct / self.grounding_total

    @property
    def passed(self) -> bool:
        ok = self.extraction_accuracy == 1.0 and self.selection_accuracy == 1.0
        ok = ok and (self.false_positive_rejected is not False)
        if self.grounding_total:
            ok = ok and self.grounding_rate == 1.0
        return ok


def _load_raw_fixtures(path: str | Path = "data/fixtures.json") -> dict:
    with open(path) as f:
        return json.load(f)


def evaluate_extraction(conn: sqlite3.Connection, raw_fixtures: dict) -> tuple[int, int, str | None, bool | None]:
    correct = 0
    total = 0
    fp_id = None
    fp_rejected = None

    for raw in raw_fixtures["raw_signals"]:
        expected = raw.get("_expected", {})
        signal = db.get_signal(conn, raw["id"])
        if signal is None:
            continue
        for field_name in EXTRACTION_FIELDS:
            if field_name not in expected:
                continue
            total += 1
            actual = signal[field_name]
            if field_name in ("uses_competitor", "uses_cassandra") and actual is not None:
                actual = bool(actual)
            if actual == expected[field_name]:
                correct += 1

        if "Cassandra" in raw["text"] and "FALSE POSITIVE" in expected.get("note", ""):
            fp_id = raw["id"]
            fp_rejected = not bool(signal["uses_cassandra"])

    return correct, total, fp_id, fp_rejected


def evaluate_selection(conn: sqlite3.Connection, raw_fixtures: dict) -> tuple[int, int, list[str]]:
    correct = 0
    total = 0
    mismatches = []

    for person in raw_fixtures["people"]:
        expected_status = person["_expected"]["status"]
        lead = db.get_lead(conn, person["id"])
        total += 1
        if lead is None:
            mismatches.append(f"{person['id']} ({person['first_name']}): no lead row found")
            continue
        actual_status = STATUS_MAP.get(lead["status"], lead["status"])
        if actual_status == expected_status:
            correct += 1
        else:
            mismatches.append(
                f"{person['id']} ({person['first_name']}): expected={expected_status} actual={lead['status']}"
            )

    return correct, total, mismatches


def evaluate_grounding(conn: sqlite3.Connection, config: Config) -> tuple[int, int, list[str]]:
    """PRD §7.3: messages whose evidence_ids all exist (and belong to the lead's account)
    and whose DataStax/Astra/DSE mentions, if any, cite high-confidence evidence.
    """
    correct = 0
    total = 0
    mismatches = []

    for msg in db.list_messages(conn):
        total += 1
        lead = db.get_lead(conn, msg["lead_id"])
        evidence_signals = evidence_signals_for_account(conn, lead["account_id"])
        draft = DraftResult(
            subject=msg["subject"], body=msg["body"],
            evidence_ids=json.loads(msg["evidence_ids"]), value_prop_ids=json.loads(msg["value_prop_ids"]),
        )
        errors = validators.validate_grounding(draft, evidence_signals, config)
        if errors:
            mismatches.append(f"message #{msg['id']} (lead {msg['lead_id']}): {'; '.join(errors)}")
        else:
            correct += 1

    return correct, total, mismatches


def run_evaluation(
    conn: sqlite3.Connection, config: Config | None = None, fixtures_path: str | Path = "data/fixtures.json"
) -> ScoreCard:
    raw_fixtures = _load_raw_fixtures(fixtures_path)
    card = ScoreCard()
    card.extraction_correct, card.extraction_total, card.false_positive_signal_id, card.false_positive_rejected = (
        evaluate_extraction(conn, raw_fixtures)
    )
    card.selection_correct, card.selection_total, card.selection_mismatches = evaluate_selection(conn, raw_fixtures)
    if config is not None:
        card.grounding_correct, card.grounding_total, card.grounding_mismatches = evaluate_grounding(conn, config)
    return card


def print_scorecard(card: ScoreCard) -> None:
    print("=== Scylla Hunter eval scorecard ===")
    print(f"Extraction accuracy:   {card.extraction_correct}/{card.extraction_total} ({card.extraction_accuracy:.0%})")
    if card.false_positive_signal_id:
        status = "rejected correctly" if card.false_positive_rejected else "NOT rejected (regression)"
        print(f"False-positive ({card.false_positive_signal_id}): {status}")
    print(f"Selection accuracy:    {card.selection_correct}/{card.selection_total} ({card.selection_accuracy:.0%})")
    for m in card.selection_mismatches:
        print(f"  MISMATCH: {m}")
    if card.grounding_total:
        print(f"Grounding rate:        {card.grounding_correct}/{card.grounding_total} ({card.grounding_rate:.0%})")
        for m in card.grounding_mismatches:
            print(f"  MISMATCH: {m}")
    print()
    print("VERDICT: PASS" if card.passed else "VERDICT: REGRESSION")
