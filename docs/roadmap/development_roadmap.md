# Development Roadmap

This document is the project-level roadmap. It explains how the runtime/harness
line and the workbench/UI line fit together, so day-to-day implementation does
not drift into unrelated details.

## Current Position

The project currently has two runtime layers:

- DAG runtime: YAML DAG loading, ready-node calculation, prompt rendering,
  review status updates, and an operational browser/Electron viewer.
- Harness runtime: deterministic protocol validation, append-only ledger and
  replay, gatekeeper decisions, assignment/result boundaries, agent doctor
  checks, isolated sessions, result packaging, outcome metrics, and dispatch
  readiness checks.

Milestones 1, 2, and 2.5 are complete. The next runtime priority is completing
advisor outcome learning and the remaining orchestrator decision artifacts.
Those tasks form Runtime Harness Milestone 3.

The project has one UI surface:

- Workbench: a browser/Electron planning-DAG viewer/editor and runtime console
  backed by the Python API.

Workbench Milestones 1 and 2 are complete. The UI now separates planning-DAG
editing from runtime workflow inspection, and can present mission, ledger,
gatekeeper, replay, and mutation state without reimplementing runtime rules in
the frontend.

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

The completed runtime line already includes one explicit manual-harness golden
path for the demo mission. The next runtime milestone builds on that
acceptance spine instead of replacing it.

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

Status: completed for the M1/M2 baseline.

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

Status: completed for the M1/M2 baseline.

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

Status: completed for the M1/M2 baseline.

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

Status: started. Budget snapshots and pre-dispatch workflow selection are
implemented; advisor outcome learning remains planned.

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

Status: started. Assignment and result artifacts are implemented; broader
orchestrator routing and review decision artifacts remain planned.

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

Status: completed for the M2.5 current-state replay scope.

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

Status: completed for the Workbench M1 baseline.

Source tasks:

- WB-01 Review Status Actions.
- WB-02 Run Record Selection.
- WB-03 Review Error Handling.
- WB-04 Validation Endpoint.
- WB-05 Diagnostics Panel.
- WB-06 Empty And Missing Data States.

Goal: make the current DAG/run-record workflow inspectable and safe to review.

### B2: File And Workspace Ergonomics

Status: completed for the Workbench M1 baseline.

Source tasks:

- WB-10 Browser Path Controls.
- WB-11 Electron File Picker Integration.

Goal: let users point the workbench at real local YAML DAGs and run directories.

### B3: Safe DAG Metadata Editing

Status: completed for the Workbench M1 baseline.

Source tasks:

- WB-07 DAG Save API For Node Metadata.
- WB-08 Metadata Edit Form.
- WB-09 Unsaved Changes Guard.

Implementation note:

- The current metadata editing surface remains DAG-oriented. It is useful for
  planning workflows, but it is not yet the primary runtime console.

### B4: Dispatch Preparation

Status: completed for the Workbench M1 baseline.

Source tasks:

- WB-15 Assignment Matrix View.
- WB-16 Prompt Export Panel.

Implementation note:

- Prompt export and assignment visibility now exist, but they remain bounded to
  manual and semi-automatic runtime flows.

### B5: Graph Editing

Status: completed for the Workbench M1 baseline.

Source tasks:

- WB-12 Add Node Workflow.
- WB-13 Dependency Editing.
- WB-14 Drag-To-Connect Dependencies.

Implementation note:

- Graph editing is available for the planning DAG. It is intentionally separate
  from runtime workflow mutation and replay semantics.

### B6: Runtime Console

Status: completed for Workbench Milestone 2.

Goal: make the workbench a first-class surface for harness runtime state.

Implemented scope:

- Show runtime workflow separately from the planning DAG.
- Visualize gatekeeper and replay state directly on the runtime graph.
- Reflect accepted and rejected workflow mutations on the runtime canvas.
- Expose ledger, assignment, supersession, and blocked-reason inspection
  without making the frontend invent business rules.
- Let operators update runtime workflow and ledger paths from the UI.

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

The current workbench consumes runtime APIs directly for workflow, mutation,
gatekeeper, replay, mission, and ledger state. It still treats Python runtime
responses as authoritative; frontend state is limited to presentation,
selection, and operator input.

## Current Priority Order

1. Complete A4 Advisor Policy outcome learning.
2. Complete A5 Orchestrator Decision Artifacts.
3. Open Runtime Harness Milestone 3 and land its acceptance spine.
4. Define the next workbench milestone only after M3 API shapes stabilize.
5. Return to post-M2.5 replay evolution only after runtime decisions and UI
   inspection surfaces are stable.

## Decision Rules

- If a task improves runtime correctness, it usually belongs to Line A.
- If a task improves human inspection or local operation, it belongs to Line B.
- If a task adds write capability, ensure the corresponding runtime validation exists first.
- If a task adds agent dispatch, defer it until workflow gates, result import,
  ledger replay, and doctor checks exist.
- If a task is only visually useful but not operationally necessary, keep it behind runtime safety work.
- If a task couples planning-DAG editing with runtime-workflow state, keep the
  runtime model authoritative and let the UI reflect it rather than derive it.

## Non-Goals For The Next Milestone

- No internal coding-agent harness.
- No automatic agent dispatch before doctor checks, gates, and replay.
- No automatic subagent spawning.
- No visual workflow drag editor.
- No full-ledger broadcast.
- No worker writes to canonical ledger.
- No worker applies workflow mutation directly.
- No full temporal workflow replay before the M3+ replay milestone.
- No advisor policy auto-tuning by LLM.
- No runtime canvas/list synchronization by ad hoc frontend state outside the
  authoritative runtime API responses.
