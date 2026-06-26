# Runtime Harness Milestone 2.5 Task List

This is the proposed implementation task list for controlled workflow mutation.
It is tracked by GitHub issue
[#1 RFC: Controlled Workflow Mutation](https://github.com/Dying-Ember/BureauLess/issues/1)
and grounded in
[`../rfcs/workflow_mutation_proposal.md`](../rfcs/workflow_mutation_proposal.md).

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

### [ ] RM2.5-01: Mutation Proposal Schema

- Status: proposed
- Priority: high
- Risk: high
- Labels: runtime, protocol, replay
- Target docs:
  - `docs/rfcs/workflow_mutation_proposal.md`
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

### [ ] RM2.5-02: Mutation Event Types

- Status: proposed
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

## Workstream 2: Session And Result Integration

Goal: let real sessions surface workflow problems without expanding assignment
scope.

### [ ] RM2.5-03: Session Result Carries Proposal Refs

- Status: proposed
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

### [ ] RM2.5-04: Mutation Pending State

- Status: proposed
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

## Workstream 3: Acceptance And Supersession

Goal: apply accepted changes to current workflow and invalidate stale work
conservatively.

### [ ] RM2.5-05: Apply Accepted Mutation To Current Workflow

- Status: proposed
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

### [ ] RM2.5-06: Affected Assignment Evaluator

- Status: proposed
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

### [ ] RM2.5-07: Supersession Events And State

- Status: proposed
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

## Workstream 4: Current-State Replay And Workbench Inspection

Goal: make mutation-aware current state inspectable without implementing
temporal replay.

### [ ] RM2.5-08: Current-State Replay Support

- Status: proposed
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

### [ ] RM2.5-09: Workbench Mutation Inspection

- Status: proposed
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

## Workstream 5: Documentation And Acceptance

Goal: promote the RFC into protocol only after the implementation contract is
clear and tested.

### [ ] RM2.5-10: Promote Accepted RFC Sections

- Status: proposed
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
