"""FR-8 / §12: R2/R3 trigger handlers and the simulated clock.

LLM calls are monkeypatched (no replay files exist yet for warm/cold emails -
that needs a live recording pass, tracked separately) so these test the
trigger/routing/idempotency logic on its own, independent of personalization
prompt quality.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from hunter import db, dispatch, personalize, scoring, triggers
from hunter import extract as extract_mod
from hunter.llm import LLMResult
from hunter.models import SimulatedEvent
from hunter.sources import load_fixtures

TRIGGERS_TEST_DB_PATH = "/tmp/hunter_pytest_triggers.db"


def _valid_follow_up_json(
    *, first_name: str, company: str, evidence_ids: list[str], value_prop_id: str, connect_opener: bool
) -> str:
    opener = "Thanks for connecting! " if connect_opener else ""
    return json.dumps({
        "subject": "Following up",
        "body": (
            f"{opener}Hi {first_name}, wanted to share a quick note about {company}'s database work "
            "and see if it's worth a short chat. Reply STOP to opt out."
        ),
        "evidence_ids": evidence_ids,
        "value_prop_ids": [value_prop_id],
        "context_fact_ids": [],
    })


@pytest.fixture
def triggers_setup(config, tmp_path, monkeypatch):
    """A fresh DB, all 5 leads already INVITED (invites drafted and dispatched),
    with call_llm monkeypatched so warm/cold drafting needs no replay file.
    """
    test_config = config.model_copy(deep=True)
    test_config.runtime.outbox_path = str(tmp_path / "outbox.jsonl")

    db.reset_db(TRIGGERS_TEST_DB_PATH)
    conn = db.connect(TRIGGERS_TEST_DB_PATH)

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
    personalize.draft_invites_for_qualified_leads(conn, test_config, llm_mode="replay", run_id=None, now=datetime.now())

    import hunter.hitl as hitl_mod
    hitl_mod.approve_all(conn, test_config, now=datetime.now())
    dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())
    assert all(db.get_lead(conn, lid)["status"] == "INVITED" for lid in ("p01", "p02", "p05", "p08", "p12"))

    calls = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        lead_id = fake_call_llm.current_lead_id
        lead = db.get_lead(conn, lead_id)
        account = db.get_account(conn, lead["account_id"])
        evidence = scoring.evidence_signals_for_account(conn, account["id"])
        value_prop_id = (
            test_config.personas.decision_maker.angles[0] if lead["persona"] == "decision_maker"
            else test_config.personas.practitioner.angles[0]
        )
        body = _valid_follow_up_json(
            first_name=lead["first_name"], company=account["name"],
            evidence_ids=[evidence[0]["id"]] if evidence else [],
            value_prop_id=value_prop_id,
            connect_opener=fake_call_llm.variant == "warm",
        )
        return LLMResult(text=body, tokens_in=10, tokens_out=10, model="fake-model", from_replay=False)

    fake_call_llm.current_lead_id = None
    fake_call_llm.variant = None

    def tracking_draft_message(conn_, *, lead, account, config, variant, llm_mode, run_id, now, stats, previous_interaction=""):
        fake_call_llm.current_lead_id = lead["id"]
        fake_call_llm.variant = variant
        return real_draft_message(
            conn_, lead=lead, account=account, config=config, variant=variant, llm_mode=llm_mode,
            run_id=run_id, now=now, stats=stats, previous_interaction=previous_interaction,
        )

    real_draft_message = personalize.draft_message
    monkeypatch.setattr(personalize, "call_llm", fake_call_llm)
    monkeypatch.setattr(triggers.personalize, "draft_message", tracking_draft_message)

    yield conn, test_config, calls
    conn.close()


def test_connection_accepted_moves_lead_to_accepted_and_drafts_warm(triggers_setup):
    conn, test_config, calls = triggers_setup
    stats = triggers.TriggerStats()

    message_id = triggers.handle_connection_accepted(
        conn, test_config, "p01", llm_mode="live", run_id=None, now=datetime.now(), stats=stats
    )

    assert message_id is not None
    assert db.get_lead(conn, "p01")["status"] == "ACCEPTED"
    message = db.get_message(conn, message_id)
    assert message["variant"] == "warm"
    assert "p01" in stats.warm_drafted
    events = db.list_events(conn, lead_id="p01")
    assert any(e["type"] == "connection_accepted" for e in events)


def test_connection_accepted_is_idempotent(triggers_setup):
    conn, test_config, calls = triggers_setup
    stats = triggers.TriggerStats()
    triggers.handle_connection_accepted(conn, test_config, "p01", llm_mode="live", run_id=None, now=datetime.now(), stats=stats)
    calls_after_first = len(calls)

    second = triggers.handle_connection_accepted(conn, test_config, "p01", llm_mode="live", run_id=None, now=datetime.now(), stats=stats)

    assert second is None
    assert len(calls) == calls_after_first  # no second LLM call


def test_connection_accepted_no_op_for_a_lead_never_invited(triggers_setup):
    conn, test_config, calls = triggers_setup
    stats = triggers.TriggerStats()
    # p03 (Ana) was never selected/invited
    result = triggers.handle_connection_accepted(conn, test_config, "p03", llm_mode="live", run_id=None, now=datetime.now(), stats=stats)
    assert result is None
    assert calls == []


def test_no_accept_after_days_drafts_cold_and_leaves_lead_invited(triggers_setup):
    conn, test_config, calls = triggers_setup
    stats = triggers.TriggerStats()

    message_id = triggers.handle_no_accept_after_days(
        conn, test_config, "p02", llm_mode="live", run_id=None, now=datetime.now(), stats=stats
    )

    assert message_id is not None
    message = db.get_message(conn, message_id)
    assert message["variant"] == "cold"
    # lead stays INVITED until the cold email is actually dispatched (PRD §14.4)
    assert db.get_lead(conn, "p02")["status"] == "INVITED"
    assert "p02" in stats.cold_drafted


def test_no_accept_after_days_is_idempotent(triggers_setup):
    conn, test_config, calls = triggers_setup
    stats = triggers.TriggerStats()
    triggers.handle_no_accept_after_days(conn, test_config, "p02", llm_mode="live", run_id=None, now=datetime.now(), stats=stats)
    calls_after_first = len(calls)

    second = triggers.handle_no_accept_after_days(conn, test_config, "p02", llm_mode="live", run_id=None, now=datetime.now(), stats=stats)

    assert second is None
    assert len(calls) == calls_after_first


def test_simulate_matches_the_prd_demo_script(triggers_setup):
    """PRD §12.3: Maya (day 2) and Lior (day 4) accept -> warm; Tom, Joris, Dana
    don't accept by day 7 -> cold."""
    conn, test_config, calls = triggers_setup
    scripted = load_fixtures().simulated_events

    stats = triggers.simulate(
        conn, test_config, days=7, llm_mode="live", run_id=None, now=datetime.now(), scripted_events=scripted
    )

    assert set(stats.warm_drafted) == {"p01", "p08"}
    assert set(stats.cold_drafted) == {"p02", "p05", "p12"}
    assert db.get_lead(conn, "p01")["status"] == "ACCEPTED"
    assert db.get_lead(conn, "p08")["status"] == "ACCEPTED"
    assert db.get_lead(conn, "p02")["status"] == "INVITED"


def test_simulate_at_day_2_only_fires_the_first_scripted_event(triggers_setup):
    conn, test_config, calls = triggers_setup
    scripted = load_fixtures().simulated_events

    stats = triggers.simulate(
        conn, test_config, days=2, llm_mode="live", run_id=None, now=datetime.now(), scripted_events=scripted
    )

    assert stats.warm_drafted == ["p01"]  # Lior's day-4 event hasn't happened yet
    assert stats.cold_drafted == []  # day 7 R3 threshold not reached


def test_simulate_called_twice_is_idempotent(triggers_setup):
    conn, test_config, calls = triggers_setup
    scripted = load_fixtures().simulated_events

    triggers.simulate(conn, test_config, days=7, llm_mode="live", run_id=None, now=datetime.now(), scripted_events=scripted)
    calls_after_first = len(calls)

    second_stats = triggers.simulate(
        conn, test_config, days=7, llm_mode="live", run_id=None, now=datetime.now(), scripted_events=scripted
    )

    assert second_stats.warm_drafted == []
    assert second_stats.cold_drafted == []
    assert len(calls) == calls_after_first


def test_simulate_then_dispatch_matches_demo_funnel(triggers_setup):
    conn, test_config, calls = triggers_setup
    scripted = load_fixtures().simulated_events

    triggers.simulate(conn, test_config, days=7, llm_mode="live", run_id=None, now=datetime.now(), scripted_events=scripted)
    stats = dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())

    # emails pending human review (score-band or sensitive) aren't dispatched yet
    for lead_id in ("p01", "p02", "p05", "p08", "p12"):
        lead = db.get_lead(conn, lead_id)
        assert lead["status"] in ("ACCEPTED", "INVITED", "EMAILED")
