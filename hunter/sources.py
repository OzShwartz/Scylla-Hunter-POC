"""Evidence sources: fixtures loader and the GitHub code-search live source (FR-2).

The GitHub source is split into a network step (`search_github_code`, the
only function here that calls out) and a pure DB step (`store_discovered_accounts`),
so the mapping/filtering logic is testable without a token or a network call -
the project's "replay-first, no network in tests" rule applies here too, even
though this source has no replay cache of its own (it's opt-in and the PRD
doesn't ask for one - a live discovery feed has no fixed "expected" response).
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date

from hunter import db
from hunter.models import Fixtures, GitHubSourceConfig

GITHUB_API_BASE = "https://api.github.com"


def load_fixtures(path: str = "data/fixtures.json") -> Fixtures:
    with open(path) as f:
        raw = json.load(f)
    return Fixtures.model_validate(raw)


class GitHubSourceError(Exception):
    """The GitHub live source couldn't run - a clear message, never a stack trace."""


@dataclass
class DiscoveredAccount:
    org_login: str
    repo_full_name: str
    repo_html_url: str
    query: str
    flagged_scylla: bool


def _github_api_get(path: str, *, token: str, params: dict | None = None) -> dict:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(
        f"{GITHUB_API_BASE}{path}{query}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "scylla-hunter-poc",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise GitHubSourceError(f"GitHub API error {e.code} for {path}: {body}") from e
    except urllib.error.URLError as e:
        raise GitHubSourceError(f"Could not reach the GitHub API: {e}") from e


def _mentions_excluded_keyword(repo: dict, config: GitHubSourceConfig) -> bool:
    text = (repo.get("description") or "").lower()
    return any(keyword.lower() in text for keyword in config.exclude_if_repo_mentions)


def search_github_code(config: GitHubSourceConfig, *, token: str) -> list[DiscoveredAccount]:
    """FR-2: run the configured code-search queries, keep organization-owned
    repos, dedupe by repo, and flag (but still return - the caller decides
    whether to exclude) any repo whose description also mentions a keyword
    in `exclude_if_repo_mentions`.
    """
    seen_repos: set[str] = set()
    discovered: list[DiscoveredAccount] = []
    for q in config.queries:
        result = _github_api_get(
            "/search/code", token=token, params={"q": q, "per_page": config.max_results_per_query}
        )
        for item in result.get("items", [])[: config.max_results_per_query]:
            repo = item.get("repository") or {}
            owner = repo.get("owner") or {}
            if owner.get("type") != config.owner_type:
                continue
            full_name = repo.get("full_name")
            if not full_name or full_name in seen_repos:
                continue
            seen_repos.add(full_name)
            discovered.append(
                DiscoveredAccount(
                    org_login=owner.get("login", full_name.split("/")[0]),
                    repo_full_name=full_name,
                    repo_html_url=repo.get("html_url", f"https://github.com/{full_name}"),
                    query=q,
                    flagged_scylla=_mentions_excluded_keyword(repo, config),
                )
            )
    return discovered


def store_discovered_accounts(
    conn: sqlite3.Connection, discovered: list[DiscoveredAccount], *, as_of: date
) -> list[str]:
    """Maps non-flagged discovered repos to accounts + a github_code signal
    each. Pure DB logic, no network - takes `discovered` as data so it's
    testable with a fake list. A live account has no firmographics (FR-2),
    so `employees` stays None - scoring.score_account already turns that
    into NEEDS_ENRICHMENT, and scoring.score_accounts (updated for FR-2)
    generates a people_query for NEEDS_ENRICHMENT accounts too, not only
    QUALIFIED ones.
    """
    account_ids: list[str] = []
    for d in discovered:
        if d.flagged_scylla:
            continue
        account_id = f"gh_{d.org_login}"
        db.upsert_account(
            conn, id=account_id, name=d.org_login, domain=f"github.com/{d.org_login}",
            industry=None, employees=None, hq=None, source="github",
        )
        db.insert_signal(
            conn,
            id=f"gh_{d.repo_full_name.replace('/', '_')}",
            account_id=account_id,
            person_id=None,
            type="github_code",
            source_url=d.repo_html_url,
            published_at=as_of,
            raw_text=f"Code search match for query {d.query!r} in {d.repo_full_name}",
            uses_competitor=True,
            uses_cassandra=True,
            product=None,
            use_case=None,
            why_now=None,
            confidence="high",
            evidence_quote=None,
        )
        account_ids.append(account_id)
    return account_ids


def run_github_source(conn: sqlite3.Connection, config: GitHubSourceConfig, *, token: str, as_of: date) -> list[str]:
    """FR-2 end to end: search, then store. Raises GitHubSourceError on any
    API failure - callers must catch it and report cleanly, never crash the run."""
    discovered = search_github_code(config, token=token)
    return store_discovered_accounts(conn, discovered, as_of=as_of)
