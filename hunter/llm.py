"""Claude API client with replay/live mode switch and hash-keyed response cache.

Replay files are keyed by hash(prompt_version, model, rendered input) and store
only the model's text output and token usage - never headers, never the API key.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


class ReplayMissError(Exception):
    """Raised when replay mode has no cached response for a call."""


@dataclass
class PromptSpec:
    version: str
    system: str
    user_template: str


def load_prompt_spec(path: str | Path) -> PromptSpec:
    """Parse a prompts/*.md file: a `prompt_version:` header, a `# System
    prompt` section, and a `# User message template` section whose content
    is the first fenced code block that follows it.
    """
    text = Path(path).read_text(encoding="utf-8")

    version_match = re.search(r"^prompt_version:\s*(.+)$", text, re.MULTILINE)
    if not version_match:
        raise ValueError(f"{path}: missing 'prompt_version: <name>' header")
    version = version_match.group(1).strip()

    parts = text.split("# User message template")
    if len(parts) != 2:
        raise ValueError(f"{path}: expected exactly one '# User message template' section")
    system_part, template_part = parts

    system = re.sub(r"^.*?# System prompt\s*", "", system_part, flags=re.DOTALL).strip()

    template_match = re.search(r"```\s*\n(.*?)```", template_part, re.DOTALL)
    if not template_match:
        raise ValueError(f"{path}: no fenced code block found under '# User message template'")
    user_template = template_match.group(1).strip("\n")

    return PromptSpec(version=version, system=system, user_template=user_template)


@dataclass
class LLMResult:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    from_replay: bool
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


def _hash_key(prompt_version: str, model: str, rendered_input: str) -> str:
    payload = json.dumps(
        {"prompt_version": prompt_version, "model": model, "input": rendered_input},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _replay_path(replay_dir: str | Path, key: str) -> Path:
    return Path(replay_dir) / f"{key}.json"


def call_llm(
    *,
    mode: str,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    prompt_version: str,
    replay_dir: str | Path = "data/llm_replay",
    output_schema: dict | None = None,
    effort: str | None = None,
) -> LLMResult:
    """Call Claude, or replay a previously recorded response.

    `mode` is "replay" (default, no key needed) or "live" (calls the real API
    and records the response for future replay).
    """
    key = _hash_key(prompt_version, model, user)
    path = _replay_path(replay_dir, key)

    # A cache hit short-circuits both modes: per PRD §11.2, "a re-run with an unchanged
    # input makes no call" - live mode is for recording *new or changed* prompts, not
    # for blindly re-calling everything (which would also churn replay files with
    # harmless but noisy wording variance on every re-run).
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        return LLMResult(
            text=cached["text"],
            tokens_in=cached["tokens_in"],
            tokens_out=cached["tokens_out"],
            model=cached["model"],
            from_replay=True,
            # .get() with a default: replay files recorded before prompt caching was
            # added don't have these keys.
            cache_creation_input_tokens=cached.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=cached.get("cache_read_input_tokens", 0),
        )

    if mode == "replay":
        raise ReplayMissError(
            f"No replay found for prompt_version={prompt_version!r}, model={model!r} "
            f"(key {key[:12]}...). Run once with `--llm live` and an ANTHROPIC_API_KEY "
            "in .env to record it, or use the committed replay set in data/llm_replay/."
        )

    if mode == "live":
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Add it to .env (see .env.example), "
                "then re-run with --llm live."
            )
        # This model family has no temperature param on messages.create() - effort (below)
        # is what this SDK uses instead.
        create_kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            # Prompt caching: the system prompt (sender identity, rules, banned phrases)
            # is identical across every call for a given prompt_version - only the user
            # message varies per lead. Both prompts in this project comfortably clear the
            # 512-token minimum for the Opus/Haiku 5.5 models configured in config.yaml
            # (measured ~750-1600 tokens); a prompt that ever fell below the minimum would
            # just be served uncached, per Anthropic's docs - no error either way.
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
        )
        output_config: dict = {}
        if output_schema is not None:
            # Native structured output: guarantees raw JSON matching the schema, no
            # markdown fences or commentary to strip - stronger than prompt instructions alone.
            output_config["format"] = {"type": "json_schema", "schema": output_schema}
        if effort is not None:
            # Without this, the model may spend part of max_tokens on hidden reasoning,
            # which can truncate the actual answer (see AI_WORKFLOW.md).
            output_config["effort"] = effort
        if output_config:
            create_kwargs["output_config"] = output_config
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(**create_kwargs)
        text = "".join(block.text for block in response.content if block.type == "text")
        result = LLMResult(
            text=text,
            tokens_in=response.usage.input_tokens,
            tokens_out=response.usage.output_tokens,
            model=model,
            from_replay=False,
            cache_creation_input_tokens=getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "text": result.text,
                    "tokens_in": result.tokens_in,
                    "tokens_out": result.tokens_out,
                    "model": result.model,
                    "prompt_version": prompt_version,
                    "cache_creation_input_tokens": result.cache_creation_input_tokens,
                    "cache_read_input_tokens": result.cache_read_input_tokens,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return result

    raise ValueError(f"Unknown llm mode: {mode!r} (expected 'replay' or 'live')")
