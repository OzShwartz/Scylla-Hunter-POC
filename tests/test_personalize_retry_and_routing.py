import json
from datetime import datetime

from hunter import db, personalize
from hunter.llm import LLMResult


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
