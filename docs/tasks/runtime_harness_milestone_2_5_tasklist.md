# Runtime Harness Milestone 2.5 Task List

This is the completed implementation task list for controlled workflow mutation.
It is tracked by GitHub issue
[#1 RFC: Controlled Workflow Mutation](https://github.com/Dying-Ember/BureauLess/issues/1)
and grounded in
[`../rfcs/001-controlled-workflow-mutation.md`](../rfcs/001-controlled-workflow-mutation.md).

Milestone 2.5 is intentionally narrow. It gives workers a controlled channel to
propose workflow structure changes after a session discovers that the current
workflow is incomplete. It does not implement full temporal workflow replay.

## Principles

- A mutation proposal must not change the workflow by itself.
- Only an accepted mutation ledger event can change the current workflow.
- Workers may propose structure changes, but they must not enact them.
- Accepted mutations must preserve replayability of current state.
- Completed assignments are preserved only when their execution context remains
  valid under the accepted workflow.
- Ambiguous assignment validity must become reviewable, not silently trusted.

## Non-Goals

- No full temporal workflow replay.
- No arbitrary historical DAG snapshots.
- No rollback-to-event.
- No mutation branch comparison.
- No visual drag-to-connect workflow editor.
- No worker-created canonical assignments.

## Workstream 1: Proposal Contract

Goal: define the smallest valid artifact and event surface for mutation
proposals.

### [x] RM2.5-01: Mutation Proposal Schema

- Status: completed
- Priority: high
- Risk: high
- Labels: runtime, protocol, replay
- Target docs:
  - `docs/rfcs/001-controlled-workflow-mutation.md`
  - `docs/protocol/harness_protocol.md`
- Target code:
  - `src/bureauless/protocol/`
  - `tests/test_harness.py`
- Work:
  - Add a structured `workflow_mutation` proposal schema.
  - Support `add_nodes`, `add_edges`, `remove_edges`, and
    `supersede_assignments`.
  - Reject proposals that attempt to remove ledger history, rewrite accepted
    events, or create canonical assignments directly.
- Acceptance criteria:
  - Invalid mutation proposals fail validation with structured errors.
  - Valid proposals remain inert until accepted by a ledger event.
- Implementation notes:
  - Added strict proposal dataclasses and structured validation in
    `src/bureauless/protocol/mutations.py`.
  - Event dependency changes use `from_node`, `to_node`, and `event`, matching
    the existing event-driven workflow model without ambiguous bare edges.
  - Proposal validation is intentionally inert and cannot append events,
    create assignments, or alter workflow objects.
  - Verified by the focused harness suite: `74 passed`.

### [x] RM2.5-02: Mutation Event Types

- Status: completed
- Priority: high
- Risk: high
- Labels: runtime, protocol
- Target docs:
  - `docs/protocol/harness_protocol.md`
- Target code:
  - `src/bureauless/protocol/`
  - `src/bureauless/runtime/replay.py`
  - `tests/test_harness.py`
- Work:
  - Add `workflow_mutation_proposed`.
  - Add `workflow_mutation_accepted`.
  - Add `workflow_mutation_rejected`.
  - Enforce provenance links from accepted/rejected events back to the proposed
    mutation event.
- Acceptance criteria:
  - The ledger can record pending, accepted, and rejected mutation decisions.
  - Accepted/rejected events without a valid proposal reference are rejected.
- Implementation notes:
  - Added the three mutation event types to the canonical ledger validator.
  - Accepted/rejected events require a prior proposal event and an
    orchestrator or human actor; each proposal can be decided only once.
  - Partial acceptance is supported only when every applied operation exists
    in the referenced proposal.
  - Verified by the focused harness suite: `78 passed`.

## Workstream 2: Session And Result Integration

Goal: let real sessions surface workflow problems without expanding assignment
scope.

### [x] RM2.5-03: Session Result Carries Proposal Refs

- Status: completed
- Priority: high
- Risk: medium
- Labels: runtime, artifact-integrity
- Target code:
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/protocol/results.py`
  - `tests/test_harness.py`
- Work:
  - Allow a session result proposal to reference one or more mutation proposal
    artifacts.
  - Preserve artifact hashes and provenance for proposal files.
  - Distinguish `completed`, `blocked`, and `completed_with_proposal`.
- Acceptance criteria:
  - A worker can return a bounded result plus a mutation proposal reference.
  - The result importer does not apply the mutation automatically.
- Implementation notes:
  - Added `mutation_proposal_refs` as artifact IDs on result proposals.
  - Proposal refs require `completed_with_proposal` and must resolve to an
    immutable YAML artifact in the same result.
  - Session extraction and packaging preserve the artifact ID while the normal
    artifact pipeline records path, hash, provenance, and immutability.
  - Result import records only `result_submitted`; proposal application remains
    behind explicit mutation events.
  - Verified by the focused harness suite: `81 passed`.

### [x] RM2.5-04: Mutation Pending State

- Status: completed
- Priority: medium
- Risk: medium
- Labels: runtime, gatekeeper
- Target code:
  - `src/bureauless/runtime/replay.py`
  - `src/bureauless/runtime/gatekeeper.py`
  - `tests/test_harness.py`
- Work:
  - Represent pending mutation proposals in derived runtime state.
  - Block downstream dispatch when a pending mutation may invalidate assignment
    context.
  - Keep unaffected ready nodes runnable.
- Acceptance criteria:
  - Gatekeeper can explain that a node is blocked by `mutation_pending`.
  - Pending mutations do not block unrelated workflow branches.
- Implementation notes:
  - Replay now exposes pending, accepted, and rejected proposal decisions.
  - Pending impact includes explicit edge targets or superseded assignment
    nodes and their existing downstream closure.
  - Gatekeeper emits `mutation_pending` only for affected nodes; rejected
    proposals release the branch without changing workflow structure.
  - Verified by the focused harness suite: `83 passed`.

## Workstream 3: Acceptance And Supersession

Goal: apply accepted changes to current workflow and invalidate stale work
conservatively.

### [x] RM2.5-05: Apply Accepted Mutation To Current Workflow

- Status: completed
- Priority: high
- Risk: high
- Labels: runtime, protocol
- Target code:
  - `src/bureauless/protocol/`
  - `src/bureauless/runtime/replay.py`
  - `tests/test_harness.py`
- Work:
  - Materialize `current_workflow` from `initial_workflow + accepted_mutations`.
  - Apply only the `applied_changes` recorded in the acceptance event.
  - Reject accepted changes that make the current workflow invalid.
- Acceptance criteria:
  - Accepted mutations deterministically produce the same current workflow.
  - Rejected mutations never affect current workflow structure.
- Implementation notes:
  - Added `materialize_current_workflow(initial_workflow, ledger)`.
  - Applied changes are replayed in ledger order into new immutable workflow
    values; the initial workflow is preserved.
  - Every accepted step must compile and remain acyclic. Unknown nodes/events,
    duplicate or missing edges, and invalid contracts reject materialization.
  - Verified by the focused harness suite: `86 passed`.

### [x] RM2.5-06: Affected Assignment Evaluator

- Status: completed
- Priority: high
- Risk: high
- Labels: runtime, replay, gatekeeper
- Target code:
  - `src/bureauless/runtime/replay.py`
  - `tests/test_harness.py`
- Work:
  - Implement conservative affected/unaffected/needs_review classification.
  - Mark downstream assignments as superseded when their dependency closure,
    goal, outputs, or acceptance criteria changed.
  - Preserve completed nodes only when their execution context is unchanged.
- Acceptance criteria:
  - Inserting `B -> C -> D` supersedes prior completed work for `D`.
  - Sibling-only changes do not supersede unrelated completed work.
  - Ambiguous cases become `needs_review`.
- Implementation notes:
  - Added deterministic `affected`, `unaffected`, and `needs_review`
    classification for assignments.
  - Evaluation compares node role/event/wait contracts and full upstream
    dependency closures before and after mutation.
  - Explicit supersession wins; missing or conflicting assignment provenance
    becomes `needs_review`.
  - Verified by the focused harness suite: `88 passed`.

### [x] RM2.5-07: Supersession Events And State

- Status: completed
- Priority: medium
- Risk: medium
- Labels: runtime, replay
- Target code:
  - `src/bureauless/protocol/`
  - `src/bureauless/runtime/replay.py`
  - `tests/test_harness.py`
- Work:
  - Record which assignments were superseded by which accepted mutation.
  - Ensure superseded sessions remain auditable.
  - Prevent superseded completed work from satisfying downstream gates.
- Acceptance criteria:
  - Replay can explain that an assignment was superseded by a mutation.
  - Superseded results remain visible but no longer count as current success.
- Implementation notes:
  - Added deterministic mutation-linked `assignment_superseded` event builders
    for affected assignments.
  - Supersession events preserve the accepted mutation reference and impact
    reasons; replay exposes the link on assignment attempt state.
  - Historical results remain append-only, while events emitted by superseded
    assignments no longer satisfy nodes, gates, or terminal conditions.
  - Verified by the focused harness suite: `89 passed`.

## Workstream 4: Current-State Replay And Workbench Inspection

Goal: make mutation-aware current state inspectable without implementing
temporal replay.

### [x] RM2.5-08: Current-State Replay Support

- Status: completed
- Priority: high
- Risk: high
- Labels: runtime, replay
- Target code:
  - `src/bureauless/runtime/replay.py`
  - `tests/test_harness.py`
- Work:
  - Replay accepted mutations into current workflow before deriving node state.
  - Keep event history append-only.
  - Explicitly exclude historical workflow snapshot queries.
- Acceptance criteria:
  - `initial_workflow + accepted_mutations -> current_workflow`.
  - `current_workflow + ledger_events -> current derived state`.
- Implementation notes:
  - `replay_workflow` now takes the initial workflow and materializes accepted
    mutations before deriving node and assignment state.
  - Pending/rejected proposals do not alter the materialized workflow.
  - Historical workflow snapshots and time-based replay remain explicitly out
    of scope.
  - Verified by the focused harness suite: `89 passed`.

### [x] RM2.5-09: Workbench Mutation Inspection

- Status: completed
- Priority: medium
- Risk: medium
- Labels: workbench, runtime
- Target code:
  - `src/bureauless/api/server.py`
  - `apps/web/src/`
  - `tests/test_server.py`
  - `apps/web/tests/`
- Work:
  - Expose pending mutation proposals through the API.
  - Show proposed changes, evidence refs, and affected assignments.
  - Support accept/reject actions only after protocol validation exists.
- Acceptance criteria:
  - Workbench can inspect pending proposals and superseded assignments.
  - No visual workflow editor is introduced in this milestone.
- Implementation notes:
  - Added mutation inspection and accept/reject API endpoints backed by the
    canonical protocol, ledger, materialization, and impact evaluators.
  - Acceptance writes the decision, validates current workflow, and appends
    affected assignment supersession events before persisting the ledger.
  - Workbench shows rationale, evidence, affected/superseded assignments, and
    validated decision actions without adding a graph editor.
  - `npm run mutation-demo:prepare` creates an ignored, disposable workflow and
    ledger and prints a parameterized Workbench URL for manual end-to-end
    acceptance testing.
  - Verified by `111` Python tests, a production web build, and `19` Playwright
    smoke tests.

## Workstream 5: Documentation And Acceptance

Goal: promote the RFC into protocol only after the implementation contract is
clear and tested.

### [x] RM2.5-10: Promote Accepted RFC Sections

- Status: completed
- Priority: medium
- Risk: low
- Labels: protocol, docs
- Target docs:
  - `docs/protocol/harness_protocol.md`
  - `docs/roadmap/development_roadmap.md`
  - `docs/tasks/runtime_harness_tasklist.md`
- Work:
  - Move accepted event/schema semantics from RFC into protocol docs.
  - Keep open questions in the RFC until resolved.
  - Update roadmap status once M2.5 is implemented.
- Acceptance criteria:
  - Protocol docs describe only accepted behavior.
  - RFC remains as design history, not the source of implemented truth.
- Implementation notes:
  - Promoted implemented schema, event, replay, gatekeeper, supersession, and
    Workbench behavior into `docs/protocol/harness_protocol.md`.
  - Marked the RFC as implemented design history and linked the canonical
    protocol source.
  - Updated the documentation map, milestone index, and project roadmap to
    reflect M2.5 completion.
  - Final verification: `129` Python tests, production web build, and `19`
    Playwright smoke tests.

## Milestone 2.5 Acceptance

Runtime milestone 2.5 is complete when:

- A session can produce a mutation proposal artifact without mutating workflow.
- The ledger can record proposed, accepted, and rejected mutation decisions.
- Accepted mutations deterministically update current workflow structure.
- Affected assignments are superseded conservatively and explainably.
- Current-state replay works on the accepted current workflow.
- Gatekeeper can block on `mutation_pending`, `needs_review`, and
  `superseded` states.
- Workbench can inspect pending proposals and superseded assignments.
- Full temporal replay remains explicitly deferred.
