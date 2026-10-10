"""FR-9a / PRD §18.1: running the pipeline twice creates no new invites.

Named to match the PRD §18.1 test table directly. Guards against the regression
found while building Phase 4: once dispatch advances a lead past QUALIFIED,
re-running select_leads must not free up its account's cap slot for another
lead (see scoring.ADVANCED_LEAD_STATUSES).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hunter import db, dispatch, scoring
from hunter import extract as extract_mod
from hunter import personalize as personalize_mod
from hunter.sources import load_fixtures

RERUN_TEST_DB_PATH = "/tmp/hunter_pytest_rerun.db"


@pytest.fixture
def rerun_conn(config, tmp_path):
    test_config = config.model_copy(deep=True)
    test_config.runtime.outbox_path = str(tmp_path / "outbox.jsonl")

    db.reset_db(RERUN_TEST_DB_PATH)
    conn = db.connect(RERUN_TEST_DB_PATH)

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

    yield conn, test_config
    conn.close()


def _run_once(conn, test_config, fixtures):
    extract_mod.extract_signals(conn, fixtures, test_config, llm_mode="replay")
    extract_mod.detect_champion_moves(conn, fixtures)
    scoring.score_accounts(conn, test_config, test_config.as_of)
    scoring.select_leads(conn, test_config, datetime.now())
    personalize_mod.draft_invites_for_qualified_leads(
        conn, test_config, llm_mode="replay", run_id=None, now=datetime.now()
    )
    dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())


def test_rerun_is_idempotent(rerun_conn):
    conn, test_config = rerun_conn
    fixtures = load_fixtures()

    _run_once(conn, test_config, fixtures)
    messages_after_first = db.list_messages(conn)
    assert len(messages_after_first) == 5  # 5 qualified leads, 1 invite each

    _run_once(conn, test_config, fixtures)
    messages_after_second = db.list_messages(conn)

    assert len(messages_after_second) == 5  # no new invites, no new leads promoted into a filled slot
    assert [m["id"] for m in messages_after_first] == [m["id"] for m in messages_after_second]


def test_rerun_does_not_promote_a_deprioritized_lead_into_a_sent_slot(rerun_conn):
    """The regression this guards: once Maya and Tom's invites are SENT at
    Northwind (cap = 2), a second select_leads must not treat their slots as
    free and promote Ana (rank 3) in behind them.
    """
    conn, test_config = rerun_conn
    fixtures = load_fixtures()

    _run_once(conn, test_config, fixtures)
    _run_once(conn, test_config, fixtures)

    ana = db.get_lead(conn, "p03")
    assert ana["status"] == "DEPRIORITIZED"
    assert db.list_messages_for_lead(conn, "p03") == []
