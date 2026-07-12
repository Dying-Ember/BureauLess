# Control Runtime Boundary Follow-Up Task List

Status: planned engineering cleanup. This is not a delivery milestone: it
closes implementation debt identified after the control-runtime boundary was
documented.

Sources: [`RFC-007`](../rfcs/007-control-runtime-boundary.md),
[`ADR-007`](../adrs/007-control-runtime-boundary/README.md), and the
[`control-runtime follow-up audit`](../audits/2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md).

## Scope

- Preserve the established boundary: BureauLess owns control invariants;
  adapters own agent-runtime mechanisms.
- Do not create a new runtime or Workbench milestone.
- Do not add an adapter, provider mesh, or frontend-owned control path.

## Tasks

### [x] CRT-000: Resolve RFC-007 And ADR-007 Status

- Priority: high
- Recommended model: gpt-5.5
- Risk: low
- Dependencies: none
- Target docs:
  - `docs/rfcs/007-control-runtime-boundary.md`
  - `docs/adrs/007-control-runtime-boundary/`
  - `docs/protocol/harness_protocol.md`
- Work:
  - Confirm or revise the proposed ownership and telemetry-evidence decisions,
    then mark the RFC and ADRs consistently.
- Acceptance criteria:
  - RFC, ADRs, protocol, audit, and this list agree on what is invariant versus
    adapter mechanism.
- Completion evidence:
  - RFC-007 and ADR-007.1/.2 were accepted on 2026-07-12.
  - GitHub issue [#9](https://github.com/Dying-Ember/BureauLess/issues/9) was
    closed as the resolved decision record; this task list owns the remaining
    implementation debt.
  - Bootstrap replan behavior is covered by focused regression
    (`3 passed`) and v12 records a real provider bootstrap-to-commit run.

### [x] CRT-003: Guard Canonical Ledger Writes

- Priority: critical
- Recommended model: gpt-5.5
- Risk: high
- Dependencies: CRT-000
- Target code:
  - `src/bureauless/protocol/ledger.py`
  - ledger-writing callers in `src/bureauless/application/`,
    `src/bureauless/cli/`, and `src/bureauless/api/server.py`
  - `tests/`
- Work:
  - Route canonical writes through one guarded writer that verifies the
    caller's expected ledger cursor or content identity, flushes a temporary
    file, and atomically replaces the ledger.
  - Reject stale writers with a structured conflict; never overwrite by retry.
- Acceptance criteria:
  - Two writers based on one ledger revision cannot silently lose an event.
  - All maintained canonical write paths use the guard.
  - Non-conflicting replay and acceptance behavior remains deterministic.
- Completion evidence:
  - Loaded ledgers retain a non-persistent source SHA-256 and path; the shared
    writer checks them under an exclusive file lock before atomic replacement.
  - The writer flushes the temporary file and parent directory, and returns the
    new source identity for consecutive writes in one flow.
  - Stale-write regression and the full suite passed (`269 passed`).

### [ ] CRT-001: Reduce Session Ownership Concentration

- Priority: high
- Recommended model: gpt-5.5
- Risk: high
- Dependencies: CRT-003
- Target code:
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/runtime/`
  - `tests/test_harness.py`
- Work:
  - Characterize lifecycle, continuation, cancellation, packaging, and
    telemetry behavior before extraction.
  - Move one cohesive ownership area at a time behind existing session
    entrypoints; retain adapters at the translation edge.
- Acceptance criteria:
  - `sessions.py` no longer directly owns every lifecycle, evidence, and
    telemetry concern.
  - Dispatch, cancellation, continuation, packet hashing, result packaging,
    and provider-usage regressions remain covered.
  - No speculative adapter interface or new runtime layer is added.

### [ ] CRT-002: Extract Shared Runtime Orchestration

- Priority: high
- Recommended model: gpt-5.5
- Risk: medium
- Dependencies: CRT-003
- Target code:
  - `src/bureauless/application/`
  - `src/bureauless/cli/main.py`
  - `src/bureauless/api/server.py`
  - `tests/`
- Work:
  - Move shared control-plane bootstrap and live-runtime coordination from CLI
    and API entrypoints into existing application-service patterns.
- Acceptance criteria:
  - Equivalent CLI and API flows produce the same canonical artifacts and
    structured failures.
  - Entry points retain parsing/transport responsibility only.
  - The validated v12 bootstrap-to-commit path remains reproducible.

### [ ] CRT-004: Surface Capability And Telemetry Confidence

- Priority: medium
- Recommended model: gpt-5.4
- Risk: low
- Dependencies: CRT-001, CRT-002
- Target code:
  - `src/bureauless/agents/registry.py`
  - `src/bureauless/runtime/metrics.py`
  - existing CLI/API metrics and doctor readers
  - `apps/web/` only if those readers cannot expose the distinction clearly
- Work:
  - Reuse existing doctor, metrics, and run-bundle readers to show control
    capability plus telemetry source/confidence.
  - Keep provider-authoritative, agent-native observed, transport-observed,
    locally estimated, unavailable, and degraded states explicit.
- Acceptance criteria:
  - Operators can distinguish control degradation from missing telemetry.
  - No agent-brand-specific workflow/ledger semantics or frontend write path is
    introduced.

### [ ] CRT-005: Close The Audit

- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: CRT-001 through CRT-004
- Target docs and tests:
  - `docs/audits/2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md`
  - `docs/protocol/harness_protocol.md`
  - `docs/roadmap/development_roadmap.md`
  - `tests/`
- Work:
  - Add maintained regression evidence for the four findings and record closure
    evidence in the audit.
- Acceptance criteria:
  - The audit can move to `closed` without broadening the product boundary.

## Execution Order

1. CRT-000 decision status
2. CRT-003 guarded writer
3. CRT-001 session split and CRT-002 application extraction
4. CRT-004 evidence surfacing
5. CRT-005 audit closure
