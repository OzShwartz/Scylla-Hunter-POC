"""Message validators and grounding checks (PRD §11.4, §11.5)."""

from __future__ import annotations

import json
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

# The IBM/DataStax-acquisition framing specifically (narrower than
# COMPETITOR_MENTION_PATTERN, which also matches plain vendor/product names
# like "Astra DB" that are legitimate technical evidence, not ownership FUD).
IBM_ACQUISITION_PATTERN = re.compile(r"\bibm\b|acquisition|watsonx", re.IGNORECASE)
IBM_OPENING_WINDOW_CHARS = 100

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


def validate_no_ibm_fact_for_practitioner(draft: DraftResult, persona: str) -> list[str]:
    """PRD §11.5: the IBM/DataStax acquisition (cf_ibm) is a decision_maker-only
    angle - a practitioner email must stay purely technical. cf_ibm is already
    withheld from a practitioner's allowed context facts in the prompt
    (personalize._render_context_facts_block); this is the deterministic
    backstop that catches it regardless, since context_fact_ids is a
    structured field, not free text - no heuristic needed here.
    """
    if persona == "practitioner" and "cf_ibm" in draft.context_fact_ids:
        return ["Practitioner email cites cf_ibm (IBM/DataStax acquisition) - decision_maker angle only"]
    return []


def validate_ibm_mention_not_opening(draft: DraftResult) -> list[str]:
    """When cf_ibm is cited (decision_maker only), it must be one clause, not
    the opening - the acquisition should never be the first thing the lead
    reads. Heuristic position check, not exhaustive - see the pattern comment
    at the top of this module; "never the main argument" is a prompt
    instruction and a human-review concern, not something a position check
    alone can verify.
    """
    if "cf_ibm" not in draft.context_fact_ids:
        return []
    if IBM_ACQUISITION_PATTERN.search(draft.body[:IBM_OPENING_WINDOW_CHARS]):
        return ["Message opens with the IBM/DataStax acquisition - cite it later, as one short clause, not the opener"]
    return []


def validate_ibm_fact_requires_competitor_evidence(draft: DraftResult, evidence_signals: list[sqlite3.Row]) -> list[str]:
    """cf_ibm implies this *account* runs a DataStax/Cassandra product - that
    must be backed by the account's own high-confidence evidence, not a
    champion_move signal. champion_move describes a *person's* history at a
    *different* company (FR-5); it is correctly marked uses_competitor=True
    and confidence=high (inherited from the signal that named them, PRD §9.2),
    but using it to justify cf_ibm on the person's *current* account states a
    fact about that account which isn't actually known - an account whose only
    signal is a champion_move has no first-party evidence of its own stack.
    """
    if "cf_ibm" not in draft.context_fact_ids:
        return []
    has_direct_competitor_evidence = any(
        row["type"] != "champion_move" and row["confidence"] == "high" and bool(row["uses_competitor"])
        for row in evidence_signals
    )
    if not has_direct_competitor_evidence:
        return [
            "cf_ibm cited but this account has no high-confidence direct evidence of competitor usage - "
            "a champion_move signal describes the person's former employer, not this account's own stack"
        ]
    return []


def _normalize_first_sentence(text: str) -> str:
    first = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    return re.sub(r"[^a-z0-9 ]", "", first.lower()).strip()


def _word_5grams(text: str) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    n = 5
    if len(words) < n:
        return set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


# Documented threshold (PRD §11.5): a message may share at most 30% of its own
# 5-word phrases with another message already drafted for the same account.
# Chosen to tolerate the inevitable overlap from shared sender/company/opt-out
# boilerplate ("Reply STOP to opt out", "GTM Engineer, ScyllaDB") while still
# catching two messages that are substantively the same email with the name
# swapped - the failure mode colleagues actually notice when they compare notes.
MAX_FIVE_GRAM_OVERLAP_FRACTION = 0.3


def validate_distinct_from_account_siblings(draft: DraftResult, other_messages: list[sqlite3.Row]) -> list[str]:
    """PRD §11.5: messages to different leads at the same account must not
    read as the same template with the name swapped - colleagues forward
    these to each other. Checks the opening sentence (normalized) for an
    exact match, and 5-word-phrase overlap against the documented threshold.
    Heuristic, not exhaustive - see the pattern comment at the top of this
    module; it catches near-duplicate *wording*. It does not catch two
    messages that are worded differently but lead with the same underlying
    fact - validate_distinct_primary_evidence_for_account (below) is the
    simpler, structural check for that, and is the one Oz asked for after
    finding this check alone let Maya's and Tom's emails both lead with
    Northwind's case-study facts despite different phrasing.
    """
    errors: list[str] = []
    this_first_sentence = _normalize_first_sentence(draft.body)
    this_ngrams = _word_5grams(draft.body)

    for other in other_messages:
        other_body = other["body"]
        if this_first_sentence and this_first_sentence == _normalize_first_sentence(other_body):
            errors.append("Opening sentence is identical (after normalizing) to another message drafted for this account")
        other_ngrams = _word_5grams(other_body)
        if this_ngrams and other_ngrams:
            overlap = len(this_ngrams & other_ngrams) / len(this_ngrams)
            if overlap >= MAX_FIVE_GRAM_OVERLAP_FRACTION:
                errors.append(
                    f"Message shares {overlap:.0%} of its 5-word phrases with another message drafted for "
                    f"this account (threshold {MAX_FIVE_GRAM_OVERLAP_FRACTION:.0%}) - vary the wording and, "
                    "where possible, lead with a different evidence item"
                )
    return errors


def validate_distinct_primary_evidence_for_account(
    draft: DraftResult, other_messages: list[sqlite3.Row], evidence_signals: list[sqlite3.Row]
) -> list[str]:
    """PRD §11.5: when an account has more than one evidence item, each
    lead's message should lead with a different one. This is the structural
    check the n-gram/opening-sentence check above couldn't provide: Maya's
    and Tom's emails at Northwind both led with the case-study facts (fraud
    scoring, single-digit-ms reads, three regions, 40k TPS) despite
    different wording, which a text-similarity check alone will not
    reliably catch - the facts repeat, not the phrasing. `evidence_ids[0]`
    (the first evidence item cited) is treated as "what this message leads
    with," matching how the prompt is asked to order them.

    Also rejects citing a sibling's primary evidence at all (not just in
    first position): an early version checked `evidence_ids[0]` only, and a
    real recorded draft (Tom's cold email) satisfied that check by leading
    with his own evidence (s02) while still citing Maya's primary (s01) as a
    second item - and restating its headline facts in prose anyway. The
    headline fact a sibling already leads with isn't this message's to use
    at all when another evidence item is available.
    """
    if len(evidence_signals) <= 1 or not draft.evidence_ids:
        return []
    primary = draft.evidence_ids[0]
    for other in other_messages:
        other_evidence_ids = json.loads(other["evidence_ids"])
        if not other_evidence_ids:
            continue
        other_primary = other_evidence_ids[0]
        if other_primary == primary:
            return [
                f"Message leads with evidence {primary!r}, which is already the lead evidence item in "
                "another message drafted for this account - lead with a different one"
            ]
        if other_primary in draft.evidence_ids:
            return [
                f"Message cites {other_primary!r}, the lead evidence item in another message drafted for "
                "this account - leave it to that message and use a different evidence item here"
            ]
    return []


def validate_sender_sign_off(draft: DraftResult, variant: str, config: Config) -> list[str]:
    """PRD §11.5: every email states the sender's identity (name, title,
    company) before the opt-out line - Maya's draft surfaced a case where the
    sender was never named at all. Presence + ordering: an earlier
    self-introduction ("I'm Oz, GTM Engineer at ScyllaDB...") satisfies this
    too, as long as it comes before the opt-out line - this is not a strict
    "immediately before" window.
    """
    if variant == "invite":
        return []
    name = config.messaging.sender.name
    title = config.messaging.sender.title
    company = config.messaging.sender.company
    body = draft.body
    missing = [f for f in (name, title, company) if f not in body]
    if missing:
        return [f"Email never states the sender's {', '.join(missing)} before the opt-out line"]
    optout_match = OPT_OUT_PATTERN.search(body)
    if optout_match and body.rfind(name) > optout_match.start():
        return ["Sender identity appears after the opt-out line, not before it"]
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
    other_messages: list[sqlite3.Row] | None = None,
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
    errors += validate_no_ibm_fact_for_practitioner(draft, persona)
    errors += validate_ibm_mention_not_opening(draft)
    errors += validate_ibm_fact_requires_competitor_evidence(draft, evidence_signals)
    errors += validate_distinct_from_account_siblings(draft, other_messages or [])
    errors += validate_distinct_primary_evidence_for_account(draft, other_messages or [], evidence_signals)
    errors += validate_sender_sign_off(draft, variant, config)
    return errors
