# BureauLess

[English](README.md) | **中文**

[![CI](https://github.com/Dying-Ember/BureauLess/actions/workflows/ci.yml/badge.svg)](https://github.com/Dying-Ember/BureauLess/actions/workflows/ci.yml)

BureauLess 是位于 coding Agent runtime 外部的本地优先控制与审计 harness。它用同一套
契约注册不同 Agent 和 Provider route，分派有边界的工作，并记录检查与比较运行结果所需
的证据。

它不是 Agent runtime、Provider gateway 或 credential broker。Codex CLI、Claude Code、
Gemini CLI、OpenCode 和 Pi 继续拥有自己的模型循环、工具、记忆、streaming 和 retry；
BureauLess 管理的是它们外面的边界。

## 为什么做 BureauLess

Agent workflow 的失败方式很像真实组织。有时，一个小 patch 被套上一整张组织架构图：
planner、reviewer、advisor 和 coordinator 都要重读同一份仓库，最后只有一个 worker
改一个文件。有时又反过来：一个过载的负责人同时指挥许多 worker，却没有 gate、可信
ledger，也说不清谁卡住了、谁完成了、哪个结果应该被相信。

BureauLess 用来选择“足够小、但足够安全”的协调结构。一个边界清楚的 worker 能完成，
就不要搭一家公司；工作真的分叉时，也只增加那些能够证明自己值得成本的 assignment、
gate、artifact check、预算和角色。

目标不只是控制一次运行。持久化的 assignment、routing decision、model choice、gate、
evidence 和 outcome 让运行可以 replay 和 backtest。长期应该由真实数据回答：哪些
workflow 形态值得、哪些 advisor 调用回本、哪些 gate 抓住风险，以及哪些 policy 应该
变得更简单。

真正有用的问题不是“能召唤多少个 Agent？”，而是“哪些 Agent 工作安全、有用、可审计，
并且值得花这些 token？”

## 边界

| BureauLess 负责 | Agent runtime 负责 |
| --- | --- |
| Agent 与 route 注册 | 模型与工具循环 |
| Dispatch admission 与隔离 workspace | 内部 planning 与 memory |
| 子进程级配置与 credential delivery | Provider streaming 与 retry |
| 原生证据保留与事实归一化 | 工具实现细节 |
| 独立验证、ledger、replay 与比较 | 自身的交互体验 |

规则很简单：Agent 可以干活，但不能自己写可信历史。

## 当前能力

### 跨 Agent 审计

- 用一个 registry 注册 Codex CLI、Claude Code、Gemini CLI、OpenCode 和 Pi。
- 显式拆分 Agent、Provider route、endpoint family、wire API、model、credential
  delivery 和 adapter capability。
- 通过一次性的子进程配置接入 route，不修改本地 Agent 配置文件。
- 在隔离 workspace 中执行，保留原生日志、workspace snapshot、diff、usage/cost
  provenance、tool event 和追加式 route observation。
- Harness 在 Agent 最终 workspace 的临时副本上运行独立验证。
- Benchmark identity v3 拆分 initial 与 realized context；paired-run comparison
  支持严格 fixed-context 和显式 adaptive-context 模式，同时列出 treatment diff
  与未控制混杂因素。
- 记录 Harness 所做 dispatch 的候选与拒绝理由，以及带 scope/blind spots 的
  workspace/process/network/credential/payment coverage；不会推断 Agent 内部决策。

当前兼容性的机器可读事实来源是：

```bash
uv run bureauless agent matrix --evidence
```

不要根据 Agent 名称、Provider 品牌或笼统的“OpenAI-compatible”标签推断支持情况；
准确的 route contract 才是权威定义。

### Workflow 控制平面

- YAML mission、workflow、ledger、assignment、result、review、routing、context、
  mutation、telemetry 和 dispatch contract。
- 确定性的 validation、gatekeeper、replay、retry control、workflow version 和
  authoritative result acceptance。
- 默认选择最小可行协调结构：先用一个 worker，只有证据证明开销值得时才增加 review
  或 DAG 结构。

### Workbench

- 浏览器和 Electron 共用一套 React UI。
- 支持 planning-DAG 编辑，以及 runtime artifact、replay、gate、mutation、telemetry
  和 dispatch 检查。
- Python/FastAPI 保持权威，前端不会重建 runtime policy。

## 设计哲学

1. **先从一个有边界的 worker 开始。** 只有 task dependency、风险或证据证明协调开销
   值得时，才增加 review、advisor 或 DAG。
2. **协调必须挣回自己的 token。** 每多一个 Agent 都要有预算理由，每个 advisor 更要
   有更强的理由；协调成本高过收益时，workflow 就应该变简单。
3. **证据先于共享事实。** Agent output 只是 proposal；verification、review 和
   acceptance 决定什么能进入 canonical ledger。
4. **原生证据不可替换。** Normalized fact 用来比较运行，但不能抹掉原生日志、workspace
   state 或 provenance。
5. **显式处理失败。** retry、升级模型、询问人类、拆分任务或停止；不要静默重复一次
   没有任何变化的尝试。
6. **控制与执行分离。** BureauLess 负责 admission、边界、证据和历史，Agent runtime
   保留模型与工具内部机制。
7. **从真实运行学习，而不是从 Demo 推断。** 追加式记录支持 replay/backtesting；
   fixture 或漂亮 dashboard 不是生产证据。

核心状态模型刻意保持精简：

| 概念 | 用途 |
| --- | --- |
| Mission 与 workflow | 目标、角色、依赖、emitted event 和 gate |
| Assignment | 一个有边界 worker 所需的最小 context 与 authority |
| Run record | 原生证据、workspace effect、metrics 和 result proposal |
| Review 与 gate | 下游继续前必须满足的显式 acceptance policy |
| Ledger | 用于确定性 replay 的追加式 accepted history |

## 快速开始

安装锁定的开发依赖：

```bash
uv sync --dev
npm install
```

### 不提供 credential，先检查 registry

```bash
uv run bureauless agent list
uv run bureauless agent matrix --evidence
uv run bureauless agent route claude-code --provider anthropic-compatible
```

### 不启动 Agent，先生成完整审计链

```bash
WORKSPACE=$(mktemp -d)

uv run bureauless audit init \
  --workspace "$WORKSPACE" \
  --task "创建 marker.txt 并添加一个确定性检查"

uv run bureauless audit run \
  --workspace "$WORKSPACE" \
  --agent codex-cli \
  --target-model gpt-5 \
  --target-provider openai \
  --session-id audit-dry-run \
  --dry-run
```

dry-run 不调用 Agent 或 Provider，但会生成与 live run 相同的 assignment → routing →
registration → dispatch → session → report → observation → archive 证据链。

### 运行真实 route

命令行只传环境变量名，不要传 key 值：

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

不同 Agent 和 wire API 的 base URL 规则不同。请使用
[canonical route 命令](docs/protocol/agent_provider_registry.md#10-canonical-commands)，
不要靠猜测改写这个例子。

### 检查与比较证据

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

Capability contribution artifact 只报告可测 delta，并明确声明
`causal_claim: not_established`。

## 证据纪律

- 原生输出始终是证据；normalized field 不会替代它。
- Tool event 证明 Agent 报告自己做了什么；workspace diff 证明最终文件状态。
- requested、CLI-reported、provider-reported 和 independently attested model identity
  保持分离。
- 缺失的 usage 或货币 cost 继续缺失；BureauLess 不做估算。
- latency 和 workspace delta 是 Harness fact；token、cost 和 tool timeline 比较保留
  各自的 provenance 与 eligibility。
- Registry 不写 secret，只记录环境变量名；独立验证使用清理后的环境。

完整定义见
[Agent/Provider registry contract](docs/protocol/agent_provider_registry.md)，最新实测见
[endpoint capability evidence](docs/audits/2026-07-15-agent-endpoint-capability-matrix.md)。

## Workbench

在两个终端分别启动 API 和浏览器 UI：

```bash
npm run api:dev
npm run web:dev
```

打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。如果 `8000` 端口被占用，API
launcher 会选择另一个本地端口，并写入 `.bureauless-api-url` 供 Web launcher 读取。

可选的本地入口：

```bash
npm run desktop:dev
npm run mutation-demo:prepare
npm run web:smoke
```

## 一次看懂架构

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

Canonical state 使用 YAML。Runtime 负责验证与状态转换，Workbench 负责展示，外部 Agent
不能直接更新 canonical state。

## 开发

运行当前维护的检查：

```bash
uv run python -m pytest -q
npm run web:build
npm run web:smoke
```

CI 在 Python 3.10 上运行 backend suite，并在 Node 24 上构建和 smoke-test Web 与
Electron。CI 不调用真实 Agent 或 Provider，也不需要 Provider secret。

源码按 runtime boundary 分工：

- `src/bureauless/agents/`：Agent registry、route evidence 和 doctor checks。
- `src/bureauless/protocol/`：YAML contract、validation 和 artifact intake。
- `src/bureauless/runtime/`：session、replay、gatekeeper、metrics 和 evidence。
- `src/bureauless/cli/`：operator 命令，包括 `agent` 和 `audit`。
- `src/bureauless/api/`：本地 Workbench API。
- `web/` 与 `electron/`：浏览器和桌面 shell。

## 文档

| 需要了解什么 | 从这里开始 |
| --- | --- |
| 文档权威层级与阅读顺序 | [`docs/README.md`](docs/README.md) |
| 稳定 Agent/Provider/evidence contract | [`docs/protocol/agent_provider_registry.md`](docs/protocol/agent_provider_registry.md) |
| 稳定 Harness protocol | [`docs/protocol/harness_protocol.md`](docs/protocol/harness_protocol.md) |
| 当前实现顺序 | [`docs/roadmap/development_roadmap.md`](docs/roadmap/development_roadmap.md) |
| 按日期记录的兼容性实测 | [`docs/audits/2026-07-15-agent-endpoint-capability-matrix.md`](docs/audits/2026-07-15-agent-endpoint-capability-matrix.md) |
| v0.4.0 Release notes | [`docs/releases/v0.4.0.md`](docs/releases/v0.4.0.md) |
| v0.3.0 Release notes | [`docs/releases/v0.3.0.md`](docs/releases/v0.3.0.md) |
| v0.2.0 发布 Demo | [`live-demos/2026-07-16-agent-audit-v0.2.0/README.md`](live-demos/2026-07-16-agent-audit-v0.2.0/README.md) |
| Control-runtime boundary decision | [`docs/rfcs/007-control-runtime-boundary.md`](docs/rfcs/007-control-runtime-boundary.md) |

## 许可证

BureauLess 使用 Apache License 2.0。见 [LICENSE](LICENSE)。
