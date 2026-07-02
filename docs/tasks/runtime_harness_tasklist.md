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
  the completed milestone for the initial `codex-cli` binding spine, node
  outcomes, bounded and measurable context delivery, advisor outcome learning,
  orchestrator decision artifacts, and the M3 runtime API surface.
- [`runtime_harness_milestone_4_tasklist.md`](runtime_harness_milestone_4_tasklist.md):
  the planned milestone for validated real-agent mutation intake, deterministic
  retry/circuit-break control, workflow versions, and linear temporal replay
  through ledger event cursors.

Runtime Milestone 4 is selected and planned but implementation has not started.
Its first task has produced draft
[`RFC-004`](../rfcs/004-temporal-replay-mutation-intake-and-retry-control.md);
implementation remains blocked until that design is accepted into an ADR.

## Reading Order

1. Read [`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md).
2. Read the relevant runtime protocol file in `../protocol/`.
3. Read any relevant RFC in [`../rfcs/`](../rfcs/) if the work touches proposed
   but not accepted behavior.
4. Read Milestone 1 for current baseline behavior.
5. Read Milestone 2 for the real-agent execution loop.
6. Read Milestone 2.5 for controlled workflow mutation design.
7. Read Milestone 3 for the current decision-artifact, bounded-context, and M3
   API baseline.
8. Read Milestone 4 and RFC-004 for the selected agent mutation intake,
   retry-control, and temporal replay scope; do not begin implementation before
   RM4-00 accepts the RFC/ADR.
