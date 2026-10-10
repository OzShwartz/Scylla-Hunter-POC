"""FR-8 / PRD §18.1: no email exists before an invite was sent.

Named to match the PRD §18.1 test table directly. R2 and R3 both gate on the
lead currently being INVITED (see triggers.handle_connection_accepted /
handle_no_accept_after_days), so a lead with no invite - or whose invite
hasn't been approved and dispatched yet - can never get a warm or cold email.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hunter import db, triggers
from hunter import extract as extract_mod
from hunter import personalize as personalize_mod
from hunter import scoring
from hunter.sources import load_fixtures

NO_EMAIL_TEST_DB_PATH = "/tmp/hunter_pytest_no_email_before_invite.db"


@pytest.fixture
def selected_but_not_dispatched_conn(config):
    """Leads are scored and selected (QUALIFIED, invite drafted) but nothing
    has been approved or dispatched yet - no lead is INVITED."""
    db.reset_db(NO_EMAIL_TEST_DB_PATH)
    conn = db.connect(NO_EMAIL_TEST_DB_PATH)

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


def test_no_email_before_invite(selected_but_not_dispatched_conn, config):
    conn = selected_but_not_dispatched_conn
    for lead_id in ("p01", "p02", "p05", "p08", "p12"):
        assert db.get_lead(conn, lead_id)["status"] == "QUALIFIED"  # not yet INVITED

    stats = triggers.TriggerStats()
    for lead_id in ("p01", "p02", "p05", "p08", "p12"):
        assert triggers.handle_connection_accepted(
            conn, config, lead_id, llm_mode="replay", run_id=None, now=datetime.now(), stats=stats
        ) is None
        assert triggers.handle_no_accept_after_days(
            conn, config, lead_id, llm_mode="replay", run_id=None, now=datetime.now(), stats=stats
        ) is None

    for lead_id in ("p01", "p02", "p05", "p08", "p12"):
        variants = {m["variant"] for m in db.list_messages_for_lead(conn, lead_id)}
        assert variants == {"invite"}  # no warm or cold email
