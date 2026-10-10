from hunter import db


def test_hr_department_rejected_despite_strong_account(pipeline_conn):
    ruth = db.get_lead(pipeline_conn, "p04")
    assert ruth["status"] == "REJECTED"
    northwind = db.get_account(pipeline_conn, "a01")
    assert northwind["status"] == "QUALIFIED"


def test_too_small_account_rejected(pipeline_conn):
    sprocket = db.get_account(pipeline_conn, "a09")
    assert sprocket["status"] == "REJECTED"
    assert sprocket["employees"] < 100


def test_competitor_domain_suppressed(pipeline_conn):
    datastax = db.get_account(pipeline_conn, "a07")
    assert datastax["status"] == "SUPPRESSED"
    priya = db.get_lead(pipeline_conn, "p11")
    assert priya["status"] == "SUPPRESSED"


def test_existing_customer_suppressed(pipeline_conn):
    quanta = db.get_account(pipeline_conn, "a06")
    assert quanta["status"] == "SUPPRESSED"
    felix = db.get_lead(pipeline_conn, "p10")
    assert felix["status"] == "SUPPRESSED"


def test_opted_out_person_suppressed(pipeline_conn):
    rita = db.get_lead(pipeline_conn, "p06")
    assert rita["status"] == "SUPPRESSED"
    lumen = db.get_account(pipeline_conn, "a02")
    assert lumen["status"] == "QUALIFIED"  # the account itself is fine; only Rita is suppressed


def test_multi_threading_cap(pipeline_conn, config):
    ana = db.get_lead(pipeline_conn, "p03")
    assert ana["status"] == "DEPRIORITIZED"
    selected_at_northwind = [
        lead for lead in db.list_leads_for_account(pipeline_conn, "a01") if lead["status"] == "QUALIFIED"
    ]
    assert len(selected_at_northwind) == config.scoring.max_leads_per_account
