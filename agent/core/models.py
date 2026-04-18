from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PlanStep:
    """One ordered implementation step produced by the planner."""

    order: int
    title: str
    outputs: list[str]


@dataclass(frozen=True)
class Plan:
    """Initial structured plan for the generation workflow."""

    goal: str
    steps: list[PlanStep]
    components: list[str]
    tests: list[str]
