"""Message validators and grounding checks (PRD §11.4, §11.5)."""

from __future__ import annotations

import re
import sqlite3

from hunter.models import Config, DraftResult

COMPETITOR_MENTION_PATTERN = re.compile(r"datastax|astra|\bdse\b|\bibm\b", re.IGNORECASE)
URL_PATTERN = re.compile(r"https?://|www\.|\.(com|io|net|org)\b", re.IGNORECASE)
OPT_OUT_PATTERN = re.compile(r"opt.?out|unsubscribe", re.IGNORECASE)

# Heuristic, not exhaustive: these catch the common shape of a sender making an
# unsupported claim about their own work/experience (the only real facts allowed
# about the sender are name, title and company - see prompts/personalize.md).
# Free-text hallucination has no fully general deterministic test; this is a
# pattern-based safety net for the known failure shape, not a semantic grounding check.
SENDER_CLAIM_PATTERNS = [
    # "I'm <anything up to the sentence end> working on/facing/etc." - the gap allows
    # for "I'm an engineer at ScyllaDB working on ...", not just "I'm working on ...".
    re.compile(r"\bI(?:'m| am)\b[^.!?]{0,60}\b(?:working on|dealt with|dealing with|facing|tackling|solving)\b", re.IGNORECASE),
    re.compile(r"\bI(?:'ve| have)\b[^.!?]{0,60}\b(?:worked on|seen|dealt with|faced|tackled|solved)\b", re.IGNORECASE),
    re.compile(r"\bin my experience\b", re.IGNORECASE),
    re.compile(r"\bmy team\b", re.IGNORECASE),
    re.compile(r"\bwe(?:'re| are)\b[^.!?]{0,60}\b(?:working on|dealing with|facing)\b", re.IGNORECASE),
]

# Heuristic, not exhaustive: a fixed set of common ways to phrase "thanks for
# connecting" - a warm email paraphrasing this unusually would false-fail.
CONNECTION_ACK_PATTERN = re.compile(
    r"thanks for connecting|glad (?:we'?re|to be) connected|since (?:we connected|connecting)|"
    r"now that we'?re connected|great to (?:be|now be) connected",
    re.IGNORECASE,
)

RENEWAL_CONTRACT_PATTERN = re.compile(r"\brenewal\b|\bcontract\b|\brfp\b|\bprocurement\b", re.IGNORECASE)

MAX_EVIDENCE_ITEMS_PER_MESSAGE = 2


def validate_length(draft: DraftResult, variant: str, config: Config) -> list[str]:
    errors = []
    if variant == "invite":
        if len(draft.body) > config.messaging.linkedin_invite_max_chars:
            errors.append(
                f"Invite body is {len(draft.body)} chars, over the {config.messaging.linkedin_invite_max_chars} limit"
            )
    else:
        word_count = len(draft.body.split())
        if word_count > config.messaging.email_max_words:
            errors.append(f"Email body is {word_count} words, over the {config.messaging.email_max_words} limit")
        if draft.subject and len(draft.subject) > 60:
            errors.append(f"Email subject is {len(draft.subject)} chars, over the 60 limit")
    return errors


def validate_no_url(draft: DraftResult, variant: str) -> list[str]:
    if variant == "invite" and URL_PATTERN.search(draft.body):
        return ["Invite body contains a URL or link"]
    return []


def validate_banned_phrases(draft: DraftResult, config: Config) -> list[str]:
    text = f"{draft.subject or ''} {draft.body}".lower()
    hits = [p for p in config.messaging.banned_phrases if p.lower() in text]
    return [f"Banned phrase present: {p!r}" for p in hits]


def validate_value_prop_persona(draft: DraftResult, persona: str, config: Config, variant: str) -> list[str]:
    if variant == "invite":
        return []
    allowed = (
        config.personas.decision_maker.angles if persona == "decision_maker" else config.personas.practitioner.angles
    )
    errors = []
    if not draft.value_prop_ids:
        errors.append("Email cites no value prop")
    for vp_id in draft.value_prop_ids:
        if vp_id not in allowed:
            errors.append(f"Value prop {vp_id!r} is not allowed for persona {persona!r}")
    return errors


def validate_grounding(
    draft: DraftResult,
    evidence_signals: list[sqlite3.Row],
    config: Config,
) -> list[str]:
    errors = []
    evidence_by_id = {row["id"]: row for row in evidence_signals}

    for eid in draft.evidence_ids:
        if eid not in evidence_by_id:
            errors.append(f"evidence_id {eid!r} does not exist or does not belong to this lead's account")

    if COMPETITOR_MENTION_PATTERN.search(draft.body):
        has_high_confidence = any(
            evidence_by_id.get(eid) is not None and evidence_by_id[eid]["confidence"] == "high"
            for eid in draft.evidence_ids
        )
        if not has_high_confidence:
            errors.append("Message mentions DataStax/Astra/DSE but cites no high-confidence evidence item")

    allowed_fact_ids = {cf.id for cf in config.messaging.context_facts}
    for cf_id in draft.context_fact_ids:
        if cf_id not in allowed_fact_ids:
            errors.append(f"context_fact_id {cf_id!r} is not in the allowed list")

    return errors


def validate_opt_out_line(draft: DraftResult, variant: str) -> list[str]:
    if variant != "invite" and not OPT_OUT_PATTERN.search(draft.body):
        return ["Email body has no opt-out line"]
    return []


def validate_name_and_company_match(draft: DraftResult, first_name: str, company_name: str) -> list[str]:
    errors = []
    if first_name.lower() not in draft.body.lower():
        errors.append(f"Body does not mention the lead's first name ({first_name!r})")
    if company_name.lower() not in draft.body.lower():
        errors.append(f"Body does not mention the lead's company ({company_name!r})")
    return errors


def validate_no_sender_claims(draft: DraftResult) -> list[str]:
    """The sender's only known facts are name, title and company (see prompts/personalize.md).
    Heuristic, not exhaustive - see the pattern comment above.
    """
    text = f"{draft.subject or ''} {draft.body}"
    hits = [p.pattern for p in SENDER_CLAIM_PATTERNS if p.search(text)]
    return [f"Body appears to make an unsupported claim about the sender's own work ({h!r})" for h in hits]


def validate_no_competitor_mention_in_invite(draft: DraftResult, variant: str) -> list[str]:
    if variant == "invite" and COMPETITOR_MENTION_PATTERN.search(draft.body):
        return [
            "Invite names a competitor product/vendor (DataStax/Astra/DSE/IBM) - "
            "reference the lead's own work instead; vendor names belong in the email"
        ]
    return []


def validate_connection_framing(draft: DraftResult, variant: str) -> list[str]:
    """Heuristic, not exhaustive - see the pattern comment above."""
    if variant == "warm" and not CONNECTION_ACK_PATTERN.search(draft.body[:150]):
        return ["Warm email does not open by acknowledging the accepted connection"]
    if variant == "cold" and CONNECTION_ACK_PATTERN.search(draft.body):
        return ["Cold email assumes a connection that has not been accepted"]
    return []


def validate_evidence_count(draft: DraftResult) -> list[str]:
    if len(draft.evidence_ids) > MAX_EVIDENCE_ITEMS_PER_MESSAGE:
        return [
            f"Message cites {len(draft.evidence_ids)} evidence items, over the "
            f"{MAX_EVIDENCE_ITEMS_PER_MESSAGE} limit - pick the strongest ones"
        ]
    return []


def is_sensitive_content(draft: DraftResult) -> bool:
    """PRD §9.6: content that must always get human review, regardless of account
    score or approval_mode - a competitor product mention, the IBM/DataStax
    acquisition, or any renewal/contract reference. This is a routing input, not
    a pass/fail validator - sensitive content can still be a perfectly good draft.
    """
    text = f"{draft.subject or ''} {draft.body}"
    if COMPETITOR_MENTION_PATTERN.search(text):
        return True
    if "cf_ibm" in draft.context_fact_ids:
        return True
    if RENEWAL_CONTRACT_PATTERN.search(text):
        return True
    return False


def validate_message(
    draft: DraftResult,
    *,
    variant: str,
    persona: str,
    first_name: str,
    company_name: str,
    evidence_signals: list[sqlite3.Row],
    config: Config,
) -> list[str]:
    errors: list[str] = []
    errors += validate_length(draft, variant, config)
    errors += validate_no_url(draft, variant)
    errors += validate_banned_phrases(draft, config)
    errors += validate_value_prop_persona(draft, persona, config, variant)
    errors += validate_grounding(draft, evidence_signals, config)
    errors += validate_opt_out_line(draft, variant)
    errors += validate_name_and_company_match(draft, first_name, company_name)
    errors += validate_no_sender_claims(draft)
    errors += validate_no_competitor_mention_in_invite(draft, variant)
    errors += validate_connection_framing(draft, variant)
    errors += validate_evidence_count(draft)
    return errors
