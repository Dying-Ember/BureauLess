# Runtime Harness Milestone 2 Task List

This is the implementation task list for BureauLess Runtime Milestone 2. It
builds on
[`runtime_harness_milestone_1_tasklist.md`](runtime_harness_milestone_1_tasklist.md).
The project-level sequencing lives in `../roadmap/development_roadmap.md`.
Protocol contracts live in `../protocol/`; architecture rationale lives in
`../architecture/`.

Milestone 2 moves the runtime from a completed foundation to a reliable
real-agent execution loop. The emphasis is not on inventing more protocol
surface. It is on proving that assignment export, isolated session execution,
result packaging, review, replay, and metrics hold together against actual
agent runtimes.

Within this document, `milestone` names the user-visible delivery target and
`workstream` names an internal implementation grouping inside that milestone.

## Principles

- Preserve the Milestone 1 control boundary: no worker or agent adapter writes
  canonical ledger state directly.
- Prove end-to-end behavior with CLI smoke paths before expanding automation.
- Treat real-agent compatibility as a first-class runtime concern, not a
  footnote to protocol correctness.
- Keep semi-automatic execution auditable: every launched session must leave a
  deterministic result proposal, native logs, and explicit outcome metrics.
- Prefer one stable execution loop over many half-supported agent paths.

## Workstream 1: End-To-End Manual Harness

Goal: make the current runtime foundation runnable as a single documented loop.

### [ ] RM2-01: Manual Harness Golden Path

- Status: pending
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Labels: runtime, replay
- Target code:
  - `src/bureauless/cli/main.py`
  - `tests/test_harness.py`
- Target docs:
  - `docs/roadmap/development_roadmap.md`
- Work:
  - Add one canonical CLI smoke path that chains mission validate, workflow
    compile, gatekeeper ready, assignment export, result import, approval, and
    replay for the demo mission.
  - Keep the smoke path explicit instead of hiding it behind magic orchestration.
  - Record the expected files and state transitions at each step.
- Acceptance criteria:
  - A fresh workspace can run the golden path without hand-editing protocol
    artifacts.
  - The same path can be used as the baseline acceptance flow for Milestone 2.

### [ ] RM2-02: Demo Mission Fixture Tightening

- Status: pending
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Labels: runtime, protocol
- Target code:
  - `tests/test_harness.py`
  - `examples/`
- Work:
  - Consolidate one maintained runtime demo mission with stable ledger,
    workflow, assignment, and result fixtures.
  - Remove ambiguity between "example protocol snippets" and "the milestone
    acceptance demo".
  - Ensure the demo uses artifact hashes, approval gates, and replayed blocked
    reasons.
- Acceptance criteria:
  - Milestone acceptance fixtures are easy to locate and do not depend on ad
    hoc temp data.
  - Replay and gatekeeper assertions use the same demo mission.

## Workstream 2: Agent Compatibility Contract

Goal: prove that real agents can be driven predictably enough for the harness.

### [ ] RM2-03: Agent Compatibility Matrix

- Status: pending
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Labels: runtime
- Target code:
  - `src/bureauless/agents/registry.py`
  - `tests/test_harness.py`
- Target docs:
  - `docs/architecture/research_and_design_notes.md`
- Work:
  - Extend the agent registry and doctor outputs into a normalized
    compatibility matrix for `codex-cli`, `claude-code`, and `opencode`.
  - Capture whether each agent supports config isolation, provider/model
    override, output capture, timeout, cancellation, and working-directory
    control strongly, weakly, or not at all.
  - Surface which gaps block semi-automatic execution versus only degrade
    metrics confidence.
- Acceptance criteria:
  - The runtime can explain why a given agent is dispatchable, limited, or
    manual-only.
  - Doctor results are stable enough to gate launch policy.

### [ ] RM2-04: Native Result Extraction Contracts

- Status: pending
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, budget
- Target code:
  - `src/bureauless/runtime/sessions.py`
  - `tests/test_harness.py`
- Work:
  - Define per-agent extraction rules for native logs, exit reasons, changed
    files, patch bytes, token usage, and cost confidence.
  - Separate "unavailable because the agent does not emit it" from "missing due
    to wrapper failure".
  - Keep extraction rules session-level; do not normalize internal tool calls.
- Acceptance criteria:
  - Session summaries do not silently drop agent-native output.
  - Metrics confidence reflects the actual extraction path.

## Workstream 3: Isolated Session Runtime

Goal: run real agent sessions in bounded execution sandboxes.

### [ ] RM2-05: Session Workspace Isolation

- Status: pending
- Priority: high
- Recommended model: gpt-5.4
- Risk: high
- Labels: runtime
- Target code:
  - `src/bureauless/runtime/sessions.py`
  - `tests/test_harness.py`
- Work:
  - Add isolated session workspace preparation for assignment runs.
  - Support copy-based and worktree-based execution modes where available.
  - Record the workspace path, cleanup policy, and retained artifacts in the
    session record.
- Acceptance criteria:
  - A session can run without mutating canonical mission state files in place.
  - Cleanup preserves logs and accepted artifacts needed for audit.

### [ ] RM2-06: Timeout, Cancellation, And Supersession Runtime

- Status: pending
- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Labels: runtime, gatekeeper
- Target code:
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/runtime/replay.py`
  - `tests/test_harness.py`
- Work:
  - Connect live session timeout, cancellation, and supersession behavior to
    the Milestone 1 event model.
  - Ensure partial sessions still emit deterministic records and native logs.
  - Distinguish runtime interruption from agent-declared task blockage.
- Acceptance criteria:
  - Timed-out or cancelled sessions replay cleanly without corrupting ready
    state.
  - Superseded sessions remain auditable and do not masquerade as completed.

## Workstream 4: Result Packaging, Review, And Replay Loop

Goal: make semi-automatic execution feed the same approval and replay path as
manual imports.

### [ ] RM2-07: Session-To-Result Packaging

- Status: pending
- Priority: high
- Recommended model: gpt-5.4
- Risk: high
- Labels: runtime, artifact-integrity
- Target code:
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/protocol/results.py`
  - `tests/test_harness.py`
- Work:
  - Turn completed session records into import-ready result proposals with
    artifact refs, emitted events, metrics, and provenance.
  - Keep packaging deterministic so a rerun of the same session record produces
    the same proposal.
  - Reject packaging when required artifact hashes or assignment boundaries are
    missing.
- Acceptance criteria:
  - Semi-automatic sessions can reuse the same `result import` path as manual
    results.
  - Packaging failures are explicit and reviewable.

### [ ] RM2-08: Reviewable Runtime Demo

- Status: pending
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Labels: runtime, workbench
- Target code:
  - `src/bureauless/api/server.py`
  - `tests/test_server.py`
- Target docs:
  - `docs/roadmap/development_roadmap.md`
- Work:
  - Expose one documented runtime demo path that starts from an exported
    assignment, runs a bounded session, packages a result, imports it, and
    replays the updated ledger.
  - Keep approval explicit; do not auto-accept public findings.
  - Ensure the workbench can inspect the resulting ledger/replay state without
    custom fixture hacks.
- Acceptance criteria:
  - A real or fake agent session can be demonstrated end-to-end through the
    same runtime boundaries.
  - The workbench can inspect the resulting mission state using normal API
    endpoints.

## Workstream 5: Policy Activation On Stable Sessions

Goal: activate selection and budget policy only after the real session loop is
stable.

### [ ] RM2-09: Dispatch Readiness Policy

- Status: pending
- Priority: medium
- Recommended model: gpt-5.4
- Risk: medium
- Labels: runtime, budget
- Target code:
  - `src/bureauless/agents/registry.py`
  - `src/bureauless/runtime/sessions.py`
  - `tests/test_harness.py`
- Work:
  - Convert doctor output, compatibility data, and workspace isolation checks
    into a dispatch readiness decision.
  - Distinguish `dispatchable`, `manual_only`, and `blocked` execution states.
  - Surface structured reasons that policy code and the workbench can both use.
- Acceptance criteria:
  - Automatic launch is impossible when required control boundaries are weak or
    missing.
  - Readiness output is deterministic and machine-readable.

### [ ] RM2-10: Budget And Workflow Selection Activation

- Status: pending
- Priority: medium
- Recommended model: gpt-5.5
- Risk: medium
- Labels: runtime, budget, workflow-selection
- Target code:
  - `src/bureauless/protocol/budget.py`
  - `src/bureauless/runtime/metrics.py`
  - `tests/test_harness.py`
- Work:
  - Activate workflow-selection and budget checks on top of stable session
    records instead of predicted-only placeholders.
  - Use Milestone 2 session metrics to validate that cost and token policies
    are grounded in observed runtime behavior.
  - Keep advisor calls and routing logic deterministic.
- Acceptance criteria:
  - Budget and selection policy can reject or downgrade execution before
    dispatch.
  - Policy decisions cite both configured rules and observed session evidence.

## Milestone 2 Acceptance

Runtime milestone 2 is complete when:

- The Milestone 1 golden path is preserved as a documented CLI smoke flow.
- At least one supported external agent can run in an isolated session
  workspace and produce a deterministic result proposal.
- Timeout, cancellation, and supersession records replay cleanly.
- Session-native logs, metrics, and artifact provenance survive through result
  packaging and import.
- The workbench can inspect the resulting replay state without custom logic.
- Dispatch readiness and budget checks can block unsafe automatic execution
  without weakening the Milestone 1 control boundary.
