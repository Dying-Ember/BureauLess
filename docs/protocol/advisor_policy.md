# Advisor Policy

Advisor roles exist to help the orchestrator see the cost and risk consequences
of a proposed workflow. They are not part of the default hot path.

The policy is intentionally conservative: do not hire an advisor unless the
workflow shape suggests avoidable waste or coordination risk.

## Core Rule

```text
run_advisor iff expected_savings * confidence > advisor_expected_cost * safety_factor
```

Default:

```yaml
advisor_policy_version: "0.1"
safety_factor: 2.0
default: skip
```

The safety factor means an advisor should usually be invoked only when expected
savings are at least twice the expected advisor cost.

## First-Version Deterministic Triggers

Invoke an advisor if any of these are true:

- `node_count >= 5`
- `parallel_width >= 3`
- `high_risk_node_count >= 1`
- `large_model_node_count >= 2`
- `review_or_human_gate_count >= 2`
- `estimated_total_tokens >= 80000`
- `broadcast_policy == full_ledger`
- `touched_file_overlap == high`

Skip an advisor if all of these are true:

- `node_count <= 2`
- `risk_level == low`
- `no_parallel_branches == true`
- `no_commit_or_human_gate == true`

Tie-breaker:

```text
Prefer skip unless there is high risk, commit/merge, full_ledger broadcast, or missing price data.
```

## First Run Without Telemetry

The first run has no project history. Do not pretend to have exact ROI.

Use this principle:

```text
Only hire an advisor when the workflow shape itself suggests avoidable waste or coordination risk.
```

In the first run, the policy looks for common failure shapes, not subtle
optimization opportunities.

### Hard Triggers

- `parallel_width >= 3`
  Three or more branches often cause duplicate file reads, broadcast growth,
  join waiting, and merge conflicts.

- `high_risk_node_count >= 1` and `mode != single_agent_with_review`
  High-risk work needs review, human gates, or an explicit reason to proceed.

- `large_model_node_count >= 2`
  Multiple large-model nodes suggest possible model routing waste.

- `review_or_human_gate_count >= 2`
  Multiple gates can create queue blockage and over-conservative workflows.

- `broadcast_policy == full_ledger`
  Full ledger broadcast is treated as high risk by default.

- `estimated_context_fanout_tokens >= advisor_expected_tokens * 2`
  If duplicate context or broadcasts may cost twice the advisor budget, the
  advisor can be worth running.

- `commit_or_merge_action == true` and missing reviewer or approval gate
  Commit and merge actions need explicit safety gates.

- `unknown_model_prices == true` and workflow uses multiple models
  Missing price data makes budget reasoning non-auditable.

### Hard Skips

- `node_count <= 2`
- `parallel_width <= 1`
- `risk_level == low`
- `large_model_node_count == 0`
- `review_or_human_gate_count <= 1`
- `estimated_total_tokens < 30000`
- `no_commit_or_merge_action == true`

If hard triggers and hard skips conflict, skip unless the trigger involves high
risk, commit/merge, full ledger broadcast, or missing price data.

## Default Advisor Cost

```yaml
advisor_cost_defaults:
  cost_risk_analyst:
    expected_input_tokens: 2500
    expected_output_tokens: 800
  context_steward:
    expected_input_tokens: 3000
    expected_output_tokens: 900
  evaluator:
    expected_input_tokens: 5000
    expected_output_tokens: 1200
```

## First-Run Savings Estimate

```yaml
estimated_savings:
  duplicate_context:
    formula: overlapping_context_tokens * duplicate_reader_count
  wrong_model_choice:
    formula: large_model_tokens_that_could_be_mini * price_delta
  broadcast_bloat:
    formula: expected_broadcast_rounds * full_ledger_tokens
  avoidable_rework:
    formula: high_risk_rework_probability * estimated_node_rerun_cost
  blocked_join:
    formula: gate_count * average_wait_or_replan_cost
```

Risk defaults:

```yaml
risk_defaults:
  low:
    rework_probability: 0.05
  medium:
    rework_probability: 0.15
  high:
    rework_probability: 0.35
```

## Advisor Gate Decision

When invoked:

```yaml
advisor_gate_decision:
  invoked: true
  advisor: cost_risk_analyst
  policy_version: "0.1"
  reason:
    - parallel_width >= 3
    - estimated_context_fanout_tokens >= advisor_expected_tokens * 2
  estimated_advisor_tokens: 3300
  estimated_savings_tokens: 9200
  confidence: low
  decision_basis: first_run_heuristic
```

When skipped:

```yaml
advisor_gate_decision:
  invoked: false
  policy_version: "0.1"
  reason:
    - node_count <= 2
    - risk_level == low
    - estimated_total_tokens < 30000
  decision_basis: first_run_heuristic
```

## Advisor Output

Advisor output must be compact.

```yaml
advisor: cost_risk_analyst
verdict: approve
confidence: medium
p50_tokens: 0
p90_tokens: 0
p50_cost_usd: 0
p90_cost_usd: 0
main_cost_drivers: []
main_risk_drivers: []
recommended_changes: []
```

Allowed verdicts:

- `approve`
- `revise`
- `reject`

Advisors cannot:

- Modify workflows directly.
- Dispatch workers.
- Update canonical ledger state.
- Summon other advisors.
- Change advisor policy.

## Outcome Tracking

After a mission, record whether the advisor decision was useful.

```yaml
advisor_gate_outcome:
  actual_advisor_tokens: 0
  actual_total_tokens: 18400
  rework_count: 0
  broadcast_tokens: 1200
  duplicate_context_observed: false
  classification: good_skip
```

Classifications:

- `good_call`: advisor was invoked and caused a useful workflow change.
- `bad_call`: advisor was invoked but made no material change.
- `good_skip`: advisor was skipped and no avoidable waste occurred.
- `missed_call`: advisor was skipped and avoidable waste or rework occurred.

## Policy Evolution

Policy changes must be versioned and approved. LLMs may suggest changes but may
not apply them automatically.

```yaml
advisor_policy_version: "0.2"
effective_from: "2026-06-19"
changes:
  - raised parallel_width trigger from 2 to 3
  - added touched_file_overlap == high
reason: >
  Previous policy produced too many bad_call outcomes on low-risk workflows.
```

After enough missions, first-run heuristics should be replaced or calibrated by
project-specific telemetry.
