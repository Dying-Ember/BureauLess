# Context Economy

Token efficiency is an architectural constraint, not a later optimization.

This project should avoid becoming a system where many expensive thinking roles
watch a small number of workers do the actual task.

## Core Rule

Every extra agent needs a budget reason.

Every advisor needs a stronger reason:

```text
expected_savings * confidence > advisor_expected_cost * safety_factor
```

Default `safety_factor`: `2.0`.

## Coordination Overhead Target

Coordination overhead should stay below `15%-25%` of execution tokens.

Coordination overhead includes:

- Orchestrator planning turns.
- Advisor turns.
- Ledger summarization.
- Broadcast generation.
- Review coordination.
- Replanning.

If coordination overhead exceeds `25%`, the orchestrator must consider replanning
toward a simpler workflow.

## Defaults

- Default execution mode is `single_agent`.
- Default broadcast policy is `filtered_delta`.
- Default advisor policy is `skip`.
- Default worker context is isolated.
- Default large tool output handling is artifact reference plus summary.
- Default low-risk task handling avoids advisors.

## Anti-Patterns

- Full ledger broadcast after every tool call.
- Multiple agents reading the same large files without a reason.
- Advisor calls for low-risk one-node tasks.
- Review gates added only because they feel safe.
- Large models used for inventory or bounded mechanical work.
- Orchestrator doing worker tasks.
- Workers writing canonical ledger facts directly.

## Broadcast Rules

Use `filtered_delta` unless a workflow explicitly justifies something broader.

Do broadcast:

- Accepted public findings.
- Relevant decision summaries.
- Artifact references.
- Gate state changes.
- New blockers.

Do not broadcast by default:

- Raw private scratchpads.
- Full tool logs.
- Large file contents.
- Unaccepted worker hypotheses.
- Irrelevant findings from other branches.

## Context Compaction

Trigger context compaction when any of these are true:

- A worker has made 3 tool calls since the last summary.
- A tool output exceeds the configured size threshold.
- Broadcast payloads are growing faster than accepted findings.
- A worker repeats information already in the ledger.
- The same artifact is summarized by multiple workers.

Compaction output should be short and structured:

```yaml
summary_id: summary-001
source_refs:
  - report-001
  - artifact-003
accepted_facts: []
discarded_as_private: []
open_questions: []
```

## Model Routing

Use smaller or cheaper models for:

- Inventory.
- Documentation.
- Pure helper scaffolding.
- Bounded tests.
- Mechanical validation.

Use larger models for:

- Orchestrator review.
- Complex planning.
- High-risk code lifecycle decisions.
- Cross-branch integration review.
- Policy review.

Escalation should be explicit:

```yaml
model_escalation:
  from: gpt-5-mini
  to: gpt-5
  reason: >
    The worker found conflicting evidence and needs high-confidence review.
```

## Advisor Budgeting

Advisors are lazy and bounded.

Run an advisor only when:

- The workflow has visible avoidable waste.
- The workflow has high coordination risk.
- The workflow uses multiple large-model branches.
- The workflow has high-risk gates or commit/merge actions.
- The estimated savings exceed advisor cost by the safety factor.

Skip advisors when:

- The task has one or two low-risk nodes.
- There is no parallelism.
- There is no commit, merge, deployment, or human gate.
- Estimated total tokens are below the configured threshold.

## Telemetry

Record predicted and actual usage:

```yaml
usage_prediction:
  p50_tokens: 0
  p90_tokens: 0
  p50_cost_usd: 0
  p90_cost_usd: 0
actual_usage:
  input_tokens: 0
  output_tokens: 0
  broadcast_tokens: 0
  advisor_tokens: 0
  coordination_tokens: 0
```

Record classification:

- `good_call`
- `bad_call`
- `good_skip`
- `missed_call`

These classifications are the feedback loop for advisor policy.

## Replanning Rules

The orchestrator should replan when:

- Coordination overhead exceeds 25%.
- Broadcast growth dominates execution.
- Advisors repeatedly produce `bad_call`.
- Workers duplicate large context reads.
- Join gates block without new information.
- A high-risk task lacks review or human approval.

The simplest valid workflow should win.
