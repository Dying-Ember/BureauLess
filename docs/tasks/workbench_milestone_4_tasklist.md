# Workbench Milestone 4 Task List

Status: completed. Implementation accepted with build and smoke coverage.

This is the completed UI/workbench delivery milestone for BureauLess. It follows
the completed Workbench Milestone 3 source-loading work and closes the current
inspection gap between the Workbench and the structured artifacts delivered by
Runtime Harness Milestone 3.

The project-level sequencing lives in
[`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md). The
backend artifact and API scope comes from
[`runtime_harness_milestone_3_tasklist.md`](runtime_harness_milestone_3_tasklist.md),
especially RM3-01 through RM3-12.

Milestone 4 is an inspection milestone. It does not add frontend-owned routing,
advisor, context, outcome, or dispatch policy. The Python protocol loaders and
API responses remain authoritative.

## Goals

1. Make the M3 decision, outcome, context, telemetry, and dispatch artifacts
   visible in the Workbench.
2. Preserve artifact provenance and references so an operator can follow why a
   node ran, what context it received, and what outcome was accepted.
3. Reuse the maintained M3 demo artifacts as the end-to-end acceptance path.

## Principles

- Read canonical M3 artifacts through the Python API; do not parse YAML or
  reproduce validation rules in the frontend.
- Keep artifact selection and display state separate from runtime truth.
- Prefer read-only inspection before adding mutation or dispatch controls.
- Make missing, invalid, and unavailable artifacts explicit states.
- Keep planning-DAG controls separate from runtime artifact inspection.
- Land each feature with focused component or smoke coverage.
- Recommended models should use current native Codex model names and reflect
  the complexity of the task rather than a fixed milestone-wide default.

## Workstream 1: Artifact Sources And API Contracts

Goal: establish one typed, testable frontend boundary for the M3 API surface.

### [x] WB4-01: Runtime Artifact Session Manifest API

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: RM3-11 M3 Integrated Demo Fixture, RM3-12 M3 Runtime API
  Coverage
- Target files:
  - `src/bureauless/application/demo.py`
  - `src/bureauless/api/server.py`
  - `tests/test_server.py`
- Work:
  - Add one read-only API response for the maintained M3 demo manifest so the
    Workbench can discover related artifact paths from one source.
  - Preserve top-level decision/telemetry paths and per-step assignment,
    context, result, outcome, review, turn, and dispatch references.
  - Validate the manifest shape and keep artifact loading delegated to the
    existing protocol endpoints and loaders.
- Acceptance criteria:
  - One `artifact_manifest_path` identifies the related M3 inspection set.
  - Invalid or incomplete manifests return structured API errors.
  - The endpoint discovers artifacts but does not reinterpret runtime policy.
- Implementation notes:
  - Added a validated `/api/artifact-session-manifest` endpoint backed by a
    shared demo-application manifest loader instead of frontend YAML parsing.
  - Expanded the maintained live-demo manifest to preserve per-step
    `turn_report_path` and `dispatch_packet_path` references needed by later
    Workbench M4 inspection tasks.
  - Brought the demo routing decision payload into canonical protocol shape so
    the manifest paths now resolve through the existing typed API endpoints.
  - Verified with:
    `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_server.py -q`
    and
    `env UV_CACHE_DIR=/tmp/uv-cache uv run python -m pytest tests/test_harness.py -q -k "run_live_demo"`.

### [x] WB4-02: M3 Artifact API Client And Source Model

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: WB4-01, Workbench Milestone 3 runtime-source model
- Target files:
  - `apps/web/src/api/client.ts`
  - `apps/web/src/main.tsx`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Add typed client functions for the artifact manifest, routing decisions,
    assignments, context capsules, context requests, result proposals, node
    outcomes, advisor outcomes, turn reports, dispatch packets, and runtime
    metrics summaries.
  - Add `artifact_manifest_path` to the runtime-source URL and persisted source
    model, following the Workbench M3 precedence rules.
  - Preserve canonical API field names, nullable states, and the existing client
    error boundary.
- Acceptance criteria:
  - A shared Workbench URL can identify the runtime baseline and its complete
    M3 inspection set without frontend YAML parsing or many independent path
    inputs.
  - The frontend can load every read-only M3 endpoint required by this
    milestone.
  - Missing optional artifacts do not prevent baseline runtime inspection.
- Implementation notes:
  - Added typed frontend client functions for the manifest, routing decision,
    assignment, context, result, outcome, advisor, turn-report, dispatch, and
    metrics endpoints used by Workbench M4.
  - Extended the runtime source model, URL parsing, and local persistence with
    `artifact_manifest_path` while keeping explicit `mission/workflow/ledger`
    inputs authoritative when present.
  - Added manifest-driven runtime source resolution so a shared Workbench URL
    can open the M3 inspection baseline from one manifest path.
  - Verified with:
    `npm run web:build`
    and
    `npm --workspace apps/web run smoke -- --grep "runtime summary panels|artifact_manifest_path"`.

## Workstream 2: Decision And Outcome Inspection

Goal: explain the orchestrator's choices and the observed result without
requiring raw YAML inspection.

### [x] WB4-03: Routing And Advisor Inspector

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: WB4-01, WB4-02; RM3-01 through RM3-04
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Show selected execution mode, rejected simpler modes, routing rationale,
    budget state, advisor invoke/skip decision, and scored advisor outcome.
  - Display source decision and price-snapshot references where present.
  - Distinguish pending outcomes from scored outcomes.
- Acceptance criteria:
  - An operator can explain why the selected mode and advisor choice were made.
  - `good_call`, `bad_call`, `good_skip`, and `missed_call` states are visible
    without the frontend recomputing them.
  - Missing evidence is shown as unavailable, not silently treated as a skip.
- Implementation notes:
  - Added a manifest-backed routing/advisor inspection panel that reads the
    canonical routing decision and advisor outcome APIs directly.
  - Exposed selected mode, rejected simpler modes, routing rationale, advisor
    invoke/skip decision, advisor classification, token totals, and source
    references without recomputing backend classifications in the UI.
  - Added smoke coverage for the manifest-backed routing/advisor surface.
  - Verified with:
    `npm run web:build`
    and
    `npm --workspace apps/web run smoke -- --grep "artifact_manifest_path|routing and advisor inspector|runtime summary panels"`.

### [x] WB4-04: Node Outcome And Evidence Inspector

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: WB4-01, WB4-02; RM3-05, RM3-07
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Show node outcome state, workspace delta, complete evidence references,
    accepted findings, rejected findings, and review decision links.
  - Connect the loaded outcome to the matching runtime node when an authoritative
    node identifier is available.
  - Keep accepted ledger facts visually distinct from unaccepted worker output.
- Acceptance criteria:
  - An operator can distinguish execution evidence from canonical mission truth.
  - Selecting a linked runtime node exposes its outcome without changing
    gatekeeper or replay state.
  - Revision and rejection reasons remain inspectable.
- Implementation notes:
  - Linked selected runtime nodes to manifest-backed M3 steps and surfaced
    node outcome state, workspace delta, execution evidence, accepted findings,
    rejected findings, and review-decision references in the runtime node
    inspector.
  - Kept accepted ledger facts visually distinct from observed worker output in
    separate inspection sections.
  - Verified with:
    `npm run web:build`
    and
    `npm --workspace apps/web run smoke -- --grep "node outcome and accepted evidence"`.

## Workstream 3: Context, Telemetry, And Dispatch Inspection

Goal: show exactly what crossed the worker boundary and why.

### [x] WB4-05: Context Delivery Inspector

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: WB4-01, WB4-02; RM3-08, RM3-09
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Show context-capsule policy version, token estimate, dependency closure,
    accepted facts, active risks, and included artifact references.
  - Show scoped context requests and their resolution state when supplied.
  - Make bounded context and progressively disclosed evidence distinguishable.
- Acceptance criteria:
  - An operator can see what the worker initially received and what was added
    later.
  - The UI does not imply that omitted ledger data was delivered.
  - Context request failures and unavailable evidence are explicit.
- Implementation notes:
  - Added manifest-backed context inspection for capsule policy version,
    dependency closure, accepted facts, active risks, included artifact refs,
    token estimate, and progressively disclosed context requests observed in
    session metrics.
  - Explicitly renders `No artifact step linked`, `none`, and `unavailable`
    states so missing or omitted context evidence is never silently inferred.
  - Verified with:
    `npm run web:build`
    and
    `npm --workspace apps/web run smoke -- --grep "context delivery details"`.

### [x] WB4-06: Budget And Context Telemetry Inspector

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB4-01, WB4-02; RM3-02, RM3-03, RM3-10
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Show observed token/cost totals, price-snapshot attribution, advisor score
    summary, and context-fit classifications from the canonical metrics API.
  - Expose policy version and recommendation evidence without applying policy
    changes from the frontend.
  - Distinguish unknown cost, unavailable evidence, and zero usage.
- Acceptance criteria:
  - Operators can inspect the budget and context telemetry delivered by M3.
  - The frontend displays backend classifications without recomputing them.
  - Metrics failures do not hide the underlying runtime artifacts.
- Implementation notes:
  - Added telemetry inspection sourced from the canonical metrics APIs for
    observed tokens, cost, advisor score counts, context-fit classification,
    context-fit reason, total context requests, and added-token totals.
  - The UI displays backend classifications directly and keeps unavailable
    telemetry explicit instead of inferring zero values.
  - Verified with:
    `npm run web:build`
    and
    `npm --workspace apps/web run smoke -- --grep "budget telemetry and bounded handoff"`.

### [x] WB4-07: Assignment, Result, Turn, And Dispatch Inspector

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB4-01, WB4-02; RM3-06, RM3-12
- Target files:
  - `apps/web/src/main.tsx`
  - `apps/web/src/styles.css`
  - `apps/web/tests/workbench.smoke.spec.ts`
- Work:
  - Show the compiled dispatch packet alongside its assignment, result proposal,
    and turn-report artifacts.
  - Expose agent/provider/model binding, constraints, expected outputs, and
    review requirements already present in canonical payloads.
  - Cross-link artifact identifiers and references without adding a dispatch
    action.
- Acceptance criteria:
  - An operator can inspect the complete bounded handoff and returned result.
  - Commit-like review constraints are visible when present.
  - This surface remains read-only.
- Implementation notes:
  - Added bounded handoff inspection for assignment, result, turn-report, and
    dispatch-packet artifacts, including provider/model binding, expected
    events, forbidden actions, required review gates, and turn-report policy.
  - Kept the surface read-only and manifest-linked without adding any dispatch
    action.
  - Verified with:
    `npm run web:build`
    and
    `npm --workspace apps/web run smoke -- --grep "budget telemetry and bounded handoff"`.

## Workstream 4: Integrated Acceptance And Documentation

Goal: prove that the Workbench can inspect the maintained M3 path end to end.

### [x] WB4-08: M3 Demo Inspection Smoke Coverage

- Status: completed
- Priority: high
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: WB4-03 through WB4-07; RM3-11
- Target files:
  - `apps/web/tests/workbench.smoke.spec.ts`
  - `docs/tasks/workbench_milestone_4_tasklist.md`
  - `docs/roadmap/development_roadmap.md`
- Work:
  - Open the Workbench with the maintained M3 demo runtime and artifact paths.
  - Verify routing/advisor, outcome/evidence, context, telemetry, and dispatch
    surfaces.
  - Verify narrow viewport layout and explicit missing-artifact states.
  - Record the final build, smoke, and manual verification commands.
- Acceptance criteria:
  - One smoke flow covers the complete M3 inspection path.
  - The test fails if the frontend falls back to stale persisted artifact paths.
  - The roadmap and indexes are updated only after implementation acceptance is
    complete.
- Implementation notes:
  - Added a narrow-viewport manifest-backed smoke flow that covers routing,
    advisor, outcome, evidence, context, telemetry, assignment, result,
    turn-report, dispatch, and explicit missing-artifact states.
  - Verified the complete frontend suite with:
    `npm run web:build`
    and
    `npm --workspace apps/web run smoke`.

## Recommended Execution Order

1. WB4-01 Runtime Artifact Session Manifest API
2. WB4-02 M3 Artifact API Client And Source Model
3. WB4-03 Routing And Advisor Inspector
4. WB4-04 Node Outcome And Evidence Inspector
5. WB4-05 Context Delivery Inspector
6. WB4-06 Budget And Context Telemetry Inspector
7. WB4-07 Assignment, Result, Turn, And Dispatch Inspector
8. WB4-08 M3 Demo Inspection Smoke Coverage

## Milestone 4 Acceptance

- The M3 manifest API provides one validated discovery boundary for related
  runtime artifacts.
- Every read-only M3 inspection endpoint has a typed frontend client and a
  visible inspection path.
- The Workbench explains routing, advisor, outcome, context, budget/telemetry,
  and dispatch state using canonical backend payloads.
- Operators can follow artifact references across the maintained M3 demo path.
- Missing artifacts and API errors remain explicit without breaking baseline
  mission/workflow/ledger inspection.
- No runtime policy, YAML parsing, dispatch action, or canonical-state mutation
  is introduced in the frontend.
- The complete web build and smoke suite pass, with the verification commands
  recorded in this task list.
