# Runtime Harness Milestone 3.5 Task List

Status: completed. RM35-01 through RM35-08 are complete.

Runtime Harness Milestone 3.5 closes the execution-spine gaps found after
Runtime M3. It does not replace or erase the delivered M2/M3 protocol and
Workbench inspection work. It makes those artifacts authoritative in the
maintained real-agent runtime before Runtime M4 builds mutation intake and
temporal replay on top of them.

Source audit:
[`2026-07-02 Runtime Execution Gap Analysis`](../audits/2026-07-02-runtime-execution-gap-analysis.md).

Identifiers use `RM35-*` so historical M3 task IDs and planned M4 task IDs remain
stable.

## Milestone Goals

1. Make review and node-outcome decisions the only authority that advances
   workflow completion state.
2. Make a validated dispatch packet precede and govern external launch.
3. Connect progressive context requests and process cancellation to real agent
   sessions.
4. Replace post-hoc demo artifacts with truthful runtime telemetry and reusable
   run-bundle discovery.
5. Prove both advisor skip and invocation paths without making advisors
   mandatory for low-risk work.

## Workstream 0: Acceptance Authority

### [x] RM35-01: Result, Review, And Outcome Acceptance Spine

- Status: completed; RFC-005 and ADR-005 are implemented
- Priority: critical
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, protocol, ledger, replay, gatekeeper
- Finding: REX-002
- Design:
  - `docs/rfcs/005-authoritative-result-acceptance-spine.md`
  - `docs/adrs/005-authoritative-result-acceptance-spine/001-accepted-design.md`
- Target code:
  - `src/bureauless/protocol/results.py`
  - `src/bureauless/protocol/reviews.py`
  - `src/bureauless/runtime/replay.py`
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/cli/exchange.py`
  - `src/bureauless/api/server.py`
  - `tests/`
- Work:
  - Implement RFC-005 and ADR-005 with one authoritative acceptance decision
    and explicit compatibility behavior for ledgers without outcome decisions.
  - Stage raw result submission separately from effective workflow completion.
  - Make review, verification policy, partial acceptance, and rejection produce
    one coherent node-outcome disposition.
  - Remove or explicitly gate direct import paths that implicitly accept worker
    events.
  - Preserve raw evidence even when no workflow event is accepted.
- Acceptance criteria:
  - An unreviewed or rejected result cannot satisfy a downstream workflow gate.
  - Failed or missing required verification cannot be accepted by default.
  - Partial acceptance affects only explicitly listed event types.
  - Legacy ledger behavior is deterministic, documented, and covered by
    compatibility tests.
- Completion evidence:
  - Ledger v2 stages result claims and materializes effective events only from
    `node_outcome_decided`.
  - Shared acceptance service enforces review, verification, partial acceptance,
    rejection, and one terminal decision per outcome.
  - Maintained CLI, API, manual golden path, and live demo use strict staged
    acceptance; v1 writes require conservative migration.
  - Focused and full backend tests plus web type/build verification pass.
  - 2026-07-11 maintenance: the maintained live demo now advances by replayed
    `gatekeeper.ready` state instead of a hard-coded `implement -> review ->
    commit` list, so separate verification nodes can run before review when
    the accepted workflow requires them.
  - 2026-07-11 live verification note: a JOJO provider run timed out at the
    `implement` node before it emitted a result. The resulting lack of
    multi-agent, mutation, independent-verification, and commit coverage is a
    provider/runtime execution limitation, not evidence of a workflow or
    harness regression.
  - 2026-07-11 maintenance: Codex native JSONL events now renew a session's
    configured idle deadline. A silent provider path records `idle_timeout`;
    observed long-running agent work is not cut off at its original start time.
  - 2026-07-11 maintenance: the implement progress contract now uses the shared
    `final_independent_verification: pending_separate_assignment` marker, so an
    accepted `patch_ready` can unlock separate review and verifier nodes without
    pretending final acceptance already happened.

## Workstream 1: Executable Handoff

### [x] RM35-02: Dispatch Packet To Session Bridge

- Status: completed
- Priority: critical
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, dispatch, routing, agents
- Dependencies: RM35-01 acceptance semantics identified; implementation may run
  in parallel where code ownership does not overlap
- Finding: REX-003
- Target code:
  - `src/bureauless/protocol/dispatch.py`
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/cli/main.py`
  - `src/bureauless/api/server.py`
  - `tests/`
- Work:
  - Compile and validate the dispatch packet before any external process starts.
  - Bind agent, model, provider, sandbox, timeout, review constraints, and report
    policy through one authoritative dispatch operation.
  - Reject mismatches between packet, binding, assignment, and launched session.
  - Persist the exact pre-launch packet and link it to the session record.
- Acceptance criteria:
  - Invalid dispatch packets fail before command execution.
  - A maintained Codex session can be reconstructed from its dispatch evidence.
  - The live demo no longer creates the dispatch packet after session completion.
- Completion evidence:
  - `dispatch_session` validates the canonical packet and mission model binding,
    persists the exact packet atomically, derives the session spec, and only
    then invokes the external runner.
  - Codex launch input now includes packet identity, routing mode, review
    constraints, and turn-report policy; model, provider, sandbox, and timeout
    remain in the linked canonical session spec.
  - Session records retain packet path/hash and the complete launch binding;
    `reconstruct_dispatched_session` verifies both before reconstruction.
  - Maintained CLI, API runtime demo, generic session-dispatch API, and live
    demo paths use the bridge. Focused and full backend tests pass.
  - 2026-07-11 boundary-demo maintenance: the task-publisher wrapper records
    only the orchestrator model. It cannot preselect derived worker/agent
    models; those require an explicit orchestrator control-plane artifact and
    harness approval.
  - 2026-07-11 boundary-demo maintenance: dispatch rejects proposed workflows
    before assignment creation or provider launch. The publisher audit reports
    that condition as old-helper control-plane contamination and evaluates
    provider telemetry only for nodes that actually executed.
  - 2026-07-11 boundary-demo maintenance: control-plane bootstrap now supports
    one bounded replan attempt with full artifact retention and worker zero
    dispatch on rejection; accepted worker bindings, semantic node roles, and
    replay-driven readiness were validated by the real
    `2026-07-11-jojocode-control-plane-bootstrap-v12` run through terminal
    commit.

### [x] RM35-03: Progressive Context Request Continuation

- Status: completed; RFC-006 and ADR-006 are implemented
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, context, agents, budget, replay
- Dependencies: RM35-02
- Finding: REX-004
- Target code:
  - `src/bureauless/protocol/context.py`
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/runtime/replay.py`
  - `tests/`
- Work:
  - Define and accept continuation semantics for request, bounded resolution,
    denial, timeout, and resumed execution.
  - Add an adapter-neutral context request channel and Codex MVP transport.
  - Attribute added context tokens and continuation attempts to the assignment.
  - Ensure unresolved requests cannot silently masquerade as ordinary retries.
- Acceptance criteria:
  - A real or fixture-backed Codex session requests one allowed evidence ref,
    receives only that bounded context, and resumes deterministically.
  - Denied, unavailable, and expired requests remain structured and replayable.
  - Unrelated branch history is never disclosed by the continuation path.
- Completion evidence:
  - RFC-006 and ADR-006 define harness-owned continuation identity, one bounded
    request/artifact policy, expiry, token budget, terminal statuses, and
    lifecycle replay semantics.
  - Codex may emit one untrusted `context_request` intent. The runtime resolves
    it against assignment-scoped artifact refs and resumes another ephemeral
    turn in the same logical session and isolated workspace.
  - Strict session staging records `context_requested`, `context_resolved`, and
    `context_resumed` before `result_submitted`; replay distinguishes
    `awaiting_context` and `context_blocked` from retry.
  - Session metrics attribute request count, continuation turns, granted
    artifacts, and added context token estimates. Tests cover granted resume,
    denied isolation, unavailable artifacts, expiry, budget rejection, staging,
    and replay.

## Workstream 2: Live Session Lifecycle

### [x] RM35-04: In-Flight Cancellation And Supersession

- Status: completed
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, agents, cancellation, process-control
- Dependencies: RM35-02
- Finding: REX-005
- Target code:
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/agents/registry.py`
  - `src/bureauless/cli/`
  - `tests/`
- Work:
  - Replace the blocking runner boundary with a live session handle that owns a
    process group and terminal state transition.
  - Implement idempotent cancel and supersede signals with bounded shutdown and
    forced termination fallback.
  - Preserve stdout, stderr, workspace delta, and partial outcome evidence.
  - Align advertised agent cancellation capability with exercised behavior.
- Acceptance criteria:
  - Cancellation terminates an active test process and records one deterministic
    terminal outcome.
  - A late process exit cannot overwrite cancelled or superseded state.
  - Replay never treats partial cancelled work as workflow completion.
- Completion evidence:
  - `LiveSessionHandle` owns one process controller and one terminal-state
    commit; repeated cancel/supersede requests are idempotent and first intent
    wins over late process exit.
  - Native shell and Codex launches use isolated process groups with bounded
    `SIGTERM` shutdown and `SIGKILL` fallback. CLI `session run` maps
    `KeyboardInterrupt` to the same live cancellation path.
  - Cancelled/superseded records retain stdout, stderr, workspace snapshots,
    deltas, metrics, and dispatch evidence while dropping result proposals.
  - Tests terminate a real process tree, prove forced and graceful paths,
    preserve partial evidence, and verify replay leaves the node runnable.

### [x] RM35-05: Truthful Turn-Report Integration

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4
- Risk: medium
- Labels: runtime, telemetry, agents
- Dependencies: RM35-02
- Finding: REX-006
- Target code:
  - `src/bureauless/protocol/dispatch.py`
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/agents/registry.py`
  - `tests/`
- Work:
  - Consume native progress/tool events where the adapter exposes them.
  - Define an explicit degraded reporting mode for adapters without that stream.
  - Remove hard-coded tool-call counts and link reports to dispatch policy.
- Acceptance criteria:
  - Reports contain observed counts and timestamps rather than fabricated demo
    values.
  - Unsupported adapters report capability degradation explicitly.
  - Report policy violations are visible without becoming canonical mission
    facts automatically.
- Completion evidence:
  - Codex JSONL parsing records completed native command, MCP, search, file, and
    tool events with source IDs and native or wrapper-capture timestamps.
  - Dispatch-bound reports expose observed tool counts, token usage, telemetry
    mode, and policy compliance. Post-run aggregation is explicitly marked as a
    violation when policy requires after-each-tool reporting.
  - Adapters without an integrated event stream emit a degraded report with
    zero observed tool calls and a capability reason; no count is fabricated.
  - The live demo persists the runtime-produced report instead of hard-coding a
    tool-call count. Tests prove observed, degraded, and violation paths and
    confirm reports do not become canonical ledger facts automatically.

## Workstream 3: Generic Inspection And Policy Evidence

### [x] RM35-06: Reusable Runtime Run Bundle

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4
- Risk: medium
- Labels: runtime, application-service, api, workbench
- Dependencies: RM35-01, RM35-02
- Finding: REX-007
- Target code:
  - `src/bureauless/application/`
  - `src/bureauless/cli/`
  - `src/bureauless/api/server.py`
  - `tests/`
- Work:
  - Extract artifact-session manifest creation from the demo into a reusable
    application service.
  - Produce or update one run bundle from maintained normal session paths.
  - Keep missing optional artifacts explicit and preserve immutable references.
- Acceptance criteria:
  - Workbench M4 can inspect a non-demo maintained session through the same
    manifest API.
  - Demo and ordinary session manifests use one validator and producer.
  - Manifest generation does not become a second canonical ledger.
- Completion evidence:
  - `application.run_bundles` owns the shared producer, validator, atomic write,
    stable bundle identity, monotonic revision, explicit optional paths, and
    SHA-256 artifact index used by demo and ordinary sessions.
  - Maintained CLI and `/api/session/dispatch` paths produce a bundle whenever
    ledger context is supplied; the existing manifest API loads both demo and
    non-demo bundles and rejects changed or missing indexed artifacts.
  - Workbench accepts nullable advisor, context, result, outcome, and review
    references, suppresses empty-path requests, and renders unavailable states
    for an ordinary session bundle.
  - The bundle remains a discovery projection over mission, workflow, ledger,
    dispatch, session, and evidence files. It never writes canonical workflow
    events or replaces replay.

### [x] RM35-07: Advisor Invocation And Outcome Linkage

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4
- Risk: medium
- Labels: runtime, advisor, routing, metrics
- Dependencies: RM35-02
- Finding: REX-008
- Target code:
  - `src/bureauless/protocol/advisors.py`
  - `src/bureauless/runtime/`
  - `src/bureauless/cli/main.py`
  - `tests/`
- Work:
  - Execute one deterministic advisor-invoked path when policy requires it.
  - Link invocation, token use, recommendation, routing/review decision, and
    scored outcome without forcing advisor use on low-risk workflows.
  - Retain the existing low-risk `good_skip` path as a separate fixture.
- Acceptance criteria:
  - Tests prove one policy skip and one policy invocation.
  - Advisor outcomes cite the decision and observed cost they score.
  - An advisor recommendation cannot bypass dispatch or acceptance gates.
- Completion evidence:
  - Deterministic policy evaluation produces validated skip or invoked gate
    decisions from structured workflow facts; the low-risk single-node fixture
    remains `good_skip`, while high-risk/full-ledger facts invoke the
    `cost_risk_analyst` fixture.
  - Invoked runs persist a recommendation-only result, invocation record,
    observed token usage and cost, orchestrator disposition, routing/gate refs,
    and a scored `good_call` outcome. Invoked outcomes without these refs and
    observations are rejected.
  - `mission advisor-demo --scenario invoke|skip` exercises both maintained
    paths. The invoked fixture revises broadcast policy only after a separate
    orchestrator disposition; the advisor artifact cannot contain workflow,
    dispatch, command, ledger-event, or acceptance authority.
  - Tests prove skip/invoke selection, cost and reference linkage, scoring, CLI
    operation, overreach rejection, and that advisor events do not complete a
    workflow node or satisfy a gate.

## Workstream 4: Acceptance And Handoff

### [x] RM35-08: Execution Spine End-To-End Acceptance

- Status: completed
- Priority: critical
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, e2e, docs, workbench
- Dependencies: RM35-01 through RM35-07
- Target code:
  - `tests/`
  - `src/bureauless/cli/main.py`
- Target docs:
  - `docs/audits/2026-07-02-runtime-execution-gap-analysis.md`
  - `docs/roadmap/development_roadmap.md`
  - `docs/protocol/`
- Work:
  - Add one maintained path proving pre-launch dispatch, bounded context
    continuation, truthful progress, explicit acceptance, cancellation safety,
    advisor policy evidence, replay, and generic Workbench discovery.
  - Update every audit finding with closure evidence and correct all capability
    language that remains narrower than the protocol intent.
- Acceptance criteria:
  - No critical or high audit finding remains unowned or unverified.
  - Runtime M4 can rely on explicitly accepted linear history.
  - The audit can be marked closed under `docs/audits/README.md` rules.
- Completion evidence:
  - `mission execution-spine-acceptance <workspace>` runs a no-network Codex
    fixture through validated pre-launch dispatch, one bounded context
    request/resume, observed native tool telemetry, staged result intake,
    explicit review/outcome acceptance, and accepted linear replay.
  - The same command runs a real process-group cancellation probe, advisor
    skip/invoke fixtures, and ordinary-session run-bundle discovery, then writes
    `execution_spine_acceptance.yaml`. Any failed check makes the command fail.
  - Maintained backend tests verify the report, ordered context/result/review/
    outcome events, cancellation safety, bundle references, and loading the
    generated non-demo bundle through the Workbench manifest API.
  - Full verification passes with 207 backend tests, 34 Chromium Workbench
    smoke tests, the production web build, Python compilation, and diff checks.
  - REX-002 through REX-008 are closed. REX-001 remains explicitly deferred to
    Runtime M4 and is not represented as implemented by this milestone.

## Recommended Execution Order

1. RM35-01 acceptance authority.
2. RM35-02 executable dispatch.
3. RM35-04 in-flight lifecycle control.
4. RM35-03 context continuation.
5. RM35-05 truthful turn reports.
6. RM35-06 reusable run bundle.
7. RM35-07 advisor invocation evidence.
8. RM35-08 end-to-end acceptance and audit closure.

## Milestone Acceptance

Runtime M3.5 is complete only when the maintained runtime proves that validated
artifacts control real execution rather than merely describing it afterward.
Completion requires maintained rejection, cancellation, context-continuation,
advisor-invocation, and non-demo Workbench discovery evidence.

RM35-08 satisfies this acceptance boundary; the milestone is complete.
