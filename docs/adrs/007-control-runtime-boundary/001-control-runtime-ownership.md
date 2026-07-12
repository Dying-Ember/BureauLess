# ADR-007.1: Control Runtime Ownership

## Status

Accepted on 2026-07-12.

## RFC

- Source RFC:
  [`docs/rfcs/007-control-runtime-boundary.md`](../../rfcs/007-control-runtime-boundary.md)
- Related RFC sections: Boundary; Invariants And Mechanisms; Adapter Rules.

## Decision

1. BureauLess owns the control runtime: launch admission, execution envelope,
   lifecycle supervision, bounded-context brokering, evidence capture, result
   intake, and canonical ledger transition.
2. External agents own their agent runtime: model loops, tool internals,
   planning, compaction, memory, provider streaming/retry, and tool
   implementations.
3. The core expresses invariant and capability requirements; adapters translate
   them into agent-specific mechanisms at the edge.
4. Adding an adapter or registering another agent does not by itself expand the
   product boundary. A change expands the boundary only when BureauLess starts
   owning the agent's internal execution mechanism.
5. An adapter must report unsupported or degraded control explicitly; it must
   not imply parity with stronger adapters.

## Consequences

- Multi-agent support remains possible without making workflow, ledger, or
  acceptance semantics agent-brand-specific.
- BureauLess can enforce governance during execution without becoming a
  replacement agent framework.
- Internal module decomposition and entrypoint cleanup remain implementation
  work, tracked separately in the related audit.

## Implementation

- Follow-up audit:
  [`2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md`](../../audits/2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md)
- Owning task list:
  [`control_runtime_boundary_follow_up_tasklist.md`](../../tasks/control_runtime_boundary_follow_up_tasklist.md)
- Future adapter and runtime tasks must cite this ADR when they add, remove, or
  degrade a control capability.
