import os
import sys
from datetime import datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hunter import db, scoring
from hunter import extract as extract_mod
from hunter import personalize as personalize_mod
from hunter.models import load_config
from hunter.sources import load_fixtures

TEST_DB_PATH = "/tmp/hunter_pytest.db"


@pytest.fixture(scope="session")
def config():
    return load_config()


@pytest.fixture(scope="session")
def pipeline_conn(config):
    """Runs the full MUST-pipeline once (replay mode, no key needed) and shares
    the resulting DB connection across all tests in the session.
    """
    db.reset_db(TEST_DB_PATH)
    conn = db.connect(TEST_DB_PATH)

    fixtures = load_fixtures()
    for a in fixtures.accounts:
        db.upsert_account(conn, id=a.id, name=a.name, domain=a.domain, industry=a.industry, employees=a.employees, hq=a.hq)
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
