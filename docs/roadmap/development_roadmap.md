# Development Roadmap

This document is the project-level roadmap. It explains how the runtime/harness
line and the workbench/UI line fit together, so day-to-day implementation does
not drift into unrelated details.

The roadmap owns capability sequencing and milestone history. The milestone
indexes identify completed and planned delivery units. Individual milestone
task lists own task status, implementation notes, and acceptance evidence. When
these documents disagree, shipped behavior and the checked task list must be
used to repair the roadmap and indexes in the same change.

Post-completion capability gaps are handled through
[`../audits/README.md`](../audits/README.md). An audit preserves historical task
status, narrows overstated capability language, and assigns remediation to a
new or existing milestone. RFCs and ADRs are required only when the remediation
still needs a semantic or architectural decision.

## Current Position

The project currently has two runtime layers:

- DAG runtime: YAML DAG loading, ready-node calculation, prompt rendering,
  review status updates, and an operational browser/Electron viewer.
- Harness runtime: deterministic protocol validation, append-only ledger and
  replay, gatekeeper decisions, assignment/result boundaries, agent doctor
  checks, isolated sessions, result packaging, outcome metrics, and dispatch
  readiness checks.

Milestones 1, 2, 2.5, and 3 delivered their declared protocol, validation,
fixture, API, and maintained-demo scopes. The runtime includes advisor outcome
learning, routing/dispatch decision artifacts, bounded deterministic context
artifacts, context telemetry, and a narrow `codex-cli` worker path.

The closed
[`runtime execution gap analysis`](../audits/2026-07-02-runtime-execution-gap-analysis.md)
found that several M2/M3 artifacts did not authoritatively control the live
session path. Runtime M3.5 is complete: it closes result acceptance, executable
dispatch, context continuation, cancellation, truthful telemetry, generic run
bundles, advisor invocation, and cross-capability acceptance. Broader agent and
provider expansion remains outside this remediation.

RM35-01 through RM35-08 are complete. Ledger v2 and staged acceptance
close REX-002; the validated pre-launch dispatch bridge closes REX-003; live
process-group cancellation, supersession, and partial-evidence retention close
REX-005; bounded context continuation closes REX-004; observed/degraded
turn-report telemetry closes REX-006; reusable ordinary-session run bundles and
Workbench inspection close REX-007; deterministic skip/invoke policy,
recommendation-only calls, observed cost linkage, and scored outcomes close
REX-008. The maintained execution-spine command closes end-to-end acceptance.
REX-001 was closed in Runtime M4. The next runtime gap is provider-side
telemetry attribution for model/provider/token/cost/cache evidence on the
maintained OpenAI-compatible path.

The project has one UI surface:

- Workbench: a browser/Electron planning-DAG viewer/editor and runtime console
  backed by the Python API.

Workbench Milestones 1, 2, 3, and 4 are complete. The UI now separates
planning-DAG editing from runtime workflow inspection, can load explicit
runtime sources directly from live-demo URLs, and can present mission, ledger,
gatekeeper, replay, and mutation state without reimplementing runtime rules in
the frontend. It provides manifest-backed visual inspection for the decision,
outcome, context, telemetry, and dispatch artifacts added in Runtime Harness
Milestone 3. The same manifest API now inspects maintained demo and
ordinary-session bundles, with missing optional evidence represented explicitly.

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
  maintained `codex-cli` demo path. This is complete for its artifact and demo
  boundary; the post-completion execution-spine audit is tracked separately.
  Source: [`../tasks/runtime_harness_milestone_3_tasklist.md`](../tasks/runtime_harness_milestone_3_tasklist.md)

### Implemented Runtime Remediation

- Runtime Harness Milestone 3.5:
  authoritative result acceptance, executable pre-launch dispatch, real context
  continuation and cancellation, truthful turn reports, reusable run bundles,
  advisor invocation evidence, and one failing-on-error execution-spine
  acceptance path.
  Source: [`../tasks/runtime_harness_milestone_3_5_tasklist.md`](../tasks/runtime_harness_milestone_3_5_tasklist.md)
  Audit: [`2026-07-02 Runtime Execution Gap Analysis`](../audits/2026-07-02-runtime-execution-gap-analysis.md)

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
- Workbench Milestone 5:
  planned read-only Runtime M4 timeline, historical snapshot, version
  selection, and workflow/state diff inspection backed by the runtime history
  APIs.
  Source: [`../tasks/workbench_milestone_5_tasklist.md`](../tasks/workbench_milestone_5_tasklist.md)

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
| Runtime Harness M2 | Hardened the A4 dispatch-readiness policy and A5.5 isolated real-agent execution loop; live process cancellation was later delivered in M3.5 | completed declared scope |
| Runtime Harness M2.5 | A6 controlled workflow mutation and current-state replay | completed |
| Runtime Harness M3 | Extended A1 with node outcomes, added A4/A5 artifacts, and proved the initial demo-scoped `codex-cli` A5.5 path | completed artifact/demo scope |
| Runtime Harness M3.5 | Acceptance, dispatch, context continuation, lifecycle control, truthful turn reports, reusable run bundles, advisor invocation, and execution-spine E2E acceptance | completed |
| Runtime Harness M4 | Close the A6 real-agent mutation intake loop and add A7 retry control plus linear temporal replay | completed |
| Runtime Harness M5 | Add provider-side telemetry capture, usage attribution, and backtest-ready metrics on the maintained OpenAI-compatible path | completed |
| Workbench M1 | B1 through B5 planning-DAG inspection, editing, and dispatch preparation | completed |
| Workbench M2 | B6 runtime console for mission, workflow, ledger, gatekeeper, replay, and mutation state | completed |
| Workbench M3 | B7 runtime-source trust and planning/runtime action clarity | completed |
| Workbench M4 | B8 visual inspection for Runtime Harness M3 artifacts | completed |
| Workbench M5 | Read-only Runtime M4 temporal inspection for timeline, snapshot, version selection, and diff explanation | completed |
| Workbench M6 | Validated runtime operator actions for context resolution, dispatch/launch, acceptance-spine controls, doctoring visibility, and smoke-backed error surfaces | completed |
| Workbench M7 | Guided runtime bootstrap, manifest/run-bundle navigation, and artifact-readiness visibility on top of the completed runtime surfaces | completed |

## Planned Next Milestones

The most recent completed workbench deliveries are Workbench Milestones 4, 5,
and 6. Workbench Milestone 4 task list is
[`../tasks/workbench_milestone_4_tasklist.md`](../tasks/workbench_milestone_4_tasklist.md).
It adds read-only inspection for the structured M3 runtime artifacts already
exposed by the backend: routing and advisor decisions, node outcomes and
evidence, context capsules and requests, assignments and results, turn reports,
and dispatch packets.

Workbench Milestone 5 task list is
[`../tasks/workbench_milestone_5_tasklist.md`](../tasks/workbench_milestone_5_tasklist.md).
It completes the read-only Runtime M4 history surface for timeline, version
selection, historical snapshot explanation, temporal diff inspection, and
smoke coverage without moving replay rules into the frontend.

Workbench Milestone 6 task list is
[`../tasks/workbench_milestone_6_tasklist.md`](../tasks/workbench_milestone_6_tasklist.md).
It is complete and turns selected validated runtime APIs into operator-facing
actions for context resolution, dispatch packet compile, bounded session
launch, result staging, review import, outcome decisions, launch doctoring,
and structured backend failure visibility while preserving Python runtime
ownership of every write and post-action refresh.

Workbench Milestone 7 is now complete as the follow-on UI milestone. Its task list is
[`../tasks/workbench_milestone_7_tasklist.md`](../tasks/workbench_milestone_7_tasklist.md).
WB7-01 through WB7-05 are complete: the Workbench now has a typed runtime-demo
bootstrap boundary, a guided runtime entry block that commits backend-owned
runtime paths into the existing runtime view, a source navigator that shows
provenance plus bounded switching between returned roots, an artifact-readiness
summary, and smoke coverage that locks the whole guided entry flow in place.

Runtime Harness Milestone 3.5 is complete. Its task list is
[`../tasks/runtime_harness_milestone_3_5_tasklist.md`](../tasks/runtime_harness_milestone_3_5_tasklist.md).
It closes the confirmed execution-spine gaps and proves the accepted ledger
history on which Runtime M4 may build.

RM35-01 produced
[`RFC-005`](../rfcs/005-authoritative-result-acceptance-spine.md). Runtime code
for acceptance compatibility is implemented under accepted
[`ADR-005`](../adrs/005-authoritative-result-acceptance-spine/001-accepted-design.md).

Runtime Harness Milestone 4 is complete. Its task list is
[`../tasks/runtime_harness_milestone_4_tasklist.md`](../tasks/runtime_harness_milestone_4_tasklist.md).
It closes the existing real-agent mutation intake gap, then adds bounded
retry/circuit-break semantics, deterministic workflow versions, and linear
temporal replay through ledger event cursors. Provider expansion is not part of
either milestone.

RM4-00 accepted
[`RFC-004`](../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md)
through
[`ADR-004`](../adrs/004-temporal-replay-mutation-intake-and-retry-control/001-accepted-design.md).
Worker-intent, retry, inclusive cursor, version transition, stale proposal,
historical assignment, and compatibility semantics are settled. RM4-01 through
RM4-11 implemented the worker intent, trusted envelope,
universal assignment escape hatch, structured result transport, deterministic
proposal registration, bounded retry/circuit control, the maintained two-turn
mutation/retry acceptance path, workflow version projection, inclusive
event-prefix replay, assignment validity across versions, historical
inspection APIs, determinism/scale guardrails, and protocol/workbench handoff
closure. Runtime M4 is complete.
The required M3.5 foundations are closed.
The existing RFC-001 remains implemented M2.5 design history rather than
being silently expanded.

Runtime Harness Milestone 5 is complete. Its task
list is
[`../tasks/runtime_harness_milestone_5_tasklist.md`](../tasks/runtime_harness_milestone_5_tasklist.md).
It added a backend/debug-first provider-side telemetry boundary for the
maintained OpenAI-compatible path so model, provider, token, cost, and
cache-related usage can be attributed to assignment/session/result boundaries
without pretending the harness can infer billing data on its own. Workbench
compatibility remains deferred until the backend evidence shape is worth a
dedicated UI surface.

The selected source of truth for Runtime M5 is trusted provider-side usage on
the maintained `codex-cli + openai-compatible` path. That evidence is captured
by the local proxy, merged into `outcome_metrics`, exposed through the existing
metrics readers, and proven by packaging/import/summarize fixtures. Still out
of scope after M5: generic multi-agent telemetry, provider-wide proxy meshes,
token guessing heuristics, and any replay semantics derived from billing data.

No additional engineering-cleanup milestone is planned. Documentation indexes,
task status, and API boundaries remain part of each delivery milestone's
acceptance work.

The confirmed RFC-007 implementation debt is tracked separately in
[`../tasks/control_runtime_boundary_follow_up_tasklist.md`](../tasks/control_runtime_boundary_follow_up_tasklist.md).
It is deliberately not a Runtime M6 or Workbench M8: CRT-001 through CRT-003
are boundary-maintenance work, while CRT-004 must reuse existing operator
readers before a dedicated UI delivery is justified.

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
path for the demo mission. The active runtime milestone builds on that
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

Status: artifact and scoring scope completed in Milestone 3. Budget snapshots,
workflow selection, advisor outcome events, price-snapshot attribution, and
deterministic scoring are implemented. RM35-07 adds maintained skip and invoked
paths with recommendation-only authority, observed call cost, independent
orchestrator disposition, and scored outcomes.

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

Status: schema, validation, API, and demo-inspection scope completed in
Milestone 3. Acceptance, dispatch, context continuation, turn-report
integration, reusable run-bundle discovery, advisor invocation evidence, and
cross-capability acceptance are implemented in RM35-01 through RM35-08.

Goal: persist orchestrator decisions as structured YAML.

Work:

- Add loaders/validators for routing decisions, assignments, turn reports,
  dispatch packets, and review decisions.
- Keep orchestrator outputs machine-readable.
- Reject decision artifacts that attempt to bypass harness gates.
- Enforce worker/orchestrator invariants from `docs/protocol/harness_protocol.md`.

Acceptance:

- A complete orchestrator proposal can be compiled and validated independently.
- Runtime M3.5 must make that validated packet the pre-launch executable handoff.

The API surface now exposes the minimum M3 artifact set directly: routing
decisions, assignments, context capsules, context requests and resolutions,
result proposals, node outcomes, advisor outcomes, turn reports, and compiled
dispatch packets. That keeps the workbench on validated backend-owned shapes
instead of file scraping or frontend-side policy reconstruction. It does not by
itself prove that every shape is an authoritative live runtime control input.

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

Status: completed for Runtime Harness Milestone 4.

Goal: turn controlled mutation from a current-state protocol into a complete
real-agent proposal path with deterministic, read-only historical replay.

Source tasks:

- [`../tasks/runtime_harness_milestone_4_tasklist.md`](../tasks/runtime_harness_milestone_4_tasklist.md)

Accepted design:

- [`../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md`](../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md)
- [`ADR-004`](../adrs/004-temporal-replay-mutation-intake-and-retry-control/001-accepted-design.md)
- [#3 RFC-004: Temporal Replay, Mutation Intake, And Retry Control](https://github.com/Dying-Ember/BureauLess/issues/3)

Current gap:

- Assignment prompts and Codex structured output now expose the typed mutation
  intent independently of completed/blocked execution status.
- Valid ledger-v3 session intake registers trusted proposals, and retry-v1 now
  appends bounded retry/circuit decisions. The maintained real-agent demo and
  temporal version projection remain open.

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

### B9: Runtime M4 Temporal Inspection

Status: completed in Workbench Milestone 5.

Source tasks:

- WB5-01 Timeline, Snapshot, And Diff API Client.
- WB5-02 Timeline And Version Selector.
- WB5-03 Historical Node And Assignment Inspector.
- WB5-04 Workflow And State Diff Inspector.
- WB5-05 Runtime M4 History Smoke Coverage.

Task list:
[`../tasks/workbench_milestone_5_tasklist.md`](../tasks/workbench_milestone_5_tasklist.md)

Goal: expose Runtime Harness Milestone 4 temporal history in the Workbench
without moving replay, version projection, or compare semantics into the
frontend.

Acceptance boundary:

- The workbench reads `/api/replay/timeline`, `/api/replay/snapshot`, and
  `/api/replay/diff` through typed clients and uses Python runtime payloads as
  the authoritative source of historical truth.
- Operators can inspect accepted workflow-version transitions, cursor-selected
  historical node and assignment state, and supported two-cursor diffs between
  linear history points.
- Unsupported cursors, rollback requests, and unavailable historical evidence
  remain explicit read-only error states rather than frontend fallback logic.
- No branching replay UI, rollback controls, or frontend-owned mutation
  authority is added.

### B10: Validated Runtime Operator Actions

Status: completed in Workbench Milestone 6.

Source tasks:

- WB6-01 Runtime Action API Client And Action State Model.
- WB6-02 Context Request Resolution Panel.
- WB6-03 Dispatch Packet Compile And Session Launch Controls.
- WB6-04 Result Staging And Review/Outcome Decision Controls.
- WB6-05 Runtime Action Safety, Doctoring, And Error Surfaces.
- WB6-06 Runtime Operator Actions Smoke Coverage.

Task list:
[`../tasks/workbench_milestone_6_tasklist.md`](../tasks/workbench_milestone_6_tasklist.md)

Goal: close the operational gap between read-only runtime inspection and the
validated backend actions that advance or launch runtime work.

Acceptance boundary:

- The workbench invokes validated action APIs for context resolution, dispatch
  compile, bounded launch, result staging, review import, and outcome decision
  through typed clients.
- All canonical mutations, packet validation, launch binding, and replay/
  gatekeeper refresh remain backend-owned.
- Action failures, strict-ledger rejections, doctor failures, and invalid
  inputs remain explicit UI states.
- No frontend-owned workflow mutation semantics, replay semantics, or silent
  optimistic ledger updates are introduced.

### B11: Guided Runtime Bootstrap And Source Navigation

Status: completed in Workbench Milestone 7.

Source tasks:

- WB7-01 Runtime Demo Bootstrap API Client And Source State.
- WB7-02 Guided Runtime Entry Panel.
- WB7-03 Manifest And Run-Bundle Source Navigator.
- WB7-04 Artifact Readiness And Missing-Evidence Summary.
- WB7-05 Guided Bootstrap And Source-Navigation Smoke Coverage.

Task list:
[`../tasks/workbench_milestone_7_tasklist.md`](../tasks/workbench_milestone_7_tasklist.md)

Goal: make the completed runtime inspection and action surface reachable from a
cold start without requiring the operator to manually construct manifest URLs
or search for generated bundle paths.

Acceptance boundary:

- The workbench invokes backend-owned bootstrap and source APIs through typed
  clients and uses returned manifest or bundle roots as authoritative.
- Operators can bootstrap a maintained runtime demo, open an explicit manifest
  root, and see which related artifacts are available or missing.
- Source provenance and missing evidence remain explicit UI states.
- No frontend-owned workspace generation, path synthesis, replay semantics, or
  canonical mutation authority is introduced.

## Current Priority Order

1. Implement Runtime Harness Milestone 5 as a backend/debug-first
   OpenAI-compatible telemetry boundary before proposing any workbench
   compatibility surface.
2. Use the completed Workbench M7 surface to run maintained `codex-cli`
   end-to-end trials and collect operator-friction findings while the new
   telemetry path lands behind CLI/API debugging surfaces.
3. Preserve the completed Runtime M3.5, Runtime M4, and Workbench M4-M7
   boundaries while validating real workflow runs.
4. Keep provider expansion, replay branches, rollback, and frontend-owned
   write authority outside the completed milestones unless a later milestone
   explicitly accepts them.

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
