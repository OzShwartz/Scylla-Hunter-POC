"""FastAPI endpoints (POST /events, POST /tick) for the n8n trigger layer (PRD FR-12).

Thin wrappers only - no new business logic. Both endpoints call the exact
same `hunter/triggers.py` functions the CLI's `event`/`simulate` commands
call, then sweep approved messages with `hunter/dispatch.py` the same way.
The rule logic is identical regardless of whether the event/time source is
the CLI, the simulated clock, or n8n - only the source changes (PRD §12.2).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from hunter import db, dispatch, triggers
from hunter.llm import ReplayMissError
from hunter.models import load_config

app = FastAPI(title="Scylla Hunter trigger endpoint", description="PRD FR-12 - dry-run only, never a real send.")


class EventRequest(BaseModel):
    type: str
    lead_id: str


class TickRequest(BaseModel):
    days: int


def _connect():
    config = load_config()
    conn = db.connect(config.runtime.db_path)
    return config, conn


@app.post("/events")
def post_event(request: EventRequest) -> dict:
    if request.type != "connection_accepted":
        raise HTTPException(status_code=400, detail=f"Unsupported event type {request.type!r}. Supported: connection_accepted")

    config, conn = _connect()
    try:
        now = datetime.now()
        run_id = db.insert_run(conn, command="event", llm_mode=config.llm.mode, started_at=now)
        stats = triggers.TriggerStats()
        try:
            message_id = triggers.handle_connection_accepted(
                conn, config, request.lead_id, llm_mode=config.llm.mode, run_id=run_id, now=now, stats=stats
            )
        except ReplayMissError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

        db.update_run_counts(conn, run_id, llm_calls=stats.llm_calls, tokens_in=stats.tokens_in, tokens_out=stats.tokens_out)
        dispatch_stats = dispatch.dispatch_approved(conn, config, run_id=run_id, now=now)

        lead = db.get_lead(conn, request.lead_id)
        return {
            "status": "ok" if message_id is not None else "no_op",
            "lead_id": request.lead_id,
            "lead_status": lead["status"] if lead else None,
            "message_id": message_id,
            "dispatched_message_ids": dispatch_stats.sent_message_ids,
        }
    finally:
        conn.close()


@app.post("/tick")
def post_tick(request: TickRequest) -> dict:
    config, conn = _connect()
    try:
        now = datetime.now()
        run_id = db.insert_run(conn, command="tick", llm_mode=config.llm.mode, started_at=now)
        try:
            stats = triggers.tick(conn, config, days=request.days, llm_mode=config.llm.mode, run_id=run_id, now=now)
        except ReplayMissError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e

        db.update_run_counts(conn, run_id, llm_calls=stats.llm_calls, tokens_in=stats.tokens_in, tokens_out=stats.tokens_out)
        dispatch_stats = dispatch.dispatch_approved(conn, config, run_id=run_id, now=now)

        return {
            "cold_drafted": stats.cold_drafted,
            "forced_review": stats.forced_review,
            "dispatched_message_ids": dispatch_stats.sent_message_ids,
        }
    finally:
        conn.close()
