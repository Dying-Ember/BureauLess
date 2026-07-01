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

No post-M3 runtime milestone is active. Its scope must be selected in the
roadmap and recorded in a dedicated task list before implementation starts.

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
8. Do not infer a Runtime Milestone 4 from roadmap ideas; open its task list
   only after the post-M3 runtime scope is selected.
