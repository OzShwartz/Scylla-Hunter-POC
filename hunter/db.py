"""SQLite schema and CRUD for the six tables in PRD §13 / the ERD in §14.3."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    llm_mode TEXT NOT NULL,
    models TEXT NOT NULL DEFAULT '{}',
    prompt_versions TEXT NOT NULL DEFAULT '{}',
    llm_calls INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    domain TEXT NOT NULL UNIQUE,
    industry TEXT,
    employees INTEGER,
    hq TEXT,
    source TEXT NOT NULL DEFAULT 'fixtures',
    evidence_points REAL NOT NULL DEFAULT 0,
    icp_points INTEGER NOT NULL DEFAULT 0,
    why_now_points INTEGER NOT NULL DEFAULT 0,
    account_score INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    reason TEXT NOT NULL DEFAULT '',
    people_query TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    person_id TEXT,
    type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    published_at TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    uses_competitor INTEGER,
    uses_cassandra INTEGER,
    product TEXT,
    use_case TEXT,
    why_now TEXT,
    confidence TEXT,
    evidence_quote TEXT,
    value REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS leads (
    id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    title TEXT NOT NULL,
    department TEXT,
    persona TEXT,
    skills TEXT NOT NULL DEFAULT '[]',
    linkedin_url TEXT NOT NULL,
    email TEXT,
    rank INTEGER,
    status TEXT NOT NULL DEFAULT 'DISCOVERED',
    reason TEXT NOT NULL DEFAULT '',
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT NOT NULL REFERENCES leads(id),
    run_id INTEGER REFERENCES runs(id),
    channel TEXT NOT NULL,
    variant TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    original_body TEXT,
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    value_prop_ids TEXT NOT NULL DEFAULT '[]',
    approval_route TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DRAFTED',
    reviewer_note TEXT,
    prompt_version TEXT NOT NULL,
    model TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id TEXT REFERENCES leads(id),
    run_id INTEGER REFERENCES runs(id),
    type TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL
);
"""


def connect(db_path: str | Path = "hunter.db") -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def reset_db(db_path: str | Path = "hunter.db", outbox_path: str | Path | None = None) -> None:
    db_file = Path(db_path)
    if db_file.exists():
        db_file.unlink()
    conn = connect(db_path)
    try:
        init_db(conn)
    finally:
        conn.close()
    if outbox_path is not None:
        outbox_file = Path(outbox_path)
        if outbox_file.exists():
            outbox_file.unlink()


def _iso(value: date | datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------


def insert_run(conn: sqlite3.Connection, *, command: str, llm_mode: str, started_at: datetime) -> int:
    cur = conn.execute(
        "INSERT INTO runs (command, llm_mode, started_at) VALUES (?, ?, ?)",
        (command, llm_mode, _iso(started_at)),
    )
    conn.commit()
    return cur.lastrowid


def update_run_counts(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    models: dict | None = None,
    prompt_versions: dict | None = None,
    llm_calls: int = 0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
) -> None:
    conn.execute(
        """
        UPDATE runs SET
            models = COALESCE(?, models),
            prompt_versions = COALESCE(?, prompt_versions),
            llm_calls = llm_calls + ?,
            tokens_in = tokens_in + ?,
            tokens_out = tokens_out + ?,
            cache_creation_input_tokens = cache_creation_input_tokens + ?,
            cache_read_input_tokens = cache_read_input_tokens + ?
        WHERE id = ?
        """,
        (
            json.dumps(models) if models is not None else None,
            json.dumps(prompt_versions) if prompt_versions is not None else None,
            llm_calls,
            tokens_in,
            tokens_out,
            cache_creation_input_tokens,
            cache_read_input_tokens,
            run_id,
        ),
    )
    conn.commit()


def list_runs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM runs ORDER BY id").fetchall()


# ---------------------------------------------------------------------------
# accounts
# ---------------------------------------------------------------------------


def upsert_account(
    conn: sqlite3.Connection,
    *,
    id: str,
    name: str,
    domain: str,
    industry: str | None,
    employees: int | None,
    hq: str | None,
    source: str = "fixtures",
) -> None:
    conn.execute(
        """
        INSERT INTO accounts (id, name, domain, industry, employees, hq, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, domain=excluded.domain, industry=excluded.industry,
            employees=excluded.employees, hq=excluded.hq, source=excluded.source
        """,
        (id, name, domain, industry, employees, hq, source),
    )
    conn.commit()


def update_account_score(
    conn: sqlite3.Connection,
    account_id: str,
    *,
    evidence_points: float,
    icp_points: int,
    why_now_points: int,
    account_score: int,
    status: str,
    reason: str,
    people_query: dict | None = None,
) -> None:
    conn.execute(
        """
        UPDATE accounts SET
            evidence_points=?, icp_points=?, why_now_points=?, account_score=?,
            status=?, reason=?, people_query=?
        WHERE id=?
        """,
        (
            evidence_points,
            icp_points,
            why_now_points,
            account_score,
            status,
            reason,
            json.dumps(people_query) if people_query is not None else None,
            account_id,
        ),
    )
    conn.commit()


def get_account(conn: sqlite3.Connection, account_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()


def list_accounts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()


# ---------------------------------------------------------------------------
# signals
# ---------------------------------------------------------------------------


def insert_signal(
    conn: sqlite3.Connection,
    *,
    id: str,
    account_id: str,
    person_id: str | None,
    type: str,
    source_url: str,
    published_at: date,
    raw_text: str,
    uses_competitor: bool | None,
    uses_cassandra: bool | None,
    product: str | None,
    use_case: str | None,
    why_now: str | None,
    confidence: str | None,
    evidence_quote: str | None,
    value: float = 0.0,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO signals
            (id, account_id, person_id, type, source_url, published_at, raw_text,
             uses_competitor, uses_cassandra, product, use_case, why_now,
             confidence, evidence_quote, value)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            id,
            account_id,
            person_id,
            type,
            source_url,
            _iso(published_at),
            raw_text,
            None if uses_competitor is None else int(uses_competitor),
            None if uses_cassandra is None else int(uses_cassandra),
            product,
            use_case,
            why_now,
            confidence,
            evidence_quote,
            value,
        ),
    )
    conn.commit()


def update_signal_value(conn: sqlite3.Connection, signal_id: str, value: float) -> None:
    conn.execute("UPDATE signals SET value = ? WHERE id = ?", (value, signal_id))
    conn.commit()


def list_signals_for_account(conn: sqlite3.Connection, account_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM signals WHERE account_id = ? ORDER BY id", (account_id,)
    ).fetchall()


def list_signals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM signals ORDER BY id").fetchall()


def get_signal(conn: sqlite3.Connection, signal_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()


# ---------------------------------------------------------------------------
# leads
# ---------------------------------------------------------------------------


def upsert_lead(
    conn: sqlite3.Connection,
    *,
    id: str,
    account_id: str,
    first_name: str,
    last_name: str,
    title: str,
    department: str | None,
    skills: list[str],
    linkedin_url: str,
    email: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO leads (id, account_id, first_name, last_name, title, department, skills, linkedin_url, email)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            account_id=excluded.account_id, first_name=excluded.first_name,
            last_name=excluded.last_name, title=excluded.title, department=excluded.department,
            skills=excluded.skills, linkedin_url=excluded.linkedin_url, email=excluded.email
        """,
        (id, account_id, first_name, last_name, title, department, json.dumps(skills), linkedin_url, email),
    )
    conn.commit()


def update_lead_status(
    conn: sqlite3.Connection,
    lead_id: str,
    *,
    status: str,
    reason: str,
    persona: str | None = None,
    rank: int | None = None,
    updated_at: datetime,
) -> None:
    conn.execute(
        """
        UPDATE leads SET status=?, reason=?, persona=COALESCE(?, persona), rank=?, updated_at=?
        WHERE id=?
        """,
        (status, reason, persona, rank, _iso(updated_at), lead_id),
    )
    conn.commit()


def get_lead(conn: sqlite3.Connection, lead_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()


def list_leads(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM leads ORDER BY id").fetchall()


def list_leads_for_account(conn: sqlite3.Connection, account_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM leads WHERE account_id = ? ORDER BY id", (account_id,)).fetchall()


# ---------------------------------------------------------------------------
# messages
# ---------------------------------------------------------------------------


def insert_message(
    conn: sqlite3.Connection,
    *,
    lead_id: str,
    run_id: int | None,
    channel: str,
    variant: str,
    subject: str | None,
    body: str,
    evidence_ids: list[str],
    value_prop_ids: list[str],
    approval_route: str,
    status: str,
    prompt_version: str,
    model: str,
    tokens: int,
    created_at: datetime,
) -> int:
    cur = conn.execute(
        """
        INSERT INTO messages
            (lead_id, run_id, channel, variant, subject, body, evidence_ids, value_prop_ids,
             approval_route, status, prompt_version, model, tokens, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            lead_id,
            run_id,
            channel,
            variant,
            subject,
            body,
            json.dumps(evidence_ids),
            json.dumps(value_prop_ids),
            approval_route,
            status,
            prompt_version,
            model,
            tokens,
            _iso(created_at),
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_message_status(
    conn: sqlite3.Connection,
    message_id: int,
    *,
    status: str,
    reviewer_note: str | None = None,
    original_body: str | None = None,
    body: str | None = None,
    sent_at: datetime | None = None,
) -> None:
    conn.execute(
        """
        UPDATE messages SET
            status=?,
            reviewer_note=COALESCE(?, reviewer_note),
            original_body=COALESCE(?, original_body),
            body=COALESCE(?, body),
            sent_at=COALESCE(?, sent_at)
        WHERE id=?
        """,
        (status, reviewer_note, original_body, body, _iso(sent_at), message_id),
    )
    conn.commit()


def get_message(conn: sqlite3.Connection, message_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()


def list_messages(conn: sqlite3.Connection, *, status: str | None = None) -> list[sqlite3.Row]:
    if status is None:
        return conn.execute("SELECT * FROM messages ORDER BY id").fetchall()
    return conn.execute("SELECT * FROM messages WHERE status = ? ORDER BY id", (status,)).fetchall()


def list_messages_for_lead(conn: sqlite3.Connection, lead_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM messages WHERE lead_id = ? ORDER BY id", (lead_id,)).fetchall()


def list_messages_for_account(conn: sqlite3.Connection, account_id: str, *, exclude_lead_id: str | None = None) -> list[sqlite3.Row]:
    """Every message drafted for any lead at this account - used to keep
    same-account messages from reading like near-duplicates (PRD §11.5)."""
    if exclude_lead_id is None:
        return conn.execute(
            "SELECT m.* FROM messages m JOIN leads l ON m.lead_id = l.id WHERE l.account_id = ? ORDER BY m.id",
            (account_id,),
        ).fetchall()
    return conn.execute(
        "SELECT m.* FROM messages m JOIN leads l ON m.lead_id = l.id WHERE l.account_id = ? AND m.lead_id != ? ORDER BY m.id",
        (account_id, exclude_lead_id),
    ).fetchall()


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------


def insert_event(
    conn: sqlite3.Connection,
    *,
    lead_id: str | None,
    run_id: int | None,
    type: str,
    payload: dict,
    occurred_at: datetime,
) -> int:
    cur = conn.execute(
        "INSERT INTO events (lead_id, run_id, type, payload, occurred_at) VALUES (?, ?, ?, ?, ?)",
        (lead_id, run_id, type, json.dumps(payload), _iso(occurred_at)),
    )
    conn.commit()
    return cur.lastrowid


def list_events(conn: sqlite3.Connection, *, lead_id: str | None = None) -> list[sqlite3.Row]:
    if lead_id is None:
        return conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    return conn.execute("SELECT * FROM events WHERE lead_id = ? ORDER BY id", (lead_id,)).fetchall()
