# ADR-003.4: Protocol Public Exports Boundary

## Status

Accepted.

## RFC

- Source RFC: [`docs/rfcs/003-engineering-boundary-refactor.md`](../../rfcs/003-engineering-boundary-refactor.md)
- Related task: [`docs/tasks/engineering_boundary_refactor_tasklist.md`](../../tasks/engineering_boundary_refactor_tasklist.md)

## Context

`src/bureauless/protocol/__init__.py` currently re-exports most protocol
documents, validators, helper functions, and intermediate types. That makes
`bureauless.protocol` convenient to import from, but it also hides ownership.
Internal modules can depend on package-level exports instead of importing the
module that actually owns the behavior.

The current codebase already has a cleaner structure below the package level:
`harness.py` owns mission/workflow/ledger documents, `assignments.py` owns
assignment export, `results.py` owns result imports, and so on. The package
root should expose only the stable protocol entrypoints that external callers
are expected to use directly.

## Decision

1. Treat `bureauless.protocol` as a small facade for stable document-level
   entrypoints.
2. Keep package-level exports for:
   - mission, workflow, and ledger document loading and compilation;
   - assignment export/loading/prompt rendering;
   - result, review, advisor, routing, dispatch, and context artifact loading
     or application flows that are used directly by CLI or API boundaries;
   - ledger append/write operations used by top-level command and API flows.
3. Stop re-exporting package-internal helper types and lower-level helpers that
   do not need a stable top-level import path.
4. Require internal callers to import from the owning submodule directly when
   they need narrower types or helper functions.
5. Preserve intentionally stable imports during this refactor and move any
   remaining internal package-root imports behind direct submodule imports.

## Consequences

- `bureauless.protocol` becomes easier to reason about as a public surface.
- Internal code becomes more explicit about which protocol module it depends
  on.
- Tests that exercise internal helpers may need direct imports from protocol
  submodules instead of the package root.
- Future protocol modules should add package-root re-exports only when the
  import path is meant to be stable for boundary callers.

## Implementation

- `src/bureauless/protocol/__init__.py`
- `src/bureauless/cli/`
- `src/bureauless/api/server.py`
- `src/bureauless/application/demo.py`
- `tests/test_harness.py`
- `tests/test_server.py`
