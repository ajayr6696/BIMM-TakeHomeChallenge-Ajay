from __future__ import annotations

from agent.core.models import Plan, PlanStep


class PlannerAgent:
    """Turn the spec into a small ordered plan before implementation starts."""

    def __init__(self, offline: bool) -> None:
        """Workflow 1: Start with a deterministic planner for the first iteration."""
        self._offline = offline

    def plan(self, spec_text: str) -> Plan:
        """Workflow 1A: Return a small starter plan with the core build steps."""
        _ = spec_text
        return Plan(
            goal="Build a car inventory manager from the supplied text specification.",
            steps=[
                PlanStep(
                    order=1,
                    title="Create the main inventory view and supporting UI components",
                    outputs=["src/components/CarInventory.tsx", "src/App.tsx"],
                ),
                PlanStep(
                    order=2,
                    title="Add test coverage for the main inventory flow",
                    outputs=["src/__tests__/CarInventory.test.tsx"],
                ),
            ],
            components=["src/components/CarInventory.tsx", "src/App.tsx"],
            tests=["src/__tests__/CarInventory.test.tsx"],
        )
