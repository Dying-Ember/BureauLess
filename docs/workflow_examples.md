# Workflow Examples

These examples are reference patterns for future workflow compiler tests and
orchestrator decisions.

All examples are YAML-only.

## Single Agent

Use when one bounded worker can execute the task and the orchestrator can review
the result afterward.

```yaml
workflow_id: single-agent-001
mode: single_agent
reason: >
  The task is bounded, low risk, and has no useful parallel branches.
roles:
  worker:
    can_emit:
      - task_complete
events:
  task_complete:
    producer_roles:
      - worker
nodes:
  - id: execute
    role: worker
    waits_for: []
    emits:
      - task_complete
gates: []
terminal_events:
  - task_complete
broadcast_policy:
  default: filtered_delta
```

## Single Agent With Review

Use when one worker can do the task, but the result needs orchestrator review.

```yaml
workflow_id: single-agent-review-001
mode: single_agent_with_review
roles:
  worker:
    can_emit:
      - task_complete
  control_reviewer:
    can_consume:
      - task_complete
    can_emit:
      - orchestrator_approved
events:
  task_complete:
    producer_roles:
      - worker
  orchestrator_approved:
    producer_roles:
      - control_reviewer
nodes:
  - id: execute
    role: worker
    emits:
      - task_complete
  - id: review
    role: control_reviewer
    waits_for:
      all_of:
        - task_complete
    emits:
      - orchestrator_approved
terminal_events:
  - orchestrator_approved
```

## Coder Reviewer Committer

Use when a patch must be produced, reviewed, and committed only after approval.

```yaml
workflow_id: coder-reviewer-committer-001
mode: small_dag
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
```

## Parallel Inventory

Use when discovery can be split into independent bounded branches.

```yaml
workflow_id: parallel-inventory-001
mode: parallel_swarm
roles:
  docs_inventory:
    can_emit:
      - inventory_complete
  tests_inventory:
    can_emit:
      - inventory_complete
  code_inventory:
    can_emit:
      - inventory_complete
  ledger_acceptor:
    can_consume:
      - inventory_complete
    can_emit:
      - ledger_updated
events:
  inventory_complete:
    producer_roles:
      - docs_inventory
      - tests_inventory
      - code_inventory
  ledger_updated:
    producer_roles:
      - ledger_acceptor
nodes:
  - id: docs_inventory
    role: docs_inventory
    emits:
      - inventory_complete
  - id: tests_inventory
    role: tests_inventory
    emits:
      - inventory_complete
  - id: code_inventory
    role: code_inventory
    emits:
      - inventory_complete
  - id: merge_inventory
    role: ledger_acceptor
    waits_for:
      all_of:
        - docs_inventory.inventory_complete
        - tests_inventory.inventory_complete
        - code_inventory.inventory_complete
    emits:
      - ledger_updated
terminal_events:
  - ledger_updated
broadcast_policy:
  default: filtered_delta
```

## Advisor-Gated Swarm

Use when the orchestrator proposes a swarm, but policy requires a cost/risk
advisor before compilation.

```yaml
workflow_id: advisor-gated-swarm-001
mode: parallel_swarm
status: proposed
advisor_gate_decision:
  invoked: true
  advisor: cost_risk_analyst
  policy_version: "0.1"
  reason:
    - parallel_width >= 3
    - high_risk_node_count >= 1
  estimated_advisor_tokens: 3300
  estimated_savings_tokens: 9200
  confidence: low
  decision_basis: first_run_heuristic
advisor_result:
  verdict: revise
  recommended_changes:
    - run inventory before implementation swarm
    - replace full ledger broadcast with filtered_delta
    - move high-risk lifecycle task behind human gate
```

## Human Gate

Use when a workflow touches high-risk behavior, destructive operations, deploys,
or commits to protected branches.

```yaml
workflow_id: human-gate-001
mode: single_agent_with_review
roles:
  worker:
    can_emit:
      - high_risk_change_ready
  human_reviewer:
    can_consume:
      - high_risk_change_ready
    can_emit:
      - human_approved
events:
  high_risk_change_ready:
    producer_roles:
      - worker
  human_approved:
    producer_roles:
      - human_reviewer
nodes:
  - id: execute
    role: worker
    emits:
      - high_risk_change_ready
  - id: human_review
    role: human_reviewer
    waits_for:
      all_of:
        - high_risk_change_ready
    emits:
      - human_approved
terminal_events:
  - human_approved
```

## Stop And Ask Human

Use when the harness cannot validate the workflow, budget, permission, or
required safety gate.

```yaml
decision_type: routing_decision
selected_mode: stop_and_ask_human
reason: >
  The workflow proposes a commit action without a reviewer approval gate.
required_user_decision:
  - add reviewer gate
  - remove commit action
  - approve explicit bypass
```
