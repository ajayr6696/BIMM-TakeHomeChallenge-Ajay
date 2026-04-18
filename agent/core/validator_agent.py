from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from agent.core.models import ValidationResult, ValidationStepResult


class ValidatorAgent:
    """
    ValidatorAgent runs the required validation commands in the generated app.

    Required commands:
    - npm install
    - npm run typecheck
    - npm run test
    """

    def validate(self, app_dir: Path) -> ValidationResult:
        """Workflow 5A: Run install, typecheck, and tests and return their logs."""
        started_at = time.perf_counter()
        npm = "npm.cmd" if os.name == "nt" else "npm"
        install_step = self._run(app_dir, "install", [npm, "install"])
        typecheck_step = self._run(app_dir, "typecheck", [npm, "run", "typecheck"])
        # Use a single worker to reduce Windows spawn flakiness in CI/agent runs.
        test_step = self._run(
            app_dir,
            "test",
            [npm, "run", "test", "--", "--pool=threads", "--maxWorkers=1"],
        )
        ok = (
            install_step.exit_code == 0
            and typecheck_step.exit_code == 0
            and test_step.exit_code == 0
        )
        elapsed = time.perf_counter() - started_at
        print(f"[validator] Total validation time: {elapsed:.2f}s")
        return ValidationResult(
            ok=ok,
            npm_install_log=install_step.log,
            typecheck_log=typecheck_step.log,
            test_log=test_step.log,
        )

    def _run(self, cwd: Path, name: str, args: list[str]) -> ValidationStepResult:
        """Workflow 5B: Execute one validation command with lightweight console logging."""
        command = " ".join(args)
        print(f"[validator] Running {name}: {command}")
        started_at = time.perf_counter()
        completed = subprocess.run(
            args,
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        elapsed = time.perf_counter() - started_at
        combined_log = (completed.stdout or "") + (completed.stderr or "")
        print(f"[validator] {name} exit code: {completed.returncode} ({elapsed:.2f}s)")
        return ValidationStepResult(
            name=name,
            command=command,
            exit_code=completed.returncode,
            log=combined_log,
        )

