import json

from hunter import db
from hunter.evaluate import STATUS_MAP


def test_all_13_lead_statuses_match_expected(pipeline_conn):
    with open("data/fixtures.json") as f:
        raw = json.load(f)

    mismatches = []
    for person in raw["people"]:
        expected_status = person["_expected"]["status"]
        lead = db.get_lead(pipeline_conn, person["id"])
        actual_status = STATUS_MAP.get(lead["status"], lead["status"])
        if actual_status != expected_status:
            mismatches.append(f"{person['id']} ({person['first_name']}): expected={expected_status} actual={lead['status']}")

    assert not mismatches, "\n".join(mismatches)
    assert len(raw["people"]) == 13
