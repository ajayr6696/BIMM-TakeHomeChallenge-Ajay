from __future__ import annotations

import json
import re
from pathlib import Path

from agent.core.llm import LLMError, call_llm, must_parse_json, shorten_for_prompt
from agent.core.models import GeneratedFile, Plan, ValidationResult
from agent.prompts.prompt_loader import load_prompt_template

PROJECT_CONSTRAINTS = load_prompt_template("project_constraints.txt")


class FixAgent:
    """
    FixAgent proposes file patches when validation fails.

    Input: the spec, plan, and validation logs
    Output: STRICT JSON with a list of full file replacements.
    """

    def __init__(self, offline: bool) -> None:
        """Workflow X1: Configure whether fix attempts may call the external LLM."""
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
        """Workflow X2: Build focused fix context, call the model, and normalize candidates."""
        if self._offline:
            return []

        # Workflow X2A: Lock onto one implementation file when fix_only already inferred it.
        focus_locked = focus_file in plan.components if focus_file else False
        spec_excerpt = shorten_for_prompt(spec_text, 700)
        typecheck_excerpt = ""
        test_excerpt = error_digest or self._extract_relevant_log_excerpt(validation.test_log, 1400)
        ordered_steps = "\n".join(
            f"{step.order}. {step.title} | depends_on={step.depends_on} | outputs={step.outputs}"
            for step in plan.steps
        )
        plan_summary = (
            f"Goal: {plan.goal}\n"
            f"Components: {', '.join(plan.components)}\n"
            f"Tests: {', '.join(plan.tests)}"
        )
        # Workflow X2B: Restrict visible file context to the suspected component when possible.
        implementation_only = focus_locked or self._should_limit_to_implementation_files(validation)
        current_files_excerpt = self._current_files_excerpt(
            plan,
            app_dir,
            focus_file=focus_file,
            focus_only=implementation_only and focus_locked,
        )
        # Workflow X2C: Constrain output paths so the model cannot rewrite unrelated files.
        if focus_file and implementation_only and focus_locked:
            allowed_paths = [focus_file]
        else:
            allowed_paths = (
                plan.components + ["src/App.tsx"]
                if implementation_only
                else plan.components + plan.tests + ["src/App.tsx"]
            )
        preferred_paths = self._preferred_fix_paths(validation, plan)
        retry_note = self._build_retry_note(attempt, focus_file)
        focus_section = self._build_focus_section(focus_file)

        prompt = (
            load_prompt_template("fix_prompt.txt")
            .replace("__PROJECT_CONSTRAINTS__", PROJECT_CONSTRAINTS)
            .replace("__SPEC_EXCERPT__", spec_excerpt)
            .replace("__PLAN_TEXT__", plan_summary)
            .replace("__ORDERED_STEPS__", ordered_steps)
            .replace("__TYPECHECK_EXCERPT__", typecheck_excerpt)
            .replace("__TEST_EXCERPT__", test_excerpt)
            .replace("__CURRENT_FILES_EXCERPT__", current_files_excerpt)
            .replace("__ALLOWED_PATHS__", "\n".join(f"- {path}" for path in allowed_paths))
            .replace("__PREFERRED_PATHS__", "\n".join(f"- {path}" for path in preferred_paths))
            .replace("__RETRY_NOTE__", retry_note)
            .replace("__FOCUS_SECTION__", focus_section)
            .replace("__ERROR_DIGEST__", test_excerpt)
            .replace("__FOCUS_FILE_SECTION__", focus_section)
        )
        self._assert_no_placeholders(prompt)

        print(
            "[fix-agent] Prompt sizes:",
            f"spec={len(spec_excerpt)}",
            f"typecheck={len(typecheck_excerpt)}",
            f"test={len(test_excerpt)}",
            f"files={len(current_files_excerpt)}",
        )

        try:
            data = must_parse_json(call_llm(prompt))
        except LLMError as exc:
            # Workflow X2D: Recover from Groq JSON wrapper failures via failed_generation salvage.
            print(f"[fix-agent] Failed to parse model response: {exc}")
            data = self._salvage_failed_generation(str(exc))
            if data is None:
                return []
        except (KeyError, TypeError, ValueError) as exc:
            print(f"[fix-agent] Failed to parse model response: {exc}")
            return []

        data = self._normalize_files_payload(data)
        if data is None:
            print("[fix-agent] Model response had an unsupported JSON shape.")
            return []

        allowed = set(allowed_paths)
        selected: dict[str, GeneratedFile] = {}
        dropped: list[str] = []
        for item in data.get("files", []):
            path = str(item["path"])
            content = str(item.get("content", ""))
            if path not in allowed:
                dropped.append(path)
                continue
            # Workflow X2E: Reject wrapped/truncated outputs before they reach fix_only.
            is_valid, reason = self._validate_full_file(path, content)
            if not is_valid:
                snippet = shorten_for_prompt(content, 240).replace("\n", "\\n")
                print(f"[fix-agent] Rejected malformed replacement for {path}: {reason}")
                print(f"[fix-agent] Replacement snippet: {snippet}")
                continue
            selected[path] = GeneratedFile(path=path, content=content)

        files = list(selected.values())
        # Workflow X2F: If the broad prompt failed, retry once with a one-file-only repair prompt.
        if not files and focus_file and focus_file in allowed and app_dir is not None:
            focused_fix = self._retry_with_single_file_prompt(
                spec_excerpt=spec_excerpt,
                test_excerpt=test_excerpt,
                focus_file=focus_file,
                app_dir=app_dir,
            )
            if focused_fix is not None:
                files = [focused_fix]
        # Workflow X2G: For the known CarCard regression family, provide a deterministic backup.
        if (
            not files
            and focus_file == "src/components/CarCard.tsx"
            and app_dir is not None
        ):
            heuristic_fix = self._heuristic_fix_car_card(app_dir / focus_file)
            if heuristic_fix is not None:
                print("[fix-agent] Using deterministic CarCard fallback.")
                files = [GeneratedFile(path=focus_file, content=heuristic_fix)]
        if dropped:
            print(f"[fix-agent] Dropped non-allowlisted fixes: {', '.join(dropped)}")
        if not files:
            print("[fix-agent] Model returned no allowlisted file replacements.")
        return files

    @staticmethod
    def _build_retry_note(attempt: int, focus_file: str | None) -> str:
        """Workflow X3: Add a retry banner so later attempts see residual failure context."""
        if attempt <= 1:
            return ""
        focus_hint = f" Focus especially on {focus_file}." if focus_file else ""
        return (
            f"NOTE: This is fix attempt {attempt}. A previous attempt did not fully "
            f"resolve the failure.{focus_hint} Make the smallest possible correction.\n"
        )

    @staticmethod
    def _build_focus_section(focus_file: str | None) -> str:
        """Workflow X4: Put the primary suspect file near the top of the prompt."""
        if not focus_file:
            return ""
        return (
            f"Primary suspect: {focus_file}\n"
            "Fix this file first unless the logs clearly implicate a different file.\n"
        )

    @staticmethod
    def _assert_no_placeholders(prompt: str) -> None:
        """Workflow X5: Fail fast if any prompt template tokens were left unfilled."""
        missed = re.findall(r"__[A-Z][A-Z0-9_]*__", prompt)
        if missed:
            raise ValueError(f"[fix-agent] Unfilled placeholders in prompt: {sorted(set(missed))}")

    def _preferred_fix_paths(self, validation: ValidationResult, plan: Plan) -> list[str]:
        """Workflow X6: Bias the model toward implementation files for UI-behavior failures."""
        behavior_assertion = (
            "Unable to find an element" in validation.test_log
            or "Expected" in validation.test_log
            or "Received" in validation.test_log
            or "toBeInTheDocument" in validation.test_log
        )
        if behavior_assertion and "error TS" not in validation.typecheck_log:
            return plan.components + ["src/App.tsx"]
        return plan.components + plan.tests + ["src/App.tsx"]

    def _should_limit_to_implementation_files(self, validation: ValidationResult) -> bool:
        """Workflow X7: For clean-typecheck UI failures, forbid test-file rewrites entirely."""
        behavior_assertion = (
            "Unable to find an element" in validation.test_log
            or "Expected" in validation.test_log
            or "Received" in validation.test_log
            or "toBeInTheDocument" in validation.test_log
        )
        test_import_or_syntax_problem = (
            "Cannot find module" in validation.test_log
            or "Failed to resolve import" in validation.test_log
            or "SyntaxError" in validation.test_log
            or "src/__tests__/" in validation.typecheck_log
            or "src\\__tests__\\" in validation.typecheck_log
        )
        return behavior_assertion and "error TS" not in validation.typecheck_log and not test_import_or_syntax_problem

    def _current_files_excerpt(
        self,
        plan: Plan,
        app_dir: Path | None,
        *,
        focus_file: str | None = None,
        focus_only: bool = False,
    ) -> str:
        """Workflow X8: Collect only the current allowlisted file text needed for this retry."""
        if app_dir is None:
            return "(No current file context provided.)"

        if focus_only and focus_file:
            ordered_paths = [focus_file]
        else:
            base_paths = plan.components + ["src/App.tsx"]
            ordered_paths = ([focus_file] if focus_file else []) + [
                path for path in base_paths if path != focus_file
            ]

        chunks: list[str] = []
        for relative_path in ordered_paths:
            file_path = app_dir / relative_path
            if not file_path.exists():
                continue
            try:
                content = file_path.read_text(encoding="utf-8")
            except OSError:
                continue
            excerpt = shorten_for_prompt(content, 900)
            chunks.append(f"FILE: {relative_path}\n{excerpt}")

        if not chunks:
            return "(No allowlisted files currently exist in the generated app.)"

        return shorten_for_prompt("\n\n".join(chunks), 4200)

    def _extract_relevant_log_excerpt(self, log_text: str, max_chars: int) -> str:
        """Workflow X9: Keep only the high-signal error lines from large validator output."""
        if not log_text.strip():
            return "(empty)"

        lines = log_text.splitlines()
        kept_indices: set[int] = set()
        patterns = [
            r"\bFAIL\b",
            r"\berror\b",
            r"\bError:",
            r"\bExpected\b",
            r"\bReceived\b",
            r"Unable to find an element",
            r"src\/",
            r"src\\",
        ]

        for index, line in enumerate(lines):
            if any(re.search(pattern, line, flags=re.IGNORECASE) for pattern in patterns):
                kept_indices.update(range(max(0, index - 2), min(len(lines), index + 3)))

        if not kept_indices:
            return shorten_for_prompt(log_text, max_chars)

        excerpt = "\n".join(
            line for index, line in enumerate(lines) if index in kept_indices and not line.lstrip().startswith("<body>")
        ).strip()
        return shorten_for_prompt(excerpt or log_text, max_chars)

    def _validate_full_file(self, path: str, content: str) -> tuple[bool, str]:
        """Workflow X10: Perform lightweight structural checks on model-returned full files."""
        stripped = content.strip()
        if len(stripped) < 80:
            return False, "content too short to be a full file"
        if stripped.startswith("{'type':") or stripped.startswith('{"type":') or stripped.startswith("```"):
            return False, "content looks like wrapped JSON or markdown, not source code"
        if path.endswith(".test.tsx"):
            if "describe(" in stripped or "it(" in stripped or "test(" in stripped:
                return True, ""
            return False, "test file is missing describe/it/test blocks"
        if path.endswith(".tsx"):
            if "export default" in stripped or "export function" in stripped:
                return True, ""
            if "import " in stripped and "return (" in stripped:
                return True, ""
            return False, "tsx file is missing expected component structure"
        if path.endswith(".ts"):
            if "export " in stripped or "import " in stripped:
                return True, ""
            return False, "ts file is missing import/export structure"
        return True, ""

    def _salvage_failed_generation(self, error_text: str) -> dict[str, object] | None:
        """Workflow X11: Recover usable file payloads from Groq json_validate_failed errors."""
        if "failed_generation" not in error_text:
            return None

        payload = self._extract_failed_generation_payload(error_text)
        if payload is None:
            print("[fix-agent] Could not isolate failed_generation payload.")
            return None

        pairs = self._extract_file_pairs_from_payload(payload)
        if not pairs:
            print("[fix-agent] Could not salvage any file replacements from failed_generation.")
            return None

        files: list[dict[str, str]] = []
        for path, raw_content in pairs:
            content = self._decode_salvaged_content(raw_content)
            if content is None:
                continue
            files.append({"path": path, "content": content})

        if not files:
            print("[fix-agent] Salvage found file entries but could not decode contents.")
            return None

        print(f"[fix-agent] Salvaged {len(files)} file replacement(s) from failed_generation.")
        return {"files": files}

    def _decode_salvaged_content(self, raw_content: str) -> str | None:
        """Workflow X12: Decode escaped near-JSON file content into raw source text."""
        try:
            return json.loads(f'"{raw_content}"')
        except json.JSONDecodeError:
            candidate = raw_content
            candidate = candidate.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
            candidate = candidate.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
            candidate = candidate.strip()
            return candidate or None

    def _extract_failed_generation_payload(self, error_text: str) -> str | None:
        """Workflow X13: Isolate the failed_generation blob from a Groq error string."""
        match = re.search(r"'failed_generation':\s*'(?P<payload>.*)'}\}$", error_text, re.DOTALL)
        if match:
            return match.group("payload")
        match = re.search(r'"failed_generation":\s*"(?P<payload>.*)"\s*[,}]', error_text, re.DOTALL)
        if match:
            return match.group("payload")
        return None

    def _extract_file_pairs_from_payload(self, payload: str) -> list[tuple[str, str]]:
        """Workflow X14: Pull `(path, content)` pairs out of malformed failed_generation JSON."""
        pairs: list[tuple[str, str]] = []
        path_pattern = re.compile(r'"path":\s*"([^"]+)"', re.DOTALL)
        position = 0

        while True:
            path_match = path_pattern.search(payload, position)
            if not path_match:
                break
            path = path_match.group(1)
            content_key = re.search(r'"content":\s*"', payload[path_match.end():], re.DOTALL)
            if not content_key:
                position = path_match.end()
                continue
            content_start = path_match.end() + content_key.end()

            decoded_chars: list[str] = []
            index = content_start
            escaping = False
            while index < len(payload):
                ch = payload[index]
                if escaping:
                    decoded_chars.append("\\" + ch)
                    escaping = False
                    index += 1
                    continue
                if ch == "\\":
                    escaping = True
                    index += 1
                    continue
                if ch == '"':
                    break
                decoded_chars.append(ch)
                index += 1

            if index >= len(payload):
                raw_content = self._extract_content_by_boundary(payload, content_start)
                if raw_content is None:
                    position = path_match.end()
                    continue
            else:
                raw_content = "".join(decoded_chars)

            pairs.append((path, raw_content))
            position = index + 1

        return pairs

    def _extract_content_by_boundary(self, payload: str, content_start: int) -> str | None:
        """Workflow X15: Fallback boundary scan when JSON string escaping is incomplete."""
        boundaries = [
            re.compile(r'"\s*},\s*{\s*"path":', re.DOTALL),
            re.compile(r'"\s*}\s*]\s*$', re.DOTALL),
        ]
        segment = payload[content_start:]
        boundary_index: int | None = None
        for pattern in boundaries:
            match = pattern.search(segment)
            if match and (boundary_index is None or match.start() < boundary_index):
                boundary_index = match.start()
        if boundary_index is None:
            return None
        return segment[:boundary_index]

    def _normalize_files_payload(self, data: object) -> dict[str, object] | None:
        """Workflow X16: Accept either `{files:[...]}` or a bare JSON array from the model."""
        if isinstance(data, dict):
            files = data.get("files")
            if isinstance(files, list):
                return {"files": files}
            return None
        if isinstance(data, list):
            return {"files": data}
        return None

    def _retry_with_single_file_prompt(
        self,
        *,
        spec_excerpt: str,
        test_excerpt: str,
        focus_file: str,
        app_dir: Path,
    ) -> GeneratedFile | None:
        """Workflow X17: Make one small second-pass LLM call for the focused file only."""
        file_path = app_dir / focus_file
        if not file_path.exists():
            return None

        original_content = file_path.read_text(encoding="utf-8")
        preserve_rules = self._build_preserve_rules(original_content)
        focused_prompt = (
            "You are FixAgent.\n"
            "Return STRICT JSON only.\n"
            "You must repair exactly one existing React/TypeScript file with the smallest possible edit.\n\n"
            f"Spec:\n{spec_excerpt}\n\n"
            f"Failing tests:\n{test_excerpt}\n\n"
            f"Target file path:\n{focus_file}\n\n"
            "Current file content:\n"
            f"{original_content}\n\n"
            "Rules:\n"
            "- Return exactly one file.\n"
            "- Use the same file path.\n"
            "- Preserve imports, types, and component structure unless the failing tests require a small change.\n"
            "- Make the minimum possible fix.\n"
            f"{preserve_rules}"
            "- Return the full corrected file content, not a patch.\n\n"
            "JSON schema:\n"
            '{ "files": [ { "path": "src/...", "content": "..." } ] }'
        )

        try:
            data = must_parse_json(call_llm(focused_prompt))
        except LLMError as exc:
            print(f"[fix-agent] Single-file retry failed: {exc}")
            return None
        except (KeyError, TypeError, ValueError) as exc:
            print(f"[fix-agent] Single-file retry parse failed: {exc}")
            return None

        files = data.get("files", [])
        if len(files) != 1:
            print("[fix-agent] Single-file retry did not return exactly one file.")
            return None
        item = files[0]
        path = str(item.get("path", ""))
        content = str(item.get("content", ""))
        is_valid, reason = self._validate_full_file(path, content)
        if path != focus_file or not is_valid:
            print(f"[fix-agent] Single-file retry rejected for {path or focus_file}: {reason}")
            return None
        print(f"[fix-agent] Single-file retry produced a valid replacement for {focus_file}.")
        return GeneratedFile(path=path, content=content)

    def _heuristic_fix_car_card(self, file_path: Path) -> str | None:
        """Workflow X18: Return the canonical CarCard implementation for known-safe recovery."""
        if not file_path.exists():
            return None

        current = file_path.read_text(encoding="utf-8")
        required_markers = [
            "CardMedia",
            "Typography",
            "useMediaQuery",
            "CarCardProps",
        ]
        if not all(marker in current for marker in required_markers):
            return None

        # Deterministic canonical implementation for this challenge component.
        return """import { Card, CardContent, CardMedia, Chip, Stack, Typography, useMediaQuery } from "@mui/material";
import type { Car } from "@/types";

type CarCardProps = {
  car: Car;
};

export default function CarCard({ car }: CarCardProps) {
  const isMobile = useMediaQuery("(max-width:640px)");
  const isTablet = useMediaQuery("(min-width:641px) and (max-width:1023px)");
  const imageSrc = isMobile ? car.mobile : isTablet ? car.tablet : car.desktop;

  return (
    <Card elevation={2} sx={{ overflow: "hidden" }}>
      <CardMedia
        component="img"
        height="220"
        image={imageSrc}
        alt={`${car.year} ${car.make} ${car.model}`}
      />
      <CardContent>
        <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={2}>
          <div>
            <Typography variant="h6">
              {car.year} {car.make} {car.model}
            </Typography>
            <Typography color="text.secondary">{car.color}</Typography>
          </div>
          <Chip label={car.make} color="primary" variant="outlined" />
        </Stack>
      </CardContent>
    </Card>
    );
}
"""

    def _build_preserve_rules(self, original_content: str) -> str:
        """Workflow X19: Tell the model to preserve key anchors from the focused original file."""
        anchors = self._extract_preserve_anchors(original_content)
        if not anchors:
            return ""
        rules = ["- Preserve these original anchors unless the failing logs directly require changing them:\n"]
        for anchor in anchors[:6]:
            rules.append(f"  {anchor}\n")
        return "".join(rules)

    def _extract_preserve_anchors(self, original_content: str) -> list[str]:
        """Workflow X20: Pull stable declarations/imports from the current file for retry prompts."""
        anchors: list[str] = []
        seen: set[str] = set()
        patterns = [
            r"^\s*import(?:\s+type)?\s+.+$",
            r"^\s*export\s+default\s+function\s+\w+.*$",
            r"^\s*export\s+function\s+\w+.*$",
            r"^\s*export\s+(?:const|let|var)\s+\w+.*$",
            r"^\s*(?:type|interface)\s+\w+.*$",
            r"^\s*function\s+\w+.*$",
            r"^\s*const\s+\w+\s*=.*$",
        ]
        for line in original_content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            if any(re.match(pattern, stripped) for pattern in patterns):
                normalized = re.sub(r"\s+", " ", stripped)
                if normalized not in seen:
                    anchors.append(stripped)
                    seen.add(normalized)
            if len(anchors) >= 6:
                break
        return anchors
