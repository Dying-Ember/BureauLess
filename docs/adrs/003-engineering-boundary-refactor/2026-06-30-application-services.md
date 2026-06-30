# ADR-003.3: Application Services Boundary

## Status

Accepted.

## RFC

- Source RFC: [`docs/rfcs/003-engineering-boundary-refactor.md`](../../rfcs/003-engineering-boundary-refactor.md)
- Related task: [`docs/tasks/engineering_boundary_refactor_tasklist.md`](../../tasks/engineering_boundary_refactor_tasklist.md)

## Context

The CLI and API both need to run bounded BureauLess use cases, but neither
should import the other for business behavior. The first concrete smell is the
API importing `prepare_demo_workspace` from `src/bureauless/cli/main.py`.

CLI modules should own argument parsing, stdout/stderr formatting, and exit
codes. API modules should own request/response models and HTTP error handling.
Shared orchestration should live below both surfaces.

## Decision

1. Introduce `src/bureauless/application/` for narrow shared use cases.
2. Start with demo workspace preparation because both CLI and API already use
   it and the current API dependency on CLI is the clearest boundary violation.
3. Keep application services transport-neutral: no argparse, FastAPI,
   stdout/stderr, or HTTP response formatting.
4. Move shared use cases only when at least two callers benefit or an ownership
   violation exists.
5. Defer broad service abstractions until repeated flows justify them.

## Consequences

- API code no longer imports CLI modules for shared behavior.
- CLI command modules remain thin adapters over protocol/runtime/application
  functions.
- Application services may use protocol/runtime primitives, but should not own
  presentation concerns.
- Future candidates include assignment export/import orchestration, session
  import, and dispatch packet compilation.

## Implementation

- `src/bureauless/application/`
- `src/bureauless/application/demo.py`
- `src/bureauless/cli/main.py`
- `src/bureauless/api/server.py`
- `tests/test_harness.py`
- `tests/test_server.py`
