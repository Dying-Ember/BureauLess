# ADR-003.1: Shared Errors Boundary

## Status

Accepted.

## RFC

- Source RFC: [`docs/rfcs/003-engineering-boundary-refactor.md`](../../rfcs/003-engineering-boundary-refactor.md)
- Related task: [`docs/tasks/engineering_boundary_refactor_tasklist.md`](../../tasks/engineering_boundary_refactor_tasklist.md)

## Context

`ProtocolError` currently lives in `src/bureauless/core.py`. That was fine when
the project was mostly the legacy DAG/runtime compatibility layer. Newer
protocol, runtime, agents, API, and CLI modules now use the same error type,
which makes them depend on `core.py` even when they do not own legacy DAG
behavior.

This coupling blurs the boundary RFC-003 is meant to clarify.

## Decision

1. Create `src/bureauless/errors.py` as the canonical shared error boundary.
2. Move `ProtocolError` to that module.
3. Keep `bureauless.core.ProtocolError` as a compatibility import while legacy
   callers and tests still import it.
4. Update newer protocol/runtime/agents/API/CLI modules to import
   `ProtocolError` from `bureauless.errors`.
5. Do not introduce a larger exception hierarchy in this step.

## Consequences

- Newer modules can depend on a small shared error boundary instead of the
  legacy DAG compatibility module.
- Existing external imports from `bureauless.core` remain compatible.
- Future error-type expansion has a clear home, but this ADR does not require
  adding more types now.

## Implementation

- `src/bureauless/errors.py`
- `src/bureauless/core.py`
- `src/bureauless/protocol/*.py`
- `src/bureauless/runtime/*.py`
- `src/bureauless/agents/*.py`
- `src/bureauless/api/server.py`
- `src/bureauless/cli/main.py`
- `docs/tasks/engineering_boundary_refactor_tasklist.md`
