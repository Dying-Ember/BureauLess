# BureauLess

BureauLess is a small, local-first orchestration layer for DAG-shaped agent
workflows.

BureauLess is not an agent. It is a token-aware harness for deciding when
agents are worth using, constraining what they may do, and recording what can
be trusted.

Today, BureauLess defines and records the workflow protocol through YAML, CLI
tools, and a local workbench. It does not dispatch to model providers yet.

BureauLess 是一个本地优先的小型编排层，用来管理 DAG 形态的 agent 工作流。

BureauLess 不是 Agent。它是一套带 token 经济意识的 harness：判断何时值得使用
Agent，约束 Agent 能做什么，并记录哪些事实可信。

当前版本主要通过 YAML、CLI 工具和本地 workbench 定义并记录 workflow protocol；它还
不会直接 dispatch 到模型供应商。

Agent workflows tend to fail in two familiar organizational ways. Sometimes a
tiny patch gets an org chart: planner, reviewer, advisor, coordinator, and
everyone reading the same repository context before one worker touches one
file. Sometimes it fails the other way: one overloaded lead fans work out to
many workers with no middle layer, no gates, no trusted ledger, and no clear
way to explain who is blocked, who is done, and which result should be believed.

Agent workflow 的失败方式很像真实组织。有时，一个小 patch 被套上一整张组织架构图：
planner、reviewer、advisor、coordinator 都来了，每个角色都要读一遍同样的仓库上下文，
最后真正改动的可能只有几行。有时又反过来：一个过载的负责人同时指挥一群 worker，
没有中间层、没有 gate、没有可信 ledger，也说不清谁卡住了、谁完成了、哪个结果应该被相信。

BureauLess helps choose the smallest coordination structure that can safely do
the job. If one bounded worker is enough, do not convene a company. If the work
fans out, add only the structure that earns its keep: assignments, gates,
artifact checks, budget limits, replayable events, and a ledger that decides
what becomes shared truth.

BureauLess 是用来选择“足够小、但足够安全”的组织形态的 harness。一个边界清楚的
worker 能完成，就不要搭一整套组织；工作真的分叉时，也只增加那些证明自己值得存在的
结构：assignment、gate、artifact 校验、预算限制、可回放事件，以及决定共享事实的
ledger。

The point is not just control in the moment. If every assignment, gate,
artifact, budget estimate, model choice, and outcome becomes durable data, the
system can be replayed and backtested. Over time, the goal is for real runs to
show which workflow shapes were worth it, which advisor calls paid for
themselves, which gates caught real risk, and where the policy should get
simpler.

重点不只是当下把 Agent 管住。如果每个 assignment、gate、artifact、预算估计、模型选择
和结果都会变成持久数据，系统就可以 replay，也可以 backtest。跑得多了，真实数据会告诉你：
哪些 workflow 形态值得，哪些 advisor 调用真的回本，哪些 gate 抓住了真实风险，以及
哪些 policy 应该变得更简单。

## Why This Exists / 为什么做它

Most agent systems are very eager to become bigger agent systems. BureauLess
goes the other way: start with one bounded worker, add coordination only when
the evidence says it is worth the cost.

很多 agent 系统天然会越长越大。BureauLess 反过来：先从一个边界清楚的 worker
开始，只有当证据说明协调成本值得时，才增加更多编排。

The useful question is not "how many agents can we summon?" It is "which agent
work is safe, useful, auditable, and worth the tokens?"

真正有用的问题不是“能召唤多少个 Agent？”，而是“哪些 Agent 工作安全、有用、可审计，
并且值得花这些 token？”

## What It Does / 它做什么

It keeps model routing, task dependencies, review gates, and run records in
YAML files outside of any single chat session. Codex, Claude, or another model
can act as the orchestrator, while smaller models execute clearly bounded task
nodes.

这个项目把模型路由、任务依赖、review gate 和运行记录保存在 YAML 文件里，而不是
锁在某一次聊天上下文中。Codex、Claude 或其他模型可以担任 orchestrator，较小模型
负责执行边界清楚的任务节点。

- Validates YAML DAG task files.
- Lists nodes that are ready to run.
- Renders per-node prompts with recommended model and review rules.
- Records execution results as YAML files in `runs/`.
- Supports review gates and retry/escalation policy as first-class metadata.

- 校验 YAML DAG 任务文件。
- 列出当前可执行的节点。
- 为每个节点渲染 prompt，并附带推荐模型和 review 规则。
- 把执行结果记录为 `runs/` 下的 YAML 文件。
- 把 review gate、retry 和 escalation policy 当作一等元数据处理。

The first durable layer is the protocol. Provider-specific dispatch can come
later, after the rules are boring enough to trust.

第一层先把协议做稳；具体 provider 的 dispatch 可以晚点再接，等规则足够无聊、足够
可信之后再说。

## Quick Start / 快速开始

```bash
uv run python -m bureauless validate examples/optimization_dag.yaml
uv run python -m bureauless mission validate examples/missions/demo/mission.yaml
uv run python -m bureauless workflow compile examples/missions/demo/workflows/coder_reviewer_committer.yaml
uv run python -m bureauless ready examples/optimization_dag.yaml
uv run python -m bureauless prompt examples/optimization_dag.yaml baseline-inventory
uv run python -m bureauless record examples/optimization_dag.yaml baseline-inventory \
  --model gpt-5-mini \
  --status passed \
  --output-commit abc1234 \
  --changed-file docs/baseline.md \
  --verification "pytest -q"
uv run python -m bureauless review examples/optimization_dag.yaml field-resolver-skeleton \
  --status orchestrator_approved
```

Use `uv run` from a fresh checkout:

新 checkout 后可以直接用 `uv run`：

```bash
uv run python -m bureauless ready examples/optimization_dag.yaml
```

After installing the package, the equivalent command is:

安装 package 后，等价命令是：

```bash
bureauless ready examples/optimization_dag.yaml
```

## Core Ideas / 核心想法

### Source Format / 源格式

Both DAG documents and run records use YAML. The project does not maintain a
second persisted representation.

DAG 文档和运行记录都使用 YAML。项目不会维护第二套持久化表示。

### Task Node / 任务节点

A node describes one bounded unit of work: goal, dependencies, files, model
routing, review gate, verification, and prompt contract.

一个节点描述一个有边界的工作单元：目标、依赖、相关文件、模型路由、review gate、
验证方式和 prompt contract。

### Run Record / 运行记录

Every execution records the model, commits, changed files, verification result,
and review status. This is what makes retries and audits possible.

每次执行都会记录模型、commit、变更文件、验证结果和 review 状态。retry 和 audit
依赖这些记录。

### Review Gate / 审查门槛

Nodes can be allowed to pass automatically, require orchestrator review, or
require human review before downstream nodes become ready.

节点可以自动通过，也可以要求 orchestrator review，或在下游节点变为可执行前要求
human review。

### Failure Policy / 失败策略

Failures are explicit: retry with the same model, escalate to a larger model,
send to a human, or split the task further.

失败是显式建模的：可以用同一模型重试、升级到更大模型、交给人类，或进一步拆分任务。

### Token Economy / Token 经济

Every extra agent needs a budget reason. Every advisor needs an even stronger
one. If coordination costs more than it saves, the workflow should get simpler.

每多雇一个 Agent，都要有预算理由。每请一个 advisor，更要有更强的理由。如果协调成本
高过节省，workflow 就应该变简单。

### Replay And Backtesting / 回放与回测

Runs should leave enough structured evidence to replay what happened and test
whether a different policy would have made a better routing, gate, model, or
advisor decision.

每次运行都应该留下足够结构化的证据，用来回放当时发生了什么，并回测另一套 policy
是否会做出更好的 routing、gate、model 或 advisor 决策。

### Orchestrator And Harness / Orchestrator 与 Harness

The long-term architecture separates the control plane from execution:

长期架构会把控制平面和执行平面分开：

- The orchestrator plans, routes, records, reviews, and replans.
- Worker agents execute bounded tasks.
- The harness enforces roles, events, gates, budget policy, and provenance.
- Advisors are lazy and budget-gated.

- orchestrator 负责规划、路由、记录、审查和重新规划。
- worker agent 执行有边界的任务。
- harness 强制执行 role、event、gate、budget policy 和 provenance。
- advisor 默认懒加载，并受预算 gate 约束。

The short version: agents can do work, but they do not get to write history.

简短版：Agent 可以干活，但不能自己写史。

## Suggested Flow / 建议流程

1. Write or generate a DAG file.
2. Run `ready` to find parallelizable tasks.
3. Render prompts for ready tasks.
4. Send each prompt to the chosen model or thread.
5. Record the result.
6. Review gated nodes.
7. Repeat until the DAG is complete.

1. 编写或生成 DAG 文件。
2. 运行 `ready` 找出可并行的任务。
3. 为 ready 任务渲染 prompt。
4. 把 prompt 发送给选定模型或线程。
5. 记录执行结果。
6. 审查带 gate 的节点。
7. 重复直到 DAG 完成。

## Workbench / 工作台

The workbench is the place to inspect DAG state, runs, gates, and records before
more execution is automated. It uses one React UI for both browser and Electron.
Python remains the source of DAG behavior through a local FastAPI API.

Workbench 用来在自动化更多执行之前，先看清 DAG state、run、gate 和 record。它使用
同一套 React UI 支持浏览器和 Electron。DAG 行为仍由 Python 通过本地 FastAPI API
提供。

Install dependencies:

安装依赖：

```bash
uv sync --dev
npm install
```

Run the local API:

运行本地 API：

```bash
uv run uvicorn bureauless.server:app --reload
```

Run the browser workbench:

运行浏览器工作台：

```bash
npm run web:dev
```

Run the browser smoke test after the API and web server are running:

API 和 web server 运行后，可以执行浏览器 smoke test：

```bash
npm run web:smoke
```

Run the Electron shell:

运行 Electron shell：

```bash
npm run desktop:dev
```

The UI follows the system color scheme by default and also exposes
`system / light / dark` controls. DAG documents and run records remain YAML-only.

UI 默认跟随系统配色，也提供 `system / light / dark` 控制。DAG 文档和运行记录保持
YAML-only。

## Documentation / 文档

Design notes, protocol drafts, and roadmap live here:

设计笔记、协议草案和路线图在这里：

- [`docs/README.md`](docs/README.md)
- [`docs/roadmap/development_roadmap.md`](docs/roadmap/development_roadmap.md)
- [`docs/architecture/research_and_design_notes.md`](docs/architecture/research_and_design_notes.md)
- [`docs/architecture/orchestrator_system_prompt.md`](docs/architecture/orchestrator_system_prompt.md)
- [`docs/architecture/context_economy.md`](docs/architecture/context_economy.md)
- [`docs/protocol/harness_protocol.md`](docs/protocol/harness_protocol.md)
- [`docs/protocol/workflow_selection_policy.md`](docs/protocol/workflow_selection_policy.md)
- [`docs/protocol/advisor_policy.md`](docs/protocol/advisor_policy.md)
- [`docs/protocol/workflow_examples.md`](docs/protocol/workflow_examples.md)
