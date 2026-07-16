# Documentation Map

This directory separates stable contracts, current plans, dated evidence, and
historical decisions. Do not use the newest-looking document when a more
authoritative layer exists.

## Authority Order

| Layer | Answers | Update rule |
| --- | --- | --- |
| Source, tests, and immutable run artifacts | What actually happened? | Never broaden a claim beyond reproducible evidence. |
| `protocol/` | What does BureauLess promise and validate now? | Update with shipped behavior. |
| `audits/` | What was observed on a named date/version/route? | Append or supersede; preserve provenance. |
| `roadmap/` and `tasks/` | What is current or next? | Keep status aligned with implementation. |
| `adrs/` | What decision was accepted? | Preserve; supersede with another ADR. |
| `rfcs/` | What design was proposed and discussed? | Keep as design history after acceptance. |
| `architecture/` | Why is the system shaped this way? | Update only when long-lived reasoning changes. |

For Agent compatibility, the live machine-readable view is authoritative over
prose summaries:

```bash
uv run bureauless agent matrix --evidence
uv run bureauless audit observations --workspace /path/to/repository
```

## Start by Goal

| Goal | Read first | Then |
| --- | --- | --- |
| Run or compare coding Agents | [`protocol/agent_provider_registry.md`](protocol/agent_provider_registry.md) | Latest compatibility audit below |
| Change dispatch, evidence, ledger, or replay | [`protocol/harness_protocol.md`](protocol/harness_protocol.md) | Runtime task index and relevant ADR |
| Understand the Agent/runtime ownership line | [`rfcs/007-control-runtime-boundary.md`](rfcs/007-control-runtime-boundary.md) | [`adrs/007-control-runtime-boundary/README.md`](adrs/007-control-runtime-boundary/README.md) |
| Work on current priorities | [`roadmap/development_roadmap.md`](roadmap/development_roadmap.md) | Relevant task index |
| Investigate a claimed capability gap | [`audits/README.md`](audits/README.md) | Relevant dated audit |
| Change the Workbench | [`tasks/workbench_tasklist.md`](tasks/workbench_tasklist.md) | Matching Workbench milestone |

## Stable Protocols

- [`protocol/agent_provider_registry.md`](protocol/agent_provider_registry.md):
  Agent, Provider route, endpoint family, wire API, model addressing,
  credentials, adapter isolation, telemetry, evidence, and comparison contract.
- [`protocol/harness_protocol.md`](protocol/harness_protocol.md): mission,
  workflow, ledger, assignment, result, event, gate, context, mutation,
  telemetry, lifecycle, and acceptance invariants.
- [`protocol/workflow_selection_policy.md`](protocol/workflow_selection_policy.md):
  deterministic rules for choosing the smallest valid workflow shape.
- [`protocol/advisor_policy.md`](protocol/advisor_policy.md): budget-gated
  advisor policy and first-run heuristics.
- [`protocol/workflow_examples.md`](protocol/workflow_examples.md): canonical
  workflow examples used by implementation and tests.

## Dated Evidence

- [`audits/2026-07-15-agent-endpoint-capability-matrix.md`](audits/2026-07-15-agent-endpoint-capability-matrix.md):
  latest isolated Agent×endpoint mutation and telemetry evidence.
- [`audits/2026-07-13-agent-provider-compatibility.md`](audits/2026-07-13-agent-provider-compatibility.md):
  initial Codex, Claude Code, Gemini, OpenCode, and Pi compatibility record.
- [`audits/2026-07-11-live-demo-control-plane-bootstrap-gap.md`](audits/2026-07-11-live-demo-control-plane-bootstrap-gap.md):
  verified provider-backed control-plane bootstrap remediation.
- [`audits/2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md`](audits/2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md):
  RFC-007 implementation-debt audit.
- [`audits/2026-07-02-runtime-execution-gap-analysis.md`](audits/2026-07-02-runtime-execution-gap-analysis.md):
  closed real-Agent execution-spine audit.

[`audits/README.md`](audits/README.md) defines the difference between a gap
analysis and a compatibility/verification record, plus evidence and closure
rules.

## Delivery State

- [`roadmap/development_roadmap.md`](roadmap/development_roadmap.md): current
  position, priorities, milestone history, and non-goals.
- [`tasks/runtime_harness_tasklist.md`](tasks/runtime_harness_tasklist.md):
  runtime/harness milestone index.
- [`tasks/workbench_tasklist.md`](tasks/workbench_tasklist.md): Workbench
  milestone index.
- [`tasks/control_runtime_boundary_follow_up_tasklist.md`](tasks/control_runtime_boundary_follow_up_tasklist.md):
  accepted RFC-007 cleanup debt.
- [`tasks/engineering_boundary_refactor_tasklist.md`](tasks/engineering_boundary_refactor_tasklist.md):
  implemented package-boundary refactor history.

Individual milestone task lists remain under `tasks/`; start from an index
instead of guessing which historical milestone is current.

## Releases

- [`releases/v0.3.0.md`](releases/v0.3.0.md): evidence-contract v2 release
  notes, controlled benchmark identity, decision candidates, and scoped
  side-effect coverage.
- [`releases/v0.2.0.md`](releases/v0.2.0.md): cross-agent audit release notes,
  implemented route summary, evidence boundary, demo, and known limitations.

## Decisions and Design History

- [`rfcs/README.md`](rfcs/README.md): proposal index and RFC lifecycle.
- [`adrs/README.md`](adrs/README.md): accepted-decision archive and
  supersession rules.
- [`architecture/context_economy.md`](architecture/context_economy.md): token
  economy and coordination-overhead principles.
- [`architecture/research_and_design_notes.md`](architecture/research_and_design_notes.md):
  external research and long-lived design rationale.
- [`architecture/orchestrator_system_prompt.md`](architecture/orchestrator_system_prompt.md):
  orchestrator control-plane prompt draft.

## Source Ownership

- `src/bureauless/agents/`: Agent registry, route evidence, and doctor checks.
- `src/bureauless/protocol/`: protocol loaders, validation, artifact integrity,
  assignment export, and result intake.
- `src/bureauless/runtime/`: sessions, replay, gatekeeper, metrics, and evidence.
- `src/bureauless/cli/`: operator commands.
- `src/bureauless/api/`: local Workbench API.
- `web/` and `electron/`: browser and desktop operator surfaces.

When behavior changes, update source/tests and the matching stable protocol in
the same change. Add a dated audit when the claim depends on a specific Agent
version or endpoint instance. Do not rewrite an RFC, ADR, or completed task list
to make old history look current.
