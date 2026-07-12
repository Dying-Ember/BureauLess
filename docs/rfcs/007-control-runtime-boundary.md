# RFC-007: Control Runtime Boundary

## Status

Accepted on 2026-07-12.

ADR archive:
[`docs/adrs/007-control-runtime-boundary/`](../adrs/007-control-runtime-boundary/)

Accepted ADRs:
[`001-control-runtime-ownership.md`](../adrs/007-control-runtime-boundary/001-control-runtime-ownership.md)
and
[`002-telemetry-evidence-levels.md`](../adrs/007-control-runtime-boundary/002-telemetry-evidence-levels.md)

Related audit:
[`2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md`](../audits/2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md)

Implementation tracking:
[`control_runtime_boundary_follow_up_tasklist.md`](../tasks/control_runtime_boundary_follow_up_tasklist.md)

Tracking issue:
[#9 RFC-007: Control Runtime Boundary (closed)](https://github.com/Dying-Ember/BureauLess/issues/9)

## Decision

Accept ADR-007.1 and ADR-007.2: BureauLess owns the control runtime needed to
enforce workflow and ledger invariants, while adapters retain agent-runtime
mechanisms. Telemetry remains source- and confidence-qualified evidence.

## Problem

BureauLess now controls more of the real execution path: validated dispatch,
isolated sessions, bounded context continuation, result staging, cancellation,
retry control, telemetry attribution, and replay. That progress makes one
boundary more important than before:

> Which part of runtime belongs to BureauLess, and which part must remain owned
> by external agent runtimes?

Without a crisp answer, future work can drift in two bad directions:

1. Treat BureauLess as a document-only harness that validates before and after
   execution but does not authoritatively control live execution boundaries.
2. Treat BureauLess as a full agent runtime that owns model loops, tool
   execution, memory, compaction, and provider interaction details.

The first is too weak to enforce the governance invariants the project now
claims. The second expands BureauLess into the wrong product.

## Goals

1. Define the runtime boundary BureauLess must own in order to enforce its
   governance invariants.
2. Keep external agent runtimes responsible for their own internal execution
   loops and provider-specific mechanisms.
3. Give adapter work a stable rule: support many agents without making the core
   protocol or runtime specific to one of them.
4. Make telemetry and context control fit the same boundary model as dispatch,
   lifecycle, and result acceptance.

## Non-Goals

- Building a unified agent loop inside BureauLess.
- Standardizing every agent-native event, tool call, or provider protocol.
- Forcing all agents to expose the same runtime capabilities.
- Replacing adapter-specific mechanisms with one universal execution backend.
- Reopening already accepted semantics for bounded context continuation,
  authoritative result acceptance, or workflow mutation.

## Boundary

### BureauLess Owns Control Runtime

BureauLess must own the execution boundary required to keep workflow and ledger
invariants true during a live run. This control runtime includes:

1. Pre-launch control:
   assignment validity, workflow/version compatibility, gate checks, routing
   legality, budget policy, and adapter capability checks.
2. Execution envelope:
   workspace selection, isolation mode, sandbox shape, timeout, target model
   and provider binding, bounded context, and output/evidence roots.
3. Lifecycle supervision:
   prepared, started, running, cancel requested, timed out, completed, failed,
   blocked, and superseded states, plus best-effort cancellation and evidence
   retention.
4. Context brokering:
   validating scoped context requests, enforcing token and artifact limits, and
   recording canonical request/resolution lifecycle.
5. Evidence capture:
   collecting the minimum trustworthy execution evidence needed for replay,
   review, telemetry, and acceptance.
6. Result intake and canonical transition:
   validating worker outputs, staging proposals, applying review/acceptance
   policy, and deciding what becomes canonical ledger history.

### External Agents Own Agent Runtime

External agent runtimes own their internal execution machinery, including:

- model invocation loops;
- tool-calling internals;
- internal planning and compaction;
- memory systems;
- provider streaming and retry strategies;
- terminal, browser, or editor tool implementations.

BureauLess may wrap, inspect, and constrain these runtimes at the assignment,
session, and result boundary. It must not become their replacement.

## Invariants And Mechanisms

The core rule is:

> BureauLess owns invariants; adapters own mechanisms.

BureauLess defines what must be true. Adapters define how a specific runtime
achieves it.

Examples:

- Invariant: a worker must not write canonical ledger state directly.
  Mechanism: read-only mounts, path isolation, API separation, or restricted
  filesystem exposure.
- Invariant: a worker may receive only bounded assignment-scope context.
  Mechanism: prompt injection, session resume payloads, MCP-backed disclosure,
  or adapter-specific continuation transport.
- Invariant: cancellation and supersession must be reflected in session state.
  Mechanism: signal handling, process-group termination, runtime-native cancel
  APIs, or degraded manual-stop semantics.

The protocol should not be rewritten to match one adapter's preferred
mechanism when the invariant can stay stable across runtimes.

## Adapter Rules

### Capability-First Core

Core runtime and policy code should reason in terms of capabilities and control
levels, not agent brands or ad hoc adapter branches.

### Translation At The Edge

Adapters translate BureauLess artifacts such as assignments, dispatch packets,
context resolutions, and result proposals into runtime-specific inputs and
outputs. They must not introduce adapter-specific semantics into the core
workflow, ledger, or acceptance model.

### Honest Degradation

Not every adapter can provide the same cancellation, telemetry, continuation,
or structured-result guarantees. BureauLess should expose those differences as
explicit capability and confidence levels rather than pretending every adapter
is equally observable or controllable.

## Telemetry Boundary

Telemetry follows the same rule: BureauLess should capture and classify
trustworthy evidence at the control boundary without pretending to own every
internal agent event.

Telemetry sources may be:

1. provider-authoritative;
2. agent-native observed;
3. transport-observed;
4. locally estimated;
5. unavailable.

Metrics should preserve source and confidence explicitly. Missing trusted
evidence must remain missing rather than being filled with guessed precision.

## Consequences

- BureauLess can keep expanding adapter support without turning the core into a
  provider or agent runtime framework.
- Runtime work should prefer stronger control envelopes and clearer evidence
  boundaries over deeper entanglement with one agent's internal loop.
- Capability reporting, context control, cancellation, telemetry, and result
  intake become one coherent boundary rather than unrelated features.
- Implementation debt such as oversized session, CLI, or API modules belongs in
  audits and task lists rather than in this boundary decision itself.
