"""Evidence sources: fixtures loader and the GitHub code-search live source (FR-2).

Three layers, each independently testable:
- `search_github_code` is the only function that touches the network.
- `load_snapshot` reads the committed, dated fallback (`data/github_snapshot.json`)
  used when no GITHUB_TOKEN is set - the same raw match shape as a live search,
  so the classification step below treats both identically.
- `classify_repo` and `store_discovered_accounts` are pure, deterministic code
  over that raw match data - no network, no token, fully testable with fakes.
"""

from __future__ import annotations

import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from hunter import db
from hunter.models import Fixtures, GitHubSourceConfig

GITHUB_API_BASE = "https://api.github.com"
SNAPSHOT_PATH = "data/github_snapshot.json"

PROBABLE_USER = "probable_user"
EXCLUDED_COMPETITOR = "excluded_competitor"
EXCLUDED_INTEGRATION = "excluded_integration"
EXCLUDED_FORK_OR_ARCHIVED = "excluded_fork_or_archived"
EXCLUDED_SCYLLA_MENTION = "excluded_scylla_mention"
EXCLUDED_STALE_PATH = "excluded_stale_path"


def load_fixtures(path: str = "data/fixtures.json") -> Fixtures:
    with open(path) as f:
        raw = json.load(f)
    return Fixtures.model_validate(raw)


class GitHubSourceError(Exception):
    """The GitHub live source couldn't run - a clear message, never a stack trace."""


@dataclass
class MatchedRepo:
    """One raw code-search hit: organization-level and repo-level facts only -
    no contributor usernames, emails or any individual-level field is ever
    read from the API response or stored here (PRD §17.2's "only the data
    needed" extends to this source too, not just personalization)."""

    org_login: str
    repo_full_name: str
    repo_html_url: str
    query: str
    matched_path: str
    is_fork: bool
    is_archived: bool
    description: str | None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MatchedRepo":
        return cls(**d)


@dataclass
class ClassifiedRepo:
    repo: MatchedRepo
    verdict: str
    reason: str


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
        # GITHUB_API_BASE (module constant, above) is a hardcoded https:// URL - never a
        # variable or user-controlled scheme.
        with urllib.request.urlopen(request, timeout=15) as response:  # nosec B310
            return json.loads(response.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        raise GitHubSourceError(f"GitHub API error {e.code} for {path}: {body}") from e
    except urllib.error.URLError as e:
        raise GitHubSourceError(f"Could not reach the GitHub API: {e}") from e


def search_github_code(config: GitHubSourceConfig, *, token: str) -> list[MatchedRepo]:
    """FR-2: run the configured code-search queries, keep organization-owned
    repos, dedupe by repo. Classification (competitor/integration/fork
    filtering) happens separately in `classify_repo` - this only collects facts.
    """
    seen_repos: set[str] = set()
    matches: list[MatchedRepo] = []
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
            matches.append(
                MatchedRepo(
                    org_login=owner.get("login", full_name.split("/")[0]),
                    repo_full_name=full_name,
                    repo_html_url=repo.get("html_url", f"https://github.com/{full_name}"),
                    query=q,
                    matched_path=item.get("path", ""),
                    is_fork=bool(repo.get("fork", False)),
                    is_archived=bool(repo.get("archived", False)),
                    description=repo.get("description"),
                )
            )
    return matches


def save_snapshot(matches: list[MatchedRepo], *, as_of: date, path: str | Path = SNAPSHOT_PATH) -> None:
    """Writes the dated, committed fallback - org/repo-level facts only."""
    payload = {"as_of": as_of.isoformat(), "matches": [m.to_dict() for m in matches]}
    Path(path).write_text(json.dumps(payload, indent=2) + "\n")


def load_snapshot(path: str | Path = SNAPSHOT_PATH) -> tuple[list[MatchedRepo], str]:
    """Returns (matches, as_of) from the committed fallback."""
    with open(path) as f:
        raw = json.load(f)
    return [MatchedRepo.from_dict(m) for m in raw["matches"]], raw["as_of"]


def _mentions_any(text: str | None, keywords: list[str]) -> bool:
    text = (text or "").lower()
    return any(keyword.lower() in text for keyword in keywords)


def _path_is_integration_shaped(matched_path: str, config: GitHubSourceConfig) -> bool:
    segments = matched_path.lower().split("/")
    return any(keyword.rstrip("/").lower() in segments for keyword in config.exclude_if_path_contains)


def _repo_name_is_integration_shaped(repo_full_name: str, config: GitHubSourceConfig) -> bool:
    repo_name = repo_full_name.split("/")[-1].lower()
    return any(keyword.lower() in repo_name for keyword in config.exclude_if_repo_name_contains)


def _path_is_stale(matched_path: str, config: GitHubSourceConfig) -> bool:
    path_lower = matched_path.lower()
    return any(path_lower.endswith(suffix.lower()) for suffix in config.exclude_if_path_ends_with)


def classify_repo(repo: MatchedRepo, config: GitHubSourceConfig) -> ClassifiedRepo:
    """Deterministic, in this order:
    1. fork or archived - not an active, original codebase.
    2. a stale-looking matched path (e.g. requirements.txt.old) - not a currently-used dependency.
    3. mentions a ScyllaDB keyword - already a prospect, not a target (original FR-2 rule).
    4. competitor-affiliated org - the match proves the org *is* the competitor.
    5. integration-shaped path or repo name (generic) - proves a connector/example
       exists, not that this org runs the dependency themselves.
    6. a verified_integration_orgs entry - same reasoning as (5), for specific
       orgs individually confirmed where the generic rule in (5) doesn't happen
       to match this project's own naming (see config.yaml for the evidence).
    7. otherwise: probable_user.
    """
    if repo.is_fork or repo.is_archived:
        return ClassifiedRepo(repo, EXCLUDED_FORK_OR_ARCHIVED, "fork or archived repository, not an active original codebase")
    if _path_is_stale(repo.matched_path, config):
        return ClassifiedRepo(repo, EXCLUDED_STALE_PATH, f"matched path looks stale/superseded, not a currently-used dependency (path: {repo.matched_path!r})")
    if _mentions_any(repo.description, config.exclude_if_repo_mentions):
        return ClassifiedRepo(repo, EXCLUDED_SCYLLA_MENTION, "repo description mentions ScyllaDB - likely already a ScyllaDB user, not a target")
    if repo.org_login.lower() in {o.lower() for o in config.competitor_orgs}:
        return ClassifiedRepo(repo, EXCLUDED_COMPETITOR, "competitor-affiliated organization (see config.yaml's competitor_orgs)")
    if _path_is_integration_shaped(repo.matched_path, config) or _repo_name_is_integration_shaped(repo.repo_full_name, config):
        return ClassifiedRepo(
            repo, EXCLUDED_INTEGRATION,
            f"matched path/repo name looks like an integration, connector or example, not product usage (path: {repo.matched_path!r})",
        )
    verified_reason = config.verified_integration_orgs.get(repo.org_login)
    if verified_reason:
        return ClassifiedRepo(repo, EXCLUDED_INTEGRATION, verified_reason)
    return ClassifiedRepo(repo, PROBABLE_USER, f"organization-owned repo with a direct dependency match (path: {repo.matched_path!r})")


def store_discovered_accounts(conn: sqlite3.Connection, classified: list[ClassifiedRepo], *, as_of: date) -> list[str]:
    """Maps only `probable_user`-classified repos to accounts + a github_code
    signal each. Pure DB logic, no network - takes `classified` as data so
    it's testable with fakes. A live account has no firmographics (FR-2), so
    `employees` stays None - scoring.score_account already turns that into
    NEEDS_ENRICHMENT, and scoring.score_accounts generates a people_query for
    NEEDS_ENRICHMENT accounts too, not only QUALIFIED ones.
    """
    account_ids: list[str] = []
    for c in classified:
        if c.verdict != PROBABLE_USER:
            continue
        d = c.repo
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
            raw_text=f"Code search match for query {d.query!r} in {d.repo_full_name} at {d.matched_path}",
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


def run_github_source(
    conn: sqlite3.Connection, config: GitHubSourceConfig, *, token: str | None, as_of: date
) -> tuple[list[str], list[ClassifiedRepo], str]:
    """FR-2 end to end: live search with a token, the committed snapshot
    without one - then the same classify/store pipeline either way. Returns
    (created_account_ids, classified_repos, mode) where mode is "live" or
    "snapshot". Raises GitHubSourceError on a live API failure - callers
    must catch it and report cleanly, never crash the run.
    """
    if token:
        matches = search_github_code(config, token=token)
        mode = "live"
    else:
        matches, _snapshot_as_of = load_snapshot()
        mode = "snapshot"
    classified = [classify_repo(m, config) for m in matches]
    account_ids = store_discovered_accounts(conn, classified, as_of=as_of)
    return account_ids, classified, mode
