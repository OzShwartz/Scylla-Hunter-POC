"""FR-12: POST /events and POST /tick produce the same DB state as the
equivalent CLI/trigger call - these are thin HTTP wrappers, not a second
implementation, so this is what proving that means."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from hunter import db, dispatch, hitl, scoring, server, triggers
from hunter import extract as extract_mod
from hunter import personalize as personalize_mod
from hunter.sources import load_fixtures

SERVER_TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "hunter_pytest_server.db")
REFERENCE_TEST_DB_PATH = os.path.join(tempfile.gettempdir(), "hunter_pytest_server_reference.db")
VOLATILE_MESSAGE_FIELDS = {"id", "created_at", "sent_at", "tokens", "run_id"}


def _build_invited_db(path: str, config) -> None:
    """Fixtures through invites drafted, approved and dispatched - every
    lead ends up INVITED, ready for either /events or /tick."""
    db.reset_db(path)
    conn = db.connect(path)
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
    hitl.approve_all(conn, config, now=datetime.now())
    dispatch.dispatch_approved(conn, config, run_id=None, now=datetime.now())
    conn.close()


def _normalize(rows: list) -> list[dict]:
    return sorted(
        ({k: v for k, v in dict(r).items() if k not in VOLATILE_MESSAGE_FIELDS} for r in rows),
        key=lambda d: (d["lead_id"], d["variant"]),
    )


@pytest.fixture
def paired_dbs(config, tmp_path, monkeypatch):
    """Two identical DBs built the same way, through the same replay-mode
    pipeline: one driven over HTTP (the server), one driven directly by the
    same trigger functions the CLI calls (the reference)."""
    test_config = config.model_copy(deep=True)
    test_config.runtime.outbox_path = str(tmp_path / "outbox.jsonl")

    server_config = test_config.model_copy(deep=True)
    server_config.runtime.db_path = SERVER_TEST_DB_PATH
    reference_config = test_config.model_copy(deep=True)
    reference_config.runtime.db_path = REFERENCE_TEST_DB_PATH

    _build_invited_db(SERVER_TEST_DB_PATH, server_config)
    _build_invited_db(REFERENCE_TEST_DB_PATH, reference_config)

    monkeypatch.setattr(server, "load_config", lambda: server_config)
    client = TestClient(server.app)

    yield client, reference_config


def test_events_endpoint_matches_the_equivalent_trigger_call(paired_dbs):
    client, reference_config = paired_dbs

    response = client.post("/events", json={"type": "connection_accepted", "lead_id": "p01"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["lead_status"] == "ACCEPTED"

    ref_conn = db.connect(REFERENCE_TEST_DB_PATH)
    triggers.handle_connection_accepted(
        ref_conn, reference_config, "p01", llm_mode="replay", run_id=None, now=datetime.now(), stats=triggers.TriggerStats()
    )
    dispatch.dispatch_approved(ref_conn, reference_config, run_id=None, now=datetime.now())

    server_conn = db.connect(SERVER_TEST_DB_PATH)
    assert db.get_lead(server_conn, "p01")["status"] == db.get_lead(ref_conn, "p01")["status"] == "ACCEPTED"
    assert _normalize(db.list_messages_for_lead(server_conn, "p01")) == _normalize(db.list_messages_for_lead(ref_conn, "p01"))
    server_conn.close()
    ref_conn.close()


def test_events_endpoint_is_a_no_op_for_a_lead_not_invited(paired_dbs):
    client, _reference_config = paired_dbs

    response = client.post("/events", json={"type": "connection_accepted", "lead_id": "p03"})  # Ana - never invited

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "no_op"
    assert body["message_id"] is None


def test_events_endpoint_rejects_an_unsupported_event_type(paired_dbs):
    client, _reference_config = paired_dbs
    response = client.post("/events", json={"type": "reply_received", "lead_id": "p01"})
    assert response.status_code == 400


def test_tick_endpoint_matches_the_equivalent_trigger_call(paired_dbs):
    """Maya (p01) and Lior (p08) accept first on both DBs - matching the real
    recorded demo, and the only scenario with a cold-email replay for the
    other three (no replay was ever recorded for a Maya/Lior *cold* email,
    since they always accept in the real demo)."""
    client, reference_config = paired_dbs

    client.post("/events", json={"type": "connection_accepted", "lead_id": "p01"})
    client.post("/events", json={"type": "connection_accepted", "lead_id": "p08"})
    ref_conn = db.connect(REFERENCE_TEST_DB_PATH)
    triggers.handle_connection_accepted(ref_conn, reference_config, "p01", llm_mode="replay", run_id=None, now=datetime.now(), stats=triggers.TriggerStats())
    triggers.handle_connection_accepted(ref_conn, reference_config, "p08", llm_mode="replay", run_id=None, now=datetime.now(), stats=triggers.TriggerStats())
    dispatch.dispatch_approved(ref_conn, reference_config, run_id=None, now=datetime.now())

    response = client.post("/tick", json={"days": 7})
    assert response.status_code == 200
    body = response.json()
    assert set(body["cold_drafted"]) == {"p02", "p05", "p12"}

    triggers.tick(ref_conn, reference_config, days=7, llm_mode="replay", run_id=None, now=datetime.now())
    dispatch.dispatch_approved(ref_conn, reference_config, run_id=None, now=datetime.now())

    server_conn = db.connect(SERVER_TEST_DB_PATH)
    for lead_id in ("p01", "p02", "p05", "p08", "p12"):
        assert db.get_lead(server_conn, lead_id)["status"] == db.get_lead(ref_conn, lead_id)["status"]
        assert _normalize(db.list_messages_for_lead(server_conn, lead_id)) == _normalize(db.list_messages_for_lead(ref_conn, lead_id))
    server_conn.close()
    ref_conn.close()


def test_tick_endpoint_below_threshold_drafts_nothing(paired_dbs):
    client, _reference_config = paired_dbs
    response = client.post("/tick", json={"days": 3})
    assert response.status_code == 200
    assert response.json()["cold_drafted"] == []
