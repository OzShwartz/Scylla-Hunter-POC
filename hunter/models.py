"""Pydantic models for config, accounts, signals, leads, messages, events and runs."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class _ConfigYAMLLoader(yaml.SafeLoader):
    """SafeLoader restricted to true/false as booleans.

    config.yaml's `sequence` list uses an unquoted `on:` key (PRD §12.1's
    rule ids). Stock PyYAML follows YAML 1.1 and resolves on/off/yes/no as
    booleans too, silently turning that key into `True`. Narrowing the bool
    resolver keeps `dry_run: true` etc. working while leaving `on` a string.
    """


_ConfigYAMLLoader.yaml_implicit_resolvers = {
    first_char: [(tag, regexp) for tag, regexp in resolvers if tag != "tag:yaml.org,2002:bool"]
    for first_char, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_ConfigYAMLLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$"),
    list("tTfF"),
)

# ---------------------------------------------------------------------------
# config.yaml
# ---------------------------------------------------------------------------


class RuntimeConfig(BaseModel):
    dry_run: bool
    approval_mode: Literal["all", "threshold", "off"]
    db_path: str
    outbox_path: str
    report_path: str
    report_html_path: str


class LLMModelsConfig(BaseModel):
    extraction: str
    personalization: str


class LLMMaxTokensConfig(BaseModel):
    extraction: int
    personalization: int


EffortLevel = Literal["low", "medium", "high", "xhigh", "max"]


class LLMEffortConfig(BaseModel):
    extraction: EffortLevel
    personalization: EffortLevel


class LLMConfig(BaseModel):
    mode: Literal["replay", "live"]
    replay_dir: str
    models: LLMModelsConfig
    max_tokens: LLMMaxTokensConfig
    effort: LLMEffortConfig
    max_retries_on_validation_fail: int


class EmployeeBand(BaseModel):
    min: int
    max: int | None
    points: int


class ICPConfig(BaseModel):
    min_employees: int
    priority_industries: list[str]
    employee_bands: list[EmployeeBand]
    industry_bonus: int


class WhyNowConfig(BaseModel):
    window_months: int
    bonus: int
    migration_keywords: list[str]


class SignalsConfig(BaseModel):
    weights: dict[str, float]
    confidence: dict[str, float]
    recency_half_life_months: float
    top_n_signals: int
    max_evidence_points: float
    why_now: WhyNowConfig


class ScoringConfig(BaseModel):
    account_threshold: int
    max_leads_per_account: int


class PersonaConfig(BaseModel):
    titles: list[str]
    priority: int
    angles: list[str]


class PersonasConfig(BaseModel):
    decision_maker: PersonaConfig
    practitioner: PersonaConfig
    excluded_departments: list[str]
    profile_skill_keywords: list[str]


class SuppressionConfig(BaseModel):
    competitor_domains: list[str]
    existing_customer_domains: list[str]
    opted_out_emails: list[str]
    already_contacted: bool


class HITLConfig(BaseModel):
    auto_send_min_account_score: int
    force_review_if: list[str]
    production_note: str = ""


class ValueProp(BaseModel):
    id: str
    text: str
    verify: bool = False


class ContextFact(BaseModel):
    id: str
    text: str
    allowed_personas: list[str] | None = None  # None = offered to every persona


class MessagingSender(BaseModel):
    name: str
    title: str
    company: str


class MessagingConfig(BaseModel):
    prompt_version: str
    sender: MessagingSender
    linkedin_invite_max_chars: int
    email_max_words: int
    value_props: list[ValueProp]
    context_facts: list[ContextFact]
    rules: list[str]
    banned_phrases: list[str]


class SequenceRule(BaseModel):
    id: str
    on: str
    action: str
    variant: str | None = None
    days: int | None = None


class GitHubSourceConfig(BaseModel):
    enabled: bool
    queries: list[str]
    max_results_per_query: int
    owner_type: str
    exclude_if_repo_mentions: list[str]
    competitor_orgs: list[str] = []
    exclude_if_path_contains: list[str] = []
    exclude_if_repo_name_contains: list[str] = []
    exclude_if_path_ends_with: list[str] = []
    verified_integration_orgs: dict[str, str] = {}


class CampaignConfig(BaseModel):
    name: str
    competitor: str
    competitor_products: list[str]


class Config(BaseModel):
    as_of: date
    campaign: CampaignConfig
    runtime: RuntimeConfig
    llm: LLMConfig
    icp: ICPConfig
    signals: SignalsConfig
    scoring: ScoringConfig
    personas: PersonasConfig
    suppression: SuppressionConfig
    hitl: HITLConfig
    messaging: MessagingConfig
    sequence: list[SequenceRule]
    github_source: GitHubSourceConfig


# ---------------------------------------------------------------------------
# LLM extraction output schema (PRD §11.3)
# ---------------------------------------------------------------------------


class NamedPerson(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    role: str | None = None


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uses_competitor: bool
    uses_cassandra: bool
    product: str | None = None
    use_case: str | None = None
    why_now: str | None = None
    confidence: Literal["high", "medium", "low"]
    evidence_quote: str | None = None
    named_people: list[NamedPerson] = Field(default_factory=list)


class DraftResult(BaseModel):
    """LLM personalization output (PRD §11.5)."""

    model_config = ConfigDict(extra="forbid")

    subject: str | None = None
    body: str
    evidence_ids: list[str] = Field(default_factory=list)
    value_prop_ids: list[str] = Field(default_factory=list)
    context_fact_ids: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Domain entities (mirror the six SQLite tables, PRD §13 / ERD)
# ---------------------------------------------------------------------------


class Account(BaseModel):
    id: str
    name: str
    domain: str
    industry: str | None = None
    employees: int | None = None
    hq: str | None = None
    source: str = "fixtures"
    evidence_points: float = 0.0
    icp_points: int = 0
    why_now_points: int = 0
    account_score: int = 0
    status: str = "DISCOVERED"
    reason: str = ""
    people_query: dict | None = None


class Signal(BaseModel):
    id: str
    account_id: str
    person_id: str | None = None
    type: str
    source_url: str
    published_at: date
    raw_text: str
    uses_competitor: bool | None = None
    uses_cassandra: bool | None = None
    product: str | None = None
    use_case: str | None = None
    why_now: str | None = None
    confidence: Literal["high", "medium", "low"] | None = None
    evidence_quote: str | None = None
    value: float = 0.0


class Lead(BaseModel):
    id: str
    account_id: str
    first_name: str
    last_name: str
    title: str
    department: str | None = None
    persona: str | None = None
    skills: list[str] = Field(default_factory=list)
    linkedin_url: str
    email: str | None = None
    rank: int | None = None
    status: str = "DISCOVERED"
    reason: str = ""
    updated_at: datetime | None = None


class Message(BaseModel):
    id: int | None = None
    lead_id: str
    run_id: int | None = None
    channel: Literal["linkedin", "email"]
    variant: Literal["invite", "warm", "cold"]
    subject: str | None = None
    body: str
    original_body: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    value_prop_ids: list[str] = Field(default_factory=list)
    approval_route: Literal["auto", "human"]
    status: str = "DRAFTED"
    reviewer_note: str | None = None
    prompt_version: str
    model: str
    tokens: int = 0
    created_at: datetime | None = None
    sent_at: datetime | None = None


class Event(BaseModel):
    id: int | None = None
    lead_id: str | None = None
    run_id: int | None = None
    type: str
    payload: dict = Field(default_factory=dict)
    occurred_at: datetime


class Run(BaseModel):
    id: int | None = None
    command: str
    llm_mode: str
    models: dict = Field(default_factory=dict)
    prompt_versions: dict = Field(default_factory=dict)
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    started_at: datetime | None = None


# ---------------------------------------------------------------------------
# Fixtures (data/fixtures.json) - pipeline-visible fields only.
# `_expected` is loaded separately by hunter/evaluate.py and tests, never here.
# ---------------------------------------------------------------------------


class FixtureAccount(BaseModel):
    id: str
    name: str
    domain: str
    industry: str
    employees: int
    hq: str


class FixtureRawSignal(BaseModel):
    id: str
    account_id: str
    type: str
    source_url: str
    published_at: date
    text: str


class PreviousCompany(BaseModel):
    account_id: str
    title: str
    left_at: date


class FixturePerson(BaseModel):
    id: str
    account_id: str
    first_name: str
    last_name: str
    title: str
    department: str
    skills: list[str]
    email: str
    linkedin_url: str
    location: str
    previous_companies: list[PreviousCompany] = Field(default_factory=list)


class SimulatedEvent(BaseModel):
    lead_id: str
    event: str | None
    day: int | None = None
    note: str = ""


class Fixtures(BaseModel):
    accounts: list[FixtureAccount]
    raw_signals: list[FixtureRawSignal]
    people: list[FixturePerson]
    simulated_events: list[SimulatedEvent]


def load_config(path: str | Path = "config.yaml") -> Config:
    with open(path) as f:
        raw = yaml.load(f, Loader=_ConfigYAMLLoader)
    return Config.model_validate(raw)
