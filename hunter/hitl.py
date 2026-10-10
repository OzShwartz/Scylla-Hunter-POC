"""Human-in-the-loop approval routing (PRD §9.6).

review/approve/reject/edit commands are added in Phase 3.
"""

from __future__ import annotations

from hunter.models import Config


def determine_route(
    *,
    account_score: int,
    validators_passed: bool,
    has_high_confidence_evidence: bool,
    has_sensitive_content: bool,
    config: Config,
) -> tuple[str, str]:
    """Returns (approval_route, status) per PRD §9.6's routing table.

    Score reflects lead *quality*; it says nothing about message *risk*. A
    high-scoring account can still produce a draft that references a
    competitor product, the IBM/DataStax acquisition, or contract/renewal
    terms - that always goes to a human, regardless of score or approval_mode.
    """
    if config.runtime.approval_mode == "all":
        return "human", "PENDING_APPROVAL"

    if not validators_passed:
        return "human", "PENDING_APPROVAL"  # forced: validator_failed_after_retry

    if has_sensitive_content:
        return "human", "PENDING_APPROVAL"  # forced: sensitive_content, overrides score and approval_mode

    if config.runtime.approval_mode == "off":
        return "auto", "APPROVED"  # testing only: skips the high-confidence-evidence requirement

    if not has_high_confidence_evidence:
        return "human", "PENDING_APPROVAL"  # forced: no_high_confidence_evidence

    if account_score >= config.hitl.auto_send_min_account_score:
        return "auto", "APPROVED"
    return "human", "PENDING_APPROVAL"
