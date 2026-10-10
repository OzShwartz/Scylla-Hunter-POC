"""Typer CLI: reset, run, review, approve, reject, edit, event, simulate, report, eval, serve."""

from __future__ import annotations

import json
from datetime import datetime

import typer
from dotenv import load_dotenv

from hunter import db, evaluate, hitl, scoring, sources
from hunter import extract as extract_mod
from hunter import personalize as personalize_mod
from hunter.llm import ReplayMissError
from hunter.models import load_config

load_dotenv()

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command()
def reset() -> None:
    """FR-11: recreate an empty database."""
    config = load_config()
    db.reset_db(config.runtime.db_path, config.runtime.outbox_path)
    typer.echo(f"Database reset: {config.runtime.db_path}")


@app.command()
def run(
    llm: str = typer.Option(None, "--llm", help="replay|live (overrides config.yaml's llm.mode)"),
    source: str = typer.Option("fixtures", "--source", help="fixtures|github|all"),
) -> None:
    """Load evidence, extract signals, score accounts, select leads."""
    config = load_config()
    llm_mode = llm or config.llm.mode

    if source != "fixtures":
        typer.echo(f"--source {source} is not implemented yet (PRD §15 Phase 8 / FR-2). Using fixtures.")

    conn = db.connect(config.runtime.db_path)
    db.init_db(conn)
    run_id = db.insert_run(conn, command="run", llm_mode=llm_mode, started_at=datetime.now())

    fixtures = sources.load_fixtures()
    for a in fixtures.accounts:
        db.upsert_account(
            conn, id=a.id, name=a.name, domain=a.domain, industry=a.industry, employees=a.employees, hq=a.hq
        )
    for p in fixtures.people:
        db.upsert_lead(
            conn, id=p.id, account_id=p.account_id, first_name=p.first_name, last_name=p.last_name,
            title=p.title, department=p.department, skills=p.skills, linkedin_url=p.linkedin_url, email=p.email,
        )

    typer.echo(f"Loaded {len(fixtures.accounts)} accounts, {len(fixtures.raw_signals)} raw signals, {len(fixtures.people)} people.")

    try:
        stats = extract_mod.extract_signals(conn, fixtures, config, llm_mode=llm_mode)
    except ReplayMissError as e:
        conn.close()
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None
    champions = extract_mod.detect_champion_moves(conn, fixtures)
    typer.echo(f"Extraction: {stats.llm_calls} LLM calls (mode={llm_mode}), {stats.tokens_in}/{stats.tokens_out} tokens in/out.")
    if champions:
        typer.echo(f"Champion-move signals derived: {len(champions)} ({', '.join(champions)})")
    if stats.flagged:
        typer.echo(f"Grounding flagged (confidence downgraded): {', '.join(stats.flagged)}")

    scoring.score_accounts(conn, config, config.as_of)
    scoring.select_leads(conn, config, datetime.now())

    try:
        personalize_stats = personalize_mod.draft_invites_for_qualified_leads(
            conn, config, llm_mode=llm_mode, run_id=run_id, now=datetime.now()
        )
    except ReplayMissError as e:
        conn.close()
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(
        f"Personalization: {personalize_stats.llm_calls} LLM calls (mode={llm_mode}), "
        f"{personalize_stats.tokens_in}/{personalize_stats.tokens_out} tokens in/out."
    )
    if personalize_stats.forced_review:
        typer.echo(f"Forced to review (validator failure after retry): {personalize_stats.forced_review}")

    db.update_run_counts(
        conn, run_id,
        models={"extraction": config.llm.models.extraction, "personalization": config.llm.models.personalization},
        prompt_versions={
            "extract_signals": extract_mod.load_prompt_spec(extract_mod.PROMPT_PATH).version,
            "personalize": personalize_mod.load_prompt_spec(personalize_mod.PROMPT_PATH).version,
        },
        llm_calls=stats.llm_calls + personalize_stats.llm_calls,
        tokens_in=stats.tokens_in + personalize_stats.tokens_in,
        tokens_out=stats.tokens_out + personalize_stats.tokens_out,
    )

    accounts = db.list_accounts(conn)
    qualified = [a for a in accounts if a["status"] == "QUALIFIED"]
    typer.echo(f"\nQualified accounts: {len(qualified)}/{len(accounts)}")
    for a in qualified:
        typer.echo(f"  {a['id']} {a['name']}: score={a['account_score']} -> {a['status']}")
        typer.echo(f"    people_query: {a['people_query']}")

    leads = db.list_leads(conn)
    selected = [lead for lead in leads if lead["status"] == "QUALIFIED"]
    typer.echo(f"\nSelected leads: {len(selected)}/{len(leads)}")
    for lead in selected:
        typer.echo(f"  {lead['id']} {lead['first_name']} {lead['last_name']} ({lead['persona']}, rank {lead['rank']})")

    messages = db.list_messages(conn)
    typer.echo(f"\nDrafted messages: {len(messages)}")
    for m in messages:
        typer.echo(f"  msg#{m['id']} lead={m['lead_id']} {m['channel']}/{m['variant']} route={m['approval_route']} status={m['status']}")

    conn.close()


@app.command()
def review() -> None:
    """FR-7: list drafts pending approval, with their evidence and routing reason."""
    config = load_config()
    conn = db.connect(config.runtime.db_path)
    pending = hitl.list_pending(conn)
    if not pending:
        typer.echo("No drafts pending approval.")
        conn.close()
        return

    for m in pending:
        lead = db.get_lead(conn, m["lead_id"])
        account = db.get_account(conn, lead["account_id"])
        reason = hitl.explain_route(conn, m, account, config)
        typer.echo(
            f"\nmsg#{m['id']} | {m['channel']}/{m['variant']} | "
            f"lead={lead['id']} {lead['first_name']} {lead['last_name']} ({lead['persona']}) @ "
            f"{account['name']} (score {account['account_score']})"
        )
        typer.echo(f"  reason: {reason}")
        if m["subject"]:
            typer.echo(f"  subject: {m['subject']}")
        typer.echo(f"  body: {m['body']}")
        if m["reviewer_note"]:
            typer.echo(f"  reviewer_note: {m['reviewer_note']}")
        evidence_ids = json.loads(m["evidence_ids"])
        if evidence_ids:
            typer.echo("  evidence:")
            for eid in evidence_ids:
                sig = db.get_signal(conn, eid)
                if sig is not None:
                    typer.echo(
                        f"    {sig['id']} | {sig['type']} | {sig['published_at']} | "
                        f"{sig['confidence']} | \"{sig['evidence_quote']}\""
                    )
        else:
            typer.echo("  evidence: (none)")
    conn.close()


@app.command()
def approve(
    message_id: int = typer.Argument(None),
    approve_all: bool = typer.Option(False, "--all", help="Approve every pending draft"),
) -> None:
    """FR-7: approve one pending draft, or every pending draft with --all."""
    config = load_config()
    conn = db.connect(config.runtime.db_path)
    if approve_all:
        ids = [m["id"] for m in hitl.list_pending(conn)]
        for mid in ids:
            hitl.approve(conn, mid, now=datetime.now())
        typer.echo(f"Approved {len(ids)} draft(s).")
        conn.close()
        return
    if message_id is None:
        conn.close()
        typer.echo("Error: pass a message id or --all", err=True)
        raise typer.Exit(code=1)
    try:
        hitl.approve(conn, message_id, now=datetime.now())
    except ValueError as e:
        conn.close()
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Approved msg#{message_id}.")
    conn.close()


@app.command()
def reject(
    message_id: int = typer.Argument(...),
    reason: str = typer.Option(..., "--reason", help="Why this draft is rejected"),
) -> None:
    """FR-7: reject one pending draft with a reason."""
    config = load_config()
    conn = db.connect(config.runtime.db_path)
    try:
        hitl.reject(conn, message_id, reason=reason, now=datetime.now())
    except ValueError as e:
        conn.close()
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None
    typer.echo(f"Rejected msg#{message_id}: {reason}")
    conn.close()


@app.command()
def edit(
    message_id: int = typer.Argument(...),
    text: str = typer.Option(..., "--text", help="Replacement body text"),
) -> None:
    """FR-7: edit a pending draft's body; original_body is kept and validators re-run."""
    config = load_config()
    conn = db.connect(config.runtime.db_path)
    try:
        message, errors = hitl.edit(conn, message_id, text=text, config=config, now=datetime.now())
    except ValueError as e:
        conn.close()
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None
    if errors:
        typer.echo(f"Edited msg#{message_id}: still fails validation, stays PENDING_APPROVAL:")
        for err in errors:
            typer.echo(f"  - {err}")
    else:
        typer.echo(f"Edited msg#{message_id}: validators pass, approved.")
    conn.close()


@app.command(name="eval")
def eval_cmd() -> None:
    """FR-13: compare pipeline output to fixture _expected values."""
    config = load_config()
    conn = db.connect(config.runtime.db_path)
    card = evaluate.run_evaluation(conn, config)
    evaluate.print_scorecard(card)
    conn.close()
    raise typer.Exit(code=0 if card.passed else 1)


if __name__ == "__main__":
    app()
