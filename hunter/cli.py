"""Typer CLI: reset, run, review, approve, reject, edit, event, simulate, report, eval, serve."""

from __future__ import annotations

from datetime import datetime

import typer
from dotenv import load_dotenv

from hunter import db, evaluate, scoring, sources
from hunter import extract as extract_mod
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

    db.update_run_counts(
        conn, run_id,
        models={"extraction": config.llm.models.extraction},
        prompt_versions={"extract_signals": extract_mod.load_prompt_spec(extract_mod.PROMPT_PATH).version},
        llm_calls=stats.llm_calls, tokens_in=stats.tokens_in, tokens_out=stats.tokens_out,
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

    conn.close()


@app.command(name="eval")
def eval_cmd() -> None:
    """FR-13: compare pipeline output to fixture _expected values."""
    config = load_config()
    conn = db.connect(config.runtime.db_path)
    card = evaluate.run_evaluation(conn)
    evaluate.print_scorecard(card)
    conn.close()
    raise typer.Exit(code=0 if card.passed else 1)


if __name__ == "__main__":
    app()
