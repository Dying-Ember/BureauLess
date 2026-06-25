# BureauLess

**English** | [中文](README.zh-CN.md)

BureauLess is a small, local-first orchestration layer for DAG-shaped agent
workflows.

BureauLess is not an agent. It is a token-aware harness for deciding when
agents are worth using, constraining what they may do, and recording what can
be trusted.

Today, BureauLess defines and records the workflow protocol through YAML, CLI
tools, and a local workbench. It does not dispatch to model providers yet.

Agent workflows tend to fail in two familiar organizational ways. Sometimes a
tiny patch gets an org chart: planner, reviewer, advisor, coordinator, and
everyone reading the same repository context before one worker touches one
file. Sometimes it fails the other way: one overloaded lead fans work out to
many workers with no middle layer, no gates, no trusted ledger, and no clear
way to explain who is blocked, who is done, and which result should be believed.

BureauLess helps choose the smallest coordination structure that can safely do
the job. If one bounded worker is enough, do not convene a company. If the work
fans out, add only the structure that earns its keep: assignments, gates,
artifact checks, budget limits, replayable events, and a ledger that decides
what becomes shared truth.

The point is not just control in the moment. If every assignment, gate,
artifact, budget estimate, model choice, and outcome becomes durable data, the
system can be replayed and backtested. Over time, the goal is for real runs to
show which workflow shapes were worth it, which advisor calls paid for
themselves, which gates caught real risk, and where the policy should get
simpler.

## Why This Exists

Most agent systems are very eager to become bigger agent systems. BureauLess
goes the other way: start with one bounded worker, add coordination only when
the evidence says it is worth the cost.

The useful question is not "how many agents can we summon?" It is "which agent
work is safe, useful, auditable, and worth the tokens?"

## What It Does

It keeps model routing, task dependencies, review gates, and run records in
YAML files outside of any single chat session. Codex, Claude, or another model
can act as the orchestrator, while smaller models execute clearly bounded task
nodes.

- Validates YAML DAG task files.
- Lists nodes that are ready to run.
- Renders per-node prompts with recommended model and review rules.
- Records execution results as YAML files in `runs/`.
- Supports review gates and retry/escalation policy as first-class metadata.

The first durable layer is the protocol. Provider-specific dispatch can come
later, after the rules are boring enough to trust.

## Quick Start

```bash
uv run python -m bureauless validate examples/optimization_dag.yaml
uv run python -m bureauless mission validate examples/missions/demo/mission.yaml
uv run python -m bureauless workflow compile examples/missions/demo/workflows/coder_reviewer_committer.yaml
uv run python -m bureauless ready examples/optimization_dag.yaml
uv run python -m bureauless prompt examples/optimization_dag.yaml baseline-inventory
uv run python -m bureauless record examples/optimization_dag.yaml baseline-inventory \
  --model gpt-5-mini \
  --status passed \
  --output-commit abc1234 \
  --changed-file docs/baseline.md \
  --verification "pytest -q"
uv run python -m bureauless review examples/optimization_dag.yaml field-resolver-skeleton \
  --status orchestrator_approved
```

Use `uv run` from a fresh checkout:

```bash
uv run python -m bureauless ready examples/optimization_dag.yaml
```

After installing the package, the equivalent command is:

```bash
bureauless ready examples/optimization_dag.yaml
```

## Core Ideas

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

### Token Economy

Every extra agent needs a budget reason. Every advisor needs an even stronger
one. If coordination costs more than it saves, the workflow should get simpler.

### Replay And Backtesting

Runs should leave enough structured evidence to replay what happened and test
whether a different policy would have made a better routing, gate, model, or
advisor decision.

### Orchestrator And Harness

The long-term architecture separates the control plane from execution:

- The orchestrator plans, routes, records, reviews, and replans.
- Worker agents execute bounded tasks.
- The harness enforces roles, events, gates, budget policy, and provenance.
- Advisors are lazy and budget-gated.

The short version: agents can do work, but they do not get to write history.

## Suggested Flow

1. Write or generate a DAG file.
2. Run `ready` to find parallelizable tasks.
3. Render prompts for ready tasks.
4. Send each prompt to the chosen model or thread.
5. Record the result.
6. Review gated nodes.
7. Repeat until the DAG is complete.

## Workbench

The workbench is the place to inspect DAG state, runs, gates, and records before
more execution is automated. It uses one React UI for both browser and Electron.
Python remains the source of DAG behavior through a local FastAPI API.

Install dependencies:

```bash
uv sync --dev
npm install
```

Run the local API:

```bash
uv run uvicorn bureauless.api:app --reload
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

If the local npm Electron binary is incomplete, the launcher automatically falls
back to a system install such as `electron39`.

The UI follows the system color scheme by default and also exposes
`system / light / dark` controls. DAG documents and run records remain YAML-only.

## Source Layout

The runtime/harness code is now grouped by ownership boundary instead of living
as one flat module shelf:

- `src/bureauless/protocol/`: YAML-backed protocol models, validators,
  assignment/result handling, artifact integrity, and budget snapshots.
- `src/bureauless/runtime/`: replay, gatekeeper, session wrapper, and outcome
  metrics.
- `src/bureauless/agents/`: external agent registry and doctor checks.
- `src/bureauless/api/`: FastAPI workbench API entrypoints.
- `src/bureauless/cli/`: CLI entrypoints.
- `src/bureauless/core.py`: legacy DAG/run-record primitives that remain as the
  compatibility layer while the newer mission/workflow runtime grows around it.

## Documentation

Design notes, protocol drafts, and roadmap live here:

- [`docs/README.md`](docs/README.md)
- [`docs/roadmap/development_roadmap.md`](docs/roadmap/development_roadmap.md)
- [`docs/tasks/runtime_harness_tasklist.md`](docs/tasks/runtime_harness_tasklist.md)
- [`docs/tasks/runtime_harness_milestone_1_tasklist.md`](docs/tasks/runtime_harness_milestone_1_tasklist.md)
- [`docs/tasks/runtime_harness_milestone_2_tasklist.md`](docs/tasks/runtime_harness_milestone_2_tasklist.md)
- [`docs/tasks/workbench_tasklist.md`](docs/tasks/workbench_tasklist.md)
- [`docs/tasks/workbench_milestone_1_tasklist.md`](docs/tasks/workbench_milestone_1_tasklist.md)
- [`docs/architecture/research_and_design_notes.md`](docs/architecture/research_and_design_notes.md)
- [`docs/architecture/orchestrator_system_prompt.md`](docs/architecture/orchestrator_system_prompt.md)
- [`docs/architecture/context_economy.md`](docs/architecture/context_economy.md)
- [`docs/protocol/harness_protocol.md`](docs/protocol/harness_protocol.md)
- [`docs/protocol/workflow_selection_policy.md`](docs/protocol/workflow_selection_policy.md)
- [`docs/protocol/advisor_policy.md`](docs/protocol/advisor_policy.md)
- [`docs/protocol/workflow_examples.md`](docs/protocol/workflow_examples.md)

The docs now use one shared vocabulary:

- `milestone`: a user-visible delivery target
- `workstream`: an internal implementation grouping inside a milestone

That keeps runtime and workbench planning aligned instead of letting one side
talk in phases while the other talks in milestones.
