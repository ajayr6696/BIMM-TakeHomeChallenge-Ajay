from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from agent.core.code_agent import CodeAgent
from agent.core.fix_agent import FixAgent
from agent.core.fs import FileSystem
from agent.core.models import GeneratedFile
from agent.core.planner_agent import PlannerAgent
from agent.core.validator_agent import ValidatorAgent


@dataclass(frozen=True)
class OrchestratorConfig:
    """Runtime configuration for a full agent run."""

    repo_root: Path
    spec_path: Path
    input_dir: Path
    output_dir: Path
    max_retries: int
    offline: bool


class Orchestrator:
    """
    Orchestrator runs the strict workflow:

    Spec -> Plan -> Generate -> Write -> Validate -> Fix -> Retry
    """

    def __init__(
        self,
        repo_root: Path,
        spec_path: Path,
        input_dir: Path,
        output_dir: Path,
        max_retries: int,
        offline: bool,
    ) -> None:
        """Workflow 2A: Wire together the planner, generator, validator, fixer, and FS tools."""
        self._cfg = OrchestratorConfig(
            repo_root=repo_root,
            spec_path=spec_path,
            input_dir=input_dir,
            output_dir=output_dir,
            max_retries=max_retries,
            offline=offline,
        )

        self._fs = FileSystem()
        self._planner = PlannerAgent(offline=offline)
        self._coder = CodeAgent(offline=offline)
        self._validator = ValidatorAgent()
        self._fixer = FixAgent(offline=offline)

    def run(self) -> None:
        """Workflow 2B: Execute the full plan -> generate -> validate -> retry loop."""
        spec_text = self._cfg.spec_path.read_text(encoding="utf-8")
        print(f"[agent] Loaded spec: {self._cfg.spec_path}")

        plan = self._planner.plan(spec_text)
        print(f"[agent] Plan goal: {plan.goal}")
        print("[agent] Ordered plan steps:")
        for step in plan.steps:
            deps = ", ".join(str(dep) for dep in step.depends_on) or "none"
            outputs = ", ".join(step.outputs)
            print(f"[agent]   {step.order}. {step.title} (depends on: {deps}; outputs: {outputs})")
        for path in plan.components + plan.tests:
            print(f"[agent] Planned file: {path}")

        files = self._coder.generate(spec_text, plan)
        self._print_test_checklist(files)

        self._fs.copy_input_to_output(self._cfg.input_dir, self._cfg.output_dir)
        self._write_files(self._cfg.output_dir, files)
        self._prune_forbidden_generated_files(self._cfg.output_dir)
        print(f"[agent] Wrote {len(files)} generated files to {self._cfg.output_dir}")

        validation = self._validator.validate(self._cfg.output_dir)

        retries = 0
        while not validation.ok and retries < self._cfg.max_retries:
            retries += 1
            print(f"[agent] Retry {retries}/{self._cfg.max_retries}")
            fixes = self._fixer.fix(spec_text, plan, validation, self._cfg.output_dir)
            if not fixes:
                print("[agent] No fixes returned; stopping retry loop.")
                break
            self._write_files(self._cfg.output_dir, fixes)
            self._prune_forbidden_generated_files(self._cfg.output_dir)
            validation = self._validator.validate(self._cfg.output_dir)

        if validation.ok:
            print("[agent] Validation passed.")
            return

        raise RuntimeError(
            "Validation failed after retries.\n\n"
            f"TYPECHECK LOG:\n{validation.typecheck_log}\n\n"
            f"TEST LOG:\n{validation.test_log}\n"
        )

    def _write_files(self, output_dir: Path, files: list[GeneratedFile]) -> None:
        """Workflow 4B: Persist each generated or fixed file into the output app."""
        for generated_file in files:
            self._fs.write_text(output_dir / generated_file.path, generated_file.content)

    def _prune_forbidden_generated_files(self, output_dir: Path) -> None:
        """Workflow 4C: Reserved hook for output cleanup while keeping the current flow no-op."""
        # Keep the generated app aligned with the current plan allowlist.
        # No blanket pruning is needed here because the input boilerplate is copied
        # fresh on every run and generated files are explicitly controlled.
        return

    def _print_test_checklist(self, files: list[GeneratedFile]) -> None:
        """Workflow 2C: Print the planned test cases before validation starts."""
        test_names: list[str] = []
        for generated_file in files:
            if not generated_file.path.endswith(".test.tsx"):
                continue
            test_names.extend(re.findall(r'\bit\("([^"]+)"', generated_file.content))

        if not test_names:
            return

        print("[agent] Planned test checklist:")
        for index, test_name in enumerate(test_names, start=1):
            print(f"[agent]   {index}. {test_name}")
