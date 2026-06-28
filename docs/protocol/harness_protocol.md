# Harness Protocol

This document defines the machine protocol that keeps orchestrated agent work
safe, auditable, and recoverable.

All persisted protocol artifacts use YAML.

## Control Model

The harness is the enforcement layer. It does not rely on prompts for safety.

The harness owns:

- Workflow compilation.
- Role permissions.
- Event validity.
- Gate enforcement.
- Ledger writes.
- Provenance checks.
- Budget checks.
- Broadcast filtering.
- Replay and recovery.

Related protocol files define hardening rules that the harness should enforce
as implementation catches up:

- [`workflow_selection_policy.md`](workflow_selection_policy.md)

The orchestrator may approve ledger updates, but the harness validates and
writes canonical ledger state.

## Runtime Boundary

The v1 harness wraps external agent runtimes. It does not implement the
internal coding-agent loop for model turns, tool calls, context compaction, or
token-segment tracing.

The v1 control grain is:

- Assignment.
- Agent runtime session.
- Result proposal.
- Artifact integrity.
- Review and gate decision.
- Ledger event.
- Session-level outcome metrics.

Native agent logs may be preserved as artifacts, but they are not the canonical
runtime state. The harness uses deterministic evidence such as result proposals,
artifacts, diffs, verification results, approvals, and ledger events.

## Mission

A mission captures the user's goal, constraints, budget, and allowed execution
modes.

```yaml
mission_id: optimize-worker-lifecycle
goal: >
  Improve worker lifecycle behavior while preserving UI responsiveness.
created_at: "2026-06-19T00:00:00Z"
status: planning
default_mode: single_agent
allowed_modes:
  - single_agent
  - single_agent_with_review
  - small_dag
  - parallel_swarm
  - stop_and_ask_human
budget:
  max_total_tokens: 300000
  max_coordination_ratio: 0.25
  max_usd: 10.00
models:
  gpt-5:
    role: large_reasoning
  gpt-5-mini:
    role: bounded_execution
human_gate:
  required_for:
    - high_risk
    - commit_to_main
```

## Ledger

The ledger is canonical mission state. Raw worker reports do not automatically
become ledger facts.

```yaml
mission_id: optimize-worker-lifecycle
ledger_version: 1
current_goal: >
  Improve worker lifecycle behavior while preserving UI responsiveness.
current_plan_ref: workflows/workflow-001.yaml
public_findings: []
decisions: []
risks: []
artifacts: []
broadcasts: []
open_questions: []
event_log: []
```

Accepted artifacts should use immutable artifact records.

Every public finding needs provenance:

```yaml
finding_id: finding-001
content: >
  Worker cancellation currently lacks a cooperative default path.
source_event: event-012
source_agent: inventory-agent
artifact_refs:
  - artifact_id: artifact-001
    path: artifacts/inventory-report.md
    sha256: "6f5902ac237024bdd0c176cb93063dc4..."
accepted_by: orchestrator
created_at: "2026-06-19T00:00:00Z"
```

## Artifact Integrity

Artifacts are immutable evidence objects. Ledger records should refer to
artifact identifiers, not mutable paths alone.

```yaml
artifact_id: artifact-001
path: artifacts/inventory-report.md
sha256: "6f5902ac237024bdd0c176cb93063dc4..."
created_by: inventory-agent
source_event: event-012
created_at: "2026-06-20T00:00:00Z"
mime_type: text/markdown
size_bytes: 12431
mutable: false
supersedes: null
invalidated_by: null
```

`path` is a retrieval hint. `artifact_id` plus `sha256` is the durable identity.
String-only references are acceptable only for drafts that have not entered the
canonical ledger.

Rules:

- An accepted artifact must not be modified in place.
- A correction creates a new artifact with `supersedes` pointing to the old one.
- A bad artifact is marked by an `artifact_invalidated` event, not overwritten.
- Replay must verify the current file hash against the recorded `sha256`.
- Missing artifacts make provenance incomplete; they do not silently become
  trusted facts.

## Workflow

A workflow is an executable coordination proposal. It must compile before any
assignment is dispatched.

Workflows must declare `terminal_events`. A workflow is complete when the
runtime observes those events and all required gates for them are satisfied.

```yaml
workflow_id: workflow-001
mission_id: optimize-worker-lifecycle
proposed_by: orchestrator
status: proposed
mode: small_dag
reason: >
  The task has one low-risk inventory phase and one high-risk lifecycle phase.
roles:
  coder:
    can_emit:
      - patch_ready
      - implementation_blocked
  reviewer:
    can_consume:
      - patch_ready
    can_emit:
      - review_approved
      - changes_requested
  committer:
    can_consume:
      - patch_ready
      - review_approved
    can_emit:
      - commit_created
events:
  patch_ready:
    producer_roles:
      - coder
  review_approved:
    producer_roles:
      - reviewer
  commit_created:
    producer_roles:
      - committer
nodes:
  - id: implement
    role: coder
    waits_for: []
    emits:
      - patch_ready
  - id: review
    role: reviewer
    waits_for:
      all_of:
        - patch_ready
    emits:
      - review_approved
  - id: commit
    role: committer
    waits_for:
      all_of:
        - patch_ready
        - review_approved
    emits:
      - commit_created
gates:
  - id: commit_gate
    node_id: commit
    requires:
      all_of:
        - patch_ready
        - review_approved
terminal_events:
  - commit_created
broadcast_policy:
  default: filtered_delta
budget_policy:
  max_coordination_ratio: 0.25
  price_snapshot: price-snapshot-2026-06-20
```

Workflow mode selection must follow
[`workflow_selection_policy.md`](workflow_selection_policy.md). A complex
workflow without a routing decision and selection-policy rationale should be
rejected.

## Assignment

An assignment is the bounded task packet sent to a worker.

```yaml
assignment_id: assign-001
workflow_id: workflow-001
node_id: implement
role: coder
model: gpt-5-mini
goal: >
  Implement the bounded change described by the workflow node.
visible_context:
  mission_summary: >
    Improve worker lifecycle behavior while preserving UI responsiveness.
  broadcast_refs: []
  artifact_refs: []
allowed_tools: []
forbidden_actions:
  - commit
  - update_canonical_ledger
expected_events:
  - patch_ready
turn_report_policy:
  after_each_tool_call: true
  max_report_tokens: 600
```

Assignments must be interpreted under the
[Protocol Invariants](#protocol-invariants). Expanding scope, requesting
broader context without rationale, creating new agents, choosing a larger
model without approval, or bypassing forbidden actions should be treated as
validation failures or review blockers rather than as harmless worker freedom.

## Turn Report

Workers submit turn reports after tool calls or bounded work intervals.

```yaml
report_id: report-001
assignment_id: assign-001
agent_id: inventory-agent
status: in_progress
tool_calls_since_last_report: 1
summary: >
  Inspected worker lifecycle entry points and identified the default stop path.
new_findings: []
artifact_refs: []
blockers: []
suggested_ledger_updates: []
token_usage:
  input_tokens: 0
  output_tokens: 0
```

## Task Result

Workers submit a task result when an assignment is complete.

```yaml
result_id: result-001
assignment_id: assign-001
agent_id: coder-agent
status: passed
emitted_events:
  - patch_ready
artifact_refs:
  - artifact_id: artifact-002
    path: artifacts/patch.diff
    sha256: "9b2cf535f27731c974343645a3985328..."
verification:
  commands:
    - pytest -q
  status: passed
notes: >
  Implementation is ready for review.
```

Task results are proposals. They do not become public ledger facts until the
harness validates role permissions, expected events, artifact integrity,
forbidden actions, and any required review gates.

A result that discovers a structural workflow gap uses
`status: completed_with_proposal` and lists proposal artifact IDs in
`mutation_proposal_refs`. Each reference must resolve to an immutable YAML
artifact in the same result. `completed` and `blocked` results cannot carry
mutation proposal refs, and blocked results cannot emit completion events.
Importing this result records only `result_submitted`; it does not append a
mutation event or alter the workflow.

Task result validation must also enforce the
[Protocol Invariants](#protocol-invariants). A result that reflects scope
expansion, unapproved model escalation, unsupported public findings, or other
invariant violations should be rejected or held for explicit review.

## Workflow Mutation Proposal

A worker or orchestrator may report that the accepted workflow is structurally
incomplete by producing a `workflow_mutation` proposal. A proposal is inert: it
cannot update the workflow, append ledger events, or create assignments.

```yaml
proposal_id: mutation-001
proposal_type: workflow_mutation
workflow_id: workflow-001
source:
  assignment_id: assign-001
  session_id: session-001
  actor: worker
reason: discovered_missing_dependency
rationale: A verification step is required before review.
proposed_changes:
  add_nodes:
    - id: verify
      role: reviewer
      waits_for:
        all_of:
          - implement.patch_ready
      emits:
        - verification_passed
  add_edges:
    - from_node: verify
      to_node: commit
      event: verification_passed
  remove_edges: []
  supersede_assignments:
    - assign-review-001
evidence_refs:
  - artifact-impact-report
requires_approval: orchestrator
```

An edge mutation names `from_node`, `to_node`, and `event`; it represents the
qualified dependency `from_node.event` on the target node. Bare graph edges are
not valid because workflow nodes may emit multiple events.

The proposal validator returns structured errors and rejects unknown fields,
empty changes, missing evidence, node removal, ledger rewriting, canonical
assignment creation, duplicate changes, self-edges, and an edge being both
added and removed. Applying accepted proposals is defined separately by the
mutation decision event protocol.

Mutation decisions are append-only ledger events:

```yaml
event_id: event-mutation-accepted-001
event_type: workflow_mutation_accepted
source_event_id: event-mutation-001
actor: orchestrator
applied_changes:
  add_nodes: []
  add_edges: []
  remove_edges: []
  supersede_assignments:
    - assign-review-001
```

`workflow_mutation_accepted` and `workflow_mutation_rejected` must reference an
existing `workflow_mutation_proposed` event. Only an orchestrator or human can
record the decision, a proposal can be decided only once, and accepted changes
must be a non-empty subset of the source proposal.

While a proposal is pending, replay derives its explicitly affected nodes from
edge targets and superseded assignments, then includes their downstream
closure. Gatekeeper blocks those nodes with `mutation_pending` while leaving
independent branches runnable. Rejecting the proposal removes the pending
block; acceptance proceeds through current-workflow materialization.

Current workflow materialization is deterministic and non-mutating:

```text
initial_workflow + accepted mutation events -> current_workflow
```

Only each acceptance event's `applied_changes` are used, in ledger order.
Rejected proposals have no structural effect. Every intermediate workflow must
compile and remain acyclic; unknown nodes or events, duplicate or missing
edges, and invalid role/event contracts reject materialization without changing
the initial workflow.

Assignment impact evaluation compares the node contract and complete upstream
dependency closure before and after an accepted mutation. A changed contract,
changed closure, or explicit supersession is `affected`; an unchanged execution
context is `unaffected`; missing or conflicting assignment-to-node provenance
is `needs_review`.

Gatekeeper exposes `needs_review` for assignments whose validity cannot be
established after an accepted mutation. When a required event exists only from
a superseded assignment, the blocked reason is `superseded` rather than a
generic missing-event reason. Mutation-added nodes use the materialized current
workflow for assignment export and result import.

Affected assignments are invalidated by append-only `assignment_superseded`
events linked to the accepted mutation event. Their original sessions, results,
and emitted events remain in history, but replay excludes events emitted by a
superseded assignment when evaluating node completion, gates, and terminal
conditions.

Current-state replay always accepts the initial workflow and performs:

```text
initial_workflow + accepted_mutations -> current_workflow
current_workflow + ledger_events      -> current derived state
```

This milestone does not expose historical workflow snapshots or arbitrary
time-based queries.

## Agent Runtime

An agent runtime is an external executor such as Codex CLI, Claude Code, or
opencode. The harness treats it as a bounded worker process, not as a trusted
source of canonical mission truth.

Agent adapters must declare and, where possible, verify their control surface:

```yaml
agent_id: codex-cli
kind: local_agent_cli
non_interactive: true
model_override: cli_arg
provider_override: runtime_config
auth_isolation: env_secret
config_isolation: runtime_override
working_directory: explicit
session_persistence: disabled
output_stream: jsonl
cancellation: process_kill
metrics_capability:
  wall_time: required
  final_status: required
  changed_files: required
  token_usage: optional
  cost_usage: optional
```

Model provider configuration is a property of an agent session. It is not the
top-level execution interface for coding tasks.

## Agent Doctor

Before automatic dispatch, the runtime should run an agent doctor check.

```yaml
agent_id: codex-cli
status: usable
control_level: high
model_override: verified
provider_override: verified
config_isolation: runtime_override
auth_isolation: env_secret
session_persistence: disabled
warnings: []
```

Agents with failed doctor checks must not receive automatic assignments. Agents
with partial control may still be used manually or behind stricter review gates.

## Agent Session

An agent session binds one assignment to one external runtime attempt.

```yaml
session_id: session-001
assignment_id: assign-001
agent_id: codex-cli
target_model: gpt-5-mini
target_provider: bureauless-proxy
workdir: .bureauless/worktrees/assign-001
started_at: "2026-06-20T00:00:00Z"
finished_at: "2026-06-20T00:03:04Z"
status: completed
exit:
  code: 0
  reason: completed
native_log_refs:
  - artifact_id: artifact-native-001
    path: artifacts/native/codex-session.jsonl
    sha256: "8d8d0a..."
```

Session records may produce result proposals, but sessions must not write the
canonical ledger directly.

## Outcome Metrics

The v1 metrics target is assignment/session-level accounting, not root-cause
analysis of every internal tool call.

```yaml
outcome_metrics:
  wall_time_ms: 184000
  input_tokens: 123456
  output_tokens: 7890
  total_tokens: 131346
  cost_usd: 0.42
  usage_source: adapter_reported
  usage_confidence: medium
  changed_files_count: 4
  patch_bytes: 18231
  verification_status: passed
  review_status: approved
```

If token or cost data is unavailable, the runtime should record the missing data
explicitly with `usage_confidence: none` rather than inventing a precise value.

## Event

Events are append-only facts about execution.

```yaml
event_id: event-001
mission_id: optimize-worker-lifecycle
workflow_id: workflow-001
assignment_id: assign-001
event_type: patch_ready
role: coder
agent_id: coder-agent
created_at: "2026-06-19T00:00:00Z"
artifact_refs:
  - artifact_id: artifact-002
    path: artifacts/patch.diff
    sha256: "9b2cf535f27731c974343645a3985328..."
provenance:
  source_report: result-001
  accepted_by: harness
```

## Gate

Gates determine whether a node can run.

```yaml
gate_id: commit_gate
node_id: commit
requires:
  all_of:
    - patch_ready
    - review_approved
```

Supported gate combinators:

- `all_of`
- `any_of`
- `human_approved`
- `orchestrator_approved`
- `budget_approved`

## Permission Levels

Human approval should be reserved for irreversible or externally visible
boundaries. The harness should prefer deterministic gates and isolated
workspaces for lower-risk work.

| Level | Capability | Default Gate |
| --- | --- | --- |
| L0 | Read, inventory, summarize, inspect repository state | No human gate |
| L1 | Write inside an isolated worktree or scratch artifact area | Harness isolation |
| L2 | Run tests or validation inside the isolated workspace | Harness policy |
| L3 | Produce `patch_ready` or comparable reviewable artifacts | Reviewer or orchestrator gate |
| L4 | Commit, merge, push, deploy, delete, or affect external systems | Human gate |

This model prevents the system from choosing between two bad extremes:
prompting a human for every tool call or allowing full autonomous mutation of
canonical state.

## Failure Lifecycle

The runtime must model unhappy paths as first-class events. A mission that can
only represent successful assignment completion is not replayable enough for
real work.

```yaml
failure_lifecycle_events:
  - worker_timeout
  - assignment_cancelled
  - assignment_retry_requested
  - assignment_superseded
  - budget_soft_limit_reached
  - budget_hard_limit_reached
  - artifact_invalidated
  - gate_expired
  - tool_call_failed
  - partial_result_submitted
```

Timeouts, retries, cancellations, and supersessions block downstream gates until
the orchestrator records what replaced or ended the assignment.

```yaml
event_id: event-022
event_type: assignment_retry_requested
assignment_id: assign-004
retry_of: assign-003
reason: >
  The previous worker produced a partial result but missed required
  verification.
retry_policy:
  max_attempts: 2
  strategy: same_model_then_escalate
  preserve_artifacts:
    - artifact-007
```

Budget limits are also events:

```yaml
event_id: event-025
event_type: budget_soft_limit_reached
mission_id: optimize-worker-lifecycle
usage:
  actual_tokens: 240000
  max_total_tokens: 300000
runtime_action: require_replan_before_new_assignments
```

Soft limits may allow current assignments to finish. Hard limits block new
assignments and advisor calls until human approval or budget revision.

Assignment terminality must be explicit in replay:

- `patch_ready`, `review_approved`, `commit_created`, and other accepted
  workflow-completion events terminate the producing assignment as completed.
- `assignment_cancelled`, `assignment_superseded`, `worker_timeout`, and
  `budget_hard_limit_reached` terminate the affected assignment as non-completed.
- `assignment_retry_requested`, `budget_soft_limit_reached`,
  `tool_call_failed`, and `partial_result_submitted` are non-terminal on their
  own; they require a later completion, cancellation, timeout, or supersession
  event to close the assignment.

## Broadcast View

Workers receive filtered broadcast views, not the full ledger.

```yaml
broadcast_view_id: view-001
mission_id: optimize-worker-lifecycle
role: coder
agent_id: coder-agent
included_findings:
  - finding-001
included_decisions:
  - decision-003
artifact_refs:
  - artifact_id: artifact-003
    path: artifacts/inventory-summary.md
    sha256: "0b4c2fda8f8f0f6f2d6f0b84d7a1c9e0..."
excluded_reason:
  raw_tool_logs: too_large
  reviewer_private_notes: not_visible_to_role
```

## Workflow Compiler

The compiler must reject workflows that violate hard rules.

It checks:

- Roles referenced by nodes exist.
- Events referenced by nodes and gates exist.
- Roles may emit only allowed events.
- Roles may consume only allowed events.
- `waits_for` conditions are satisfiable.
- Join gates have all required upstream events.
- Committer-like roles cannot run without review and patch events.
- Terminal events exist.
- Obvious deadlocks are rejected.

Compiler output:

```yaml
status: rejected
errors:
  - code: missing_review_gate
    node_id: commit
    message: >
      Commit node requires patch_ready and review_approved before it can run.
```

## Gatekeeper

The gatekeeper decides whether a node is runnable at a specific moment.

It checks:

- Required events exist.
- Required reviews are approved.
- Required human gates are approved.
- Budget gates are satisfied.
- The assigned role has permission.

The gatekeeper must not ask a model to decide whether a hard gate is satisfied.

## Replay

Mission state should be recoverable from:

- Mission YAML.
- Workflow YAML.
- Assignment YAML.
- Append-only ledger events.
- Accepted ledger updates.

Replay should explain why each node became runnable, blocked, completed, or
rejected. It should also explain cancellation, retry, supersession, artifact
invalidation, and budget-limit transitions.

## Protocol Invariants

These rules should remain true across prompts, workflow compiler checks,
gatekeeper decisions, and replay.

Worker invariants:

- A worker must not expand its assignment scope.
- A worker must not request broader context unless it explains expected savings
  or risk reduction.
- A worker must not create new agents.
- A worker must not convert private hypotheses into public findings.
- A worker must not choose a larger model without model escalation approval.
- A worker must not update the canonical ledger.
- A worker must not satisfy gates by assertion; gates require events.
- A worker must not overwrite accepted artifacts.
- A worker must not perform forbidden actions listed in its assignment.

Orchestrator invariants:

- The orchestrator owns coordination, not execution.
- The orchestrator must prefer `single_agent` unless a policy rule justifies
  escalation.
- The orchestrator must not bypass compiler or gatekeeper decisions.
- The orchestrator must not accept public facts without provenance.
- The orchestrator must not broadcast raw private worker context by default.
- The orchestrator must not summon advisors without advisor policy approval.

Harness invariants:

- The harness is the enforcement layer.
- Canonical ledger writes are validated by deterministic rules.
- Accepted events are append-only.
- Accepted artifacts are immutable.
- Gate satisfaction is derived from accepted events and approvals.
- Budget checks use a recorded price snapshot or explicitly mark price data as
  unknown.

Human override is allowed only when it is explicit, persisted, and replayable.
