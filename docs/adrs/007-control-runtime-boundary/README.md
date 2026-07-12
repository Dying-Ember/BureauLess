# ADR-007: Control Runtime Boundary Archive

## RFC

- Source RFC: `docs/rfcs/007-control-runtime-boundary.md`
- Tracking issue: [#9 (closed)](https://github.com/Dying-Ember/BureauLess/issues/9)

## Purpose

This directory archives the decision records that resolve the control runtime
boundary RFC.

## Decision Records

- [`001-control-runtime-ownership.md`](001-control-runtime-ownership.md):
  accepted control-runtime versus agent-runtime ownership boundary.
- [`002-telemetry-evidence-levels.md`](002-telemetry-evidence-levels.md):
  accepted telemetry source and confidence boundary.

## Correspondence Rules

- Each ADR in this directory must reference the RFC above.
- Future adapter work should cite the accepted ADR when it adds or downgrades
  runtime capabilities.
- Implementation debt in session, CLI, or API modules should be tracked in
  audits or task lists unless it changes the boundary decision itself.
- Related audit:
  `docs/audits/2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md`
