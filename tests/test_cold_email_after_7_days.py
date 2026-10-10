"""FR-8 / PRD §18.1: a cold email is drafted exactly when `sequence.R3.days`
days pass without acceptance - not before.

Named to match the PRD §18.1 test table directly.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hunter import db, dispatch, hitl, scoring, triggers
from hunter import extract as extract_mod
from hunter import personalize as personalize_mod
from hunter.sources import load_fixtures

COLD_EMAIL_TEST_DB_PATH = "/tmp/hunter_pytest_cold_email_7_days.db"


@pytest.fixture
def invited_conn(config, tmp_path):
    """All 5 leads INVITED (invites drafted, approved and dispatched)."""
    test_config = config.model_copy(deep=True)
    test_config.runtime.outbox_path = str(tmp_path / "outbox.jsonl")

    db.reset_db(COLD_EMAIL_TEST_DB_PATH)
    conn = db.connect(COLD_EMAIL_TEST_DB_PATH)

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
    extract_mod.extract_signals(conn, fixtures, test_config, llm_mode="replay")
    extract_mod.detect_champion_moves(conn, fixtures)
    scoring.score_accounts(conn, test_config, test_config.as_of)
    scoring.select_leads(conn, test_config, datetime.now())
    personalize_mod.draft_invites_for_qualified_leads(conn, test_config, llm_mode="replay", run_id=None, now=datetime.now())
    hitl.approve_all(conn, test_config, now=datetime.now())
    dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())
    assert all(db.get_lead(conn, lid)["status"] == "INVITED" for lid in ("p01", "p02", "p05", "p08", "p12"))

    yield conn, test_config
    conn.close()


def test_cold_email_after_7_days(invited_conn):
    """R3's threshold (config: sequence[R3].days = 7) is a hard boundary - the
    cold email never fires below it, and fires for everyone still INVITED once
    reached. Uses the real scripted events and the committed replay set (no
    live call, no monkeypatch): Maya (day 2) and Lior (day 4) accept and get
    warm emails regardless of the day boundary; Tom, Joris and Dana only get
    their cold email once day 7 is reached.
    """
    conn, test_config = invited_conn
    scripted = load_fixtures().simulated_events

    before_threshold = triggers.simulate(
        conn, test_config, days=6, llm_mode="replay", run_id=None, now=datetime.now(), scripted_events=scripted,
    )
    assert set(before_threshold.warm_drafted) == {"p01", "p08"}  # day-2 and day-4 events, unrelated to R3
    assert before_threshold.cold_drafted == []  # 6 < 7: R3 has not fired yet
    for lead_id in ("p02", "p05", "p12"):
        assert db.get_lead(conn, lead_id)["status"] == "INVITED"
        assert all(m["variant"] == "invite" for m in db.list_messages_for_lead(conn, lead_id))

    at_threshold = triggers.simulate(
        conn, test_config, days=7, llm_mode="replay", run_id=None, now=datetime.now(), scripted_events=scripted,
    )
    assert at_threshold.warm_drafted == []  # Maya/Lior already handled - idempotent, not redrafted
    assert set(at_threshold.cold_drafted) == {"p02", "p05", "p12"}  # 7 >= 7: R3 fires now
