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
ledger_version: 2
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

`ledger_version: 2` uses strict result acceptance. A worker result is staged as
`result_submitted`, and only a later `node_outcome_decided` event can make its
claimed workflow events effective. Version 1 remains readable with historical
replay semantics but maintained mutating CLI/API paths require explicit
conservative migration to v2.

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

### Canonical State Boundary

The ledger stores accepted mission-relevant facts, not a compressed copy of an
agent transcript. A record belongs in canonical state when removing it could
cause a later worker to take an invalid action, repeat material work, violate a
constraint, or make replay unable to explain mission state.

The runtime separates four kinds of records:

- Native traces and large outputs are immutable evidence artifacts.
- Node outcomes are compact proposals at the assignment boundary.
- Acceptance decisions identify which observations, findings, and decisions
  become canonical.
- Current findings, risks, decisions, and open questions are projections over
  accepted events, not independent competing sources of truth.

Corrections append supersession or invalidation events. They do not rewrite
accepted history. Normal replay must not read native transcripts.

If a current-state projection is persisted, it records the last event it
includes:

```yaml
projection:
  through_event_id: event-outcome-decision-017
  accepted_workspace_ref: workspace:def456
  generated_at: "2026-06-29T00:00:00Z"
```

A missing or mismatched projection cursor makes the projection a rebuildable
cache. The accepted event history remains authoritative.

### Node Outcome

Every completed, failed, timed-out, cancelled, or partial assignment attempt
produces a compact node outcome. The harness fills deterministic observations;
workers may propose semantic findings but cannot accept them.

```yaml
outcome_id: outcome-017
run_id: run-017
mission_id: optimize-worker-lifecycle
workflow_id: workflow-001
node_id: implement
assignment_id: assign-017
session_id: session-017
status: completed
pre_state_ref: workspace:abc123
post_state_ref: workspace:def456
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

Outcome content is classified before acceptance:

- `observation`: machine-verifiable state, hash, exit, or verification fact.
- `finding`: a semantic claim with evidence and review provenance.
- `decision`: an orchestrator, policy, reviewer, or human disposition.
- `unknown`: information that could not be established and must not be guessed.

Low-risk observations may be accepted automatically by deterministic harness
rules. Semantic, conflicting, externally visible, or high-risk claims use the
review and permission model. Accepted events identify the actor, source
outcome, evidence refs, and validation rule.

```yaml
event_id: event-outcome-decision-017
event_type: node_outcome_decided
mission_id: optimize-worker-lifecycle
workflow_id: workflow-001
assignment_id: assign-017
node_id: implement
role: coder
agent_id: coder-agent
session_id: session-017
source_result_event_id: event-result-017
source_outcome_id: outcome-017
source_review_event_id: event-review-017
outcome_status: completed
actor: harness
disposition: partially_accepted
pre_state_ref: workspace:abc123
post_state_ref: workspace:def456
accepted_event_types:
  - patch_ready
acceptance_policy_version: acceptance-v1
verification_status: passed
validation_rule: reviewed_verified_result_v1
```

The decision event supports `accepted`, `partially_accepted`, and `rejected`
dispositions without copying the full outcome into the ledger. In ledger v2,
replay materializes effective workflow events at this decision's log position.
There is at most one terminal decision per `source_outcome_id`.

An outcome's state claims are scoped to its `pre_state_ref`, `post_state_ref`,
and workflow. If the accepted workspace has moved past the pre-state, the
outcome is `stale` or `needs_review`; it is not silently applied. Failed and
interrupted outcomes must record partial effects and cleanup requirements.

### Review Decision

Review acceptance is a separate artifact, not an implicit side effect of raw
worker output. The review decision packet captures who made the judgment, which
existing ledger event they reviewed, which findings were accepted or rejected,
and what should happen next.

```yaml
decision_type: review_decision
decision_id: review-017
mission_id: optimize-worker-lifecycle
workflow_id: workflow-001
reviewed_event: event-result-017
actor: orchestrator
verdict: approved
reason: >
  The patch satisfies the node acceptance criteria and verification receipts
  match the claimed workspace delta.
evidence_refs:
  - artifact-patch-017
  - artifact-test-report-017
accepted_findings:
  - finding_id: finding-017
    content: Superseded assignment events no longer satisfy downstream gates.
rejected_findings: []
next_action: continue
```

The harness validates review decisions independently of the worker payload.
`actor` is limited to `orchestrator` or `human`. `verdict` is limited to
`approved`, `rejected`, or `changes_requested`. `next_action` is limited to
`continue`, `retry`, `escalate`, or `stop`. The same `finding_id` must not
appear in both `accepted_findings` and `rejected_findings`.

Accepted review decisions append a dedicated ledger event that preserves both
the reviewed event linkage and the raw decision packet reference:

```yaml
event_id: event-review-017
event_type: review_decision_recorded
mission_id: optimize-worker-lifecycle
workflow_id: workflow-001
review_decision_id: review-017
reviewed_event: event-result-017
actor: orchestrator
verdict: approved
reason: >
  The patch satisfies the node acceptance criteria and verification receipts
  match the claimed workspace delta.
evidence_refs:
  - artifact-patch-017
  - artifact-test-report-017
accepted_findings:
  - finding_id: finding-017
    content: Superseded assignment events no longer satisfy downstream gates.
rejected_findings: []
next_action: continue
decision_ref: artifacts/reviews/review-017.yaml
```

Projected `public_findings` and `decisions` derive from
`review_decision_recorded` events. A public finding therefore always carries
review provenance through `source_event`, `source_agent`, `accepted_by`, and
`review_decision_id`. Raw decision packets remain audit evidence; the accepted
projection remains the canonical current-state view.

A review decision does not complete a workflow node by itself. Harness-owned
acceptance policy combines its verdict with independently supplied verification
status and node-outcome state. Only `approved` may authorize accepted event
types; `rejected` and `changes_requested` accept none. `next_action: retry` is a
later control request, not permission to accept the current attempt.

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
observed_at: "2026-07-03T00:00:02Z"
telemetry_mode: observed
source_event_ids:
  - tool-001
policy_compliance:
  status: violated
  reasons:
    - native_events_aggregated_after_process_exit
```

Turn-report counts and timestamps must come from adapter events or be marked
degraded. Codex completed command, MCP, search, file-change, and tool events are
observable through JSONL. The maintained runner currently aggregates them after
process exit; therefore an `after_each_tool_call` policy with observed tools is
reported as violated until a streaming adapter emits reports during execution.
Adapters without an integrated event stream report `telemetry_mode: degraded`,
zero observed calls, and the capability reason. Turn reports are inspection and
policy evidence; they do not become canonical mission facts automatically.

## Runtime Run Bundle

A runtime run bundle is a discovery projection that links one maintained
session to its mission, workflow, ledger, dispatch, session record, and
available evidence. Demo and ordinary session paths use the same producer and
validator. Optional artifacts are explicit null values so consumers do not
infer evidence that was never produced.

Each bundle has a stable `bundle_id`, a monotonic `bundle_revision`, and an
artifact index containing immutable path and SHA-256 references. Updating the
projection preserves its identity and replaces the file atomically. Loading a
bundle rejects missing or changed indexed artifacts.

The bundle is not canonical workflow state. It cannot satisfy gates, accept
results, append ledger events, or replace replay. Mission, workflow, and
accepted ledger history remain authoritative; Workbench treats the bundle only
as an index into validated inspection endpoints.

The maintained Runtime M3.5 acceptance command is:

```bash
python -m bureauless mission execution-spine-acceptance <workspace>
```

It verifies pre-launch dispatch, one bounded context continuation, observed
turn telemetry, explicit result acceptance, process cancellation, advisor
skip/invocation evidence, accepted replay, and ordinary-session bundle loading.
It writes `execution_spine_acceptance.yaml` and exits unsuccessfully if any
required check fails. This report is verification evidence, not a canonical
ledger or an alternative replay source.

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

Result import, workspace observation, and outcome acceptance are distinct
boundaries:

```text
result submitted
  -> workspace and evidence observed
  -> node outcome validated
  -> outcome accepted or rejected
  -> accepted workflow events become effective
```

An emitted event asserted by a worker must not become effective merely because
it appears in a transcript. Low-risk event acceptance may be automatic, but the
ledger still records that the harness accepted it and which deterministic rule
was used.

A result that discovers a structural workflow gap uses
`status: completed_with_proposal` and lists proposal artifact IDs in
`mutation_proposal_refs`. Each reference must resolve to an immutable YAML
artifact in the same result. `completed` and `blocked` results cannot carry
mutation proposal refs, and blocked results cannot emit completion events.
In ledger v2, importing any result records only `result_submitted`; it does not
append claimed workflow events. The node remains blocked with
`awaiting_acceptance` until policy produces a terminal outcome decision. A
result carrying mutation references also does not append a mutation event or
alter the workflow.

This is the implemented M2.5/M3 compatibility shape. The accepted Runtime M4
contract below replaces the status coupling with an optional typed
`control_intents` channel while retaining a compatibility reader for existing
records.

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

### Accepted Runtime M4 Extension

Status: accepted by
[`ADR-004`](../adrs/004-temporal-replay-mutation-intake-and-retry-control/001-accepted-design.md),
implementation pending under Runtime M4.

Runtime M4 permits every worker to include at most one inert
`workflow_mutation` intent in `control_intents`, independently of whether the
execution result is `completed` or `blocked`. The worker supplies only reason,
rationale, proposed changes, and evidence refs. The harness owns proposal IDs,
assignment/session/agent provenance, base workflow version, artifact identity,
and approval policy.

Result staging and intent intake are separate transactions. Intake writes a
`mutation_intake_disposition` evidence artifact with `registered`, `duplicate`,
`invalid`, `stale`, or `unsupported` status. Only `registered` appends a new
`workflow_mutation_proposed` event. Duplicate intake returns the existing
proposal; failed intake appends no canonical event and never erases a valid
result.

Maintained mutation/version writes require `ledger_version: 3`. Workflow
content hashes are SHA-256 over canonical JSON of the validated workflow.
Version IDs have this form:

```text
<workflow_id>:v<accepted-mutation-sequence:04d>:<first-12-hash-characters>
```

Version zero uses sequence `0000`. Each accepted mutation records full
before/after hashes, parent version, and `workflow_version_before` /
`workflow_version_after`. Proposal and rejection events do not advance the
version. V1 stays historical-read only; v2 temporal compatibility is read only;
explicit v3 migration appends `workflow_version_initialized` without rewriting
history.

Historical `through_event_id` replay is inclusive. An accepted mutation is
visible as its child version through its own event; an unknown cursor fails;
replay through the final event equals current replay. Ledger append order is
authoritative and timestamps never order replay.

Assignments record their creation workflow version. They remain valid in a
child version only if deterministic impact proves their node contract,
dependencies, gates, scoped evidence, and forbidden actions unchanged.
Affected in-flight assignments are superseded and cancelled when supported;
late results remain evidence but cannot satisfy gates. Mutation acceptance uses
compare-and-swap over expected ledger tail and expected current version. Stale
proposals never auto-rebase.

High-risk safety weakening, protected side effects, permission expansion, and
high-risk in-flight supersession require a distinct human second approver. A
proposer cannot approve its own proposal. `review_overdue` becomes replay state
only after an explicit `workflow_mutation_review_overdue` event; deadline
timestamps cannot accept or reject anything by themselves.

The first Codex CLI transport uses structured final output. A future native
tool transport must call the same validator and intake service. Neither
transport grants workflow, ledger, dispatch, or acceptance authority.

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
Maintained external launches must enter through a validated dispatch packet;
the assignment embedded in that packet is the canonical assignment for the
attempt.

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
dispatch:
  packet_id: packet-001
  packet_path: decisions/implement_dispatch_packet.yaml
  packet_sha256: "c40f5b..."
  mission_id: optimize-worker-lifecycle
  workflow_id: workflow-001
  assignment_id: assign-001
  session_spec:
    session_id: session-001
    assignment_id: assign-001
    agent_id: codex-cli
    timeout_seconds: 120
    sandbox_mode: workspace-write
    target_model: gpt-5-mini
    target_provider: bureauless-proxy
```

Session records may produce result proposals, but sessions must not write the
canonical ledger directly.

Native maintained launches return a `LiveSessionHandle` that owns the process
group and terminal transition. Cancel and supersede are idempotent; the first
accepted terminal intent wins over a late process exit. Shutdown sends a
bounded graceful signal to the complete process group and escalates to a forced
kill when required. A cancelled or superseded record retains native logs,
workspace snapshots, deltas, metrics, and dispatch evidence, but it carries no
importable result proposal. Replay therefore treats partial work as an attempt,
not as workflow completion.

Codex currently has exercised strong process-group cancellation. Registry
entries for adapters not yet connected to this session lifecycle must report
weaker cancellation control even when their binary can be killed externally.

The runtime validates and persists the exact dispatch packet before process
start. Agent, model, provider, sandbox, timeout, review constraints, and
turn-report policy belong to one dispatch operation. The Codex adapter receives
the packet routing and policy constraints in its launch prompt. A mismatch
between packet, assignment, binding, or reconstructed session evidence is a
pre-launch or reconstruction error, never a warning applied after execution.

Native logs preserve provider-specific evidence. They may include tool calls,
command output, file edits, and errors, but are not normalized into ledger
events one tool call at a time. Trace access follows artifact visibility,
redaction, and retention policy.

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

Context-delivery telemetry is also session-level data. It records the context
policy version, capsule size, included references, later context requests,
first-pass outcome, review outcome, and rework. High-volume telemetry does not
become canonical mission state. Only an accepted context-policy change and its
rationale become a ledger decision.

## Event

Ledger events are append-only facts about execution. In ledger v2, workflow
completion event names are effective projections of an accepted node-outcome
decision; they are not appended directly.

```yaml
effective_event: patch_ready
assignment_id: assign-001
node_id: implement
effective_at_event: event-outcome-decision-017
source_result_event: event-result-017
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

The accepted Runtime M4 `retry-v1` extension classifies failures before another
attempt is scheduled. Transient infrastructure failures allow three total
attempts; malformed output, verification repair, and capability rerouting allow
two; structural, stale/superseded, and policy failures allow one. Retry turns
default to a 20,000-token aggregate cap, additionally bounded by assignment and
mission remainder. Non-transient retry requires changed evidence, input,
strategy, assignment revision, or workflow version.

V3 retry control appends `assignment_retry_scheduled` with a new attempt ID,
prior attempt, failure class/fingerprint, changed-input evidence, strategy, and
budget snapshot. The second identical deterministic fingerprint appends
`assignment_circuit_opened` and launches no third unchanged attempt. Existing
`assignment_retry_requested` remains a compatibility event until migration.

Assignment terminality must be explicit in replay:

- `patch_ready`, `review_approved`, `commit_created`, and other workflow effects
  accepted by `node_outcome_decided` terminate the producing assignment as
  completed.
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

## Context Capsule And Progressive Disclosure

Workers receive a bounded context capsule compiled for one assignment rather
than a full ledger broadcast. Selection uses explicit relationships before any
semantic retrieval:

- mission constraints and current workspace revision;
- direct and transitive workflow dependencies;
- required gates and role permissions;
- active findings, risks, and questions scoped to the node;
- shared paths, artifacts, and accepted decisions.

Unrelated branches, resolved risks, superseded history, raw private output, full
tool logs, and large artifact bodies are excluded by default.

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

Disclosure is progressive:

1. Assignment, constraints, accepted facts, gates, and current state.
2. Concise rationale, provenance, relevant diffs, and verification summaries.
3. Selected artifact bodies or trace excerpts.
4. Full native trace only for audit, conflict resolution, or exceptional review.

A worker requesting more context must identify the missing information,
requested refs, and expected value. The context broker checks relevance,
visibility, and token budget, then returns a targeted context packet. It does
not rebroadcast an entire level. Missing evidence is returned as `unavailable`.

```yaml
context_request_id: context-request-004
assignment_id: assign-022
session_id: session-022
continuation_id: continuation-session-022
request_index: 1
requested_at: "2026-07-02T08:00:00+00:00"
expires_at: "2026-07-02T08:05:00+00:00"
missing_information: The failing verification details are not in the capsule.
requested_refs:
  - artifact-test-report-017
expected_value: Determine whether the failure is in the patch or environment.
```

The worker emits only the missing-information intent. The harness owns request,
continuation, session, policy, and expiration identity. A granted request may
start another adapter process turn in the same logical session and isolated
workspace; it is not an assignment retry.

Strict staging records `context_requested`, `context_resolved`, and, when
granted, `context_resumed` before the eventual result. These lifecycle events
never satisfy workflow waits. Denied, unavailable, expired, budget-exceeded,
and exhausted requests remain structured and replayable without producing an
importable result. The maintained M3.5 policy permits one request and one scoped
artifact. Broader policies require a new version.

The cold-start acceptance test is explicit: a fresh worker with no previous
conversation should be able to continue from the mission, assignment, context
capsule, and referenced artifacts. Routine dependence on full transcripts means
the accepted facts or context policy are inadequate.

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
- Ledger maintenance scales with node outcomes, not native tool calls.
- Normal replay does not read agent transcripts.
- Current ledger summaries and context capsules are derived projections.
- Facts are scoped to their observed workflow and workspace state.
- Missing evidence remains explicit and is never filled by model inference.
- Low-risk nodes do not require an extra summarizer or reviewer by default.
- Context policy changes are versioned and based on aggregated evidence rather
  than a single run.

Human override is allowed only when it is explicit, persisted, and replayable.
