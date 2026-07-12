# RFC-004: Temporal Replay, Mutation Intake, And Retry Control

## Status

Accepted and implemented by Runtime Harness Milestone 4 under
[`ADR-004`](../adrs/004-temporal-replay-mutation-intake-and-retry-control/001-accepted-design.md).

Decision: accepted on 2026-07-03.

Tracking issue:
[#3 RFC-004: Temporal Replay, Mutation Intake, And Retry Control (closed)](https://github.com/Dying-Ember/BureauLess/issues/3)

Implementation planning:
[`docs/tasks/runtime_harness_milestone_4_tasklist.md`](../tasks/runtime_harness_milestone_4_tasklist.md)

Related accepted design history:
[`RFC-001: Controlled Workflow Mutation`](001-controlled-workflow-mutation.md)

ADR archive:
[`docs/adrs/004-temporal-replay-mutation-intake-and-retry-control/`](../adrs/004-temporal-replay-mutation-intake-and-retry-control/)

## Problem

Milestone 2.5 implemented controlled workflow mutation and current-state replay.
Milestone 3 added a maintained `codex-cli` execution path. The two capabilities
do not yet form a complete real-agent mutation loop:

- A worker result can carry `mutation_proposal_refs`, but the worker does not
  have a first-class, version-bound mutation-intent channel.
- The runtime preserves referenced artifacts but does not turn a worker intent
  into a validated canonical `workflow_mutation_proposed` event.
- `completed_with_proposal` couples execution outcome to proposal presence even
  though a completed or blocked execution may independently discover a workflow
  problem.
- Current-state replay cannot answer what the workflow or gatekeeper state was
  through an earlier ledger event.
- Unclassified retries can repeatedly spend tokens on an assignment whose
  workflow, evidence, and execution strategy have not changed.

The design must close those gaps without wrapping every worker in another LLM,
granting workers canonical write authority, or making replay depend on wall-clock
timestamps.

## Goals

1. Give every worker a safe structural escape hatch.
2. Separate untrusted worker intent from the trusted canonical proposal envelope.
3. Keep execution outcome valid when mutation-intent intake fails.
4. Bound retries by error class, changed information, and explicit budgets.
5. Introduce deterministic workflow versions and linear event-cursor replay.
6. Preserve explicit approval as the only path from proposal to workflow change.

## Non-Goals

- A mandatory mutation, planner, summarizer, or reviewer agent around each worker.
- Automatic acceptance of mutation proposals.
- Worker writes to canonical workflow or ledger state.
- Counterfactual branches, branch merge, branch comparison, or rollback.
- Timestamp-ordered replay.
- Provider expansion or a general agent tool platform.
- Workbench history UI in Runtime Milestone 4.

## Proposed Decisions

### 1. Proposal Is Universal; Application Is Privileged

The initial orchestration may itself be wrong. A binary per-worker permission to
propose mutation can therefore create a bootstrap failure: the worker that needs
the escape hatch may be the worker whose assignment omitted it.

Every worker may:

- report a `workflow_structure` issue;
- return one inert `workflow_mutation` intent with a result;
- provide evidence and a bounded suggested change.

No worker may:

- choose canonical proposal, artifact, or ledger event IDs;
- claim trusted assignment, session, agent, or workflow provenance;
- choose the approval policy;
- append ledger events or apply workflow changes.

Only a human, the existing orchestrator role, or an explicitly configured
deterministic approval policy may accept a valid proposal. High-risk operations
may require separation between proposer and approver. Forbidden operations stay
forbidden even when the proposal is inert.

### 2. Worker Intent And Trusted Envelope Are Separate Types

The worker emits a minimal untrusted intent:

```yaml
intent_type: workflow_mutation
reason: discovered_missing_dependency
rationale: Verification must complete before commit.
proposed_changes:
  add_nodes: []
  add_edges: []
  remove_edges: []
  supersede_assignments: []
evidence_refs:
  - artifact-verification-gap
```

Bureauless validates that intent against the assignment's observed workflow
version and creates the canonical envelope:

```yaml
proposal_id: proposal-<runtime-owned-id>
proposal_type: workflow_mutation
workflow_id: workflow-001
base_workflow_version_id: workflow-001:v0002
source:
  assignment_id: assign-001
  session_id: session-001
  agent_id: codex-cli
  actor: worker
requires_approval: orchestrator
intent: <validated-worker-intent>
```

Canonical IDs, provenance, base version, and approval policy are runtime-owned.
The worker cannot override them.

### 3. Transport Does Not Define Semantics

An adapter with tool support may expose a function such as:

```text
propose_workflow_mutation(reason, rationale, proposed_changes, evidence_refs)
```

The first Codex CLI path may carry the same payload through structured final
output. Both transports must enter the same validator and intake service. Tool
calling is a transport improvement, not a second mutation implementation.

### 4. Execution Outcome And Control Intent Are Orthogonal

The candidate result envelope is:

```yaml
status: blocked
emitted_events: []
verification:
  status: failed
control_intents:
  - intent_type: workflow_mutation
    reason: discovered_missing_dependency
    rationale: Verification must complete before commit.
    proposed_changes: {}
    evidence_refs:
      - artifact-verification-gap
```

A `completed` or `blocked` result may carry no intent or one active mutation
intent. Runtime M4 limits each result to at most one active mutation intent to
preserve linear proposal handling. Additional independent problems are reported
as evidence or later intents after the first decision.

Result import and intent intake are separate stages:

1. Validate and import the execution result.
2. Validate the optional intent.
3. If valid, create the immutable canonical proposal artifact and proposal event.
4. If invalid, preserve the valid result and record a distinct session/run
   evidence disposition without appending a canonical proposal event.

An invalid intent is not a review rejection. `workflow_mutation_rejected` remains
reserved for a valid proposal that an approver explicitly rejects.

### 5. Retry Is Classified, Bounded, And Replayable

The retry rule is:

> Except for a classified transient infrastructure failure, an assignment must
> not be retried when its inputs, available evidence, execution strategy, and
> workflow version are unchanged.

Every retry has a new `attempt_id`, a `retry_reason`, a reference to the prior
attempt, and an applicable attempt/token budget. Failed attempts remain in
history.

| Failure class | Runtime behavior |
| --- | --- |
| Network, rate limit, process launch failure, transient timeout | Retry with bounded attempts and backoff |
| Malformed structured output | At most one repair attempt with validator errors as new evidence |
| Compilation or verification failure | Retry only with failure evidence and a declared repair strategy |
| Agent/model capability mismatch | Reroute only through a new recorded routing decision |
| Repeated deterministic failure fingerprint | Open the circuit and move to `needs_review` |
| `workflow_structure` block | Stop execution retry and move to mutation review or `needs_replan` |
| Superseded assignment or stale workflow version | Never retry the old assignment version |
| Safety or permission rejection | Do not retry to bypass the policy |

The first execution failure can itself create new evidence. A retry using that
evidence is valid; an unchanged repetition after the same deterministic failure
is not.

### 6. Failure Fingerprints Prevent Token-Burning Loops

A deterministic failure fingerprint should include at least:

- assignment identity and revision;
- workflow version;
- normalized failure class and error code;
- relevant verification or validator result hash;
- effective agent/model/provider and execution strategy identity.

The runtime maintains attempt and token budgets per assignment and may also
enforce branch- and mission-level limits. Reaching the configured threshold
produces `needs_review` or `needs_replan`; it does not silently launch another
worker attempt.

No node returns from `structural_blocked`, `needs_replan`, or `superseded` to
`runnable` unless a relevant assignment revision, context/evidence set, routing
strategy, or workflow version changes.

### 7. Linear Workflow Versions Follow Ledger Order

The initial workflow is version zero. Each accepted mutation creates exactly one
child version in ledger append order. Proposed and rejected mutations do not
advance the structural version.

Each accepted mutation timeline entry exposes:

- `workflow_version_before`;
- `workflow_version_after`;
- the accepted mutation event ID;
- the parent version;
- a deterministic workflow content hash.

Ledger append order is authoritative. Timestamps are descriptive metadata only.

### 8. Historical Replay Uses An Inclusive Event Cursor

`through_event_id` means replay the ledger prefix including the named event. For
an accepted mutation event, the snapshot through that event observes the new
workflow version; the preceding cursor observes the parent version.

Historical replay must derive workflow, node, assignment, mutation, gatekeeper,
and terminal state using only the selected prefix. Replay through the final event
must equal current-state replay.

### 9. Stale And Concurrent Proposals Never Auto-Rebase

Every proposal is bound to the workflow version used by its source assignment.
If another mutation is accepted first, a proposal against the old base becomes
`stale`. Runtime M4 does not automatically rebase it.

Concurrent decisions use ledger-version compare-and-swap or an equivalent
single-writer check. Only one conflicting decision may win. A stale proposal can
be replaced only by a new intent against the current workflow version.

### 10. In-Flight And Late Results Are Version-Aware

When an accepted mutation affects an in-flight assignment, the runtime records
supersession and requests cancellation where supported. A late result remains
historical evidence but cannot satisfy gates under the new workflow version.

An intent from a late or superseded assignment may be preserved for audit, but
it cannot be registered as an applicable proposal against the new version.

### 11. Intake Is Idempotent And Recoverable

Transport retries use a session-scoped idempotency key. Canonical proposal
identity is deterministic for the source result, intent ordinal, and base
workflow version. Duplicate intake returns the existing disposition.

Proposal artifacts are written through a temporary path and atomic rename before
the corresponding event is committed. Recovery must detect and reconcile an
orphan artifact or an event whose artifact is unavailable; it must not silently
apply a mutation.

### 12. Pending Review Cannot Block Silently Forever

A pending proposal may acquire `review_overdue` inspection state after a policy
deadline. Expiry never means automatic acceptance. The configured policy may
escalate to a human, explicitly reject, or leave the affected branch terminally
blocked with an explanation.

## Required Invariants

1. No explicit approval, no workflow change.
2. No matching base workflow version, no mutation application.
3. An invalid intent never erases an otherwise valid execution result.
4. Future events never affect an earlier historical replay projection.
5. Except for classified transient infrastructure failures, no retry occurs
   without changed evidence, input, strategy, assignment revision, or workflow
   version.
6. Every retry and mutation decision is append-only and attributable.
7. A proposal never counts as successful task execution by itself.

## Edge-Case Decisions For Runtime M4

- A worker that cannot formulate a valid graph patch may report
  `workflow_structure` and enter `needs_replan` without retrying execution.
- Duplicate intents are deduplicated by normalized content, source result, and
  base version.
- Partial acceptance is compiled and impact-checked as a complete candidate
  workflow before the acceptance event is appended.
- Cross-mission and cross-workflow node, event, assignment, or artifact references
  are rejected.
- A mutation proposed after terminal mission completion is inspectable but does
  not reopen the mission without explicit approval.
- Existing ledgers without workflow-version fields use a deterministic read-only
  compatibility projection; historical events are not rewritten.
- External edits to the initial workflow are detected through the version-zero
  content hash.
- Mutation/version budgets limit repeated structural churn at assignment, branch,
  and mission scope.

## Resolved Decisions For ADR Acceptance

### Intake Disposition And Transaction Boundary

The intake service returns a `mutation_intake_disposition` evidence artifact
with one of these statuses:

- `registered`: a new canonical proposal artifact and
  `workflow_mutation_proposed` event were committed;
- `duplicate`: the deterministic proposal identity already exists, so the
  existing artifact/event is returned and no event is appended;
- `invalid`: schema, reference, or semantic validation failed;
- `stale`: the assignment-observed base version is no longer current;
- `unsupported`: the intent requests an operation outside the accepted M4
  mutation vocabulary.

`invalid`, `stale`, and `unsupported` dispositions are session/run evidence,
not canonical ledger events. This preserves the RM4-01 invariant that failed
validation is inert. Review rejection remains a separate
`workflow_mutation_rejected` event for a valid registered proposal.

Result staging commits first. Intent validation then writes the disposition
atomically. For `registered`, the immutable proposal artifact is atomically
renamed before its proposal event is appended. Recovery may delete an orphan
temporary file, return an existing deterministic artifact, or report a missing
artifact as corruption; it may never infer acceptance.

Canonical proposal identity is the first 16 hexadecimal characters of SHA-256
over the source result event ID, intent ordinal (`0` in M4), base workflow
version ID, and canonical intent payload. The runtime owns all IDs and
provenance.

### Retry Defaults And Overrides

Retry policy version `retry-v1` defines total attempts, including the original:

| Failure class | Default total attempts | Additional requirement |
| --- | ---: | --- |
| transient infrastructure | 3 | bounded backoff; no evidence change required |
| malformed output contract | 2 | validator errors become new bounded evidence |
| verification/compilation | 2 | failure evidence plus declared repair strategy |
| capability mismatch | 2 | new routing decision and changed agent/model strategy |
| repeated deterministic fingerprint | 2 | second identical failure opens the circuit |
| workflow structure | 1 | mutation review or `needs_replan`; no execution retry |
| stale/superseded | 1 | new assignment against current version required |
| safety/policy rejection | 1 | no retry intended to bypass policy |

The default aggregate token budget for retry turns of one assignment is 20,000
tokens, additionally bounded by remaining assignment and mission budgets. An
assignment retry policy may lower the limit or raise it only within the
recorded mission remainder. Missing or unknown mission remainder cannot justify
raising the default. A retry is denied when either its class attempt limit or
token limit is exhausted.

Every scheduled retry appends `assignment_retry_scheduled` with a new
`attempt_id`, prior attempt reference, failure class/fingerprint, changed-input
evidence, strategy identity, and budget snapshot. Opening the circuit appends
`assignment_circuit_opened` and derives `needs_review` or `needs_replan`.
Backoff timestamps control launch timing only; ledger order controls replay.

### Approval Separation

The runtime derives approval policy from mutation impact. A distinct human
second approver is required when the proposal:

- removes or weakens a review, human, permission, commit, merge, deploy, or
  terminal safety dependency;
- removes a node or event that participates in such a dependency;
- supersedes an in-flight high-risk or protected-operation assignment; or
- expands role permissions or introduces a protected side effect.

The proposer cannot satisfy either approval slot. For lower-risk worker
proposals, one authorized orchestrator or human approval is sufficient. For an
orchestrator-authored proposal, approval must always come from a distinct actor.
Deterministic policy may approve only operations explicitly classified low risk
and may never stand in for the required human second approval.

### Review Deadline

`review_overdue` is activated only by an explicit
`workflow_mutation_review_overdue` event. Policy deadlines and timestamps tell a
scheduler when it may append that event, but timestamps do not change replay by
themselves. The event may trigger escalation, explicit rejection, or a blocked
branch; it never accepts a proposal.

### Codex MVP Transport

The first maintained Codex CLI implementation uses the structured final-output
`control_intents` channel. A native tool transport is deferred until the
non-interactive adapter exposes a reliable control surface. Future transports
must call the same validator and intake service and cannot change semantics.

### Exact Workflow Version Identity

Runtime M4 introduces `ledger_version: 3` for maintained mutation/version
writes. Version 1 remains historical-read only; version 2 retains strict result
acceptance and gains read-only temporal compatibility. Migration to v3 is
explicit and appends `workflow_version_initialized`; existing events are not
rewritten.

Workflow content is hashed as UTF-8 SHA-256 over the validated workflow mapping
serialized as canonical JSON with sorted keys and compact separators. Version
IDs use:

```text
<workflow_id>:v<accepted-mutation-sequence:04d>:<first-12-hash-characters>
```

Version zero uses sequence `0000`. Every accepted mutation appends exactly one
child version and records `workflow_version_before`, `workflow_version_after`,
full before/after content hashes, and parent version. Proposal and rejection
events do not advance the sequence.

For a `workflow_mutation_accepted` event, replay through that event observes the
child version. Every other event observes the version active immediately before
it unless that event explicitly creates a version. Event IDs remain unique and
ledger append order is the only ordering authority.

### Historical Cursor And Assignment Validity

`through_event_id` is inclusive. An omitted cursor means current replay through
the final event. An unknown cursor is an error. Historical replay reads only the
selected prefix; replay through the final event must equal current replay.

An assignment records its workflow version at creation. It remains valid in a
child version only when deterministic mutation impact says its node, role,
waits, emits, gates, scoped evidence, and forbidden actions are unchanged.
Otherwise acceptance appends supersession, requests cancellation for in-flight
work, and prevents late results from satisfying gates. Gatekeeper evaluation at
a cursor uses that cursor's workflow version and only effective accepted events
from assignments valid in that version.

Proposal acceptance uses compare-and-swap over both expected ledger-tail event
ID and expected current workflow version. A mismatch fails without appending a
decision. Proposals whose base is no longer current derive `stale`; M4 never
auto-rebases them.

### Compatibility Fixtures And External Drift

RM4 maintains fixtures for:

1. v1 ledgers under historical current-state compatibility;
2. v2 strict-acceptance ledgers with no explicit version metadata, projected
   read-only from version zero and accepted mutation order;
3. explicitly migrated v3 ledgers with `workflow_version_initialized`;
4. native v3 ledgers whose accepted mutations carry full version transitions.

The version-zero hash detects external workflow edits. A mismatch blocks
dispatch, mutation intake/application, and temporal replay beyond the last
verified version, and records `workflow_external_drift_detected` when a writer
observes it. Recovery requires an explicit human-approved migration or mutation;
the runtime does not silently treat external files as a new canonical version.

## Acceptance Outcome

RM4-00 resolves the prior open questions, defines compatibility fixtures, and
confirms a deterministic validator/application-service boundary without a
mandatory secondary agent. ADR-004 accepts these semantics. Implementation now
proceeds task-by-task under RM4-01 through RM4-11; implemented canonical rules
must be kept aligned in `docs/protocol/harness_protocol.md`.
