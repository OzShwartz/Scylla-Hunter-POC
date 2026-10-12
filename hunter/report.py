"""Build report.md and report.html from the database (PRD FR-10).

Deterministic and LLM-free: every number here is a direct read of the six
tables (§13), never a re-derivation that could drift from what `hunter eval`
or the CLI already printed.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from hunter import db, hitl, sources
from hunter.models import Config

ACCOUNT_FUNNEL_STAGES = ["gathered", "qualified", "suppressed", "rejected"]
FUNNEL_STAGES = ["gathered", "qualified", "drafted", "approved", "sent", "accepted", "emailed"]
PERSONAS = ["decision_maker", "practitioner"]

# A lead that reached this far in the lifecycle was, at some point, correctly
# selected - QUALIFIED is not the only "qualified" state once triggers advance
# a lead past it (see scoring.ADVANCED_LEAD_STATUSES / evaluate.STATUS_MAP for
# the same reasoning applied elsewhere).
QUALIFIED_OR_LATER = {"QUALIFIED", "INVITED", "ACCEPTED", "EMAILED"}


@dataclass
class ReportData:
    account_funnel: dict[str, int]
    funnel: dict[str, int]
    engagement: dict
    hitl_summary: dict
    accounts: list[sqlite3.Row]
    leads: list[sqlite3.Row]
    sent_messages: list[dict]
    live_accounts: list[dict]
    run_meta: dict
    lead_cards: list[dict]
    score_legend: dict
    route_code_info: dict
    sequence_timeline: list[dict]


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0%}"


def compute_account_funnel(conn: sqlite3.Connection) -> dict[str, int]:
    """Discovery starts at the account (PRD §9.1) - this is the funnel one
    level up from compute_funnel's lead-level one."""
    accounts = db.list_accounts(conn)
    return {
        "gathered": len(accounts),
        "qualified": sum(1 for a in accounts if a["status"] == "QUALIFIED"),
        "suppressed": sum(1 for a in accounts if a["status"] == "SUPPRESSED"),
        "rejected": sum(1 for a in accounts if a["status"] == "REJECTED"),
    }


def compute_funnel(conn: sqlite3.Connection) -> dict[str, int]:
    leads = db.list_leads(conn)
    messages = db.list_messages(conn)
    events = db.list_events(conn)

    invite_messages = [m for m in messages if m["variant"] == "invite"]
    email_messages = [m for m in messages if m["variant"] in ("warm", "cold")]

    return {
        "gathered": len(leads),
        "qualified": sum(1 for lead in leads if lead["status"] in QUALIFIED_OR_LATER),
        "drafted": len({m["lead_id"] for m in invite_messages}),
        "approved": len({m["lead_id"] for m in invite_messages if m["status"] in ("APPROVED", "SENT")}),
        "sent": len({m["lead_id"] for m in invite_messages if m["status"] == "SENT"}),
        "accepted": len({e["lead_id"] for e in events if e["type"] == "connection_accepted"}),
        "emailed": len({m["lead_id"] for m in email_messages if m["status"] == "SENT"}),
    }


def compute_engagement(conn: sqlite3.Connection) -> dict:
    leads_by_id = {lead["id"]: lead for lead in db.list_leads(conn)}
    messages = db.list_messages(conn)
    accepted_lead_ids = {e["lead_id"] for e in db.list_events(conn) if e["type"] == "connection_accepted"}
    invited_lead_ids = {m["lead_id"] for m in messages if m["variant"] == "invite" and m["status"] == "SENT"}

    by_persona = {}
    for persona in PERSONAS:
        persona_invited = {lid for lid in invited_lead_ids if leads_by_id[lid]["persona"] == persona}
        persona_accepted = persona_invited & accepted_lead_ids
        by_persona[persona] = {
            "invited": len(persona_invited),
            "accepted": len(persona_accepted),
            "accept_rate": (len(persona_accepted) / len(persona_invited)) if persona_invited else None,
        }

    overall_accepted = invited_lead_ids & accepted_lead_ids
    return {
        "overall_accept_rate": (len(overall_accepted) / len(invited_lead_ids)) if invited_lead_ids else None,
        "by_persona": by_persona,
        "warm_sent": sum(1 for m in messages if m["variant"] == "warm" and m["status"] == "SENT"),
        "cold_sent": sum(1 for m in messages if m["variant"] == "cold" and m["status"] == "SENT"),
    }


def compute_hitl_summary(conn: sqlite3.Connection, config: Config) -> dict:
    by_route: dict[str, int] = {}
    by_code: dict[str, int] = {}
    edits = 0
    rejections = 0
    for m in db.list_messages(conn):
        by_route[m["approval_route"]] = by_route.get(m["approval_route"], 0) + 1
        lead = db.get_lead(conn, m["lead_id"])
        account = db.get_account(conn, lead["account_id"])
        _, _, _, code = hitl.route_info(conn, m, account, config)
        by_code[code] = by_code.get(code, 0) + 1
        if m["original_body"]:
            edits += 1
        if m["status"] == "REJECTED":
            rejections += 1
    return {"by_route": by_route, "by_code": by_code, "edits": edits, "rejections": rejections}


def sent_messages_detail(conn: sqlite3.Connection) -> list[dict]:
    out = []
    for m in db.list_messages(conn, status="SENT"):
        lead = db.get_lead(conn, m["lead_id"])
        account = db.get_account(conn, lead["account_id"])
        evidence = []
        for eid in json.loads(m["evidence_ids"]):
            sig = db.get_signal(conn, eid)
            if sig is not None:
                evidence.append(
                    {"id": sig["id"], "type": sig["type"], "source_url": sig["source_url"], "published_at": sig["published_at"]}
                )
        out.append(
            {
                "message_id": m["id"],
                "lead": f"{lead['first_name']} {lead['last_name']}",
                "account": account["name"],
                "channel": m["channel"],
                "variant": m["variant"],
                "approval_route": m["approval_route"],
                "evidence": evidence,
            }
        )
    return out


def run_metadata(conn: sqlite3.Connection) -> dict:
    runs = db.list_runs(conn)
    models: set[str] = set()
    prompt_versions: set[str] = set()
    for r in runs:
        models.update(json.loads(r["models"] or "{}").values())
        prompt_versions.update(json.loads(r["prompt_versions"] or "{}").values())
    return {
        "runs": len(runs),
        "llm_calls": sum(r["llm_calls"] for r in runs),
        "tokens_in": sum(r["tokens_in"] for r in runs),
        "tokens_out": sum(r["tokens_out"] for r in runs),
        "cache_creation_input_tokens": sum(r["cache_creation_input_tokens"] for r in runs),
        "cache_read_input_tokens": sum(r["cache_read_input_tokens"] for r in runs),
        "models": sorted(models),
        "prompt_versions": sorted(prompt_versions),
    }


def live_discovered_accounts(conn: sqlite3.Connection) -> list[dict]:
    """FR-10: accounts found by a live source (FR-2's GitHub search), not the
    fixtures - empty on a fixtures-only run."""
    out = []
    for a in db.list_accounts(conn):
        if a["source"] == "fixtures":
            continue
        query = json.loads(a["people_query"]) if a["people_query"] else None
        target_title_count = (
            len(query["target_titles"]["decision_maker"]) + len(query["target_titles"]["practitioner"])
            if query else 0
        )
        out.append(
            {
                "name": a["name"], "source": a["source"], "status": a["status"],
                "domain": query["company_domain"] if query else a["domain"],
                "target_title_count": target_title_count,
            }
        )
    return out


def build_lead_cards(conn: sqlite3.Connection, config: Config) -> list[dict]:
    """One self-contained card per lead that reached QUALIFIED or later: the
    account's score breakdown plus every message drafted for this lead, each
    with its route/reason (hitl.route_info, the same function `review` uses)
    and cited evidence - report.html's per-lead section needs no further DB
    reads at render time. Additive only: report.md's own fields are untouched."""
    cards = []
    for lead in db.list_leads(conn):
        if lead["status"] not in QUALIFIED_OR_LATER:
            continue
        account = db.get_account(conn, lead["account_id"])
        messages = []
        for m in db.list_messages_for_lead(conn, lead["id"]):
            _, _, reason, code = hitl.route_info(conn, m, account, config)
            evidence = []
            for eid in json.loads(m["evidence_ids"]):
                sig = db.get_signal(conn, eid)
                if sig is not None:
                    evidence.append(
                        {
                            "id": sig["id"], "type": sig["type"], "source_url": sig["source_url"],
                            "published_at": sig["published_at"], "confidence": sig["confidence"],
                            "evidence_quote": sig["evidence_quote"],
                        }
                    )
            messages.append(
                {
                    "id": m["id"], "channel": m["channel"], "variant": m["variant"],
                    "subject": m["subject"], "body": m["body"], "status": m["status"],
                    "approval_route": m["approval_route"], "route_reason": reason, "route_code": code,
                    "evidence": evidence,
                }
            )
        cards.append({"lead": lead, "account": account, "messages": messages})
    return cards


def build_score_legend(config: Config) -> dict:
    """Every number here is read from config.yaml, never hardcoded (PRD §9) -
    so a reviewer changing a weight sees the legend change with it."""
    icp_max = max(b.points for b in config.icp.employee_bands) + config.icp.industry_bonus
    evidence_max = config.signals.max_evidence_points
    why_now_max = config.signals.why_now.bonus
    return {
        "evidence_max": evidence_max,
        "icp_max": icp_max,
        "why_now_max": why_now_max,
        "total_max": evidence_max + icp_max + why_now_max,
        "qualify_threshold": config.scoring.account_threshold,
        "auto_threshold": config.hitl.auto_send_min_account_score,
    }


def build_route_code_info(config: Config) -> dict:
    """Human-readable label + explanation for every hitl.py route code, with
    the live config thresholds interpolated in - never a hardcoded number."""
    qualify = config.scoring.account_threshold
    auto = config.hitl.auto_send_min_account_score
    return {
        hitl.AUTO_SCORE_OK: {
            "label": "Auto-sent",
            "description": f"Score {auto}+, all checks passed, nothing sensitive",
        },
        hitl.SCORE_BAND: {
            "label": "Human review: mid score",
            "description": f"Score {qualify}-{auto - 1}",
        },
        hitl.SENSITIVE_CONTENT: {
            "label": "Human review: forced",
            "description": "Mentions a competitor product, the IBM/DataStax acquisition, or a renewal/contract",
        },
        hitl.NO_HIGH_CONFIDENCE_EVIDENCE: {
            "label": "Human review: forced",
            "description": "No high-confidence evidence item cited",
        },
        hitl.VALIDATOR_FAILED: {
            "label": "Human review: forced",
            "description": "Failed content validation after one retry",
        },
        hitl.APPROVAL_MODE_ALL: {
            "label": "Human review: policy",
            "description": "approval_mode=all - every draft requires review regardless of score",
        },
        hitl.AUTO_MODE_OFF: {
            "label": "Auto-sent: policy",
            "description": "approval_mode=off - auto-approved (testing only)",
        },
    }


def build_sequence_timeline(conn: sqlite3.Connection, config: Config) -> list[dict]:
    """PRD §12: the trigger sequence made visible, one row per lead that has
    actually been contacted (a SENT invite exists) - meaningful mid-run too,
    right after `hunter run` and before `hunter simulate` has touched anyone.

    Dates are as_of + a simulated day offset, never wall-clock: R1 always
    fires on day 0; a scripted acceptance day comes from fixtures (the same
    source triggers.simulate reads); R3's day comes from config.sequence. A
    lead with no warm/cold message yet hasn't had any time simulated for it,
    so its reference day is 0 and it's showing the full countdown to R3.
    """
    r3_days = next(r.days for r in config.sequence if r.id == "R3")
    # The scripted day a lead is *planned* to accept (fixtures) is only a real
    # date once that event has actually been processed (db.events) - showing
    # the planned day regardless would make a mid-run snapshot (before
    # `simulate` has run) falsely claim leads already accepted.
    actually_accepted = {e["lead_id"] for e in db.list_events(conn) if e["type"] == "connection_accepted"}
    scripted_day_by_lead = {
        e.lead_id: e.day
        for e in sources.load_fixtures().simulated_events
        if e.event == "connection_accepted" and e.day is not None
    }
    accepted_day_by_lead = {
        lead_id: day for lead_id, day in scripted_day_by_lead.items() if lead_id in actually_accepted
    }

    rows = []
    for lead in db.list_leads(conn):
        messages = db.list_messages_for_lead(conn, lead["id"])
        invite = next((m for m in messages if m["variant"] == "invite" and m["status"] == "SENT"), None)
        if invite is None:
            continue
        warm = next((m for m in messages if m["variant"] == "warm"), None)
        cold = next((m for m in messages if m["variant"] == "cold"), None)
        accepted_day = accepted_day_by_lead.get(lead["id"])

        if warm is not None:
            due_day = accepted_day if accepted_day is not None else 0
            sent = warm["status"] == "SENT"
            next_action = "Done (warm email)" if sent else "Warm email (awaiting approval)"
            status_label = f"Sent on {config.as_of + timedelta(days=due_day)}" if sent else "Pending approval"
            days_remaining = 0
        elif cold is not None:
            due_day = r3_days
            sent = cold["status"] == "SENT"
            next_action = "Done (cold email)" if sent else "Cold email (awaiting approval)"
            status_label = f"Sent on {config.as_of + timedelta(days=due_day)}" if sent else "Pending approval"
            days_remaining = 0
        else:
            due_day = r3_days
            next_action = f"Cold email due at day {r3_days}"
            status_label = "Pending"
            days_remaining = r3_days

        rows.append(
            {
                "lead": lead,
                "invite_sent": config.as_of,
                "accepted": (config.as_of + timedelta(days=accepted_day)) if accepted_day is not None else None,
                "next_action": next_action,
                "due_date": config.as_of + timedelta(days=due_day),
                "days_remaining": days_remaining,
                "status_label": status_label,
            }
        )
    return rows


def build_report(conn: sqlite3.Connection, config: Config) -> ReportData:
    return ReportData(
        account_funnel=compute_account_funnel(conn),
        funnel=compute_funnel(conn),
        engagement=compute_engagement(conn),
        hitl_summary=compute_hitl_summary(conn, config),
        accounts=db.list_accounts(conn),
        leads=db.list_leads(conn),
        sent_messages=sent_messages_detail(conn),
        live_accounts=live_discovered_accounts(conn),
        run_meta=run_metadata(conn),
        lead_cards=build_lead_cards(conn, config),
        score_legend=build_score_legend(config),
        route_code_info=build_route_code_info(config),
        sequence_timeline=build_sequence_timeline(conn, config),
    )


def render_markdown(data: ReportData) -> str:
    accounts_by_id = {a["id"]: a for a in data.accounts}
    lines = ["# Scylla Hunter Report", "", "## Account funnel", "", "| Stage | Count |", "|---|---|"]
    for stage in ACCOUNT_FUNNEL_STAGES:
        lines.append(f"| {stage} | {data.account_funnel[stage]} |")

    lines += ["", "## Lead funnel", "", "| Stage | Count |", "|---|---|"]
    for stage in FUNNEL_STAGES:
        lines.append(f"| {stage} | {data.funnel[stage]} |")

    lines += ["", "## Engagement", ""]
    lines.append(f"- Overall invite accept rate: {_pct(data.engagement['overall_accept_rate'])}")
    lines.append(f"- Warm emails sent: {data.engagement['warm_sent']} · Cold emails sent: {data.engagement['cold_sent']}")
    lines += ["", "| Persona | Invited | Accepted | Accept rate |", "|---|---|---|---|"]
    for persona in PERSONAS:
        stats = data.engagement["by_persona"][persona]
        lines.append(f"| {persona} | {stats['invited']} | {stats['accepted']} | {_pct(stats['accept_rate'])} |")

    lines += ["", "## HITL summary", ""]
    lines.append(
        f"- Auto-approved: {data.hitl_summary['by_route'].get('auto', 0)} · "
        f"Human-approved: {data.hitl_summary['by_route'].get('human', 0)}"
    )
    lines.append(f"- Edited: {data.hitl_summary['edits']} · Rejected: {data.hitl_summary['rejections']}")
    lines += ["", "| Route code | What it means | Count |", "|---|---|---|"]
    for code, count in sorted(data.hitl_summary["by_code"].items()):
        info = data.route_code_info.get(code, {"label": code, "description": ""})
        lines.append(f"| `{code}` ({info['label']}) | {info['description']} | {count} |")

    lines += ["", "## Accounts", "", "| Account | Score | Status | Reason |", "|---|---|---|---|"]
    for a in data.accounts:
        lines.append(f"| {a['name']} | {a['account_score']} | {a['status']} | {a['reason']} |")

    if data.live_accounts:
        lines += ["", "## Live discovered accounts", "", "| Account | Source | Status | People query |", "|---|---|---|---|"]
        for a in data.live_accounts:
            lines.append(f"| {a['name']} | {a['source']} | {a['status']} | `{a['domain']}`, {a['target_title_count']} target titles |")

    legend = data.score_legend
    lines += ["", "## How the account score works", ""]
    lines.append(f"- Evidence: top-2 signals, recency decay, confidence - max {legend['evidence_max']:.0f}")
    lines.append(f"- ICP: company size band + industry bonus - max {legend['icp_max']}")
    lines.append(f"- Why now: {legend['why_now_max']} when a recent signal shows intent")
    lines.append(
        f"- Total max {legend['total_max']:.0f} · qualify at {legend['qualify_threshold']}+ · "
        f"auto-approve at {legend['auto_threshold']}+ (see PRD §9)"
    )

    lines += ["", "## Leads", "", "| Lead | Title | LinkedIn | Company | Persona | Status | Reason |", "|---|---|---|---|---|---|---|"]
    for lead in data.leads:
        account = accounts_by_id.get(lead["account_id"])
        company = account["name"] if account is not None else lead["account_id"]
        linkedin = lead["linkedin_url"] or "-"
        lines.append(
            f"| {lead['first_name']} {lead['last_name']} | {lead['title'] or '-'} | {linkedin} | {company} | "
            f"{lead['persona'] or '-'} | {lead['status']} | {lead['reason']} |"
        )

    lines += ["", "## Sent messages", ""]
    for m in data.sent_messages:
        lines.append(
            f"### msg#{m['message_id']} - {m['lead']} @ {m['account']} "
            f"({m['channel']}/{m['variant']}, route={m['approval_route']})"
        )
        if m["evidence"]:
            lines += ["", "| Evidence | Type | Source | Date |", "|---|---|---|---|"]
            for e in m["evidence"]:
                lines.append(f"| {e['id']} | {e['type']} | {e['source_url']} | {e['published_at']} |")
        else:
            lines += ["", "(no evidence cited)"]
        lines.append("")

    if data.sequence_timeline:
        lines += [
            "## Sequence timeline", "",
            "| Lead | Invite sent | Accepted | Next action | Due | Days remaining | Status |",
            "|---|---|---|---|---|---|---|",
        ]
        for row in data.sequence_timeline:
            lead = row["lead"]
            accepted = row["accepted"].isoformat() if row["accepted"] else "-"
            lines.append(
                f"| {lead['first_name']} {lead['last_name']} | {row['invite_sent'].isoformat()} | {accepted} | "
                f"{row['next_action']} | {row['due_date'].isoformat()} | {row['days_remaining']} | {row['status_label']} |"
            )
        lines.append("")

    lines += ["## Run metadata", ""]
    lines.append(f"- Runs: {data.run_meta['runs']}")
    lines.append(f"- LLM calls: {data.run_meta['llm_calls']} ({data.run_meta['tokens_in']} in / {data.run_meta['tokens_out']} out tokens)")
    lines.append(
        f"- Prompt cache: {data.run_meta['cache_read_input_tokens']} tokens read from cache, "
        f"{data.run_meta['cache_creation_input_tokens']} tokens written to cache (live mode only - 0/0 in replay mode)"
    )
    lines.append(f"- Models: {', '.join(data.run_meta['models']) or 'none'}")
    lines.append(f"- Prompt versions: {', '.join(data.run_meta['prompt_versions']) or 'none'}")
    lines.append("")

    return "\n".join(lines)


def render_html(data: ReportData) -> str:
    import base64

    from jinja2 import Environment, FileSystemLoader

    templates_dir = Path(__file__).resolve().parent.parent / "templates"
    env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=True)
    template = env.get_template("report.html.j2")
    accounts_by_id = {a["id"]: a for a in data.accounts}
    logo_b64 = base64.b64encode((templates_dir / "scylladb_logo.png").read_bytes()).decode()
    return template.render(
        data=data, accounts_by_id=accounts_by_id, account_funnel_stages=ACCOUNT_FUNNEL_STAGES,
        funnel_stages=FUNNEL_STAGES, personas=PERSONAS, logo_b64=logo_b64,
    )


def write_report(conn: sqlite3.Connection, config: Config, *, html: bool = False) -> ReportData:
    data = build_report(conn, config)

    report_path = Path(config.runtime.report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_markdown(data))

    if html:
        html_path = Path(config.runtime.report_html_path)
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(render_html(data))

    return data
