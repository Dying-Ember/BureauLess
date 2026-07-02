# Runtime Harness Milestone 4 Task List

Status: planned. Implementation has not started.

This is the implementation task list for Runtime Harness Milestone 4:
validated agent mutation intake and linear temporal workflow replay. It builds
on the controlled current-state mutation model from Milestone 2.5 and the first
maintained `codex-cli` execution path from Milestone 3.

The project-level sequence lives in
[`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md). RFC-001
remains the design history for controlled current-state mutation. RM4-00 must
advance the draft
[`RFC-004`](../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md)
to an accepted ADR before temporal replay implementation begins.

## Current Capability Gap

Milestone 2.5 implemented the mutation proposal schema, mutation ledger events,
accept/reject decisions, current-workflow materialization, supersession, and
current-state replay. Milestone 3 lets `codex-cli` return artifact metadata and
`mutation_proposal_refs` in a result.

The real-agent mutation path is not yet closed:

- The agent assignment prompt does not provide a bounded mutation-intent
  contract or the local workflow facts needed to form one.
- Session packaging preserves proposal artifact references but does not parse
  and validate the referenced YAML as a workflow mutation proposal.
- Result import records `result_submitted` but does not register a validated
  `workflow_mutation_proposed` event.
- The API can inspect and decide an existing proposal event, but it has no
  validated proposal-intake operation for an agent result.

The M2.5 result shape also couples execution status to proposal presence through
`completed_with_proposal`, although discovering an incomplete workflow may leave
the assigned execution either completed or blocked. Therefore an agent can
currently mention or package a proposal reference, but it cannot reliably drive
the complete `detect -> propose -> validate -> pending review` flow. Milestone 4
closes that gap before relying on mutation history for temporal replay.

## Milestone Goals

1. Let every bounded worker produce one declarative mutation intent that the
   harness turns into a trusted, inert proposal event without invoking another
   agent.
2. Introduce deterministic workflow version identity and event-cursor semantics.
3. Replay workflow, assignment, node, and gatekeeper state through an arbitrary
   ledger event in the linear accepted history.
4. Prevent unchanged deterministic failures from consuming unbounded attempts
   or tokens while preserving bounded recovery from agent and infrastructure
   errors.
5. Expose read-only timeline, historical snapshot, diff, and explanation APIs
   suitable for a later Workbench milestone.

## Principles

- Agents emit untrusted declarative intents; they never issue an imperative
  canonical write, choose canonical IDs, or append ledger events directly.
- Bureauless deterministically creates the trusted proposal envelope, including
  proposal/artifact/event IDs, source provenance, workflow identity, base
  workflow version, and approval policy.
- Execution outcome and control intent are orthogonal: a completed or blocked
  result may carry no intent or one active mutation intent in M4.
- Every worker has the inert proposal escape hatch. Approval and application,
  not proposal, are privileged capabilities.
- No secondary mutation agent is required. A human, deterministic policy, or the
  existing orchestrator role may review a pending proposal.
- Ledger append order is the canonical history cursor. Wall-clock timestamps are
  descriptive metadata, not replay ordering authority.
- A workflow version changes only after an accepted mutation event. Proposed and
  rejected mutations do not create structural versions.
- Historical replay uses the same workflow, ledger, mutation, assignment, and
  gatekeeper validators as current-state replay.
- Except for classified transient infrastructure failures, unchanged input,
  evidence, strategy, assignment revision, and workflow version cannot produce
  another retry.
- Start with linear accepted history. Do not hide branch, rollback, or stale
  proposal semantics behind UI-only behavior.
- Recommended models use current native Codex model names and match task risk.

## Explicit Non-Goals

- No automatic acceptance of agent or orchestrator mutation proposals.
- No mandatory planner, summarizer, or mutation-specific LLM around a worker
  session.
- No worker write access to canonical workflow or ledger files.
- No counterfactual mutation branches, branch merge, or branch comparison.
- No `rollback_to_event`; historical snapshots are read-only projections.
- No timestamp-based replay contract.
- No provider expansion beyond the maintained `codex-cli` proof path.
- No Workbench timeline UI in this runtime milestone.
- No replay cache or checkpoint subsystem until correctness and measured need
  justify it.

## Workstream 0: Accepted Temporal Semantics

Goal: settle replay and mutation-intake semantics before changing runtime code.

### [ ] RM4-00: Temporal Replay, Mutation Intake, And Retry RFC

- Status: in progress; RFC-004 is drafted and no ADR is accepted
- Priority: critical
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, protocol, rfc, mutation, replay
- Target docs:
  - `docs/rfcs/004-temporal-replay-mutation-intake-and-retry-control.md`
  - `docs/adrs/`
  - `docs/protocol/harness_protocol.md`
  - `docs/roadmap/development_roadmap.md`
- Work:
  - Define inclusive `through_event_id` replay cursor semantics and explicit
    before/after version identity for mutation acceptance events.
  - Define `workflow_version_id`, parent version, mutation event provenance, and
    deterministic version ordering.
  - Define how stale proposals are detected when their base workflow version is
    no longer current.
  - Define historical assignment validity, supersession, and gatekeeper
    evaluation under each workflow version.
  - Define universal inert proposal access while keeping acceptance and
    application privileged.
  - Classify transient, output-contract, verification, capability, structural,
    stale, and policy failures with bounded retry behavior.
  - Define failure fingerprints, retry evidence requirements, attempt/token
    budgets, circuit breaking, and `needs_replan` transitions.
  - Define result/intake transaction boundaries so an invalid intent does not
    erase a valid execution result.
  - Resolve concurrency, duplicate intake, late results, in-flight
    supersession, review timeout, and external workflow drift behavior.
  - Record linear-history limits and migration behavior for existing ledgers
    that do not contain explicit version metadata.
- Acceptance criteria:
  - The RFC answers which workflow version and derived state are visible through
    every event type.
  - Timestamp ordering, branching, rollback, and automatic acceptance are
    explicitly outside the contract.
  - The RFC distinguishes recoverable agent execution errors from unchanged
    deterministic retry loops.
  - An ADR records the accepted semantics before RM4-01 begins.

### [ ] RM4-01: Worker Intent And Trusted Proposal Envelope

- Status: planned
- Priority: critical
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, protocol, mutation, provenance
- Dependencies: RM4-00
- Target code:
  - `src/bureauless/protocol/mutations.py`
  - `src/bureauless/protocol/results.py`
  - `tests/test_harness.py`
- Target docs:
  - `docs/protocol/harness_protocol.md`
- Work:
  - Define a minimal agent-authored `workflow_mutation` intent containing only
    reason, rationale, proposed changes, and evidence references.
  - Define a Bureauless-authored canonical proposal envelope containing IDs,
    assignment/session/agent provenance, workflow identity, base workflow
    version, and approval policy.
  - Make execution status independent from intent presence so either completed
    or blocked results may carry mutation intents.
  - Limit M4 results to at most one active mutation intent while retaining
    ordinary evidence for additional discovered problems.
  - Reject stale, spoofed, malformed, or semantically invalid intents with
    structured errors before building the canonical envelope.
  - Preserve a documented compatibility reader for existing M2.5
    `completed_with_proposal` and `mutation_proposal_refs` records.
- Acceptance criteria:
  - A proposal cannot be registered against a workflow version other than the
    harness-observed version used for its assignment.
  - Agent-controlled output cannot choose or spoof canonical provenance, IDs,
    workflow version, or approval policy.
  - Validation remains inert and appends no event on failure.

## Workstream 1: Real Agent Mutation Intake

Goal: close the bounded real-agent mutation proposal loop without granting the
agent canonical write authority.

### [ ] RM4-02: Universal Structural Escape Hatch And Output Contract

- Status: planned
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Labels: runtime, agents, codex-cli, prompt-contract
- Dependencies: RM4-01
- Target code:
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/protocol/assignments.py`
  - `tests/test_harness.py`
- Work:
  - Give every worker a compact `workflow_structure` reporting path and the
    exact typed mutation-intent contract.
  - Include the current workflow version and enough current workflow structure
    for the agent to name valid nodes, events, and affected assignments.
  - Add a typed `control_intents` result channel independent from execution
    status; use final structured output for the Codex CLI MVP and allow future
    adapters to carry the same payload through a tool call.
  - Require normal bounded results with no intent when no structural change is
    needed.
  - Keep canonical approval and application unavailable to workers even though
    inert proposal submission is universal.
- Acceptance criteria:
  - A fixture-backed Codex session can distinguish a normal result from a
    completed or blocked result carrying a parseable mutation intent.
  - The output contract does not invite direct workflow or ledger edits.
  - An incorrectly planned assignment cannot omit the worker's structural escape
    hatch.

### [ ] RM4-03: Deterministic Intent Intake And Proposal Registration

- Status: planned
- Priority: critical
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, mutation, artifact-integrity, ledger
- Dependencies: RM4-02
- Target code:
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/protocol/results.py`
  - `src/bureauless/protocol/ledger.py`
  - `tests/test_harness.py`
- Work:
  - Parse typed intents from the session result and validate every intent before
    registering a proposal event.
  - Enrich valid intents with harness-owned provenance and version metadata,
    serialize canonical immutable proposal artifacts, and verify their hashes.
  - Register one deterministic `workflow_mutation_proposed` event per canonical
    proposal after `result_submitted`, linked to its result and source artifact.
  - Make repeated intake idempotent and reject duplicate canonical identities.
- Acceptance criteria:
  - Valid intent intake produces a pending replay-visible proposal without
    invoking another agent or changing workflow structure.
  - An invalid intent creates no proposal event but does not erase an otherwise
    valid imported result; its intake disposition remains inspectable.
  - Proposal event ordering and identifiers are deterministic.

### [ ] RM4-04: Retry Classification And Stuck-Loop Circuit Breaker

- Status: planned
- Priority: critical
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, agents, retry, budget, gatekeeper
- Dependencies: RM4-01, RM4-02
- Target code:
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/runtime/replay.py`
  - `src/bureauless/runtime/gatekeeper.py`
  - `tests/test_harness.py`
- Work:
  - Classify transient infrastructure, malformed output, verification,
    capability mismatch, structural, stale/superseded, and policy failures.
  - Give every retry a new attempt identity, retry reason, prior-attempt
    reference, and applicable attempt/token budget.
  - Permit bounded recovery retries for transient failures and one repair retry
    with validator feedback for malformed output.
  - Require new evidence or a recorded strategy/routing change for execution
    repair retries.
  - Derive stable failure fingerprints and open the circuit on repeated
    deterministic failures.
  - Prevent `structural_blocked`, `needs_replan`, and superseded assignments from
    becoming runnable without a relevant assignment, context, strategy, or
    workflow-version change.
- Acceptance criteria:
  - Agent execution and infrastructure errors can recover within explicit
    budgets.
  - Identical deterministic failures cannot launch an unbounded sequence of
    agent attempts.
  - Retry and circuit-break decisions are append-only, attributable, and
    replayable.

### [ ] RM4-05: Maintained Real-Agent Mutation And Retry Demo

- Status: planned
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, agents, codex-cli, demo, e2e
- Dependencies: RM4-03, RM4-04
- Target code:
  - `src/bureauless/cli/main.py`
  - `tests/test_harness.py`
- Work:
  - Add one bounded scenario where `codex-cli` discovers a missing structural
    dependency and returns a mutation intent through the normal session path.
  - Verify proposal validation, pending gatekeeper state, explicit acceptance,
    workflow version advance, supersession, and resumed dispatch.
  - Verify one recoverable execution error and one repeated deterministic
    failure that opens the circuit without spending another agent turn.
  - Keep deterministic fixture coverage in the normal test suite and expose the
    real model invocation as a maintained opt-in smoke path.
- Acceptance criteria:
  - The demo proves `detect -> propose -> validate -> pending -> accept -> new
    version -> replay` without manual ledger editing.
  - Agent failure or malformed output never mutates canonical state.
  - The demo does not retry an unchanged structural or deterministic failure.

## Workstream 2: Linear Temporal Replay

Goal: derive historical workflow and runtime state from append-only event order.

### [ ] RM4-06: Workflow Version Projection

- Status: planned
- Priority: critical
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, replay, workflow-version
- Dependencies: RM4-00, RM4-01
- Target code:
  - `src/bureauless/runtime/replay.py`
  - `src/bureauless/protocol/mutations.py`
  - `tests/test_harness.py`
- Work:
  - Derive version zero from the initial workflow and one child version for each
    accepted mutation in ledger order.
  - Record version-before and version-after for every accepted mutation event.
  - Map every ledger event to the active workflow version under inclusive cursor
    semantics.
  - Reject impossible or stale linear version transitions explicitly.
- Acceptance criteria:
  - Equal initial workflow and ledger inputs always produce equal version IDs
    and event mappings.
  - Proposed and rejected mutations do not advance the workflow version.

### [ ] RM4-07: Event-Prefix State Replay

- Status: planned
- Priority: critical
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, replay, gatekeeper, history
- Dependencies: RM4-06
- Target code:
  - `src/bureauless/runtime/replay.py`
  - `src/bureauless/runtime/gatekeeper.py`
  - `tests/test_harness.py`
- Work:
  - Replay an inclusive ledger prefix through a specified event ID or event
    ordinal using the workflow version active at that cursor.
  - Derive historical node, assignment, mutation, gatekeeper, and terminal state
    without consulting future events.
  - Explain why a node was runnable, blocked, completed, or superseded at that
    cursor.
- Acceptance criteria:
  - Future result, decision, and mutation events cannot leak into an earlier
    historical projection.
  - Current-state replay remains equivalent to replay through the final event.

### [ ] RM4-08: Assignment Validity Across Workflow Versions

- Status: planned
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, replay, assignment, supersession
- Dependencies: RM4-07
- Target code:
  - `src/bureauless/protocol/assignments.py`
  - `src/bureauless/runtime/replay.py`
  - `src/bureauless/runtime/gatekeeper.py`
  - `tests/test_harness.py`
- Work:
  - Associate new assignments with the workflow version used for export.
  - Preserve historical validity for assignments that were valid before a later
    mutation while excluding superseded evidence from later versions.
  - Define conservative compatibility behavior for pre-M4 assignments without
    explicit version identity.
- Acceptance criteria:
  - The same assignment may be historically valid before a mutation and
    superseded after it without rewriting either state.
  - Gatekeeper explanations identify the relevant assignment and mutation
    version transition.

## Workstream 3: Historical Inspection API

Goal: expose runtime-owned history projections without moving replay logic into
the Workbench.

### [ ] RM4-09: Timeline And Historical Snapshot API

- Status: planned
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Labels: runtime, api, replay, inspection
- Dependencies: RM4-07, RM4-08
- Target code:
  - `src/bureauless/api/server.py`
  - `tests/test_server.py`
- Work:
  - Add a timeline endpoint with event ordinal, event ID, event type, active
    version, and version transition metadata.
  - Add a historical snapshot endpoint using explicit `through_event_id` or
    event ordinal selectors.
  - Add runtime-owned workflow and state diff output between two valid cursors.
  - Return structured errors for unknown cursors and unsupported branch or
    rollback requests.
- Acceptance criteria:
  - API consumers can answer "what was the workflow and why was this node in
    that state then?" without reading YAML or replaying rules themselves.
  - Existing current-state replay and mutation APIs remain compatible.

### [ ] RM4-10: Temporal Replay Determinism And Scale Guardrails

- Status: planned
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: medium
- Labels: runtime, tests, replay, performance
- Dependencies: RM4-09
- Target code:
  - `tests/test_harness.py`
  - `tests/test_server.py`
- Work:
  - Add fixtures covering multiple accepted and rejected proposals,
    supersession, stale proposals, and historical queries before and after each
    version transition.
  - Add determinism tests for repeated replay and current-state equivalence.
  - Measure prefix replay on a bounded synthetic ledger and document the first
    threshold that would justify checkpoints; do not add speculative caching.
- Acceptance criteria:
  - Focused runtime and server suites cover every event/version boundary.
  - The measured baseline is recorded and no correctness path depends on a
    cache.

## Workstream 4: Acceptance And Handoff

### [ ] RM4-11: Protocol, Roadmap, And Workbench Handoff

- Status: planned
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Labels: docs, roadmap, acceptance
- Dependencies: RM4-05, RM4-10
- Target docs:
  - `docs/protocol/harness_protocol.md`
  - `docs/roadmap/development_roadmap.md`
  - `docs/tasks/runtime_harness_tasklist.md`
  - `docs/tasks/workbench_tasklist.md`
- Work:
  - Promote accepted temporal semantics into canonical protocol docs.
  - Record actual implementation and verification commands on every task.
  - Define the later Workbench milestone around read-only timeline, version
    selection, historical state explanation, and diff inspection.
  - Keep mutation decisions runtime-authoritative and avoid frontend replay.
- Acceptance criteria:
  - Roadmap, task indexes, RFC/ADR status, and implementation agree on M4 scope
    and completion.
  - The Workbench handoff names API contracts rather than duplicating runtime
    logic.

## Required Execution Order

1. RM4-00 Temporal Replay, Mutation Intake, And Retry RFC
2. RM4-01 Worker Intent And Trusted Proposal Envelope
3. RM4-02 Universal Structural Escape Hatch And Output Contract
4. RM4-03 Deterministic Intent Intake And Proposal Registration
5. RM4-04 Retry Classification And Stuck-Loop Circuit Breaker
6. RM4-05 Maintained Real-Agent Mutation And Retry Demo
7. RM4-06 Workflow Version Projection
8. RM4-07 Event-Prefix State Replay
9. RM4-08 Assignment Validity Across Workflow Versions
10. RM4-09 Timeline And Historical Snapshot API
11. RM4-10 Temporal Replay Determinism And Scale Guardrails
12. RM4-11 Protocol, Roadmap, And Workbench Handoff

RM4-06 may begin after RM4-00 and RM4-01 while RM4-02 through RM4-05 are being
implemented, but milestone acceptance requires both the real-agent intake path
and temporal replay path to meet at the same version-bound mutation contract.

## Milestone Acceptance

Runtime Harness Milestone 4 is complete when:

- One maintained `codex-cli` path can produce a mutation intent without editing
  canonical workflow or ledger state or invoking a mutation-specific agent.
- Bureauless deterministically turns valid intents into version-bound canonical
  proposals and inert pending ledger events; invalid intent intake preserves an
  otherwise valid result.
- Recoverable agent or infrastructure failures can retry within explicit
  budgets, while unchanged deterministic or structural failures open the
  circuit instead of consuming another agent turn.
- Explicit acceptance creates a deterministic child workflow version;
  rejection does not.
- Replay through any valid event cursor derives workflow, node, assignment,
  mutation, and gatekeeper state without future-event leakage.
- Current-state replay equals temporal replay through the final event.
- Historical timeline, snapshot, diff, and explanation APIs are covered by
  deterministic runtime and server tests.
- Branching, rollback, automatic mutation acceptance, provider expansion, and
  Workbench history UI remain explicitly deferred.
