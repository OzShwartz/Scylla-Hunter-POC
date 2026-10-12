"""FR-10: report.md / report.html built from the database (PRD §13, §12.3)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from hunter import db, dispatch, hitl, report, scoring, triggers
from hunter import extract as extract_mod
from hunter import personalize as personalize_mod
from hunter.sources import load_fixtures

REPORT_TEST_DB_PATH = "/tmp/hunter_pytest_report.db"
POST_RUN_TEST_DB_PATH = "/tmp/hunter_pytest_report_post_run.db"


@pytest.fixture
def full_funnel_conn(config, tmp_path):
    """The full §12.3 demo funnel: 5 invited, 2 accepted, 5 emailed (2 warm, 3
    cold), with every HITL decision (auto, score-band, sensitive-content)
    resolved - using the real committed replay set, no monkeypatching.
    """
    test_config = config.model_copy(deep=True)
    test_config.runtime.outbox_path = str(tmp_path / "outbox.jsonl")
    test_config.runtime.report_path = str(tmp_path / "report.md")
    test_config.runtime.report_html_path = str(tmp_path / "report.html")

    db.reset_db(REPORT_TEST_DB_PATH)
    conn = db.connect(REPORT_TEST_DB_PATH)

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

    triggers.simulate(
        conn, test_config, days=7, llm_mode="replay", run_id=None, now=datetime.now(),
        scripted_events=fixtures.simulated_events,
    )
    approved_ids, skipped = hitl.approve_all(conn, test_config, now=datetime.now())
    dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())
    for message, _reason in skipped:
        hitl.approve(conn, message["id"], now=datetime.now())
    dispatch.dispatch_approved(conn, test_config, run_id=None, now=datetime.now())

    yield conn, test_config
    conn.close()


@pytest.fixture
def post_run_conn(config, tmp_path):
    """Right after `hunter run`, before any approval: invites drafted and
    routed (2 auto, 3 human), nothing approved or dispatched yet."""
    test_config = config.model_copy(deep=True)
    test_config.runtime.outbox_path = str(tmp_path / "outbox.jsonl")

    db.reset_db(POST_RUN_TEST_DB_PATH)
    conn = db.connect(POST_RUN_TEST_DB_PATH)

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


def test_account_funnel_matches_the_fixture_set(full_funnel_conn):
    """9 accounts: Northwind/Lumen/Kestrel/Brightwave qualified, Quanta/DataStax
    suppressed, Orbit/Pinecrest/Sprocket rejected (PRD §9.4/§6.2)."""
    conn, test_config = full_funnel_conn
    account_funnel = report.compute_account_funnel(conn)

    assert account_funnel == {"gathered": 9, "qualified": 4, "suppressed": 2, "rejected": 3}


def test_account_funnel_counts_match_db_counts(full_funnel_conn):
    conn, test_config = full_funnel_conn
    account_funnel = report.compute_account_funnel(conn)
    accounts = db.list_accounts(conn)

    assert account_funnel["gathered"] == len(accounts)
    assert account_funnel["qualified"] == sum(1 for a in accounts if a["status"] == "QUALIFIED")
    assert account_funnel["suppressed"] == sum(1 for a in accounts if a["status"] == "SUPPRESSED")
    assert account_funnel["rejected"] == sum(1 for a in accounts if a["status"] == "REJECTED")
    # every account is accounted for in exactly one of the three buckets
    assert account_funnel["qualified"] + account_funnel["suppressed"] + account_funnel["rejected"] == len(accounts)


def test_funnel_matches_the_prd_demo_script(full_funnel_conn):
    conn, test_config = full_funnel_conn
    funnel = report.compute_funnel(conn)

    assert funnel == {
        "gathered": 13, "qualified": 5, "drafted": 5, "approved": 5,
        "sent": 5, "accepted": 2, "emailed": 5,
    }


def test_report_account_count_matches_db_count(full_funnel_conn):
    conn, test_config = full_funnel_conn
    data = report.build_report(conn, test_config)
    assert len(data.accounts) == len(db.list_accounts(conn))


def test_report_lead_count_matches_db_count(full_funnel_conn):
    conn, test_config = full_funnel_conn
    data = report.build_report(conn, test_config)
    assert len(data.leads) == len(db.list_leads(conn))


def test_report_sent_message_count_matches_db_count(full_funnel_conn):
    conn, test_config = full_funnel_conn
    data = report.build_report(conn, test_config)
    assert len(data.sent_messages) == len(db.list_messages(conn, status="SENT"))
    assert len(data.sent_messages) == 10  # 5 invites + 2 warm + 3 cold


def _table_row_count(section: str) -> int:
    rows = [line for line in section.splitlines() if line.startswith("|")]
    return len(rows) - 2  # header row + "|---|" separator row


def test_markdown_table_row_counts_match_db_counts(full_funnel_conn):
    conn, test_config = full_funnel_conn
    data = report.build_report(conn, test_config)
    markdown = report.render_markdown(data)

    account_funnel_section = markdown.split("## Account funnel")[1].split("## Lead funnel")[0]
    assert _table_row_count(account_funnel_section) == len(report.ACCOUNT_FUNNEL_STAGES)
    assert sum(data.account_funnel[s] for s in ("qualified", "suppressed", "rejected")) == len(db.list_accounts(conn))

    accounts_section = markdown.split("## Accounts")[1].split("## Leads")[0]
    assert _table_row_count(accounts_section) == len(db.list_accounts(conn))

    leads_section = markdown.split("## Leads")[1].split("## Sent messages")[0]
    assert _table_row_count(leads_section) == len(db.list_leads(conn))

    sent_section = markdown.split("## Sent messages")[1].split("## Run metadata")[0]
    assert sent_section.count("### msg#") == len(db.list_messages(conn, status="SENT"))

    timeline_section = markdown.split("## Sequence timeline")[1].split("## Run metadata")[0]
    sent_invites = sum(1 for m in db.list_messages(conn, status="SENT") if m["variant"] == "invite")
    assert _table_row_count(timeline_section) == sent_invites == len(data.sequence_timeline)


def test_hitl_summary_route_counts_sum_to_all_messages(full_funnel_conn):
    conn, test_config = full_funnel_conn
    summary = report.compute_hitl_summary(conn, test_config)
    assert sum(summary["by_route"].values()) == len(db.list_messages(conn))
    assert sum(summary["by_code"].values()) == len(db.list_messages(conn))


def test_hitl_summary_distinguishes_routed_from_approved(post_run_conn):
    """Right after `run`, 3 invites are routed to human review but none of
    them have actually been approved yet - by_route['human'] (routed) and
    human_approved (approved) must not be conflated."""
    conn, test_config = post_run_conn
    summary = report.compute_hitl_summary(conn, test_config)
    assert summary["by_route"].get("human", 0) == 3
    assert summary["human_approved"] == 0


def test_engagement_accept_rate_by_persona(full_funnel_conn):
    conn, test_config = full_funnel_conn
    engagement = report.compute_engagement(conn)
    # Maya (decision_maker) and Lior (practitioner) are the two who accept.
    assert engagement["by_persona"]["decision_maker"]["accepted"] == 1
    assert engagement["by_persona"]["practitioner"]["accepted"] == 1
    assert engagement["warm_sent"] == 2
    assert engagement["cold_sent"] == 3


def test_write_report_produces_markdown_and_html(full_funnel_conn):
    conn, test_config = full_funnel_conn
    report.write_report(conn, test_config, html=True)

    from pathlib import Path
    markdown_text = Path(test_config.runtime.report_path).read_text()
    html_text = Path(test_config.runtime.report_html_path).read_text()

    assert "# Scylla Hunter Report" in markdown_text
    assert "<title>Scylla Hunter Report</title>" in html_text
    assert "{{" not in html_text and "{%" not in html_text  # no unrendered Jinja


def test_html_report_contains_every_lead_and_the_logo(full_funnel_conn):
    conn, test_config = full_funnel_conn
    report.write_report(conn, test_config, html=True)

    from pathlib import Path
    html_text = Path(test_config.runtime.report_html_path).read_text()

    for lead in db.list_leads(conn):
        assert f"{lead['first_name']} {lead['last_name']}" in html_text
        if lead["linkedin_url"]:
            assert f'href="{lead["linkedin_url"]}"' in html_text
    assert 'src="data:image/png;base64,' in html_text


def test_sequence_timeline_dates_come_from_as_of_not_wall_clock(full_funnel_conn):
    conn, test_config = full_funnel_conn

    first = report.build_sequence_timeline(conn, test_config)
    second = report.build_sequence_timeline(conn, test_config)
    assert first == second  # same conn and config in, same output out - no datetime.now() anywhere

    r3_days = next(r.days for r in test_config.sequence if r.id == "R3")
    for row in first:
        assert row["invite_sent"] == test_config.as_of
        if row["accepted"] is None:
            # never accepted -> R3 fired the cold email at exactly r3_days
            assert row["due_date"] == test_config.as_of + timedelta(days=r3_days)
        else:
            assert row["due_date"] == row["accepted"]
        assert row["days_remaining"] == 0  # full_funnel_conn runs the demo to completion
