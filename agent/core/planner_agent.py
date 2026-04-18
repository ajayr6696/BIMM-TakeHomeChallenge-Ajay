from __future__ import annotations

from agent.core.llm import LLMError, call_llm, must_parse_json
from agent.core.models import Plan, PlanStep
from agent.prompts.prompt_loader import load_prompt_template

PROJECT_CONSTRAINTS = load_prompt_template("project_constraints.txt")

SUPPORTED_COMPONENTS = {
    "src/hooks/useCars.ts",
    "src/components/CarCard.tsx",
    "src/components/AddCarForm.tsx",
    "src/components/CarInventory.tsx",
}
SUPPORTED_TESTS = {"src/__tests__/CarInventory.test.tsx"}
SUPPORTED_OUTPUTS = SUPPORTED_COMPONENTS | SUPPORTED_TESTS | {"src/App.tsx"}


class PlannerAgent:
    """PlannerAgent turns a natural-language spec into a structured implementation plan."""

    def __init__(self, offline: bool) -> None:
        """Workflow 3: Configure whether planning should use the LLM or the fallback plan."""
        self._offline = offline

    def plan(self, spec_text: str) -> Plan:
        """Workflow 3A: Convert the natural-language spec into an ordered implementation plan."""
        if self._offline:
            return self._default_plan()

        prompt = (
            load_prompt_template("planner_prompt.txt")
            .replace("__PROJECT_CONSTRAINTS__", PROJECT_CONSTRAINTS)
            .replace("__SPEC_TEXT__", spec_text)
        )

        try:
            data = must_parse_json(call_llm(prompt))
            plan = Plan(
                goal=str(data["goal"]),
                steps=[
                    PlanStep(
                        order=int(step["order"]),
                        title=str(step["title"]),
                        depends_on=[int(x) for x in step["depends_on"]],
                        outputs=[str(x) for x in step["outputs"]],
                    )
                    for step in data["steps"]
                ],
                components=[str(x) for x in data["components"]],
                tests=[str(x) for x in data["tests"]],
            )
            sanitized = self._sanitize_plan(plan)
            if sanitized.components and sanitized.tests:
                return sanitized
        except (LLMError, KeyError, TypeError, ValueError):
            pass

        return self._default_plan()

    def _sanitize_plan(self, plan: Plan) -> Plan:
        """Workflow 3B: Filter model output down to the supported file locations."""
        default_plan = self._default_plan()
        components = []
        for p in plan.components:
            s = p.strip()
            if s in SUPPORTED_COMPONENTS:
                components.append(s)
        tests = []
        for p in plan.tests:
            s = p.strip()
            if s in SUPPORTED_TESTS:
                tests.append(s)
        component_set = set(components)
        test_set = set(tests)
        valid_outputs = component_set | test_set | {"src/App.tsx"}
        steps = self._sanitize_steps(plan.steps, valid_outputs)

        # If the LLM returns only a partial supported plan, merge in the missing
        # required files from the deterministic default plan so generation stays
        # self-consistent and downstream imports do not break.
        merged_components = list(dict.fromkeys(components + default_plan.components))
        merged_tests = list(dict.fromkeys(tests + default_plan.tests))

        merged_outputs = set(merged_components) | set(merged_tests) | {"src/App.tsx"}
        merged_steps = self._sanitize_steps(plan.steps, merged_outputs)
        default_step_by_order = {step.order: step for step in default_plan.steps}
        seen_orders = {step.order for step in merged_steps}
        for step in default_plan.steps:
            if step.order not in seen_orders:
                merged_steps.append(default_step_by_order[step.order])
        merged_steps.sort(key=lambda step: step.order)

        return Plan(
            goal=plan.goal or default_plan.goal,
            steps=merged_steps,
            components=merged_components,
            tests=merged_tests,
        )

    def _sanitize_steps(self, steps: list[PlanStep], valid_outputs: set[str]) -> list[PlanStep]:
        """Workflow 3C: Keep only ordered plan steps that point at supported outputs."""
        sanitized_steps: list[PlanStep] = []
        seen_orders: set[int] = set()
        for step in sorted(steps, key=lambda item: item.order):
            outputs = [output for output in step.outputs if output in valid_outputs]
            if not outputs or step.order in seen_orders:
                continue
            depends_on = [dep for dep in step.depends_on if dep < step.order]
            sanitized_steps.append(
                PlanStep(
                    order=step.order,
                    title=step.title.strip(),
                    depends_on=depends_on,
                    outputs=outputs,
                )
            )
            seen_orders.add(step.order)
        return sanitized_steps

    def _default_plan(self) -> Plan:
        """Workflow 3D: Provide a deterministic ordered plan when LLM planning is unavailable."""
        return Plan(
            goal=(
                "Build a car inventory manager with a reusable useCars hook, responsive "
                "car cards, search and sorting controls, and an Add Car form."
            ),
            steps=[
                PlanStep(
                    order=1,
                    title="Create the reusable useCars hook for fetching, sorting, and mutation state",
                    depends_on=[],
                    outputs=["src/hooks/useCars.ts"],
                ),
                PlanStep(
                    order=2,
                    title="Build the responsive CarCard component for mobile, tablet, and desktop images",
                    depends_on=[1],
                    outputs=["src/components/CarCard.tsx"],
                ),
                PlanStep(
                    order=3,
                    title="Build the AddCarForm component with validation and submit handling",
                    depends_on=[1],
                    outputs=["src/components/AddCarForm.tsx"],
                ),
                PlanStep(
                    order=4,
                    title="Assemble the CarInventory screen with search, sorting, and app wiring",
                    depends_on=[1, 2, 3],
                    outputs=["src/components/CarInventory.tsx", "src/App.tsx"],
                ),
                PlanStep(
                    order=5,
                    title="Cover the main inventory flows with Vitest and MockedProvider",
                    depends_on=[1, 2, 3, 4],
                    outputs=["src/__tests__/CarInventory.test.tsx"],
                ),
            ],
            components=[
                "src/hooks/useCars.ts",
                "src/components/CarCard.tsx",
                "src/components/AddCarForm.tsx",
                "src/components/CarInventory.tsx",
            ],
            tests=["src/__tests__/CarInventory.test.tsx"],
        )
