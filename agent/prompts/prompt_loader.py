from __future__ import annotations

from pathlib import Path


PROMPTS_DIR = Path(__file__).resolve().parent


def load_prompt_template(filename: str) -> str:
    """Workflow support: Load a text prompt template from the shared prompt folder."""
    return (PROMPTS_DIR / filename).read_text(encoding="utf-8").strip()
