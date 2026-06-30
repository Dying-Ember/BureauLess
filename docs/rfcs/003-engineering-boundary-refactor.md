# RFC-003: Engineering Boundary Refactor

## Status

Draft. Decision records, if accepted, should be archived under
[`docs/adrs/003-engineering-boundary-refactor/`](../adrs/003-engineering-boundary-refactor/).

## Scope

CLI, protocol boundary, application service layer, shared errors.

## Summary

BureauLess now has clearer product goals than internal engineering boundaries.
The project already separates protocol models, runtime behavior, session
handling, workbench API, CLI commands, ledger operations, assignment/result
flows, and demo orchestration. The implementation boundary is starting to blur.

This RFC proposes a small refactor before adding more runtime or agent
features. The aim is to make the current system easier to maintain, test, and
extend without redesigning the product.

## Problem

Current symptoms include:

- `cli/main.py` has become a large command registry, dispatcher, demo runner,
  and orchestration script.
- Newer protocol/runtime modules still depend on `core.py` for shared errors.
- `protocol/__init__.py` re-exports too much, which makes the public surface
  unclear.
- CLI and API are likely to duplicate orchestration logic unless shared
  application services exist.

## Goals

- Make ownership boundaries explicit.
- Keep CLI thin and command-focused.
- Introduce an application service layer shared by CLI and API.
- Remove dependency from newer protocol/runtime code to legacy `core.py`.
- Reduce accidental public API surface.
- Improve maintainability without changing user-facing behavior.

## Non-Goals

- No database replacement.
- No workflow semantics change.
- No provider dispatch work.
- No microservices rewrite.
- No rebuild of the workbench.

## Proposed Changes

1. Introduce `src/bureauless/errors.py` and move `ProtocolError` there.
2. Split CLI commands into command-specific modules under `src/bureauless/cli/`.
3. Add an `application/` layer for shared use cases such as assignment export,
   result import, session import, and workflow compilation.
4. Narrow `bureauless.protocol` exports to stable entrypoints only.

## Migration Plan

1. Extract shared errors.
2. Split initial CLI command groups.
3. Add application services for the shared flows.
4. Narrow protocol exports.

## Risks

- Refactor delays feature work.
- Too much abstraction too early.
- Breaking existing commands.
- Public API instability.

## Success Criteria

- `cli/main.py` becomes small and mostly declarative.
- Command groups live in separate modules.
- Protocol/runtime code no longer depends on `core.py`.
- CLI and API can share application services.
- Protocol public exports are intentional.
- Existing workflows and README commands still work.
