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
        """Workflow X2: Ask the model for a focused set of full-file replacements."""
        if self._offline:
            return []

        current_files_excerpt = self._current_files_excerpt(plan, app_dir, focus_file)
        allowed_paths = [focus_file] if focus_file and focus_file in plan.components else plan.components + plan.tests
        retry_note = (
            f"NOTE: This is fix attempt {attempt}. Make the smallest possible change.\n"
            if attempt > 1
            else ""
        )
        focus_section = (
            f"Primary suspect: {focus_file}\nFix this file first unless the logs clearly implicate another file.\n"
            if focus_file
            else ""
        )
        prompt = (
            load_prompt_template("fix_prompt.txt")
            .replace("__PROJECT_CONSTRAINTS__", PROJECT_CONSTRAINTS)
            .replace("__SPEC_EXCERPT__", shorten_for_prompt(spec_text, 700))
            .replace("__PLAN_TEXT__", f"Goal: {plan.goal}")
            .replace("__ORDERED_STEPS__", "\n".join(f"{step.order}. {step.title}" for step in plan.steps))
            .replace("__CURRENT_FILES_EXCERPT__", current_files_excerpt)
            .replace("__ALLOWED_PATHS__", "\n".join(f"- {path}" for path in allowed_paths))
            .replace("__PREFERRED_PATHS__", "\n".join(f"- {path}" for path in plan.components))
            .replace("__RETRY_NOTE__", retry_note)
            .replace("__FOCUS_SECTION__", focus_section)
            .replace("__ERROR_DIGEST__", error_digest or shorten_for_prompt(validation.test_log, 1200))
            .replace("__FOCUS_FILE_SECTION__", focus_section)
        )

        try:
            data = must_parse_json(call_llm(prompt))
        except (LLMError, KeyError, TypeError, ValueError):
            data = None

        if data is None and focus_file and app_dir is not None:
            focused_fix = self._retry_with_single_file_prompt(
                spec_excerpt=shorten_for_prompt(spec_text, 700),
                test_excerpt=error_digest or shorten_for_prompt(validation.test_log, 1200),
                focus_file=focus_file,
                app_dir=app_dir,
            )
            return [focused_fix] if focused_fix is not None else []

        files = data.get("files", [])
        return [
            GeneratedFile(path=str(item["path"]), content=str(item["content"]))
            for item in files
            if isinstance(item, dict) and "path" in item
        ]

    def _current_files_excerpt(self, plan: Plan, app_dir: Path | None, focus_file: str | None) -> str:
        """Workflow X3: Provide the model with the current contents of the likely target files."""
        if app_dir is None:
            return "(No current file context provided.)"

        paths = ([focus_file] if focus_file else []) + [
            path for path in plan.components if path != focus_file
        ]
        chunks: list[str] = []
        for relative_path in paths:
            if relative_path is None:
                continue
            file_path = app_dir / relative_path
            if not file_path.exists():
                continue
            chunks.append(
                f"FILE: {relative_path}\n{shorten_for_prompt(file_path.read_text(encoding='utf-8'), 700)}"
            )
        return "\n\n".join(chunks) if chunks else "(No matching files found.)"

    def _retry_with_single_file_prompt(
        self,
        *,
        spec_excerpt: str,
        test_excerpt: str,
        focus_file: str,
        app_dir: Path,
    ) -> GeneratedFile | None:
        """Workflow X4: Retry once with a smaller prompt scoped to one file."""
        file_path = app_dir / focus_file
        if not file_path.exists():
            return None

        prompt = (
            "You are FixAgent.\n"
            "Return STRICT JSON only.\n"
            "Repair exactly one existing React/TypeScript file.\n\n"
            f"Spec:\n{spec_excerpt}\n\n"
            f"Failing tests:\n{test_excerpt}\n\n"
            f"Target file path:\n{focus_file}\n\n"
            "Current file content:\n"
            f"{file_path.read_text(encoding='utf-8')}\n\n"
            "JSON schema:\n"
            '{ "files": [ { "path": "src/...", "content": "..." } ] }'
        )
        try:
            data = must_parse_json(call_llm(prompt))
        except (LLMError, KeyError, TypeError, ValueError):
            return None

        files = data.get("files", [])
        if len(files) != 1:
            return None
        item = files[0]
        return GeneratedFile(path=str(item.get("path", "")), content=str(item.get("content", "")))
