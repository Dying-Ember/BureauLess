# BureauLess

**English** | [中文](README.zh-CN.md)

[![CI](https://github.com/Dying-Ember/BureauLess/actions/workflows/ci.yml/badge.svg)](https://github.com/Dying-Ember/BureauLess/actions/workflows/ci.yml)

BureauLess is a local-first control and audit harness that sits outside coding
agent runtimes. It registers heterogeneous agents and provider routes under one
contract, dispatches bounded work, and records the evidence needed to inspect
and compare runs.

It is not an agent runtime, provider gateway, or credential broker. Codex CLI,
Claude Code, Gemini CLI, OpenCode, and Pi keep their own model loops, tools,
memory, streaming, and retries. BureauLess owns the boundary around them.

## Why BureauLess

Agent workflows often fail like organizations. A tiny patch gets an org chart:
planner, reviewer, advisor, and coordinator all reread the same repository
before one worker changes one file. Or the system fails in the opposite way:
one overloaded lead fans work out to many workers with no gates, trusted
ledger, or clear answer to who is blocked, who is done, and which result should
be believed.

BureauLess chooses the smallest coordination structure that can safely do the
job. If one bounded worker is enough, do not convene a company. When work truly
fans out, add only the assignments, gates, artifact checks, budgets, and roles
that earn their cost.

The goal is not only control during one run. Durable assignments, routing
decisions, model choices, gates, evidence, and outcomes make runs replayable and
backtestable. Over time, real data should show which workflow shapes were worth
it, which advisors paid for themselves, which gates caught risk, and where the
policy should become simpler.

The useful question is not "how many agents can we summon?" It is "which Agent
work is safe, useful, auditable, and worth the tokens?"

## The Boundary

| BureauLess owns | Agent runtime owns |
| --- | --- |
| Agent and route registration | Model and tool loops |
| Dispatch admission and isolated workspaces | Internal planning and memory |
| Child-only configuration and credential delivery | Provider streaming and retries |
| Native evidence retention and normalized facts | Tool implementation details |
| Independent verification, ledger, replay, and comparison | Its own interactive UX |

The rule is simple: agents may do work, but they do not get to write trusted
history.

## What Ships Today

### Cross-agent audit

- One registry for Codex CLI, Claude Code, Gemini CLI, OpenCode, and Pi.
- Explicit separation of Agent, Provider route, endpoint family, wire API,
  model, credential delivery, and adapter capability.
- Route-specific, one-shot child configuration without editing local Agent
  configuration files.
- Isolated workspace execution with native logs, workspace snapshots, diffs,
  usage/cost provenance, tool events, and append-only route observations.
- Harness-owned independent verification against a temporary copy of the
  Agent's final workspace.
- Benchmark identity v3 separates initial and realized context; paired-run
  comparisons support strict fixed-context and explicit adaptive-context modes
  while exposing treatment differences and uncontrolled confounders.
- Harness-owned dispatch decision candidates/rejections and scoped
  workspace/process/network/credential/payment coverage with explicit blind
  spots. Agent-internal decisions are not inferred.

The machine-readable source of current compatibility is:

```bash
uv run bureauless agent matrix --evidence
```

Do not infer support from an Agent name, provider brand, or a generic
"OpenAI-compatible" label. The exact route contract is authoritative.

### Workflow control plane

- YAML mission, workflow, ledger, assignment, result, review, routing, context,
  mutation, telemetry, and dispatch contracts.
- Deterministic validation, gatekeeping, replay, retry control, workflow
  versions, and authoritative result acceptance.
- The smallest valid coordination shape by default: one worker first, then
  reviews or DAG structure only when the evidence justifies the overhead.

### Workbench

- One React UI for browser and Electron.
- Planning-DAG editing plus runtime artifact, replay, gate, mutation, telemetry,
  and dispatch inspection.
- Python/FastAPI remains authoritative; the frontend does not reconstruct
  runtime policy.

## Design Philosophy

1. **Start with one bounded worker.** Add review, advisors, or a DAG only when
   task dependency, risk, or evidence justifies the coordination overhead.
2. **Coordination must earn its tokens.** Every extra Agent needs a budget
   reason; every advisor needs a stronger one. If coordination costs more than
   it saves, simplify the workflow.
3. **Evidence precedes shared truth.** Agent output is a proposal. Verification,
   review, and acceptance decide what enters the canonical ledger.
4. **Keep native evidence immutable.** Normalized facts make runs comparable,
   but never erase the original logs, workspace state, or provenance.
5. **Make failure explicit.** Retry, escalate, ask a human, split the task, or
   stop; do not silently repeat an unchanged attempt.
6. **Separate control from execution.** BureauLess owns admission, boundaries,
   evidence, and history. Agent runtimes retain their model/tool internals.
7. **Learn from runs, not demos.** Append-only records enable replay and
   backtesting; a fixture or attractive dashboard is not production evidence.

The core state model stays deliberately small:

| Concept | Purpose |
| --- | --- |
| Mission and workflow | Goal, roles, dependencies, emitted events, and gates |
| Assignment | Minimum context and authority for one bounded worker |
| Run record | Native evidence, workspace effects, metrics, and result proposal |
| Review and gate | Explicit acceptance policy before downstream progress |
| Ledger | Append-only accepted history used for deterministic replay |

## Quick Start

Install the locked development dependencies:

```bash
uv sync --dev
npm install
```

### Inspect the registry without credentials

```bash
uv run bureauless agent list
uv run bureauless agent matrix --evidence
uv run bureauless agent route claude-code --provider anthropic-compatible
```

### Materialize an audit without launching an Agent

```bash
WORKSPACE=$(mktemp -d)

uv run bureauless audit init \
  --workspace "$WORKSPACE" \
  --task "Create marker.txt and add a deterministic check"

uv run bureauless audit run \
  --workspace "$WORKSPACE" \
  --agent codex-cli \
  --target-model gpt-5 \
  --target-provider openai \
  --session-id audit-dry-run \
  --dry-run
```

This produces the same assignment → routing → registration → dispatch →
session → report → observation → archive chain as a live run, without invoking
an Agent or provider.

### Run a live route

Use an environment-variable name, never a key value, on the command line:

```bash
export AUDIT_PROVIDER_API_KEY=...

uv run bureauless audit run \
  --workspace /path/to/repository \
  --agent codex-cli \
  --target-model your-model \
  --target-provider openai-compatible \
  --provider-wire-api responses \
  --provider-base-url https://endpoint.example/v1 \
  --provider-api-key-env AUDIT_PROVIDER_API_KEY \
  --route-instance-id staging-responses \
  --cohort-id parser-benchmark-v1 \
  --verify-command 'python -m pytest -q'
```

Base-URL conventions differ by Agent and wire API. Use the
[canonical route commands](docs/protocol/agent_provider_registry.md#10-canonical-commands)
instead of adapting this example by guesswork.

### Inspect and compare evidence

```bash
uv run bureauless audit report path/to/session.yaml
uv run bureauless audit verify path/to/archive/manifest.yaml
uv run bureauless audit observations --workspace /path/to/repository
uv run bureauless metrics summarize /path/to/repository/.bureauless/runs

uv run bureauless audit contribution \
  baseline/session.yaml candidate/session.yaml \
  --capability-id workspace-edit \
  --invoked true
```

Capability contribution artifacts report measurable deltas; they deliberately
state `causal_claim: not_established`.

## Evidence Discipline

- Native output remains evidence; normalized fields never replace it.
- A tool event proves what an Agent reported doing. The workspace diff proves
  the final file state.
- Requested, CLI-reported, provider-reported, and independently attested model
  identities remain separate.
- Missing usage or currency cost stays missing; BureauLess does not estimate it.
- Latency and workspace delta are Harness facts. Token, cost, and tool-timeline
  comparisons retain their own provenance and eligibility.
- Secrets are not written to the registry. Only environment-variable names are
  recorded, and independent verification receives a scrubbed environment.

See the complete
[Agent/Provider registry contract](docs/protocol/agent_provider_registry.md)
and the latest dated
[endpoint capability evidence](docs/audits/2026-07-15-agent-endpoint-capability-matrix.md).

## Workbench

Start the API and browser UI in separate terminals:

```bash
npm run api:dev
npm run web:dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). If port `8000` is busy,
the API launcher selects another local port and records it in
`.bureauless-api-url` for the Web launcher.

Optional local surfaces:

```bash
npm run desktop:dev
npm run mutation-demo:prepare
npm run web:smoke
```

## Architecture in One Pass

```text
mission + workflow + ledger
            │
            ▼
 routing → bounded assignment → registered Agent route
            │
            ▼
 isolated child session → native evidence + workspace delta
            │
            ▼
 independent verification → review/acceptance → append-only ledger
            │
            ▼
 observations + metrics + replay/backtesting
```

Canonical state is YAML. The runtime validates and transitions it; the
Workbench displays it; external Agents never update it directly.

## Development

Run the maintained checks:

```bash
uv run python -m pytest -q
npm run web:build
npm run web:smoke
```

CI runs the backend suite on Python 3.10 and builds/smoke-tests the Web and
Electron applications on Node 24. CI never calls a real Agent or provider and
requires no provider secrets.

Source ownership follows the runtime boundary:

- `src/bureauless/agents/`: Agent registry, route evidence, and doctor checks.
- `src/bureauless/protocol/`: YAML contracts, validation, and artifact intake.
- `src/bureauless/runtime/`: sessions, replay, gatekeeper, metrics, and evidence.
- `src/bureauless/cli/`: operator commands, including `agent` and `audit`.
- `src/bureauless/api/`: local Workbench API.
- `web/` and `electron/`: browser and desktop shells.

## Documentation

| Need | Start here |
| --- | --- |
| Documentation authority and reading order | [`docs/README.md`](docs/README.md) |
| Stable Agent/Provider/evidence contract | [`docs/protocol/agent_provider_registry.md`](docs/protocol/agent_provider_registry.md) |
| Stable Harness protocol | [`docs/protocol/harness_protocol.md`](docs/protocol/harness_protocol.md) |
| Current implementation order | [`docs/roadmap/development_roadmap.md`](docs/roadmap/development_roadmap.md) |
| Dated live compatibility evidence | [`docs/audits/2026-07-15-agent-endpoint-capability-matrix.md`](docs/audits/2026-07-15-agent-endpoint-capability-matrix.md) |
| v0.4.0 release notes | [`docs/releases/v0.4.0.md`](docs/releases/v0.4.0.md) |
| v0.3.0 release notes | [`docs/releases/v0.3.0.md`](docs/releases/v0.3.0.md) |
| v0.2.0 release demo | [`live-demos/2026-07-16-agent-audit-v0.2.0/README.md`](live-demos/2026-07-16-agent-audit-v0.2.0/README.md) |
| Control-runtime boundary decision | [`docs/rfcs/007-control-runtime-boundary.md`](docs/rfcs/007-control-runtime-boundary.md) |

## License

BureauLess is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
