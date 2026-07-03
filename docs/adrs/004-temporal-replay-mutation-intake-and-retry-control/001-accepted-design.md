# ADR-004: Temporal Replay, Mutation Intake, And Retry Control

## Status

Accepted on 2026-07-03 for Runtime Harness Milestone 4. Implementation is
pending under RM4-01 through RM4-11.

## RFC

- Source RFC:
  [`docs/rfcs/004-temporal-replay-mutation-intake-and-retry-control.md`](../../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md)

## Context

Milestone 2.5 supports controlled current-state workflow mutation, and Runtime
M3.5 establishes authoritative dispatch, result acceptance, context,
cancellation, telemetry, advisor, and replay foundations. The maintained agent
path still lacks a version-bound mutation-intent channel, bounded retry control,
and historical replay through an event cursor. Implementing those features
without accepted semantics would risk ambiguous stale proposals, future-event
leakage, and unchanged token-burning retries.

## Decision

1. Every worker may emit at most one inert `workflow_mutation` control intent
   with a completed or blocked result. The runtime owns canonical identity,
   provenance, base version, proposal artifact, event, and approval policy.
2. Result staging and intent intake are separate. Invalid, stale, unsupported,
   and duplicate intake never erases a valid result. Only a new valid proposal
   appends `workflow_mutation_proposed`.
3. Intake always returns an atomic `mutation_intake_disposition` evidence
   artifact. Failed validation appends no canonical event; review rejection is
   reserved for a valid registered proposal.
4. Proposal identity is deterministic from source result event, intent ordinal,
   base workflow version, and canonical intent payload. Duplicate transport
   returns the prior artifact/event without another append.
5. Codex CLI initially carries intents through structured final output. Native
   tools may be added later only through the same validator and intake service.
6. Retry policy `retry-v1` classifies transient, output-contract, verification,
   capability, deterministic, structural, stale/superseded, and policy
   failures. Total-attempt defaults are 3 for transient, 2 for repair/reroute,
   and 1 for non-retryable classes.
7. Retry turns have a default aggregate 20,000-token cap, further bounded by
   assignment and mission remainder. Non-transient retry requires changed
   evidence, input, strategy, assignment revision, or workflow version.
8. The second identical deterministic fingerprint opens the circuit; no third
   unchanged attempt launches. Retry scheduling and circuit opening are
   append-only events.
9. High-risk safety weakening, protected side effects, high-risk in-flight
   supersession, and permission expansion require a distinct human second
   approver. An orchestrator-authored proposal always requires another actor.
10. Review overdue state requires an explicit
    `workflow_mutation_review_overdue` event. Time metadata may trigger the
    event but never changes replay or accepts a proposal by itself.
11. Maintained mutation/version writes require `ledger_version: 3`. Migration
    is explicit and appends `workflow_version_initialized`; historical events
    are not rewritten.
12. Workflow hashes use canonical validated JSON and SHA-256. Version IDs
    combine workflow ID, accepted-mutation sequence, and a 12-character hash
    prefix. Version zero is sequence `0000`; only accepted mutation events create
    child versions.
13. `through_event_id` is inclusive. Replay through an accepted mutation sees
    the child version; an unknown cursor fails; final-cursor replay equals
    current replay; timestamps never order state.
14. Assignments retain their creation version across a child version only when
    deterministic impact proves their node, role, waits, emits, gates, scoped
    evidence, and forbidden actions unchanged. Affected work is superseded and
    late results cannot satisfy gates.
15. Mutation acceptance uses compare-and-swap over expected ledger tail and
    expected current workflow version. Stale proposals never auto-rebase.
16. V1, v2 compatibility, migrated v3, and native v3 ledgers have maintained
    fixtures. External workflow hash drift blocks version-sensitive operations
    until explicit human-approved recovery.
17. History is linear. Branching, rollback, counterfactual replay, timestamp
    replay, automatic proposal acceptance, provider expansion, and Workbench
    timeline UI remain outside Runtime M4.

## Consequences

- Workers gain a universal structural escape hatch without canonical write
  authority or a mandatory secondary agent.
- Valid execution evidence survives malformed control intent.
- Retry recovery remains possible, but unchanged deterministic loops have a
  hard stop and attributable budget evidence.
- Event-prefix replay has one deterministic workflow version and assignment
  validity model.
- Ledger v3 requires an explicit migration path and additional compatibility
  fixtures before maintained mutation writes can begin.
- Wall-clock deadlines need an event-producing scheduler or operator action;
  replay itself remains independent of current time.
- The first implementation is intentionally linear and may reject workflows
  that would require rebasing, branching, or rollback.

## Implementation

- `src/bureauless/protocol/mutations.py`
- `src/bureauless/protocol/results.py`
- `src/bureauless/protocol/ledger.py`
- `src/bureauless/runtime/sessions.py`
- `src/bureauless/runtime/replay.py`
- `src/bureauless/runtime/gatekeeper.py`
- `src/bureauless/application/`
- `src/bureauless/api/server.py`
- `docs/protocol/harness_protocol.md`
- `docs/tasks/runtime_harness_milestone_4_tasklist.md`
- `tests/`
