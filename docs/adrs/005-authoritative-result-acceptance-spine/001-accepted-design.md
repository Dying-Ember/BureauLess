# ADR-005: Authoritative Result Acceptance Spine

## Status

Accepted and implemented by RM35-01 in Runtime Harness Milestone 3.5.

## RFC

- Source RFC:
  [`docs/rfcs/005-authoritative-result-acceptance-spine.md`](../../rfcs/005-authoritative-result-acceptance-spine.md)

## Context

Raw result import currently appends worker-declared workflow events, and replay
accepts those events when no node-outcome decision exists. Review decisions are
recorded separately and do not control that acceptance. This allows unreviewed
or failed verification evidence to coexist with workflow progress.

## Decision

1. `node_outcome_decided` is the sole workflow-event acceptance authority in
   strict ledgers.
2. Result import is staged: `result_submitted` preserves claims and evidence but
   does not satisfy workflow waits.
3. A harness-owned acceptance service combines dispatch-bound review policy,
   independently evaluated verification evidence, and node-outcome state.
4. Review verdicts map deterministically: only `approved` may produce accepted
   events; `rejected` and `changes_requested` accept none.
5. `not_run` is not equivalent to `not_required`; the default acceptance policy
   requires `passed` verification.
6. One `source_outcome_id` may have only one terminal outcome decision.
7. `ledger_version: 2` uses strict acceptance. Version 1 remains readable with
   historical replay behavior but becomes read-only through maintained mutation
   paths.
8. V1-to-v2 migration is explicit, creates a new artifact, and quarantines
   undecided legacy workflow events by default.
9. `acceptance_policy` is embedded directly in the dispatch packet for M3.5.
10. Migrated assignments use normal outcome-decision operations; there is no
    separate bulk-acceptance path.
11. `awaiting_acceptance` is a structured blocked reason, not a new node-state
    enum value.

## Consequences

- Worker result claims remain auditable without becoming canonical progress.
- Replay and gatekeeper state advance only at an explicit accepted outcome
  decision.
- Existing v1 ledgers retain deterministic historical reads, while new writes
  cannot continue the unsafe compatibility behavior.
- CLI, API, demos, and future dispatch code must share one acceptance service.
- Workbench must distinguish claimed events, review verdicts, and effective
  accepted events.

## Implementation

- `src/bureauless/application/acceptance.py`
- `src/bureauless/protocol/results.py`
- `src/bureauless/protocol/reviews.py`
- `src/bureauless/protocol/outcomes.py`
- `src/bureauless/protocol/ledger.py`
- `src/bureauless/runtime/replay.py`
- `src/bureauless/cli/`
- `src/bureauless/api/server.py`
- `docs/protocol/harness_protocol.md`
- `docs/tasks/runtime_harness_milestone_3_5_tasklist.md`
