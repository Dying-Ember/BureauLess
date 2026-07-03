# BureauLess

[English](README.md) | **中文**

BureauLess 是一个本地优先的小型编排层，用来管理 DAG 形态的 agent 工作流。

BureauLess 不是 Agent。它是一套带 token 经济意识的 harness：判断何时值得使用
Agent，约束 Agent 能做什么，并记录哪些事实可信。

当前版本由 YAML protocol、Python runtime/API、CLI 工具和浏览器/Electron Workbench
组成，并已经维护一条通过 `codex-cli` 运行受限真实 Agent 的路径；更广泛的 provider 和
Agent 支持仍属于后续工作。

Agent workflow 的失败方式很像真实组织。有时，一个小 patch 被套上一整张组织架构图：
planner、reviewer、advisor、coordinator 都来了，每个角色都要读一遍同样的仓库上下文，
最后真正改动的可能只有几行。有时又反过来：一个过载的负责人同时指挥一群 worker，
没有中间层、没有 gate、没有可信 ledger，也说不清谁卡住了、谁完成了、哪个结果应该被相信。

BureauLess 是用来选择“足够小、但足够安全”的组织形态的 harness。一个边界清楚的
worker 能完成，就不要搭一整套组织；工作真的分叉时，也只增加那些证明自己值得存在的
结构：assignment、gate、artifact 校验、预算限制、可回放事件，以及决定共享事实的
ledger。

重点不只是当下把 Agent 管住。如果每个 assignment、gate、artifact、预算估计、模型选择
和结果都会变成持久数据，系统就可以 replay，也可以 backtest。跑得多了，真实数据会告诉你：
哪些 workflow 形态值得，哪些 advisor 调用真的回本，哪些 gate 抓住了真实风险，以及
哪些 policy 应该变得更简单。

## 为什么做它

很多 agent 系统天然会越长越大。BureauLess 反过来：先从一个边界清楚的 worker
开始，只有当证据说明协调成本值得时，才增加更多编排。

真正有用的问题不是“能召唤多少个 Agent？”，而是“哪些 Agent 工作安全、有用、可审计，
并且值得花这些 token？”

## 它做什么

这个项目把模型路由、任务依赖、review gate 和运行记录保存在 YAML 文件里，而不是
锁在某一次聊天上下文中。Codex、Claude 或其他模型可以担任 orchestrator，较小模型
负责执行边界清楚的任务节点。

- 校验 planning DAG、mission、workflow、ledger、assignment 和结构化 runtime artifact。
- 通过 replay 和 gatekeeper 规则推导 runnable、blocked、completed 和 superseded 状态。
- 导出有边界的 assignment，并通过隔离的 `codex-cli` session 维护一条真实 Agent
  执行路径。
- 把 result、review、routing decision、context delivery、telemetry 和 mutation decision
  记录为可检查的 artifact 与 ledger event。
- 提供本地 Workbench，用于 planning-DAG 编辑和 runtime 检查，同时保持 Python runtime
  规则权威。

## 快速开始

在新 checkout 中安装 Python 和 workspace 依赖：

```bash
uv sync --dev
npm install
```

在第一个终端启动 Python API：

```bash
npm run api:dev
```

在第二个终端启动浏览器 Workbench：

```bash
npm run web:dev
```

打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。API 默认使用
`http://127.0.0.1:8000`；如果端口被占用，`api:dev` 会选择其他本地端口，Web 启动器
会从 `.bureauless-api-url` 读取实际地址。

API 与 Web server 运行后，可以启动使用同一套 UI 的 Electron shell：

```bash
npm run desktop:dev
```

只检查 CLI 时可以运行：

```bash
uv run python -m bureauless mission validate examples/missions/demo/mission.yaml
uv run python -m bureauless workflow compile examples/missions/demo/workflows/coder_reviewer_committer.yaml
uv run python -m bureauless ledger replay \
  examples/missions/demo/workflows/coder_reviewer_committer.yaml \
  examples/missions/demo/ledger.yaml
uv run python -m bureauless mission execution-spine-acceptance \
  /tmp/bureauless-execution-spine
```

`execution-spine-acceptance` 会运行确定性的 Runtime M3.5 验收路径，并在目标
workspace 中写入遇错即失败的结构化证据报告。

运行当前维护的验证：

```bash
uv run python -m pytest -q
npm run web:build
npm run web:smoke
```

`web:smoke` 会由 Playwright 自动启动或复用 Vite dev server。

## 核心想法

### 源格式

DAG 文档和运行记录都使用 YAML。项目不会维护第二套持久化表示。

### 任务节点

一个节点描述一个有边界的工作单元：目标、依赖、相关文件、模型路由、review gate、
验证方式和 prompt contract。

### 运行记录

每次执行都会记录模型、commit、变更文件、验证结果和 review 状态。retry 和 audit
依赖这些记录。

### 审查门槛

节点可以自动通过，也可以要求 orchestrator review，或在下游节点变为可执行前要求
human review。

### 失败策略

失败是显式建模的：可以用同一模型重试、升级到更大模型、交给人类，或进一步拆分任务。

### Token 经济

每多雇一个 Agent，都要有预算理由。每请一个 advisor，更要有更强的理由。如果协调成本
高过节省，workflow 就应该变简单。

### 回放与回测

每次运行都应该留下足够结构化的证据，用来回放当时发生了什么，并回测另一套 policy
是否会做出更好的 routing、gate、model 或 advisor 决策。

### Orchestrator 与 Harness

长期架构会把控制平面和执行平面分开：

- orchestrator 负责规划、路由、记录、审查和重新规划。
- worker agent 执行有边界的任务。
- harness 强制执行 role、event、gate、budget policy 和 provenance。
- advisor 默认懒加载，并受预算 gate 约束。

简短版：Agent 可以干活，但不能自己写史。

## 建议流程

1. 定义或加载 planning DAG、mission、workflow 和 ledger。
2. 通过 Workbench 或 gatekeeper CLI 检查 runnable 与 blocked 状态。
3. 导出带必要 context 和 review policy 的有边界 assignment。
4. 手工执行，或通过受支持的 bounded session adapter 执行。
5. 导入并 review result，再记录 accepted finding 和 event。
6. replay ledger，只在下游 gate 满足后继续执行。

## 工作台

Workbench 同时处理 planning-DAG 编辑，以及 mission、workflow、ledger、replay、
gatekeeper、mutation、routing、outcome、evidence、context、telemetry、assignment、
result、turn-report 和 dispatch artifact 的 runtime 检查。它使用同一套 React UI 支持
浏览器和 Electron，Python 通过本地 FastAPI API 保持规则权威。

运行本地 API：

```bash
npm run api:dev
```

这个启动器会强制使用仓库自己的 `.venv`，所以即使你当前 shell 还挂着别的项目
的虚拟环境，也不会把 BureauLess 带偏。
如果 `8000` 端口已经被占用，它会自动顺延到下一个可用端口，并把实际 API 地址
写入 `.bureauless-api-url`。

运行浏览器工作台：

```bash
npm run web:dev
```

Vite dev server 会在启动时读取 `.bureauless-api-url`。如果 API 启动器从 `8000`
切到了别的端口，重启一次 `web:dev`，前端代理就会跟上新的 API 地址。

执行浏览器 smoke test：

```bash
npm run web:smoke
```

手工测试 Workbench 的 mutation Accept/Reject 链路前，先生成隔离 demo：

```bash
npm run mutation-demo:prepare
```

该命令只会重置 `.bureauless/mutation-demo`，不会修改 tracked 示例或真实 ledger，
并会输出带临时 workflow/ledger 路径的 Workbench URL。启动 `api:dev` 和
`web:dev` 后打开该地址即可测试。

运行 Electron shell：

```bash
npm run desktop:dev
```

Playwright 会自动启动或复用 Vite dev server。如果本地 npm 安装出来的 Electron
二进制不完整，启动器会自动回退到系统里的 `electron39` 这类可执行文件。UI 默认跟随
系统配色，也提供 `system / light / dark` 控制。DAG 文档和运行记录保持 YAML-only。

## 源码结构

现在 runtime/harness 代码按 ownership boundary 分组，不再平铺在一层模块里：

- `src/bureauless/protocol/`：YAML 协议模型、校验器、assignment/result 处理、
  artifact 完整性，以及 budget snapshot。
- `src/bureauless/runtime/`：replay、gatekeeper、session wrapper 和 outcome
  metrics。
- `src/bureauless/agents/`：外部 agent registry 和 doctor checks。
- `src/bureauless/api/`：Workbench 的 FastAPI API 入口。
- `src/bureauless/cli/`：CLI 入口。
- `src/bureauless/core.py`：旧版 DAG / run-record 原语，当前作为兼容层保留，
  新的 mission/workflow runtime 则围绕它逐步长出来。

## 文档

先从文档地图开始，再通过两个 milestone 索引查看当前交付状态：

- [`docs/README.md`](docs/README.md)
- [`docs/roadmap/development_roadmap.md`](docs/roadmap/development_roadmap.md)
- [`docs/tasks/runtime_harness_tasklist.md`](docs/tasks/runtime_harness_tasklist.md)
- [`docs/tasks/workbench_tasklist.md`](docs/tasks/workbench_tasklist.md)
- [`docs/rfcs/README.md`](docs/rfcs/README.md)
- [`docs/rfcs/004-temporal-replay-mutation-intake-and-retry-control.md`](docs/rfcs/004-temporal-replay-mutation-intake-and-retry-control.md)
- [`docs/protocol/harness_protocol.md`](docs/protocol/harness_protocol.md)
- [`docs/protocol/workflow_selection_policy.md`](docs/protocol/workflow_selection_policy.md)
- [`docs/protocol/advisor_policy.md`](docs/protocol/advisor_policy.md)
- [`docs/protocol/workflow_examples.md`](docs/protocol/workflow_examples.md)

现在文档统一使用一套术语：

- `milestone`：面向验收的交付目标
- `workstream`：某个 milestone 内部的实现分组

这样 runtime 和 workbench 的规划语言会保持一致，不会一边讲 phase，
另一边讲 milestone。

## 许可证

BureauLess 使用 Apache License 2.0。见 [LICENSE](LICENSE)。
