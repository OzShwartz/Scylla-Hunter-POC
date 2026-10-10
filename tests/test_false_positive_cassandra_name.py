from hunter import db


def test_cassandra_person_name_not_extracted_as_database(pipeline_conn):
    """s08: 'You will report to Cassandra Lee, our Head of Data' must not be read
    as Apache Cassandra usage - this is the keyword-false-positive the PRD calls out.
    """
    signal = db.get_signal(pipeline_conn, "s08")
    assert signal is not None
    assert bool(signal["uses_cassandra"]) is False
    assert bool(signal["uses_competitor"]) is False


def test_pinecrest_account_rejected_for_no_evidence(pipeline_conn):
    pinecrest = db.get_account(pipeline_conn, "a05")
    assert pinecrest["status"] == "REJECTED"
    assert "evidence" in pinecrest["reason"].lower()


def test_cassandra_lee_person_rejected(pipeline_conn):
    cassandra_lee = db.get_lead(pipeline_conn, "p09")
    assert cassandra_lee["status"] == "REJECTED"
