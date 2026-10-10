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

---

## Entry #3 — 2026-10-10 — Phase 1: fixtures, extraction, full schema, scoring, selection, eval

**What Claude did:** built `hunter/models.py` (Config + domain Pydantic models), `hunter/db.py` (all 6 tables per PRD §13, not just the Phase-1 ones), `hunter/sources.py`, `hunter/llm.py` (replay/live switch, hash-keyed cache, prompt-file parser), `hunter/extract.py` (LLM extraction + grounding checks + FR-5 champion detection), `hunter/scoring.py` (§9 gates, scoring, ranking), `hunter/evaluate.py` (extraction+selection scorecard), `prompts/extract_signals.md`, and wired `reset`/`run`/`eval` in `hunter/cli.py`. Validated `scoring.py` and `select_leads` against every PRD §9.4 worked number and all 13 `_expected` lead statuses using fixture `_expected` values directly (bypassing the LLM) before touching real extraction, to isolate scoring-logic bugs from extraction-quality issues. Wrote `tests/` (12 tests across the 4 Phase-1 files) and ran the full verify sequence clean at the end.

**Mistakes found and corrected (several, in order):**

1. **YAML `on:` key parsed as the boolean `True`.** `config.yaml`'s `sequence` list uses an unquoted `on:` key (`{id: R1, on: "lead_qualified", ...}`). Stock PyYAML follows YAML 1.1 and resolves `on`/`off`/`yes`/`no` as booleans, silently turning that key into `True` and breaking `Config` validation. Fixed with a custom loader that narrows bool resolution to `true`/`false` only, leaving `on`/`off`/`yes`/`no` as plain strings - config.yaml itself was not changed.
2. **`ReplayMissError` would have printed a raw stack trace**, violating CLAUDE.md rule 5 ("a replay miss must fail with a clear message, never a stack trace"). Caught in `cli.py` before any pipeline code ran, not after - this was caught by deliberately testing the replay-miss path before ever attempting a live call.
3. **`temperature` doesn't exist in the installed `anthropic` SDK (1.13.0) for this model family.** `messages.create(temperature=...)` raised `TypeError`. The newer Claude 5 API dropped `temperature` in favor of `effort` (reasoning level) and `output_config`. Fixed by dropping the parameter from the live call (config.yaml's `llm.temperature` is kept but now documented as unused); confirmed via SDK introspection (`inspect.signature`), not guessed.
4. **Model wrapped JSON in a markdown fence** (` ```json ... ``` `) despite "Return JSON only" in the prompt - `json.loads` failed. Rather than hand-stripping fences, used the SDK's native structured-output support (`output_config.format` with a JSON Schema from `ExtractionResult.model_json_schema()`), which is a stronger guarantee than prompt instructions alone. This surfaced a secondary bug: Pydantic's generated schema only sets `additionalProperties: false` on the top-level model, not on nested models (`NamedPerson`), and the API requires it everywhere - fixed by adding `model_config = ConfigDict(extra="forbid")` to `NamedPerson` too.
5. **Responses were silently truncated**: `stop_reason: max_tokens` with the full 400-token budget spent on a hidden `thinking` block (375 of 400 tokens), leaving too little for the actual JSON. This model family can spend part of `max_tokens` on internal reasoning unless told not to. Added a proper `llm.effort: {extraction, personalization}` config section (same nested pattern as `models`/`max_tokens`) and set `effort: "low"` for extraction, matching the PRD's own "simple extraction → cheap/fast" intent (§11.2). Confirmed via direct API probing (checking `usage.output_tokens_details.thinking_tokens`) before deciding on the fix, not by guessing.
6. **Prompt v1's confidence guidance was simply wrong for this fixture set**, caught by running `hunter eval` against real extraction and diffing every field against `_expected`, not by assumption. Two real corrections, each confirmed by exact-matching the PRD's own worked numbers afterward:
   - v1 told the model a "clear technographic detection" was `high` confidence; the fixtures' intended reading is that confidence tracks *source reliability* (first-party quotes/job-posts = high, third-party tools/reviews = medium), not just clarity. Fixed in v2.
   - v1 gave no guidance for confidence when there's no evidence at all; the Pinecrest false-positive (`Cassandra` = a person's name) should be `high`-confidence *in the negative finding*, not low. Fixed in v3.
   - Also added explicit `"Apache Cassandra (self-managed)"` product guidance in v2 (text said "self-managed", gold expected that exact string; v1's schema only offered plain `"Apache Cassandra"`).
   - Each prompt version bump (`extract_signals.v1` → `v2` → `v3`) was followed by deleting the stale replay files and re-recording live, per CLAUDE.md's prompt-versioning rule.

**End state:** `hunter eval` → extraction 32/32 (100%), false-positive (s08) rejected correctly, selection 13/13 (100%), VERDICT: PASS. Account scores match PRD §9.4 exactly (96, 76, 78, 61, 23). Replay mode proven deterministic and keyless (`env -u ANTHROPIC_API_KEY`). Secret scan on `data/llm_replay/` clean (model output + token usage only). `pytest -q` → 12/12 passed.

**Decisions made by the human:** none required mid-phase; all of the above were engineering/technical corrections within the approved plan, not product or scope decisions.

---

## Entry #4 — 2026-10-10 — Post-Phase-1 review: overfitting check and PRD/config sync

**Prompt (summarized):** before Phase 2, Oz asked for (1) an overfitting check on `prompts/extract_signals.md` - confirm no fixture-specific content (company/person names, or rules written for one case), generalize anything found, re-record and re-run eval, and report honestly whether 100% still holds; (2) `config.yaml`'s dead `temperature` field replaced by the `effort` setting actually used, PRD §11.2 updated to match (including which model actually ran extraction), and the SDK finding confirmed logged here.

**What Claude did:**
- Read the full prompt line by line. Two lines reference "Cassandra" as a person's name (§ domain-appropriate: Apache Cassandra genuinely is named after a person, so handling that ambiguity is inherent to the task, not a fixture artifact - matches Oz's own example "a person's name is not a technology"). One line was a real miss: the confidence guidance said a name/tech collision is high-confidence absence-of-evidence "with an unrelated tech stack explicitly listed" - that qualifier describes the exact shape of one fixture's text (a job post with a literal "Stack: ..." list) rather than the general principle. Generalized it to "when a word that looks like a technology name is clearly being used as a person's name instead, with nothing else in the text suggesting that technology" - no reference to any particular text shape.
- Bumped to `extract_signals.v4`, deleted the stale replay files, re-recorded all 10 calls live, and re-ran `hunter eval`.
- Removed `temperature` entirely (not just stopped using it) from `config.yaml`, `hunter/models.py`'s `LLMConfig`, and the `llm.py`/`extract.py` call sites, since it was fully dead code once already documented as unused - keeping an unused parameter around once there's no ambiguity left to flag would just be clutter.
- Updated PRD §11.2 with two additions: a "Reasoning effort" row explaining the no-`temperature`/hidden-thinking-tokens finding and the `effort: low`/`medium` split, and a note on the "Output caps" row about using native structured output instead of prompt-only JSON. Confirmed in the same edit that extraction really did run on `claude-haiku-5-5` (visible in the replay files' `model` field), matching what §11.2 already claimed.
- The SDK finding (temperature removal, hidden thinking tokens, structured output) was already logged in entry #3; no new entry needed for that part, just this review round.

**Result (reported honestly, as asked):** extraction accuracy is still **32/32 (100%)** after generalizing the prompt, selection still 13/13, false-positive still rejected correctly, all 5 scored accounts still match PRD §9.4 exactly, replay still deterministic and keyless, replay files still secret-scan clean, `pytest -q` still 12/12. The generalization did not cost any accuracy on this fixture set.

**Decisions made by the human:** run an overfitting check before every phase that touches a prompt, not just once at the end; keep config.yaml's technical LLM knobs (not just business weights) free of dead/inaccurate fields; keep PRD §11.2 as a living record of what actually ran, not just the original plan.

---

## Entry #5 — 2026-10-10 — Phase 2: personalization, validators, grounding

**Prompt (summarized):** build personalization/validators/grounding on `claude-opus-5-5`; before committing any replay files, show the full text of 2 drafts (one invite, one email, different personas) for a tone check (no generic sales language, one concrete evidence reference); give every validator failure its own test.

**What Claude did:**
- Built `hunter/validators.py` (all 7 checks from PRD §11.5's table), `hunter/hitl.py` (routing decision only - the interactive review/approve/reject/edit CLI is Phase 3, per Oz's earlier reordering), `hunter/personalize.py` (drafts, retry-once-then-force-review, routing), `prompts/personalize.md` v1 with config-rendered rules/banned-phrases (never hard-coded), and extended `hunter/evaluate.py` with the grounding check. Wired invite-drafting into `hunter run` for every newly-qualified lead (R1, ahead of the full trigger engine in Phase 4).
- Refactored a 3-way-duplicated `_is_evidence` filter (scoring.py, personalize.py, and the new evaluate.py use) into one public `scoring.evidence_signals_for_account`, rather than copy-pasting it a third time.
- Drafted a sample warm email (Lior, practitioner) by calling `personalize.draft_message` directly with `variant="warm"`, to have a second example ready for Oz's tone review even though nothing in the pipeline triggers warm emails until Phase 4.
- Added one integration test beyond what was asked (`test_personalize_retry_and_routing.py`), monkeypatching `call_llm` to always return an invalid draft, to prove the retry-once-then-force-to-human-review path (FR-6's AC) actually works end-to-end, not just by code review.

**Mistake found and corrected:** re-running `--llm live` to record personalization silently re-called the *extraction* API too (live mode always called the API, never checking the cache first), producing new, slightly-reworded-but-equivalent extraction responses that overwrote 4 already-committed replay files. This also meant the `data/llm_replay/` directory accumulated orphaned duplicate recordings (3 extra invite variants with a different hash than the ones actually referenced by the DB) from earlier iterations in this same session. Root cause: `call_llm`'s live branch didn't check for an existing cache entry before calling, contradicting PRD §11.2's "a re-run with an unchanged input makes no call." Fixed by checking the cache first regardless of mode, only falling through to a live API call on an actual miss; confirmed idempotent by re-running `--llm live` and checking `git status` showed zero modified files; cleaned the orphaned files and re-recorded once to leave exactly the 5 files `hunter run` actually produces.

**Result:** `hunter eval` → extraction 32/32, selection 13/13, **grounding 5/5 (100%)**, VERDICT: PASS. `pytest -q` → 32/32 passed (19 validator tests - one per failure mode - plus the retry/routing integration test). Replay mode proven deterministic and keyless. Secret scan clean. Routing on the fixture set matches the PRD's §12.3 demo script exactly: Maya and Tom (Northwind, score 96) auto-approved; Joris, Lior and Dana routed to human review.

**Decisions made by the human:** Oz reviewed the two drafts and did not approve - see entry #6 for the specific corrections required.

---

## Entry #6 — 2026-10-10 — Phase 2 correction round: sender grounding, invite vendor names, connection framing

**Prompt (summarized):** Oz rejected the first two drafts with four specific, non-taste issues: (1) the invite claimed "I'm an engineer at ScyllaDB working on similar latency problems" - a sender fact not in any provided context; add `sender.title` to config, restrict the prompt to name/title/company for the sender, and add a validator plus a test "if it can be checked deterministically - if not, explain why." (2) LinkedIn invites must never name a competitor product (DataStax/Astra/DSE/IBM) - vendor context belongs in the email, not the invite; add a deterministic validator and test. (3) Invites: at most one specific number/metric, no filler compliments; add "impressive" to banned_phrases and the rule to the prompt. (4) Warm emails must open by acknowledging the accepted connection; cold must not assume one; add to the prompt and validate "if feasible." Bump to personalize.v2, re-record, re-verify, show the same 2 drafts again plus a cold email, update PRD §11.5's validators table, and commit only after approval.

**What Claude did:**
- Added `messaging.sender.title: "GTM Engineer"` to config.yaml and `MessagingSender.title` to the Pydantic model; added `"impressive"` to `banned_phrases`.
- Rewrote `prompts/personalize.md` as v2: the sender's only stateable facts are name/title/company; invites may not name DataStax/Astra DB/DSE/IBM (vendor context moves to the email) and may use at most one specific number; no filler compliments; warm emails must open acknowledging the connection, cold emails must not assume one.
- Added three new validators to `hunter/validators.py`: `validate_no_sender_claims`, `validate_no_competitor_mention_in_invite`, `validate_connection_framing`, each with its own passing/failing test (including one built from Oz's exact flagged sentence).
- **On "if it can be checked deterministically, if not explain why"**: a fully general check for "does this text make an unsupported claim" has no deterministic test - that's an open semantic question, the same category of problem as detecting any hallucination in free text. What *is* deterministic is pattern-matching the known failure shape (first-person claims about the sender's own work/experience beyond identity, and connection-acknowledgment phrasing). Implemented both `validate_no_sender_claims` and `validate_connection_framing` as regex-pattern checks, documented in-code and in PRD §11.5 as heuristic safety nets for the known failure shape, not exhaustive semantic verifiers - reported this limitation plainly rather than overclaiming a general solution.
- Re-recorded all personalize.v2 calls live and regenerated the invite and warm-email examples, plus a new cold-email example (Tom Hale, Northwind) for the three-draft review Oz asked for.

**Mistakes found and corrected (two, both real, found while re-recording):**
1. The first sender-claim regex (`"I'm working on"` with only `\s+` between "I'm" and the verb) didn't match Oz's actual flagged sentence, because "an engineer at ScyllaDB" sits between "I'm" and "working on". Caught immediately by writing the test around his exact sentence first and watching it fail. Fixed by allowing up to 60 non-sentence-ending characters between the pronoun and the claim verb.
2. **A real resilience gap, found while debugging an apparent flaky JSON-parse failure during manual redrafting**: `personalize.draft_message` called `json.loads(result.text)` with no exception handling - a malformed response (truncated JSON, an API hiccup, anything short of a clean parse) would raise an uncaught `JSONDecodeError` and crash the entire `hunter run`, not just route that one message to review. This directly contradicts PRD §11.7's own failure-handling table ("Invalid JSON or validator failure → one retry, then human review"), which the code didn't actually implement for the JSON-parse case - only for schema-valid-but-content-invalid drafts. Root-caused by reproducing the failure with direct instrumentation rather than assuming it was transient, even after it stopped reproducing. Fixed by wrapping the parse in `try/except (json.JSONDecodeError, ValidationError)`, treating a parse failure exactly like a validator failure (retry once, then force human review with the raw response preserved in the body for the reviewer to see), and added a dedicated test (`test_malformed_json_retries_then_forces_review_without_crashing`) distinct from the existing schema-valid-but-invalid-content test.
- Also cleaned up orphaned replay files that accumulated from the iterative debugging (computed the exact hash each real message actually uses and deleted everything else untracked), rather than committing debugging noise.

**Result:** `hunter eval` → extraction 32/32, selection 13/13, grounding 5/5, VERDICT: PASS (unchanged - this round was about message quality, not scoring/selection). `pytest -q` → 43/43 passed (10 new tests: 3 validators × ~3 cases each, plus the malformed-JSON retry test). All three re-reviewed drafts: no sender-claim hallucination, no vendor names in the invite, no filler compliments, warm opens with "Thanks for connecting," cold makes no connection reference. PRD §11.5 updated with the three new validators and an explicit note on their heuristic nature.

**Decisions made by the human:** Oz reviewed the regenerated drafts and did not approve - see entry #7.

---

## Entry #7 — 2026-10-10 — Phase 2 correction round 2: mislabeled quote, routing by score alone

**Prompt (summarized, in Hebrew with an English instruction):** Oz caught two more issues in Lior's and Tom's emails and one design gap: (1) Lior's email quoted "How we run 60 self-managed Apache Cassandra nodes" as if it were the talk's title - the real title is "Taming tail latency in our leaderboard cluster"; the quoted phrase is verbatim from the description, so grounding passed even though the label was wrong, and Lior would spot it immediately. Also two calls to action where the rule allows one. (2) Tom's cold email put the account's 2027 renewal year in the subject line (reads as surveillance), cited three evidence items (over-stuffed), and awkwardly referenced his own job posting. (3) **The important one**: Tom's email was the most commercially sensitive of the three (acquisition + renewal framing) and was the only one auto-approved, purely because Northwind scored 96 - proving account score and message risk are orthogonal and routing needs to consider both. Fix: bump to personalize.v3, add deterministic rules/validators for the content issues, add a content-based forced-review rule to §9.6 (competitor product, cf_ibm/IBM acquisition, or renewal/contract → always human, regardless of score), test it, update PRD §9.6 and §12.3's demo script if outcomes change, show the two emails again plus a routing summary, and log two specific findings: a validator-clean mislabeled quote, and auto-approval routing the riskiest message.

**What Claude did:**
- Added `validate_evidence_count` (hard cap of 2 evidence items/message - unlike the previous round, this one wasn't explicitly requested as "add a validator," but it's a trivial, zero-ambiguity count check in the same spirit as the existing length/value-prop-count validators, so added it directly and flagged the judgment call rather than silently expanding scope).
- Added `hunter/validators.is_sensitive_content(draft)`: true if the body/subject names a competitor product (extended `COMPETITOR_MENTION_PATTERN` is reused), cites `cf_ibm`, or mentions a renewal/contract (`RENEWAL_CONTRACT_PATTERN`). This is a **routing input, not a pass/fail validator** - sensitive content can be a perfectly good draft that still needs a human's eyes.
- Added `has_sensitive_content` to `hitl.determine_route`, overriding auto-approval regardless of score or `approval_mode` (except `approval_mode=all`, which was already all-human). Wired it from `personalize.draft_message`.
- Rewrote `prompts/personalize.md` as v3 (then v4 - see mistake below): quote/title labeling, one CTA, 2-evidence cap, no commercial details in the subject line, job posts framed as team direction.
- Added `tests/test_hitl_routing.py` (the test PRD §18.1 names) covering the full routing matrix, with a dedicated case proving sensitive content overrides a 96 score.

**Mistakes found and corrected (three - two content, one process):**
1. **The v3 prompt rule for quote/title labeling did not fix the actual model behavior** - re-tested Lior's email and it still quoted the description as if it were the title. Root-caused by inspecting what `extract.py` actually stored as `evidence_quote` for s06: it's the description sentence, not the title in the raw text (there's no separate `title` field in the extraction schema at all). Rather than touching extraction (out of the scope Oz set - he asked for a prompt fix), fixed it within personalize.py/personalize.md only: relabeled the evidence block's quote field as "excerpt (verbatim fragment, NOT a title)" and rewrote the system rule with a concrete instruction to paraphrase instead of quote when uncertain. Bumped to v4; re-tested Lior's email alone before committing to a full re-record, and confirmed the paraphrase this time, rather than assuming the second attempt worked.
2. **A second real resilience gap**, found while verifying the v3 recording: Tom's cold email hit `stop_reason: max_tokens` with 478 of 700 tokens spent on hidden `thinking` (same root cause as the Phase 1 extraction truncation, not yet fully covered for personalization's `effort: medium`). The retry-then-force-review path (added last round) caught it without crashing, but still wasted calls and produced a broken draft needlessly. Fixed by raising `max_tokens.personalization` 700 → 1200 in config.yaml, confirmed by direct API probing that this eliminates the truncation (`stop_reason: end_turn`, full response) before re-recording anything.
3. **Process mistake, not a product bug**: while cleaning up orphaned replay files from iterative debugging, ran `rm -f data/llm_replay/*.json` (twice) to get a clean slate for personalization - but this also deleted the 10 *committed* extraction replay files, which then got silently re-recorded with slightly different (non-deterministic but equivalent) wording under the same filenames. A later "keep only these hashes" cleanup script, built only from personalization hashes, then deleted 3 of those regenerated extraction files as presumed orphans, and `git status` showed them as deleted even though `git ls-files` proved they were tracked - the mismatch between what I'd *intended* to delete and what `git status` actually showed is what surfaced it. Fixed with `git checkout -- data/llm_replay/` to restore the committed extraction content exactly, then re-recorded personalization once, cleanly, against that now-stable extraction state - and confirmed with `git status | grep '^ M'` showing nothing before declaring it done. **Lesson, applied for the rest of the build**: never bulk-delete inside a git-tracked directory; remove specific known files, or rely on the cache-hit check instead of clearing anything.

**The two findings Oz asked to have on record:**
- **Validators passed but human review caught a mislabeled quote.** `evidence_quote` grounding only checks that quoted text is a verbatim substring of the source - it says nothing about whether the draft is using that text honestly (as a direct quote) or dishonestly (relabeling a description as a title). Verbatim-substring grounding is necessary but not sufficient; this specific failure mode needed a human reviewer, and a sharper prompt instruction rather than a new deterministic check (there's no field distinguishing "title" from "description" to check against).
- **Auto-approval was routing the riskiest message.** Account score measures lead quality (evidence strength, ICP fit, timing) - it has no relationship to how commercially sensitive a given draft's *wording* turns out to be. The highest-scoring account (Northwind, 96) produced the single most sensitive draft of the three reviewed (it named the IBM/DataStax acquisition and implied a contract renewal date), and was the only one of the three that auto-sent. Fixed by making content sensitivity an independent, unconditional routing input alongside score - §9.6 now routes on *both* axes, not score alone.

**Result:** `hunter eval` → extraction 32/32, selection 13/13, grounding 5/5, VERDICT: PASS (unchanged). `pytest -q` → 54/54 passed. Final Lior and Tom drafts: correct paraphrase (no mislabeled quote), one CTA each, ≤2 evidence items, no commercial details in subject lines, team-direction framing for job-post evidence. Tom's cold email now correctly routes to `PENDING_APPROVAL` despite the 96 score, because it names Astra DB. PRD §9.6 and §12.3 updated; §12.3 flags that Maya's warm email will likely also now route to human (not yet confirmed - no `simulate` command exists until Phase 4).

**Decisions made by the human:** pending final approval before commit.

---

## Entry #8 — 2026-10-10 — Phase 3: HITL CLI (review / approve / reject / edit)

**Prompt (summarized):** build FR-7's interactive CLI on top of the Phase 2 routing logic (`hitl.determine_route`, already tested): `review` shows each pending draft with its evidence and the routing reason (score band vs. content-sensitivity override); `approve <id> | --all`; `reject <id> --reason ".."`; `edit <id> --text ".."` keeps `original_body` and re-runs the validators on the edited text. Every decision writes an event. Tests for each command. Commit at the end of the phase and wait for OK before Phase 3 (now 4): triggers + simulate.

**What Claude did:**
- Extended `hitl.determine_route` from a `(route, status)` pair to `(route, status, reason)`, so the human-readable reason required by FR-7's `review` AC is generated from the same single branch of logic that decides routing, rather than a second parallel implementation that could drift from it. Updated its one caller (`personalize.draft_message`) and the existing `test_hitl_routing.py` assertions to match, and logged the reason into the `message_drafted` event payload (events' `payload` is an unconstrained JSON blob already, so this needed no schema change).
- Added `hitl.explain_route`, which recomputes `determine_route`'s three inputs from a *stored* message (cited evidence confidence via `signals`, a recorded validator failure via `reviewer_note`, and a text-based sensitivity check via the existing competitor/renewal regexes) and calls it again. This was a deliberate scope decision: PRD §13's ERD gives `accounts` and `leads` a `reason` column but not `messages`, and the build-order decision in Entry #2 fixed the full schema in Phase 1 with no mid-build migrations - so the reason shown in `review` is recomputed on demand, not persisted. One real limitation from this: the `cf_ibm` context-fact trigger inside `is_sensitive_content` can't be recovered this way, since `context_fact_ids` isn't a persisted column on `messages` either - only the body/subject regex checks (competitor product, renewal/contract) are recoverable. Documented in the docstring rather than silently accepted.
- Added `hitl.list_pending`, `hitl.approve`, `hitl.reject`, `hitl.edit`, each writing its own event (`message_approved`, `message_rejected` with the reason in `payload`, `message_edited` with the post-edit status and any remaining validator errors) - satisfying "every decision writes an event" without adding a table.
- Wired four thin Typer commands in `cli.py` (`review`, `approve`, `reject`, `edit`) that call these functions and format the output; all error handling (unknown id, wrong status) raises `ValueError` from `hitl.py` and is caught once at the CLI boundary, printed to stderr, exit code 1 - not scattered per command.
- **`edit`'s semantics required a judgment call the prompt didn't spell out**: FR-7 says edit "keeps original_body" and re-runs validators, but doesn't say what status the message ends up in. Decided that a human editing the text *is* their approval of it - so if the edited text now passes validators, status becomes `APPROVED` (and any stale `reviewer_note` from the original draft's validator failure is cleared); if it still fails, status stays `PENDING_APPROVAL` with the new validator errors recorded, so it can be edited again or rejected. `original_body` is only ever set from the message's *first* body (handles a second edit correctly: `original_body or body`, never overwritten by a later edit).
- Tests (`tests/test_hitl_cli.py`) test the `hitl` module functions directly against a dedicated per-test DB fixture, not the session-scoped `pipeline_conn` other test files read from (approving/rejecting/editing mutates status, which would make shared-connection tests order-dependent) and not through `typer.testing.CliRunner` (the CLI commands are thin wrappers with no logic of their own, and the project has no existing CliRunner tests to extend - consistent with Phase 2's `test_hitl_routing.py`, which also tests `hitl` functions directly rather than the CLI). Verified the CLI wiring itself manually end-to-end instead: `hunter run` (5 drafted, 2 auto / 3 pending matching §12.3 exactly) → `hunter review` → `hunter edit` (one invalid edit, one valid edit that flips to `APPROVED`) → `hunter reject` → `hunter review` (shows the edited draft's new "forced: validator failed" reason) → `hunter approve --all` → `hunter approve` on the now-`REJECTED` message correctly errors.

**Mistakes found and corrected:** none this phase - the only non-obvious decision (edit's post-validation status) is a design call, not a bug, and is logged above.

**Result:** `hunter eval` → extraction 32/32, selection 13/13, grounding 5/5, VERDICT: PASS (unchanged - no scoring/extraction/personalization logic touched). `pytest -q` → 67/67 passed (13 new HITL-CLI tests). Manual run matches PRD §12.3's demo script step 1-2 exactly.

**Decisions made by the human:** pending approval before commit.

---

## Entry #9 — 2026-10-11 — Phase 3 correction: `approve --all` must not sweep up content-sensitive drafts

**Prompt (summarized):** Oz caught that `approve --all` as built would bulk-approve *every* `PENDING_APPROVAL` draft, including ones forced to review by the §9.6 content-sensitivity override - one command would defeat the override routing just built. Required: `--all` approves only score-band pending drafts; sensitive drafts need an individual `approve <id>` or an explicit `--include-sensitive` flag; `review` must clearly mark which drafts are sensitive and why; add tests; update the PRD §12.3 demo script to show `--all` skipping Tom's email, then approving it individually after reading it.

**What Claude did:**
- This was a real correctness gap, not a style note: the Phase 3 `review`/`approve --all` just built was unconditional - it approved every row `hitl.list_pending` returned, with no awareness of *why* each one was pending. Fixing it required knowing which of several different forced-review reasons a given pending message represents, not just that it's pending.
- Gave `determine_route` a fourth return value, a stable `code` (one of `SCORE_BAND`, `SENSITIVE_CONTENT`, `VALIDATOR_FAILED`, `NO_HIGH_CONFIDENCE_EVIDENCE`, `APPROVAL_MODE_ALL`, plus the two auto-route codes), alongside the existing free-text `reason` - `--all`'s filtering and `review`'s badge match on the stable code, not by parsing the human-readable sentence. Added `hitl.route_info` (route, status, reason, code recomputed from a stored message) and refactored `explain_route` to use it, so there's one source of truth instead of two recomputations.
- Added `hitl.approve_all(conn, config, *, include_sensitive=False, now)`: bulk-approves only `SCORE_BAND` drafts by default; `include_sensitive=True` also sweeps up `SENSITIVE_CONTENT` ones; `VALIDATOR_FAILED` and `NO_HIGH_CONFIDENCE_EVIDENCE` drafts are **never** bulk-approved, with or without the flag - those are quality problems the reviewer should see, not a policy override `--all` can make on their behalf. Returns `(approved_ids, [(skipped_message, reason), ...])` so the CLI can report exactly what was skipped and why, with the message id to approve it individually.
- Wired a new `--include-sensitive` flag onto `hunter approve --all` and updated `review`'s output to print `[SENSITIVE CONTENT - excluded from 'approve --all']` next to any draft whose code is `SENSITIVE_CONTENT`.
- **Verified by hand, not just by reading the code**: since no email variant exists yet (R2/R3 are Phase 4), there was no real sensitive-content draft in the current pipeline to exercise this against. Inserted one directly via `db.insert_message` (a synthetic cold email naming DataStax, the IBM acquisition and a renewal) against the real `hunter.db` after a normal `hunter run`, then ran `review` → `approve --all` (0 approved, msg skipped with its id) → `approve <id>` (approved individually) end-to-end, confirming the behavior before writing it into tests or the PRD. Reset the DB afterward so the committed state stays the normal post-`run` snapshot.
- Added the same synthetic-message technique to `tests/test_hitl_cli.py`: `test_route_info_flags_sensitive_content`, `test_approve_all_skips_sensitive_content_by_default`, `test_approve_all_include_sensitive_approves_it_too`, `test_approve_all_never_sweeps_up_a_validator_failed_draft_even_with_include_sensitive`, `test_approve_all_never_sweeps_up_a_no_high_confidence_evidence_draft`. Added `test_approval_mode_all_overrides_everything` to `test_hitl_routing.py` for the new `code` return value's last untested branch.
- Updated PRD FR-7 (new AC for the skip-and-report behavior), §16.1's CLI table and quickstart (two separate `approve --all` calls, the second one now followed by an individual `approve <msg_id>` for Tom's flagged email), and §12.3's demo script steps 2 and 4 to describe the new `--all` behavior precisely (step 2: all three invites are pure score-band, so `--all` needs no flag there; step 4: `--all` approves Lior's/Joris's/Dana's emails but skips Tom's, which then needs an individual read-and-approve).

**Mistakes found and corrected:** none beyond the one Oz flagged - no further issues surfaced while implementing or verifying it.

**Result:** `pytest -q` → 73/73 passed (5 new sensitive-content tests + 1 new routing-code test). `hunter eval` → unchanged, VERDICT: PASS. Manual end-to-end check (synthetic sensitive draft, real `hunter.db`) matches the intended behavior exactly: `--all` approves the score-band drafts, reports the sensitive one as skipped with its id, and an individual `approve <id>` clears it.

**Decisions made by the human:** pending approval before commit, secret-scan, and push.
