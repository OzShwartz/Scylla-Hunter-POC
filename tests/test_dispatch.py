"""FR-9 / FR-9a: dry-run dispatch to console + outbox.jsonl, idempotency."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from hunter import db, dispatch, hitl, scoring
from hunter import extract as extract_mod
from hunter import personalize as personalize_mod
from hunter.sources import load_fixtures

DISPATCH_TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "hunter_pytest_dispatch.db")


@pytest.fixture
def dispatch_setup(config, tmp_path):
    """A fresh DB + an isolated outbox.jsonl (never examples/outbox.jsonl) per test."""
    test_config = config.model_copy(deep=True)
    test_config.runtime.outbox_path = str(tmp_path / "outbox.jsonl")

    db.reset_db(DISPATCH_TEST_DB_PATH)
    conn = db.connect(DISPATCH_TEST_DB_PATH)

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

    yield conn, test_config
    conn.close()


def test_dispatch_sends_only_approved_messages(dispatch_setup):
    conn, test_config = dispatch_setup
    stats = dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())

    # Maya (p01) and Tom (p02) auto-approved at Northwind (score 96); the rest pending.
    assert set(stats.sent_message_ids) == {1, 2}
    for mid in stats.sent_message_ids:
        assert db.get_message(conn, mid)["status"] == "SENT"


def test_dispatch_advances_lead_status_and_writes_event(dispatch_setup):
    conn, test_config = dispatch_setup
    dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())

    lead = db.get_lead(conn, "p01")
    assert lead["status"] == "INVITED"
    events = db.list_events(conn, lead_id="p01")
    assert events[-1]["type"] == "message_sent"


def test_dispatch_appends_to_outbox_jsonl(dispatch_setup):
    conn, test_config = dispatch_setup
    dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())

    lines = Path(test_config.runtime.outbox_path).read_text().strip().splitlines()
    assert len(lines) == 2
    record = json.loads(lines[0])
    assert record["lead_id"] == "p01"
    assert record["channel"] == "linkedin"
    assert record["recipient"].startswith("https://linkedin.example/")


def test_dispatch_is_idempotent_on_a_second_call(dispatch_setup):
    conn, test_config = dispatch_setup
    dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())
    second = dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())

    assert second.sent_message_ids == []
    lines = Path(test_config.runtime.outbox_path).read_text().strip().splitlines()
    assert len(lines) == 2  # not duplicated


def test_dispatch_after_approve_all_sends_the_rest(dispatch_setup):
    conn, test_config = dispatch_setup
    dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())  # Maya, Tom
    hitl.approve_all(conn, test_config, now=datetime.now())  # Joris, Lior, Dana
    stats = dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())

    assert len(stats.sent_message_ids) == 3
    for lead_id in ("p05", "p08", "p12"):
        assert db.get_lead(conn, lead_id)["status"] == "INVITED"


def test_dispatch_refuses_to_run_outside_dry_run(dispatch_setup):
    conn, test_config = dispatch_setup
    test_config.runtime.dry_run = False
    with pytest.raises(RuntimeError, match="dry_run"):
        dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())


def test_simulate_cli_sent_at_is_not_before_created_at(config, tmp_path, monkeypatch):
    """`hunter simulate --days 7` auto-dispatches Tom's cold email (route=auto) in the
    same invocation that drafted it at simulated day 7. sent_at must come from that same
    simulated clock, not an independent datetime.now() call made moments later - which
    would make a day-7-created message look like it was sent before it was created."""
    from typer.testing import CliRunner
    from hunter import cli

    test_db_path = str(tmp_path / "hunter.db")
    test_config = config.model_copy(deep=True)
    test_config.runtime.db_path = test_db_path
    test_config.runtime.outbox_path = str(tmp_path / "outbox.jsonl")
    monkeypatch.setattr(cli, "load_config", lambda: test_config)

    runner = CliRunner()
    assert runner.invoke(cli.app, ["reset"]).exit_code == 0
    assert runner.invoke(cli.app, ["run"]).exit_code == 0
    assert runner.invoke(cli.app, ["approve", "--all"]).exit_code == 0
    assert runner.invoke(cli.app, ["simulate", "--days", "7"]).exit_code == 0

    conn = db.connect(test_db_path)
    tom_cold = next(
        m for m in db.list_messages_for_lead(conn, "p02") if m["channel"] == "email" and m["variant"] == "cold"
    )
    assert tom_cold["status"] == "SENT"
    assert tom_cold["sent_at"] >= tom_cold["created_at"]
