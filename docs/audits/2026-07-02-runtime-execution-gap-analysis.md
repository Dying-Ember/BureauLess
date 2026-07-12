# Runtime Execution Gap Analysis

- Status: closed
- Audited baseline: `f6e3816febd5`
- Audit date: 2026-07-02
- Closed date: 2026-07-03
- Scope: maintained `codex-cli` runtime path, ledger acceptance, progressive
  context, lifecycle control, M3 artifacts, and Workbench artifact discovery
- Related milestones:
  [Runtime M2](../tasks/runtime_harness_milestone_2_tasklist.md),
  [Runtime M3](../tasks/runtime_harness_milestone_3_tasklist.md),
  [Runtime M3.5](../tasks/runtime_harness_milestone_3_5_tasklist.md), and
  [Runtime M4](../tasks/runtime_harness_milestone_4_tasklist.md)
- Owners: Runtime M3.5 completed execution-spine remediation; Runtime M4 owns
  the explicitly deferred mutation-intake finding

## Executive Summary

Runtime M2 and M3 delivered substantial protocol, validation, fixture, API, and
Workbench inspection coverage. The audit found that several artifacts described
as runtime control inputs are currently generated or inspected without driving
the maintained real-agent execution path.

Runtime M3.5 closed the acceptance, dispatch, context, cancellation, telemetry,
run-bundle, and advisor findings with maintained runtime and end-to-end
evidence. The remaining mutation-intake finding is explicitly deferred to
Runtime M4 because it depends on RFC-004 and a future accepting ADR. The
capability matrix continues to state that this path is not implemented.

## Capability Matrix

| Capability | Schema | Validation | Runtime integration | Operator surface | E2E evidence |
| --- | --- | --- | --- | --- | --- |
| Mutation intent intake | partial legacy shape | partial | missing | inspect/decide only | missing |
| Result review and outcome acceptance | complete | complete in v2 | strict v2 complete; v1 read compatibility | CLI/API/Workbench-readable | maintained acceptance and rejection paths |
| Dispatch packet | complete | complete | authoritative pre-launch bridge | compile/dispatch/inspect | maintained CLI/API/Codex demo paths |
| Progressive context request | complete | complete | bounded request/resolve/resume loop | CLI/API/session evidence | fixture-backed Codex continuation and replay |
| In-flight cancellation | complete | complete | live process-group control | live handle and CLI interrupt | forced/graceful process and replay paths |
| Turn reports | complete | complete | native-event observation with explicit degradation | session/demo inspect | observed, degraded, and policy-violation paths |
| Artifact session manifest | complete | shared producer, validator, revision, and hash index | demo and ordinary maintained sessions | Workbench inspect with explicit unavailable states | API plus non-demo Workbench smoke |
| Advisor invocation policy | complete | shared gate/recommendation/invocation/outcome validation | deterministic skip and invoked paths | CLI plus inspect/score | cost-linked good-skip and good-call fixtures |

## Findings

### REX-001: Mutation Intent Does Not Reach Proposal Intake

- Severity: high
- Status: closed by Runtime M4 and ADR-004
- Claim: a worker can identify a structural problem and submit a controlled
  workflow mutation proposal.
- Evidence: the Codex output contract in
  [`sessions.py`](../../src/bureauless/runtime/sessions.py) accepts only legacy
  `mutation_proposal_refs`; result import does not parse an agent intent or
  register `workflow_mutation_proposed`.
- Impact: the agent can mention or reference a mutation, but the harness cannot
  complete `detect -> validate -> pending review` through the normal session
  path.
- Disposition: RM4-01 through RM4-05 and RFC-004.
- Decision requirement: RFC-004 and its accepting ADR.
- Deferral evidence:
  - Runtime M4 task RM4-01 owns version-bound worker mutation-intent intake, and
    RM4-00 owns the prerequisite RFC/ADR decision.
  - Draft [`RFC-004`](../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md)
    records the unresolved intent, retry, cursor, and workflow-version semantics.
  - The roadmap and capability matrix continue to label real-agent mutation
    intake as missing. Runtime M3.5 does not claim this capability.

### REX-002: Result Events Can Bypass Authoritative Acceptance

- Severity: critical
- Status: closed by RM35-01 and ADR-005
- Claim: worker observations, review decisions, and accepted workflow state are
  separate; only explicitly accepted outcome events advance replay.
- Baseline evidence at `f6e3816febd5`:
  - [`protocol/results.py`](../../src/bureauless/protocol/results.py)
    `import_result_proposal` appends every declared workflow event.
  - [`runtime/replay.py`](../../src/bureauless/runtime/replay.py)
    `_workflow_event_is_accepted` treats an event with no outcome decision as
    accepted for compatibility.
  - [`cli/exchange.py`](../../src/bureauless/cli/exchange.py) and
    [`api/server.py`](../../src/bureauless/api/server.py) expose direct import
    paths that do not create a node-outcome decision.
  - [`runtime/sessions.py`](../../src/bureauless/runtime/sessions.py)
    `import_session_record` defaults to accepting all emitted events before the
    later review decision is applied.
- Baseline impact: failed or unreviewed verification could advance downstream
  gates; review rejection did not authoritatively revoke the already accepted
  result.
- Disposition: define one acceptance authority, migrate compatibility imports,
  and add rejection/partial-acceptance integration tests in RM35-01.
- Decision requirement:
  [`RFC-005`](../rfcs/005-authoritative-result-acceptance-spine.md) accepted by
  [`ADR-005`](../adrs/005-authoritative-result-acceptance-spine/001-accepted-design.md).
- Closure evidence:
  - `src/bureauless/application/acceptance.py` owns staged intake and deterministic
    outcome acceptance.
  - Ledger v2 strict replay ignores raw workflow events and exposes
    `awaiting_acceptance`; v1 remains readable and requires explicit migration
    before maintained writes.
  - CLI/API/golden/live-demo paths use staged acceptance, and maintained tests
    cover approved, rejected, changes-requested, failed-verification, partial,
    duplicate-decision, migration, and compatibility behavior.

### REX-003: Dispatch Packet Is Not The Executable Handoff

- Severity: high
- Status: closed by RM35-02
- Claim: a canonical dispatch packet is validated before an external session
  starts and its constraints govern the launch.
- Baseline evidence: [`cli/main.py`](../../src/bureauless/cli/main.py) created a
  `SessionSpec` directly from CLI parameters and called `run_session` before it
  compiled the dispatch packet. No runtime entrypoint consumed a dispatch packet
  to produce the launched session.
- Impact: routing, review constraints, and turn-report policy are auditable
  metadata rather than authoritative execution inputs.
- Disposition: make validated packet compilation precede launch and derive the
  session binding and runtime constraints from the packet or a linked harness
  binding owned by the same dispatch operation.
- Decision requirement: no standalone RFC unless target-binding ownership
  cannot be resolved from existing protocol invariants.
- Closure evidence:
  - `runtime.sessions.dispatch_session` validates and atomically persists the
    packet before it derives or launches a session.
  - The packet-owned assignment, review constraints, routing mode, and report
    policy govern Codex launch input; the linked session spec owns agent,
    model, provider, sandbox, timeout, and workspace binding.
  - Session records retain packet path/hash plus the canonical binding, and
    reconstruction rejects packet, assignment, or evidence mismatches.
  - CLI `session run`, `/api/session/dispatch`, `/api/runtime-demo`, and the
    maintained live demo all use the bridge. Tests prove pre-run rejection,
    pre-launch persistence, prompt constraints, reconstruction, and tamper
    rejection.

### REX-004: Context Requests Do Not Round Trip Through A Real Session

- Severity: high
- Status: closed by RM35-03 and ADR-006
- Claim: a worker can request one relevant evidence reference and receive a
  bounded resolution without full-ledger disclosure.
- Baseline evidence: context request loaders, validators, resolver, and API existed, but
  the Codex output contract has no request channel and the maintained M3 demo
  records `context_request_path: null` for every step.
- Impact: progressive disclosure is available to fixtures and operators, not to
  the maintained agent session that needs it.
- Disposition: define a bounded pause/request/resolve/resume state machine or an
  equivalent adapter-neutral interaction contract, then prove it with Codex.
- Decision requirement: RFC and ADR because continuation identity, token budget,
  timeout, and replay behavior require explicit semantics.
- Closure evidence:
  - [`RFC-006`](../rfcs/006-bounded-context-continuation.md) and
    [`ADR-006`](../adrs/006-bounded-context-continuation/001-accepted-design.md)
    define continuation identity, bounded disclosure, expiry, token budget,
    terminal outcomes, and replay semantics.
  - The Codex output contract accepts one request intent; the harness creates
    canonical identity, resolves only assignment-scoped refs, and resumes in
    the same logical session and workspace.
  - Denied, unavailable, expired, budget-exceeded, and exhausted requests do
    not resume or produce an importable result.
  - Strict staging persists ordered context lifecycle events, replay separates
    context waiting/blocking from retry, and tests prove unrelated artifact
    history is not disclosed.

### REX-005: Cancellation Does Not Stop A Running Agent Process

- Severity: high
- Status: closed by RM35-04
- Claim: the runtime supports externally enforced session cancellation and
  records deterministic cancellation evidence.
- Baseline evidence: [`runtime/sessions.py`](../../src/bureauless/runtime/sessions.py)
  executed Codex with synchronous `subprocess.run`; `cancel_session_record`
  rewrites an already returned record and owns no live process handle.
- Impact: operators cannot stop an active agent, and declared `process_kill`
  capability is not exercised by the runtime.
- Disposition: add a live session handle/process-group lifecycle with idempotent
  cancellation, log preservation, and terminal-event integration.
- Decision requirement: implementation task; escalate to RFC only if persistent
  cross-process supervision enters scope.
- Closure evidence:
  - `LiveSessionHandle` owns the running process group and applies one terminal
    cancel or supersede intent after process collection, so late exit cannot
    overwrite control state.
  - Native shell and Codex runners use bounded process-group termination with a
    forced-kill fallback; CLI interruption calls the same handle.
  - Partial logs, workspace state, deltas, metrics, and dispatch evidence are
    retained, while result proposals are removed from cancelled work.
  - Maintained tests exercise graceful and forced termination, child-process
    cleanup, idempotence, supersession, and replay that never treats partial
    cancelled work as completion.

### REX-006: Turn-Report Policy Is Not Enforced

- Severity: medium
- Status: closed by RM35-05
- Claim: workers submit bounded turn reports after tool calls or configured work
  intervals.
- Baseline evidence: dispatch packets defaulted to `after_each_tool_call: true`, while the
  maintained demo creates one completed report after the session and hard-codes
  `tool_calls_since_last_report: 1`.
- Impact: operators cannot rely on turn reports for live progress, interruption,
  or policy enforcement.
- Disposition: consume supported native event streams and state the fallback
  behavior for adapters without tool-call telemetry.
- Decision requirement: no RFC if the existing protocol can express adapter
  capability degradation.
- Closure evidence:
  - Codex JSONL parsing records completed native tool events with source IDs
    and native or wrapper-capture timestamps; reports use those observed counts.
  - Adapters without integrated progress streams report explicit degraded mode
    and zero observed calls rather than a fabricated count.
  - Dispatch policy is linked into every report. Because current Codex events
    are aggregated after process exit, after-each-tool policy with observed
    tools is truthfully marked `violated`, not silently claimed as enforced.
  - Runtime-produced reports replace the demo's hard-coded report and remain
    inspection evidence; strict staging does not promote them to ledger facts.

### REX-007: Workbench Manifest Discovery Is Demo-Only

- Severity: medium
- Status: closed by RM35-06
- Claim: Workbench can inspect related runtime artifacts through an authoritative
  manifest.
- Baseline evidence at `f6e3816febd5`: the manifest was produced only by
  `run_live_demo`; ordinary session run/import paths did not create or update
  an artifact-session manifest.
- Baseline impact: Workbench M4 was complete against its demo acceptance boundary, but it
  is not a generic operator surface for ordinary runtime sessions.
- Disposition: introduce a reusable run-bundle/manifest application service and
  use it from demo and normal maintained session paths.
- Decision requirement: no RFC unless run-bundle persistence becomes canonical
  runtime state.
- Closure evidence:
  - `application.run_bundles` is the single producer and validator for live-demo
    and ordinary-session bundles, with atomic updates, stable identity,
    monotonic revisions, and SHA-256 verification of indexed evidence.
  - CLI `session run` and `/api/session/dispatch` produce bundles from maintained
    sessions when ledger context is present. Optional result, outcome, review,
    context, advisor, and aggregate references are represented as explicit
    nulls rather than invented files.
  - The existing artifact-session manifest API loads the ordinary bundle, and
    Workbench smoke coverage proves nullable artifacts remain inspectable as
    unavailable without issuing empty-path requests.
  - Bundles are discovery projections only. Canonical state remains mission,
    workflow, and accepted ledger history; bundle generation appends no events.

### REX-008: Advisor Policy Proves Only The Skip Path

- Severity: medium
- Status: closed by RM35-07
- Claim: deterministic policy skips low-value advisor calls and invokes review
  for qualifying high-risk workflows, with measurable outcomes.
- Baseline evidence at `f6e3816febd5`: the maintained demo hard-coded `invoked: false` and later recorded a
  `good_skip`; there is no maintained advisor invocation session linked to the
  decision and outcome.
- Baseline impact: scoring and inspection were implemented, but the invocation half of the
  policy loop is unproven.
- Disposition: add one deterministic invoked fixture/path and preserve lazy skip
  behavior for the existing low-risk demo.
- Decision requirement: no RFC if existing advisor policy remains authoritative.
- Closure evidence:
  - `runtime.advisors.evaluate_advisor_policy` implements deterministic v0.1
    triggers and preserves the low-risk skip path.
  - `run_advisor_invocation` validates recommendation-only output and records
    fixture or observed telemetry, token usage, cost, gate decision, and
    recommendation references. Unknown recommendation fields are rejected.
  - `mission advisor-demo` proves separate skip and invoked fixtures. The
    invoked path records an orchestrator disposition before revising the
    pre-dispatch workflow and produces a cost-linked `good_call`; the live demo
    now emits a validated and ledger-linked `good_skip` outcome.
  - Runtime scoring requires recommendation disposition plus observed token and
    cost evidence for invoked calls. Tests prove an advisor artifact cannot
    contain dispatch, workflow mutation, commands, ledger events, or accepted
    event claims and cannot advance replay or gatekeeper state.

## Required Sequencing

1. Resolve REX-002 before treating accepted ledger history as a temporal replay
   source of truth.
2. Resolve REX-003 before calling dispatch packets execution constraints.
3. Resolve REX-004 and REX-005 before broadening automatic runtime operation.
4. Resolve REX-006 through REX-008 before declaring the M3 artifact set generic
   beyond the maintained demo.
5. Continue REX-001 under Runtime M4 on the critical acceptance and dispatch
   foundations now closed by Runtime M3.5.

## Closure Standard

This audit can move to `closed` when every finding is either:

- implemented with maintained unit and end-to-end evidence linked from this
  document; or
- explicitly deferred in the roadmap with a named future milestone, rationale,
  and non-misleading capability language in protocol and operator docs.

## Closure Outcome

RM35-08 satisfies this standard. REX-002 through REX-008 have maintained unit,
integration, CLI, API, and Workbench evidence. The deterministic
`mission execution-spine-acceptance` path additionally proves pre-launch
dispatch, bounded context continuation, observed turn reports, explicit
acceptance, cancellation safety, advisor policy, accepted replay, and generic
bundle discovery in one failing-on-error report.

REX-001 is the sole deferred finding. It remains open under Runtime M4 and
RFC-004; this audit closes because the deferral has a named owner, rationale,
and accurate missing-capability language rather than because mutation intake
was implemented.
