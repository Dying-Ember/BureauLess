# BureauLess v0.2.0 Agent Audit 发布 Demo

这个 Demo 展示 BureauLess 如何站在 coding Agent runtime 外部，用同一套契约完成
Agent route 注册、隔离 dispatch、原生证据保留、独立验证和可比较 observation。

Demo 不依赖本地 Agent 配置文件，不保存 API Key，也不把可变 workspace 或 native log
提交到 git。

## 测试任务

目标 workspace 中的 Agent 任务是：

> 创建 `release_marker.txt`，内容必须严格等于
> `bureauless-agent-audit-v0.2.0`，并以一个换行符结尾。

这是一个刻意缩小的 mutation task。业务复杂度不重要；重要的是最终文件状态、原生事件、
usage/cost provenance、独立 acceptance 和 archive 是否形成完整证据链。

## 审计标准

- Agent、Provider route、endpoint family 和 wire API 必须分别记录。
- Route 与 credential 只能通过本次子进程注入，不能修改本地 Agent 配置。
- Tool event 只能证明 Agent 报告的行为；最终文件事实以 workspace snapshot/diff 为准。
- 独立验证必须由 Harness 在 Agent 最终 workspace 的临时副本上执行。
- native output 必须保留，normalized fact 必须声明 provenance。
- credential 值不能进入 registry、session、report、notes 或 git。
- endpoint 不可用不得被改写成 Agent 产品不兼容。

## A. 无密钥 60 秒 Demo

在 BureauLess 仓库根目录运行：

```bash
DEMO_ROOT=live-demos/2026-07-16-agent-audit-v0.2.0
DEMO_WORKSPACE="$DEMO_ROOT/workspace"

uv run bureauless agent matrix --evidence

uv run bureauless audit init \
  --workspace "$DEMO_WORKSPACE" \
  --task "创建 release_marker.txt，内容严格等于 bureauless-agent-audit-v0.2.0 并以一个换行符结尾"

uv run bureauless audit run \
  --workspace "$DEMO_WORKSPACE" \
  --agent codex-cli \
  --target-model gpt-5 \
  --target-provider openai \
  --route-instance-id release-dry-run \
  --cohort-id release-demo-v0.2.0 \
  --session-id release-dry-run \
  --dry-run

uv run bureauless audit observations --workspace "$DEMO_WORKSPACE"
```

这条路径不调用 Agent 或 Provider，但会生成与 live run 相同的控制与证据结构。预期看到：

```text
assignment.yaml
routing.yaml
registration.yaml
dispatch.yaml
session.yaml
report.md
route-observation.yaml
archive/.../manifest.yaml
```

`route-observation.yaml` 必须能够从 session/report 重新构建；修改 observation 后，
`audit observations` 应拒绝该记录。

## B. 可选真实 Responses Route

准备一个明确支持 OpenAI Responses wire API 的 endpoint。环境变量值不会写入命令参数：

```bash
export BUREAULESS_DEMO_BASE_URL=https://endpoint.example/v1
export BUREAULESS_DEMO_API_KEY=...
export BUREAULESS_DEMO_MODEL=your-model
```

复用上面的 control plane，运行一个新的 session：

```bash
uv run bureauless audit run \
  --workspace "$DEMO_WORKSPACE" \
  --agent codex-cli \
  --target-model "$BUREAULESS_DEMO_MODEL" \
  --target-provider openai-compatible \
  --provider-wire-api responses \
  --provider-base-url "$BUREAULESS_DEMO_BASE_URL" \
  --provider-api-key-env BUREAULESS_DEMO_API_KEY \
  --route-instance-id release-responses-route \
  --cohort-id release-demo-v0.2.0 \
  --session-id release-live-responses \
  --verify-command "python -c 'from pathlib import Path; assert Path(\"release_marker.txt\").read_text() == \"bureauless-agent-audit-v0.2.0\\n\"'"
```

成功标准：

- session 状态为 `completed`；
- `changed_files_count` 为 `1`；
- `verification.yaml` 状态为 `passed`；
- workspace pre/post state 不同；
- native logs、diff、usage/cost provenance 和 route observation 都已落盘；
- archive manifest 通过 `bureauless audit verify`。

## 检查结果

```bash
RUN_ROOT="$DEMO_WORKSPACE/.bureauless/runs/release-live-responses"

uv run bureauless audit report "$RUN_ROOT/session.yaml"
uv run bureauless audit observations --workspace "$DEMO_WORKSPACE"
uv run bureauless metrics summarize "$DEMO_WORKSPACE/.bureauless/runs"
uv run bureauless agent matrix \
  --evidence \
  --observations "$DEMO_WORKSPACE/.bureauless/runs"
```

`audit run` 会打印本次 archive manifest 的准确路径；使用该路径验证：

```bash
uv run bureauless audit verify path/to/manifest.yaml
```

## 证据入口

- Stable contract：[`../../docs/protocol/agent_provider_registry.md`](../../docs/protocol/agent_provider_registry.md)
- Dated capability matrix：[`../../docs/audits/2026-07-15-agent-endpoint-capability-matrix.md`](../../docs/audits/2026-07-15-agent-endpoint-capability-matrix.md)
- Release notes：[`../../docs/releases/v0.2.0.md`](../../docs/releases/v0.2.0.md)

## 已知边界

- 这个发布 Demo 只要求一条真实 Responses route，不假装一次运行验证所有 Agent。
- Dry-run 的 review 状态是 `not_run`，cost provenance 是 `unavailable`；它不构成
  Agent、endpoint、model、mutation 或 telemetry 的运行证据。
- OpenCode Anthropic adapter 仍未实现。
- OpenCode/Pi Responses route 的 runtime shape 已观察，但 tested endpoint 不可用，
  因此 adapter 仍未实现。
- 不同 provenance 的 token/cost 不应被画成统一价格排名。
- Provider 或 Agent 报告的 cost 不是已验证的 payment/charge side effect。
- `workspace/`、`.bureauless/` 和 native logs 由 `.gitignore` 排除；公开提交只保留这份
  脱敏说明和稳定输入。

## 重新运行

`audit init` 会拒绝覆盖已有 control plane。需要重新运行时，先人工归档或删除这个 Demo
的 ignored `workspace/`，再从 A 开始。不要覆盖仍需审查的原生证据。
