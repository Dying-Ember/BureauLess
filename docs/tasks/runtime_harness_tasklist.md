# Runtime Harness Task Lists

This index tracks the BureauLess runtime/harness milestone task lists.

Use `milestone` for a user-visible delivery target and `workstream` for an
internal implementation grouping inside that milestone.

## Milestones

- [`runtime_harness_milestone_1_tasklist.md`](runtime_harness_milestone_1_tasklist.md):
  the completed foundation milestone for protocol hardening, replay,
  gatekeeper, assignment export, result import, agent registry, session
  wrapping, metrics, budget snapshots, and runtime API coverage.
- [`runtime_harness_milestone_2_tasklist.md`](runtime_harness_milestone_2_tasklist.md):
  the completed runtime milestone that turned the foundation into a
  reliable real-agent execution loop with isolated sessions, compatibility
  checks, and end-to-end milestone smoke coverage.
- [`runtime_harness_milestone_2_5_tasklist.md`](runtime_harness_milestone_2_5_tasklist.md):
  the completed bridge milestone for controlled workflow mutation, where workers
  can propose DAG changes but only accepted ledger events can change current
  workflow state.
- [`runtime_harness_milestone_3_tasklist.md`](runtime_harness_milestone_3_tasklist.md):
  the completed artifact/protocol milestone for the initial `codex-cli` binding
  spine, node outcomes, bounded context artifacts, advisor outcome learning,
  orchestrator decision artifacts, and the M3 runtime API surface.
- [`runtime_harness_milestone_3_5_tasklist.md`](runtime_harness_milestone_3_5_tasklist.md):
  the completed remediation milestone for authoritative result acceptance,
  executable dispatch, live context continuation and cancellation, truthful
  telemetry, generic run bundles, and advisor invocation evidence.
- [`runtime_harness_milestone_4_tasklist.md`](runtime_harness_milestone_4_tasklist.md):
  the active milestone for validated real-agent mutation intake, deterministic
  retry/circuit-break control, workflow versions, and linear temporal replay
  through ledger event cursors.

Runtime Milestone 3.5 is complete. Runtime Milestone 4 is active. RM4-00 accepted
[`RFC-004`](../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md)
through
[`ADR-004`](../adrs/004-temporal-replay-mutation-intake-and-retry-control/001-accepted-design.md);
RM4-01 is the next implementation task.

RM35-01 produced
[`RFC-005`](../rfcs/005-authoritative-result-acceptance-spine.md). Acceptance
compatibility is implemented under accepted
[`ADR-005`](../adrs/005-authoritative-result-acceptance-spine/001-accepted-design.md).

## Reading Order

1. Read [`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md).
2. Read the relevant runtime protocol file in `../protocol/`.
3. Read any relevant RFC in [`../rfcs/`](../rfcs/) if the work touches proposed
   but not accepted behavior.
4. Read Milestone 1 for current baseline behavior.
5. Read Milestone 2 for the real-agent execution loop.
6. Read Milestone 2.5 for controlled workflow mutation design.
7. Read Milestone 3 for the delivered decision-artifact, bounded-context, and M3
   API baseline.
8. Read the
   [`runtime execution gap analysis`](../audits/2026-07-02-runtime-execution-gap-analysis.md)
   and Milestone 3.5 for the required execution-spine remediation.
9. Read Milestone 4 and RFC-004 for the selected agent mutation intake,
   retry-control, and temporal replay scope. RM4-00 and the required RM35
   foundations are complete; begin implementation with RM4-01.
