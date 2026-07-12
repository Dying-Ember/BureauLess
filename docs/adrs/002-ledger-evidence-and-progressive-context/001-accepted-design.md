# ADR-002: Ledger Evidence And Progressive Context

## Status

Accepted and implemented through Runtime Milestones 3 and 3.5.

## RFC

- Source RFC: [`docs/rfcs/002-ledger-evidence-and-progressive-context.md`](../../rfcs/002-ledger-evidence-and-progressive-context.md)

## Context

BureauLess records durable mission state in a ledger, but native runtime traces
are too large and too specific to treat as canonical state. The system needs to
preserve evidence, commit only minimum-sufficient facts, and compile bounded
context for the next worker.

## Decision

1. Preserve native evidence separately from the ledger.
2. Record minimum-sufficient facts in the ledger.
3. Classify outcome content into observations, findings, decisions, and
   unknowns.
4. Keep current-state projections rebuildable and authoritative only when the
   projection cursor matches.
5. Compile bounded context capsules instead of rebroadcasting full history.
6. Use feedback from observed outcomes to improve context policy.

## Consequences

- The ledger stays auditable without becoming a transcript store.
- Context delivery can remain bounded and role-specific.
- Future workers receive the facts they need without requiring every artifact by
  default.

## Implementation

- `docs/protocol/harness_protocol.md`
- `docs/architecture/context_economy.md`
- `src/bureauless/protocol/ledger.py`
- `src/bureauless/protocol/outcomes.py`
- `src/bureauless/protocol/context.py`
- `src/bureauless/runtime/metrics.py`
