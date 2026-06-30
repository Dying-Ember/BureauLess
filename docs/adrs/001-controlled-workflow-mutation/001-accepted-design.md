# ADR-001: Controlled Workflow Mutation

## Status

Accepted and implemented in Milestone 2.5.

## RFC

- Source RFC: [`docs/rfcs/001-controlled-workflow-mutation.md`](../../rfcs/001-controlled-workflow-mutation.md)

## Context

BureauLess needs a controlled channel for structural workflow changes that are
discovered during execution. Workers may detect missing dependencies, split a
task into bounded subtasks, or surface stale downstream work, but they must not
rewrite the workflow directly.

## Decision

1. Mutation proposals are inert until accepted.
2. Only accepted mutation ledger events change the workflow.
3. Accepted and rejected decisions must reference the original proposal event.
4. A worker may propose structural changes, but the orchestrator or a human
   reviewer decides whether they become effective.
5. Accepted mutations may supersede affected assignments instead of deleting
   historical state.
6. Current-state replay is supported; full temporal replay is deferred.
7. Canonical behavior lives in `docs/protocol/harness_protocol.md`.

## Consequences

- Workers stay bounded executors.
- The ledger remains the source of accepted history.
- Mutation inspection can explain pending, accepted, rejected, and superseded
  states without replaying arbitrary historical timelines.

## Implementation

- `src/bureauless/protocol/mutations.py`
- `src/bureauless/protocol/ledger.py`
- `src/bureauless/runtime/replay.py`
- `src/bureauless/api/server.py`
- `docs/protocol/harness_protocol.md`
- `docs/tasks/runtime_harness_milestone_2_5_tasklist.md`
