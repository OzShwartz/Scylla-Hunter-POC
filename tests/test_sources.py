"""FR-2: the GitHub live source. No network in these tests - store_discovered_accounts
takes DiscoveredAccount data directly, so the mapping/filtering logic is fully
testable without a token (search_github_code, the only networked function, is
exercised manually against the real API, not in the automated suite)."""

from __future__ import annotations

from datetime import datetime

import pytest

from hunter import db, report, scoring
from hunter.sources import DiscoveredAccount, _mentions_excluded_keyword, store_discovered_accounts

SOURCES_TEST_DB_PATH = "/tmp/hunter_pytest_sources.db"


@pytest.fixture
def sources_conn():
    db.reset_db(SOURCES_TEST_DB_PATH)
    conn = db.connect(SOURCES_TEST_DB_PATH)
    yield conn
    conn.close()


def _discovered(org="acme-corp", repo="acme-corp/payments", flagged=False) -> DiscoveredAccount:
    return DiscoveredAccount(
        org_login=org, repo_full_name=repo, repo_html_url=f"https://github.com/{repo}",
        query="com.datastax.oss language:Java", flagged_scylla=flagged,
    )


def test_mentions_excluded_keyword_true():
    repo = {"description": "Internal tools, now migrating to ScyllaDB"}
    assert _mentions_excluded_keyword(repo, _config()) is True


def test_mentions_excluded_keyword_false():
    repo = {"description": "Payments service"}
    assert _mentions_excluded_keyword(repo, _config()) is False


def test_mentions_excluded_keyword_handles_missing_description():
    assert _mentions_excluded_keyword({}, _config()) is False


def _config():
    from hunter.models import GitHubSourceConfig
    return GitHubSourceConfig(
        enabled=True, queries=["x"], max_results_per_query=5, owner_type="Organization",
        exclude_if_repo_mentions=["scylla"],
    )


def test_store_discovered_accounts_creates_account_with_no_firmographics(sources_conn):
    account_ids = store_discovered_accounts(sources_conn, [_discovered()], as_of=datetime(2026, 10, 8).date())

    assert account_ids == ["gh_acme-corp"]
    account = db.get_account(sources_conn, "gh_acme-corp")
    assert account["employees"] is None
    assert account["source"] == "github"
    assert account["domain"] == "github.com/acme-corp"


def test_store_discovered_accounts_creates_a_github_code_signal(sources_conn):
    store_discovered_accounts(sources_conn, [_discovered()], as_of=datetime(2026, 10, 8).date())

    signals = db.list_signals_for_account(sources_conn, "gh_acme-corp")
    assert len(signals) == 1
    sig = signals[0]
    assert sig["type"] == "github_code"
    assert bool(sig["uses_competitor"]) is True
    assert bool(sig["uses_cassandra"]) is True
    assert sig["confidence"] == "high"
    assert sig["source_url"] == "https://github.com/acme-corp/payments"


def test_store_discovered_accounts_skips_flagged_repos(sources_conn):
    account_ids = store_discovered_accounts(
        sources_conn, [_discovered(flagged=True)], as_of=datetime(2026, 10, 8).date()
    )

    assert account_ids == []
    assert db.get_account(sources_conn, "gh_acme-corp") is None


def test_store_discovered_accounts_dedupes_same_org_across_repos(sources_conn):
    """Two matching repos in the same org map to one account."""
    discovered = [
        _discovered(org="acme-corp", repo="acme-corp/payments"),
        _discovered(org="acme-corp", repo="acme-corp/ledger"),
    ]
    account_ids = store_discovered_accounts(sources_conn, discovered, as_of=datetime(2026, 10, 8).date())

    assert account_ids == ["gh_acme-corp", "gh_acme-corp"]  # same account upserted twice
    assert len(db.list_accounts(sources_conn)) == 1
    assert len(db.list_signals_for_account(sources_conn, "gh_acme-corp")) == 2


def test_needs_enrichment_account_still_gets_a_people_query(sources_conn, config):
    """FR-2/FR-4: a live account has no firmographics, so it's NEEDS_ENRICHMENT,
    but FR-4's people-search query should still be generated for it."""
    store_discovered_accounts(sources_conn, [_discovered()], as_of=config.as_of)

    scoring.score_accounts(sources_conn, config, config.as_of)

    account = db.get_account(sources_conn, "gh_acme-corp")
    assert account["status"] == "NEEDS_ENRICHMENT"
    assert account["people_query"] is not None


def test_live_discovered_accounts_empty_when_only_fixtures_present(sources_conn):
    db.upsert_account(
        sources_conn, id="a01", name="Northwind Payments", domain="northwindpay.example",
        industry="Fintech", employees=500, hq="NY",
    )
    assert report.live_discovered_accounts(sources_conn) == []


def test_live_discovered_accounts_lists_github_accounts(sources_conn, config):
    store_discovered_accounts(sources_conn, [_discovered()], as_of=config.as_of)
    scoring.score_accounts(sources_conn, config, config.as_of)

    live = report.live_discovered_accounts(sources_conn)

    assert len(live) == 1
    assert live[0]["name"] == "acme-corp"
    assert live[0]["source"] == "github"
    assert live[0]["status"] == "NEEDS_ENRICHMENT"
    assert live[0]["target_title_count"] > 0


def test_run_without_github_token_explains_and_leaves_fixtures_unaffected(tmp_path, monkeypatch):
    """FR-2's AC, literally: without a token, the command explains how to
    enable it and the fixture run is unaffected."""
    from typer.testing import CliRunner

    from hunter import cli
    from hunter.models import load_config

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    test_config = load_config()
    test_config.runtime.db_path = str(tmp_path / "hunter.db")
    test_config.runtime.outbox_path = str(tmp_path / "outbox.jsonl")
    monkeypatch.setattr(cli, "load_config", lambda: test_config)

    result = CliRunner().invoke(cli.app, ["run", "--source", "github"])

    assert result.exit_code == 0
    assert "GITHUB_TOKEN is not set" in result.output
    assert "Loaded 9 accounts" in result.output


def test_run_github_api_failure_is_reported_cleanly_not_a_crash(tmp_path, monkeypatch):
    """PRD §11.7-style failure handling: a GitHub API error must not crash
    the run - report it and continue with the fixtures already loaded."""
    from typer.testing import CliRunner

    from hunter import cli, sources
    from hunter.models import load_config

    monkeypatch.setenv("GITHUB_TOKEN", "fake-token-for-this-test")

    def fake_run_github_source(*args, **kwargs):
        raise sources.GitHubSourceError("GitHub API error 401 for /search/code: bad credentials")

    monkeypatch.setattr(sources, "run_github_source", fake_run_github_source)

    test_config = load_config()
    test_config.runtime.db_path = str(tmp_path / "hunter.db")
    test_config.runtime.outbox_path = str(tmp_path / "outbox.jsonl")
    monkeypatch.setattr(cli, "load_config", lambda: test_config)

    result = CliRunner().invoke(cli.app, ["run", "--source", "github"])

    assert result.exit_code == 0  # never crashes
    assert "GitHub API error 401" in result.output
    assert "Loaded 9 accounts" in result.output
