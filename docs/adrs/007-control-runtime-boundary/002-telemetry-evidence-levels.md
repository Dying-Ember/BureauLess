# ADR-007.2: Telemetry Evidence Levels

## Status

Accepted on 2026-07-12.

## RFC

- Source RFC:
  [`docs/rfcs/007-control-runtime-boundary.md`](../../rfcs/007-control-runtime-boundary.md)
- Related RFC sections: Telemetry Boundary; Adapter Rules.

## Decision

1. BureauLess captures telemetry at its control boundary and classifies the
   origin of every metric it presents as trustworthy execution evidence.
2. Allowed evidence levels are: provider-authoritative, agent-native observed,
   transport-observed, locally estimated, and unavailable.
3. Metrics retain their source and confidence. Unavailable authoritative
   evidence remains unavailable; it is not silently replaced with an estimate.
4. Adapters may expose agent-native telemetry, but agent-specific events do not
   become core protocol semantics unless separately accepted.

## Consequences

- Operators can distinguish measured provider usage from adapter observations
  and estimates.
- New adapters can improve telemetry fidelity without changing the common
  ledger or workflow model.
- Capability and confidence presentation remains follow-up implementation work
  in the related audit.

## Implementation

- Follow-up audit:
  [`2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md`](../../audits/2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md)
- Owning task list:
  [`control_runtime_boundary_follow_up_tasklist.md`](../../tasks/control_runtime_boundary_follow_up_tasklist.md)
- Future telemetry and adapter tasks must preserve these evidence levels when
  adding metrics or displays.
