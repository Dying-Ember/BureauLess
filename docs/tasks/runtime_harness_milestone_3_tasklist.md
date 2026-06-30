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

Milestone 3 also has one delivery constraint: it must end with one maintained
real-agent demo path, not only fixture-only or shell-dummy validation. The
first real worker target is `codex-cli`. This milestone does not attempt to
build a complete multi-provider or multi-agent platform; it adds only the
minimum binding spine needed to launch a bounded real task and inspect the
result through the normal runtime surfaces. `opencode` remains the next
strategic integration target after that first path is stable.

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
- Keep real-agent integration narrow: prove one `codex-cli` path before
  broadening provider or agent coverage.
- Do not turn Milestone 3 into a general provider platform or plugin
  ecosystem.
- Keep temporal replay out of scope for this milestone; focus on decision
  quality and auditability first.

## Workstream 0: Real Agent Binding Spine

Goal: launch one bounded real agent path for the Milestone 3 demo without
expanding into a full provider abstraction platform.

### [x] RM3-00: Codex CLI Binding Spine

- Status: completed
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, agents, provider, demo
- Target docs:
  - `docs/protocol/harness_protocol.md`
  - `docs/roadmap/development_roadmap.md`
- Target code:
  - `src/bureauless/agents/`
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/cli/main.py`
  - `tests/test_harness.py`
- Work:
  - Add the minimum runtime registry needed to bind one agent adapter to one
    provider profile and validate target model/provider combinations before
    launch.
  - Keep provider auth injection environment-scoped for automation and avoid
    introducing a broad secret-management subsystem.
  - Implement the first real launch path for `codex-cli`, reusing doctor and
    readiness signals rather than creating a separate registry.
  - Record `target_model`, `target_provider`, and resolved `effective_*`
    session/result fields on the real launch path.
  - Explicitly defer `opencode` customization and multi-provider breadth until
    the first `codex-cli` demo path is stable.
- Acceptance criteria:
  - The runtime can reject an invalid agent/provider/model binding before any
    external session starts.
  - One bounded `codex-cli` assignment can run non-interactively in an
    isolated workspace and return an importable result proposal.
  - The implementation does not require a general provider marketplace,
    fallback mesh, or dynamic secret backend.

## Workstream 1: Advisor Outcome Learning

Goal: record whether advisor invocations and skips were actually worth it.

### [x] RM3-01: Advisor Outcome Event Model

- Status: completed
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

### [x] RM3-02: Budget Snapshot Attribution

- Status: completed
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

### [x] RM3-03: Advisor Outcome Scoring Pass

- Status: completed
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

### [x] RM3-04: Routing Decision Artifact

- Status: completed
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

### [x] RM3-05: Review Decision Artifact

- Status: completed
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

### [x] RM3-06: Turn Report And Dispatch Packet Compiler

- Status: completed
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

### [x] RM3-07: Node Outcome And Workspace Delta Protocol

- Status: completed
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, protocol, ledger, replay
- Target docs:
  - `docs/protocol/harness_protocol.md`
  - `docs/rfcs/002-ledger-evidence-and-progressive-context.md`
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

### [x] RM3-08: Deterministic Context Capsule Compiler

- Status: completed
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

### [x] RM3-09: Scoped Context Requests And Progressive Disclosure

- Status: completed
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

### [x] RM3-10: Context Telemetry And Policy Feedback

- Status: completed
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

### [x] RM3-11: M3 Integrated Demo Fixture

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Labels: runtime, replay, workbench
- Target code:
  - `examples/`
  - `tests/test_harness.py`
- Work:
  - Add one maintained demo path that covers a real small task, not only a
    synthetic fixture.
  - Use `codex-cli` as the first real worker target for that path.
  - Include routing rationale, advisor invocation or skip, a scored outcome, a
    node outcome, a compiled context capsule, and the resulting review/ledger
    decisions.
  - Keep the demo small enough to inspect manually and stable enough to reuse
    in replay, metrics, and API tests.
- Acceptance criteria:
  - One stable demo path exercises the full M3 path end to end.
  - The demo can be inspected through the normal API and workbench surfaces.
  - The milestone is not considered complete if the path still depends solely
    on `fake` or `shell-dummy` execution.
  - A real `codex-cli` run has been exercised end to end and verified through
    the workbench against the emitted mission/workflow/ledger artifacts.

### [x] RM3-12: M3 Runtime API Coverage

- Status: completed
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
  - Reuse protocol loaders/compilers in the API layer so the frontend reads
    canonical runtime shapes instead of re-deriving them.
- Acceptance criteria:
  - The workbench can inspect M3 artifacts without file scraping.
  - API responses avoid duplicating runtime business rules in the frontend.

## Recommended Execution Order

1. RM3-00 Codex CLI Binding Spine
2. RM3-07 Node Outcome And Workspace Delta Protocol
3. RM3-05 Review Decision Artifact
4. RM3-08 Deterministic Context Capsule Compiler
5. RM3-09 Scoped Context Requests And Progressive Disclosure
6. RM3-10 Context Telemetry And Policy Feedback
7. RM3-01 Advisor Outcome Event Model
8. RM3-04 Routing Decision Artifact
9. RM3-06 Turn Report And Dispatch Packet Compiler
10. RM3-02 Budget Snapshot Attribution
11. RM3-03 Advisor Outcome Scoring Pass
12. RM3-11 M3 Integrated Demo Fixture
13. RM3-12 M3 Runtime API Coverage

## Milestone 3 Acceptance

- Advisor opportunities can be recorded and scored without calling an LLM.
- Routing and review judgments are persisted as structured YAML artifacts.
- One maintained `codex-cli` path can execute a bounded real task and produce
  inspectable session, review, and ledger state.
- Node outcomes preserve complete evidence refs while committing only accepted,
  revision-scoped facts.
- Fresh workers receive bounded deterministic context and can request targeted
  evidence without full-ledger broadcast.
- Context telemetry can identify under- and over-provisioning without becoming
  canonical mission noise.
- Invalid orchestrator packets fail before worker launch.
- Replay and metrics can explain not only what happened, but whether the
  orchestrator's higher-level calls were justified.
