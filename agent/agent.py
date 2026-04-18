"""
CLI entrypoint for the multi-agent React app generator.

Usage:
  python agent/agent.py --spec spec.txt --input ./Fullstack-Coding-Challenge-main --output ./generated-app
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
# When executed as `python agent/agent.py`, Python puts `agent/` on sys.path which
# breaks importing the `agent` package (it resolves to `agent.py` instead).
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agent.core.orchestrator import Orchestrator  # noqa: E402


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Workflow 1: Parse the CLI inputs that drive a generation run."""
    parser = argparse.ArgumentParser(description="Generate a React app from a spec.")
    parser.add_argument("--spec", required=True, help="Path to spec text file.")
    parser.add_argument(
        "--input",
        required=True,
        help="Path to provided React boilerplate (read-only input).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to generated output app directory.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Max self-heal retries after validation failures (default: 2).",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run without external LLM calls (deterministic local generation).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Workflow 2: Validate paths, build the orchestrator, and launch the run."""
    # Avoid generating __pycache__/pyc files that can dirty the git working tree.
    os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
    started_at = time.perf_counter()

    args = _parse_args(sys.argv[1:] if argv is None else argv)

    spec_path = Path(args.spec).resolve()
    input_dir = Path(args.input).resolve()
    output_dir = Path(args.output).resolve()

    if not spec_path.exists():
        raise FileNotFoundError(f"Spec file not found: {spec_path}")
    if not input_dir.exists():
        raise FileNotFoundError(f"Input project not found: {input_dir}")

    orchestrator = Orchestrator(
        repo_root=Path.cwd().resolve(),
        spec_path=spec_path,
        input_dir=input_dir,
        output_dir=output_dir,
        max_retries=args.max_retries,
        offline=args.offline or os.getenv("AGENT_OFFLINE_MODE", "").strip() == "1",
    )
    orchestrator.run()
    elapsed = time.perf_counter() - started_at
    print(f"[agent] Total run time: {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

