from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanStep:
    """One ordered implementation step in the planner output."""

    order: int
    title: str
    depends_on: list[int]
    outputs: list[str]


@dataclass(frozen=True)
class Plan:
    """Structured plan produced by PlannerAgent."""

    goal: str
    steps: list[PlanStep]
    components: list[str]
    tests: list[str]


@dataclass(frozen=True)
class GeneratedFile:
    """A file to be written into the generated React app."""

    path: str
    content: str


@dataclass(frozen=True)
class ValidationResult:
    """Result of validating the generated app."""

    ok: bool
    npm_install_log: str
    typecheck_log: str
    test_log: str


@dataclass(frozen=True)
class ValidationStepResult:
    """Result of a single validation command."""

    name: str
    command: str
    exit_code: int
    log: str

