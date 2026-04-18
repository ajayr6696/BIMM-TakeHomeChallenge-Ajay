## BIMM Take-Home: Multi-Agent React Code Generator

This repository contains a Python CLI agent that reads a text specification and generates a React + TypeScript app in `generated-app/` from the immutable starter in `Fullstack-Coding-Challenge-main/`.

### Why Python

I used Python for the agent because the workflow is mostly orchestration: reading files, calling an LLM, writing generated code, and running validation commands. Python made it easy to keep the agent loop small, explicit, and interview-friendly without adding a lot of framework overhead.

### Current architecture

The current implementation follows this workflow:

`Spec -> Plan -> Generate -> Write -> Validate -> Fix -> Retry`

- `PlannerAgent` builds an ordered, dependency-aware plan with outputs for each step.
- `CodeAgent` generates the supported React files and falls back to deterministic local templates when the model output is unsafe.
- `ValidatorAgent` runs `npm install`, `npm run typecheck`, and `npm run test`.
- `FixAgent` uses validator failures to request focused full-file repairs.
- `fix_only.py` runs the fixer directly against an already generated app so the fix path can be tested independently.
- `Orchestrator` wires the whole run together.

### Workflow diagram

```text
          spec.txt
             |
             v
       +-------------+
       | PlannerAgent|
       +-------------+
             |
             v
       +-------------+      +------------------+
       |  CodeAgent  | ---> | write files into |
       +-------------+      | generated-app/   |
             |              +------------------+
             v
       +-------------+
       | Validator   |  npm install/typecheck/test
       +-------------+
             |
     ok? ----+---- no
      |           |
      v           v
    Finish    +----------+
              | FixAgent |
              +----------+
                   |
                Retry (<=2 in full agent)
```

`fix_only.py` has its own retry loop with a default of `3` attempts.

### Project structure

```text
BIMM-TakeHomeChallenge-Ajay/
  agent/                           # Python CLI agent implementation
    core/                          # planner/generator/validator/fixer/orchestrator
    prompts/                       # prompt templates and loader
  Fullstack-Coding-Challenge-main/ # provided React starter (read-only input)
  generated-app/                   # generated output app
  spec.txt                         # sample natural-language spec
  .env.example                     # root env template for the Python agent
  README.md                        # project documentation
```

### Current branch history

These are the main branches used to show iterative development:

- `feature/planner`
- `feature/codegen`
- `feature/validator`
- `feature/fix-agent`
- `feature/fix-only`
- `feature/final-docs`
- `main`

Each feature branch contains small focused commits and is merged back into `main` so the git log shows the project evolving in stages.

### Local setup

Prerequisites:

- Python 3.10+
- Node.js + npm

1. Clone the repository:

```bash
git clone https://github.com/ajayr6696/BIMM-TakeHomeChallenge-Ajay.git
cd BIMM-TakeHomeChallenge-Ajay
```

2. Create and activate a Python virtual environment:

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
```

macOS/Linux:

```bash
source .venv/bin/activate
```

3. Install the Python dependency used by the agent:

```bash
pip install groq
```

4. Create the root `.env` file from `.env.example`:

Windows PowerShell:

```bash
Copy-Item .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

The root `.env` is used by the Python agent only. It is not used by the React starter app.

### Run the full agent locally

This command runs the full pipeline: planning, code generation, file writes, validation, and up to `2` repair retries.

```bash
python agent/agent.py --spec spec.txt --input ./Fullstack-Coding-Challenge-main --output ./generated-app
```

After generation, run the app locally:

```bash
cd generated-app
npm install
npm run dev
```

Useful validation commands inside `generated-app/`:

```bash
npm run typecheck
npm run test -- --pool=threads --maxWorkers=1
```

### Run without an LLM

I used offline mode during development to check whether the planner and deterministic generator path were working without spending model calls.

You can run the agent locally without external LLM calls in either of these ways:

```bash
python agent/agent.py --offline --spec spec.txt --input ./Fullstack-Coding-Challenge-main --output ./generated-app
```

or:

```bash
$env:AGENT_OFFLINE_MODE=1
python agent/agent.py --spec spec.txt --input ./Fullstack-Coding-Challenge-main --output ./generated-app
```

Offline mode is useful for verifying the planner shape, file orchestration, and local workflow before testing the full LLM-assisted path.

### Run fix-only mode

`fix_only.py` was created so I could test the repair workflow independently and see whether `FixAgent` could repair an already generated app without rerunning the whole planner/codegen pipeline.

Run it like this:

```bash
python agent/fix_only.py --spec spec.txt --output ./generated-app
```

Useful variants:

```bash
python agent/fix_only.py --spec spec.txt --output ./generated-app --dry-run
python agent/fix_only.py --spec spec.txt --output ./generated-app --max-retries 3
python agent/fix_only.py --spec spec.txt --output ./generated-app --offline
```

What `fix_only.py` does:

1. Validates the current `generated-app/`.
2. Builds a compact digest from typecheck and test failures.
3. Infers the most likely file to repair from the logs.
4. Calls `FixAgent` with focused failure context.
5. Applies pre-write safety checks.
6. Re-runs validation after each attempt.
7. Rolls back failed attempts so the next retry starts from a known-good state.

### Implementation notes

- Prompts are stored in `agent/prompts/` instead of being embedded inline.
- Planning is dependency-aware through `PlanStep`.
- Generation and repair both use strict JSON contracts.
- Fixes use full-file replacements rather than AST patches.
- The full orchestrator retries failed validation up to `2` times.
- The fix-only runner retries up to `3` times by default.
- The generated app includes the car inventory UI, add-car flow, responsive images, search/sort behavior, and Vitest coverage.

### Architecture decisions

- **Why Groq**
  Fast structured generation through an OpenAI-compatible API and good latency for iteration.

- **Why a custom multi-agent loop**
  The take-home emphasized visible workflow and planning, so I kept the system explicit instead of hiding it inside a larger orchestration framework.

- **Why prompt files**
  They make the planning, generation, and repair behavior easier to inspect and tune separately from the Python control flow.

- **Why a separate fix-only runner**
  It made it easier to isolate the repair loop while developing and debugging the fixer.

### Demo flow

1. Run the full agent to generate `generated-app/`.
2. Start the React app from `generated-app/`.
3. Run `fix_only.py` if you want to test the repair path against an existing generated output.
