from __future__ import annotations

import json
import os
import textwrap
from pathlib import Path
from typing import Any

from groq import Groq


class LLMError(RuntimeError):
    """Raised when the LLM call fails or returns invalid JSON."""


def _load_repo_env_file() -> None:
    """Workflow helper 0: Load root .env values into the process environment when present."""
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def shorten_for_prompt(text: str, max_chars: int) -> str:
    """Workflow helper A: Trim large prompt sections so model requests stay within budget."""
    clean = text.strip()
    if len(clean) <= max_chars:
        return clean
    head = max_chars // 2
    tail = max_chars - head - len("\n...[truncated]...\n")
    return f"{clean[:head].rstrip()}\n...[truncated]...\n{clean[-tail:].lstrip()}"


def call_llm(prompt: str) -> str:
    """
    Workflow 3A: Send one structured prompt to Groq and return the raw text response.

    Contract:
    - Input: prompt string
    - Output: string (expected to be STRICT JSON by caller's prompt discipline)
    """
    _load_repo_env_file()
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise LLMError(
            "Missing GROQ_API_KEY. Set it in your environment (see .env.example) "
            "or run with --offline / AGENT_OFFLINE_MODE=1."
        )

    model = os.getenv("GROQ_MODEL", "").strip() or "lllama-3.1-8b-instant"
    max_tokens = int(os.getenv("GROQ_MAX_TOKENS", "").strip() or "2048")
    preview = textwrap.shorten(prompt.replace("\n", " "), width=140, placeholder="...")
    print(f"[llm] Requesting LLM model={model} prompt={preview}")

    client = Groq(api_key=api_key)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"Groq API request failed: {e}") from e

    try:
        text = str(response.choices[0].message.content).strip()
        if not text:
            raise LLMError(f"Empty model output text. Full response: {response}")
        return text
    except Exception as e:  # noqa: BLE001
        raise LLMError(f"Unexpected Groq response shape: {response}") from e


def must_parse_json(text: str) -> Any:
    """Workflow helper B: Parse model output as JSON with a readable failure message."""
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        snippet = textwrap.shorten(text.replace("\n", " "), width=300, placeholder="…")
        raise LLMError(f"LLM did not return valid JSON: {e}\nResponse snippet: {snippet}") from e

