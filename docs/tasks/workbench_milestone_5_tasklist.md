# Workbench Milestone 5 Task List

Status: completed. WB5-01 through WB5-05 are complete. This milestone follows the completed Runtime Harness Milestone
4 history APIs and the completed Workbench Milestone 4 artifact-inspection
baseline.

This is the planned UI/workbench delivery milestone for BureauLess. It adds
read-only temporal inspection for the Runtime M4 history surface without moving
replay, version projection, or mutation authority into the frontend.

The project-level sequencing lives in
[`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md). The
backend API and protocol scope comes from
[`runtime_harness_milestone_4_tasklist.md`](runtime_harness_milestone_4_tasklist.md),
especially RM4-09 through RM4-11.

Milestone 5 is an inspection milestone. It does not add frontend-owned replay,
branching, rollback, or mutation application. The Python runtime APIs remain
authoritative for timeline, snapshot, diff, and historical explanation data.

## Goals

1. Make Runtime M4 timeline, version, historical snapshot, and diff APIs
   visible in the Workbench.
2. Let an operator answer "what changed, when, and why was this node in that
   state?" without reading YAML or reimplementing replay rules in TypeScript.
3. Keep mutation decisions and historical interpretation runtime-owned while
   preserving the Workbench's read-only inspection posture.

## Principles

- Read history exclusively through `/api/replay/timeline`,
  `/api/replay/snapshot`, and `/api/replay/diff`.
- Treat workflow version IDs, mutation states, assignment validity, and node
  explanations as canonical API data, not frontend-derived facts.
- Keep timeline selection, compare cursors, and panel state separate from
  runtime truth.
- Make unknown cursors, unsupported rollback requests, and unavailable
  historical artifacts explicit UI states.
- Preserve the existing separation between planning-DAG editing and runtime
  workflow inspection.
- Land each feature with focused smoke or component coverage.
- Recommended models should use current native Codex model names and reflect
  task complexity rather than a milestone-wide default.

## Workstream 1: Runtime M4 History Sources

Goal: establish one typed, testable frontend boundary for the Runtime M4
history surface.

### [x] WB5-01: Timeline, Snapshot, And Diff API Client

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: RM4-09, RM4-11, Workbench Milestone 4 runtime-source model
- Target files:
  - `apps/web/src/api/client.ts`
  - `apps/web/src/main.tsx`
- Work:
  - Add typed frontend clients for `/api/replay/timeline`,
    `/api/replay/snapshot`, and `/api/replay/diff`.
  - Extend runtime source state with optional timeline cursor and compare-cursor
    inputs while preserving existing explicit mission/workflow/ledger paths.
  - Preserve canonical API field names, nullable states, and structured error
    codes.
- Acceptance criteria:
  - The frontend can load the full Runtime M4 history surface without parsing
    YAML or reconstructing replay semantics.
  - Unsupported cursor combinations remain explicit UI errors rather than
    implicit fallback behavior.
- Notes:
  - Added typed frontend contracts for the completed Runtime M4 history APIs:
    replay timeline, cursor-selected snapshot, and two-cursor diff.
  - Extended runtime source state, URL/local persistence, and source inputs
    with snapshot and compare-cursor selectors while keeping mission/workflow/
    ledger paths authoritative.
  - Wired the Workbench runtime source model to actually query the new history
    APIs so later timeline and diff panels can consume already-loaded state.
  - Verification:
    `npm --workspace apps/web run build`

### [x] WB5-02: Timeline And Version Selector

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: WB5-01
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add a read-only timeline view that shows event ordinal, event ID, event
    type, active workflow version, and version-transition metadata.
  - Allow selecting a single cursor for historical snapshot inspection and
    expose the active workflow version at that cursor.
  - Distinguish accepted version transitions from non-transition events.
- Acceptance criteria:
  - An operator can move through linear accepted history without reloading or
    editing canonical files.
  - Version transitions are visible without the frontend deriving them.
- Notes:
  - Added a dedicated timeline-and-version panel to the runtime workflow view
    so operators can browse accepted workflow versions and ledger events from
    the Runtime M4 history APIs.
  - Wired timeline event and version-card selection into the snapshot cursor
    source state without moving replay or version-projection logic into the
    frontend.
  - Exposed current-versus-historical selection state and version-transition
    metadata directly from the API payload, with responsive layout support for
    narrower workbench widths.
  - Verification:
    `npm --workspace apps/web run build`

## Workstream 2: Historical Explanation

Goal: make node and assignment history intelligible at a selected cursor.

### [x] WB5-03: Historical Node And Assignment Inspector

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: WB5-01, WB5-02
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Show the selected historical workflow shape, node runtime state, blocked
    reasons, assignment attempts, and assignment-validity state from the
    snapshot API.
  - Make superseded, rejected, stale, and retry-related states visually
    distinct.
  - Keep historical explanation runtime-authored; do not compute node state
    transitions in the frontend.
- Acceptance criteria:
  - An operator can explain why a node was runnable, blocked, completed, or
    superseded at a selected event cursor.
  - Historical explanation remains aligned with the runtime snapshot payload.
- Notes:
  - Added a dedicated historical snapshot inspector that reads selected-cursor
    workflow shape, node runtime state, gatekeeper state, blocked reasons,
    assignment attempts, and assignment-validity evidence directly from the
    Runtime M4 snapshot APIs.
  - Kept history explanation runtime-authored by consuming snapshot and
    gatekeeper payloads instead of deriving historical transitions in the
    frontend.
  - Made removed-versus-present historical node states explicit so operators
    can tell when a selected node does not exist in the active workflow
    version at a cursor.
  - Verification:
    `npm --workspace apps/web run build`

## Workstream 3: Temporal Comparison

Goal: show what changed between two valid cursors without adding counterfactual
history.

### [x] WB5-04: Workflow And State Diff Inspector

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB5-01, WB5-02
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add compare-cursor controls backed by `/api/replay/diff`.
  - Show workflow node/gate additions and removals, mutation state changes, and
    node/assignment validity deltas between two valid cursors.
  - Keep rollback, branch comparison, and unsupported compare directions as
    explicit API-driven error states.
- Acceptance criteria:
  - An operator can see what changed between two valid points in linear history
    without the frontend replaying rules itself.
  - Unsupported compare requests remain explicit and read-only.
- Notes:
  - Added a temporal diff inspector backed by `/api/replay/diff` so operators
    can inspect event traversal, workflow structure changes, node-state deltas,
    assignment-validity changes, and mutation-state changes between two valid
    cursors.
  - Kept compare behavior API-driven by surfacing unsupported rollback or
    invalid compare requests as explicit UI error states instead of adding
    frontend fallback semantics.
  - Verification:
    `npm --workspace apps/web run build`

### [x] WB5-05: Runtime M4 History Smoke Coverage

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB5-02, WB5-03, WB5-04
- Target files:
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add smoke coverage for timeline selection, historical snapshot rendering,
    diff inspection, and structured unsupported-cursor error states.
  - Reuse the maintained Runtime M4 history fixture rather than frontend-only
    synthetic data.
- Acceptance criteria:
  - The maintained Runtime M4 history path remains inspectable end to end.
  - Frontend coverage proves that the Workbench consumes API contracts rather
    than replaying rules locally.
- Notes:
  - Added focused smoke coverage for timeline/version rendering, historical
    snapshot explanation, temporal diff inspection, and explicit unsupported
    cursor errors.
  - Reused maintained Runtime M4-shaped fixtures for timeline, snapshot, and
    diff payloads instead of frontend-only derived history.
  - Verification:
    `npm --workspace apps/web run smoke -- --grep "Runtime M4"`
