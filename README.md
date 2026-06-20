# agents-swarm

A small, local orchestration layer for DAG-shaped agent workflows.

This project keeps model routing, task dependencies, review gates, and run
records in YAML files outside of any single chat session. Codex, Claude, or another model can
act as the orchestrator, while smaller models execute clearly bounded task
nodes.

## What It Does

- Validates a YAML DAG task file.
- Lists nodes that are ready to run.
- Renders per-node prompts with recommended model and review rules.
- Records execution results as YAML files in `runs/`.
- Supports review gates and retry/escalation policy as first-class metadata.

It intentionally does not call a model provider yet. The first durable layer is
the protocol; provider-specific dispatch can sit on top.

## Quick Start

```bash
uv run python -m agents_swarm validate examples/optimization_dag.yaml
uv run python -m agents_swarm mission validate examples/missions/demo/mission.yaml
uv run python -m agents_swarm workflow compile examples/missions/demo/workflows/coder_reviewer_committer.yaml
uv run python -m agents_swarm ready examples/optimization_dag.yaml
uv run python -m agents_swarm prompt examples/optimization_dag.yaml baseline-inventory
uv run python -m agents_swarm record examples/optimization_dag.yaml baseline-inventory \
  --model gpt-5-mini \
  --status passed \
  --output-commit abc1234 \
  --changed-file docs/baseline.md \
  --verification "pytest -q"
uv run python -m agents_swarm review examples/optimization_dag.yaml field-resolver-skeleton \
  --status orchestrator_approved
```

Use `uv run` from a fresh checkout:

```bash
uv run python -m agents_swarm ready examples/optimization_dag.yaml
```

After installing the package, the equivalent command is:

```bash
agents-swarm ready examples/optimization_dag.yaml
```

## Git In This Workspace

The Codex desktop workspace mounts `.git/` as a read-only placeholder, so this
repo uses `.git-local/` as its Git directory:

```bash
git --git-dir=.git-local --work-tree=. status
git --git-dir=.git-local --work-tree=. add .
git --git-dir=.git-local --work-tree=. commit -m "Initial swarm orchestrator"
```

For convenience:

```bash
alias gswarm='git --git-dir=.git-local --work-tree=.'
gswarm status
```

## Core Concepts

### Source Format

Both DAG documents and run records use YAML. The project does not maintain a
second persisted representation.

### Task Node

A node describes one bounded unit of work: goal, dependencies, files, model
routing, review gate, verification, and prompt contract.

### Run Record

Every execution records the model, commits, changed files, verification result,
and review status. This is what makes retries and audits possible.

### Review Gate

Nodes can be allowed to pass automatically, require orchestrator review, or
require human review before downstream nodes become ready.

### Failure Policy

Failures are explicit: retry with the same model, escalate to a larger model,
send to a human, or split the task further.

### Orchestrator/Harness Direction

The long-term architecture separates the control plane from execution:

- The orchestrator plans, routes, records, reviews, and replans.
- Worker agents execute bounded tasks.
- The harness enforces roles, events, gates, budget policy, and provenance.
- Advisors are lazy and budget-gated.

Design notes and protocol drafts:

- [`docs/research_and_design_notes.md`](docs/research_and_design_notes.md)
- [`docs/orchestrator_system_prompt.md`](docs/orchestrator_system_prompt.md)
- [`docs/harness_protocol.md`](docs/harness_protocol.md)
- [`docs/advisor_policy.md`](docs/advisor_policy.md)
- [`docs/context_economy.md`](docs/context_economy.md)
- [`docs/workflow_examples.md`](docs/workflow_examples.md)

## Suggested Flow

1. Write or generate a DAG file.
2. Run `ready` to find parallelizable tasks.
3. Render prompts for ready tasks.
4. Send each prompt to the chosen model or thread.
5. Record the result.
6. Review gated nodes.
7. Repeat until the DAG is complete.

## Workbench

The workbench uses one React UI for both browser and Electron. Python remains
the source of DAG behavior through a local FastAPI API.

The detailed workbench roadmap lives in
[`docs/workbench_tasklist.md`](docs/workbench_tasklist.md).

Install dependencies:

```bash
uv sync --dev
npm install
```

Run the local API:

```bash
uv run uvicorn agents_swarm.server:app --reload
```

Run the browser workbench:

```bash
npm run web:dev
```

Run the browser smoke test after the API and web server are running:

```bash
npm run web:smoke
```

Run the Electron shell:

```bash
npm run desktop:dev
```

The UI follows the system color scheme by default and also exposes
`system / light / dark` controls. DAG documents and run records remain YAML-only.
