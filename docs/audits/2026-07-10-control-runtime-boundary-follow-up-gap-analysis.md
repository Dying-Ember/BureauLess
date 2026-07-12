# Control Runtime Boundary Follow-Up Gap Analysis

- Status: confirmed
- Audited baseline: `main` as of 2026-07-10
- Audit date: 2026-07-10
- Scope: runtime ownership cleanup needed to keep the control-runtime boundary
  maintainable in the current codebase
- Related task list:
  [`control_runtime_boundary_follow_up_tasklist.md`](../tasks/control_runtime_boundary_follow_up_tasklist.md)
- Owners: control-runtime boundary follow-up task list

## Executive Summary

The current runtime and protocol direction is consistent with the accepted
boundary: BureauLess owns control runtime while external agents own agent
runtime. The remaining gaps are no longer primarily semantic. They are
engineering-boundary and write-safety gaps that make that boundary harder to
maintain and easier to accidentally weaken.

This audit records the implementation debt that should be routed into future
task lists without expanding RFC-007 into a mixed architecture-plus-cleanup
document.

## Findings

### CRT-001: `runtime/sessions.py` Concentrates Too Many Ownership Areas

- Severity: medium
- Status: open
- Claim: control-runtime responsibilities should stay understandable and
  separable across lifecycle, dispatch, continuation, cancellation, result
  intake, and telemetry work.
- Evidence:
  [`src/bureauless/runtime/sessions.py`](../../src/bureauless/runtime/sessions.py)
  currently owns session models, launch preparation, process control,
  cancellation, continuation, result packaging, and provider-side telemetry
  capture.
- Impact: changes to telemetry, provider bindings, or dispatch behavior are
  more likely to regress lifecycle and cancellation semantics.
- Disposition: owned by CRT-001, which splits cohesive session ownership areas
  behind the existing entrypoints before another large runtime capability lands.
- Decision requirement: no new RFC required; this is engineering cleanup under
  the accepted control-runtime boundary.

### CRT-002: CLI And API Still Retain Too Much Orchestration

- Severity: medium
- Status: open
- Claim: CLI and API should stay transport-oriented while shared coordination
  lives behind application services.
- Evidence:
  [`src/bureauless/cli/main.py`](../../src/bureauless/cli/main.py) still owns
  substantial mission/demo orchestration and fixture generation;
  [`src/bureauless/api/server.py`](../../src/bureauless/api/server.py) still
  imports broad protocol/runtime surfaces directly.
- Impact: shared runtime use cases can drift across entrypoints, weakening the
  intended application boundary and making control-runtime flows harder to
  reason about.
- Disposition: owned by CRT-002, which moves shared control-plane and runtime
  coordination into application services.
- Decision requirement: no new RFC required unless the application boundary
  itself changes.

### CRT-003: YAML Ledger Writes Need Explicit Single-Writer Discipline

- Severity: high
- Status: closed
- Claim: canonical ledger history must not be vulnerable to silent lost updates
  as more CLI, API, and runtime paths append events.
- Evidence:
  current ledger writes still rely on direct file replacement patterns rather
  than an explicit single-writer protocol with expected-cursor guards and
  atomic replace semantics across all write paths.
- Impact: concurrent or overlapping writers can produce valid YAML with missing
  events, which is harder to detect than a corrupted file.
- Disposition: owned by CRT-003, which adds a guarded atomic ledger writer with
  stale-writer rejection, temporary-file write, `fsync`, and atomic replace.
- Decision requirement: implementation task by default; escalate to an RFC only
  if the write protocol itself changes replay or acceptance semantics.
- Closure evidence: `write_ledger()` now serializes writers with an exclusive
  lock, rejects a changed source identity, flushes the temporary file and parent
  directory, and atomically replaces the ledger. A stale-writer regression and
  the full suite passed (`269 passed`).

### CRT-004: Capability And Telemetry Confidence Need Clearer Surfacing

- Severity: low
- Status: open
- Claim: adapters with different control strength and telemetry quality should
  remain explicitly distinguishable.
- Evidence:
  capability and confidence concepts exist today in agent registry and runtime
  metrics, but they are not yet consistently surfaced as one coherent operator
  story across CLI, API, and future adapter work.
- Impact: future adapter additions may drift toward implied parity even when
  cancellation, continuation, or telemetry remain degraded.
- Disposition: owned by CRT-004, which reuses existing operator readers before
  adding any dedicated frontend surface.
- Decision requirement: no new RFC required under the accepted boundary.
