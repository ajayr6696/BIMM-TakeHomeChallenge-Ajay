## Multi-Agent React Code Generator

This repository contains a Python CLI agent that reads a text specification and generates a working React + TypeScript app in `generated-app/`, starting from the provided immutable boilerplate in `Fullstack-Coding-Challenge-main/`.

### Project structure

```text
Multi-Agent-React-Code-Generator/
  agent/                           # Python CLI agent implementation
    core/                          # planner/generator/validator/fixer/orchestrator
    prompts/                       # text prompt templates used by Planner/Code/Fix agents
  Fullstack-Coding-Challenge-main/ # provided React project (read-only input)
  generated-app/                   # generated output app
  spec.txt                         # sample natural-language spec
  README.md                        # project documentation
  .env.example                     # root env template for the Python agent
```

### Why Python

I used Python for the agent because the workflow is primarily orchestration: read the spec, plan tasks, call the LLM, write files, run shell validation commands, and coordinate retries. Python kept that loop concise, explicit, and easy to reason about without adding extra framework overhead. It also made it straightforward to separate the control-flow code from the React/TypeScript output being generated.

Python also has a very strong ecosystem for data processing and AI work, including libraries such as `pandas` and `numpy` for data handling, and frameworks such as `PyTorch` and `TensorFlow` for machine learning, deep learning, and NLP-related workflows. Since I already have experience using Python and these kinds of libraries, it felt like the most natural choice for building this agent quickly and cleanly.

### Local setup

- Prereqs: Node.js (npm) and Python 3.10+

1. Clone the repository:

```bash
git clone https://github.com/ajayr6696/Multi-Agent-React-Code-Generator.git
cd Multi-Agent-React-Code-Generator
```

2. Create a Python virtual environment:

```bash
python -m venv .venv
```

3. Activate it:

```bash
# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate
```

4. Install the Python dependency used by the agent:

```bash
pip install groq
```

5. Create the root `.env` file from `.env.example`:

```bash
# Windows PowerShell
Copy-Item .env.example .env

# macOS/Linux
cp .env.example .env
```

The root `.env` is used by the Python agent only. It is not used by the React boilerplate itself.

### Run

Run the full agent:

```bash
python agent/agent.py --spec spec.txt --input ./Fullstack-Coding-Challenge-main --output ./generated-app
```

This runs the full workflow: planning, generation, file writes, validation, and up to `2` self-heal retries inside the full orchestrator.

Run the generated app:

```bash
cd generated-app
npm install
npm run dev
```

Useful validation commands in `generated-app/`:

```bash
npm run typecheck
npm run test -- --pool=threads --maxWorkers=1
```

### Run without an LLM

I used offline mode while developing to verify that the planner, orchestration, and deterministic fallback generator path were working properly even without external model calls.

You can run locally without an LLM in either of these ways:

```bash
python agent/agent.py --offline --spec spec.txt --input ./Fullstack-Coding-Challenge-main --output ./generated-app
```

or:

```bash
# Windows PowerShell
$env:AGENT_OFFLINE_MODE=1
python agent/agent.py --spec spec.txt --input ./Fullstack-Coding-Challenge-main --output ./generated-app
```

This is useful for checking the planner shape and the local workflow quickly before testing the full LLM-assisted path.

### Architecture overview

The agent uses a modular multi-agent workflow:

**Spec -> Plan -> Generate -> Write -> Validate -> Fix -> Retry**

- **PlannerAgent** (`agent/core/planner_agent.py`)
  - Produces a structured plan with:
    - goal
    - ordered implementation steps
    - dependency links between steps
    - component/test file targets
- **CodeAgent** (`agent/core/code_agent.py`)
  - Generates strict JSON file outputs for the planned files.
  - Falls back to deterministic templates if model output is unsafe.
- **ValidatorAgent** (`agent/core/validator_agent.py`)
  - Runs `npm install`, `npm run typecheck`, and `npm run test`.
  - Prints short command logs plus durations for each validation step.
- **FixAgent** (`agent/core/fix_agent.py`)
  - Uses validation logs plus the ordered plan to request targeted full-file replacements.
  - Narrows fixes to the most likely implementation file for UI-behavior failures.
  - Falls back to a one-file-only retry prompt when the broad fix prompt returns unusable output.
  - Can salvage malformed Groq `failed_generation` payloads when JSON mode fails.
- **Fix-Only Runner** (`agent/fix_only.py`)
  - Runs validator + fixer against the current `generated-app/` without rerunning full generation.
  - Infers a single focus file from the latest failure logs.
  - Applies pre-write safety checks, retries up to a limit, and rolls back failed attempts.
  - Uses deterministic fallbacks for known high-confidence regression patterns when the small model is unreliable.
- **Orchestrator** (`agent/core/orchestrator.py`)
  - Coordinates the full run, prints ordered plan steps, test checklist, validation status, and total run time.

### Architecture diagram

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
                Retry (<=2)
```

For `fix_only.py`, the standalone repair runner has its own retry loop with a default of `3` attempts.

### Current branch history

These are the main branches used to show iterative development:

- `feature/planner`
- `feature/codegen`
- `feature/validator`
- `feature/fix-agent`
- `feature/fix-only`
- `feature/final-docs`
- `main`

Each feature branch contains small focused commits and is merged back into `main` so the git log shows the project evolving in stages instead of appearing as one large drop.

### What was updated

- Added **explicit ordered task decomposition** through `PlanStep` objects.
- Added **dependency-aware planning** rather than only returning a flat file list.
- Added **few-shot guidance** in planner and generator prompts.
- Kept **strict JSON schema enforcement** across planner, generator, and fixer prompts.
- Moved the three main LLM prompts into text files under:
  - `agent/prompts/planner_prompt.txt`
  - `agent/prompts/code_prompt.txt`
  - `agent/prompts/fix_prompt.txt`
- Moved shared project constraints into:
  - `agent/prompts/project_constraints.txt`
- Added a shared loader at:
  - `agent/prompts/prompt_loader.py`
- Added a deterministic **fallback generator** when LLM output is invalid.
- Expanded generated-app coverage to include:
  - loading state
  - query error state
  - desktop image selection
  - mobile image selection
  - tablet image selection
  - search/filter behavior
  - empty-state behavior
  - sorting by make
  - sorting by year
  - add-form validation
  - add-from-UI success flow
  - form reset after success
  - mutation error handling
- Added concise workflow comments/docstrings across Python files under `agent/`.
- Added timing logs for:
  - overall Python agent run
  - each internal npm validation command
  - total validation time

### Task decomposition

The planner now creates ordered, dependency-aware implementation steps instead of only listing files.

Example plan shape:

1. Create the reusable `useCars` hook for fetching, sorting, and mutation state.
2. Build the responsive `CarCard` component for mobile, tablet, and desktop images.
3. Build the `AddCarForm` component with validation and submit behavior.
4. Assemble the `CarInventory` screen and wire it into `App.tsx`.
5. Cover the main flows with Vitest and `MockedProvider`.

Each step includes:

- `order`
- `title`
- `depends_on`
- `outputs`

This makes the workflow visibly agentic and dependency-aware instead of one giant prompt.

### Prompt design

Prompting is structured and explicit:

- Planner prompt:
  - strict JSON schema
  - few-shot planning example
  - ordered-step requirement
  - dependency-aware step requirement
  - loaded from `agent/prompts/planner_prompt.txt`
- Code generation prompt:
  - strict JSON output contract
  - constrained file allowlist
  - shared project constraints from `project_constraints.txt`
  - few-shot output-shape example
  - ordered implementation steps included as context
  - loaded from `agent/prompts/code_prompt.txt`
- Fix prompt:
  - strict JSON output contract
  - truncated validation logs to stay within token budget
  - ordered implementation steps included as context
  - loaded from `agent/prompts/fix_prompt.txt`
  - now supports:
    - retry-note context for later fix attempts
    - focus-file context near the top of the prompt
    - preferred-path steering toward implementation files instead of tests
    - one-file repair guidance for small React/TypeScript regressions

This structure keeps prompt assets separate from Python logic while still using proper Python imports through the shared prompt loader.

### Design decisions

- **Why Groq**
  - Fast, cost-effective inference with an OpenAI-compatible API surface.
  - The implementation uses Chat Completions with JSON mode and strict parsing.

- **Why Python for the agent**
  - The agent is mainly a control-flow/orchestration layer, so Python let me keep the workflow explicit and compact.
  - It was also convenient for file operations, shell validation commands, and retry logic.

- **Why a custom loop instead of LangChain/LangGraph**
  - The take-home asks for a visible, explicit workflow.
  - A small custom loop makes each step auditable and easy to explain in an interview.

- **Why a separate `fix_only.py`**
  - I created it to test the repair path independently and see whether `FixAgent` could actually fix an already generated app without rerunning the full planner/codegen pipeline.
  - It made debugging the fix workflow much faster while iterating.

- **Tradeoffs**
  - Fixes use full-file replacements instead of AST or diff patches.
  - Offline mode exists for reproducibility without credentials.
  - Deterministic fallback templates make the workflow more reliable for demo and evaluation.

### Evaluation criteria mapping

- **Plans the implementation**
  - `PlannerAgent` outputs goal, ordered steps, dependencies, and file targets.
- **Task decomposition**
  - `PlanStep` makes the plan stepwise and dependency-aware rather than a single prompt.
- **Tool use**
  - File writes, shell validation commands, and LLM calls are all separated into concrete agent/tool steps.
- **Context management**
  - Shared project constraints are stored once in `project_constraints.txt`.
  - Retry logs are trimmed before sending them back to the model.
- **Prompt design**
  - Prompts use strict JSON schema enforcement and few-shot guidance.
- **Error handling**
  - Validation feeds into `FixAgent` with bounded retries.

### Logging and observability

When running:

```bash
python agent/agent.py --spec spec.txt --input ./Fullstack-Coding-Challenge-main --output ./generated-app
```

The agent prints:

- loaded spec path
- ordered plan steps
- planned file list
- numbered planned test checklist
- each validation command being run
- exit code and duration for each validation command
- total validation time
- total Python agent run time

The standard generated-app commands remain:

```bash
npm run typecheck
npm run test -- --pool=threads --maxWorkers=1
```

### Fix-only workflow

You can run the fixer directly against the current `generated-app/` without re-running the full planner + codegen pipeline:

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
2. Builds a compact error digest from `typecheck` and `test` failures.
3. Infers the most likely source file to fix by scoring the supported implementation files against the latest validator logs.
4. Calls `FixAgent` with:
   - the spec excerpt
   - focused failure digest
   - current file content from the inferred file
   - a strict allowlist of writable paths
5. Runs pre-apply safety checks before writing any returned file:
   - rejects wrapped JSON / markdown / partial source
   - rejects obviously nonsensical placeholder code
   - preserves critical anchors from the original focused file (imports, exports, declarations)
6. Re-runs validation immediately after the attempted fix.
7. If validation still fails:
   - prints failed test counts before vs after
   - prints a compact residual error digest
   - reverts the attempted file changes so the next retry starts from a known-good state

### Current FixAgent behavior

The fix path is more defensive than the initial implementation.

- `FixAgent` first tries a broad strict-JSON fix prompt constrained to allowlisted files.
- For UI-behavior failures with clean typecheck, it limits output to implementation files instead of tests.
- When a single focus file is known, it can lock both the prompt context and the writable paths to that file.
- If the broad prompt fails to produce a usable result, `FixAgent` retries once with a smaller one-file-only repair prompt that preserves key anchors from the current file.
- If Groq returns a `json_validate_failed` error, `FixAgent` attempts to salvage file content from `failed_generation`.
- If the broad prompt fails to produce a usable result, the fixer falls back to a smaller one-file retry path using the inferred focus file.

### Deterministic fallback path

For known, high-confidence regression patterns, `fix_only.py` can bypass the LLM and apply a deterministic local repair path first.

In general, this is used when:

- the fixer has high confidence about the focus file
- pre-fix `typecheck` is clean
- the failing tests strongly indicate a narrow UI-behavior regression

This makes the fix-only path more reliable than relying entirely on a small general-purpose model for every retry.

### Files involved in fix-only mode

- `agent/fix_only.py`
  - CLI runner for validating, focusing, retrying, and rolling back direct fixes
- `agent/core/fix_agent.py`
  - LLM prompt construction, payload normalization, salvage, and one-file retry logic
- `agent/prompts/fix_prompt.txt`
  - strict JSON repair prompt template used by `FixAgent`

### Python workflow comments

All Python files under `agent/` include concise workflow-oriented comments/docstrings for readability:

- `agent/agent.py`
- `agent/core/orchestrator.py`
- `agent/core/planner_agent.py`
- `agent/core/code_agent.py`
- `agent/core/fix_agent.py`
- `agent/fix_only.py`
- `agent/core/validator_agent.py`
- `agent/core/fs.py`
- `agent/core/llm.py`
- `agent/prompts/prompt_loader.py`

### Reflection

- **Which LLM was used and why?**
  - Groq, for fast structured generation using an OpenAI-compatible chat API.

- **What worked well?**
  - Strict JSON contracts reduced ambiguity.
  - Ordered steps made the workflow easier to inspect and explain.
  - Validation provided a concrete done/not-done gate.
  - Offline mode helped verify the local planner/generator path during development.

- **What would improve with more time?**
  - AST-aware patching for smaller fixes.
  - Richer planning schema for more generalized frontend specs.
  - Token/cost reporting per model call.

- **Approximate cost per run**
  - Depends on prompt size and retries.
  - Roughly a few thousand to tens of thousands of tokens across planning, generation, and retries.
  - Offline mode costs $0.

### Demo instructions

Run:

```bash
python agent/agent.py --spec spec.txt --input ./Fullstack-Coding-Challenge-main --output ./generated-app
```

Expected outcome:

- `generated-app/` is refreshed from the provided boilerplate
- the planned component, hook, and test files are written
- validation runs automatically
- the agent prints ordered steps, test checklist, validation timings, and total runtime

If you do not want to use the LLM:

```bash
python agent/agent.py --offline --spec spec.txt --input ./Fullstack-Coding-Challenge-main --output ./generated-app
```
