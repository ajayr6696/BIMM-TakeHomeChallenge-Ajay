"""
Run FixAgent directly against an existing generated app.

Usage:
  python agent/fix_only.py --spec spec.txt --output ./generated-app
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.core.fix_agent import FixAgent  # noqa: E402
from agent.core.fs import FileSystem  # noqa: E402
from agent.core.planner_agent import PlannerAgent  # noqa: E402
from agent.core.validator_agent import ValidatorAgent  # noqa: E402

MAX_RETRIES = 3


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Workflow F1: Parse CLI arguments for a direct fix-only run."""
    parser = argparse.ArgumentParser(description="Run FixAgent on an existing generated app.")
    parser.add_argument("--spec", required=True, help="Path to spec text file.")
    parser.add_argument("--output", required=True, help="Path to the generated output app.")
    parser.add_argument("--offline", action="store_true", help="Run without external LLM calls.")
    parser.add_argument("--dry-run", action="store_true", help="Print returned fixes without writing files.")
    parser.add_argument(
        "--max-retries",
        type=int,
        default=MAX_RETRIES,
        help=f"Maximum fix attempts before giving up (default: {MAX_RETRIES}).",
    )
    return parser.parse_args(argv)


def _extract_error_digest(typecheck_log: str, test_log: str) -> str:
    """Workflow F2: Trim validator logs down to the most useful failure lines."""
    lines = (typecheck_log + "\n" + test_log).splitlines()
    kept = [
        line
        for line in lines
        if "FAIL" in line or "error" in line.lower() or "Unable to find an element" in line
    ]
    return "\n".join(kept[:40]) if kept else "\n".join(lines[-40:])


def main(argv: list[str] | None = None) -> int:
    """Workflow F3: Retry focused repairs and roll back failed attempts."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    spec_path = Path(args.spec).resolve()
    output_dir = Path(args.output).resolve()

    spec_text = spec_path.read_text(encoding="utf-8")
    offline = args.offline or os.getenv("AGENT_OFFLINE_MODE", "").strip() == "1"

    planner = PlannerAgent(offline=True)
    validator = ValidatorAgent()
    fixer = FixAgent(offline=offline)
    fs = FileSystem()

    plan = planner.plan(spec_text)
    validation = validator.validate(output_dir)
    if validation.ok:
        print("[fix-only] Validation already passed. Nothing to fix.")
        return 0

    for attempt in range(1, args.max_retries + 1):
        error_digest = _extract_error_digest(validation.typecheck_log, validation.test_log)
        focus_file = None
        matches = re.findall(r"\b(src/[\w/.-]+\.(?:tsx?|jsx?))\b", error_digest)
        if matches:
            focus_file = matches[0]

        fixes = fixer.fix(
            spec_text,
            plan,
            validation,
            output_dir,
            error_digest=error_digest,
            focus_file=focus_file,
            attempt=attempt,
        )
        if not fixes:
            print("[fix-only] FixAgent returned no fixes.")
            return 1

        print("[fix-only] Proposed fixes:")
        for generated_file in fixes:
            print(f"[fix-only]   - {generated_file.path}")
        if args.dry_run:
            return 0

        backups: dict[str, str] = {}
        for generated_file in fixes:
            target_path = output_dir / generated_file.path
            if target_path.exists():
                backups[generated_file.path] = target_path.read_text(encoding="utf-8")
            fs.write_text(target_path, generated_file.content)

        post_validation = validator.validate(output_dir)
        if post_validation.ok:
            print("[fix-only] Validation passed after fixes.")
            return 0

        for path, content in backups.items():
            fs.write_text(output_dir / path, content)
        validation = post_validation

    print("[fix-only] Exiting with failure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
