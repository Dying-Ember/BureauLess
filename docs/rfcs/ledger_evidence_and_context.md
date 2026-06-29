# RFC: Ledger Evidence And Progressive Context

## Status

**Accepted design; implementation pending in Milestone 3.** Canonical rules are
promoted into
[`docs/protocol/harness_protocol.md`](../protocol/harness_protocol.md) and
[`docs/architecture/context_economy.md`](../architecture/context_economy.md).
This RFC remains as decision history while implementation is tracked in
[`docs/tasks/runtime_harness_milestone_3_tasklist.md`](../tasks/runtime_harness_milestone_3_tasklist.md).

## Problem

External agent runtimes increasingly expose detailed traces: model messages,
tool calls, command output, file edits, failures, usage, and native transcripts.
Those traces overlap with the ledger only superficially. Treating them as
canonical mission state would create several problems:

- Every runtime emits a different trace format.
- Full traces are too large and too private to broadcast by default.
- A trace proves that an operation was attempted, not that its claimed effect
  still exists in the workspace.
- Re-summarizing every trace creates coordination work proportional to tool
  calls rather than useful node outcomes.
- Later workers need current accepted facts, not every historical action.

At the opposite extreme, a ledger that records only `completed` or `failed`
cannot provide enough context for a fresh worker to continue safely. BureauLess
needs a boundary that preserves evidence without turning evidence management
into the dominant workload.

## North Star

> Preserve complete evidence, commit the minimum sufficient facts, distribute
> context on demand, and use observed outcomes to improve context policy.

The ledger is not a compressed transcript. It is the durable record of accepted
mission-relevant state transitions. A fact belongs in the ledger when removing
it could cause a later worker to take an invalid action, repeat material work,
violate a constraint, or make replay unable to explain the mission state.

## Layered Model

```text
workspace and external state
  -> independently observed pre/post state
agent-native trace + immutable artifacts
  -> node outcome proposal
harness validation + risk-proportional review
  -> accepted ledger events
replay and context compiler
  -> role- and assignment-specific context capsule
```

### Evidence Store

The evidence store preserves native traces, diffs, logs, reports, and other
large immutable artifacts. Evidence is content-addressed and referenced from
protocol records. It is available for audit or targeted disclosure, but it is
not read during normal replay and is not broadcast by default.

Agent adapters normalize only the session boundary. BureauLess does not require
them to normalize every internal tool call.

### Node Outcome

A node outcome is a compact, structured proposal describing one assignment
attempt at the node boundary. It combines deterministic workspace observations
with worker-proposed semantic findings. It is produced for successful, failed,
timed-out, cancelled, and partial attempts.

```yaml
outcome_id: outcome-017
run_id: run-017
mission_id: optimize-worker-lifecycle
workflow_id: workflow-001
node_id: implement
assignment_id: assign-017
session_id: session-017
status: succeeded
pre_state_ref: git-tree:abc123
post_state_ref: git-tree:def456
observed_delta:
  modified_files:
    - src/bureauless/runtime/replay.py
  created_artifact_refs:
    - artifact-patch-017
  external_effects: []
verification:
  status: passed
  evidence_refs:
    - artifact-test-report-017
proposed_findings:
  - finding_id: finding-017
    content: Superseded assignment events no longer satisfy downstream gates.
risks:
  - risk_id: risk-017
    content: Temporal replay remains unsupported.
open_questions: []
unknowns: []
trace_ref: artifact-trace-017
```

The harness should fill deterministic fields such as state references, changed
paths, hashes, exit status, and verification receipts. The worker may propose
semantic findings, risks, and questions, but cannot make them canonical.

### Acceptance Decision

Validation classifies outcome content instead of accepting the worker response
as one indivisible claim:

- `observation`: machine-verifiable state, hash, exit, or verification fact.
- `finding`: a semantic claim that requires evidence and may require review.
- `decision`: an orchestrator, policy, reviewer, or human disposition.
- `unknown`: information that could not be established and must not be guessed.

Low-risk deterministic observations may be accepted automatically by the
harness. Semantic, conflicting, externally visible, or high-risk claims use the
existing review and permission model. Accepted events record the actor and the
rule or evidence used.

One decision event handles full acceptance, partial acceptance, and rejection
without copying the full outcome payload into the ledger:

```yaml
event_id: event-outcome-decision-017
event_type: node_outcome_decided
source_outcome_id: outcome-017
outcome_ref: artifact-outcome-017
actor: harness
disposition: partially_accepted
validation_rule: low_risk_workspace_delta_v1
accepted:
  observation_ids:
    - observation-workspace-delta-017
    - observation-tests-passed-017
  finding_ids:
    - finding-017
  risk_ids:
    - risk-017
rejected_claim_ids: []
evidence_refs:
  - artifact-patch-017
  - artifact-test-report-017
```

Effective workflow completion events reference this decision event. A worker's
asserted emitted event is never effective merely because it appears in a native
trace or result proposal.

### Ledger

The ledger records accepted state transitions and their provenance. It keeps
large evidence out of line and references immutable artifacts instead. Current
findings, risks, decisions, and open questions are projections over accepted
events rather than independent sources of truth.

If a current-state projection is persisted in the ledger file, it records the
last event included in that projection. A missing or mismatched cursor makes the
projection a rebuildable cache, never an alternative authority:

```yaml
projection:
  through_event_id: event-outcome-decision-017
  generated_at: "2026-06-29T00:00:00Z"
```

Corrections append supersession or invalidation events. They do not rewrite
accepted history.

### Context Capsule

The context compiler builds a bounded view for one assignment. It selects from
accepted ledger state by explicit relationships first:

- mission constraints and current workspace revision;
- direct and transitive workflow dependencies;
- required gates and permissions;
- active facts, risks, and questions scoped to the node;
- shared paths and artifact relationships;
- relevant accepted decisions.

It excludes unrelated branches, resolved risks, superseded history, full tool
logs, raw private output, and large artifact bodies by default.

```yaml
context_capsule_id: context-022
policy_version: context-v1
mission_id: optimize-worker-lifecycle
assignment_id: assign-022
workspace_ref: git-tree:def456
included_fact_ids:
  - finding-017
included_decision_ids:
  - decision-008
active_risk_ids:
  - risk-017
artifact_refs:
  - artifact-patch-017
excluded:
  unrelated_branch_history: not_in_dependency_scope
  raw_tool_logs: disclosure_level_too_low
```

The complete ledger may grow over time; the context delivered to a worker must
remain bounded.

## Progressive Disclosure

Context is disclosed in layers:

1. Assignment, constraints, accepted facts, gates, and current state.
2. Concise rationale, provenance, relevant diffs, and verification summaries.
3. Selected artifact bodies or trace excerpts.
4. Full native trace only for audit, conflict resolution, or exceptional review.

A worker requests more context with a scoped explanation:

```yaml
context_request_id: context-request-004
assignment_id: assign-022
missing_information: The failing verification details are not in the capsule.
requested_refs:
  - artifact-test-report-017
expected_value: Determine whether the failure is in the patch or environment.
```

The context broker checks relevance, visibility, and token budget before
returning a targeted context packet. It does not rebroadcast an entire ledger
layer. Missing evidence is returned as `unavailable`; the worker must not infer
it.

Context requests are not canonical mission facts by default. They are session
telemetry unless they reveal a blocker, risk, or decision that affects mission
state.

## Feedback Loop

Every compiled capsule records its policy version, included references, token
estimate, and disclosure level. Session metrics connect that delivery to later
requests and externally observable outcomes.

```yaml
context_delivery:
  policy_version: context-v1
  capsule_tokens: 1800
  included_fact_ids: []
  included_artifact_refs: []
  disclosure_level: 1
context_requests:
  - reason: missing_test_failure_details
    requested_refs:
      - artifact-test-report-017
    granted: true
    added_tokens: 620
outcome:
  first_pass_success: true
  rework_required: false
  review_status: approved
context_fit:
  classification: under_provisioned
  reason: Required evidence was requested and the task succeeded after disclosure.
```

Initial context-fit classifications are:

- `under_provisioned`
- `well_provisioned`
- `over_provisioned`
- `mis_scoped`
- `insufficient_evidence`

Scoring should prefer observable signals: context requests, missing-context
blocks, first-pass success, review rejection, rework, and repeated artifact
requests. It must not claim to know whether a model internally used a prompt
fragment.

Telemetry is aggregated by role, task type, risk level, model, and policy
version. A single run never changes policy automatically. Repeated evidence
produces a versioned policy recommendation; accepting that recommendation is a
reviewable decision.

## State And Concurrency Rules

- Outcome facts are scoped to their observed workspace revision and workflow.
- A successful trace does not establish a post-state without an independent
  observation or receipt.
- If the accepted workspace has moved past an outcome's `pre_state_ref`, the
  outcome becomes `stale` or `needs_review`; it is not silently applied.
- A failed or interrupted run must report partial effects and cleanup needs.
- External effects require explicit receipts when observable and `unknown`
  markers when not.
- Superseded outcomes remain available for audit but do not satisfy current
  gates.

## Bureaucracy Budget

This design is valid only while it reduces coordination cost:

- Ledger work scales with node outcomes, not internal tool calls.
- Normal replay never reads native transcripts.
- Low-risk nodes do not require an extra summarizer or reviewer by default.
- Large values spill into immutable artifacts and remain references in events.
- The same evidence is verified once and subsequently trusted by content hash
  and acceptance provenance.
- Context delivery remains inside the mission coordination budget defined in
  `context_economy.md`.
- No semantic search, vector store, or knowledge graph is required until
  measured runs show that explicit dependency and scope rules are insufficient.

## Cold-Start Acceptance Test

A fresh worker with no prior conversation should be able to continue a node
using only:

```text
mission + assignment + context capsule + referenced artifacts
```

If it routinely needs full transcripts, the accepted facts or context policy
are inadequate. If it routinely receives large irrelevant capsules, the policy
is over-provisioned. Both failures must be visible in telemetry.

## Non-Goals

This RFC does not propose:

- storing every tool call in the ledger;
- normalizing all provider-native trace formats;
- broadcasting the full ledger to every worker;
- using an LLM for hard gates, replay, or deterministic state extraction;
- automatically changing context policy after individual runs;
- implementing temporal replay or a general-purpose knowledge graph;
- treating private chain-of-thought as required protocol evidence.

## Accepted Decisions

1. Native traces remain immutable evidence artifacts, not canonical runtime
   state.
2. Node outcomes are the normalized control boundary, including failed and
   partial runs.
3. Accepted ledger events contain minimum sufficient facts and evidence refs.
4. Current ledger summaries and worker broadcasts are derived projections.
5. Context is compiled per assignment and progressively disclosed by reference.
6. Context telemetry is high-volume session data; only accepted policy changes
   become ledger decisions.
7. Context policy remains deterministic and versioned until measured evidence
   justifies a more adaptive mechanism.
8. Cold-start continuation and coordination overhead are explicit acceptance
   tests.

## Related Documents

- [`docs/protocol/harness_protocol.md`](../protocol/harness_protocol.md)
- [`docs/architecture/context_economy.md`](../architecture/context_economy.md)
- [`docs/roadmap/development_roadmap.md`](../roadmap/development_roadmap.md)
- [`docs/tasks/runtime_harness_milestone_3_tasklist.md`](../tasks/runtime_harness_milestone_3_tasklist.md)
