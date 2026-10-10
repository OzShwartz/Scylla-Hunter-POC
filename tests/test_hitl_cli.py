"""FR-7: review / approve / reject / edit (PRD §9.6, §12.3).

Uses its own DB per test (unlike the session-scoped `pipeline_conn` other test
files share and only read from) because approve/reject/edit mutate message
status - sharing one connection across tests would make them order-dependent.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hunter import db, hitl, scoring
from hunter import extract as extract_mod
from hunter import personalize as personalize_mod
from hunter.sources import load_fixtures

HITL_TEST_DB_PATH = "/tmp/hunter_pytest_hitl.db"

# PRD §12.3: Maya (p01) and Tom (p02) at Northwind (score 96) auto-approve.
# Joris (p05, Lumen 76), Lior (p08, Kestrel 78) and Dana (p12, Brightwave 61,
# champion move) stay pending on score alone.
PENDING_LEAD_IDS = {"p05", "p08", "p12"}
AUTO_APPROVED_LEAD_IDS = {"p01", "p02"}


@pytest.fixture
def hitl_conn(config):
    db.reset_db(HITL_TEST_DB_PATH)
    conn = db.connect(HITL_TEST_DB_PATH)

    fixtures = load_fixtures()
    for a in fixtures.accounts:
        db.upsert_account(
            conn, id=a.id, name=a.name, domain=a.domain, industry=a.industry, employees=a.employees, hq=a.hq
        )
    for p in fixtures.people:
        db.upsert_lead(
            conn, id=p.id, account_id=p.account_id, first_name=p.first_name, last_name=p.last_name,
            title=p.title, department=p.department, skills=p.skills, linkedin_url=p.linkedin_url, email=p.email,
        )

    extract_mod.extract_signals(conn, fixtures, config, llm_mode="replay")
    extract_mod.detect_champion_moves(conn, fixtures)
    scoring.score_accounts(conn, config, config.as_of)
    scoring.select_leads(conn, config, datetime.now())
    personalize_mod.draft_invites_for_qualified_leads(conn, config, llm_mode="replay", run_id=None, now=datetime.now())

    yield conn
    conn.close()


def _pending_message_for(conn, lead_id: str):
    for m in hitl.list_pending(conn):
        if m["lead_id"] == lead_id:
            return m
    raise AssertionError(f"no pending message for lead {lead_id}")


def _insert_pending_message(conn, *, lead_id: str, body: str, evidence_ids: list[str] | None = None) -> int:
    """A synthetic PENDING_APPROVAL draft, standing in for a future email (R2/R3
    aren't built until Phase 4) so --all's content-sensitivity skip can be tested
    without the trigger engine.
    """
    return db.insert_message(
        conn, lead_id=lead_id, run_id=None, channel="email", variant="cold",
        subject=None, body=body, evidence_ids=evidence_ids or [], value_prop_ids=[],
        approval_route="human", status="PENDING_APPROVAL", prompt_version="test", model="test",
        tokens=0, created_at=datetime.now(),
    )


def test_review_lists_exactly_the_three_score_banded_pending_invites(hitl_conn):
    pending = hitl.list_pending(hitl_conn)
    assert {m["lead_id"] for m in pending} == PENDING_LEAD_IDS
    for m in pending:
        assert m["status"] == "PENDING_APPROVAL"


def test_auto_approved_invites_are_not_in_the_pending_queue(hitl_conn):
    pending_leads = {m["lead_id"] for m in hitl.list_pending(hitl_conn)}
    assert pending_leads.isdisjoint(AUTO_APPROVED_LEAD_IDS)


def test_explain_route_for_mid_score_account_cites_the_score_band(hitl_conn, config):
    message = _pending_message_for(hitl_conn, "p05")  # Lumen, score 76
    account = db.get_account(hitl_conn, "a02")
    reason = hitl.explain_route(hitl_conn, message, account, config)
    assert "76" in reason
    assert "below" in reason


def test_approve_moves_message_to_approved_and_writes_an_event(hitl_conn):
    message = _pending_message_for(hitl_conn, "p05")
    before_events = len(db.list_events(hitl_conn, lead_id="p05"))

    updated = hitl.approve(hitl_conn, message["id"], now=datetime.now())

    assert updated["status"] == "APPROVED"
    events = db.list_events(hitl_conn, lead_id="p05")
    assert len(events) == before_events + 1
    assert events[-1]["type"] == "message_approved"


def test_approve_all_clears_the_pending_queue(hitl_conn):
    for lead_id in PENDING_LEAD_IDS:
        message = _pending_message_for(hitl_conn, lead_id)
        hitl.approve(hitl_conn, message["id"], now=datetime.now())
    assert hitl.list_pending(hitl_conn) == []


def test_approve_rejects_a_message_not_pending(hitl_conn):
    message = _pending_message_for(hitl_conn, "p05")
    hitl.approve(hitl_conn, message["id"], now=datetime.now())
    with pytest.raises(ValueError, match="not PENDING_APPROVAL"):
        hitl.approve(hitl_conn, message["id"], now=datetime.now())


def test_approve_unknown_message_id_raises(hitl_conn):
    with pytest.raises(ValueError, match="No message"):
        hitl.approve(hitl_conn, 999999, now=datetime.now())


def test_reject_stores_reason_and_writes_an_event(hitl_conn):
    message = _pending_message_for(hitl_conn, "p08")

    updated = hitl.reject(hitl_conn, message["id"], reason="wrong angle for this account", now=datetime.now())

    assert updated["status"] == "REJECTED"
    assert updated["reviewer_note"] == "wrong angle for this account"
    events = db.list_events(hitl_conn, lead_id="p08")
    assert events[-1]["type"] == "message_rejected"
    assert events[-1]["payload"]
    import json as _json
    assert _json.loads(events[-1]["payload"])["reason"] == "wrong angle for this account"


def test_edit_with_invalid_text_keeps_pending_and_records_errors(hitl_conn, config):
    message = _pending_message_for(hitl_conn, "p12")  # Dana, Brightwave

    updated, errors = hitl.edit(hitl_conn, message["id"], text="x" * 500, config=config, now=datetime.now())

    assert errors  # over the 280-char invite limit, missing name/company, etc.
    assert updated["status"] == "PENDING_APPROVAL"
    assert updated["original_body"] == message["body"]
    assert updated["body"] == "x" * 500
    assert updated["reviewer_note"]


def test_edit_with_valid_text_approves_and_keeps_original_body(hitl_conn, config):
    message = _pending_message_for(hitl_conn, "p08")
    lead = db.get_lead(hitl_conn, "p08")
    account = db.get_account(hitl_conn, lead["account_id"])
    new_text = f"Hi {lead['first_name']}, noticed {account['name']}'s recent engineering work - let's connect."

    updated, errors = hitl.edit(hitl_conn, message["id"], text=new_text, config=config, now=datetime.now())

    assert errors == []
    assert updated["status"] == "APPROVED"
    assert updated["body"] == new_text
    assert updated["original_body"] == message["body"]
    assert updated["reviewer_note"] == ""


def test_edit_twice_keeps_the_first_original_body(hitl_conn, config):
    message = _pending_message_for(hitl_conn, "p12")
    first_original = message["body"]

    hitl.edit(hitl_conn, message["id"], text="x" * 500, config=config, now=datetime.now())
    lead = db.get_lead(hitl_conn, "p12")
    account = db.get_account(hitl_conn, lead["account_id"])
    new_text = f"Hi {lead['first_name']}, {account['name']}'s engineering work caught my eye - let's connect."
    updated, errors = hitl.edit(hitl_conn, message["id"], text=new_text, config=config, now=datetime.now())

    assert errors == []
    assert updated["original_body"] == first_original


def test_edit_writes_a_message_edited_event(hitl_conn, config):
    message = _pending_message_for(hitl_conn, "p05")
    before_events = len(db.list_events(hitl_conn, lead_id="p05"))

    hitl.edit(hitl_conn, message["id"], text="x" * 500, config=config, now=datetime.now())

    events = db.list_events(hitl_conn, lead_id="p05")
    assert len(events) == before_events + 1
    assert events[-1]["type"] == "message_edited"


def test_edit_unknown_message_id_raises(hitl_conn, config):
    with pytest.raises(ValueError, match="No message"):
        hitl.edit(hitl_conn, 999999, text="hello", config=config, now=datetime.now())


# ---------------------------------------------------------------------------
# approve --all must not bulk-approve content-sensitive drafts (PRD §9.6):
# that would defeat the override routing was built for.
# ---------------------------------------------------------------------------


SENSITIVE_BODY = (
    "Hi Joris, your team's DataStax Enterprise contract renewal is worth "
    "revisiting given the IBM acquisition."
)


def test_route_info_flags_sensitive_content(hitl_conn, config):
    sensitive_id = _insert_pending_message(hitl_conn, lead_id="p05", body=SENSITIVE_BODY)
    message = db.get_message(hitl_conn, sensitive_id)
    account = db.get_account(hitl_conn, "a02")

    _, status, _, code = hitl.route_info(hitl_conn, message, account, config)

    assert status == "PENDING_APPROVAL"
    assert code == hitl.SENSITIVE_CONTENT


def test_approve_all_skips_sensitive_content_by_default(hitl_conn, config):
    sensitive_id = _insert_pending_message(hitl_conn, lead_id="p05", body=SENSITIVE_BODY)

    approved_ids, skipped = hitl.approve_all(hitl_conn, config, now=datetime.now())

    assert sensitive_id not in approved_ids
    assert db.get_message(hitl_conn, sensitive_id)["status"] == "PENDING_APPROVAL"
    skipped_ids = {m["id"] for m, _ in skipped}
    assert sensitive_id in skipped_ids
    # the three score-band invites (Joris, Lior, Dana) are still bulk-approved
    assert len(approved_ids) == 3
    assert hitl.list_pending(hitl_conn) == [db.get_message(hitl_conn, sensitive_id)]


def test_approve_all_include_sensitive_approves_it_too(hitl_conn, config):
    sensitive_id = _insert_pending_message(hitl_conn, lead_id="p05", body=SENSITIVE_BODY)

    approved_ids, skipped = hitl.approve_all(hitl_conn, config, include_sensitive=True, now=datetime.now())

    assert sensitive_id in approved_ids
    assert db.get_message(hitl_conn, sensitive_id)["status"] == "APPROVED"
    assert skipped == []


def test_approve_all_never_sweeps_up_a_validator_failed_draft_even_with_include_sensitive(hitl_conn, config):
    failed_id = _insert_pending_message(hitl_conn, lead_id="p05", body="x" * 500)
    db.update_message_status(hitl_conn, failed_id, status="PENDING_APPROVAL", reviewer_note="too long")

    approved_ids, skipped = hitl.approve_all(hitl_conn, config, include_sensitive=True, now=datetime.now())

    assert failed_id not in approved_ids
    assert db.get_message(hitl_conn, failed_id)["status"] == "PENDING_APPROVAL"
    skipped_ids = {m["id"] for m, _ in skipped}
    assert failed_id in skipped_ids


def test_approve_all_never_sweeps_up_a_no_high_confidence_evidence_draft(hitl_conn, config):
    low_conf_id = _insert_pending_message(
        hitl_conn, lead_id="p05", body="Hi Joris, following up - open to a quick chat about Lumen Logistics?",
    )

    approved_ids, skipped = hitl.approve_all(hitl_conn, config, include_sensitive=True, now=datetime.now())

    assert low_conf_id not in approved_ids
    skipped_ids = {m["id"] for m, _ in skipped}
    assert low_conf_id in skipped_ids
    _, _, _, code = hitl.route_info(
        hitl_conn, db.get_message(hitl_conn, low_conf_id), db.get_account(hitl_conn, "a02"), config
    )
    assert code == hitl.NO_HIGH_CONFIDENCE_EVIDENCE
