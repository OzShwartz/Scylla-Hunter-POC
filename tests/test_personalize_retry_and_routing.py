import json
from datetime import datetime

from hunter import db, personalize
from hunter.llm import LLMResult

MULTI_THREAD_TEST_DB_PATH = "/tmp/hunter_pytest_multithread_block.db"


def test_practitioner_is_never_offered_the_ibm_context_fact(config):
    """cf_ibm is decision_maker-only (PRD §11.5) - a practitioner shouldn't
    even see it as an option, not just be told not to use it."""
    block = personalize._render_context_facts_block(config, "practitioner")
    assert "cf_ibm" not in block


def test_decision_maker_is_offered_the_ibm_context_fact(config):
    block = personalize._render_context_facts_block(config, "decision_maker")
    assert "cf_ibm" in block


def test_other_account_messages_block_is_empty_with_no_siblings():
    db.reset_db(MULTI_THREAD_TEST_DB_PATH)
    conn = db.connect(MULTI_THREAD_TEST_DB_PATH)
    db.upsert_account(conn, id="a01", name="Northwind Payments", domain="northwindpay.example", industry="Fintech", employees=500, hq="NY")
    db.upsert_lead(conn, id="p01", account_id="a01", first_name="Maya", last_name="Rosen", title="CTO", department="Engineering", skills=[], linkedin_url="https://x", email="maya@x.example")

    block = personalize._render_other_account_messages_block(conn, "a01", exclude_lead_id="p01")

    assert block == "(none)"
    conn.close()


def test_other_account_messages_block_lists_a_sibling_opening_and_evidence():
    db.reset_db(MULTI_THREAD_TEST_DB_PATH)
    conn = db.connect(MULTI_THREAD_TEST_DB_PATH)
    db.upsert_account(conn, id="a01", name="Northwind Payments", domain="northwindpay.example", industry="Fintech", employees=500, hq="NY")
    db.upsert_lead(conn, id="p01", account_id="a01", first_name="Maya", last_name="Rosen", title="CTO", department="Engineering", skills=[], linkedin_url="https://x", email="maya@x.example")
    db.upsert_lead(conn, id="p02", account_id="a01", first_name="Tom", last_name="Hale", title="SRE", department="Engineering", skills=[], linkedin_url="https://y", email="tom@x.example")
    db.insert_message(
        conn, lead_id="p02", run_id=None, channel="email", variant="cold", subject="S",
        body="Hi Tom, following up on your fraud-scoring cluster. Reply STOP to opt out.",
        evidence_ids=["s01"], value_prop_ids=["vp_tco"], approval_route="human", status="PENDING_APPROVAL",
        prompt_version="test", model="test", tokens=0, created_at=datetime.now(),
    )

    block = personalize._render_other_account_messages_block(conn, "a01", exclude_lead_id="p01")

    assert "Hi Tom, following up on your fraud-scoring cluster." in block
    assert "s01" in block
    conn.close()


def test_other_account_messages_block_excludes_the_current_lead_own_messages():
    db.reset_db(MULTI_THREAD_TEST_DB_PATH)
    conn = db.connect(MULTI_THREAD_TEST_DB_PATH)
    db.upsert_account(conn, id="a01", name="Northwind Payments", domain="northwindpay.example", industry="Fintech", employees=500, hq="NY")
    db.upsert_lead(conn, id="p01", account_id="a01", first_name="Maya", last_name="Rosen", title="CTO", department="Engineering", skills=[], linkedin_url="https://x", email="maya@x.example")
    db.insert_message(
        conn, lead_id="p01", run_id=None, channel="linkedin", variant="invite", subject=None,
        body="Hi Maya, would love to connect.", evidence_ids=["s01"], value_prop_ids=[],
        approval_route="auto", status="SENT", prompt_version="test", model="test", tokens=0, created_at=datetime.now(),
    )

    block = personalize._render_other_account_messages_block(conn, "a01", exclude_lead_id="p01")

    assert block == "(none)"
    conn.close()


def test_persistent_validator_failure_retries_once_then_forces_review(pipeline_conn, config, monkeypatch):
    """FR-6: on failure, retry once; if it still fails, route to human review with the reason."""
    bad_json = json.dumps({"subject": None, "body": "x" * 500, "evidence_ids": [], "value_prop_ids": []})
    calls = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        return LLMResult(text=bad_json, tokens_in=10, tokens_out=10, model="fake-model", from_replay=False)

    monkeypatch.setattr(personalize, "call_llm", fake_call_llm)

    lead = db.get_lead(pipeline_conn, "p01")
    account = db.get_account(pipeline_conn, "a01")
    stats = personalize.PersonalizationStats()

    message_id = personalize.draft_message(
        pipeline_conn, lead=lead, account=account, config=config, variant="invite",
        llm_mode="live", run_id=None, now=datetime.now(), stats=stats,
    )

    assert len(calls) == 2  # original attempt + exactly one retry
    assert message_id in stats.forced_review

    msg = db.get_message(pipeline_conn, message_id)
    assert msg["status"] == "PENDING_APPROVAL"
    assert msg["reviewer_note"]  # failure reason stored, per FR-6


def test_malformed_json_retries_then_forces_review_without_crashing(pipeline_conn, config, monkeypatch):
    """PRD §11.7: invalid JSON is a failure like a validator failure - retry once,
    then force review. Must never crash the run over one bad response.
    """
    calls = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        return LLMResult(text="not valid json at all {{{", tokens_in=10, tokens_out=10, model="fake-model", from_replay=False)

    monkeypatch.setattr(personalize, "call_llm", fake_call_llm)

    lead = db.get_lead(pipeline_conn, "p01")
    account = db.get_account(pipeline_conn, "a01")
    stats = personalize.PersonalizationStats()

    message_id = personalize.draft_message(
        pipeline_conn, lead=lead, account=account, config=config, variant="invite",
        llm_mode="live", run_id=None, now=datetime.now(), stats=stats,
    )

    assert len(calls) == 2  # original attempt + exactly one retry, no crash
    msg = db.get_message(pipeline_conn, message_id)
    assert msg["status"] == "PENDING_APPROVAL"
    assert "not valid JSON" in msg["reviewer_note"]
