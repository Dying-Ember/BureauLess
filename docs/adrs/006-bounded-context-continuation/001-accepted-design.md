# ADR-006: Bounded Context Continuation

## Status

Accepted for RM35-03 in Runtime Harness Milestone 3.5.

## RFC

- Source RFC:
  [`docs/rfcs/006-bounded-context-continuation.md`](../../rfcs/006-bounded-context-continuation.md)

## Decision

1. Workers emit a context-request intent; the harness owns canonical request
   and continuation identity, timestamps, policy, and expiration.
2. One logical session may contain multiple adapter turns under the same
   assignment, dispatch, and isolated workspace. These turns are continuation,
   not assignment retry.
3. The maintained policy permits one request and one scoped artifact with an
   explicit added-token ceiling.
4. Only granted or partially granted resolutions resume execution. Denied,
   unavailable, expired, budget-exceeded, and exhausted requests produce a
   blocked session with no result proposal.
5. Resumed input contains only the bounded assignment and canonical resolution;
   unrelated ledger history is never added.
6. Strict staging records ordered context lifecycle events before the result.
   Context events do not satisfy workflow waits.
7. Session metrics separately report continuation turns and resolver-estimated
   added context tokens.
8. The Codex MVP uses another ephemeral process turn in the same isolated
   workspace; provider-native resume is deferred.

## Consequences

- Context disclosure becomes an explicit runtime control loop rather than an
  operator-only artifact.
- Session execution may involve several short processes while preserving one
  logical attempt and terminal authority.
- Replay and telemetry can distinguish unresolved disclosure from retry.
- Broader retrieval, native resume, and multi-request policies require later
  explicit milestones.

## Implementation

- `src/bureauless/protocol/context.py`
- `src/bureauless/runtime/sessions.py`
- `src/bureauless/application/acceptance.py`
- `src/bureauless/protocol/ledger.py`
- `src/bureauless/runtime/replay.py`
- `src/bureauless/cli/`
- `src/bureauless/api/server.py`
- `tests/`
