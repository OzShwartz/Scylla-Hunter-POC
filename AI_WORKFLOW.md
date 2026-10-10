# AI_WORKFLOW.md: how Scylla Hunter was built

This log records how the project was built with Claude Code: the significant prompts given, mistakes the agent made and how they were corrected, and decisions made by the human (Oz). Required by PRD §16.3 / §2.1 (S4).

Format per entry: prompt summary → what Claude did → corrections (if any) → decisions made.

---

## Entry #1 — 2026-10-10 — Kickoff: inspect, plan, do not code yet

**Prompt (summarized):** Read the PDF assignment, PRD.md (source of truth, supersedes any earlier proposal/review files), CLAUDE.md (project rules), config.yaml, data/fixtures.json and the three `.claude/skills/`. Then, before writing any code: (1) inspect the folder vs PRD §16.2 and report what exists/is missing; (2) check the environment (Python version, git, venv); (3) propose a phased build plan following PRD §15 (MUST → SHOULD → COULD), each phase runnable and tested with exact verify commands, mapped to R1–R5/FR-x; (4) list ambiguous or risky parts of the PRD with suggested resolutions; (5) list every decision needed from the human. Also: `git init` and a first commit of existing files (checking `.gitignore` keeps `.env` out), and create this file with the prompt logged as entry #1. Wait for plan approval before writing code.

**What Claude did:**
- Found that the working directory only contained the PDF, `PRD.md` and a `scylla-hunter-starter.zip`; the rest of the starter kit (`CLAUDE.md`, `config.yaml`, `data/fixtures.json`, `.claude/skills/`, `docs/diagrams/`, `.gitignore`, `.env.example`) was packaged inside the zip. Extracted it and flattened it into the project root (after confirming the zip's `PRD.md` was byte-identical to the root copy).
- Read all required files in full.
- Checked environment: Python 3.13.3, git 2.39.5, no `.venv` yet, no git repo yet.
- Added the assignment PDF and the starter zip to `.gitignore` (not part of the PRD §16.2 repo layout; kept on disk, not tracked) — a judgment call flagged to the user rather than silently made.
- Ran `git init` and committed the 24 starter files (spec, rules, config, fixtures, diagrams, skills) as the first commit. Verified no secrets and no `.env` were staged before committing.
- Cross-checked the §9.4 worked scoring examples against the §9.2/§9.3 formulas and config.yaml by hand for all 5 scored accounts, to catch inconsistencies before writing scoring code.
- Found one real numeric contradiction: §9.2's signal table pairs `champion_move` with confidence `low` (factor 0.5), but the only way to reproduce Brightwave's worked score of 61 (champion_move value 30.9) is with confidence `high` (factor 1.0) — which matches the confidence of the original signal (s01) where the champion person was named. Flagged to the user with a proposed resolution (inherit confidence from the source signal) rather than guessing silently, per CLAUDE.md's "stop and ask" rule.
- Found a build-order vs. quickstart tension: PRD §15 places "README, AI_WORKFLOW.md, examples, record replay" (MUST) before "HITL routing/CLI" and "report.html" (SHOULD), but the §16.1 quickstart that the README must document uses `hunter review` / `hunter approve --all` (SHOULD-phase commands). Proposed resolution: Phase 5 ships a first-pass README/examples showing the MUST-only flow; pre-submit (already specified to regenerate `examples/` from final code) finalizes both once the SHOULD items exist.
- Did not write any application code yet, per instruction to wait for plan approval.

**Corrections:** none yet — first turn.

**Decisions made by the human:** pending (see the plan message for the list of decisions requested).
