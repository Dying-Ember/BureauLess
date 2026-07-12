# ADR-003: Engineering Boundary Refactor Archive Index

## RFC

- Implemented RFC: `docs/rfcs/003-engineering-boundary-refactor.md`
- Tracking issue: [#2 RFC-003: Engineering Boundary Refactor (closed)](https://github.com/Dying-Ember/BureauLess/issues/2)

## Purpose

This directory archives the decision records that resolve the engineering
boundary refactor RFC.

## Accepted Decision Records

- `2026-06-30-shared-errors.md`: accepted; extract `ProtocolError` into `src/bureauless/errors.py`.
- `2026-06-30-cli-split.md`: accepted; split CLI command ownership into command modules.
- `2026-06-30-application-services.md`: accepted; introduce shared application services for CLI/API flows.
- `2026-06-30-protocol-exports.md`: accepted; narrow `bureauless.protocol` public exports to stable entrypoints.

## Correspondence Rules

- Each ADR in this directory must reference the RFC above.
- Each implementation PR should link back to the specific ADR file it satisfies.
- If a later ADR changes direction, it should supersede the earlier ADR inside
  this directory rather than moving to another topic.
