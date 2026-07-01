# Workbench Milestone 3 Task List

Status: completed.

This is the completed Workbench Milestone 3 task list for BureauLess. It
followed the completed Workbench Milestone 2 runtime console milestone and
focused on making real runtime artifacts easier to open, trust, and operate.

The project-level sequencing lives in
[`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md).
Runtime contracts live in `../protocol/`; runtime implementation sequencing
lives in [`runtime_harness_tasklist.md`](runtime_harness_tasklist.md).

Milestone 3 is not about adding broad planning-DAG write capability. It is
about polishing the boundary between URL-provided runtime artifacts, persisted
runtime sources, and clearly scoped operator actions:

1. Make live-demo runtime artifacts load predictably from URL parameters.
2. Keep planning-DAG controls honest when no backend write contract exists.
3. Improve runtime-source feedback without moving runtime semantics into the
   frontend.

Within this document, `milestone` names the user-visible delivery target and
`workstream` names an internal implementation grouping inside that milestone.

## Principles

- Treat URL parameters, persisted local settings, and visible form state as one
  coherent runtime-source model.
- Keep Python runtime APIs authoritative for mission, workflow, ledger,
  gatekeeper, replay, and mutation state.
- Do not make disabled controls mysterious; explain unavailable actions in the
  UI or remove the action from that phase.
- Preserve planning-DAG editing behavior unless a task explicitly changes it.
- Land each feature with smoke coverage or explicit manual verification.

## Workstream 1: Runtime Source Loading

Goal: make runtime artifacts opened from links behave like first-class
workbench sessions.

### [x] WB3-01: Normalize Runtime Source URL Parameters

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: Workbench Milestone 2 runtime path controls
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Treat `mission_path`, `workflow_path`, and `ledger_path` URL parameters as
    authoritative initial runtime sources.
  - Ensure visible runtime-source inputs reflect URL-provided values on first
    render.
  - Keep persisted runtime-source values from overriding explicit URL values.
- Acceptance criteria:
  - Opening the workbench with explicit runtime-source query parameters shows
    those exact paths in the runtime source controls.
  - The runtime view remains the default when workflow or ledger paths are
    supplied.
  - Existing persisted browser settings still work when no runtime-source query
    parameters are supplied.
- Implementation notes:
  - Added a shared explicit-runtime-source query check for mission, workflow,
    and ledger URL parameters.
  - URL-provided runtime sources now win over stale persisted runtime-source
    values as a single initialization mode.
  - Added smoke coverage that preloads stale localStorage values before opening
    a runtime URL and verifies the visible controls plus API request paths.
  - Verified with `npm run web:build` and
    `npm --workspace apps/web run smoke -- --grep "runtime summary panels"`.

### [x] WB3-02: Auto-Load Explicit Runtime Sources

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: WB3-01
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Trigger the same runtime refresh path used by `Apply runtime sources` when
    explicit runtime-source query parameters are present.
  - Avoid duplicate refreshes when the user manually applies the same source
    values.
  - Preserve error reporting for missing or invalid artifacts.
- Acceptance criteria:
  - A live-demo workbench URL opens directly into the loaded runtime state
    without requiring a manual apply step.
  - Failed loads still show actionable error text.
  - Re-applying unchanged runtime sources does not create confusing UI churn.
- Implementation notes:
  - Existing runtime queries now receive the normalized URL-first source values
    at initialization, so explicit runtime URLs load mission, workflow, ledger,
    mutation, replay, and gatekeeper state without a manual apply step.
  - Added smoke coverage that asserts the runtime summary is loaded before any
    manual source apply and that `Apply runtime sources` is disabled while the
    visible source values match the committed runtime sources.
  - Verified with
    `npm --workspace apps/web run smoke -- --grep "runtime summary panels"`.

### [x] WB3-03: Runtime Source Status Feedback

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB3-02
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Show compact status for loaded, loading, unchanged, and failed runtime
    source states.
  - Keep the status close to the runtime source controls.
  - Avoid duplicating raw API error blocks already shown elsewhere.
- Acceptance criteria:
  - Operators can tell whether URL-provided artifacts have loaded.
  - Status text does not overlap or crowd the runtime toolbar on narrow
    viewports.
- Implementation notes:
  - Added compact runtime-source status next to the apply action for loaded,
    loading, pending, and error states.
  - Added smoke assertions for loaded URL state and pending edits.
  - Verified with `npm run web:build` and
    `npm --workspace apps/web run smoke -- --grep "runtime summary panels"`.

## Workstream 2: Planning Action Honesty

Goal: remove ambiguity around planning-DAG actions whose backend contract is
not yet real.

### [x] WB3-04: Clarify Planning Apply Availability

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: Workbench Milestone 1 planning-DAG behavior
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Audit what the planning `Apply` button currently means.
  - If it is only valid for local metadata edits, label or scope it precisely.
  - If no current backend write contract exists, disable it with visible
    reason text or remove it from the unavailable state.
- Acceptance criteria:
  - Users no longer interpret disabled planning `Apply` as a broken runtime
    feature.
  - Existing valid planning edits, if any, remain usable.
  - Smoke coverage verifies the visible disabled reason or scoped action.
- Implementation notes:
  - Renamed the planning workspace path action from `Apply` to
    `Apply workspace paths` to clarify that it only applies the DAG path and
    runs directory.
  - Updated the existing smoke test for custom DAG and runs paths.
  - Verified with `npm run web:build` and
    `npm --workspace apps/web run smoke -- --grep "applies custom DAG"`.

### [x] WB3-05: Separate Planning And Runtime Action Copy

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB3-04
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Review button labels and empty states that use ambiguous terms like
    "apply" across planning and runtime surfaces.
  - Keep runtime-source actions named as source loading actions.
  - Keep planning actions named after the exact planning artifact they affect.
- Acceptance criteria:
  - Planning and runtime controls can be distinguished by label without reading
    implementation details.
  - No runtime action appears inside the planning-only surface.
- Implementation notes:
  - Planning source changes now use `Apply workspace paths`.
  - Runtime source changes continue to use `Apply runtime sources`.
  - Verified there are no remaining bare `Apply` button labels in the web
    client or smoke tests.

## Workstream 3: Verification And Documentation

Goal: keep the milestone small, testable, and easy to resume.

### [x] WB3-06: Smoke Coverage For Live-Demo URL Loading

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB3-01, WB3-02
- Target files:
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add or update a smoke test that opens a URL with runtime-source query
    parameters.
  - Assert that the runtime view loads the expected mission, workflow, and
    ledger state.
  - Keep the fixture small and deterministic.
- Acceptance criteria:
  - `npm run web:smoke` covers URL-provided runtime source loading.
  - The test fails if URL-provided paths are ignored in favor of persisted
    values.
- Implementation notes:
  - Expanded the runtime source smoke test to seed stale localStorage values,
    open a URL with explicit workflow and ledger paths, and verify derived
    mission path, visible controls, API request paths, loaded summaries, and
    unchanged apply state.
  - Verified with
    `npm --workspace apps/web run smoke -- --grep "runtime summary panels"`.

### [x] WB3-07: Document Workbench Milestone 3 Completion

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB3-01 through WB3-06
- Target files:
  - `docs/tasks/workbench_milestone_3_tasklist.md`
  - `docs/roadmap/development_roadmap.md`
- Work:
  - Mark completed WB3 tasks with short implementation notes.
  - Update the roadmap once runtime-source loading and planning-action clarity
    are verified.
- Acceptance criteria:
  - The docs state what was verified and which tests were run.
  - The next priority after WB3 is explicit.
- Implementation notes:
  - Marked WB3-01 through WB3-06 complete with implementation notes.
  - Updated the roadmap priority order after clearing the WB3 verification
    follow-up.
  - Verified the WB3 scope with `npm run web:build`,
    `npm --workspace apps/web run smoke -- --grep "runtime summary panels"`,
    and `npm --workspace apps/web run smoke -- --grep "applies custom DAG"`.
  - Fixed the planning graph drag smoke failures by waiting for the React Flow
    node box to stabilize before drag interactions and reset comparisons.
  - Verified the full workbench suite with `npm run web:smoke` (`27 passed`).

## Recommended Execution Order

1. WB3-01 Normalize Runtime Source URL Parameters
2. WB3-02 Auto-Load Explicit Runtime Sources
3. WB3-06 Smoke Coverage For Live-Demo URL Loading
4. WB3-03 Runtime Source Status Feedback
5. WB3-04 Clarify Planning Apply Availability
6. WB3-05 Separate Planning And Runtime Action Copy
7. WB3-07 Document Workbench Milestone 3 Completion

## Milestone 3 Acceptance

- Runtime-source query parameters open directly into a trustworthy runtime
  console state.
- Explicit URL values, persisted values, and visible input state do not fight
  each other.
- Planning actions no longer imply backend write capabilities that do not
  exist.
- The milestone is covered by smoke tests or clear manual verification notes.

## Verification Follow-Up

- Cleared. The planning graph drag tests now wait for React Flow layout and
  viewport settling before dragging nodes or connections.
- `npm run web:smoke` now passes (`27 passed`).
