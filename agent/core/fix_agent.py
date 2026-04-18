from __future__ import annotations

from pathlib import Path

from agent.core.llm import LLMError, call_llm, must_parse_json, shorten_for_prompt
from agent.core.models import GeneratedFile, Plan, ValidationResult
from agent.prompts.prompt_loader import load_prompt_template

PROJECT_CONSTRAINTS = load_prompt_template("project_constraints.txt")


class FixAgent:
    """
    FixAgent proposes file replacements when validation fails.

    The first version keeps the repair request broad and relies on the
    validator logs plus the original plan to ask for one or two files back.
    """

    def __init__(self, offline: bool) -> None:
        """Workflow X1: Store whether repair attempts may call the LLM."""
        self._offline = offline

    def fix(
        self,
        spec_text: str,
        plan: Plan,
        validation: ValidationResult,
        app_dir: Path | None = None,
        *,
        error_digest: str | None = None,
        focus_file: str | None = None,
        attempt: int = 1,
    ) -> list[GeneratedFile]:
        """Workflow X2: Ask the model for a small set of full-file replacements."""
        _ = app_dir
        _ = focus_file
        _ = attempt
        if self._offline:
            return []

        prompt = (
            load_prompt_template("fix_prompt.txt")
            .replace("__PROJECT_CONSTRAINTS__", PROJECT_CONSTRAINTS)
            .replace("__SPEC_EXCERPT__", shorten_for_prompt(spec_text, 700))
            .replace("__PLAN_TEXT__", f"Goal: {plan.goal}")
            .replace("__ORDERED_STEPS__", "\n".join(f"{step.order}. {step.title}" for step in plan.steps))
            .replace("__CURRENT_FILES_EXCERPT__", "(Current file context added later.)")
            .replace("__ALLOWED_PATHS__", "\n".join(f"- {path}" for path in plan.components + plan.tests))
            .replace("__PREFERRED_PATHS__", "\n".join(f"- {path}" for path in plan.components))
            .replace("__RETRY_NOTE__", "")
            .replace("__FOCUS_SECTION__", "")
            .replace("__ERROR_DIGEST__", error_digest or shorten_for_prompt(validation.test_log, 1200))
            .replace("__FOCUS_FILE_SECTION__", "")
        )

        try:
            data = must_parse_json(call_llm(prompt))
        except (LLMError, KeyError, TypeError, ValueError):
            return []

        files = data.get("files", [])
        return [
            GeneratedFile(path=str(item["path"]), content=str(item["content"]))
            for item in files
            if isinstance(item, dict) and "path" in item
        ]
