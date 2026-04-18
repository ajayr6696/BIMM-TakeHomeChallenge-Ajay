"""
Run FixAgent directly against an existing generated app.

Usage:
  python agent/fix_only.py --spec spec.txt --output ./generated-app
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.core.fix_agent import FixAgent  # noqa: E402
from agent.core.planner_agent import PlannerAgent  # noqa: E402
from agent.core.validator_agent import ValidatorAgent  # noqa: E402


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Workflow F1: Parse CLI arguments for a direct fix-only run."""
    parser = argparse.ArgumentParser(description="Run FixAgent on an existing generated app.")
    parser.add_argument("--spec", required=True, help="Path to spec text file.")
    parser.add_argument("--output", required=True, help="Path to the generated output app.")
    parser.add_argument("--offline", action="store_true", help="Run without external LLM calls.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Workflow F2: Validate the current app once and ask FixAgent for direct repairs."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    spec_path = Path(args.spec).resolve()
    output_dir = Path(args.output).resolve()

    spec_text = spec_path.read_text(encoding="utf-8")
    offline = args.offline or os.getenv("AGENT_OFFLINE_MODE", "").strip() == "1"

    planner = PlannerAgent(offline=True)
    validator = ValidatorAgent()
    fixer = FixAgent(offline=offline)

    plan = planner.plan(spec_text)
    validation = validator.validate(output_dir)
    if validation.ok:
        print("[fix-only] Validation already passed. Nothing to fix.")
        return 0

    fixes = fixer.fix(spec_text, plan, validation, output_dir)
    if not fixes:
        print("[fix-only] FixAgent returned no fixes.")
        return 1

    print("[fix-only] Proposed fixes:")
    for generated_file in fixes:
        print(f"[fix-only]   - {generated_file.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
