# Runtime Harness Task List

This is the implementation task list for the BureauLess runtime/harness line.
The project-level sequencing lives in `../roadmap/development_roadmap.md`.
Protocol contracts live in `../protocol/`; architecture rationale lives in
`../architecture/`.

The v1 runtime wraps external agent runtimes. It controls assignment, session,
result, artifact, gate, ledger, replay, and outcome-metrics boundaries. It does
not implement an internal coding-agent harness for model turns, tool calls, or
token-level tracing.

## Principles

- Keep YAML as the canonical persisted format.
- Keep protocol contracts in `docs/protocol`, not in implementation notes.
- Keep long-lived rationale in `docs/architecture`, not in task cards.
- Keep task cards concrete enough to become issues.
- Treat legacy DAG support as compatibility; new runtime work targets mission,
  workflow, ledger, assignment, session, replay, and metrics.
- Do not let workers or agent adapters write canonical ledger state directly.
- Mark a task `completed` only after its acceptance criteria have code coverage
  or an explicit CLI smoke check. Use `started` for partial implementation.

## Phase 1: Protocol Hardening

Goal: make the runtime safety contract explicit before expanding execution.

### [x] RT-01: Runtime Control Boundary

- Status: completed
- Priority: high
- Risk: medium
- Labels: runtime, protocol
- Target docs:
  - `docs/protocol/harness_protocol.md`
  - `docs/architecture/research_and_design_notes.md`
- Work:
  - State that v1 controls assignment/session/result boundaries, not internal
    model turns or tool-call traces.
  - State that agent runtime internals are native logs and optional artifacts.
  - Clarify that session-level outcome metrics are the v1 measurement target.
- Acceptance criteria:
  - Protocol docs distinguish external agent runtime wrapping from building an
    internal agent.
  - Architecture notes explain why v1 does not normalize every tool-call format.

### [x] RT-02: Runtime Invariants

- Status: completed
- Priority: high
- Risk: medium
- Labels: runtime, protocol
- Target docs:
  - `docs/protocol/harness_protocol.md`
- Work:
  - Add explicit invariants for worker scope, ledger writes, agent creation,
    model escalation, private hypotheses, and broader-context requests.
  - Mark invariant violations as validation failures or review blockers.
- Acceptance criteria:
  - A future validator can reject artifacts that violate these invariants.
  - The invariants are linked from assignment and result sections.

### [x] RT-03: Failure, Retry, And Cancellation Events

- Status: completed
- Priority: high
- Risk: medium
- Labels: runtime, protocol
- Target docs:
  - `docs/protocol/harness_protocol.md`
- Work:
  - Define event records for worker timeout, assignment cancellation, retry
    request, supersession, budget soft/hard limits, artifact invalidation, and
    gate expiry.
  - Define which events are terminal for an assignment.
- Acceptance criteria:
  - Runtime failures can be represented without ad hoc status strings.
  - Replay can distinguish cancelled, retried, superseded, timed-out, and
    completed assignments.

## Phase 2: Ledger, Artifact, Replay

Goal: make mission state append-only, verifiable, and replayable.

### [x] RT-04: Ledger Event Core

- Status: completed
- Priority: high
- Risk: medium
- Labels: runtime, replay
- Target code:
  - `src/bureauless/ledger.py`
  - `src/bureauless/cli.py`
  - `tests/test_harness.py`
- Work:
  - Add event data structures and append helpers.
  - Validate event ids, event types, actor/source fields, and duplicate events.
  - Keep raw worker reports separate from accepted public ledger facts.
  - Add `bureauless ledger validate` and `bureauless ledger append`.
- Acceptance criteria:
  - Valid events can be appended to a YAML ledger.
  - Duplicate or unknown events are rejected.
  - Public findings without provenance remain invalid.

### [x] RT-05: Artifact Integrity

- Status: completed
- Priority: high
- Risk: medium
- Labels: runtime, artifact-integrity
- Target code:
  - `src/bureauless/artifacts.py`
  - `src/bureauless/cli.py`
  - `tests/test_harness.py`
- Work:
  - Add artifact records with `artifact_id`, `path`, `sha256`, `created_by`,
    `source_event`, and `mutable`.
  - Verify accepted artifact refs against current file hashes.
  - Treat corrections as new artifacts and invalidations as events.
  - Add `bureauless artifact verify`.
- Acceptance criteria:
  - Modified artifacts are detected.
  - Missing artifacts make provenance incomplete rather than trusted.
  - Accepted artifacts cannot be mutable.

### [x] RT-06: Replay Engine

- Status: completed
- Priority: high
- Risk: high
- Labels: runtime, replay, gatekeeper
- Target code:
  - `src/bureauless/replay.py`
  - `src/bureauless/cli.py`
  - `tests/test_harness.py`
- Work:
  - Derive assignment, node, gate, artifact, and terminal workflow state from
    ledger events.
  - Return structured blocked reasons.
  - Keep replay read-only and deterministic.
  - Add `bureauless ledger replay`.
- Acceptance criteria:
  - The same ledger always produces the same replay state.
  - Replay explains runnable, blocked, completed, and expired states.

## Phase 3: Gatekeeper And Assignment

Goal: turn compiled workflows into bounded work packets.

### [x] RT-07: Gatekeeper Decisions

- Status: completed
- Priority: high
- Risk: high
- Labels: runtime, gatekeeper
- Target code:
  - `src/bureauless/gatekeeper.py`
  - `src/bureauless/cli.py`
  - `tests/test_harness.py`
- Work:
  - Evaluate empty waits, `all_of`, `any_of`, and node-qualified event refs.
  - Evaluate approval, artifact, and budget gates as accepted event references.
  - Reject committer-like nodes without patch and review evidence.
  - Add `bureauless gatekeeper ready`.
- Scope note:
  - Deep artifact hash validation belongs to RT-05.
  - Deterministic budget calculation belongs to RT-14.
- Acceptance criteria:
  - Runnable nodes and blocked reasons are machine-readable.
  - Workbench can consume gatekeeper output without duplicating rules.

### [x] RT-08: Assignment Export

- Status: completed
- Priority: high
- Risk: medium
- Labels: runtime, protocol
- Target code:
  - `src/bureauless/assignments.py`
  - `src/bureauless/cli.py`
  - `tests/test_harness.py`
- Work:
  - Export bounded assignment packets from runnable workflow nodes.
  - Include visible context, artifact refs, forbidden actions, expected events,
    and outcome metrics policy.
  - Render a prompt from the assignment packet.
  - Add `bureauless assignment export`.
- Acceptance criteria:
  - Non-runnable nodes cannot be exported without an explicit force path.
  - Assignment YAML contains enough boundary information for an external agent.

### [x] RT-09: Result Import

- Status: completed
- Priority: high
- Risk: high
- Labels: runtime, artifact-integrity
- Target code:
  - `src/bureauless/results.py`
  - `src/bureauless/cli.py`
  - `tests/test_harness.py`
- Work:
  - Import result proposals from manual or automated agent sessions.
  - Validate assignment id, emitted events, role permissions, artifacts, and
    required outcome metrics.
  - Append `result_submitted` events only after validation.
- Acceptance criteria:
  - Unauthorized emitted events are rejected.
  - Result import does not automatically accept public ledger facts.

## Phase 4: Agent Runtime Wrapper

Goal: safely wrap real external coding agents after the manual loop works.

### [x] RT-10: Agent Registry

- Status: completed
- Priority: high
- Risk: medium
- Labels: runtime
- Target code:
  - `src/bureauless/agents.py`
  - `tests/test_harness.py`
- Work:
  - Define specs for `codex-cli`, `claude-code`, and `opencode`.
  - Record non-interactive command, model/provider override strategy, config
    injection strategy, output format, cancellation behavior, and metrics
    capability.
- Acceptance criteria:
  - Agent specs are inspectable without launching an agent.
  - Model/provider is represented as a session property, not the top-level
    execution interface.

### [x] RT-11: Agent Doctor

- Status: completed
- Priority: high
- Risk: medium
- Labels: runtime, budget
- Target code:
  - `src/bureauless/agents.py`
  - `src/bureauless/cli.py`
  - `tests/test_harness.py`
- Work:
  - Add `bureauless agent list`.
  - Add `bureauless agent doctor <agent-id>`.
  - Check binary availability, version/help, non-interactive support,
    model/provider override, config isolation, working directory control,
    JSON output, persistence control, and metrics visibility.
- Acceptance criteria:
  - Missing agents return structured unavailable results.
  - Failed doctor checks disable automatic dispatch.
  - Warnings can be used by workflow selection and budget logic.

### [x] RT-12: Session Runtime Wrapper

- Status: completed
- Priority: high
- Risk: high
- Labels: runtime
- Target code:
  - `src/bureauless/sessions.py`
  - `src/bureauless/cli.py`
  - `tests/test_harness.py`
- Work:
  - Launch fake and shell dummy sessions first.
  - Add session records for start/end time, exit reason, native logs, diffs,
    artifacts, and outcome metrics.
  - Support timeout, cancellation, cleanup, and dry-run.
  - Add `bureauless session run --dry-run`.
- Acceptance criteria:
  - Session runtime can produce a result proposal without writing ledger state.
  - Timeout and cancellation produce structured records.

## Phase 5: Outcome Metrics And Budget Hooks

Goal: make token efficiency measurable at assignment/session granularity.

### [x] RT-13: Outcome Metrics

- Status: completed
- Priority: high
- Risk: medium
- Labels: runtime, budget
- Target code:
  - `src/bureauless/metrics.py`
  - `src/bureauless/cli.py`
  - `tests/test_harness.py`
- Work:
  - Record status, accepted/rejected outcome, agent/model/provider, wall time,
    token usage, cost, changed file count, patch bytes, artifact count,
    verification result, and review result.
  - Support unavailable token/cost data with explicit confidence.
  - Add `bureauless metrics summarize`.
- Acceptance criteria:
  - Completed assignments can be compared by agent/model/workflow mode.
  - Missing usage does not break summaries.

### [x] RT-14: Budget Oracle Snapshot

- Status: completed
- Priority: medium
- Risk: medium
- Labels: budget
- Target code:
  - `src/bureauless/budget.py`
  - `tests/test_harness.py`
- Target docs:
  - `docs/architecture/context_economy.md`
- Work:
  - Load model price snapshots.
  - Support token pricing, bundled quota, and unknown cost sources.
  - Calculate deterministic cost when token usage and price are available.
- Acceptance criteria:
  - Cost calculations cite their source and confidence.
  - Bundled/unknown pricing does not masquerade as precise USD cost.

## Phase 6: Runtime API Surface

Goal: expose runtime decisions to the workbench without duplicating rules.

### [x] RT-15: Runtime API Endpoints

- Status: completed
- Priority: medium
- Risk: medium
- Labels: runtime, workbench
- Target code:
  - `src/bureauless/server.py`
  - `tests/test_server.py`
- Work:
  - Add endpoints for mission, workflow, ledger, replay, gatekeeper, agents,
    doctor result, metrics, and review approval.
  - Return structured protocol errors without tracebacks.
- Acceptance criteria:
  - API output matches CLI-derived runtime state.
  - Workbench can show runtime state without reimplementing gatekeeper logic.

## Milestone 1 Acceptance

Runtime milestone 1 is complete when:

- A demo mission can run through manual compile, ready, assignment export,
  result import, approval, and replay.
- Replay explains runnable, blocked, completed, and expired states.
- Accepted artifacts are hash-verified.
- Outcome metrics are recorded at assignment/session level.
- Agent doctor can classify Codex CLI, Claude Code, and opencode control level.
- No external agent or worker can write canonical ledger state directly.
