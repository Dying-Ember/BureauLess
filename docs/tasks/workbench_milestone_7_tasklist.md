# Workbench Milestone 7 Task List

Status: completed. WB7-01 through WB7-05 are complete. This
milestone follows the completed Workbench Milestone 6 validated runtime
operator-actions surface and closes the current guided runtime-operations
frontend track for BureauLess.

This is the planned UI/workbench delivery milestone for BureauLess. It turns
the existing runtime demo, manifest, and run-bundle backend contracts into a
guided bootstrap and navigation surface without moving orchestration, ledger
mutation rules, or replay semantics into the frontend.

The project-level sequencing lives in
[`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md). The
backend scope comes primarily from
[`runtime_harness_milestone_3_5_tasklist.md`](runtime_harness_milestone_3_5_tasklist.md)
and [`runtime_harness_milestone_4_tasklist.md`](runtime_harness_milestone_4_tasklist.md),
with frontend foundations from
[`workbench_milestone_4_tasklist.md`](workbench_milestone_4_tasklist.md),
[`workbench_milestone_5_tasklist.md`](workbench_milestone_5_tasklist.md), and
[`workbench_milestone_6_tasklist.md`](workbench_milestone_6_tasklist.md).

Milestone 7 is a guided-operations milestone. It does not add frontend-owned
workflow mutation, dispatch validation, replay interpretation, or acceptance
semantics. The Python runtime remains authoritative for workspace bootstrap,
session packaging, artifact generation, and every canonical write.

## Goals

1. Make the Workbench usable from a cold start instead of requiring a
   preconstructed manifest path or manual artifact hunting.
2. Let an operator bootstrap a maintained runtime demo or open a run bundle,
   then move directly into the completed M4-M6 inspection and action surfaces.
3. Make artifact availability, source provenance, and missing evidence explicit
   so operators can tell whether a runtime view is actionable.

## Principles

- Reuse existing backend bootstrap and artifact APIs before inventing
  frontend-only workflows.
- Treat manifests and run bundles as backend-authored navigation roots.
- Keep generated path ownership in Python; the frontend only selects, invokes,
  and displays returned sources.
- Prefer one guided operator flow over many disconnected path fields.
- Keep missing optional artifacts explicit instead of silently hiding panels.
- Preserve the existing separation between planning-DAG editing and runtime
  operations.
- Land each step with focused smoke coverage that proves the frontend follows
  backend-owned manifests and run bundles.
- Recommended models should use current native Codex model names and reflect
  task complexity instead of a milestone-wide default.

## Workstream 1: Runtime Bootstrap Boundary

Goal: establish one typed frontend boundary for creating or opening runtime
artifact roots.

### [x] WB7-01: Runtime Demo Bootstrap API Client And Source State

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: Workbench Milestone 6 completed; RM35-07 maintained run
  bundles; existing `/api/runtime-demo`
- Target files:
  - `apps/web/src/api/client.ts`
  - `apps/web/src/main.tsx`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add a typed frontend client for `/api/runtime-demo`.
  - Add shared source-state handling for bootstrap pending, succeeded, failed,
    and selected-manifest outcomes.
  - Preserve canonical backend field names and structured API errors.
- Acceptance criteria:
  - The Workbench can create a backend-owned runtime demo workspace through a
    typed client.
  - Bootstrap success and failure states are explicit and do not require manual
    URL editing.
- Notes:
  - Added typed frontend request and response contracts for `/api/runtime-demo`
    and kept backend field names intact in the shared API client.
  - Added shared runtime-demo bootstrap draft and mutation state handling for
    pending, succeeded, failed, and source-hydration outcomes in the Workbench.
  - Successful bootstrap now commits backend-returned mission, workflow, and
    ledger paths into the existing runtime source state instead of requiring
    manual query construction.
  - Verification:
    `npm --workspace apps/web run build`

## Workstream 2: Guided Entry And Source Navigation

Goal: replace manual manifest-path bootstrapping with an operator-facing entry
flow that lands on the completed runtime surfaces.

### [x] WB7-02: Guided Runtime Entry Panel

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: WB7-01
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add an entry panel that can bootstrap a maintained runtime demo workspace
    or open an explicit artifact manifest path.
  - Let the operator provide bounded bootstrap inputs such as workspace,
    assignment ID, session ID, result ID, agent, and shell command when the
    backend contract supports them.
  - Route successful bootstrap responses into the existing runtime source state
    and visible runtime view.
- Acceptance criteria:
  - A first-time operator can reach a populated runtime inspection/action view
    without manually constructing query parameters.
  - Invalid bootstrap input and backend bootstrap failures remain explicit.
- Notes:
  - Added a `Runtime demo bootstrap` block inside the existing runtime-sources
    surface so operators can provide workspace, agent, assignment, session,
    result, and shell-command inputs without leaving the Workbench.
  - Routed bootstrap success directly into the completed runtime source view so
    the existing M4-M6 inspection and action panels load from backend-returned
    paths.
  - Kept bootstrap failures explicit through the runtime-source status surface
    and added smoke coverage for the no-query-editing entry path.
  - Verification:
    `npm --workspace apps/web run smoke -- --grep "Runtime M7|Runtime M6"`

### [x] WB7-03: Manifest And Run-Bundle Source Navigator

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB7-01, WB7-02
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add a source navigator that shows the active manifest or run-bundle root,
    the resolved artifact family, and the key derived paths the runtime view is
    using.
  - Surface whether the current source came from bootstrap, a direct manifest
    path, or a run bundle.
  - Allow bounded switching between the returned root and explicit related
    sources without retyping every field.
- Acceptance criteria:
  - An operator can tell what artifact root is active and how the runtime view
  was populated.
  - Source switching stays bounded to backend-returned paths instead of
    frontend path synthesis.
- Notes:
  - Added a `Runtime source navigator` block that shows the current root,
    artifact family, provenance, manifest root, and the direct runtime paths
    now driving the view.
  - Added bounded source switching between backend-returned bootstrap runtime
    paths, manifest runtime paths, manifest root, and dispatch run-bundle root
    without frontend path reconstruction.
  - Added smoke coverage for bootstrap provenance and run-bundle-to-manifest
    switching so navigation fails if the frontend stops following backend-owned
    roots.
  - Verification:
    `npm --workspace apps/web run build`
    `npm --workspace apps/web run smoke -- --grep "Runtime M7|Runtime M6"`

## Workstream 3: Artifact Readiness And UX Verification

Goal: make the runtime surface feel operationally trustworthy once a source is
loaded.

### [x] WB7-04: Artifact Readiness And Missing-Evidence Summary

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB7-02, WB7-03
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add a compact readiness summary for the currently loaded artifact set:
    manifest present, dispatch packet present, session/result/outcome present,
    review link present, timeline availability, and missing optional evidence.
  - Keep the summary backend-driven by reading already loaded manifest and API
    payloads rather than inferring runtime truth in the frontend.
  - Link the summary to the existing M4-M6 panels so an operator can jump from
    readiness diagnosis to detailed inspection or action.
- Acceptance criteria:
  - An operator can tell whether the current source is only inspectable or also
    actionable.
  - Missing evidence remains visible without breaking the surrounding runtime
    view.
- Notes:
  - Added an `Artifact readiness summary` block that reports actionability,
    manifest availability, dispatch/result/outcome/review evidence, and
    timeline state from already loaded backend artifacts and API payloads.
  - Kept missing evidence explicit for ordinary session bundles instead of
    hiding controls or inventing frontend defaults.
  - Verification:
    `npm --workspace apps/web run build`
    `npm --workspace apps/web run smoke -- --grep "Runtime M7|Runtime M6"`

### [x] WB7-05: Guided Bootstrap And Source-Navigation Smoke Coverage

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB7-02, WB7-03, WB7-04
- Target files:
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add smoke coverage for runtime-demo bootstrap, manifest-root loading,
    run-bundle source selection, and missing-evidence readiness states.
  - Reuse maintained M3.5/M4-shaped manifests and bundles instead of
    frontend-only synthetic navigation state.
- Acceptance criteria:
  - The Workbench proves it can move from guided bootstrap to the existing
    runtime surfaces end to end.
  - Coverage fails if the frontend falls back to ad hoc path reconstruction or
    hides missing-evidence states.
- Notes:
  - Runtime M7 smoke coverage now proves bootstrap hydration, run-bundle to
    manifest-root switching, and explicit inspect-only readiness states for
    missing evidence.
  - Existing Runtime M6 smoke coverage still runs alongside the new Runtime M7
    cases so operator actions remain stable while the guided entry surface
    grows.
  - Verification:
    `npm --workspace apps/web run smoke -- --grep "Runtime M7|Runtime M6"`
