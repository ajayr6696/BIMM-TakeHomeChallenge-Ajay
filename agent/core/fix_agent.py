from __future__ import annotations

import json
import re
from collections import Counter
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
        """Workflow X1: Record whether this fixer may call the external LLM service."""
        self._offline = offline

    def infer_focus_file(self, validation: ValidationResult, plan: Plan, app_dir: Path | None = None) -> str | None:
        """Workflow X1A: Pick the most likely broken implementation file from the latest failures.

        The inference stays generic:
        - first prefer direct file-path mentions from the validator logs
        - then score candidate component files by filename matches
        - finally boost files whose current contents look like they render the
          failing text/image assertions
        """
        candidate_paths = list(dict.fromkeys(plan.components + ["src/App.tsx"]))
        raw = f"{validation.typecheck_log}\n{validation.test_log}"
        lowered = raw.lower()
        matches = re.findall(r"\b(src/[\w/.-]+\.(?:tsx?|jsx?))\b", raw)
        if matches:
            normalized_candidates = set(candidate_paths)
            non_test_matches = [
                match for match in matches if "/__tests__/" not in match and match in normalized_candidates
            ]
            target_matches = non_test_matches or [match for match in matches if match in normalized_candidates]
            if target_matches:
                return Counter(target_matches).most_common(1)[0][0]

        scored: list[tuple[int, str]] = []
        for path in candidate_paths:
            stem = Path(path).stem
            score = 0
            if path.lower() in lowered:
                score += 12
            if stem.lower() in lowered:
                score += 8

            tokens = self._camel_tokens(stem)
            if tokens and all(token in lowered for token in tokens):
                score += 5
            score += sum(1 for token in tokens if token in lowered)

            parent = Path(path).parent.name.lower()
            if parent and parent in lowered:
                score += 1

            score += self._score_candidate_file_contents(path, app_dir, lowered)

            if score > 0:
                scored.append((score, path))

        if not scored:
            return None

        scored.sort(key=lambda item: (-item[0], candidate_paths.index(item[1])))
        return scored[0][1]

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
        """Workflow X2: Produce safe full-file repair candidates for the current validation failure.

        This method is the shared repair entrypoint used by both the full
        orchestrator flow and the standalone fix-only runner.
        """
        if self._offline:
            return []

        if focus_file is None:
            focus_file = self.infer_focus_file(validation, plan, app_dir)

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
        malformed_items = 0
        files: list[GeneratedFile] = []
        # Workflow X2E: When a single focused implementation file is known, prefer the
        # tighter one-file repair prompt before trusting a broad multi-file answer.
        if focus_file and focus_file in allowed and app_dir is not None and focus_locked:
            focused_fix = self._retry_with_single_file_prompt(
                spec_excerpt=spec_excerpt,
                test_excerpt=test_excerpt,
                focus_file=focus_file,
                app_dir=app_dir,
            )
            if focused_fix is not None:
                files = [focused_fix]
        if not files:
            for item in data.get("files", []):
                if not isinstance(item, dict):
                    malformed_items += 1
                    continue
                raw_path = item.get("path")
                if not raw_path:
                    malformed_items += 1
                    continue
                path = str(raw_path)
                content = str(item.get("content", ""))
                if path not in allowed:
                    dropped.append(path)
                    continue
                is_valid, reason = self._validate_full_file(path, content)
                if not is_valid:
                    snippet = shorten_for_prompt(content, 240).replace("\n", "\\n")
                    print(f"[fix-agent] Rejected malformed replacement for {path}: {reason}")
                    print(f"[fix-agent] Replacement snippet: {snippet}")
                    continue
                selected[path] = GeneratedFile(path=path, content=content)
            files = list(selected.values())

        # Workflow X2F: If the broad path also failed, retry once with a one-file-only repair prompt.
        if not files and focus_file and focus_file in allowed and app_dir is not None:
            focused_fix = self._retry_with_single_file_prompt(
                spec_excerpt=spec_excerpt,
                test_excerpt=test_excerpt,
                focus_file=focus_file,
                app_dir=app_dir,
            )
            if focused_fix is not None:
                files = [focused_fix]
        if dropped:
            print(f"[fix-agent] Dropped non-allowlisted fixes: {', '.join(dropped)}")
        if malformed_items:
            print(f"[fix-agent] Dropped malformed file entries: {malformed_items}")
        if not files:
            print("[fix-agent] Model returned no allowlisted file replacements.")
        return files

    @staticmethod
    def _build_retry_note(attempt: int, focus_file: str | None) -> str:
        """Workflow X3: Add retry context so later attempts understand prior failures."""
        if attempt <= 1:
            return ""
        focus_hint = f" Focus especially on {focus_file}." if focus_file else ""
        return (
            f"NOTE: This is fix attempt {attempt}. A previous attempt did not fully "
            f"resolve the failure.{focus_hint} Make the smallest possible correction.\n"
        )

    @staticmethod
    def _build_focus_section(focus_file: str | None) -> str:
        """Workflow X4: Put the inferred suspect file near the top of the prompt."""
        if not focus_file:
            return ""
        return (
            f"Primary suspect: {focus_file}\n"
            "Fix this file first unless the logs clearly implicate a different file.\n"
        )

    @staticmethod
    def _camel_tokens(value: str) -> list[str]:
        """Workflow X4A: Split a filename stem into lower-cased tokens for heuristic scoring."""
        parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+", value)
        return [part.lower() for part in parts if part]

    @staticmethod
    def _score_candidate_file_contents(path: str, app_dir: Path | None, lowered_log: str) -> int:
        """Workflow X4B: Use current file contents to prefer the component rendering the broken UI.

        This helps leaf UI components win over container pages when the failure is
        about missing text or alt text in the rendered output.
        """
        if app_dir is None:
            return 0

        file_path = app_dir / path
        if not file_path.exists():
            return 0
        try:
            content = file_path.read_text(encoding="utf-8").lower()
        except OSError:
            return 0

        score = 0
        text_or_alt_failure = (
            "unable to find an element with the text:" in lowered_log
            or "unable to find an element with the alt text:" in lowered_log
        )
        if text_or_alt_failure:
            # Prefer leaf components that actually render text/image fields over container pages.
            render_field_hits = re.findall(
                r"\b\w+\.(year|make|model|title|name|label|image|src|alt|mobile|tablet|desktop)\b",
                content,
            )
            score += min(len(render_field_hits), 10)
            if "alt={" in content or 'alt={`${' in content:
                score += 4
            if "cardmedia" in content or 'component="img"' in content or "<img" in content:
                score += 3
            if "typography" in content or "return (" in content:
                score += 2
        return score

    @staticmethod
    def _assert_no_placeholders(prompt: str) -> None:
        """Workflow X5: Fail fast if any prompt-template placeholders were left unfilled."""
        missed = re.findall(r"__[A-Z][A-Z0-9_]*__", prompt)
        if missed:
            raise ValueError(f"[fix-agent] Unfilled placeholders in prompt: {sorted(set(missed))}")

    def _preferred_fix_paths(self, validation: ValidationResult, plan: Plan) -> list[str]:
        """Workflow X6: Bias the prompt toward implementation files for UI-behavior failures."""
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
        """Workflow X7: Decide when repair attempts should stay out of test files entirely."""
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
        """Workflow X8: Gather the current allowlisted file contents needed for this retry prompt."""
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
        """Workflow X9: Keep only the highest-signal lines from a large validator log."""
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
        """Workflow X10: Reject obviously incomplete or non-source replacements before writing."""
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
        """Workflow X11: Recover usable file payloads from malformed Groq JSON-mode failures."""
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
        """Workflow X12: Decode escaped near-JSON file content back into raw source text."""
        try:
            return json.loads(f'"{raw_content}"')
        except json.JSONDecodeError:
            candidate = raw_content
            candidate = candidate.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\t", "\t")
            candidate = candidate.replace('\\"', '"').replace("\\'", "'").replace("\\\\", "\\")
            candidate = candidate.strip()
            return candidate or None

    def _extract_failed_generation_payload(self, error_text: str) -> str | None:
        """Workflow X13: Isolate the `failed_generation` blob from a Groq error string."""
        match = re.search(r"'failed_generation':\s*'(?P<payload>.*)'}\}$", error_text, re.DOTALL)
        if match:
            return match.group("payload")
        match = re.search(r'"failed_generation":\s*"(?P<payload>.*)"\s*[,}]', error_text, re.DOTALL)
        if match:
            return match.group("payload")
        return None

    def _extract_file_pairs_from_payload(self, payload: str) -> list[tuple[str, str]]:
        """Workflow X14: Pull `(path, content)` pairs out of malformed `failed_generation` JSON."""
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
        """Workflow X15: Use boundary scanning when malformed JSON strings never close cleanly."""
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
        """Workflow X16: Normalize supported model payload shapes into a `{files:[...]}` dict."""
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
        """Workflow X17: Run a smaller second-pass LLM repair for one focused file only.

        This path is intentionally narrower and stronger than the broad prompt so
        small UI regressions can be repaired with less drift.
        """
        file_path = app_dir / focus_file
        if not file_path.exists():
            return None

        original_content = file_path.read_text(encoding="utf-8")
        preserve_rules = self._build_preserve_rules(original_content)
        expected_assertions = self._extract_expected_assertions(test_excerpt)
        focused_prompt = (
            "You are FixAgent.\n"
            "Return STRICT JSON only.\n"
            "You must repair exactly one existing React/TypeScript file with the smallest possible edit.\n\n"
            f"Spec:\n{spec_excerpt}\n\n"
            f"Failing tests:\n{test_excerpt}\n\n"
            f"{expected_assertions}"
            f"Target file path:\n{focus_file}\n\n"
            "Current file content:\n"
            f"{original_content}\n\n"
            "Rules:\n"
            "- Return exactly one file.\n"
            "- Use the same file path.\n"
            "- Preserve imports, types, and component structure unless the failing tests require a small change.\n"
            "- Make the minimum possible fix.\n"
            "- When the failing tests include exact expected text or alt values, repair the file so those assertions pass.\n"
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

    def _build_preserve_rules(self, original_content: str) -> str:
        """Workflow X18: Tell the model which original anchors should survive the repair."""
        anchors = self._extract_preserve_anchors(original_content)
        if not anchors:
            return ""
        rules = ["- Preserve these original anchors unless the failing logs directly require changing them:\n"]
        for anchor in anchors[:6]:
            rules.append(f"  {anchor}\n")
        return "".join(rules)

    def _extract_preserve_anchors(self, original_content: str) -> list[str]:
        """Workflow X19: Pull stable declarations/imports from the current file for retry prompts."""
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

    @staticmethod
    def _extract_expected_assertions(test_excerpt: str) -> str:
        """Workflow X20: Pull exact text/alt assertions from failures for the focused retry prompt.

        Feeding these exact expected values back into the one-file prompt helps the
        model repair small rendering regressions without guessing the intended UI.
        """
        patterns = [
            r"Unable to find an element with the text:\s*([^\n.]+)",
            r"Unable to find an element with the alt text:\s*([^\n.]+)",
        ]
        expected: list[str] = []
        seen: set[str] = set()
        for pattern in patterns:
            for match in re.findall(pattern, test_excerpt, flags=re.IGNORECASE):
                value = match.strip().strip('"').strip("'")
                if value and value not in seen:
                    expected.append(value)
                    seen.add(value)
                if len(expected) >= 5:
                    break
            if len(expected) >= 5:
                break
        if not expected:
            return ""
        lines = ["Expected assertions from the failing tests:\n"]
        for value in expected:
            lines.append(f"- {value}\n")
        lines.append("\n")
        return "".join(lines)
