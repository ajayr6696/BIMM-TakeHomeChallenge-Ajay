## BIMM Take-Home: Multi-Agent React Code Generator

This repository will contain a Python CLI agent that reads a text specification and generates a React + TypeScript app in `generated-app/` from the provided immutable starter in `Fullstack-Coding-Challenge-main/`.

### Planned work

1. Add a planner that converts the natural-language spec into ordered implementation tasks.
2. Add a code generator that produces only the supported React app files.
3. Add validation so the generated app must typecheck and pass tests.
4. Add a fix loop that uses validator failures to repair the generated output.
5. Add a direct fixer mode for iterating on an already generated app.

### Initial architecture decisions

- Use a small custom agent loop instead of a framework so the workflow stays visible in the take-home.
- Keep prompt text in separate files so agent behavior is easier to inspect and tune.
- Use full-file rewrites for generated output first, then add repair logic only after validation exists.
- Use Groq-compatible chat completions because they are fast and support structured JSON responses.

### Target workflow

`Spec -> Plan -> Generate -> Validate -> Fix`
