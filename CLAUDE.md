# CLAUDE.md: Scylla Hunter

PoC for a ScyllaDB GTM Engineer home assignment: find DataStax/Cassandra users, qualify them, draft LinkedIn invites and follow-up emails with an LLM, run trigger logic in dry-run, store everything in SQLite and report it.

## Source of truth
- **`PRD.md` is the spec.** Build what it says. Do not redesign.
- If something in the PRD is wrong, unclear or in conflict, **stop and ask**. Do not silently diverge.
- Scoring formulas, thresholds and expected numbers are in PRD §9; all parameters live in `config.yaml`. Never hard-code a weight.

## Non-negotiable rules
1. **Code decides what, the LLM decides how.**
   - The LLM is used only in `hunter/extract.py` (signal extraction) and `hunter/personalize.py` (wording), both through `hunter/llm.py`.
   - Qualification, selection, routing and triggers are deterministic code.
2. **Dry-run is the default.** No code path may contact LinkedIn, send email or call any outreach service.
3. **Never scrape or automate LinkedIn.**
4. **Grounding is enforced in code** (PRD §11.4), not only asked for in prompts.
5. **The reviewer must run everything without keys.**
   - `llm.mode: replay` is the default.
   - A replay miss must fail with a clear message, never with a stack trace.
6. **Secrets:**
   - Never read, print, log or commit `.env`, or any key or token.
   - Never put a key in code, tests, fixtures, replay files or docs.
7. **Fixtures:** `_expected*` fields are test oracles. Pipeline code must never read them; only `hunter/evaluate.py` and tests may.

## Stack
- Python 3.11+, Typer, Pydantic v2, PyYAML, SQLite (stdlib), Jinja2, anthropic SDK, python-dotenv, pytest.
- FastAPI + uvicorn only for `hunter serve`.
- No LangChain, no ORM, no Docker requirement.

## Conventions
- Small modules, as listed in PRD §16.2. Type hints everywhere. Pydantic models in `hunter/models.py`.
- Every status change writes a row to `events`. Every decision stores a human-readable `reason`.
- Time comes from an injectable clock (`as_of` plus simulated days), never `datetime.now()` in pipeline logic.
- Prompts live in `prompts/*.md` with a version header. Bump the version when you change a prompt.

## Commands
```bash
python -m hunter reset && python -m hunter run      # full pipeline, replay mode
python -m hunter eval                               # must stay 100% on extraction + selection
pytest -q                                           # must pass before any commit
```

## Workflow
- Work in the build order of PRD §15. Finish and test one item before starting the next.
- After any change to prompts, weights or scoring, run the `run-eval` skill.
- Before committing new LLM responses, run the `record-replay` skill.
- Before submission, run the `pre-submit` skill.
- Keep `AI_WORKFLOW.md` updated:
  - log significant prompts given to you;
  - log mistakes you made that were corrected;
  - log decisions made by the human.
