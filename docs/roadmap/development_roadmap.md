# Development Roadmap

This document is the project-level roadmap. It explains how the runtime/harness
line and the workbench/UI line fit together, so day-to-day implementation does
not drift into unrelated details.

## Current Position

The project currently has two layers:

- DAG runtime: YAML DAG loading, ready-node calculation, prompt rendering, YAML
  run records, review status updates.
- Harness foundation: YAML mission, ledger, workflow loading, and deterministic
  workflow compilation for role/event/gate rules.

The project also has one UI surface:

- Workbench: a browser/Electron DAG viewer and node inspector backed by the
  Python API.

## North Star

Build a YAML-only orchestration harness where:

- The orchestrator owns coordination, not execution.
- Workers own bounded execution, not global truth.
- The harness enforces workflow safety with deterministic rules.
- The ledger records durable mission truth with provenance.
- Advisors are lazy and budget-gated.
- The workbench makes the system inspectable before it becomes deeply editable.

## Line A: Harness Runtime

This is the main line. It makes orchestration safe, auditable, and recoverable.

### A1: Mission, Ledger, Workflow Foundation

Status: started.

Implemented:

- Mission YAML loader.
- Ledger YAML loader.
- Workflow YAML loader.
- Deterministic workflow compiler.
- Demo coder/reviewer/committer mission.
- CLI:
  - `agents-swarm mission validate`
  - `agents-swarm workflow compile`

Next:

- Make terminal event and event reference semantics part of the canonical docs.
- Keep examples compiler-valid.

### A2: Event Ledger And Provenance

Status: next.

Goal: make mission state append-only and replayable.

Work:

- Add event append helpers.
- Enforce event provenance.
- Enforce public finding provenance.
- Separate raw worker reports from accepted public ledger state.
- Add replay helper that derives current mission state from event history.

Acceptance:

- Events can be appended to a YAML ledger.
- Public findings without provenance are rejected.
- Replaying event history explains why a workflow node is blocked, runnable, or complete.

### A3: Gatekeeper

Status: planned.

Goal: decide what can run now.

Work:

- Evaluate `all_of` and `any_of` waits.
- Evaluate approval gates.
- Evaluate budget gates.
- Reject committer-like actions without patch and review events.

Acceptance:

- A committer node becomes runnable only after `patch_ready` and
  `review_approved`.
- A blocked node returns structured reasons.

### A4: Advisor Policy And Budget Estimator

Status: planned.

Goal: make advisor usage measurable instead of instinctive.

Work:

- Implement deterministic advisor gating policy from `docs/protocol/advisor_policy.md`.
- Add a small model price table format.
- Estimate P50/P90 token and cost ranges.
- Record `good_call`, `bad_call`, `good_skip`, and `missed_call` outcomes.

Acceptance:

- Low-risk single-node workflows skip advisors.
- High-risk parallel workflows invoke advisor review.
- Estimation does not call an LLM.

### A5: Orchestrator Decision Artifacts

Status: planned.

Goal: persist orchestrator decisions as structured YAML.

Work:

- Add loaders/validators for routing decisions, assignments, turn reports, and
  review decisions.
- Keep orchestrator outputs machine-readable.
- Reject decision artifacts that attempt to bypass harness gates.

Acceptance:

- A complete orchestrator proposal can be compiled before worker dispatch.

## Line B: Workbench UI

This is the product surface line. It should expose current runtime state before
it edits or dispatches work.

Detailed task cards live in `docs/roadmap/workbench_tasklist.md`.

### B1: Operational DAG Viewer

Status: planned.

Source tasks:

- WB-01 Review Status Actions.
- WB-02 Run Record Selection.
- WB-03 Review Error Handling.
- WB-04 Validation Endpoint.
- WB-05 Diagnostics Panel.
- WB-06 Empty And Missing Data States.

Goal: make the current DAG/run-record workflow inspectable and safe to review.

### B2: File And Workspace Ergonomics

Status: planned.

Source tasks:

- WB-10 Browser Path Controls.
- WB-11 Electron File Picker Integration.

Goal: let users point the workbench at real local YAML DAGs and run directories.

### B3: Safe DAG Metadata Editing

Status: deferred.

Source tasks:

- WB-07 DAG Save API For Node Metadata.
- WB-08 Metadata Edit Form.
- WB-09 Unsaved Changes Guard.

Reason for deferral:

- The project is moving toward mission/workflow/ledger semantics.
- DAG editing is useful, but it should not outrun harness validation.

### B4: Dispatch Preparation

Status: deferred.

Source tasks:

- WB-15 Assignment Matrix View.
- WB-16 Prompt Export Panel.

Reason for deferral:

- Prompt export remains useful.
- Actual model dispatch waits until harness gates, ledger, and advisor policy are
  in place.

### B5: Graph Editing

Status: later.

Source tasks:

- WB-12 Add Node Workflow.
- WB-13 Dependency Editing.
- WB-14 Drag-To-Connect Dependencies.

Reason for deferral:

- Structural editing is high risk.
- It should reuse validation and compiler semantics from the harness line.

## Where The Lines Meet

The workbench should gradually become the visual surface for harness runtime:

- Mission view: goal, status, budget, default mode.
- Workflow view: roles, events, nodes, waits, gates, terminal events.
- Ledger view: public findings, decisions, risks, artifacts, provenance.
- Gatekeeper view: runnable, blocked, completed, and why.
- Advisor view: invoke/skip decisions and expected ROI.
- Replay view: event history and derived state.

This means the UI should not become a separate source of business rules. Python
runtime remains the source of truth.

## Current Priority Order

1. A2 Event Ledger And Provenance.
2. A3 Gatekeeper.
3. B1 Operational DAG Viewer.
4. A4 Advisor Policy And Budget Estimator.
5. B2 File And Workspace Ergonomics.
6. A5 Orchestrator Decision Artifacts.
7. B3 Safe DAG Metadata Editing.
8. B4 Dispatch Preparation.
9. B5 Graph Editing.

## Decision Rules

- If a task improves runtime correctness, it usually belongs to Line A.
- If a task improves human inspection or local operation, it belongs to Line B.
- If a task adds write capability, ensure the corresponding runtime validation exists first.
- If a task adds model dispatch, defer it until workflow gates and ledger replay exist.
- If a task is only visually useful but not operationally necessary, keep it behind runtime safety work.

## Non-Goals For The Next Phase

- No real model provider dispatch.
- No automatic subagent spawning.
- No visual workflow drag editor.
- No full-ledger broadcast.
- No worker writes to canonical ledger.
- No advisor policy auto-tuning by LLM.
