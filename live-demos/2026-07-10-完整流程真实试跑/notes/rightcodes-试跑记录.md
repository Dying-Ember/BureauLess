# Right Codes 试跑记录

## 2026-07-10 SSE 修复后复跑

在 `2026-07-10 21:35 +08:00` 之后，基于当前仓库中已修复的 SSE / provider usage capture 路径，重新对 Right Codes 做了一次完整真实试跑。

这次最新结果是：

- `implement / review / commit` 三个节点全部 completed
- `terminal_complete: true`
- `failure: null`
- 三个节点都产出了 `provider_usage_capture` artifact
- `metrics_summary.yaml` 中三节点全部是 `usage_source: provider_attributed`

也就是说，前面那版“Right Codes 在 review 阶段卡在 proxy / SSE”已经不是当前代码状态下的最新结论。

本次复跑目录：

- `live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-10-rightcodes-sse-rerun`

关键产物：

- `generated/telemetry/m3_integrated_demo_manifest.yaml`
- `generated/telemetry/metrics_summary.yaml`
- `artifacts/provider-usage/result-session-implement-live.provider-usage.yaml`
- `artifacts/provider-usage/result-session-review-live.provider-usage.yaml`
- `artifacts/provider-usage/result-session-commit-live.provider-usage.yaml`

这次复跑还说明两点：

1. `openai-compatible` 路径现在已经能从 Right Codes 的 `responses` SSE 流里提取 usage，并写回 provider-side usage artifact。
2. 维护中的 live-demo 仍然需要临时把 demo mission 模型名单切到真实暴露模型名，例如 `gpt-5.5` / `gpt-5.4-mini`，否则会先撞上旧白名单，而不是 SSE 问题。

仍然保留的剩余问题：

- `turn_report` 还是在进程结束后聚合写入，`policy_compliance.status` 仍为 `violated`
- `cost_source` 仍然是 `agent_not_supported`，还没有 provider cost 归因

## 2026-07-10 高压任务边界复跑

在上一轮 SSE 修复确认后，又把 live-demo 输入任务升级成更强约束版本，再次用 Right Codes 复跑，目标是尽量逼出：

- 独立 verification assignment
- verifier 或等价新 role
- workflow mutation / proposal
- commit gate 对 verification 事实的显式依赖

这次运行目录：

- `live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-10-rightcodes-boundary-task-rerun`

### 结果

这轮 run 仍然完整跑完了：

- `implement` completed
- `review` completed
- `commit` completed
- `terminal_complete: true`
- `failure: null`

provider usage capture 也仍然正常：

- 三节点继续是 `usage_source: provider_attributed`

### 但这次更重要的结论不是“跑通”，而是“没撞到新边界”

原因很直接：

1. 最终代码结果仍然只是 `print('new')`，没有实现高压任务里要求的 CLI / `--check` / 独立验证入口。
2. 实现节点读取到的仍然是 demo helper 预置的旧材料：
   - `README.md` 仍写着 “Implement updates src/demo.py from old to new.”
   - `artifacts/implement_patch.diff` 仍然只是一行 `old -> new`
3. review 节点仍然只是 reviewer 自己运行 `python3 src/demo.py`，并没有出现：
   - 独立 verification assignment
   - verifier role
   - mutation proposal
   - 新 gate 事件

也就是说，这轮高压任务已经足够强，但执行入口仍然把它压扁成了“旧 demo patch”。

### 当前更准确的架构判断

现在 Right Codes 线路已经足以说明两件事：

1. `openai-compatible` 的 SSE / usage capture 路径当前是通的。
2. 维护中的 `run_live_demo()` 仍然不适合作为“控制平面边界验证”的主证据。

因为它会继续预置：

- 旧 README
- 旧 patch artifact
- 旧 `coder / reviewer / committer` workflow
- 旧 routing reasoning

所以它更像“维护中的固定 demo 流水线”，而不是“把外部任务原样交给 BureauLess 决策”的入口。

### 这轮复跑真正暴露的问题

问题不再是 provider，也不再是 SSE，而是：

- 现有 live-demo 入口没有把高压任务输入真正注入到执行语义
- helper 预制 workflow 与 patch 仍然覆盖了任务发布人的外部约束
- 因此 verifier / mutation / role 扩编边界根本没有获得真实触发机会

## 结论

这次改用用户新提供的 `Right Code` 渠道后，结论和前面的 JOJO 完全不同：

- `Right Code` 的 Codex `Responses API` 是通的
- `codex-cli` 按官方文档配置后是通的
- BureauLess 也已经成功跑完 `implement` 节点，并正常入 ledger、review decision、node outcome
- 真正暴露出的架构问题在 BureauLess 自己的 `openai-compatible` telemetry proxy，而不是 provider 或模型名

## 关键证据

### 1. 正确 Base URL

Right Code 文档给出的 Codex 配置是：

- `base_url = "https://right.codes/codex/v1"`
- `wire_api = "responses"`

文档里的 curl 示例也使用：

- `https://www.right.codes/codex/v1/responses`

所以根域名 `/v1` 不是正确入口。

### 2. 模型列表可用

已确认以下 Codex 模型可用：

- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.5`
- `gpt-5.6-luna`
- `gpt-5.6-sol`
- `gpt-5.6-terra`
- `codex-auto-review`

同时文档历史示例里还出现了：

- `gpt-5.2`
- `gpt-5.3-codex`

### 3. 直接请求 `responses` 成功

最小探活：

```bash
curl https://right.codes/codex/v1/responses \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <API_KEY>' \
  -d '{"model":"gpt-5.5","input":"reply with exactly: pong"}'
```

结果：

- 返回 `200 OK`
- SSE 中实际产出 `pong`
- `response.completed` 中带有 `usage`

这说明 provider 本身可用。

### 4. `codex-cli` 直连成功

使用 Right Code 文档同款方式：

- `config.toml`
- `auth.json`

最小 `codex exec` 测试成功返回 `pong`。

这里也暴露一个小兼容点：

- 对这家渠道，`codex-cli` 不能只依赖外部环境变量注入 key
- 按文档写入 `CODEX_HOME/auth.json` 更稳

## BureauLess 实跑结果

### 成功部分

本次对 `run_live_demo()` 做了最小局部补丁：

- 不改仓库逻辑
- 只在这次运行中把 demo mission 的模型白名单改成：
  - `gpt-5.5`
  - `gpt-5.4-mini`

然后用现成 `run_live_demo()` 跑 Right Code。

`implement` 节点成功完成，关键事实：

- `src/demo.py` 已从 `old` 改成 `new`
- 执行了 `python src/demo.py`
- verification 输出 `new`
- ledger 中已记录：
  - `result_submitted`
  - `review_decision_recorded`
  - `node_outcome_decided`
  - `assignment_created` for `review`

也就是说：

- BureauLess 真实 dispatch 成功
- codex-cli worker 成功工作
- harness 的 ledger / review / outcome 链条是通的

### 暴露的问题

进入 `review` 节点后，运行卡住，代理层出现：

```text
http.client.RemoteDisconnected: Remote end closed connection without response
```

这说明问题不在“模型名不对”或“provider 不通”，而在 BureauLess 的 `openai-compatible` 代理包装层。

## 架构问题判断

### 问题点 1：provider usage capture 假设了“整块 JSON”

当前 proxy 在 `src/bureauless/runtime/sessions.py` 中：

- 用 `urllib.request.urlopen()` 把上游整个响应读完
- 再把整个 `response_body` 交给 `_maybe_capture_response()`
- `_maybe_capture_response()` 直接 `json.loads(response_body)`

这对普通 JSON 响应可行，但对 Right Code 的 `/responses` 不成立，因为它返回的是：

- `Content-Type: text/event-stream`
- SSE 分帧事件流

后果：

- provider-side usage 无法被当场解析成 `provider_usage_capture`
- 最终 implement 节点只留下 `agent_reported` usage，而不是 RM5 目标里的 `provider_attributed`

这就是为什么：

- provider 明明返回了 usage
- 但 BureauLess 的 session 里仍然是 `usage_source: agent_reported`

### 问题点 2：proxy 对流式通道不够稳

当前 proxy 不是边读边转发，而是：

1. 先从上游读完整个 body
2. 再统一回写给客户端

这对短响应可能勉强工作，但对真实长流式对话很脆弱。

Right Code 这次表现出来的症状就是：

- implement 节点侥幸成功
- review 节点在更长、更复杂的流里卡住并断链

所以这不是 provider 的单次波动，更像是代理设计与 SSE 的边界不匹配。

## 这次测试能回答什么

可以明确回答：

- 不是 Right Code provider 本身有问题
- 不是暴露模型名不可用
- 不是 Codex CLI 不能接 Right Code
- BureauLess 的 workflow / ledger / review / outcome 基本链路能跑
- BureauLess 当前 RM5 的 `openai-compatible` telemetry proxy 对 SSE `responses` 流有架构缺口

## 建议

最短建议只有两条：

1. `openai-compatible` provider usage capture 不要再假设上游一定返回单个 JSON 文档，至少要支持 SSE 的 `response.completed` 事件提取。
2. 代理层不要再“读完整个上游 body 再回写”，应改成真正的流式透传，否则后面会继续遇到断链和 telemetry 丢失。
