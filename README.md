# Scylla Hunter

A small, runnable PoC for an AI-driven competitor-displacement hunter: it finds people at companies that show evidence of running DataStax or Apache Cassandra, qualifies them with a deterministic score, drafts a LinkedIn invite and follow-up email with an LLM, runs the trigger/approval logic in dry-run, and reports what happened. No real sending, no LinkedIn scraping, no API key required to run it.

Full spec: **[PRD.md](PRD.md)**. Build log: **[AI_WORKFLOW.md](AI_WORKFLOW.md)**.

## Quickstart (no keys, ~2 minutes)

```bash
git clone <this-repo> && cd scylla-hunter
pip install -r requirements.txt
python -m hunter reset
python -m hunter run                 # 5 qualified leads; 2 invites auto-sent, 3 pending
python -m hunter review              # see pending drafts with evidence and routing reason
python -m hunter approve --all       # approves the score-band ones; skips anything content-sensitive
python -m hunter simulate --days 7   # 2 accept -> warm email; 3 don't -> cold email
python -m hunter review              # several of these are tagged [SENSITIVE CONTENT]
python -m hunter approve --all       # skips the flagged ones again, with their ids
python -m hunter approve <msg_id>    # read each flagged one, then approve individually
python -m hunter report --html       # examples/report.md and examples/report.html
```

Everything runs against a committed **replay set** (`data/llm_replay/`) - real Claude responses recorded once, replayed deterministically. `--llm live` plus `ANTHROPIC_API_KEY` in `.env` re-records them; the reviewer never needs a key.

## The problem, and how I read it

ScyllaDB is CQL/Cassandra-compatible, so a team running DataStax or Cassandra can switch with the lowest rewrite cost of any competitor's customer base. IBM completed its acquisition of DataStax in May 2025 - a classic moment for a buyer to re-evaluate options, which the project treats as a *neutral* trigger, never fear-based messaging (enforced in code, not just asked for in the prompt - see §9.6 and `validators.is_sensitive_content`).

"Users of DataStax" is read as *people at companies with evidence of running DataStax products or self-managed Apache Cassandra* - not DataStax employees (suppressed), and self-managed Cassandra counts because the same compatibility argument applies. Discovery is **account-first**: evidence qualifies a company, then the right people are chosen inside it, ending in a LinkedIn profile URL per lead - never a raw LinkedIn search or scrape. Full reasoning, assumptions, and the questions this would need answered from a real hiring manager: **[PRD.md §3](PRD.md#3-discovery-business-context-and-why-now), [§21](PRD.md#21-assumptions-and-open-questions)**.

## Architecture

![Infrastructure](docs/diagrams/infra_poc.png)

**Code decides what happens. The LLM decides only how it's worded. n8n (production) decides when.** Qualification, scoring, routing and triggers are deterministic Python - testable, explainable, free to re-run. The LLM is called in exactly two places (`hunter/extract.py`, `hunter/personalize.py`), both through `hunter/llm.py`. More diagrams (DFD, ERD, lifecycles) in `docs/diagrams/` and PRD §14.

## One lead, end to end: Maya Rosen

Real output from `examples/run_log.txt` - nothing in this section is invented.

1. **Evidence.** `s01`, a customer-reference page, high confidence: *"Northwind Payments runs fraud scoring on Astra DB."*
2. **Score breakdown.** `evidence=55.7, icp=25, why_now=15` → **account score 96** (≥ 80 auto-approve threshold).
3. **Invite** (auto-approved, sent): *"Hi Maya, I'm Oz, GTM Engineer at ScyllaDB. I saw that Northwind Payments runs fraud scoring across multiple regions at 40k transactions per second, with tight read-latency requirements. I'd be glad to connect."*
4. **Accepted event** (`hunter simulate --days 7`, scripted day 2): lead status `INVITED` → `ACCEPTED`.
5. **Warm email drafted:** opens "Hi Maya, thanks for connecting," cites the same evidence, adds one value prop, and - because the account's own evidence is Astra DB usage - mentions the IBM/DataStax acquisition as one clause after the main argument, never the opener.
6. **Route: forced to human review.** Score alone (96) would auto-approve. The draft's content - a competitor product name and the acquisition - overrides that unconditionally (`hitl.determine_route`, code `sensitive_content`). This is the project's central finding: **account score measures lead quality, not message risk**, and the two are independent. `hunter review` tags it `[SENSITIVE CONTENT]`; `approve --all` skips it; a human reads it and approves (or doesn't) individually.

## Key decisions

| Decision | Why |
|---|---|
| Account-first discovery, ending in a LinkedIn profile URL | Answers "identify users on LinkedIn" without scraping or automating LinkedIn, which breaches its ToS (Proxycurl's shutdown, Jan 2025, is the cautionary case) |
| Deterministic scoring, selection, routing and triggers | Explainable and testable; an SDR or GTM lead can audit *why*, not just *what* |
| Grounding enforced in code, not just prompted | A model will still occasionally mislabel a quote or restate a fact loosely - verbatim-substring checks and evidence-existence checks catch what a prompt instruction alone doesn't |
| Content-sensitive HITL override | Found empirically (Phase 2): the highest-scoring account produced the most commercially sensitive draft and auto-sent anyway - score and risk are orthogonal, so routing now checks both |
| Replay mode as the default | The reviewer runs the whole thing in minutes, with no key, deterministically - see `hunter/llm.py` |
| No LinkedIn scraping or automation, anywhere | Legal/ToS risk is real and recent; invites are "sent" only to console + `outbox.jsonl` |

## What I deliberately left out, and why

- **Real sending, any channel.** `dry_run: true` always; FR-9's acceptance criterion is literally "no network call to any channel exists in the code path" (verified by grep, not just by convention).
- **LinkedIn automation or scraping.** Out of scope on legal grounds, not a time constraint.
- **Live Apollo/people-API calls.** The exact request is generated and logged (`people_query` in the account record); nothing is actually sent.
- **CRM sync, a UI beyond the report, reply classification, A/B testing.** All production-roadmap items (§20) that need real outcome data this PoC has no way to generate.
- **`hunter serve` / n8n webhook endpoints (FR-12).** Documented as the production trigger layer (§14.5); not built, since the CLI + simulated clock already exercise the same rule logic.

## Path to production

| Concern | PoC | Production |
|---|---|---|
| Triggers and time | CLI + simulated clock | n8n schedules and webhooks |
| System of record | SQLite | Salesforce; Postgres for evidence/audit |
| Sending | Dry-run to console + outbox | Human-approved; LinkedIn always manual |
| Sources | Fixtures + GitHub (opt-in) | Real sources behind the same input shape |
| Decision logic | Python core | Same Python core, unchanged |

Full version: **[PRD.md §14.5](PRD.md#145-infrastructure)**, **[§20](PRD.md#20-out-of-scope-and-production-roadmap)**.

## GitHub live source (FR-2)

> **Placeholder - filling this in Monday.** `--source github` with a `GITHUB_TOKEN` runs real code-search queries and maps matching repos to accounts (§5.2, FR-2); this section will show real discovered-account output once that pass is done.

## How this was built

Built with [Claude Code](https://claude.com/claude-code) in VS Code. `CLAUDE.md` holds the project's non-negotiable rules (dry-run by default, grounding in code, secrets handling, replay-first). `.claude/skills/` holds three repeatable workflows: `run-eval`, `record-replay`, `pre-submit`. The full build log - every significant prompt, every mistake caught and how, every human decision - is in **[AI_WORKFLOW.md](AI_WORKFLOW.md)**, including a "Highlights" table of the specific cases where human review caught something the automated checks missed.
