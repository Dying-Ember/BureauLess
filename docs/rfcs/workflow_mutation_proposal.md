# RFC: Controlled Workflow Mutation

## Status

**Proposed** - Milestone 2.5 candidate. Open for discussion.

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
event_id: mut-<uuid>
source:
  assignment_id: <ref>
  session_id: <ref>
  actor: worker
  evidence_refs:
    - artifact-impact-report
proposed_changes:
  add_nodes:
    - id: <new-node-id>
      dependencies: [<ref>, ...]
      # full node spec
  add_edges:
    - from: <ref>
      to: <ref>
  remove_edges: []
  supersede_assignments: []
reason: discovered_missing_dependency | node_needs_split | stale_result | other
rationale: <human-readable justification>
requires_approval: orchestrator
```

### `workflow_mutation_accepted`

```yaml
event_type: workflow_mutation_accepted
event_id: acc-<uuid>
source:
  mutation_event: mut-<uuid>
  actor: orchestrator | human
  notes: <optional>
applied_changes:
  add_nodes: [...]
  add_edges: [...]
  supersede_assignments: [...]
```

### `workflow_mutation_rejected`

```yaml
event_type: workflow_mutation_rejected
event_id: rej-<uuid>
source:
  mutation_event: mut-<uuid>
  actor: orchestrator | human
  reason: <why it was rejected>
```

## Mutation Proposal Schema

A session result carries an optional reference to a mutation proposal:

```yaml
result:
  status: completed_with_proposal
  artifacts: [...]
  mutation_proposal:
    proposal_type: workflow_mutation
    reason: discovered_missing_dependency
    proposed_changes:
      add_nodes:
        - id: field-resolver-tests
          dependencies:
            - field-resolver-skeleton
          goal: "Write focused tests for the FieldResolver helper."
          ...
      add_edges:
        - from: field-resolver-skeleton
          to: field-resolver-tests
    evidence_refs:
      - artifact-impact-report
    requires_approval: orchestrator
```

The proposal schema allows:

- `add_nodes`: Create new nodes with full specs, such as goal, dependencies,
  target files, review gate, and verification commands.
- `add_edges`: Insert edges between existing or new nodes.
- `remove_edges`: Remove edges. This must not orphan completed nodes without
  explicit `supersede_assignments`.
- `supersede_assignments`: Explicitly mark downstream assignments as
  invalidated.

The schema explicitly prohibits:

- Removing existing nodes entirely. Supersession handles this by marking
  assignments, not deleting structural history.
- Rewriting ledger events.
- Creating new assignments for already-completed nodes.

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

## Open Questions

1. **Partial acceptance**: Can the orchestrator accept a subset of proposed
   changes, such as accepting `add_node` but rejecting `remove_edge`?

   Proposal: yes, with explicit `applied_changes` in the acceptance event. This
   makes the harness more useful without adding complexity.

2. **Chained mutations**: What happens when a mutation proposal depends on a
   previously-proposed but not-yet-accepted mutation?

   Proposal: reject with `mutation_dependency_pending`. Keep the dependency
   chain linear until temporal replay can handle branching.

3. **Mutation from orchestrator**: Can the orchestrator itself generate mutation
   proposals, not just approve or deny?

   Proposal: keep the mutability right symmetric. The orchestrator can propose
   to itself and the same acceptance flow applies. This is useful for
   orchestrator-initiated replanning.

4. **Mutually exclusive mutations**: Two workers propose incompatible structural
   changes simultaneously.

   Proposal: gatekeeper detects conflict, marks both proposals as
   `conflict_pending`, and requires the orchestrator to accept one and reject
   the other.

5. **Node versioning**: When a node is superseded and re-executed, does it need
   a separate node identity?

   Proposal: yes. The old assignment retains its original `node_id`; the
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
