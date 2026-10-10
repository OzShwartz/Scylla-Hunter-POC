---
name: pre-submit
description: Final pre-submission check for the Scylla Hunter home assignment - fresh-clone run, requirement coverage, examples, secrets and docs - before sending the GitHub link.
---

# Pre-submit check

## 1. Fresh clone, no keys
```bash
rm -rf /tmp/hunter-check && git clone <repo-url> /tmp/hunter-check && cd /tmp/hunter-check
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
env -u ANTHROPIC_API_KEY -u GITHUB_TOKEN bash -c '<README quickstart commands>'
pytest -q && python -m hunter eval
```
Time it. Target: under 5 minutes. Any error is a blocker.

## 2. Requirement coverage
Check each item against the repo and quote the file that satisfies it:

| ID | Requirement |
|---|---|
| R1 | Lead identification logic, including how people are found "on LinkedIn" |
| R2 | LLM-written LinkedIn invite and follow-up email |
| R3 | Trigger logic with dry-run logging to console or file |
| R4 | Report of leads gathered, selected and messages "sent", kept in a database |
| R5 | Engagement tracked (funnel and rates) |
| S1–S4 | Repo link, run instructions, output examples, prompts/agents used to build it |

## 3. Examples are current
Regenerate `examples/` from the final code:
- `report.md`
- `report.html`
- `outbox.jsonl`
- `run_log.txt`
- `hunter.db`

Confirm that the numbers in the README equal those in `examples/report.md`.

## 4. Secrets and privacy
```bash
git log -p | grep -Ein "sk-ant-|ghp_|github_pat_|api[_-]?key\s*=" || echo "history clean"
git ls-files | grep -E "^\.env$" && echo "BLOCKER: .env tracked"
```
- All people in fixtures are fictional, on `.example` domains.

## 5. Docs
- **README:** quickstart first; decisions; "what I left out and why"; example output inline.
- **AI_WORKFLOW.md:** real prompts, at least one correction, and the human decisions.
- **PRD.md:** matches the code (scores in §9.4, CLI in §16.1).

## Report back
- A checklist with PASS, FAIL or BLOCKER for each item.
- Fix nothing without asking.
