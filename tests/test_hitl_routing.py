from hunter import hitl


def test_high_score_valid_grounded_clean_content_auto_approves(config):
    route, status, reason = hitl.determine_route(
        account_score=96, validators_passed=True, has_high_confidence_evidence=True,
        has_sensitive_content=False, config=config,
    )
    assert (route, status) == ("auto", "APPROVED")
    assert "96" in reason


def test_mid_score_routes_to_human(config):
    route, status, reason = hitl.determine_route(
        account_score=76, validators_passed=True, has_high_confidence_evidence=True,
        has_sensitive_content=False, config=config,
    )
    assert (route, status) == ("human", "PENDING_APPROVAL")
    assert "76" in reason


def test_validator_failure_forces_human_even_at_high_score(config):
    route, status, reason = hitl.determine_route(
        account_score=96, validators_passed=False, has_high_confidence_evidence=True,
        has_sensitive_content=False, config=config,
    )
    assert (route, status) == ("human", "PENDING_APPROVAL")
    assert "validator" in reason


def test_no_high_confidence_evidence_forces_human_even_at_high_score(config):
    route, status, reason = hitl.determine_route(
        account_score=96, validators_passed=True, has_high_confidence_evidence=False,
        has_sensitive_content=False, config=config,
    )
    assert (route, status) == ("human", "PENDING_APPROVAL")
    assert "evidence" in reason


def test_sensitive_content_forces_human_even_at_high_score(config):
    """PRD §9.6: score reflects lead quality, not message risk - a draft naming a
    competitor product, the IBM acquisition, or a renewal/contract always goes to
    a human, regardless of how well-qualified the account is.
    """
    route, status, reason = hitl.determine_route(
        account_score=96, validators_passed=True, has_high_confidence_evidence=True,
        has_sensitive_content=True, config=config,
    )
    assert (route, status) == ("human", "PENDING_APPROVAL")
    assert "competitor" in reason
