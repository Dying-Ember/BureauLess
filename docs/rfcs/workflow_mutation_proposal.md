# RFC: Controlled Workflow Mutation

## Status

**Implemented in Milestone 2.5.** Canonical behavior now lives in
[`docs/protocol/harness_protocol.md`](../protocol/harness_protocol.md). This RFC
remains as design history. Full temporal replay remains deferred to M3+.

Tracking issue:
[#1 RFC: Controlled Workflow Mutation](https://github.com/Dying-Ember/BureauLess/issues/1)

Implementation task list:
[`docs/tasks/runtime_harness_milestone_2_5_tasklist.md`](../tasks/runtime_harness_milestone_2_5_tasklist.md)

## Problem

BureauLess currently assumes a static DAG: the workflow is defined before
execution and does not change at runtime. As soon as semi-automatic sessions
(Milestone 2) start executing real agent assignments, workers will encounter
situations where the original DAG is incomplete:

- A worker discovers a missing dependency that must be resolved before it can
  produce a valid result.
- A task logically splits into two bounded subtasks that should become separate
  nodes.
- A completed node is rendered stale by a structural change upstream.

Without a formal channel for communicating these discoveries, the worker is
left with bad options:

1. Exceed scope and change the structure itself, breaking invariants.
2. Describe the problem in natural-language output and hope a human notices.
3. Produce an incomplete result that will fail later review.
4. Force a human to manually edit YAML and guess which nodes are still reusable.

None of these preserve the core goal of BureauLess: structured, auditable, and
trustworthy agent workflow governance.

## Non-Goals

This RFC does not propose:

- Full temporal DAG replay, which is deferred to M3+.
- Time-travel browsing of historical workflow snapshots.
- Automatic DAG restructuring without human or orchestrator approval.
- Comparing mutation branches or rollback-to-event.
- Replacing the orchestrator with automated graph editing.

The scope is deliberately minimal: give workers a controlled, auditable channel
to propose structural changes without being allowed to enact them.

## Core Principle

> Mutation proposals do not change the workflow. Only accepted mutation ledger
> events change the workflow.

This extends the existing invariant: no worker writes canonical ledger state
directly. A worker can discover a problem and propose a structural fix; the
orchestrator or human reviewer decides whether to accept it; the harness records
the decision as a ledger event; only then does the workflow change.

The principle preserves every safety property established in M1 and M2: workers
remain bounded executors, not structural authors.

## Event Types

Three new ledger event types are proposed.

### `workflow_mutation_proposed`

```yaml
event_type: workflow_mutation_proposed
event_id: event-mutation-001
mission_id: <ref>
workflow_id: <ref>
mutation_proposal:
  # Valid Workflow Mutation Proposal document from the schema below.
  proposal_id: mutation-001
  proposal_type: workflow_mutation
  ...
```

### `workflow_mutation_accepted`

```yaml
event_type: workflow_mutation_accepted
event_id: event-mutation-accepted-001
source_event_id: event-mutation-001
actor: orchestrator | human
applied_changes:
  add_nodes: [...]
  add_edges: [...]
  remove_edges: [...]
  supersede_assignments: [...]
```

### `workflow_mutation_rejected`

```yaml
event_type: workflow_mutation_rejected
event_id: event-mutation-rejected-001
source_event_id: event-mutation-001
actor: orchestrator | human
reason: <why it was rejected>
```

Accepted and rejected events must reference an earlier
`workflow_mutation_proposed` event through `source_event_id`. The referenced
proposal may be decided only once. An acceptance may apply a subset of the
proposal, but every item in `applied_changes` must exist in that proposal.

## Mutation Proposal Schema

A session result carries optional immutable artifact references to mutation
proposals:

```yaml
result:
  status: completed_with_proposal
  artifacts:
    - artifact_id: artifact-mutation-001
      path: artifacts/mutation-001.yaml
      sha256: "..."
      created_by: worker-001
      source_event: event-result-001
      mutable: false
  mutation_proposal_refs:
    - artifact-mutation-001
```

The referenced YAML artifact contains the proposal schema below. Keeping the
result reference as an `artifact_id` makes the immutable artifact record the
single source of truth for path, hash, provenance, and mutability.

The proposal schema allows:

- `add_nodes`: Create nodes using the canonical workflow node fields: `id`,
  `role`, `waits_for`, and `emits`.
- `add_edges`: Insert event dependencies between existing or new nodes.
- `remove_edges`: Remove edges. This must not orphan completed nodes without
  explicit `supersede_assignments`.
- `supersede_assignments`: Explicitly mark downstream assignments as
  invalidated.

The schema explicitly prohibits:

- Removing existing nodes entirely. Supersession handles this by marking
  assignments, not deleting structural history.
- Rewriting ledger events.
- Creating new assignments for already-completed nodes.

Because BureauLess workflows express dependencies through events rather than
anonymous graph edges, every edge mutation uses `from_node`, `to_node`, and
`event`. The edge means that `to_node` waits for the qualified event reference
`from_node.event`. A bare `from`/`to` pair is invalid because one source node
may emit more than one event.

Schema validation is strict and inert:

- Unknown fields and forbidden operations are rejected with structured error
  codes and paths.
- At least one evidence artifact and one proposed change are required.
- Duplicate, self-referential, or simultaneously added-and-removed edges are
  rejected.
- Validation produces a proposal value only. It does not alter a workflow,
  create assignments, or append ledger events.

## Accept / Reject Flow

```text
worker/session
  -> emits workflow_mutation_proposal artifact
  -> result package carries proposal ref
  -> gatekeeper marks mutation pending
  -> orchestrator/human accepts or rejects
     -> accepted: produce workflow_mutation_accepted ledger event
        -> apply to current_workflow
        -> supersede affected assignments
        -> gatekeeper recalculates ready/blocked
     -> rejected: produce workflow_mutation_rejected ledger event
        -> no workflow state change
```

The gateway between proposal and effect is always an explicit accept/reject
decision recorded as a ledger event. There is no path from "worker noticed a
problem" to "workflow changed" that bypasses this gate.

## Affected Assignment Rules

When a mutation is accepted, the harness must determine which existing
assignments are superseded. The rules are conservative by design: the cost of
falsely marking an assignment as unaffected, which means trusting stale results,
is higher than the cost of re-running a superseded assignment.

### Default Rule

An assignment is affected if the mutation changes any of:

- Its effective preconditions, meaning dependency closure.
- Its goal or output contract semantics.
- Its `acceptance_criteria`.
- Its reachable path in the dependency graph.

### Explicit Rules

| Situation | Verdict | Rationale |
|---|---|---|
| New node inserted into an upstream dependency chain of assignment X | affected | X was produced under older preconditions. Its execution context is invalidated. |
| X's `dependencies`, `goal`, `outputs`, `acceptance_criteria`, or `required_events` are directly changed | affected | The assignment was executed under a different contract. |
| An upstream dependency of X is superseded | affected | Transitive invalidation. X's result depends on a result whose validity has been revoked. |
| Sibling node Y changes, but X's dependency closure, goal, and output contract are unchanged | unaffected | No structural or semantic effect on X. |
| A node or edge with no reachable path to X is deleted | unaffected | X's execution context is independent. |
| Ambiguous, cannot determine with certainty | needs_review | Do not automatically preserve `completed` status. Flag for orchestrator or human decision. |

### Example: `B -> D` becomes `B -> C -> D`

```text
Before: B -> D (completed)
After:  B -> C -> D
```

D is marked affected and superseded. Even though D completed successfully, it
ran under the precondition "B is done." Its new path is "B is done, then C is
done, then D runs." The execution context has changed: the result of D may not
hold under the new chain, because C may modify the state D depends on.

### Preserved Nodes

Completed nodes whose dependency closure, goal, outputs, and acceptance criteria
are unchanged by the mutation remain `completed`. Re-running them would be
wasteful and would break the audit trail for no reason.

## Current-State Replay (M2.5 Scope)

M2.5 provides current-state replay only:

```text
initial_workflow + accepted_mutations -> current_workflow
current_workflow + ledger_events      -> derived_node_states
```

This is tractable and sufficient for:

- Gatekeeper determining `ready`, `blocked`, `completed`, and `superseded`.
- Workbench displaying current DAG structure and node states.
- Verifying that accepted mutations produce a consistent workflow.

### Explicitly Deferred

- Snapshotting the workflow at every historical event timestamp.
- Answering "which nodes were runnable at time T?" for arbitrary T.
- Time-travel browsing of previous workflow versions.
- Comparing mutation branches.
- `rollback_to_event`.

These belong to temporal workflow replay, which is a separate body of work
targeted at M3+.

## Temporal Replay (Deferred - M3+)

When BureauLess eventually supports full temporal replay, the problem becomes:

```text
initial_workflow
  + event_1 (before mutation)
  + event_2 (workflow_mutation_accepted: B -> C -> D)
  + event_3 (node C completed)
  + event_4 (node D completed)
  ->
  workflow snapshots over time
  + node states under each snapshot
  + gatekeeper decisions at each version
  + "why was this runnable then?" queries
```

Required infrastructure deferred to M3+:

- `workflow_version_id` tracking.
- Event-to-`workflow_version` mapping.
- Node identity across split/merge operations.
- Assignment validity checks under old and new workflow versions.
- Historical gatekeeper decision records.
- Workbench timeline view.

## Workbench Implications

M2.5 adds one new inspection surface:

| View | Content |
|---|---|
| Current DAG | Post-mutation workflow structure |
| Mutation proposal list | Pending proposals with accept/reject actions |
| Mutation proposal detail | Proposed changes, evidence refs, affected assignments |
| Superseded assignments | Which assignments were invalidated, by which mutation |
| Replay view (current-state) | `current_workflow + ledger -> derived state` |
| Diff view | Original DAG vs. current DAG after accepted mutations |

No drag-to-connect editor. No visual DAG construction. These remain deferred
(B5 in the roadmap).

## Milestone 2.5 Decisions

1. **Partial acceptance**: Can the orchestrator accept a subset of proposed
   changes, such as accepting `add_node` but rejecting `remove_edge`?

   Decision: yes, with explicit `applied_changes` in the acceptance event.

2. **Chained mutations**: What happens when a mutation proposal depends on a
   previously-proposed but not-yet-accepted mutation?

   Decision: reject with `mutation_dependency_pending`. Keep the dependency
   chain linear until temporal replay can handle branching.

3. **Mutation from orchestrator**: Can the orchestrator itself generate mutation
   proposals, not just approve or deny?

   Decision: keep the mutability right symmetric. The orchestrator can propose
   to itself and the same acceptance flow applies. This is useful for
   orchestrator-initiated replanning.

4. **Mutually exclusive mutations**: Two workers propose incompatible structural
   changes simultaneously.

   Decision: gatekeeper detects conflict, marks both proposals as
   `conflict_pending`, and requires the orchestrator to accept one and reject
   the other.

5. **Node versioning**: When a node is superseded and re-executed, does it need
   a separate node identity?

   Decision: yes. The old assignment retains its original `node_id`; the
   superseded assignment gets a new `assignment_id` tied to the same `node_id`
   in the updated workflow.

## Migration Path

No breaking changes to existing protocol. New event types are additive.
Existing M1/M2 invariants are preserved: workers cannot write the ledger; only
accepted events change current workflow.

## Related Documents

- [`docs/protocol/harness_protocol.md`](../protocol/harness_protocol.md)
- [`docs/architecture/research_and_design_notes.md`](../architecture/research_and_design_notes.md)
- [`docs/roadmap/development_roadmap.md`](../roadmap/development_roadmap.md)
- [`docs/tasks/runtime_harness_milestone_1_tasklist.md`](../tasks/runtime_harness_milestone_1_tasklist.md)
- [`docs/tasks/runtime_harness_milestone_2_tasklist.md`](../tasks/runtime_harness_milestone_2_tasklist.md)
