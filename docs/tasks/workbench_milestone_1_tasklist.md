# Workbench Milestone 1 Task List

This is the UI/workbench task list for BureauLess Workbench Milestone 1, not
the full project roadmap. The
project-level split between harness/runtime work and workbench/UI work lives in
`../roadmap/development_roadmap.md`.

This task list records the current workbench milestone set. The current UI is
primarily a DAG viewer and node inspector. The next goal is to turn it into a
small, safe operations console before adding DAG editing.

Within this document, `milestone` names the user-visible delivery target and
`workstream` names an internal implementation grouping inside that milestone.

See also:

- [`workbench_tasklist.md`](workbench_tasklist.md) for the workbench task-list
  index.

## Principles

- Keep YAML as the only persisted data format.
- Keep DAG business rules in Python, not duplicated in the frontend.
- Add write operations gradually, starting with run records before DAG edits.
- Prefer explicit validation and review gates over hidden auto-fixes.
- Preserve one UI implementation for browser and Electron.
- Recommended models should use current native Codex model names and reflect
  total execution cost, not raw token count alone. Context refill, subagent
  startup, and per-token price all matter.
- Mark a task `completed` only after its acceptance criteria have frontend/API
  coverage or explicit manual verification. Use `started` for partial
  implementation and `pending` for untouched tasks.

## Workstream 1: Review Operations

Goal: make the first safe write path usable from the workbench.

### [x] WB-01: Review Status Actions

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: existing `/api/review`
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/api/client.ts`
  - `apps/web/src/styles.css`
- Work:
  - Add `approve`, `reject`, and `mark pending` actions in the node inspector.
  - Only show actions when the selected node has at least one passed run record.
  - Use `orchestrator_approved` for `orchestrator_review` nodes.
  - Use `human_approved` for `human_review` nodes.
  - Use `approved` for `auto_pass` only if manual override is needed.
  - Refresh runs and state after a successful update.
- Acceptance criteria:
  - Selecting a node with a pending review shows relevant action buttons.
  - Clicking approve updates the YAML run record through the API.
  - The node state changes from `needs_review` to `completed`.
  - Rejected nodes remain visible as review-needed.
- Tests:
  - Add frontend smoke coverage for approve/reject visibility.
  - Add API test for review status update if not already sufficient.

### [x] WB-02: Run Record Selection

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB-01
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/api/client.ts`
- Work:
  - Add a per-node run list in the inspector.
  - Show latest run by default.
  - Allow selecting an older run to inspect its details.
  - Pass selected `run_id` when review actions are used.
- Acceptance criteria:
  - Multiple runs for the same task are visible.
  - Review actions can target a specific run.
  - Timeline and inspector agree on the selected run.
- Tests:
  - Add API fixture with two run records for one task.
  - Add frontend test for selecting a run row.

### [x] WB-03: Review Error Handling

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB-01
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
- Work:
  - Show inline errors when review update fails.
  - Keep the previous UI state if the API request fails.
  - Add a retry affordance.
- Acceptance criteria:
  - Failed review requests are visible to the user.
  - The UI does not pretend the node changed state after failure.
- Tests:
  - Mock a failed review request in frontend test or add a small API error test.

## Workstream 2: Validation And Diagnostics

Goal: make YAML and DAG problems obvious before editing is introduced.

### [x] WB-04: Validation Endpoint

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: current `load_dag()` validation
- Target files:
  - `src/bureauless/api/server.py`
  - `tests/test_server.py`
- Work:
  - Add `GET /api/validate?path=...`.
  - Return `{ ok: true, errors: [] }` for valid DAGs.
  - Return structured errors for invalid YAML, missing fields, unknown
    dependencies, duplicate nodes, and cycles.
  - Do not expose tracebacks to the frontend.
- Acceptance criteria:
  - Valid DAG returns `ok: true`.
  - Invalid DAG returns `ok: false` and readable errors.
  - API response shape is stable enough for the frontend to render.
- Tests:
  - Valid DAG test.
  - Missing required field test.
  - Unknown dependency test.
  - Cycle test.

### [x] WB-05: Diagnostics Panel

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB-04
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/api/client.ts`
  - `apps/web/src/styles.css`
- Work:
  - Add a diagnostics panel or toolbar indicator.
  - Show validation errors with concise messages.
  - Keep the graph visible when possible.
  - Show a full-page error only when the DAG cannot be loaded at all.
- Acceptance criteria:
  - Users can distinguish API failure from DAG validation failure.
  - Errors identify the failing node or field when available.
- Tests:
  - Frontend smoke test for a valid diagnostics state.
  - Optional test with a temporary invalid DAG served by the API.

### [x] WB-06: Empty And Missing Data States

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: none
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
- Work:
  - Add specific empty states for no run records, no ready nodes, and no selected
    node.
  - Avoid generic loading text after the API has returned.
- Acceptance criteria:
  - Empty `runs/` directory is presented as normal, not an error.
  - Missing DAG file is presented as a clear load failure.
- Tests:
  - Existing smoke test still passes with no run records.

## Workstream 3: Low-Risk Metadata Editing

Goal: allow editing node metadata without changing DAG structure.

### [x] WB-07: DAG Save API For Node Metadata

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: high
- Dependencies: WB-04
- Target files:
  - `src/bureauless/core.py`
  - `src/bureauless/api/server.py`
  - `tests/test_core.py`
  - `tests/test_server.py`
- Work:
  - Add a safe YAML write path for node metadata.
  - Preserve node order.
  - Preserve YAML-only format.
  - Validate after write and reject invalid updates.
  - Create a backup before writing, such as `.bak` or timestamped copy.
  - Initially allow only:
    - `recommended_model`
    - `risk_level`
    - `review_gate`
    - `failure_policy`
    - `tags`
- Acceptance criteria:
  - Valid metadata updates are persisted.
  - Invalid values are rejected before writing.
  - Existing dependencies and prompt templates are unchanged.
- Tests:
  - Update one field.
  - Reject invalid enum value.
  - Preserve unrelated fields.
  - Validate written file can be reloaded.

### [x] WB-08: Metadata Edit Form

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB-07
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/api/client.ts`
  - `apps/web/src/styles.css`
- Work:
  - Add an edit mode in the inspector.
  - Use selects for enum fields.
  - Use a token input or simple text input for tags.
  - Show save/cancel controls.
  - Refresh DAG and state after save.
- Acceptance criteria:
  - Users can update low-risk metadata from the UI.
  - Save button is disabled while request is in flight.
  - Cancel restores the previous values.
- Tests:
  - Frontend test edits `risk_level` and observes updated badge.

### [x] WB-09: Unsaved Changes Guard

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB-08
- Target files:
  - `apps/web/src/main.tsx`
- Work:
  - Track dirty state in the inspector edit form.
  - Warn before switching nodes with unsaved changes.
  - Keep this local to the inspector; do not add global app state yet.
- Acceptance criteria:
  - Accidental node switch does not silently discard edits.
  - Explicit cancel discards edits.
- Tests:
  - Component-level test if a frontend test harness exists.
  - Manual verification is acceptable for the first pass.

## Workstream 4: File Selection And Workspace Ergonomics

Goal: make the workbench useful beyond the default example file.

### [x] WB-10: Browser Path Controls

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: none
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/api/client.ts`
- Work:
  - Add text inputs for `dag_path` and `runs_dir`.
  - Persist values in `localStorage`.
  - Use those values in all API calls.
- Acceptance criteria:
  - Users can point the browser workbench at another YAML DAG.
  - Refresh keeps the selected paths.
- Tests:
  - Smoke test still passes with default paths.

### [x] WB-11: Electron File Picker Integration

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB-10
- Target files:
  - `apps/desktop/src/main.ts`
  - `apps/desktop/src/preload.cts`
  - `apps/web/src/main.tsx`
- Work:
  - Wire existing `openDag` and `openRunsDir` preload methods into the UI.
  - Hide file picker buttons when running in plain browser mode.
  - Keep manual text inputs available in both modes.
- Acceptance criteria:
  - Electron users can choose a DAG file through native file picker.
  - Browser users still have path inputs.
- Tests:
  - Electron smoke can be manual for now.
  - Manual verification completed on June 24, 2026: both picker buttons appeared in the Electron shell and successfully opened Dolphin for file and folder selection.

## Workstream 5: Structure Editing

Goal: edit graph structure only after validation and metadata editing are stable.

### [x] WB-12: Add Node Workflow

- Status: completed
- Priority: low
- Recommended model: gpt-5.4
- Risk: high
- Dependencies: WB-04, WB-07, WB-08
- Work:
  - Add a form to create a complete node with required fields.
  - Validate before write.
  - Insert at end of YAML node list.
- Acceptance criteria:
  - New node appears in the graph after save.
  - Missing required fields are rejected.

### [x] WB-13: Dependency Editing

- Status: completed
- Priority: low
- Recommended model: gpt-5.4
- Risk: high
- Dependencies: WB-12
- Work:
  - Allow editing dependencies through a controlled multi-select first.
  - Do not start with drag-to-connect writes.
  - Reject cycles and unknown dependencies.
- Acceptance criteria:
  - Dependency changes update graph edges after save.
  - Cycles are rejected with clear diagnostics.

### [x] WB-14: Drag-To-Connect Dependencies

- Status: completed
- Priority: low
- Recommended model: gpt-5.5
- Risk: high
- Dependencies: WB-13
- Work:
  - Add graph edge creation/removal gestures.
  - Route all changes through the same validated dependency API.
  - Provide undo for the latest unsaved graph edit.
  - Keep the canvas usable as the graph grows: persist manual node placement,
    support resetting back to automatic layout, and prefer left-to-right
    dependency flow with horizontal handles.
- Acceptance criteria:
  - Dragging an edge does not write until explicitly saved.
  - Invalid edges are rejected before persistence.
  - Orphan/root nodes remain visible after edge edits.
  - Manual graph layout survives refresh and can be reset in one action.

## Workstream 6: Dispatch Preparation

Goal: prepare the UI for future agent execution without implementing model
dispatch yet.

### [x] WB-15: Assignment Matrix View

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB-10
- Work:
  - Add a table view of nodes by `recommended_model`, `risk_level`, and state.
  - Highlight ready nodes that can run in parallel.
- Acceptance criteria:
  - Users can see which nodes are ready for lower-cost model execution.
  - High-risk nodes are visually separated.

### [x] WB-16: Prompt Export Panel

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: current prompt API
- Work:
  - Add a copy button for rendered prompt.
  - Add a batch prompt preview for all ready nodes.
  - Do not dispatch to models yet.
- Acceptance criteria:
  - Users can copy a single node prompt.
  - Users can inspect prompts for all ready nodes.

## Recommended Execution Order

1. WB-01 Review Status Actions
2. WB-02 Run Record Selection
3. WB-03 Review Error Handling
4. WB-04 Validation Endpoint
5. WB-05 Diagnostics Panel
6. WB-06 Empty And Missing Data States
7. WB-10 Browser Path Controls
8. WB-11 Electron File Picker Integration
9. WB-07 DAG Save API For Node Metadata
10. WB-08 Metadata Edit Form
11. WB-09 Unsaved Changes Guard
12. WB-15 Assignment Matrix View
13. WB-16 Prompt Export Panel
14. WB-12 Add Node Workflow
15. WB-13 Dependency Editing
16. WB-14 Drag-To-Connect Dependencies

## Capability Bundles

### Bundle A: Operational Viewer

- Includes WB-01 through WB-06.
- The workbench can inspect, review, diagnose, and recover from common loading
  problems.
- No DAG writes yet.

### Bundle B: Practical Local Workbench

- Includes WB-10 and WB-11.
- Users can point the app at real DAG and runs directories.
- Browser and Electron remain aligned.

### Bundle C: Safe Metadata Editing

- Includes WB-07 through WB-09.
- Users can edit low-risk node metadata with validation and backup.

### Bundle D: Dispatch Readiness

- Includes WB-15 and WB-16.
- Users can see ready work and export prompts for external agent execution.

### Bundle E: Graph Editing

- Includes WB-12 through WB-14.
- Users can edit DAG structure, but only after validation and save semantics are
  mature.
