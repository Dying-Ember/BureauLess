# RFC-005: Authoritative Result Acceptance Spine

## Status

Accepted and implemented by RM35-01 in Runtime Harness Milestone 3.5.

ADR:
[`ADR-005: Authoritative Result Acceptance Spine`](../adrs/005-authoritative-result-acceptance-spine/001-accepted-design.md)

Implementation planning:
[`RM35-01: Result, Review, And Outcome Acceptance Spine`](../tasks/runtime_harness_milestone_3_5_tasklist.md)

Source audit:
[`REX-002: Result Events Can Bypass Authoritative Acceptance`](../audits/2026-07-02-runtime-execution-gap-analysis.md)

Tracking issue:
[#10 RFC-005: Authoritative Result Acceptance Spine (closed)](https://github.com/Dying-Ember/BureauLess/issues/10)

## Problem

The current runtime has the right artifact categories but not one authoritative
acceptance transaction:

- `result_submitted` preserves a worker result, then result import immediately
  appends each worker-declared workflow event;
- replay treats raw workflow events without a `node_outcome_decided` event as
  accepted for compatibility;
- `import_session_record` defaults to accepting all declared events before the
  maintained demo records a review decision;
- `review_decision_recorded` projects findings and review provenance but does not
  control the workflow events accepted by `node_outcome_decided`; and
- verification status is evidence, not an enforced acceptance policy.

Consequently, a missing, failed, or rejected review can coexist with workflow
events that already satisfy downstream gates. Temporal replay and mutation
intake cannot safely build on that ambiguity.

## Goals

1. Name exactly one event as the authority for effective workflow completion.
2. Preserve raw worker results and evidence without treating them as accepted
   mission truth.
3. Make review and verification requirements deterministic inputs to outcome
   acceptance.
4. Support full, partial, and rejected dispositions without deleting evidence.
5. Preserve deterministic reads of legacy ledgers while preventing legacy
   behavior from leaking into new writes.
6. Give CLI, API, demos, replay, and Workbench one shared application path.

## Non-Goals

- Automatically approving worker results.
- Replacing review decisions with worker-authored `review_status`.
- Defining mutation-intent acceptance; RFC-004 owns mutation proposal semantics.
- Defining retry classification beyond the acceptance result exposed to RM4.
- Editing or deleting historical ledger events.
- Supporting correction by silently replacing a prior accepted outcome decision.
- Introducing distributed transactions or a persistent job queue.

## Proposed Decisions

### 1. `node_outcome_decided` Is The Sole Workflow Acceptance Authority

For strict ledgers, only `node_outcome_decided.accepted_event_types` creates
effective workflow events. Worker-declared `ResultProposal.emitted_events` are
claims to evaluate, not accepted events.

`result_submitted` remains canonical evidence that a result was received. It
does not satisfy waits, complete nodes, open gates, update the accepted workspace
reference, or authorize a mutation.

Replay synthesizes effective workflow events at the log position of the
`node_outcome_decided` event. This preserves append-only temporal order without
duplicating raw workflow event records.

### 2. New Result Import Is Staged

The strict import sequence is:

1. validate assignment/result identity, role, allowed claimed events, artifacts,
   metrics, and workflow version;
2. append one `result_submitted` event containing the immutable raw proposal;
3. create and persist the linked `NodeOutcome` evidence artifact;
4. collect required verification and review evidence;
5. evaluate one deterministic acceptance policy; and
6. append one terminal `node_outcome_decided` event.

Steps 2 through 6 may occur in separate commands or process turns. Between
steps 2 and 6 the assignment is `awaiting_acceptance`; it is neither completed
nor eligible for an execution retry solely because review is pending.

Strict `import_result_proposal` does not append the workflow event types listed
in `ResultProposal.emitted_events`.

### 3. Review And Outcome Decisions Have Different Responsibilities

A `ReviewDecision` answers:

- whether the result/evidence is approved, rejected, or needs changes;
- which semantic findings become public; and
- whether the next requested action is continue, retry, escalate, or stop.

A `node_outcome_decided` event answers:

- which claimed workflow event types become effective;
- whether the observed workspace transition is accepted;
- which deterministic policy and evidence authorized that disposition; and
- where in ledger history the accepted effect begins.

The acceptance application service consumes a review decision when dispatch
policy requires one. Recording a review decision alone never advances workflow
state. Appending a node-outcome decision without satisfying required review and
verification policy is invalid.

### 4. Acceptance Policy Is Dispatch-Bound And Harness-Owned

The dispatch handoff supplies a harness-owned `acceptance_policy` with:

```yaml
acceptance_policy:
  policy_version: acceptance-v1
  review:
    required: true
    allowed_actors: [orchestrator, human]
  verification:
    required_statuses: [passed]
  allow_partial_acceptance: false
```

The worker cannot relax this policy. The accepted outcome event records the
policy version, source result event, source outcome artifact, optional source
review decision event, and validation rule.

For nodes with no meaningful executable verification, dispatch policy may use
`required_statuses: [not_required]`. `not_run` is observational and never means
`not_required`. Any policy permitting `not_run` must be explicit, versioned, and
cannot be the maintained default.

RM35-02 will make the dispatch packet the authoritative carrier of this policy.
Until that bridge lands, tests may supply the same policy directly to the
acceptance service.

### 5. Verdict Mapping Is Deterministic

When review is required:

| Review verdict | Allowed outcome disposition | Effective events |
| --- | --- | --- |
| `approved` | `accepted` or `partially_accepted` | Policy-approved subset of claimed events |
| `rejected` | `rejected` | none |
| `changes_requested` | `rejected` | none; later retry/escalation is a separate control decision |

`next_action` does not override the verdict. For example,
`verdict: changes_requested` with `next_action: retry` requests later retry
evaluation but accepts no workflow event from the current attempt.

When review is not required, only the harness acceptance policy may decide the
outcome. Worker-authored `review_status` is ignored for authorization and kept
only as deprecated telemetry during compatibility reads.

### 6. Outcome And Verification Invariants

The acceptance service enforces all of these rules:

- accepted event types are a subset of the result's claimed `emitted_events` and
  the current workflow node's allowed emits;
- `accepted` requires the full policy-approved claimed set;
- `partially_accepted` requires a non-empty strict subset and explicit
  `allow_partial_acceptance: true`;
- `rejected` requires an empty accepted-event set;
- `failed`, `timed_out`, `cancelled`, `superseded`, `stale`, and `needs_review`
  outcomes cannot accept workflow completion events;
- required verification status must be present before any event is accepted;
- required review must reference the exact `result_submitted` event and matching
  mission, workflow version, assignment, and outcome evidence;
- accepted workspace state advances only through an accepted or partially
  accepted outcome carrying a validated `post_state_ref`; and
- malformed optional control intent never erases a valid staged execution
  result, consistent with RFC-004.

### 7. One Terminal Decision Per Outcome

An outcome receives at most one terminal `node_outcome_decided` event. Duplicate
or conflicting decisions for the same `source_outcome_id` are rejected.

This avoids a later event silently reversing an earlier accepted workspace or
workflow transition. A corrected execution uses a new assignment attempt and
outcome. A future explicit administrative correction protocol may supersede a
decision, but it is outside Runtime M3.5.

### 8. Ledger V2 Defines Strict Acceptance

`ledger_version: 2` introduces strict acceptance semantics:

- result import stages `result_submitted` and does not append raw workflow event
  records;
- workflow events without a valid outcome decision are ineffective;
- mutating CLI/API/runtime commands require v2; and
- replay, gatekeeper, context compilation, and Workbench expose pending
  acceptance explicitly.

`ledger_version: 1` remains readable with its historical replay behavior so
existing evidence is not reinterpreted silently. Once v2 support lands, v1 is
read-only through maintained mutating commands.

### 9. V1 To V2 Migration Is Explicit And Conservative

Migration creates a new v2 ledger artifact and a migration report; it never
edits the v1 source in place.

For each legacy result/assignment:

- an existing valid `node_outcome_decided` event is preserved as the acceptance
  authority;
- raw workflow events with no decision are quarantined as
  `requires_acceptance_review` and do not become effective in v2;
- a human may explicitly preserve legacy acceptance by creating a reviewed v2
  outcome decision with migration provenance; and
- ambiguous, stale, or incomplete provenance is reported rather than inferred.

There is no automatic bulk acceptance flag in the default migration path. A
separate explicit operator option may generate review work, but it cannot claim
that historical verification occurred when it did not.

### 10. One Application Service Owns The Transaction

CLI, API, demos, and future dispatch code use one acceptance application service
for:

- staging a result and node outcome;
- validating review/verification evidence;
- deciding accepted event types;
- appending the terminal outcome decision; and
- returning replay/gatekeeper state.

Direct low-level append helpers remain protocol primitives for tests and
migration tooling. They are not maintained operator paths.

The existing `result import` command becomes a staging operation. A separate
outcome decision operation, or a higher-level reviewed import command, performs
acceptance. Command output must state `awaiting_acceptance`, `accepted`,
`partially_accepted`, or `rejected` explicitly.

## Canonical Event Example

```yaml
- event_id: event-result-017
  event_type: result_submitted
  assignment_id: assign-017
  node_id: implement
  result:
    result_id: result-017
    emitted_events: [patch_ready]
    verification:
      status: passed

- event_id: event-review-017
  event_type: review_decision_recorded
  reviewed_event: event-result-017
  verdict: approved
  next_action: continue

- event_id: event-outcome-017-decision
  event_type: node_outcome_decided
  assignment_id: assign-017
  source_result_event_id: event-result-017
  source_outcome_id: outcome-017
  source_review_event_id: event-review-017
  outcome_status: completed
  actor: harness
  disposition: accepted
  accepted_event_types: [patch_ready]
  acceptance_policy_version: acceptance-v1
  validation_rule: reviewed_verified_result_v1
```

No standalone `patch_ready` ledger record is required. Replay materializes
`patch_ready` at the index of `event-outcome-017-decision`.

## Required API And Operator Behavior

- Result inspection distinguishes claimed events from accepted events.
- Replay and gatekeeper expose `awaiting_acceptance` as a blocked reason.
- Review endpoints reject decisions that do not reference an existing matching
  result event.
- Outcome decision endpoints return the policy evidence used for acceptance.
- Workbench labels raw result claims, review verdict, and effective events
  separately.
- Legacy v1 mode is visible and cannot be mistaken for strict v2 acceptance.

## Rejected Alternatives

### Keep Raw Workflow Events And Filter Them Later

This preserves ambiguous records whose event type looks canonical before a
decision exists. Synthesizing effective events from the outcome decision is
clearer and is already supported by replay.

### Let Review Decisions Directly Complete Nodes

Review decisions also own semantic findings and next-action recommendations.
Making them workflow completion events would conflate review evidence with the
accepted workspace/outcome boundary.

### Let The Latest Outcome Decision Win

This permits silent reversal of accepted history and complicates temporal
replay. Runtime M3.5 uses one terminal decision per outcome.

### Change V1 Replay In Place

That would make old ledgers produce different state after a software upgrade.
V2 strict semantics and explicit migration preserve deterministic legacy reads.

### Trust Worker `review_status` Or `verification.status`

Both originate in the worker result. They are evidence claims until independently
validated under harness-owned policy.

## Implementation Sequence

1. Accept this RFC into an ADR and finalize `acceptance_policy` fields.
2. Add ledger v2 loading, strict replay, and v1 read-only compatibility.
3. Add staged result/outcome persistence and acceptance service.
4. Validate review and verification linkage.
5. Migrate CLI, API, runtime demo, and session import paths.
6. Add conservative v1-to-v2 migration and reports.
7. Update protocol docs, Workbench labels, examples, and maintained acceptance
   tests.

## Acceptance Test Matrix

| Scenario | Expected result |
| --- | --- |
| Result submitted, no decision | No effective workflow event; awaiting acceptance |
| Required review missing | Acceptance rejected by validator |
| Review rejected | Outcome rejected; no effective events |
| Review requests changes | Outcome rejected; retry only considered separately |
| Verification failed or not run under default policy | No accepted events |
| Approved and verified result | Claimed allowed events become effective at decision index |
| Partial acceptance disabled | Subset decision rejected by validator |
| Partial acceptance enabled | Only explicit subset becomes effective |
| Cancelled, stale, or superseded outcome | No completion event can be accepted |
| Duplicate decision for one outcome | Second decision rejected |
| V1 ledger read | Historical replay preserved and compatibility mode visible |
| V1 ledger mutation | Rejected until explicit migration |
| Default v1-to-v2 migration | Undecided legacy events quarantined |

## Resolved Review Questions

1. `acceptance_policy` lives directly in `DispatchPacket` for M3.5.
2. Migrated assignments use normal outcome-decision commands after migration.
3. `awaiting_acceptance` is a structured blocked reason so the existing
   node-state vocabulary remains stable.

## Decision

Accepted by ADR-005 and implemented by RM35-01.
