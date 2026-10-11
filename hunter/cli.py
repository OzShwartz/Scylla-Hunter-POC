"""Typer CLI: reset, run, review, approve, reject, edit, event, simulate, report, eval, serve."""

from __future__ import annotations

import json
import os
from datetime import datetime

import typer
from dotenv import load_dotenv

from hunter import db, dispatch, evaluate, hitl, scoring, sources, triggers
from hunter import extract as extract_mod
from hunter import personalize as personalize_mod
from hunter import report as report_mod
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

    if source not in ("fixtures", "github", "all"):
        typer.echo(f"Unknown --source {source!r}. Supported: fixtures|github|all. Using fixtures.")
        source = "fixtures"

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

    if source in ("github", "all"):
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            typer.echo(
                "--source github: GITHUB_TOKEN is not set in .env - using the committed, dated "
                f"snapshot ({sources.SNAPSHOT_PATH}) instead of a live search (see .env.example / "
                "PRD §5.2, FR-2 to enable live search)."
            )
        try:
            github_account_ids, classified, mode = sources.run_github_source(
                conn, config.github_source, token=token, as_of=config.as_of
            )
            excluded = len(classified) - len(github_account_ids)
            typer.echo(
                f"GitHub source ({mode}): {len(classified)} raw match(es) -> {len(github_account_ids)} probable "
                f"user(s), {excluded} excluded"
                + (f" ({', '.join(github_account_ids)})" if github_account_ids else "")
            )
        except sources.GitHubSourceError as e:
            typer.echo(f"--source github: {e}", err=True)

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

    leads = db.list_leads(conn)
    selected = [lead for lead in leads if lead["status"] == "QUALIFIED"]
    typer.echo(f"\nSelected leads: {len(selected)}/{len(leads)}")
    for lead in selected:
        typer.echo(f"  {lead['id']} {lead['first_name']} {lead['last_name']} ({lead['persona']}, rank {lead['rank']})")

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

    dispatch_stats = dispatch.dispatch_approved(conn, config, run_id=run_id, now=datetime.now())
    if dispatch_stats.sent_message_ids:
        typer.echo(f"\n{len(dispatch_stats.sent_message_ids)} message(s) dispatched (dry-run) - see outbox.jsonl")

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
        _, _, reason, code = hitl.route_info(conn, m, account, config)
        sensitive_tag = "  [SENSITIVE CONTENT - excluded from `approve --all`]" if code == hitl.SENSITIVE_CONTENT else ""
        typer.echo(
            f"\nmsg#{m['id']} | {m['channel']}/{m['variant']} | "
            f"lead={lead['id']} {lead['first_name']} {lead['last_name']} ({lead['persona']}) @ "
            f"{account['name']} (score {account['account_score']}){sensitive_tag}"
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
    approve_all: bool = typer.Option(False, "--all", help="Approve every score-band pending draft"),
    include_sensitive: bool = typer.Option(
        False, "--include-sensitive",
        help="With --all, also approve content-sensitive drafts (competitor/IBM/renewal mentions)",
    ),
) -> None:
    """FR-7: approve one pending draft, or every pending draft with --all.

    --all only bulk-approves drafts pending on account score alone. A draft
    forced to review for a content reason (sensitive content, a validator
    failure, no high-confidence evidence) or by approval_mode=all is skipped -
    run `hunter review` to see why, then approve it individually, or pass
    --include-sensitive to also sweep up the sensitive-content ones.
    """
    config = load_config()
    conn = db.connect(config.runtime.db_path)
    if approve_all:
        approved_ids, skipped = hitl.approve_all(
            conn, config, include_sensitive=include_sensitive, now=datetime.now()
        )
        typer.echo(f"Approved {len(approved_ids)} draft(s).")
        for message, reason in skipped:
            typer.echo(f"  Skipped msg#{message['id']}: {reason} - approve individually with `hunter approve {message['id']}`")
        dispatch.dispatch_approved(conn, config, run_id=None, now=datetime.now())
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
    dispatch.dispatch_approved(conn, config, run_id=None, now=datetime.now())
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
        dispatch.dispatch_approved(conn, config, run_id=None, now=datetime.now())
    conn.close()


@app.command()
def event(
    event_type: str = typer.Argument(..., help="Only 'connection-accepted' is supported (PRD §12.2)"),
    lead: str = typer.Option(..., "--lead", help="Lead id"),
    llm: str = typer.Option(None, "--llm", help="replay|live (overrides config.yaml's llm.mode)"),
) -> None:
    """FR-8: inject an external event (the PoC's CLI event source, PRD §12.2). R2."""
    if event_type != "connection-accepted":
        typer.echo(f"Unknown event type {event_type!r}. Supported: connection-accepted", err=True)
        raise typer.Exit(code=1)

    config = load_config()
    llm_mode = llm or config.llm.mode
    conn = db.connect(config.runtime.db_path)
    run_id = db.insert_run(conn, command="event", llm_mode=llm_mode, started_at=datetime.now())
    stats = triggers.TriggerStats()
    try:
        message_id = triggers.handle_connection_accepted(
            conn, config, lead, llm_mode=llm_mode, run_id=run_id, now=datetime.now(), stats=stats
        )
    except ReplayMissError as e:
        conn.close()
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    if message_id is None:
        typer.echo(f"No-op: lead {lead} is not currently INVITED (already accepted, already emailed, or never invited).")
        conn.close()
        return

    typer.echo(f"Lead {lead} -> ACCEPTED. Warm email drafted as msg#{message_id}.")
    if stats.forced_review:
        typer.echo(f"Forced to review (validator failure after retry): {stats.forced_review}")
    db.update_run_counts(conn, run_id, llm_calls=stats.llm_calls, tokens_in=stats.tokens_in, tokens_out=stats.tokens_out)
    dispatch.dispatch_approved(conn, config, run_id=run_id, now=datetime.now())
    conn.close()


@app.command()
def simulate(
    days: int = typer.Option(..., "--days", help="Advance the simulated clock to N days after each invite was sent"),
    llm: str = typer.Option(None, "--llm", help="replay|live (overrides config.yaml's llm.mode)"),
) -> None:
    """PRD §12.2/§12.3: replay fixtures.simulated_events up to --days, then
    fire R3's cold email for anyone still INVITED once the day threshold is reached."""
    config = load_config()
    llm_mode = llm or config.llm.mode
    fixtures = sources.load_fixtures()

    conn = db.connect(config.runtime.db_path)
    run_id = db.insert_run(conn, command="simulate", llm_mode=llm_mode, started_at=datetime.now())
    try:
        stats = triggers.simulate(
            conn, config, days=days, llm_mode=llm_mode, run_id=run_id, now=datetime.now(),
            scripted_events=fixtures.simulated_events,
        )
    except ReplayMissError as e:
        conn.close()
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1) from None

    typer.echo(f"Simulated to day {days}.")
    if stats.warm_drafted:
        typer.echo(f"Warm emails drafted (connection accepted): {', '.join(stats.warm_drafted)}")
    if stats.cold_drafted:
        typer.echo(f"Cold emails drafted (no accept by day {days}): {', '.join(stats.cold_drafted)}")
    if stats.forced_review:
        typer.echo(f"Forced to review (validator failure after retry): {stats.forced_review}")

    db.update_run_counts(conn, run_id, llm_calls=stats.llm_calls, tokens_in=stats.tokens_in, tokens_out=stats.tokens_out)
    dispatch_stats = dispatch.dispatch_approved(conn, config, run_id=run_id, now=datetime.now())
    if dispatch_stats.sent_message_ids:
        typer.echo(f"\n{len(dispatch_stats.sent_message_ids)} message(s) dispatched (dry-run) - see outbox.jsonl")
    conn.close()


@app.command(name="report")
def report_cmd(
    html: bool = typer.Option(False, "--html", help="Also write the HTML report"),
) -> None:
    """FR-10: write report.md (and, with --html, report.html) from the database."""
    config = load_config()
    conn = db.connect(config.runtime.db_path)
    report_mod.write_report(conn, config, html=html)
    typer.echo(f"Wrote {config.runtime.report_path}")
    if html:
        typer.echo(f"Wrote {config.runtime.report_html_path}")
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
