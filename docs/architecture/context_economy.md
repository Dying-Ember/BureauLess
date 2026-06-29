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

## Evidence, Ledger, And Context

BureauLess separates retention from delivery:

```text
evidence store       ledger                    context capsule
full trace and logs  minimum sufficient facts  bounded assignment view
diffs and artifacts  accepted state changes    relevant references
```

Native traces preserve what an agent attempted. Node outcomes describe observed
pre/post state and proposed semantic changes. The ledger records only accepted
mission-relevant facts and evidence refs. A context compiler projects the facts
needed for one assignment.

The complete evidence history may be large. The context delivered to a worker
must remain bounded. A fact belongs in the ledger when removing it could cause a
later worker to take an invalid action, repeat material work, violate a
constraint, or make replay unable to explain mission state.

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

Compaction is a derived view, not a canonical write. It must preserve source
references and must not create accepted findings by inference.

## Progressive Disclosure

Assignment context is disclosed in layers:

1. Mission constraints, assignment contract, accepted facts, gates, and current
   workspace state.
2. Concise rationale, provenance, diffs, and verification summaries.
3. Selected artifact bodies or trace excerpts.
4. Full native traces only for audit, conflict resolution, or exceptional
   review.

The initial capsule should already contain information implied by dependency
closure, role, active risks, and required gates. Progressive disclosure is not
an excuse to make every worker fail once before receiving necessary context.

A request for more context must identify:

- the missing information;
- the artifact or fact references requested;
- the expected value to the current assignment.

The context broker checks role visibility, relevance, and budget, then returns
only the requested material. Unavailable evidence stays unavailable. Context
requests are session telemetry unless they expose a canonical blocker or risk.

## Context Delivery Budget

Context priority is:

1. Safety constraints, permissions, and gates.
2. Current assignment and workspace state.
3. Accepted facts from direct and transitive dependencies.
4. Active risks and open questions.
5. Historical rationale.
6. Evidence bodies and native traces.

When the budget is exhausted, lower-priority content becomes an artifact
reference rather than displacing higher-priority facts. Context selection uses
workflow dependencies, scope, paths, artifacts, and role visibility before
introducing semantic retrieval.

Low-risk nodes must not require an extra summarizer or reviewer by default.
Ledger work should scale with node outcomes, not internal tool calls, and normal
replay should never load native transcripts.

## Context Feedback

Every context capsule records its policy version, token estimate, disclosure
level, and included fact and artifact refs. Session metrics connect that
delivery to observable outcomes:

- context request rate;
- missing-context block rate;
- added tokens after disclosure;
- first-pass success and rework;
- review rejection;
- repeated artifact requests;
- context tokens as a share of execution tokens.

Context fit uses conservative classifications:

- `under_provisioned`
- `well_provisioned`
- `over_provisioned`
- `mis_scoped`
- `insufficient_evidence`

The runtime should prefer external signals over model self-report. It cannot
reliably observe whether a model internally used a prompt fragment. Policy
recommendations require repeated evidence grouped by role, task type, risk,
model, and policy version. A single run never changes context policy
automatically.

Context telemetry remains outside canonical ledger state. An accepted policy
change, its evidence basis, and its version are ledger decisions.

## Cold-Start Test

A fresh worker with no prior conversation should be able to continue from:

```text
mission + assignment + context capsule + referenced artifacts
```

Routine requests for the same missing evidence indicate under-provisioning and
should promote that evidence class into the default capsule. Routine delivery
of large irrelevant context indicates over-provisioning and should demote it to
on-demand disclosure.

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

## Budget Oracle

The budget oracle is the deterministic component that turns model usage into
auditable cost estimates. It does not call a model and it does not decide
workflow shape by itself.

It should:

- Store price snapshots used for a mission.
- Explain token-priced, quota-priced, and bundled models.
- Convert predicted and actual usage into comparable estimates when possible.
- Mark estimates as unauditable when price data is missing.
- Provide the price inputs used by advisor ROI calculations.

```yaml
model_price_snapshot:
  snapshot_id: price-snapshot-2026-06-20
  provider: mixed
  captured_at: "2026-06-20T00:00:00Z"
  currency: USD
  source: manual
  models:
    kimi-code:
      provider: opencode-go
      pricing_model: token
      input_per_million: 0.00
      output_per_million: 0.00
      source: manual
      confidence: medium
    m3:
      provider: minimax
      pricing_model: bundled_quota
      quota_model: bundled
      effective_cost_basis: monthly_pool
      marginal_cost_usd: unknown
      source: manual
      confidence: low
```

Prices change and provider billing models differ. The snapshot must record what
the orchestrator believed at decision time. When prices are bundled,
quota-based, or unknown, estimates must say so instead of inventing precision.

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
