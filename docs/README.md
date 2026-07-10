# Documentation Map

The documentation is organized by decision level so future work can find the
right context without rereading chat history.

## Roadmap

Use this path for implementation order and product/runtime sequencing.

- [`roadmap/development_roadmap.md`](roadmap/development_roadmap.md): project
  roadmap that keeps the harness/runtime line and the workbench/UI line separate.

## Audits

Use this path for evidence-backed differences between documented capability
claims and shipped behavior. Audits route remediation into roadmaps, task lists,
RFCs, and ADRs without replacing any of them.

- [`audits/README.md`](audits/README.md): gap-analysis format, severity,
  completion vocabulary, and processing workflow.
- [`audits/2026-07-02-runtime-execution-gap-analysis.md`](audits/2026-07-02-runtime-execution-gap-analysis.md):
  closed real-agent execution-spine audit with REX-001 deferred to Runtime M4.

## Tasks

Use this path for concrete implementation task cards, milestone indexes, and
acceptance criteria.

- [`tasks/runtime_harness_tasklist.md`](tasks/runtime_harness_tasklist.md):
  runtime/harness milestone index.
- [`tasks/runtime_harness_milestone_1_tasklist.md`](tasks/runtime_harness_milestone_1_tasklist.md):
  runtime/harness foundation milestone.
- [`tasks/runtime_harness_milestone_2_tasklist.md`](tasks/runtime_harness_milestone_2_tasklist.md):
  completed runtime/harness milestone for real-agent execution loop hardening.
- [`tasks/runtime_harness_milestone_2_5_tasklist.md`](tasks/runtime_harness_milestone_2_5_tasklist.md):
  completed runtime/harness bridge milestone for controlled workflow mutation.
- [`tasks/runtime_harness_milestone_3_tasklist.md`](tasks/runtime_harness_milestone_3_tasklist.md):
  completed artifact/protocol milestone for node outcomes, bounded context
  delivery, orchestrator decision artifacts, and advisor outcome learning.
- [`tasks/runtime_harness_milestone_3_5_tasklist.md`](tasks/runtime_harness_milestone_3_5_tasklist.md):
  planned remediation milestone that makes M2/M3 artifacts authoritative in the
  real-agent execution path.
- [`tasks/runtime_harness_milestone_4_tasklist.md`](tasks/runtime_harness_milestone_4_tasklist.md):
  completed runtime milestone for universal inert mutation intents, trusted
  proposal intake, retry control, workflow versions, linear temporal replay,
  and history APIs.
- [`tasks/workbench_tasklist.md`](tasks/workbench_tasklist.md): workbench
  milestone index.
- [`tasks/workbench_milestone_1_tasklist.md`](tasks/workbench_milestone_1_tasklist.md):
  completed planning-DAG workbench milestone.
- [`tasks/workbench_milestone_2_tasklist.md`](tasks/workbench_milestone_2_tasklist.md):
  completed runtime console milestone for workflow, replay, gatekeeper, and
  mutation inspection.
- [`tasks/workbench_milestone_3_tasklist.md`](tasks/workbench_milestone_3_tasklist.md):
  completed runtime-source loading and planning-action clarity milestone.
- [`tasks/workbench_milestone_4_tasklist.md`](tasks/workbench_milestone_4_tasklist.md):
  completed milestone for visual inspection of Runtime Harness Milestone 3
  decisions, outcomes, context delivery, telemetry, and dispatch artifacts.
- [`tasks/workbench_milestone_5_tasklist.md`](tasks/workbench_milestone_5_tasklist.md):
  completed milestone for read-only Runtime Harness Milestone 4 timeline,
  historical snapshot, version-selection, and diff inspection.
- [`tasks/workbench_milestone_6_tasklist.md`](tasks/workbench_milestone_6_tasklist.md):
  completed milestone for validated runtime operator actions including context
  resolution, dispatch/launch controls, and acceptance-spine actions.
- [`tasks/workbench_milestone_7_tasklist.md`](tasks/workbench_milestone_7_tasklist.md):
  completed milestone for guided runtime bootstrap, manifest/run-bundle
  navigation, and artifact-readiness visibility.
- [`tasks/engineering_boundary_refactor_tasklist.md`](tasks/engineering_boundary_refactor_tasklist.md):
  RFC-003 implementation task list for shared errors, CLI split, application
  services, and protocol exports.

## RFCs

Use this path for design proposals and their decision history. Implemented
behavior is promoted into `protocol/`; the RFC remains as provenance.

- [`rfcs/001-controlled-workflow-mutation.md`](rfcs/001-controlled-workflow-mutation.md):
  RFC-001, implemented Milestone 2.5 design history for controlled workflow
  mutation.
- [`rfcs/002-ledger-evidence-and-progressive-context.md`](rfcs/002-ledger-evidence-and-progressive-context.md):
  RFC-002, accepted design for separating native evidence, node outcomes,
  canonical ledger facts, progressive context disclosure, and context-policy
  feedback.
- [`rfcs/003-engineering-boundary-refactor.md`](rfcs/003-engineering-boundary-refactor.md):
  RFC-003, implemented engineering-boundary refactor for shared errors, CLI
  split, application services, and narrower protocol exports.
- [`rfcs/004-temporal-replay-mutation-intake-and-retry-control.md`](rfcs/004-temporal-replay-mutation-intake-and-retry-control.md):
  RFC-004, accepted Runtime Milestone 4 design for mutation intent intake,
  bounded retry control, workflow versions, and linear temporal replay.
- [`rfcs/005-authoritative-result-acceptance-spine.md`](rfcs/005-authoritative-result-acceptance-spine.md):
  RFC-005, implemented Runtime Milestone 3.5 design for staged result intake and
  one authoritative review/outcome/replay acceptance chain.
- [`rfcs/006-bounded-context-continuation.md`](rfcs/006-bounded-context-continuation.md):
  RFC-006, implemented Runtime Milestone 3.5 bounded context continuation design.

## ADRs

Use this path for decision records that resolve an RFC into a stable archived
choice.

- [`adrs/README.md`](adrs/README.md): ADR archive rules and RFC/ADR linking
  model.
- [`adrs/001-controlled-workflow-mutation/README.md`](adrs/001-controlled-workflow-mutation/README.md):
  ADR-001 archive for GitHub issue #1 and controlled workflow mutation.
- [`adrs/002-ledger-evidence-and-progressive-context/README.md`](adrs/002-ledger-evidence-and-progressive-context/README.md):
  ADR-002 archive for ledger evidence and progressive context.
- [`adrs/003-engineering-boundary-refactor/README.md`](adrs/003-engineering-boundary-refactor/README.md):
  ADR-003 archive index for the engineering boundary refactor RFC.
- [`adrs/004-temporal-replay-mutation-intake-and-retry-control/README.md`](adrs/004-temporal-replay-mutation-intake-and-retry-control/README.md):
  ADR-004 accepted mutation intake, retry, ledger v3, and temporal replay design.
- [`adrs/005-authoritative-result-acceptance-spine/README.md`](adrs/005-authoritative-result-acceptance-spine/README.md):
  ADR-005 accepted result, review, outcome, and strict ledger acceptance design.
- [`adrs/006-bounded-context-continuation/README.md`](adrs/006-bounded-context-continuation/README.md):
  ADR-006 accepted bounded context continuation design.

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
2. Read any open relevant audit in [`audits/`](audits/) when the work touches a
   known capability gap.
3. Read the relevant protocol file for the runtime feature being changed.
4. Read any relevant RFC in [`rfcs/`](rfcs/) if the work touches a proposed
   but not yet accepted design.
5. Read the relevant milestone index and task list in [`tasks/`](tasks/).
6. Read the relevant architecture note only when the design rationale matters.

## Source Layout

The runtime/harness implementation follows the same boundary split as the
documentation, but not a literal one-to-one directory mirror:

- `src/bureauless/protocol/`: runtime protocol loaders, validators, artifact
  integrity, assignment export, result import, and budget snapshot logic.
- `src/bureauless/runtime/`: replay, gatekeeper, session wrapper, and outcome
  metrics.
- `src/bureauless/agents/`: external agent registry and doctor checks.
- `src/bureauless/api/`: FastAPI workbench API.
- `src/bureauless/cli/`: CLI entrypoint plus command modules for legacy DAG,
  runtime, exchange, agent, session, and metrics operations.
- `src/bureauless/core.py`: legacy DAG/run-record compatibility layer.

When changing runtime behavior, update both the relevant `docs/protocol/*` file
and the matching source package so future sessions do not have to reconstruct
the boundary from chat history.

When an implementation review discovers that a completed milestone claim is
broader than shipped behavior, follow [`audits/README.md`](audits/README.md):
preserve the historical task record, add a dated correction, and route every
confirmed gap to an owned task or explicit roadmap deferral.
