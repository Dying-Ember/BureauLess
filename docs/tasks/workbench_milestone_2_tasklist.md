# Workbench Milestone 2 Task List

Status: completed.

This is the completed Workbench Milestone 2 task list for BureauLess. It built
on the completed Workbench Milestone 1 viewer/editor surface and turned
the workbench into a runtime console for the harness line.

The project-level sequencing lives in
[`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md).
Runtime contracts live in `../protocol/`; runtime task sequencing lives in
[`runtime_harness_milestone_3_tasklist.md`](runtime_harness_milestone_3_tasklist.md).

Milestone 2 is not about adding more planning-DAG editing. It is about making
runtime state visible and trustworthy:

1. Show the runtime workflow as its own thing.
2. Make mutation, replay, and gatekeeper state legible on screen.
3. Keep Python runtime authoritative while the UI becomes a better operator
   surface.

Within this document, `milestone` names the user-visible delivery target and
`workstream` names an internal implementation grouping inside that milestone.

## Principles

- Treat the planning DAG and runtime workflow as related but distinct surfaces.
- Reflect runtime truth from APIs; do not re-derive workflow semantics in the
  frontend.
- Favor inspection and explanation before adding new write capabilities.
- Keep browser and Electron aligned on one implementation.
- Land each runtime-console feature with smoke coverage or explicit manual
  verification.

## Workstream 1: Runtime Workflow Surface

Goal: give the runtime workflow a first-class visual home.

### [x] WB2-01: Planning DAG / Runtime Workflow View Split

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: existing mutation inspection API
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add a clear view switch or tab split between planning DAG and runtime
    workflow.
  - Preserve current DAG editing behavior in the planning view.
  - Make the runtime view default automatically when a workflow/ledger pair is
    explicitly supplied.
- Acceptance criteria:
  - Users can tell which graph they are looking at without inference.
  - Mutation tests no longer rely on side-panel text to understand state.
- Implementation notes:
  - Added a persistent planning/runtime view toggle to the toolbar.
  - Runtime mode becomes the default when `workflow_path` or `ledger_path` is
    explicitly supplied.
  - Planning DAG editing remains isolated to the planning view, while runtime
    mode exposes workflow source context and runtime summaries.
  - Verified with `npm run web:build` and `npm run web:smoke` (`19 passed`).

### [x] WB2-02: Runtime Graph Rendering

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: high
- Dependencies: WB2-01
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Render runtime workflow nodes and edges from mission/workflow/ledger APIs.
  - Show accepted mutation changes in the runtime graph.
  - Keep layout readable for small DAG-style mission graphs.
- Acceptance criteria:
  - Accepted mutations visibly change the runtime canvas.
  - Rejected mutations leave the runtime canvas unchanged.
- Implementation notes:
  - Expanded the runtime workflow types in the web client to match the backend
    `workflow_payload()` shape returned by `/api/mutations`.
  - Replaced the runtime summary-only surface with a read-only runtime
    React Flow canvas derived from `current_workflow`.
  - Added smoke coverage proving that accepted mutations add the new runtime
    node while rejected mutations leave the canvas unchanged.
  - Verified with `npm run web:build` and `npm run web:smoke` (`20 passed`).

### [x] WB2-03: Runtime Node List And Selection

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB2-02
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add a runtime node list aligned with the runtime graph.
  - Support selecting runtime nodes independently of planning-DAG nodes.
  - Expose node role, current state, and latest assignment attempt summary.
- Acceptance criteria:
  - The runtime list and runtime graph stay in sync after mutation decisions.
  - Selecting a runtime node drives the runtime inspector.
- Implementation notes:
  - Added runtime-selected node state independent from the planning-DAG
    selection state.
  - Runtime graph clicks and runtime node list clicks now target the same
    runtime inspector surface.
  - Runtime list entries expose node role and a compact current-state summary,
    and the selection survives switching between planning and runtime views.
  - During verification, fixed a real hook-order regression on the missing-DAG
    error path before rerunning the full suite.
  - Verified with `npm run web:build` and `npm run web:smoke` (`21 passed`).

## Workstream 2: Gatekeeper And Replay Inspection

Goal: make blocked/runnable/completed state explainable from the UI.

### [x] WB2-04: Gatekeeper Overlay

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: existing `/api/gatekeeper`
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/api/client.ts`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Overlay gatekeeper state on runtime nodes.
  - Distinguish `runnable`, `blocked`, `completed`, `needs_review`, and
    `superseded` clearly.
  - Keep blocked-reason tooltips or detail panels concise and inspectable.
- Acceptance criteria:
  - A user can see why a node is blocked without opening raw YAML.
  - Superseded and mutation-pending states are visually distinct.
- Implementation notes:
  - Added `/api/gatekeeper` client types and fetch helpers to keep runtime
    gatekeeper data authoritative from the Python API.
  - Overlaid gatekeeper state on runtime graph nodes, runtime node chips, and
    the runtime inspector using explicit `runnable`, `blocked`, `completed`,
    `needs_review`, and `superseded` treatments.
  - Added concise blocked-reason cards with mutation, gate, assignment, and
    missing-ref metadata so operators can see why a node is blocked without
    opening the ledger.
  - Added runtime summary counts for runnable, blocked, review, completed, and
    superseded nodes.
  - Verified with `npm run web:build` and `npm run web:smoke` (`22 passed`).

### [x] WB2-05: Replay Inspector

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: high
- Dependencies: WB2-04
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/api/client.ts`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add a replay-oriented inspector that shows emitted events, assignment
    attempts, blocked reasons, and supersession links.
  - Keep this separate from the planning-DAG metadata editor.
- Acceptance criteria:
  - Users can inspect why runtime state is what it is.
  - Assignment supersession is visible without reading the ledger directly.
  - Verified with `npm run web:build` and `npm run web:smoke` (`26 passed`).

## Workstream 3: Mutation Operations Console

Goal: turn the current mutation side panel into a genuine runtime operator
surface.

### [x] WB2-06: Mutation Decision Synchronization

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB2-02, WB2-03
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Refresh runtime graph, runtime node list, and ready-state surfaces after
    mutation accept/reject.
  - Keep decision latency and error states explicit.
  - Avoid ad hoc frontend-only mutation state.
- Acceptance criteria:
  - Clicking `Accept` changes the runtime canvas and related runtime lists.
  - Clicking `Reject` updates decision state while leaving runtime structure
    unchanged.
- Implementation notes:
  - Kept mutation decisions authoritative through the query response and only
    refreshed gatekeeper afterward, so the runtime surfaces do not regress to
    stale proposal data.
  - Added a lightweight sync status message while decision and gatekeeper
    refresh are in flight.
  - Surfaced decision errors explicitly in the mutation panel and kept the
    runtime canvas unchanged on failure.
  - Extended smoke coverage for sync state, failure state, and the accept /
    reject lifecycle.
  - Verified with `npm run web:build` and `npm run web:smoke` (`24 passed`).

### [x] WB2-07: Mutation Impact Drilldown

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB2-06
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Expand mutation cards into affected nodes, affected assignments, and
    superseded assignment evidence.
  - Link impact drilldown back to selected runtime nodes when possible.
- Acceptance criteria:
  - Users can move from a mutation card to the impacted runtime state directly.
  - Mutation reasoning is visible without overwhelming the main graph.
  - Verified with `npm run web:build` and `npm run web:smoke` (`26 passed`).

## Workstream 4: Runtime Resource Views

Goal: expose the rest of the runtime surfaces the harness already computes.

### [x] WB2-08: Mission And Ledger Summary Panels

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: existing mission/ledger APIs
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/api/client.ts`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add mission summary, artifact count, risk count, and decision count panels.
  - Keep them compact and operational rather than turning the app into a YAML
    browser.
- Acceptance criteria:
  - Operators can orient themselves without opening protocol files.
  - Panels stay accurate when runtime state changes.

### [x] WB2-09: Runtime Path Controls

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB2-01
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add first-class inputs or pickers for workflow and ledger paths, not only
    DAG and runs paths.
  - Persist them with the same ergonomics as the current DAG/runs controls.
- Acceptance criteria:
  - Users can change runtime sources from the UI instead of editing the URL.
  - Browser and Electron remain aligned on this capability.

## Recommended Execution Order

1. WB2-01 Planning DAG / Runtime Workflow View Split
2. WB2-02 Runtime Graph Rendering
3. WB2-03 Runtime Node List And Selection
4. WB2-04 Gatekeeper Overlay
5. WB2-06 Mutation Decision Synchronization
6. WB2-07 Mutation Impact Drilldown
7. WB2-05 Replay Inspector
8. WB2-08 Mission And Ledger Summary Panels
9. WB2-09 Runtime Path Controls

## Milestone 2 Acceptance

- The workbench can show planning and runtime graphs as distinct surfaces.
- Accepted and rejected mutations visibly affect the runtime console in the
  right way.
- Gatekeeper and replay state are inspectable without reading raw YAML.
- Runtime APIs remain the source of truth; the frontend does not invent its
  own workflow semantics.
