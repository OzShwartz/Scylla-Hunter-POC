from hunter import db

EXPECTED_SCORES = {
    "a01": 96,  # Northwind Payments
    "a04": 78,  # Kestrel Games
    "a02": 76,  # Lumen Logistics
    "a08": 61,  # Brightwave AI
    "a03": 23,  # Orbit Media
}


def test_scoring_matches_prd(pipeline_conn):
    for account_id, expected_score in EXPECTED_SCORES.items():
        row = db.get_account(pipeline_conn, account_id)
        assert row["account_score"] == expected_score, (
            f"{row['name']}: expected {expected_score}, got {row['account_score']}"
        )


def test_qualified_status_follows_threshold(pipeline_conn, config):
    for account_id, expected_score in EXPECTED_SCORES.items():
        row = db.get_account(pipeline_conn, account_id)
        expected_status = "QUALIFIED" if expected_score >= config.scoring.account_threshold else "REJECTED"
        assert row["status"] == expected_status
