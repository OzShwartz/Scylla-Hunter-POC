# Scylla Hunter Report

## Account funnel

| Stage | Count |
|---|---|
| gathered | 9 |
| qualified | 4 |
| suppressed | 2 |
| rejected | 3 |

## Lead funnel

| Stage | Count |
|---|---|
| gathered | 13 |
| qualified | 5 |
| drafted | 5 |
| approved | 5 |
| sent | 5 |
| accepted | 2 |
| emailed | 5 |

## Engagement

- Overall invite accept rate: 40%
- Warm emails sent: 2 · Cold emails sent: 3

| Persona | Invited | Accepted | Accept rate |
|---|---|---|---|
| decision_maker | 3 | 1 | 33% |
| practitioner | 2 | 1 | 50% |

## HITL summary

- Auto-approved: 3 · Routed to human: 7 · Human-approved: 7
- Edited: 1 · Rejected: 0

| Route code | What it means | Count |
|---|---|---|
| `score_band` (Human review: mid score) | Score 60-79 | 4 |
| `score_ok` (Auto-sent) | Score 80+, all checks passed, nothing sensitive | 3 |
| `sensitive_content` (Human review: forced) | Mentions a competitor product, the IBM/DataStax acquisition, or a renewal/contract | 3 |

## Accounts

| Account | Score | Status | Reason |
|---|---|---|---|
| Northwind Payments | 96 | QUALIFIED | Account score 96 >= threshold 60 (evidence=55.7, icp=25, why_now=15) |
| Lumen Logistics | 76 | QUALIFIED | Account score 76 >= threshold 60 (evidence=41.3, icp=20, why_now=15) |
| Orbit Media | 23 | REJECTED | Account score 23 below threshold 60 |
| Kestrel Games | 78 | QUALIFIED | Account score 78 >= threshold 60 (evidence=43.3, icp=20, why_now=15) |
| Pinecrest Analytics | 0 | REJECTED | Gate: no technology evidence |
| Quanta Retail | 0 | SUPPRESSED | Existing ScyllaDB customer domain |
| DataStax | 0 | SUPPRESSED | Competitor domain |
| Brightwave AI | 61 | QUALIFIED | Account score 61 >= threshold 60 (evidence=30.9, icp=15, why_now=15) |
| Sprocket Labs | 0 | REJECTED | Gate: 12 employees, below ICP min_employees=100 |

## How the account score works

- Evidence: top-2 signals, recency decay, confidence - max 60
- ICP: company size band + industry bonus - max 25
- Why now: 15 when a recent signal shows intent
- Total max 100 · qualify at 60+ · auto-approve at 80+ (see PRD §9)

## Leads

| Lead | Title | LinkedIn | Company | Persona | Status | Reason |
|---|---|---|---|---|---|---|
| Maya Rosen | VP Engineering | https://linkedin.example/in/maya-rosen | Northwind Payments | decision_maker | EMAILED | warm email dispatched (dry-run) |
| Tom Hale | Staff SRE | https://linkedin.example/in/tom-hale | Northwind Payments | practitioner | EMAILED | cold email dispatched (dry-run) |
| Ana Costa | Senior Data Engineer | https://linkedin.example/in/ana-costa | Northwind Payments | practitioner | DEPRIORITIZED | Qualified but rank 3 exceeds the remaining cap (2/2 slots open - 0 already contacted) |
| Ruth Green | HR Director | https://linkedin.example/in/ruth-green | Northwind Payments | - | REJECTED | Gate: excluded department (HR) |
| Joris de Vries | Head of Platform | https://linkedin.example/in/joris-devries | Lumen Logistics | decision_maker | EMAILED | cold email dispatched (dry-run) |
| Rita Okafor | SRE | https://linkedin.example/in/rita-okafor | Lumen Logistics | - | SUPPRESSED | Email is on the opt-out list |
| Jason Park | Director of Engineering | https://linkedin.example/in/jason-park | Orbit Media | - | REJECTED | Account not qualified: Account score 23 below threshold 60 |
| Lior Ben-David | Principal Engineer | https://linkedin.example/in/lior-ben-david | Kestrel Games | practitioner | EMAILED | warm email dispatched (dry-run) |
| Cassandra Lee | Head of Data | https://linkedin.example/in/cassandra-lee | Pinecrest Analytics | - | REJECTED | Account not qualified: Gate: no technology evidence |
| Felix Braun | VP Engineering | https://linkedin.example/in/felix-braun | Quanta Retail | - | SUPPRESSED | Account suppressed: Existing ScyllaDB customer domain |
| Priya Nair | Solutions Architect | https://linkedin.example/in/priya-nair | DataStax | - | SUPPRESSED | Account suppressed: Competitor domain |
| Dana Weiss | Head of Infrastructure | https://linkedin.example/in/dana-weiss | Brightwave AI | decision_maker | EMAILED | cold email dispatched (dry-run) |
| Nuno Alves | CTO | https://linkedin.example/in/nuno-alves | Sprocket Labs | - | REJECTED | Account not qualified: Gate: 12 employees, below ICP min_employees=100 |

## Sent messages

### msg#1 - Maya Rosen @ Northwind Payments (linkedin/invite, route=auto)

| Evidence | Type | Source | Date |
|---|---|---|---|
| s01 | customer_reference | https://competitor.example/customers/northwind-payments | 2025-11-12 |

### msg#2 - Tom Hale @ Northwind Payments (linkedin/invite, route=auto)

| Evidence | Type | Source | Date |
|---|---|---|---|
| s02 | job_post | https://jobs.example/northwind/staff-sre-data | 2026-09-20 |

### msg#3 - Joris de Vries @ Lumen Logistics (linkedin/invite, route=human)

| Evidence | Type | Source | Date |
|---|---|---|---|
| s03 | job_post | https://jobs.example/lumen/platform-engineer | 2026-08-05 |

### msg#4 - Lior Ben-David @ Kestrel Games (linkedin/invite, route=human)

| Evidence | Type | Source | Date |
|---|---|---|---|
| s06 | conference_talk | https://conf.example/2026/talks/kestrel-leaderboards | 2026-05-14 |

### msg#5 - Dana Weiss @ Brightwave AI (linkedin/invite, route=human)

| Evidence | Type | Source | Date |
|---|---|---|---|
| champ_p12_a01 | champion_move | https://competitor.example/customers/northwind-payments | 2026-07-01 |

### msg#6 - Maya Rosen @ Northwind Payments (email/warm, route=human)

| Evidence | Type | Source | Date |
|---|---|---|---|
| s01 | customer_reference | https://competitor.example/customers/northwind-payments | 2025-11-12 |

### msg#7 - Lior Ben-David @ Kestrel Games (email/warm, route=human)

| Evidence | Type | Source | Date |
|---|---|---|---|
| s06 | conference_talk | https://conf.example/2026/talks/kestrel-leaderboards | 2026-05-14 |

### msg#8 - Tom Hale @ Northwind Payments (email/cold, route=auto)

| Evidence | Type | Source | Date |
|---|---|---|---|
| s02 | job_post | https://jobs.example/northwind/staff-sre-data | 2026-09-20 |

### msg#9 - Joris de Vries @ Lumen Logistics (email/cold, route=human)

| Evidence | Type | Source | Date |
|---|---|---|---|
| s03 | job_post | https://jobs.example/lumen/platform-engineer | 2026-08-05 |

### msg#10 - Dana Weiss @ Brightwave AI (email/cold, route=human)

| Evidence | Type | Source | Date |
|---|---|---|---|
| champ_p12_a01 | champion_move | https://competitor.example/customers/northwind-payments | 2026-07-01 |

## Sequence timeline

| Lead | Invite sent | Accepted | Next action | Due | Days remaining | Status |
|---|---|---|---|---|---|---|
| Maya Rosen | 2026-10-08 | 2026-10-10 | Done (warm email) | 2026-10-10 | 0 | Sent on 2026-10-10 |
| Tom Hale | 2026-10-08 | - | Done (cold email) | 2026-10-15 | 0 | Sent on 2026-10-15 |
| Joris de Vries | 2026-10-08 | - | Done (cold email) | 2026-10-15 | 0 | Sent on 2026-10-15 |
| Lior Ben-David | 2026-10-08 | 2026-10-12 | Done (warm email) | 2026-10-12 | 0 | Sent on 2026-10-12 |
| Dana Weiss | 2026-10-08 | - | Done (cold email) | 2026-10-15 | 0 | Sent on 2026-10-15 |

## Run metadata

- Runs: 2
- LLM calls: 20 (25666 in / 6887 out tokens)
- Prompt cache: 0 tokens read from cache, 0 tokens written to cache (live mode only - 0/0 in replay mode)
- Models: claude-haiku-5-5, claude-opus-5-5
- Prompt versions: extract_signals.v4, personalize.v9
