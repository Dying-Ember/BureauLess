# RFC-004: Temporal Replay, Mutation Intake, And Retry Control

## Status

Draft for Runtime Harness Milestone 4. No ADR has been accepted and no runtime
implementation has started.

Implementation planning:
[`docs/tasks/runtime_harness_milestone_4_tasklist.md`](../tasks/runtime_harness_milestone_4_tasklist.md)

Related accepted design history:
[`RFC-001: Controlled Workflow Mutation`](001-controlled-workflow-mutation.md)

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
4. If invalid, preserve the valid result and record a distinct intake disposition.

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

## Open Questions Before ADR Acceptance

1. Which exact event or session disposition records invalid, duplicate, stale,
   and unsupported intent intake without conflating them with review rejection?
2. Which retry limits and token budgets are defaults versus assignment policy?
3. Which mutation operations require a second approver when the orchestrator is
   also the proposer?
4. Should `review_overdue` be derived from policy and time metadata or recorded as
   an explicit event?
5. Does the first Codex CLI implementation expose a native tool call, structured
   final output, or both, given the available non-interactive control surface?

## Acceptance Path

This RFC may advance to an ADR only after RM4-00 resolves the open questions,
defines compatibility fixtures, and confirms that the proposed contracts can be
validated without adding a mandatory secondary agent. Canonical implemented
rules then move into `docs/protocol/harness_protocol.md`.
