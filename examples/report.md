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

- Auto-approved: 3 · Human-approved: 7
- Edited: 1 · Rejected: 0

| Route code | Count |
|---|---|
| score_band | 4 |
| score_ok | 3 |
| sensitive_content | 3 |

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

## Leads

| Lead | Company | Persona | Status | Reason |
|---|---|---|---|---|
| Maya Rosen | Northwind Payments | decision_maker | EMAILED | warm email dispatched (dry-run) |
| Tom Hale | Northwind Payments | practitioner | EMAILED | cold email dispatched (dry-run) |
| Ana Costa | Northwind Payments | practitioner | DEPRIORITIZED | Qualified but rank 3 exceeds the remaining cap (2/2 slots open - 0 already contacted) |
| Ruth Green | Northwind Payments | - | REJECTED | Gate: excluded department (HR) |
| Joris de Vries | Lumen Logistics | decision_maker | EMAILED | cold email dispatched (dry-run) |
| Rita Okafor | Lumen Logistics | - | SUPPRESSED | Email is on the opt-out list |
| Jason Park | Orbit Media | - | REJECTED | Account not qualified: Account score 23 below threshold 60 |
| Lior Ben-David | Kestrel Games | practitioner | EMAILED | warm email dispatched (dry-run) |
| Cassandra Lee | Pinecrest Analytics | - | REJECTED | Account not qualified: Gate: no technology evidence |
| Felix Braun | Quanta Retail | - | SUPPRESSED | Account suppressed: Existing ScyllaDB customer domain |
| Priya Nair | DataStax | - | SUPPRESSED | Account suppressed: Competitor domain |
| Dana Weiss | Brightwave AI | decision_maker | EMAILED | cold email dispatched (dry-run) |
| Nuno Alves | Sprocket Labs | - | REJECTED | Account not qualified: Gate: 12 employees, below ICP min_employees=100 |

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

## Run metadata

- Runs: 2
- LLM calls: 20 (25666 in / 6887 out tokens)
- Prompt cache: 0 tokens read from cache, 0 tokens written to cache (live mode only - 0/0 in replay mode)
- Models: claude-haiku-5-5, claude-opus-5-5
- Prompt versions: extract_signals.v4, personalize.v9
