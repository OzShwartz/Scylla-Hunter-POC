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

**Decisions made by the human:**
- Champion_move confidence: inherit from the source signal that named the person (confirmed the recommended option), plus split PRD §9.2 into separate weights/confidence tables and state the inheritance rule explicitly in FR-5, so the ambiguity can't recur.
- ANTHROPIC_API_KEY: Oz will add it to `.env` himself when told the right moment; never to be pasted into chat or read by the agent.
- GitHub live source (FR-2): build it.
- Remote GitHub repo: local only for now; no push yet.

---

## Entry #2 — 2026-10-10 — Plan review: reordering and process corrections

**Prompt (summarized):** Oz reviewed the first draft build plan (presented via plan mode / ExitPlanMode) and rejected it with four structural corrections plus two process rules, before approving a revised version:
1. Build the full 6-table SQLite schema in Phase 1, not incrementally in Phase 4 — no schema migrations mid-build.
2. Move the HITL CLI (`review`/`approve`/`reject`/`edit`) from after the SHOULD items to right after personalization (now Phase 3) — otherwise 3 of 5 qualified leads stay stuck in `PENDING_APPROVAL` and the trigger-engine phase has nothing to exercise for them.
3. Build `evaluate.py` for extraction + selection in Phase 1 (needed while iterating on the extraction prompt, not after the README), extend it with grounding in Phase 2.
4. Write `README.md` once, at the end, after the full MUST + HITL flow works — rename the old "README + examples" phase to "examples + replay finalization," with the README drafted last.
Plus: end every phase with its own git commit (`"Phase N: <what>"`) and stop for explicit OK before the next phase; tell Oz the exact moment to add the API key to `.env` rather than assuming; log this feedback in `AI_WORKFLOW.md` as a human decision.

**What Claude did:**
- This was a **correction**, not a confirmation: the first draft plan had sequenced the DB schema, HITL CLI and eval scorecard later than they needed to be, which Oz caught would have left the trigger-engine phase unable to actually exercise 3 of the 5 qualified leads (they'd be stuck pending approval with no CLI to clear them). The agent had reasoned itself into a literal reading of PRD §15's MUST-then-SHOULD ordering without noticing this downstream blocker.
- Rewrote the plan file (`/Users/oz/.claude/plans/piped-sniffing-rain.md`) incorporating all four structural changes, renumbered the phases accordingly (new Phase 3 = HITL CLI, old Phase 3 trigger engine → Phase 4, etc.), added the explicit "stop and wait for OK after every phase" process rule, and added a mid-Phase-1 checkpoint instruction to flag the API-key moment explicitly rather than assuming timing.
- Noted that moving HITL earlier also resolves a tension flagged in the first draft (the §16.1 quickstart needs `review`/`approve` to exist before it can be demonstrated, which conflicted with README being a MUST-phase item preceding the HITL SHOULD-phase item in the original literal ordering).
- Re-exited plan mode with the revised plan; Oz approved it.

**Corrections (the agent's mistake and the fix):**
- **Mistake:** followed PRD §15's MUST/SHOULD/COULD *priority* labels as if they were also the required *build sequence* within MUST items, without checking whether an earlier MUST phase would be left unexercisable by a later one. Priority order and dependency order are not automatically the same thing.
- **Fix:** sequence by dependency — build whatever a later phase needs to be fully exercised (full schema, HITL CLI to clear pending drafts, eval scorecard to iterate against) as early as the thing that needs it, regardless of MUST/SHOULD label, then document the reasoning in the plan so it's auditable.

**Decisions made by the human:**
- Full 6-table schema built in Phase 1, not incrementally.
- HITL CLI moved to Phase 3 (right after personalization), ahead of the trigger engine.
- `evaluate.py` (extraction + selection) built in Phase 1; grounding check added in Phase 2. No separate later "add eval" phase.
- `README.md` drafted once at the end (Phase 6), after the full MUST + HITL flow is working, not alongside the MUST-only cut.
- Process: every phase ends in its own commit and an explicit stop for approval before the next phase begins.

---

## Near-miss — 2026-10-10 — API key pasted into the wrong file

While staging the Phase 0 scaffold commit, `git status` showed `.env.example` (tracked, **not** gitignored) as modified. The diff showed a real `ANTHROPIC_API_KEY` value had been pasted into it — `.env` (gitignored) did not exist. Oz had put the key in the placeholder template instead of the real, ignored file.

**What Claude did:** stopped before staging or committing anything further, inspected only enough to confirm the key was not staged and `.env` didn't exist, restored `.env.example` to its empty placeholder, and flagged it to Oz rather than silently fixing and moving on, or creating `.env` with the key itself (per the standing decision that Oz handles the real key value, never Claude).

**Why this matters / how to apply:** `.env.example` is committed by design (CLAUDE.md §"Security and secrets"); anything pasted there is one `git add` away from being public. The fix is mechanical (empty the placeholder, ask the human to use `.env`), but the check — reading `git status`/`git diff` before every `git add`, especially for files near secrets — is what caught it. Diagnosing this required briefly viewing the key in `cat`/`diff` output, which is a narrow, justified exception to "never print `.env`" when the alternative is risking it reaching git history; the value was not committed, logged elsewhere, or repeated after the fix.

---

## Decision — 2026-10-10 — Key rotated after the near-miss

**Decision made by the human:** because the exposed key's value had entered this session (visible in tool output while diagnosing the near-miss above, even though never committed), Oz treated it as compromised, revoked it in the Anthropic Console, generated a new key, and created `.env` himself (not `.env.example`) with the new value. In the same step he discovered `.env.example` had been deleted from disk (likely `mv` instead of `cp` when creating `.env`) — Claude restored it from git (`git restore .env.example`; no content was lost, it only had the empty placeholder).

**Verification run after rotation** (none of it reads `.env`'s contents):
- `git check-ignore .env` → prints `.env` (ignored, confirmed).
- `git grep -n "sk-ant"` across tracked files → 2 matches, both inside `.claude/skills/{pre-submit,record-replay}/SKILL.md`, which quote the grep pattern itself as documentation (`"sk-ant-|..."`) — not a real key.
- `git log -p | grep -c "sk-ant"` → 2, same two documentation lines, present since the first commit — not a real key. (Oz's own checklist expected 0 here; the correct expectation for this repo is 2, exactly matching the two skill-file references, for as long as those skill files exist.)
- `AI_WORKFLOW.md` and all other tracked files: no key fragments.

**How to apply:** the pre-submit skill's own secret-scan command (`git log -p | grep -Ein "sk-ant-|..."`) will always return at least 2 for this repo because of its own documentation text — don't treat a non-zero count as a blocker without first checking which lines matched.
