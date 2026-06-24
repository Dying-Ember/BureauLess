# Documentation Map

The documentation is organized by decision level so future work can find the
right context without rereading chat history.

## Roadmap

Use this path for implementation order and product/runtime sequencing.

- [`roadmap/development_roadmap.md`](roadmap/development_roadmap.md): project
  roadmap that keeps the harness/runtime line and the workbench/UI line separate.

## Tasks

Use this path for concrete implementation task cards and acceptance criteria.

- [`tasks/runtime_harness_tasklist.md`](tasks/runtime_harness_tasklist.md):
  runtime/harness task cards for ledger, replay, gatekeeper, assignments,
  external agent sessions, and outcome metrics.
- [`tasks/workbench_tasklist.md`](tasks/workbench_tasklist.md): concrete
  workbench task cards.

## Architecture

Use this path for design principles, tradeoffs, and long-lived reasoning.

- [`architecture/research_and_design_notes.md`](architecture/research_and_design_notes.md):
  external references and why they matter for this project.
- [`architecture/orchestrator_system_prompt.md`](architecture/orchestrator_system_prompt.md):
  orchestrator control-plane prompt draft.
- [`architecture/context_economy.md`](architecture/context_economy.md):
  token economy and coordination overhead rules.

## Protocol

Use this path for machine-readable contracts and validation targets.

- [`protocol/harness_protocol.md`](protocol/harness_protocol.md): mission,
  ledger, workflow, assignment, report, event, gate, broadcast, artifact,
  failure lifecycle, and invariant protocol.
- [`protocol/workflow_selection_policy.md`](protocol/workflow_selection_policy.md):
  deterministic routing rules for choosing the simplest valid execution mode.
- [`protocol/advisor_policy.md`](protocol/advisor_policy.md): lazy advisor
  gating policy and first-run heuristics.
- [`protocol/workflow_examples.md`](protocol/workflow_examples.md): canonical
  workflow examples for future implementation and tests.

## Reading Order

For a new implementation session:

1. Read [`roadmap/development_roadmap.md`](roadmap/development_roadmap.md).
2. Read the relevant protocol file for the runtime feature being changed.
3. Read the relevant task list in [`tasks/`](tasks/).
4. Read the relevant architecture note only when the design rationale matters.

## Source Layout

The runtime/harness implementation follows the same boundary split as the
documentation, but not a literal one-to-one directory mirror:

- `src/bureauless/protocol/`: runtime protocol loaders, validators, artifact
  integrity, assignment export, result import, and budget snapshot logic.
- `src/bureauless/runtime/`: replay, gatekeeper, session wrapper, and outcome
  metrics.
- `src/bureauless/agents/`: external agent registry and doctor checks.
- `src/bureauless/api/`: FastAPI workbench API.
- `src/bureauless/cli/`: CLI entrypoints.
- `src/bureauless/core.py`: legacy DAG/run-record compatibility layer.

When changing runtime behavior, update both the relevant `docs/protocol/*` file
and the matching source package so future sessions do not have to reconstruct
the boundary from chat history.
