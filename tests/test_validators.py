from hunter import validators
from hunter.models import DraftResult


def _evidence():
    return [
        {"id": "s01", "confidence": "high"},
        {"id": "s02", "confidence": "medium"},
    ]


def test_invite_over_length_fails(config):
    draft = DraftResult(body="x" * (config.messaging.linkedin_invite_max_chars + 1), evidence_ids=["s01"])
    errors = validators.validate_length(draft, "invite", config)
    assert any("over" in e for e in errors)


def test_email_over_word_count_fails(config):
    draft = DraftResult(
        subject="Subject",
        body=" ".join(["word"] * (config.messaging.email_max_words + 1)),
        evidence_ids=["s01"],
    )
    errors = validators.validate_length(draft, "warm", config)
    assert any("words, over" in e for e in errors)


def test_email_subject_over_60_chars_fails(config):
    draft = DraftResult(subject="x" * 61, body="short body", evidence_ids=["s01"])
    errors = validators.validate_length(draft, "warm", config)
    assert any("subject" in e.lower() for e in errors)


def test_invite_with_url_fails():
    draft = DraftResult(body="Check out https://scylladb.com for more info.", evidence_ids=["s01"])
    errors = validators.validate_no_url(draft, "invite")
    assert errors


def test_email_with_url_is_allowed():
    draft = DraftResult(body="Check out https://scylladb.com for more info.", evidence_ids=["s01"])
    errors = validators.validate_no_url(draft, "warm")
    assert errors == []


def test_banned_phrase_fails(config):
    banned = config.messaging.banned_phrases[0]
    draft = DraftResult(body=f"Hi there, {banned}! Let's talk.", evidence_ids=["s01"])
    errors = validators.validate_banned_phrases(draft, config)
    assert errors


def test_value_prop_not_allowed_for_persona_fails(config):
    disallowed = next(
        vp.id for vp in config.messaging.value_props if vp.id not in config.personas.practitioner.angles
    )
    draft = DraftResult(subject="S", body="b", evidence_ids=["s01"], value_prop_ids=[disallowed])
    errors = validators.validate_value_prop_persona(draft, "practitioner", config, "warm")
    assert any("not allowed for persona" in e for e in errors)


def test_email_with_no_value_prop_fails(config):
    draft = DraftResult(subject="S", body="b", evidence_ids=["s01"], value_prop_ids=[])
    errors = validators.validate_value_prop_persona(draft, "practitioner", config, "warm")
    assert any("cites no value prop" in e for e in errors)


def test_invite_skips_value_prop_check(config):
    draft = DraftResult(body="b", evidence_ids=["s01"], value_prop_ids=[])
    errors = validators.validate_value_prop_persona(draft, "practitioner", config, "invite")
    assert errors == []


def test_nonexistent_evidence_id_fails(config):
    draft = DraftResult(body="b", evidence_ids=["s99"])
    errors = validators.validate_grounding(draft, _evidence(), config)
    assert any("s99" in e for e in errors)


def test_competitor_mention_without_high_confidence_citation_fails(config):
    draft = DraftResult(body="I saw you use DataStax Enterprise.", evidence_ids=["s02"])  # s02 is medium
    errors = validators.validate_grounding(draft, _evidence(), config)
    assert any("DataStax/Astra/DSE" in e for e in errors)


def test_competitor_mention_with_high_confidence_citation_passes(config):
    draft = DraftResult(body="I saw you use DataStax Enterprise.", evidence_ids=["s01"])  # s01 is high
    errors = validators.validate_grounding(draft, _evidence(), config)
    assert errors == []


def test_disallowed_context_fact_id_fails(config):
    draft = DraftResult(body="b", evidence_ids=["s01"], context_fact_ids=["cf_not_real"])
    errors = validators.validate_grounding(draft, _evidence(), config)
    assert any("cf_not_real" in e for e in errors)


def test_email_without_opt_out_line_fails():
    draft = DraftResult(subject="S", body="A normal email with no closing line.", evidence_ids=["s01"])
    errors = validators.validate_opt_out_line(draft, "warm")
    assert errors


def test_email_with_opt_out_line_passes():
    draft = DraftResult(subject="S", body="A normal email. Reply STOP to opt out.", evidence_ids=["s01"])
    errors = validators.validate_opt_out_line(draft, "warm")
    assert errors == []


def test_invite_skips_opt_out_check():
    draft = DraftResult(body="A normal invite with no opt-out line.", evidence_ids=["s01"])
    errors = validators.validate_opt_out_line(draft, "invite")
    assert errors == []


def test_missing_first_name_fails():
    draft = DraftResult(body="Hi there, I saw your work at Acme Corp.", evidence_ids=["s01"])
    errors = validators.validate_name_and_company_match(draft, "Maya", "Acme Corp")
    assert any("first name" in e for e in errors)


def test_missing_company_fails():
    draft = DraftResult(body="Hi Maya, great to connect with you.", evidence_ids=["s01"])
    errors = validators.validate_name_and_company_match(draft, "Maya", "Acme Corp")
    assert any("company" in e for e in errors)


def test_name_and_company_present_passes():
    draft = DraftResult(body="Hi Maya, I saw your work at Acme Corp.", evidence_ids=["s01"])
    errors = validators.validate_name_and_company_match(draft, "Maya", "Acme Corp")
    assert errors == []


def test_sender_hallucination_fails():
    # Oz's exact flagged example.
    draft = DraftResult(
        body="Hi Maya, great numbers. I'm an engineer at ScyllaDB working on similar latency problems.",
        evidence_ids=["s01"],
    )
    errors = validators.validate_no_sender_claims(draft)
    assert errors


def test_sender_identity_only_statement_passes():
    draft = DraftResult(body="Hi Maya, I'm Oz, GTM Engineer at ScyllaDB. Glad to connect.", evidence_ids=["s01"])
    errors = validators.validate_no_sender_claims(draft)
    assert errors == []


def test_invite_naming_competitor_product_fails():
    draft = DraftResult(body="Hi Maya, I saw you run Astra DB at Northwind.", evidence_ids=["s01"])
    errors = validators.validate_no_competitor_mention_in_invite(draft, "invite")
    assert errors


def test_invite_naming_ibm_fails():
    draft = DraftResult(body="Hi Maya, with the IBM news this seems timely.", evidence_ids=["s01"])
    errors = validators.validate_no_competitor_mention_in_invite(draft, "invite")
    assert errors


def test_invite_without_competitor_mention_passes():
    draft = DraftResult(body="Hi Maya, I saw your fraud-scoring work at Northwind.", evidence_ids=["s01"])
    errors = validators.validate_no_competitor_mention_in_invite(draft, "invite")
    assert errors == []


def test_email_mentioning_competitor_is_allowed_by_this_check():
    # Vendor names belong in the email - this check only restricts invites.
    draft = DraftResult(body="Hi Maya, re: your Astra DB setup.", evidence_ids=["s01"])
    errors = validators.validate_no_competitor_mention_in_invite(draft, "warm")
    assert errors == []


def test_warm_email_without_connection_ack_fails():
    draft = DraftResult(subject="S", body="Hi Maya, following up on fraud scoring. Reply STOP to opt out.", evidence_ids=["s01"])
    errors = validators.validate_connection_framing(draft, "warm")
    assert errors


def test_warm_email_with_connection_ack_passes():
    draft = DraftResult(subject="S", body="Hi Maya, thanks for connecting! Following up on fraud scoring.", evidence_ids=["s01"])
    errors = validators.validate_connection_framing(draft, "warm")
    assert errors == []


def test_cold_email_assuming_connection_fails():
    draft = DraftResult(subject="S", body="Hi Maya, thanks for connecting last week.", evidence_ids=["s01"])
    errors = validators.validate_connection_framing(draft, "cold")
    assert errors


def test_cold_email_without_connection_assumption_passes():
    draft = DraftResult(subject="S", body="Hi Maya, reaching out again about fraud scoring.", evidence_ids=["s01"])
    errors = validators.validate_connection_framing(draft, "cold")
    assert errors == []


def test_too_many_evidence_items_fails():
    draft = DraftResult(body="b", evidence_ids=["s01", "s02", "s03"])
    errors = validators.validate_evidence_count(draft)
    assert errors


def test_two_evidence_items_passes():
    draft = DraftResult(body="b", evidence_ids=["s01", "s02"])
    errors = validators.validate_evidence_count(draft)
    assert errors == []


def test_sensitive_content_detects_competitor_product_mention():
    draft = DraftResult(subject="S", body="I saw you use DataStax Enterprise.", evidence_ids=["s01"])
    assert validators.is_sensitive_content(draft)


def test_sensitive_content_detects_ibm_acquisition_context_fact():
    draft = DraftResult(subject="S", body="A relevant moment for your stack.", evidence_ids=["s01"], context_fact_ids=["cf_ibm"])
    assert validators.is_sensitive_content(draft)


def test_sensitive_content_detects_renewal_mention():
    draft = DraftResult(subject="S", body="Ahead of your contract renewal this seemed timely.", evidence_ids=["s01"])
    assert validators.is_sensitive_content(draft)


def test_sensitive_content_absent_for_clean_draft():
    draft = DraftResult(subject="S", body="Hi Maya, following up on fraud scoring at Northwind.", evidence_ids=["s01"])
    assert not validators.is_sensitive_content(draft)
