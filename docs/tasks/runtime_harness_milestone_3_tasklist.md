# Runtime Harness Milestone 3 Task List

This is the next active runtime/harness milestone task list for BureauLess. It
builds on the completed M1, M2, and M2.5 milestones and turns the current
runtime from "safe to run" into "safe to evaluate and route".

The project-level sequencing lives in
[`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md).
Protocol contracts live in `../protocol/`; architecture rationale lives in
`../architecture/`.

Milestone 3 has three goals:

1. Close the advisor-policy loop with measurable outcome tracking.
2. Make orchestrator decisions first-class structured artifacts instead of
   implicit glue between assignment export and result import.
3. Establish a minimum-sufficient ledger boundary and bounded, measurable
   context delivery for real-agent runs.

Within this document, `milestone` names the user-visible delivery target and
`workstream` names an internal implementation grouping inside that milestone.

## Principles

- Keep runtime selection and routing deterministic until there is enough data
  to justify a more adaptive policy.
- Measure advisor value with explicit outcomes, not with retrospective vibes.
- Make orchestrator judgments reviewable as YAML before they launch work.
- Do not let richer decision artifacts bypass existing gatekeeper or ledger
  invariants.
- Preserve native traces as evidence while keeping normal replay and worker
  context independent of full transcripts.
- Make ledger and context work scale with node outcomes, not internal tool
  calls.
- Keep low-risk execution free of mandatory summarizer or reviewer agents.
- Keep temporal replay out of scope for this milestone; focus on decision
  quality and auditability first.

## Workstream 1: Advisor Outcome Learning

Goal: record whether advisor invocations and skips were actually worth it.

### [ ] RM3-01: Advisor Outcome Event Model

- Status: pending
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Labels: runtime, budget, advisor-policy
- Target docs:
  - `docs/protocol/advisor_policy.md`
  - `docs/architecture/context_economy.md`
- Target code:
  - `src/bureauless/protocol/`
  - `tests/test_harness.py`
- Work:
  - Define the canonical outcome record for `good_call`, `bad_call`,
    `good_skip`, and `missed_call`.
  - Require provenance back to the routing or review decision that created the
    advisor opportunity.
  - Distinguish "not enough evidence yet" from a completed scored outcome.
- Acceptance criteria:
  - Advisor outcome records are append-only and replayable.
  - Missing provenance or invalid outcome types are rejected.

### [ ] RM3-02: Budget Snapshot Attribution

- Status: pending
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Labels: runtime, budget
- Target docs:
  - `docs/architecture/context_economy.md`
- Target code:
  - `src/bureauless/runtime/`
  - `tests/test_harness.py`
- Work:
  - Attach the relevant price snapshot and estimation basis to advisor and
    routing outcomes.
  - Preserve estimated-vs-actual token and cost comparisons when available.
  - Keep "unavailable from agent runtime" separate from "not recorded".
- Acceptance criteria:
  - Outcome review can explain which price basis was in force.
  - Cost comparisons survive replay and metrics export.

### [ ] RM3-03: Advisor Outcome Scoring Pass

- Status: pending
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, advisor-policy, replay
- Target code:
  - `src/bureauless/runtime/`
  - `src/bureauless/api/server.py`
  - `tests/test_harness.py`
- Work:
  - Implement a deterministic pass that scores completed advisor opportunities.
  - Use mission outcome, review outcome, and budget variance as inputs.
  - Emit structured "insufficient evidence" states instead of guessing.
- Acceptance criteria:
  - Completed runs can be scored without calling an LLM.
  - The runtime can summarize advisor performance over a ledger.

## Workstream 2: Orchestrator Decision Artifacts

Goal: make orchestrator proposals machine-readable, reviewable, and
compilable.

### [ ] RM3-04: Routing Decision Artifact

- Status: pending
- Priority: high
- Recommended model: gpt-5.4
- Risk: high
- Labels: runtime, protocol, workflow-selection
- Target docs:
  - `docs/protocol/workflow_selection_policy.md`
  - `docs/protocol/harness_protocol.md`
- Target code:
  - `src/bureauless/protocol/`
  - `tests/test_harness.py`
- Work:
  - Define a structured routing decision artifact that captures selected mode,
    rejected simpler modes, expected savings, and gating rationale.
  - Require links to budget assumptions and workflow selection policy triggers.
  - Reject routing artifacts that contradict workflow invariants.
- Acceptance criteria:
  - A routing artifact can be validated before dispatch.
  - Complex routing without explicit selection rationale is rejected.

### [ ] RM3-05: Review Decision Artifact

- Status: pending
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Labels: runtime, protocol, gatekeeper
- Target code:
  - `src/bureauless/protocol/`
  - `tests/test_harness.py`
- Work:
  - Define an explicit orchestrator/human review decision artifact separate
    from raw worker output.
  - Capture evidence refs, accepted findings, rejected findings, and next-step
    disposition.
  - Keep accepted public state in the ledger, but preserve the raw decision
    packet for audit.
- Acceptance criteria:
  - Review decisions can be validated independently of worker result payloads.
  - Public findings cannot appear without review provenance.

### [ ] RM3-06: Turn Report And Dispatch Packet Compiler

- Status: pending
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, protocol
- Target code:
  - `src/bureauless/protocol/`
  - `src/bureauless/cli/main.py`
  - `tests/test_harness.py`
- Work:
  - Add loaders/validators for turn reports and dispatch packets.
  - Compile routing decision, assignment, and review constraints into one
    machine-checkable handoff.
  - Enforce worker/orchestrator invariants before the packet can launch.
- Acceptance criteria:
  - A complete orchestrator proposal can be compiled before worker dispatch.
  - Invalid packets fail before any external session starts.

## Workstream 3: Ledger Outcomes And Context Delivery

Goal: preserve full execution evidence while committing only the minimum facts
needed for safe continuation, replay, and targeted context delivery.

### [ ] RM3-07: Node Outcome And Workspace Delta Protocol

- Status: pending
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, protocol, ledger, replay
- Target docs:
  - `docs/protocol/harness_protocol.md`
  - `docs/rfcs/ledger_evidence_and_context.md`
- Target code:
  - `src/bureauless/protocol/`
  - `src/bureauless/runtime/sessions.py`
  - `tests/test_harness.py`
- Work:
  - Add a structured node-outcome record for successful, failed, timed-out,
    cancelled, and partial assignment attempts.
  - Capture observed pre/post workspace refs, deterministic deltas,
    verification evidence, partial effects, unknowns, and native trace refs.
  - Keep observations, proposed semantic findings, and acceptance decisions
    distinct.
  - Add one `node_outcome_decided` event that supports full, partial, and
    rejected dispositions without duplicating the full outcome payload.
  - Treat persisted current-state summaries as projections with a cursor to the
    last accepted event they include.
  - Mark outcomes `stale` or `needs_review` when their pre-state no longer
    matches the accepted workspace.
- Acceptance criteria:
  - A failed run can report partial workspace effects without emitting a
    workflow completion event.
  - Accepted facts retain outcome, evidence, actor, and validation-rule
    provenance.
  - A stale or missing projection cursor causes deterministic rebuild rather
    than creating a second source of truth.
  - Normal replay does not read native trace artifacts.

### [ ] RM3-08: Deterministic Context Capsule Compiler

- Status: pending
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, context, protocol
- Target docs:
  - `docs/architecture/context_economy.md`
  - `docs/protocol/harness_protocol.md`
- Target code:
  - `src/bureauless/protocol/assignments.py`
  - `src/bureauless/runtime/`
  - `tests/test_harness.py`
- Work:
  - Compile a bounded assignment context from mission constraints, workspace
    state, dependency closure, gates, scoped accepted facts, active risks, and
    artifact refs.
  - Exclude unrelated branches, superseded history, resolved risks, raw logs,
    and large artifact bodies by default.
  - Record a stable context-policy version and source refs for every capsule.
  - Use explicit graph, path, artifact, and role relationships before any
    semantic retrieval.
- Acceptance criteria:
  - The same inputs and policy version produce the same capsule.
  - A fresh worker fixture can continue from mission, assignment, capsule, and
    referenced artifacts without prior transcript access.
  - Low-risk single-node assignments require no summarizer model.

### [ ] RM3-09: Scoped Context Requests And Progressive Disclosure

- Status: pending
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Labels: runtime, context, budget
- Target docs:
  - `docs/architecture/context_economy.md`
  - `docs/protocol/harness_protocol.md`
- Target code:
  - `src/bureauless/protocol/`
  - `src/bureauless/runtime/`
  - `tests/test_harness.py`
- Work:
  - Define context requests with missing information, requested refs, and
    expected assignment value.
  - Enforce role visibility, relevance, and token budget before disclosure.
  - Return targeted artifact bodies or trace excerpts instead of rebroadcasting
    the full ledger.
  - Represent absent evidence as `unavailable` rather than inferred content.
- Acceptance criteria:
  - A worker can request one relevant evidence ref without receiving unrelated
    branch history.
  - Denied and unavailable requests have structured reasons.
  - Context requests remain telemetry unless they expose a mission blocker,
    risk, or accepted decision.

### [ ] RM3-10: Context Telemetry And Policy Feedback

- Status: pending
- Priority: medium
- Recommended model: gpt-5.4
- Risk: medium
- Labels: runtime, metrics, context, budget
- Target docs:
  - `docs/architecture/context_economy.md`
- Target code:
  - `src/bureauless/runtime/metrics.py`
  - `tests/test_harness.py`
- Work:
  - Record policy version, capsule tokens, included refs, context requests,
    added tokens, first-pass outcome, review outcome, and rework.
  - Classify context fit as `under_provisioned`, `well_provisioned`,
    `over_provisioned`, `mis_scoped`, or `insufficient_evidence` using
    externally observable signals.
  - Aggregate by role, task type, risk level, model, and policy version.
  - Generate versioned policy recommendations without automatically applying
    changes from individual runs.
- Acceptance criteria:
  - Metrics distinguish missing context from unavailable evidence.
  - Repeated requests for one evidence class produce a reviewable promotion
    recommendation.
  - High-volume telemetry stays outside canonical ledger state; only accepted
    policy changes become ledger decisions.

## Workstream 4: Acceptance Spine And Operator Surface

Goal: make Milestone 3 reviewable through one documented path instead of a set
of isolated unit tests.

### [ ] RM3-11: M3 Integrated Demo Fixture

- Status: pending
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Labels: runtime, replay, workbench
- Target code:
  - `examples/`
  - `tests/test_harness.py`
- Work:
  - Add one maintained demo fixture that includes routing rationale, advisor
    invocation or skip, a scored outcome, a node outcome, and a compiled
    context capsule.
  - Keep the fixture small enough to inspect manually.
  - Reuse the same fixture in replay, metrics, and API tests.
- Acceptance criteria:
  - One stable fixture exercises the full M3 path.
  - The fixture can be inspected through the normal API surface.

### [ ] RM3-12: M3 Runtime API Coverage

- Status: pending
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Labels: runtime, workbench
- Target code:
  - `src/bureauless/api/server.py`
  - `tests/test_server.py`
- Work:
  - Expose minimal API endpoints needed to inspect routing decisions, advisor
    outcomes, node outcomes, context delivery, and compiled dispatch packets.
  - Keep response shapes stable enough for the next workbench milestone.
- Acceptance criteria:
  - The workbench can inspect M3 artifacts without file scraping.
  - API responses avoid duplicating runtime business rules in the frontend.

## Recommended Execution Order

1. RM3-07 Node Outcome And Workspace Delta Protocol
2. RM3-05 Review Decision Artifact
3. RM3-08 Deterministic Context Capsule Compiler
4. RM3-09 Scoped Context Requests And Progressive Disclosure
5. RM3-10 Context Telemetry And Policy Feedback
6. RM3-01 Advisor Outcome Event Model
7. RM3-04 Routing Decision Artifact
8. RM3-06 Turn Report And Dispatch Packet Compiler
9. RM3-02 Budget Snapshot Attribution
10. RM3-03 Advisor Outcome Scoring Pass
11. RM3-11 M3 Integrated Demo Fixture
12. RM3-12 M3 Runtime API Coverage

## Milestone 3 Acceptance

- Advisor opportunities can be recorded and scored without calling an LLM.
- Routing and review judgments are persisted as structured YAML artifacts.
- Node outcomes preserve complete evidence refs while committing only accepted,
  revision-scoped facts.
- Fresh workers receive bounded deterministic context and can request targeted
  evidence without full-ledger broadcast.
- Context telemetry can identify under- and over-provisioning without becoming
  canonical mission noise.
- Invalid orchestrator packets fail before worker launch.
- Replay and metrics can explain not only what happened, but whether the
  orchestrator's higher-level calls were justified.
