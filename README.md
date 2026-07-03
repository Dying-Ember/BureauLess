# BureauLess

**English** | [中文](README.zh-CN.md)

[![CI](https://github.com/Dying-Ember/BureauLess/actions/workflows/ci.yml/badge.svg)](https://github.com/Dying-Ember/BureauLess/actions/workflows/ci.yml)

BureauLess is a small, local-first orchestration layer for DAG-shaped agent
workflows.

BureauLess is not an agent. It is a token-aware harness for deciding when
agents are worth using, constraining what they may do, and recording what can
be trusted.

Today, BureauLess combines YAML protocols, a Python runtime/API, CLI tools, and
a browser/Electron workbench. It also maintains one bounded real-agent execution
path through `codex-cli`; broader provider and agent coverage remains future
work.

Agent workflows tend to fail in two familiar organizational ways. Sometimes a
tiny patch gets an org chart: planner, reviewer, advisor, coordinator, and
everyone reading the same repository context before one worker touches one
file. Sometimes it fails the other way: one overloaded lead fans work out to
many workers with no middle layer, no gates, no trusted ledger, and no clear
way to explain who is blocked, who is done, and which result should be believed.

BureauLess helps choose the smallest coordination structure that can safely do
the job. If one bounded worker is enough, do not convene a company. If the work
fans out, add only the structure that earns its keep: assignments, gates,
artifact checks, budget limits, replayable events, and a ledger that decides
what becomes shared truth.

The point is not just control in the moment. If every assignment, gate,
artifact, budget estimate, model choice, and outcome becomes durable data, the
system can be replayed and backtested. Over time, the goal is for real runs to
show which workflow shapes were worth it, which advisor calls paid for
themselves, which gates caught real risk, and where the policy should get
simpler.

## Why This Exists

Most agent systems are very eager to become bigger agent systems. BureauLess
goes the other way: start with one bounded worker, add coordination only when
the evidence says it is worth the cost.

The useful question is not "how many agents can we summon?" It is "which agent
work is safe, useful, auditable, and worth the tokens?"

## What It Does

It keeps model routing, task dependencies, review gates, and run records in
YAML files outside of any single chat session. Codex, Claude, or another model
can act as the orchestrator, while smaller models execute clearly bounded task
nodes.

- Validates planning DAGs, missions, workflows, ledgers, assignments, and
  structured runtime artifacts.
- Derives runnable, blocked, completed, and superseded state through replay and
  gatekeeper rules.
- Exports bounded assignments and can execute one maintained real-agent path
  through isolated `codex-cli` sessions.
- Records results, reviews, routing decisions, context delivery, telemetry, and
  mutation decisions as inspectable artifacts and ledger events.
- Provides a local Workbench for planning-DAG editing and runtime inspection
  without moving canonical runtime rules into the frontend.

## Quick Start

Install Python and workspace dependencies from a fresh checkout:

```bash
uv sync --dev
npm install
```

Start the Python API in the first terminal:

```bash
npm run api:dev
```

Start the browser Workbench in a second terminal:

```bash
npm run web:dev
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). The API normally uses
`http://127.0.0.1:8000`; if that port is busy, `api:dev` selects another local
port and the Web launcher reads it from `.bureauless-api-url`.

With the API and Web server running, the optional Electron shell uses the same
Workbench UI:

```bash
npm run desktop:dev
```

For a CLI-only sanity check:

```bash
uv run python -m bureauless mission validate examples/missions/demo/mission.yaml
uv run python -m bureauless workflow compile examples/missions/demo/workflows/coder_reviewer_committer.yaml
uv run python -m bureauless ledger replay \
  examples/missions/demo/workflows/coder_reviewer_committer.yaml \
  examples/missions/demo/ledger.yaml
uv run python -m bureauless mission execution-spine-acceptance \
  /tmp/bureauless-execution-spine
```

The execution-spine command runs the deterministic Runtime M3.5 acceptance
path and writes a failing-on-error evidence report into the target workspace.

Run the maintained checks with:

```bash
uv run python -m pytest -q
npm run web:build
npm run web:smoke
```

Playwright starts or reuses its own Vite dev server for `web:smoke`.

## Core Ideas

### Source Format

Both DAG documents and run records use YAML. The project does not maintain a
second persisted representation.

### Task Node

A node describes one bounded unit of work: goal, dependencies, files, model
routing, review gate, verification, and prompt contract.

### Run Record

Every execution records the model, commits, changed files, verification result,
and review status. This is what makes retries and audits possible.

### Review Gate

Nodes can be allowed to pass automatically, require orchestrator review, or
require human review before downstream nodes become ready.

### Failure Policy

Failures are explicit: retry with the same model, escalate to a larger model,
send to a human, or split the task further.

### Token Economy

Every extra agent needs a budget reason. Every advisor needs an even stronger
one. If coordination costs more than it saves, the workflow should get simpler.

### Replay And Backtesting

Runs should leave enough structured evidence to replay what happened and test
whether a different policy would have made a better routing, gate, model, or
advisor decision.

### Orchestrator And Harness

The long-term architecture separates the control plane from execution:

- The orchestrator plans, routes, records, reviews, and replans.
- Worker agents execute bounded tasks.
- The harness enforces roles, events, gates, budget policy, and provenance.
- Advisors are lazy and budget-gated.

The short version: agents can do work, but they do not get to write history.

## Suggested Flow

1. Define or load a planning DAG, mission, workflow, and ledger.
2. Inspect runnable and blocked state through the Workbench or gatekeeper CLI.
3. Export a bounded assignment with the required context and review policy.
4. Execute it manually or through a supported bounded session adapter.
5. Import and review the result, then record accepted findings and events.
6. Replay the ledger and continue only when downstream gates are satisfied.

## Workbench

The Workbench handles planning-DAG editing plus runtime inspection for mission,
workflow, ledger, replay, gatekeeper, mutation, routing, outcome, evidence,
context, telemetry, assignment, result, turn-report, and dispatch artifacts. It
uses one React UI for both browser and Electron. Python remains authoritative
through the local FastAPI API.

Run the local API:

```bash
npm run api:dev
```

This launcher always uses the repo-local `.venv`, so it still works even if
your shell currently has another project's virtual environment activated.
If port `8000` is already busy, it automatically picks the next free local
port and writes the chosen API URL to `.bureauless-api-url`.

Run the browser workbench:

```bash
npm run web:dev
```

The Vite dev server reads `.bureauless-api-url` when it starts. If the API
launcher had to move from `8000` to another port, restart `web:dev` once so
the proxy follows the new API address.

Run the browser smoke test:

```bash
npm run web:smoke
```

Prepare an isolated controlled-mutation demo before manually testing the
Workbench accept/reject flow:

```bash
npm run mutation-demo:prepare
```

The command resets only `.bureauless/mutation-demo`, validates no tracked demo
state, and prints a Workbench URL containing the disposable workflow and ledger
paths. Open that URL after `api:dev` and `web:dev` are running.

Run the Electron shell:

```bash
npm run desktop:dev
```

If the local npm Electron binary is incomplete, the launcher automatically falls
back to a system install such as `electron39`.

Playwright starts or reuses the Vite dev server. The UI follows the system color
scheme by default and also exposes `system / light / dark` controls. DAG
documents and run records remain YAML-only.

## Continuous Integration

GitHub Actions runs two deterministic checks for every pull request, every push
to `main`, merge-queue groups, and manual dispatches:

- `backend`: installs locked Python dependencies with uv on Python 3.10 and runs
  the complete pytest suite.
- `workbench`: installs locked npm dependencies on Node 24, builds the Web and
  Electron applications, installs Playwright Chromium, and runs the browser
  smoke suite.

CI does not invoke a real agent or model provider and requires no provider
secrets. After both checks have completed successfully in GitHub at least once,
the `main` ruleset should require `backend` and `workbench`, require pull
requests to be up to date, and block force pushes and branch deletion.

## Source Layout

The runtime/harness code is now grouped by ownership boundary instead of living
as one flat module shelf:

- `src/bureauless/protocol/`: YAML-backed protocol models, validators,
  assignment/result handling, artifact integrity, and budget snapshots.
- `src/bureauless/runtime/`: replay, gatekeeper, session wrapper, and outcome
  metrics.
- `src/bureauless/agents/`: external agent registry and doctor checks.
- `src/bureauless/api/`: FastAPI workbench API entrypoints.
- `src/bureauless/cli/`: CLI entrypoints.
- `src/bureauless/core.py`: legacy DAG/run-record primitives that remain as the
  compatibility layer while the newer mission/workflow runtime grows around it.

## Documentation

Start with the documentation map, then use the two milestone indexes for current
delivery status:

- [`docs/README.md`](docs/README.md)
- [`docs/roadmap/development_roadmap.md`](docs/roadmap/development_roadmap.md)
- [`docs/audits/README.md`](docs/audits/README.md)
- [`docs/audits/2026-07-02-runtime-execution-gap-analysis.md`](docs/audits/2026-07-02-runtime-execution-gap-analysis.md)
- [`docs/tasks/runtime_harness_tasklist.md`](docs/tasks/runtime_harness_tasklist.md)
- [`docs/tasks/runtime_harness_milestone_3_5_tasklist.md`](docs/tasks/runtime_harness_milestone_3_5_tasklist.md)
- [`docs/tasks/workbench_tasklist.md`](docs/tasks/workbench_tasklist.md)
- [`docs/rfcs/README.md`](docs/rfcs/README.md)
- [`docs/rfcs/004-temporal-replay-mutation-intake-and-retry-control.md`](docs/rfcs/004-temporal-replay-mutation-intake-and-retry-control.md)
- [`docs/rfcs/005-authoritative-result-acceptance-spine.md`](docs/rfcs/005-authoritative-result-acceptance-spine.md)
- [`docs/protocol/harness_protocol.md`](docs/protocol/harness_protocol.md)
- [`docs/protocol/workflow_selection_policy.md`](docs/protocol/workflow_selection_policy.md)
- [`docs/protocol/advisor_policy.md`](docs/protocol/advisor_policy.md)
- [`docs/protocol/workflow_examples.md`](docs/protocol/workflow_examples.md)

The docs now use one shared vocabulary:

- `milestone`: a user-visible delivery target
- `workstream`: an internal implementation grouping inside a milestone
- `audit`: evidence-backed capability gaps and their remediation ownership

That keeps runtime and workbench planning aligned instead of letting one side
talk in phases while the other talks in milestones.

## License

BureauLess is licensed under the Apache License 2.0. See [LICENSE](LICENSE).
