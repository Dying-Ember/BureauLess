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

Every public finding needs provenance:

```yaml
finding_id: finding-001
content: >
  Worker cancellation currently lacks a cooperative default path.
source_event: event-012
source_agent: inventory-agent
artifact_refs:
  - artifacts/inventory-report.md
accepted_by: orchestrator
created_at: "2026-06-19T00:00:00Z"
```

## Workflow

A workflow is an executable coordination proposal. It must compile before any
assignment is dispatched.

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
broadcast_policy:
  default: filtered_delta
budget_policy:
  max_coordination_ratio: 0.25
```

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
  - artifacts/patch.diff
verification:
  commands:
    - pytest -q
  status: passed
notes: >
  Implementation is ready for review.
```

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
  - artifacts/patch.diff
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
  - artifacts/inventory-summary.md
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
- Terminal condition exists.
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
rejected.

