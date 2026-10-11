"""FR-2: the GitHub live source. No network in these tests - store_discovered_accounts
and classify_repo take MatchedRepo data directly, so the mapping/classification
logic is fully testable without a token (search_github_code, the only networked
function, is exercised manually against the real API, not in the automated suite)."""

from __future__ import annotations

from datetime import datetime

import pytest

from hunter import db, report, scoring
from hunter.models import GitHubSourceConfig
from hunter.sources import (
    EXCLUDED_COMPETITOR,
    EXCLUDED_FORK_OR_ARCHIVED,
    EXCLUDED_INTEGRATION,
    EXCLUDED_SCYLLA_MENTION,
    EXCLUDED_STALE_PATH,
    PROBABLE_USER,
    MatchedRepo,
    classify_repo,
    load_snapshot,
    store_discovered_accounts,
)

SOURCES_TEST_DB_PATH = "/tmp/hunter_pytest_sources.db"


@pytest.fixture
def sources_conn():
    db.reset_db(SOURCES_TEST_DB_PATH)
    conn = db.connect(SOURCES_TEST_DB_PATH)
    yield conn
    conn.close()


def _config(**overrides) -> GitHubSourceConfig:
    defaults = dict(
        enabled=True, queries=["x"], max_results_per_query=5, owner_type="Organization",
        exclude_if_repo_mentions=["scylla"], competitor_orgs=["datastax", "stargate", "thelastpickle"],
        exclude_if_path_contains=["integrations/", "connectors/", "examples/", "docs/", "tests/", "tutorials/"],
        exclude_if_repo_name_contains=["integration", "connector", "sdk", "example", "demo"],
        exclude_if_path_ends_with=[".old", ".bak", ".orig"],
        verified_integration_orgs={"rocketride-org": "store_astra is one of 8+ pluggable storage nodes"},
    )
    defaults.update(overrides)
    return GitHubSourceConfig(**defaults)


def _repo(
    org="acme-corp", repo="acme-corp/payments", path="requirements.txt", fork=False, archived=False,
    description="Payments service",
) -> MatchedRepo:
    return MatchedRepo(
        org_login=org, repo_full_name=repo, repo_html_url=f"https://github.com/{repo}",
        query="cassandra-driver filename:requirements.txt", matched_path=path,
        is_fork=fork, is_archived=archived, description=description,
    )


# ---------------------------------------------------------------------------
# classify_repo - the deterministic filters, PRD-§5.2/FR-2's "scylla mention"
# rule plus the four Oz asked for after reviewing the raw matches
# ---------------------------------------------------------------------------


def test_classify_fork_is_excluded():
    c = classify_repo(_repo(fork=True), _config())
    assert c.verdict == EXCLUDED_FORK_OR_ARCHIVED


def test_classify_archived_is_excluded():
    c = classify_repo(_repo(archived=True), _config())
    assert c.verdict == EXCLUDED_FORK_OR_ARCHIVED


def test_classify_scylla_mention_is_excluded():
    c = classify_repo(_repo(description="Migrating off DataStax to ScyllaDB"), _config())
    assert c.verdict == EXCLUDED_SCYLLA_MENTION


def test_classify_competitor_org_is_excluded():
    c = classify_repo(_repo(org="stargate", repo="stargate/stargate"), _config())
    assert c.verdict == EXCLUDED_COMPETITOR


def test_classify_competitor_org_match_is_case_insensitive():
    c = classify_repo(_repo(org="StarGate", repo="StarGate/stargate"), _config())
    assert c.verdict == EXCLUDED_COMPETITOR


def test_classify_integration_path_is_excluded():
    """Real case: deepset-ai/haystack-core-integrations matched under integrations/.../examples/."""
    c = classify_repo(_repo(org="deepset-ai", path="integrations/astra/examples/requirements.txt"), _config())
    assert c.verdict == EXCLUDED_INTEGRATION
    assert "integrations/astra/examples/requirements.txt" in c.reason


def test_classify_integration_repo_name_is_excluded():
    c = classify_repo(_repo(repo="acme-corp/astra-connector-sdk"), _config())
    assert c.verdict == EXCLUDED_INTEGRATION


def test_classify_stale_path_is_excluded():
    """Real case: neurodata/ndstore matched setup/requirements.txt.old."""
    c = classify_repo(_repo(org="neurodata", path="setup/requirements.txt.old"), _config())
    assert c.verdict == EXCLUDED_STALE_PATH


def test_classify_verified_integration_org_is_excluded():
    """Real case: rocketride-org's store_astra is one of 8+ pluggable storage
    nodes - the generic path/name filters don't catch this project's own
    naming, so it's a verified, cited override."""
    c = classify_repo(_repo(org="rocketride-org", path="nodes/src/nodes/store_astra/requirements.txt"), _config())
    assert c.verdict == EXCLUDED_INTEGRATION
    assert "store_astra" in c.reason


def test_classify_clean_repo_is_probable_user():
    """Real case: sky-uk/cqlmigrate - the org's own Cassandra migration tool,
    core application code, not under any excluded path or name."""
    c = classify_repo(_repo(org="sky-uk", repo="sky-uk/cqlmigrate", path="src/main/java/uk/sky/cqlmigrate/CqlLoader.java"), _config())
    assert c.verdict == PROBABLE_USER


def test_classify_checks_fork_before_competitor_org():
    """Order matters for the reason shown - a forked competitor repo is
    excluded as a fork, not re-labeled as competitor-affiliated."""
    c = classify_repo(_repo(org="stargate", repo="stargate/stargate", fork=True), _config())
    assert c.verdict == EXCLUDED_FORK_OR_ARCHIVED


# ---------------------------------------------------------------------------
# store_discovered_accounts - pure DB logic over classified repos
# ---------------------------------------------------------------------------


def test_store_discovered_accounts_only_creates_probable_user_accounts(sources_conn):
    classified = [
        classify_repo(_repo(org="acme-corp", repo="acme-corp/payments"), _config()),
        classify_repo(_repo(org="stargate", repo="stargate/stargate"), _config()),
    ]
    account_ids = store_discovered_accounts(sources_conn, classified, as_of=datetime(2026, 10, 8).date())

    assert account_ids == ["gh_acme-corp"]
    assert db.get_account(sources_conn, "gh_stargate") is None


def test_store_discovered_accounts_creates_account_with_no_firmographics(sources_conn):
    classified = [classify_repo(_repo(), _config())]
    store_discovered_accounts(sources_conn, classified, as_of=datetime(2026, 10, 8).date())

    account = db.get_account(sources_conn, "gh_acme-corp")
    assert account["employees"] is None
    assert account["source"] == "github"
    assert account["domain"] == "github.com/acme-corp"


def test_store_discovered_accounts_creates_a_github_code_signal(sources_conn):
    classified = [classify_repo(_repo(), _config())]
    store_discovered_accounts(sources_conn, classified, as_of=datetime(2026, 10, 8).date())

    signals = db.list_signals_for_account(sources_conn, "gh_acme-corp")
    assert len(signals) == 1
    sig = signals[0]
    assert sig["type"] == "github_code"
    assert bool(sig["uses_competitor"]) is True
    assert bool(sig["uses_cassandra"]) is True
    assert sig["confidence"] == "high"
    assert sig["source_url"] == "https://github.com/acme-corp/payments"


def test_store_discovered_accounts_dedupes_same_org_across_repos(sources_conn):
    classified = [
        classify_repo(_repo(org="acme-corp", repo="acme-corp/payments"), _config()),
        classify_repo(_repo(org="acme-corp", repo="acme-corp/ledger"), _config()),
    ]
    account_ids = store_discovered_accounts(sources_conn, classified, as_of=datetime(2026, 10, 8).date())

    assert account_ids == ["gh_acme-corp", "gh_acme-corp"]
    assert len(db.list_accounts(sources_conn)) == 1
    assert len(db.list_signals_for_account(sources_conn, "gh_acme-corp")) == 2


def test_needs_enrichment_account_still_gets_a_people_query(sources_conn, config):
    """FR-2/FR-4: a live account has no firmographics, so it's NEEDS_ENRICHMENT,
    but FR-4's people-search query should still be generated for it."""
    classified = [classify_repo(_repo(), _config())]
    store_discovered_accounts(sources_conn, classified, as_of=config.as_of)

    scoring.score_accounts(sources_conn, config, config.as_of)

    account = db.get_account(sources_conn, "gh_acme-corp")
    assert account["status"] == "NEEDS_ENRICHMENT"
    assert account["people_query"] is not None


# ---------------------------------------------------------------------------
# no personal/individual-level data anywhere in a MatchedRepo
# ---------------------------------------------------------------------------


def test_matched_repo_has_no_individual_or_personal_fields():
    """FR-2 + PRD §17.2: only org/repo-level facts - no contributor username,
    email, or any other individual-level field."""
    repo = _repo()
    fields = set(repo.to_dict().keys())
    forbidden = {"login", "email", "author", "committer", "user", "contributor", "name", "id", "avatar_url"}
    assert fields == {
        "org_login", "repo_full_name", "repo_html_url", "query", "matched_path",
        "is_fork", "is_archived", "description",
    }
    assert fields.isdisjoint(forbidden)


# ---------------------------------------------------------------------------
# the committed snapshot: real, dated, org-level only
# ---------------------------------------------------------------------------


def test_snapshot_loads_and_holds_only_org_level_data():
    matches, as_of = load_snapshot()

    assert as_of
    assert len(matches) > 0
    for m in matches:
        assert isinstance(m, MatchedRepo)
        assert m.org_login
        assert m.repo_full_name


def test_snapshot_classification_matches_the_verified_table():
    """Pins the real, verified result: 10 raw matches -> 2 probable_user
    (sky-uk, quintoandar), 2 competitor (stargate, thelastpickle), 5
    integration (alibaba, Dataherald, rocketride-org, AI-Northstar-Tech,
    deepset-ai), 1 stale path (neurodata). See AI_WORKFLOW.md for the
    evidence behind each verdict.
    """
    matches, _ = load_snapshot()
    from hunter.models import load_config
    config = load_config().github_source

    classified = [classify_repo(m, config) for m in matches]
    by_org = {c.repo.org_login: c.verdict for c in classified}

    assert by_org["sky-uk"] == PROBABLE_USER
    assert by_org["quintoandar"] == PROBABLE_USER
    assert by_org["stargate"] == EXCLUDED_COMPETITOR
    assert by_org["thelastpickle"] == EXCLUDED_COMPETITOR
    assert by_org["deepset-ai"] == EXCLUDED_INTEGRATION
    assert by_org["rocketride-org"] == EXCLUDED_INTEGRATION
    assert by_org["AI-Northstar-Tech"] == EXCLUDED_INTEGRATION
    assert by_org["alibaba"] == EXCLUDED_INTEGRATION
    assert by_org["Dataherald"] == EXCLUDED_INTEGRATION
    assert by_org["neurodata"] == EXCLUDED_STALE_PATH
    assert sum(1 for v in by_org.values() if v == PROBABLE_USER) == 2


# ---------------------------------------------------------------------------
# report.live_discovered_accounts
# ---------------------------------------------------------------------------


def test_live_discovered_accounts_empty_when_only_fixtures_present(sources_conn):
    db.upsert_account(
        sources_conn, id="a01", name="Northwind Payments", domain="northwindpay.example",
        industry="Fintech", employees=500, hq="NY",
    )
    assert report.live_discovered_accounts(sources_conn) == []


def test_live_discovered_accounts_lists_github_accounts(sources_conn, config):
    classified = [classify_repo(_repo(), _config())]
    store_discovered_accounts(sources_conn, classified, as_of=config.as_of)
    scoring.score_accounts(sources_conn, config, config.as_of)

    live = report.live_discovered_accounts(sources_conn)

    assert len(live) == 1
    assert live[0]["name"] == "acme-corp"
    assert live[0]["source"] == "github"
    assert live[0]["status"] == "NEEDS_ENRICHMENT"
    assert live[0]["target_title_count"] > 0


# ---------------------------------------------------------------------------
# CLI-level: the no-token snapshot fallback, and clean failure handling
# ---------------------------------------------------------------------------


def test_run_without_github_token_falls_back_to_snapshot_and_says_so(tmp_path, monkeypatch):
    """FR-2's AC: without a token, the command uses the committed, dated
    snapshot (not a skip) and says so; the fixture run is unaffected."""
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
    assert "committed, dated snapshot" in result.output
    assert "GitHub source (snapshot):" in result.output
    assert "Loaded 9 accounts" in result.output


def test_run_github_api_failure_is_reported_cleanly_not_a_crash(tmp_path, monkeypatch):
    """A GitHub API error (with a token present) must not crash the run -
    report it and continue with the fixtures already loaded."""
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

    assert result.exit_code == 0
    assert "GitHub API error 401" in result.output
    assert "Loaded 9 accounts" in result.output
