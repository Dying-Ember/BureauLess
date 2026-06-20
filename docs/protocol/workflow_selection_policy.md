# Workflow Selection Policy

This policy keeps BureauLess from turning ordinary tasks into coordination
projects. The default is always the simplest executable workflow.

## Default

```yaml
policy_version: "0.1"
default_mode: single_agent
allowed_modes:
  - single_agent
  - single_agent_with_review
  - small_dag
  - parallel_swarm
  - stop_and_ask_human
```

The orchestrator may propose a more complex mode only when the routing decision
records the trigger, expected benefit, and rejected simpler alternative.

## Upgrade Rules

```yaml
upgrade_to_single_agent_with_review_if:
  any_of:
    - risk_level >= medium
    - touches_protected_files == true
    - external_side_effect == true
    - commit_or_merge_action == true
    - destructive_action_possible == true

upgrade_to_small_dag_if:
  all_of:
    - independent_subtasks >= 3
    - shared_context_tokens < estimated_parallel_savings_tokens
    - merge_complexity != high
  any_of:
    - specialist_roles_reduce_risk == true
    - context_isolation_reduces_total_tokens == true
    - staged_review_required == true

upgrade_to_parallel_swarm_if:
  all_of:
    - independent_subtasks >= 4
    - shared_file_overlap != high
    - budget_confidence != low
    - coordination_ratio_prediction <= 0.25
    - merge_complexity == low
    - expected_wall_clock_savings == material

stop_and_ask_human_if:
  any_of:
    - user_intent_unclear_and_side_effectful == true
    - required_permission_missing == true
    - policy_conflict_detected == true
    - budget_hard_limit_would_be_exceeded == true
```

## Rejection Rules

```yaml
reject_small_dag_if:
  any_of:
    - node_count <= 2 and risk_level == low
    - coordination_ratio_prediction > 0.25
    - merge_complexity == high
    - shared_context_tokens >= estimated_parallel_savings_tokens

reject_parallel_swarm_if:
  any_of:
    - shared_file_overlap == high
    - budget_confidence == low
    - coordination_ratio_prediction > 0.25
    - merge_complexity != low
    - expected_wall_clock_savings != material
```

## Routing Decision Requirements

Every routing decision must include:

```yaml
decision_type: routing_decision
selected_mode: single_agent
selection_policy_version: "0.1"
triggered_rules: []
rejected_modes:
  - mode: small_dag
    rejected_because: >
      The task has one coherent execution path and no material parallel savings.
estimated_coordination_ratio: 0.0
budget_confidence: high
```

The harness should reject a complex workflow proposal when its routing decision
does not cite this policy or cannot explain why the simpler mode is insufficient.

