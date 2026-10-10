---
name: run-eval
description: Run the Scylla Hunter evaluation scorecard and tests after any change to prompts, scoring weights, config.yaml or fixtures, and report regressions against the PRD.
---

# Run eval

Use this after changing anything in `prompts/`, `config.yaml`, `hunter/scoring.py`, `hunter/extract.py`, `hunter/personalize.py`, `hunter/validators.py` or `data/fixtures.json`.

## Steps
1. Run, in replay mode:
   ```bash
   python -m hunter reset
   python -m hunter run
   python -m hunter eval
   pytest -q
   ```
2. Read the scorecard and compare it with the targets in PRD §7.3:
   - extraction accuracy 100%
   - false-positive rejection 1/1
   - selection accuracy 13/13
   - grounding rate 100%
3. Check the account scores against PRD §9.4:
   - Northwind 96, Kestrel 78, Lumen 76, Brightwave 61, Orbit 23.
   - If a score changed on purpose, update PRD §9.4 in the same change. Otherwise it is a regression.
4. If a replay miss occurs because a prompt changed, do **not** edit replay files by hand. Tell the user that the `record-replay` skill must be run with a live key.

## Report back
- **Verdict:** PASS, or REGRESSION with the failing items.
- **For each failure:** expected value, actual value, and the most likely cause.
- **Do not "fix" a failure by changing `_expected` values** unless the user explicitly agrees that the expectation was wrong.
