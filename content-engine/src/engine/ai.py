"""Thin wrapper around the Claude API for structured (JSON-schema) answers.

Everything AI in the engine goes through `structured()`, so tests can
monkeypatch one function and the rest of the system never imports `anthropic`.
Enabled only when ANTHROPIC_API_KEY is set and `anthropic` is installed.
"""
from __future__ import annotations

import json

from . import config

MAX_CONTINUATIONS = 5


class AIUnavailable(RuntimeError):
    pass


def available() -> bool:
    if not config.env("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def model() -> str:
    return config.env("ENGINE_CLAUDE_MODEL", "claude-opus-5-5")


def structured(system: str, prompt: str, schema: dict, *, web_search: bool = False,
               max_searches: int = 5) -> tuple[dict, str]:
    """Ask Claude for JSON matching `schema`. Returns (data, model_that_answered).

    With web_search=True Claude may search the web first (useful for checking
    that steps match the current OS/app version)."""
    if not available():
        raise AIUnavailable("Set ANTHROPIC_API_KEY and `pip install -e \".[ai]\"` to use AI features.")
    import anthropic

    client = anthropic.Anthropic()
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}] if web_search else []
    messages: list = [{"role": "user", "content": prompt}]
    for _ in range(MAX_CONTINUATIONS + 1):
        response = client.beta.messages.create(
            model=model(),
            max_tokens=16000,
            system=system,
            messages=messages,
            output_config={
                "effort": config.env("ENGINE_CLAUDE_EFFORT", "medium"),
                "format": {"type": "json_schema", "schema": schema},
            },
            # Server-side refusal fallback: a declined request is rerouted automatically.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            **({"tools": tools} if tools else {}),
        )
        if response.stop_reason != "pause_turn":
            break
        # Long server-side search loop paused; resend so the server resumes it.
        messages = [messages[0], {"role": "assistant", "content": response.content}]
    else:
        raise RuntimeError("Claude's research turn did not finish; try again or disable web search.")

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined this request.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("Claude's response was truncated; try asking for fewer items.")
    # The JSON answer is the text after the last search result (earlier text may be commentary).
    blocks = list(response.content)
    last_tool = max((i for i, b in enumerate(blocks) if b.type.endswith("tool_result")), default=-1)
    text = "".join(b.text for b in blocks[last_tool + 1:] if b.type == "text")
    return json.loads(text), response.model
