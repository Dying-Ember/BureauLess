# RFC-006: Bounded Context Continuation

## Status

Accepted for implementation by RM35-03 in Runtime Harness Milestone 3.5.

ADR:
[`ADR-006: Bounded Context Continuation`](../adrs/006-bounded-context-continuation/001-accepted-design.md)

Implementation tracking:
[`RM35-03: Progressive Context Request Continuation`](../tasks/runtime_harness_milestone_3_5_tasklist.md)

Source audit:
[`REX-004: Context Requests Do Not Round Trip Through A Real Session`](../audits/2026-07-02-runtime-execution-gap-analysis.md)

## Problem

Context request and resolution artifacts exist, but no maintained agent session
can emit a request, receive a bounded resolution, and continue. Treating a new
process invocation as an ordinary retry would lose continuation identity,
double-count attempts, and allow unresolved requests to masquerade as recovery.

## Goals

1. Define an adapter-neutral request, resolution, and resumed-turn state model.
2. Keep canonical identifiers, scope checks, expiration, and token budgets under
   harness control.
3. Preserve one assignment, logical session, dispatch, and isolated workspace
   across continuation turns.
4. Make granted, denied, unavailable, expired, and exhausted outcomes explicit
   and replayable.
5. Prove one fixture-backed Codex request and resume path without requiring
   native provider session persistence.

## Non-Goals

- Interactive arbitrary chat with a worker.
- Full-ledger disclosure or semantic retrieval outside assignment scope.
- More than one granted artifact per request in the maintained MVP.
- Treating continuation as assignment retry or workflow mutation.
- Provider-native session resume, streaming tool interception, or distributed
  continuation workers.

## Decision

### Agent Intent And Harness Envelope

The worker may finish a turn with `status: context_requested` and one intent:

```yaml
context_request:
  missing_information: Exact API behavior needed for the bounded patch.
  requested_refs: [artifact-api-contract]
  expected_value: Avoid guessing the existing contract.
```

The worker cannot choose request, continuation, session, assignment, policy, or
expiration identifiers. The harness builds the canonical request envelope.

### Continuation Identity

One logical session owns one `continuation_id`. Request indexes are monotonic
from one. Every request and resolution records assignment ID, session ID,
continuation ID, request index, timestamps, and policy version.

Continuation turns reuse the same assignment, dispatch evidence, and isolated
workspace. A new adapter process may be launched, but it is not an assignment
retry and does not append another `assignment_created` event.

### Resolution And Budget

The resolver may grant only artifacts already present in the assignment's
bounded artifact refs and canonical ledger artifact registry. The maintained
policy permits one request, one artifact, and a configured added-token ceiling.

`granted` and `partially_granted` may resume. `denied`, `unavailable`,
`expired`, and `budget_exceeded` terminate the logical session as blocked with
no importable result proposal. Expiration is evaluated against a harness clock,
not a worker timestamp.

### Resumed Input

The resumed prompt contains the original bounded assignment plus only the
canonical resolution, granted artifact records, and request identity. It does
not contain unrelated ledger history or denied artifact payloads.

### Ledger And Replay

Session execution returns ordered context lifecycle evidence. Strict result
staging appends `context_requested`, `context_resolved`, and `context_resumed`
events before `result_submitted`. These events never satisfy workflow waits.
Replay projects continuation state for an assignment and keeps it in flight
while a request is unresolved. Terminal denied, unavailable, expired, or
budget-exceeded resolutions leave the node blocked until an explicit later
control decision.

### Metrics

The session record reports continuation turn count, request count, granted
artifact count, and added context token estimate. Adapter-reported execution
tokens remain separate from resolver-estimated added context tokens.

## Alternatives Rejected

- Native Codex resume only: not adapter-neutral and couples correctness to one
  provider feature.
- New assignment per request: incorrectly turns disclosure into retry.
- Put full artifact contents into the request: violates bounded disclosure and
  duplicates immutable artifact storage.
- Operator-only resolution: does not close the maintained agent round trip.

## Acceptance

- A fixture-backed Codex turn requests one scoped ref and completes after one
  bounded resumed turn in the same workspace.
- Out-of-scope, missing, expired, and over-budget requests cannot resume.
- Context lifecycle evidence is validated, staged, replayable, and visible in
  session metrics without advancing workflow completion by itself.
