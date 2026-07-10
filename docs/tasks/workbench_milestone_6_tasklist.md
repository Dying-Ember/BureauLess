# Workbench Milestone 6 Task List

Status: completed. WB6-01 through WB6-06 are complete. This milestone follows
the completed Workbench Milestone 5 Runtime M4 temporal inspection surface and
is now the delivered Line B milestone for BureauLess.

This is the delivered UI/workbench milestone for BureauLess. It turns selected
validated runtime APIs into operator-facing actions without moving dispatch,
acceptance, or protocol semantics into the frontend.

The project-level sequencing lives in
[`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md). The
backend action and validation scope comes primarily from
[`runtime_harness_milestone_3_5_tasklist.md`](runtime_harness_milestone_3_5_tasklist.md),
especially RM35-01 through RM35-05, with runtime-history context from
[`runtime_harness_milestone_4_tasklist.md`](runtime_harness_milestone_4_tasklist.md).

Milestone 6 is an operator-actions milestone. It does not move canonical
ledger mutation rules, dispatch validation, replay interpretation, or workflow
editing authority into TypeScript. The Python runtime remains authoritative for
every write-capable action and every post-action replay/gatekeeper refresh.

## Goals

1. Make validated runtime actions usable from the Workbench instead of leaving
   them CLI- or raw-API-only.
2. Let an operator move from inspection to bounded action for dispatch,
   context-resolution, result staging, review import, and outcome decision.
3. Preserve the current rule that the frontend proposes operator intent while
   the backend validates, mutates, and returns authoritative runtime state.

## Principles

- Reuse existing backend action APIs before inventing frontend-only workflow.
- Treat compiled packets, staged results, review decisions, and outcome
  decisions as backend-owned artifacts and mutations.
- Require explicit paths, actor choices, and policy fields where the backend
  requires them; do not silently infer missing write inputs.
- Refresh runtime state from canonical API responses after every accepted
  action.
- Make dry-run, unavailable, invalid, and rejected action states explicit UI
  outcomes.
- Keep planning-DAG editing separate from runtime operator controls.
- Land each feature with focused smoke coverage that proves the UI uses the
  backend contracts rather than bypassing them.
- Recommended models should use current native Codex model names and reflect
  task complexity instead of a milestone-wide default.

## Workstream 1: Runtime Action Clients And Shared State

Goal: establish one typed frontend boundary for validated runtime write APIs and
their action-state UX.

### [x] WB6-01: Runtime Action API Client And Action State Model

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: Workbench Milestone 5 completed runtime-source and history
  model; RM35-01, RM35-02, RM35-03
- Target files:
  - `apps/web/src/api/client.ts`
  - `apps/web/src/main.tsx`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add typed frontend clients for `/api/context-request/resolve`,
    `/api/dispatch-packet/compile`, `/api/session/dispatch`,
    `/api/result/stage`, `/api/review-decision/import`, and
    `/api/outcome/decide`.
  - Add shared action-state handling for pending, succeeded, failed, and
    post-action refresh outcomes.
  - Preserve canonical backend field names and structured API errors.
- Acceptance criteria:
  - The Workbench can invoke every Milestone 6 action through typed clients.
  - Runtime action success and failure states are explicit and do not require
    page reloads.
- Notes:
  - Added typed frontend clients for Runtime M6 action APIs: context request
    resolution, dispatch packet compile, session dispatch, result staging,
    review-decision import, and outcome decision.
  - Added shared runtime-operator action mutations with centralized post-action
    replay/gatekeeper refresh for acceptance-path writes.
  - Exposed a lightweight operator-action status surface in the runtime view so
    the shared action layer has explicit idle, pending, success, and error
    states before the dedicated action panels land.
  - Verification:
    `npm --workspace apps/web run build`

## Workstream 2: Launch And Context Operator Controls

Goal: expose the validated handoff and continuation controls already supported
by the runtime.

### [x] WB6-02: Context Request Resolution Panel

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: WB6-01; RM35-03
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add an operator panel for manifest-backed or path-provided context requests
    that can call `/api/context-request/resolve`.
  - Show resolved artifacts, denied or unavailable refs, and bounded artifact
    limits from the backend response.
  - Keep context resolution visibly separate from ledger mutation and replay.
- Acceptance criteria:
  - An operator can resolve a bounded context request from the Workbench
    without reconstructing assignment or ledger inputs manually.
  - Denied, unavailable, and oversized requests remain explicit backend-driven
    outcomes.
- Notes:
  - Added a dedicated runtime context-resolution panel that pre-fills the
    selected assignment, context-request, and ledger paths from the current
    runtime/manifest state instead of requiring manual re-entry.
  - Wired the panel into the shared Runtime M6 operator-action mutation layer
    and surfaced granted artifacts plus denied/unavailable refs directly from
    the backend resolution payload.
  - Kept the action backend-owned by sending the validated request through the
    typed `/api/context-request/resolve` client and rendering returned status
    rather than inferring continuation semantics in the frontend.
  - Verification:
    `npm --workspace apps/web run build`

### [x] WB6-03: Dispatch Packet Compile And Session Launch Controls

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: high
- Dependencies: WB6-01; RM35-02, RM35-04, RM35-05
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add operator controls for compiling a dispatch packet from existing mission,
    workflow, routing-decision, and assignment artifacts.
  - Add dry-run and bounded launch controls for `/api/session/dispatch` with
    explicit session record, workspace, timeout, isolation, and agent/model
    inputs.
  - Surface returned session record paths, run-bundle paths, and launch errors
    without hiding the authoritative backend response.
- Acceptance criteria:
  - An operator can compile and dry-run a bounded dispatch path from the
    Workbench.
  - Launch failures stay explicit and do not silently create fake success UI.
- Notes:
  - Added a dispatch compile preview panel that reuses the current mission,
    workflow, routing-decision, and assignment artifacts to call the validated
    `/api/dispatch-packet/compile` backend action.
  - Added a bounded session-dispatch control surface that launches from an
    existing dispatch-packet path with explicit agent, workdir, timeout,
    isolation, sandbox, dry-run, session-record, and run-bundle inputs.
  - Kept compile preview and launch separate because the backend compile action
    returns a validated packet object but does not persist a packet file.
  - Verification:
    `npm --workspace apps/web run build`

## Workstream 3: Acceptance And Runtime-State Advancement

Goal: let the operator apply the authoritative acceptance spine from the
Workbench while preserving backend control of ledger changes.

### [x] WB6-04: Result Staging And Review/Outcome Decision Controls

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: high
- Dependencies: WB6-01; RM35-01
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add explicit action forms for `/api/result/stage`,
    `/api/review-decision/import`, and `/api/outcome/decide`.
  - Require the operator to provide the same policy and artifact inputs the
    backend needs instead of deriving acceptance semantics in the frontend.
  - Refresh replay, gatekeeper, mutation, and history panels from the returned
    backend state after accepted actions.
- Acceptance criteria:
  - An operator can stage a result, import a review decision, and apply an
    authoritative outcome decision without leaving the Workbench.
  - Replay and gatekeeper panels reflect backend-returned post-action state
    rather than optimistic frontend assumptions.
- Notes:
  - Added three acceptance-spine action surfaces for result staging, review
    decision import, and node outcome decision directly in the runtime view.
  - Kept backend-required inputs explicit by showing assignment/result/outcome/
    decision paths, review event IDs, accepted event types, validation rule,
    and acceptance policy JSON instead of deriving acceptance semantics in the
    frontend.
  - Reused the shared Runtime M6 operator-action layer so result staging and
    outcome decisions refresh replay and gatekeeper state from backend
    responses.
  - Verification:
    `npm --workspace apps/web run build`

### [x] WB6-05: Runtime Action Safety, Doctoring, And Error Surfaces

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB6-01, WB6-03, WB6-04
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Surface available agents and doctor results near launch controls.
  - Add action-scoped safety copy for writable ledgers, dry-run mode, and
    structured backend rejections.
  - Keep invalid-path, validation, and strict-ledger failures visible without
    corrupting the surrounding runtime view.
- Acceptance criteria:
  - An operator can tell whether a launch target is doctor-healthy before
    dispatch.
  - Structured backend write failures are visible and locally recoverable.
- Notes:
  - Added typed agent inventory and doctor fetchers so the runtime view can
    inspect available launch targets and selected-agent health without leaving
    the Workbench.
  - Added an `Action safety and doctoring` runtime panel that surfaces doctor
    status, control level, binary/version details, dry-run and sandbox safety
    posture, and aggregated structured backend action failures.
  - Kept failures backend-authored by rendering returned validation and strict
    ledger rejection messages directly instead of translating them into local
    pseudo-states.
  - Verification:
    `npm --workspace apps/web run build`

### [x] WB6-06: Runtime Operator Actions Smoke Coverage

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: WB6-02, WB6-03, WB6-04, WB6-05
- Target files:
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add smoke coverage for context resolution, dispatch packet compile,
    dry-run launch, result staging, review import, outcome decision, and
    structured backend action failures.
  - Reuse maintained M3/M4-shaped fixtures and action responses instead of
    frontend-only synthetic control flow.
- Acceptance criteria:
  - The Workbench proves it can invoke the validated runtime action APIs end to
    end.
  - Coverage shows post-action state refresh coming from backend replay and
    gatekeeper responses instead of local mutation logic.
- Notes:
  - Extended the Workbench smoke harness with validated Runtime M6 backend
    routes for agent doctoring, context resolution, dispatch compile, session
    launch, result staging, review import, and outcome decision flows.
  - Added one smoke path for the full happy-path operator sequence and one
    smoke path for doctor degradation plus structured backend write failures,
    verifying the surrounding runtime view remains intact.
  - Tightened repeated-text assertions for pane-count and summary chips so the
    Runtime M6 smoke coverage stays stable under Playwright strict mode.
  - Verification:
    `npm --workspace apps/web run smoke -- --grep "Runtime M6"`
