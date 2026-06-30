# Engineering Boundary Refactor Task List

This task list tracks implementation for
[`RFC-003: Engineering Boundary Refactor`](../rfcs/003-engineering-boundary-refactor.md)
and GitHub issue
[#2 RFC: Engineering Boundary Refactor](https://github.com/Dying-Ember/BureauLess/issues/2).

The RFC proposes a bounded refactor of ownership boundaries after Runtime
Harness Milestone 3 and Workbench Milestone 3 stabilized the current behavior.
This work should preserve user-facing CLI/API behavior while reducing internal
coupling.

Within this document, `workstream` names an implementation grouping. Each
workstream should be backed by an ADR in
[`../adrs/003-engineering-boundary-refactor/`](../adrs/003-engineering-boundary-refactor/).

## Principles

- Preserve existing CLI commands, API responses, and smoke-tested workflows.
- Move behavior behind clearer ownership boundaries before adding new runtime
  features.
- Keep refactors mechanical and test-backed.
- Prefer small commits that each leave the suite green.
- Do not combine boundary cleanup with product semantics changes.

## Workstream 1: Shared Errors Boundary

Goal: remove newer protocol/runtime dependency on legacy `core.py` for shared
error types.

### [x] EBR-01: Accept Shared Errors ADR

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: low
- Target files:
  - `docs/adrs/003-engineering-boundary-refactor/2026-06-30-shared-errors.md`
  - `docs/rfcs/003-engineering-boundary-refactor.md`
- Work:
  - Draft and accept the shared-errors ADR.
  - Link the ADR from the RFC decision history.
  - State the migration path for `ProtocolError`.
- Acceptance criteria:
  - The ADR identifies `src/bureauless/errors.py` as the canonical shared error
    boundary.
  - The RFC links to the ADR.
- Implementation notes:
  - Accepted
    [`2026-06-30-shared-errors.md`](../adrs/003-engineering-boundary-refactor/2026-06-30-shared-errors.md).
  - Cross-linked the RFC and ADR archive index.

### [x] EBR-02: Extract ProtocolError

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: EBR-01
- Target files:
  - `src/bureauless/errors.py`
  - `src/bureauless/core.py`
  - `src/bureauless/protocol/*.py`
  - `src/bureauless/runtime/*.py`
  - `tests/test_core.py`
  - `tests/test_harness.py`
  - `tests/test_server.py`
- Work:
  - Move `ProtocolError` to `src/bureauless/errors.py`.
  - Keep compatibility imports where needed.
  - Update newer protocol/runtime modules to import from `bureauless.errors`.
- Acceptance criteria:
  - Newer protocol/runtime modules no longer import `ProtocolError` from
    `bureauless.core`.
  - Existing tests that assert error behavior still pass.
- Implementation notes:
  - Added `src/bureauless/errors.py` as the canonical shared error boundary.
  - Kept `bureauless.core.ProtocolError` as a compatibility import.
  - Updated protocol, runtime, agents, API, CLI, and runtime workspace modules
    to import `ProtocolError` from `bureauless.errors`.
  - Verified compatibility with
    `PYTHONPATH=src python -c 'from bureauless.core import ProtocolError as C; from bureauless.errors import ProtocolError as E; print(C is E)'`.
  - Verified behavior with
    `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_core.py tests/test_harness.py tests/test_server.py -q`
    (`180 passed`).

## Workstream 2: CLI Command Ownership

Goal: make `cli/main.py` small and mostly declarative.

### [x] EBR-03: Accept CLI Split ADR

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: low
- Target files:
  - `docs/adrs/003-engineering-boundary-refactor/2026-06-30-cli-split.md`
  - `docs/rfcs/003-engineering-boundary-refactor.md`
- Work:
  - Draft and accept the CLI split ADR.
  - Define command module ownership and compatibility rules.
- Acceptance criteria:
  - The ADR identifies command groups that can move out of `cli/main.py`.
  - The ADR names commands that must remain behavior-compatible.
- Implementation notes:
  - Accepted
    [`2026-06-30-cli-split.md`](../adrs/003-engineering-boundary-refactor/2026-06-30-cli-split.md).
  - Defined initial command module groups while preserving the public
    `bureauless` CLI entrypoint.

### [ ] EBR-04: Split Initial CLI Command Modules

- Status: planned
- Priority: high
- Recommended model: gpt-5.4
- Risk: high
- Dependencies: EBR-03
- Target files:
  - `src/bureauless/cli/main.py`
  - `src/bureauless/cli/*.py`
  - `tests/test_harness.py`
- Work:
  - Move bounded command groups into command-specific modules.
  - Keep `main.py` as parser registration and dispatch glue.
  - Preserve all existing command names and arguments.
- Acceptance criteria:
  - CLI tests still pass.
  - `cli/main.py` is materially smaller and no longer owns demo/session
    orchestration details directly.

## Workstream 3: Application Services

Goal: share use cases between CLI and API instead of duplicating orchestration
logic.

### [ ] EBR-05: Accept Application Services ADR

- Status: planned
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Target files:
  - `docs/adrs/003-engineering-boundary-refactor/2026-06-30-application-services.md`
  - `docs/rfcs/003-engineering-boundary-refactor.md`
- Work:
  - Draft and accept the application services ADR.
  - Define first service boundaries without introducing broad abstractions.
- Acceptance criteria:
  - The ADR names the initial shared use cases and non-goals.
  - CLI/API ownership remains explicit.

### [ ] EBR-06: Introduce First Application Services

- Status: planned
- Priority: medium
- Recommended model: gpt-5.4
- Risk: high
- Dependencies: EBR-05
- Target files:
  - `src/bureauless/application/`
  - `src/bureauless/cli/`
  - `src/bureauless/api/server.py`
  - `tests/test_harness.py`
  - `tests/test_server.py`
- Work:
  - Introduce narrow shared services for the flows already used by CLI/API.
  - Move orchestration glue only when both callers benefit.
  - Keep IO and transport formatting at the CLI/API boundary.
- Acceptance criteria:
  - CLI and API share at least one application service.
  - API response shapes and CLI output behavior remain compatible.

## Workstream 4: Protocol Public Exports

Goal: make `bureauless.protocol` exports intentional and stable.

### [ ] EBR-07: Accept Protocol Exports ADR

- Status: planned
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Target files:
  - `docs/adrs/003-engineering-boundary-refactor/2026-06-30-protocol-exports.md`
  - `docs/rfcs/003-engineering-boundary-refactor.md`
- Work:
  - Draft and accept the protocol exports ADR.
  - Define stable public entrypoints and internal-only modules.
- Acceptance criteria:
  - The ADR states what `bureauless.protocol` should re-export.
  - Existing internal callers have a migration path.

### [ ] EBR-08: Narrow Protocol __init__ Exports

- Status: planned
- Priority: medium
- Recommended model: gpt-5.4
- Risk: high
- Dependencies: EBR-07
- Target files:
  - `src/bureauless/protocol/__init__.py`
  - `src/bureauless/protocol/*.py`
  - `tests/test_harness.py`
  - `tests/test_server.py`
- Work:
  - Reduce `bureauless.protocol` re-exports to ADR-approved entrypoints.
  - Update internal imports to direct module imports where appropriate.
  - Keep stable public imports compatible where intentionally retained.
- Acceptance criteria:
  - Tests pass with narrower exports.
  - Protocol public surface is documented in the ADR or protocol docs.

## Recommended Execution Order

1. EBR-01 Accept Shared Errors ADR
2. EBR-02 Extract ProtocolError
3. EBR-03 Accept CLI Split ADR
4. EBR-04 Split Initial CLI Command Modules
5. EBR-05 Accept Application Services ADR
6. EBR-06 Introduce First Application Services
7. EBR-07 Accept Protocol Exports ADR
8. EBR-08 Narrow Protocol `__init__` Exports

## Milestone Acceptance

- All four RFC-003 ADRs are accepted and cross-linked.
- `ProtocolError` lives at the shared errors boundary.
- `cli/main.py` is smaller and command ownership is split.
- At least one CLI/API shared use case lives in `application/`.
- `bureauless.protocol` exports are intentional.
- Existing runtime, server, and workbench tests pass.
