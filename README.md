# agents-swarm

A small, local orchestration layer for DAG-shaped agent workflows.

This project keeps model routing, task dependencies, review gates, and run
records outside of any single chat session. Codex, Claude, or another model can
act as the orchestrator, while smaller models execute clearly bounded task
nodes.

## What It Does

- Validates a YAML or JSON DAG task file.
- Lists nodes that are ready to run.
- Renders per-node prompts with recommended model and review rules.
- Records execution results in `runs/`.
- Supports review gates and retry/escalation policy as first-class metadata.

It intentionally does not call a model provider yet. The first durable layer is
the protocol; provider-specific dispatch can sit on top.

## Quick Start

```bash
python -m agents_swarm validate examples/optimization_dag.yaml
python -m agents_swarm check-sync examples/optimization_dag.yaml examples/optimization_dag.json
python -m agents_swarm export-json examples/optimization_dag.yaml examples/optimization_dag.json
python -m agents_swarm ready examples/optimization_dag.yaml
python -m agents_swarm prompt examples/optimization_dag.yaml baseline-inventory
python -m agents_swarm record examples/optimization_dag.yaml baseline-inventory \
  --model gpt-5-mini \
  --status passed \
  --output-commit abc1234 \
  --changed-file docs/baseline.md \
  --verification "pytest -q"
python -m agents_swarm review examples/optimization_dag.yaml field-resolver-skeleton \
  --status orchestrator_approved
```

Use `PYTHONPATH=src` if you are running from a fresh checkout without installing
the package:

```bash
PYTHONPATH=src python -m agents_swarm ready examples/optimization_dag.yaml
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

YAML is the human-authored source of truth. JSON is a generated compatibility
artifact for tools that prefer strict machine-readable input.

After editing `examples/optimization_dag.yaml`, regenerate and check JSON:

```bash
python -m agents_swarm export-json examples/optimization_dag.yaml examples/optimization_dag.json
python -m agents_swarm check-sync examples/optimization_dag.yaml examples/optimization_dag.json
```

Use `check-sync` in tests or CI so drift is caught before a task graph is used.

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

## Suggested Flow

1. Write or generate a DAG file.
2. Run `ready` to find parallelizable tasks.
3. Render prompts for ready tasks.
4. Send each prompt to the chosen model or thread.
5. Record the result.
6. Review gated nodes.
7. Repeat until the DAG is complete.
