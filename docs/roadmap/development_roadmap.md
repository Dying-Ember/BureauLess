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
Detailed task cards live in
[`../tasks/runtime_harness_tasklist.md`](../tasks/runtime_harness_tasklist.md).

### Landing Strategy

The project should land in three stages:

1. Manual Harness: generate assignments, export prompts, import result YAML and
   artifacts, validate provenance, append ledger events, and review in the
   workbench. No automatic agent dispatch.
2. Semi-Automatic Runtime: launch one external agent in an isolated worktree,
   collect results, and keep commit/push/deploy behind gates.
3. Policy-Driven Automation: add agent/runtime selection, retries, fallback,
   and budget-aware dispatch only after gates, replay, and budget checks are
   stable.

The first milestone is not "automatic completion". It is making agent work
bounded, auditable, and unable to damage canonical state.

The first runtime does not implement an internal coding-agent harness. It wraps
external agent runtimes at assignment/session/result boundaries and records
session-level outcome metrics.

The next runtime milestone starts by formalizing one explicit manual-harness
golden path for the demo mission. That path is the acceptance spine for every
later semi-automatic session feature.

The current runtime line also exposes a reviewable semi-automatic demo through
the API. That demo prepares a workspace, exports an assignment, runs one
bounded session, packages a result, imports it into the ledger, and leaves the
resulting mission state inspectable through the normal mission/workflow/ledger/
replay/gatekeeper endpoints.

The local development entrypoint for that API is `npm run api:dev`. It pins
execution to the repo-local `.venv`, tolerates another active shell virtual
environment, and records the selected API URL in `.bureauless-api-url` when it
has to move off the default port. The browser workbench reads that file at
startup, so changing API ports requires a `web:dev` restart rather than manual
proxy edits.

Issue
[#1](https://github.com/Dying-Ember/BureauLess/issues/1) tracks a proposed
bridge milestone between the semi-automatic runtime and later policy-driven
automation: controlled workflow mutation. The goal is to let workers report
that the current workflow is structurally incomplete without allowing them to
change workflow or ledger state directly. This work is documented as
[`../rfcs/workflow_mutation_proposal.md`](../rfcs/workflow_mutation_proposal.md)
and broken down in
[`../tasks/runtime_harness_milestone_2_5_tasklist.md`](../tasks/runtime_harness_milestone_2_5_tasklist.md).

### A1: Mission, Ledger, Workflow Foundation

Status: started.

Implemented:

- Mission YAML loader.
- Ledger YAML loader.
- Workflow YAML loader.
- Deterministic workflow compiler.
- Demo coder/reviewer/committer mission.
- CLI:
  - `bureauless mission validate`
  - `bureauless workflow compile`

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
- Enforce immutable artifact references with `artifact_id` and `sha256`.
- Record timeout, retry, cancellation, supersession, budget-limit, and
  artifact-invalidation events.
- Separate raw worker reports from accepted public ledger state.
- Add replay helper that derives current mission state from event history.

Acceptance:

- Events can be appended to a YAML ledger.
- Public findings without provenance are rejected.
- Accepted artifact references verify against recorded hashes.
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
- Implement the budget oracle snapshot format from `docs/architecture/context_economy.md`.
- Implement workflow selection checks from `docs/protocol/workflow_selection_policy.md`.
- Estimate P50/P90 token and cost ranges.
- Record `good_call`, `bad_call`, `good_skip`, and `missed_call` outcomes.

Acceptance:

- Low-risk single-node workflows skip advisors.
- High-risk parallel workflows invoke advisor review.
- Estimation does not call an LLM.
- Complex workflows without a selection-policy rationale are rejected.

### A5: Orchestrator Decision Artifacts

Status: planned.

Goal: persist orchestrator decisions as structured YAML.

Work:

- Add loaders/validators for routing decisions, assignments, turn reports, and
  review decisions.
- Keep orchestrator outputs machine-readable.
- Reject decision artifacts that attempt to bypass harness gates.
- Enforce worker/orchestrator invariants from `docs/protocol/harness_protocol.md`.

Acceptance:

- A complete orchestrator proposal can be compiled before worker dispatch.

### A6: Controlled Workflow Mutation

Status: proposed.

Goal: let agents propose workflow changes discovered during execution without
letting them mutate canonical workflow state.

Tracking:

- GitHub issue:
  [#1 RFC: Controlled Workflow Mutation](https://github.com/Dying-Ember/BureauLess/issues/1)
- RFC:
  [`../rfcs/workflow_mutation_proposal.md`](../rfcs/workflow_mutation_proposal.md)
- Task list:
  [`../tasks/runtime_harness_milestone_2_5_tasklist.md`](../tasks/runtime_harness_milestone_2_5_tasklist.md)

Work:

- Add mutation proposal artifacts and ledger event types.
- Route proposal acceptance/rejection through orchestrator or human approval.
- Apply accepted mutations to current workflow only.
- Supersede affected assignments conservatively.
- Support current-state replay on the accepted workflow.
- Defer full temporal replay to a later milestone.

Acceptance:

- Workers can propose structural changes without expanding assignment scope.
- Accepted mutation events deterministically update current workflow.
- Superseded assignments no longer satisfy downstream gates.
- Gatekeeper can explain `mutation_pending`, `needs_review`, and
  `superseded` states.
- Temporal workflow replay remains out of scope.

## Line B: Workbench UI

This is the product surface line. It should expose current runtime state before
it edits or dispatches work.

Detailed task cards live in
[`../tasks/workbench_tasklist.md`](../tasks/workbench_tasklist.md).

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
- Actual agent dispatch waits until harness gates, result import, ledger replay,
  and doctor checks are in place.

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
- Mutation view: pending proposals, accept/reject decisions, affected
  assignments, and supersession reasons.

This means the UI should not become a separate source of business rules. Python
runtime remains the source of truth.

## Current Priority Order

1. A2 Event Ledger And Provenance.
2. A3 Gatekeeper.
3. Runtime assignment export and result import.
4. Agent registry and doctor checks.
5. Session-level outcome metrics.
6. B1 Operational DAG Viewer.
7. A6 Controlled Workflow Mutation.
8. A4 Advisor Policy And Budget Estimator.
9. B2 File And Workspace Ergonomics.
10. A5 Orchestrator Decision Artifacts.
11. B3 Safe DAG Metadata Editing.
12. B4 Dispatch Preparation.
13. B5 Graph Editing.

## Decision Rules

- If a task improves runtime correctness, it usually belongs to Line A.
- If a task improves human inspection or local operation, it belongs to Line B.
- If a task adds write capability, ensure the corresponding runtime validation exists first.
- If a task adds agent dispatch, defer it until workflow gates, result import,
  ledger replay, and doctor checks exist.
- If a task is only visually useful but not operationally necessary, keep it behind runtime safety work.

## Non-Goals For The Next Milestone

- No internal coding-agent harness.
- No automatic agent dispatch before doctor checks, gates, and replay.
- No automatic subagent spawning.
- No visual workflow drag editor.
- No full-ledger broadcast.
- No worker writes to canonical ledger.
- No worker applies workflow mutation directly.
- No full temporal workflow replay in the controlled mutation bridge milestone.
- No advisor policy auto-tuning by LLM.
