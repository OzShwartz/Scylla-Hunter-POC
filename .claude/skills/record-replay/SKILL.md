---
name: record-replay
description: Record real Claude API responses into data/llm_replay so the reviewer can run Scylla Hunter without an API key; use when prompts change or replay files are missing.
---

# Record replay

Live mode calls the Claude API and saves each response under `data/llm_replay/`. The response is keyed by `hash(prompt_version, model, rendered input)`. Replay mode then reproduces the run with no key.

## Preconditions
- The user has put `ANTHROPIC_API_KEY` in `.env`.
  - **Never read `.env` yourself.** Never ask the user to paste the key into the chat.
  - If the key is missing, the CLI will say so. Relay that message.
- `run-eval` passes for everything that does not depend on new responses.

## Steps
1. Remove stale replay files only for prompt versions that changed. Keep the others.
2. Record the live responses:
   ```bash
   python -m hunter reset
   python -m hunter run --llm live
   python -m hunter simulate --days 7 --llm live
   ```
3. Prove that replay mode now needs no key:
   ```bash
   env -u ANTHROPIC_API_KEY python -m hunter reset
   env -u ANTHROPIC_API_KEY python -m hunter run
   env -u ANTHROPIC_API_KEY python -m hunter simulate --days 7
   ```
4. Run `python -m hunter eval`. Extraction must still be 100%. If it is not, show the user the extraction that disagrees with `_expected` and stop.
5. Scan the new files for secrets:
   ```bash
   grep -rEn "sk-ant-|api[_-]?key|authorization|x-api-key" data/llm_replay/ || echo "clean"
   ```
   Replay files must contain only the model's output and usage numbers.
6. Read 2–3 generated messages and check them against the PRD §11.5 validators.

## Report back
Report:
- number of calls;
- tokens in and out;
- models used;
- eval result;
- secret scan result;
- any message that reads generic or awkward, even if it passes the validators.
