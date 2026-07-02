# Development Roadmap

This document is the project-level roadmap. It explains how the runtime/harness
line and the workbench/UI line fit together, so day-to-day implementation does
not drift into unrelated details.

The roadmap owns capability sequencing and milestone history. The milestone
indexes identify completed and planned delivery units. Individual milestone
task lists own task status, implementation notes, and acceptance evidence. When
these documents disagree, shipped behavior and the checked task list must be
used to repair the roadmap and indexes in the same change.

## Current Position

The project currently has two runtime layers:

- DAG runtime: YAML DAG loading, ready-node calculation, prompt rendering,
  review status updates, and an operational browser/Electron viewer.
- Harness runtime: deterministic protocol validation, append-only ledger and
  replay, gatekeeper decisions, assignment/result boundaries, agent doctor
  checks, isolated sessions, result packaging, outcome metrics, and dispatch
  readiness checks.

Milestones 1, 2, 2.5, and 3 are complete for the runtime/harness line. The
current runtime now includes advisor outcome learning, routing/dispatch
decision artifacts, bounded deterministic context delivery, context telemetry,
and the integrated M3 acceptance spine on top of the earlier ledger/replay and
gatekeeper baseline. Milestone 3 also landed the initial narrow real-agent
binding spine: `codex-cli` is the first real worker target for the maintained
demo path. This is still not a full provider platform milestone. Broader agent
and provider expansion, including deeper `opencode` customization, remains
post-M3 work.

The project has one UI surface:

- Workbench: a browser/Electron planning-DAG viewer/editor and runtime console
  backed by the Python API.

Workbench Milestones 1, 2, 3, and 4 are complete. The UI now separates
planning-DAG editing from runtime workflow inspection, can load explicit
runtime sources directly from live-demo URLs, and can present mission, ledger,
gatekeeper, replay, and mutation state without reimplementing runtime rules in
the frontend. It now provides manifest-backed visual inspection for the
decision, outcome, context, telemetry, and dispatch artifacts added in Runtime
Harness Milestone 3.

## Milestone History

This roadmap tracks both the delivery order and the historical shape of the
system. The task lists remain the implementation source of truth; this section
summarizes what has already landed so the current position is easy to read
without reconstructing it from commits.

### Implemented Runtime Milestones

- Runtime Harness Milestone 1:
  protocol hardening, append-only ledger/replay, gatekeeper, assignment
  export, result import, agent registry, session wrapping, metrics, budget
  snapshots, and baseline runtime API coverage.
  Source: [`../tasks/runtime_harness_milestone_1_tasklist.md`](../tasks/runtime_harness_milestone_1_tasklist.md)
- Runtime Harness Milestone 2:
  reliable real-agent execution loop hardening, isolated sessions,
  compatibility checks, and end-to-end runtime smoke coverage.
  Source: [`../tasks/runtime_harness_milestone_2_tasklist.md`](../tasks/runtime_harness_milestone_2_tasklist.md)
- Runtime Harness Milestone 2.5:
  controlled workflow mutation, where workers can propose structural changes
  but only accepted ledger events can change current workflow state.
  Source: [`../tasks/runtime_harness_milestone_2_5_tasklist.md`](../tasks/runtime_harness_milestone_2_5_tasklist.md)
- Runtime Harness Milestone 3:
  advisor outcome learning, orchestrator decision artifacts, node outcomes,
  bounded deterministic context delivery, context telemetry, and one
  maintained `codex-cli` demo path.
  Source: [`../tasks/runtime_harness_milestone_3_tasklist.md`](../tasks/runtime_harness_milestone_3_tasklist.md)

### Implemented Workbench Milestones

- Workbench Milestone 1:
  planning-DAG review actions, diagnostics, file selection, metadata editing,
  graph editing, prompt export, and assignment visibility.
  Source: [`../tasks/workbench_milestone_1_tasklist.md`](../tasks/workbench_milestone_1_tasklist.md)
- Workbench Milestone 2:
  runtime console coverage for mission, workflow, ledger, replay, gatekeeper,
  and mutation inspection.
  Source: [`../tasks/workbench_milestone_2_tasklist.md`](../tasks/workbench_milestone_2_tasklist.md)
- Workbench Milestone 3:
  runtime-source URL loading, persisted source alignment, planning/runtime
  action clarity, and full workbench smoke coverage.
  Source: [`../tasks/workbench_milestone_3_tasklist.md`](../tasks/workbench_milestone_3_tasklist.md)
- Workbench Milestone 4:
  manifest-backed inspection for routing/advisor, node outcome and evidence,
  context delivery, telemetry, and bounded handoff artifacts from Runtime
  Harness Milestone 3.
  Source: [`../tasks/workbench_milestone_4_tasklist.md`](../tasks/workbench_milestone_4_tasklist.md)

### Implemented Engineering Cleanup

- RFC-003 Engineering Boundary Refactor:
  shared errors boundary, CLI command ownership split, first application
  service extraction, and narrower `bureauless.protocol` package exports.
  Source: [`../tasks/engineering_boundary_refactor_tasklist.md`](../tasks/engineering_boundary_refactor_tasklist.md)

### Capability And Delivery Map

Capability sections describe the long-lived product shape. Milestones describe
the delivery order. A milestone can advance several capabilities, and a
capability can span several milestones.

| Delivery milestone | Roadmap capability contribution | State |
| --- | --- | --- |
| Runtime Harness M1 | A1 mission/workflow foundation, A2 ledger/replay, A3 gatekeeper, plus the first A4 budget and A5/A5.5 assignment/session boundaries | completed |
| Runtime Harness M2 | Hardened the A4 dispatch-readiness policy and A5.5 isolated real-agent execution loop | completed |
| Runtime Harness M2.5 | A6 controlled workflow mutation and current-state replay | completed |
| Runtime Harness M3 | Extended A1 with node outcomes, completed the current A4 and A5 scope, and proved the initial `codex-cli` A5.5 path | completed |
| Runtime Harness M4 | Close the A6 real-agent mutation intake loop and add A7 retry control plus linear temporal replay | planned |
| Workbench M1 | B1 through B5 planning-DAG inspection, editing, and dispatch preparation | completed |
| Workbench M2 | B6 runtime console for mission, workflow, ledger, gatekeeper, replay, and mutation state | completed |
| Workbench M3 | B7 runtime-source trust and planning/runtime action clarity | completed |
| Workbench M4 | B8 visual inspection for Runtime Harness M3 artifacts | completed |

## Planned Next Milestones

There is no active Workbench Milestone 5 yet. The most recent completed
workbench delivery is Workbench Milestone 4. Its task list is
[`../tasks/workbench_milestone_4_tasklist.md`](../tasks/workbench_milestone_4_tasklist.md).
It adds read-only inspection for the structured M3 runtime artifacts already
exposed by the backend: routing and advisor decisions, node outcomes and
evidence, context capsules and requests, assignments and results, turn reports,
and dispatch packets.

Runtime Harness Milestone 4 is the next planned runtime delivery. Its task list
is [`../tasks/runtime_harness_milestone_4_tasklist.md`](../tasks/runtime_harness_milestone_4_tasklist.md).
It first closes the existing real-agent mutation intake gap, then adds
bounded retry/circuit-break semantics, deterministic workflow versions, and
linear temporal replay through ledger event cursors. Provider expansion is not
part of this milestone.

RM4-00 has produced draft
[`RFC-004`](../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md).
Implementation remains blocked until its worker-intent, retry, inclusive cursor,
version transition, stale proposal, historical assignment, and compatibility
semantics are accepted into an ADR. The existing RFC-001 remains implemented
M2.5 design history rather than being silently expanded.

No additional engineering-cleanup milestone is planned. Documentation indexes,
task status, and API boundaries remain part of each delivery milestone's
acceptance work.

## North Star

Build a YAML-only orchestration harness where:

- The orchestrator owns coordination, not execution.
- Workers own bounded execution, not global truth.
- The harness enforces workflow safety with deterministic rules.
- The ledger records the minimum sufficient durable mission truth with
  provenance while native traces remain referenced evidence.
- Workers receive bounded assignment context with progressive evidence
  disclosure rather than full-ledger broadcasts.
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

The next acceptance step was not "support many agents". It was "prove one real
agent path". That M3 step is now in place: `codex-cli` can launch bounded real
tasks non-interactively, return structured result payloads, and drive the demo
workflow end to end through normal session/import/replay paths. Broader agent
and provider breadth remains out of scope until the next decision-artifact and
context work is complete.

That acceptance spine is now accompanied by one maintained integrated M3 demo
fixture. The live demo writes inspectable routing, advisor-skip, context
capsule, session, node-outcome, review-decision, metrics-summary, and ledger
artifacts into one workspace so replay, metrics, API, and workbench checks can
reuse the same bounded path.
That path has now been validated through a real `codex-cli` run and reloaded in
the workbench against the emitted `tmp/...` mission/workflow/ledger artifacts,
not only against fixture-only test doubles.

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
[`../rfcs/001-controlled-workflow-mutation.md`](../rfcs/001-controlled-workflow-mutation.md)
and broken down in
[`../tasks/runtime_harness_milestone_2_5_tasklist.md`](../tasks/runtime_harness_milestone_2_5_tasklist.md).

### A1: Mission, Ledger, Workflow Foundation

Status: completed for the M1/M2 baseline, with the M3 node-outcome/projection
spine now implemented.

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

Next:

- Compile bounded assignment context from accepted facts and expose deeper
  evidence only through scoped requests.
- Measure context fit before adapting context policy.

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

Status: completed for the Milestone 3 scope. Budget snapshots, pre-dispatch
workflow selection, advisor outcome events, price-snapshot attribution, and
deterministic scoring are implemented.

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

Status: completed for the Milestone 3 scope. Assignment, result, review
decision, routing decision, turn report, and dispatch packet artifacts are now
implemented and validated.

Goal: persist orchestrator decisions as structured YAML.

Work:

- Add loaders/validators for routing decisions, assignments, turn reports,
  dispatch packets, and review decisions.
- Keep orchestrator outputs machine-readable.
- Reject decision artifacts that attempt to bypass harness gates.
- Enforce worker/orchestrator invariants from `docs/protocol/harness_protocol.md`.

Acceptance:

- A complete orchestrator proposal can be compiled before worker dispatch.

The API surface now exposes the minimum M3 artifact set directly: routing
decisions, assignments, context capsules, context requests and resolutions,
result proposals, node outcomes, advisor outcomes, turn reports, and compiled
dispatch packets. That keeps the workbench on authoritative runtime shapes
instead of file scraping or frontend-side policy reconstruction.

### A5.5: Real Agent Binding Spine

Status: completed for the initial M3 spine.

Goal: add the smallest runtime registry needed to launch one real agent path
without turning the harness into a general provider platform.

Work:

- Bind one verified agent adapter to one provider profile and validate the
  target model/provider pair before launch.
- Reuse agent doctor and readiness outputs instead of creating a second agent
  metadata system.
- Launch `codex-cli` as the first real worker target for the M3 demo path.
- Keep provider auth injection environment-scoped and narrow.
- Defer deeper `opencode` customization until after the first real-agent demo
  path is stable.

Acceptance:

- The runtime can reject an invalid agent/provider/model binding before any
  session starts.
- One bounded `codex-cli` assignment can run non-interactively in isolation and
  produce an importable result proposal.
- The live demo path can advance `implement -> review -> commit` through real
  bounded sessions and normal ledger replay.
- This work does not expand into a broad provider marketplace, fallback mesh,
  or secret-management subsystem.

### A6: Controlled Workflow Mutation

Status: completed for the M2.5 current-state replay scope.

Goal: let agents propose workflow changes discovered during execution without
letting them mutate canonical workflow state.

Tracking:

- GitHub issue:
  [#1 RFC: Controlled Workflow Mutation](https://github.com/Dying-Ember/BureauLess/issues/1)
- RFC:
  [`../rfcs/001-controlled-workflow-mutation.md`](../rfcs/001-controlled-workflow-mutation.md)
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

### A7: Agent Mutation Intake, Retry Control, And Temporal History

Status: planned for Runtime Harness Milestone 4. Implementation has not started.

Goal: turn controlled mutation from a current-state protocol into a complete
real-agent proposal path with deterministic, read-only historical replay.

Source tasks:

- [`../tasks/runtime_harness_milestone_4_tasklist.md`](../tasks/runtime_harness_milestone_4_tasklist.md)

Draft design:

- [`../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md`](../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md)

Current gap:

- `codex-cli` can return `mutation_proposal_refs`, but the assignment contract
  does not provide a typed mutation-intent channel and couples proposal presence
  to `completed_with_proposal` execution status.
- Session/result packaging preserves the referenced artifact but does not
  validate its YAML as a mutation proposal or register a
  `workflow_mutation_proposed` event.
- Existing mutation APIs inspect and decide proposal events that already exist;
  they do not complete agent proposal intake.

Planned work:

- Let a worker return a minimal declarative mutation intent as part of its normal
  result, without adding a mutation-specific wrapper agent.
- Give every worker the inert structural escape hatch while reserving approval
  and application authority for the orchestrator, deterministic policy, or a
  human.
- Have Bureauless deterministically bind the intent to assignment, session,
  agent, workflow, base version, canonical IDs, and approval policy.
- Validate intents and serialize canonical proposal artifacts before atomically
  registering inert proposal events.
- Preserve a valid execution result when its optional mutation intent is invalid.
- Classify recoverable execution errors separately from structural and repeated
  deterministic failures; bound retries by reason, attempt/token budget, and
  changed evidence or strategy.
- Derive deterministic workflow versions from accepted mutations in append-only
  ledger order.
- Replay workflow, assignment, node, mutation, and gatekeeper state through an
  explicit event cursor.
- Expose read-only timeline, historical snapshot, diff, and explanation APIs.

Acceptance boundary:

- A maintained real-agent demo reaches pending mutation review without manual
  ledger editing or granting the agent canonical write authority.
- Recoverable agent/infrastructure errors may retry within policy, while
  unchanged deterministic or structural failures cannot consume another agent
  turn indefinitely.
- Explicit acceptance creates one deterministic child workflow version.
- Historical replay never consults future events and final-cursor replay equals
  current-state replay.
- Branching, rollback, automatic acceptance, provider expansion, and Workbench
  timeline UI remain deferred.

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
- Decision view: routing rationale, rejected modes, advisor decisions, and
  scored advisor outcomes.
- Outcome view: node results, evidence references, workspace deltas, accepted
  findings, rejected findings, and review decisions.
- Context view: initial capsules, policy versions, included facts and risks,
  scoped requests, and progressively disclosed evidence.
- Dispatch view: assignment, result, turn-report, and compiled dispatch-packet
  boundaries.

This means the UI should not become a separate source of business rules. Python
runtime remains the source of truth.

The current workbench consumes runtime APIs directly for workflow, mutation,
gatekeeper, replay, mission, and ledger state. It still treats Python runtime
responses as authoritative; frontend state is limited to presentation,
selection, and operator input.

### B7: Runtime Source Trust And Operator Clarity

Status: completed for Workbench Milestone 3.

Source tasks:

- WB3-01 Normalize Runtime Source URL Parameters.
- WB3-02 Auto-Load Explicit Runtime Sources.
- WB3-03 Runtime Source Status Feedback.
- WB3-04 Clarify Planning Apply Availability.
- WB3-05 Separate Planning And Runtime Action Copy.
- WB3-06 Smoke Coverage For Live-Demo URL Loading.
- WB3-07 Document Workbench Milestone 3 Completion.

Goal: make runtime artifacts opened from links behave like trustworthy
workbench sessions without moving runtime semantics into the frontend.

Implemented scope:

- Treat URL-provided runtime sources as authoritative initial state.
- Auto-load live-demo runtime artifacts without a manual apply step.
- Show compact status for loaded, loading, pending, and failed runtime-source
  states.
- Keep planning and runtime actions visibly distinct when backend write
  contracts differ.
- Preserve the Python runtime as the source of truth while making the runtime
  console easier to trust and operate.

### B8: Runtime M3 Artifact Inspection

Status: completed in Workbench Milestone 4.

Source tasks:

- WB4-01 Runtime Artifact Session Manifest API.
- WB4-02 M3 Artifact API Client And Source Model.
- WB4-03 Routing And Advisor Inspector.
- WB4-04 Node Outcome And Evidence Inspector.
- WB4-05 Context Delivery Inspector.
- WB4-06 Budget And Context Telemetry Inspector.
- WB4-07 Assignment, Result, Turn, And Dispatch Inspector.
- WB4-08 M3 Demo Inspection Smoke Coverage.

Task list:
[`../tasks/workbench_milestone_4_tasklist.md`](../tasks/workbench_milestone_4_tasklist.md)

Goal: close the current visual-inspection gap between Runtime Harness M3 and the
Workbench while keeping all runtime rules and artifact validation in Python.

Acceptance boundary:

- One validated manifest API discovers the related M3 artifacts, and all
  read-only M3 inspection endpoints have typed frontend clients and visible
  inspection paths.
- Operators can follow routing, advisor, outcome, evidence, context,
  budget/telemetry, assignment, result, turn-report, and dispatch references
  through the maintained M3 demo.
- Missing artifacts remain explicit and do not break baseline runtime views.
- No dispatch action, runtime policy, YAML parsing, or canonical-state mutation
  moves into the frontend.

## Current Priority Order

1. Review draft RFC-004 and accept temporal replay, mutation-intake, and retry
   semantics into an ADR before implementation.
2. Close the version-bound real-agent mutation proposal path before treating
   mutation history as an end-to-end runtime capability.
3. Implement failure classification and stuck-loop circuit breaking before the
   maintained real-agent M4 demo.
4. Implement linear event-cursor replay and its read-only API after workflow
   version semantics are fixed.
5. Keep provider expansion, replay branches, rollback, and Workbench history UI
   outside Runtime Harness Milestone 4.
6. Defer policy auto-tuning and broader automatic dispatch until a later
   runtime milestone explicitly owns them.

## Decision Rules

- If a task improves runtime correctness, it usually belongs to Line A.
- If a task improves human inspection or local operation, it belongs to Line B.
- If a task adds write capability, ensure the corresponding runtime validation exists first.
- If a task adds agent dispatch, defer it until workflow gates, result import,
  ledger replay, and doctor checks exist.
- If a retry does not change evidence, input, strategy, assignment revision, or
  workflow version, require a classified transient failure or open the circuit.
- If a task is only visually useful but not operationally necessary, keep it behind runtime safety work.
- If a task couples planning-DAG editing with runtime-workflow state, keep the
  runtime model authoritative and let the UI reflect it rather than derive it.

## Non-Goals For Workbench Milestone 4

- No internal coding-agent harness.
- No broader automatic agent dispatch or provider expansion.
- No automatic subagent spawning.
- No runtime-workflow drag editor; the existing planning-DAG editor remains.
- No full-ledger broadcast.
- No worker writes to canonical ledger.
- No worker applies workflow mutation directly.
- No full temporal workflow replay before the M3+ replay milestone.
- No advisor policy auto-tuning by LLM.
- No runtime canvas/list synchronization by ad hoc frontend state outside the
  authoritative runtime API responses.
