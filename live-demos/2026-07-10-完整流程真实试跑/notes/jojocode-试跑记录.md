# JOJO 试跑记录

## 当前结论

这份记录已经过一次纠偏。

最初在 `2026-07-10 16:29 +08:00` 左右，JOJO 这条链路表现为：

- `models` 可访问
- `responses` 最小推理一度返回 `502`
- 旧 demo 模板模型名又与当前暴露模型不一致

但随后按 JOJO **实际暴露的模型名** 重新测试后，情况变成了：

- `gpt-5.5` 和 `gpt-5.4-mini` 的 `responses` 探活成功
- `codex-cli` 直连 JOJO 成功
- BureauLess 的 `run_live_demo()` 也已通过 JOJO 完整跑完 `implement / review / commit`

所以现在更准确的结论是：

- JOJO 当前并不是“完全不可用”
- 旧结论里“JOJO 线路整体不通”已经过时
- 真正仍然存在的问题主要是：
  - demo 模板默认模型白名单过旧
  - BureauLess 的 `openai-compatible` telemetry proxy 对上游流式链路不够稳

## 关键证据

### 1. JOJO 暴露的模型名

`https://jojocode.com/v1/models` 当前可见：

- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.5`
- `gpt-5.6-luna`
- `gpt-5.6-sol`
- `gpt-5.6-terra`
- `codex-auto-review`

这说明本次重跑应使用显式模型名，而不是旧模板里的：

- `gpt-5`
- `gpt-5-mini`

### 2. 直接 `responses` 探活成功

最小请求：

```bash
curl https://jojocode.com/v1/responses \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <JOJO_KEY>' \
  -d '{"model":"gpt-5.5","input":"reply with exactly: pong"}'
```

以及：

```bash
curl https://jojocode.com/v1/responses \
  -H 'Content-Type: application/json' \
  -H 'Authorization: Bearer <JOJO_KEY>' \
  -d '{"model":"gpt-5.4-mini","input":"reply with exactly: pong"}'
```

观察：

- 两次都返回 `200 OK`
- 都产出了 `pong`
- 返回体中带 usage

所以“显式模型名下的 JOJO responses 完全不可用”这个判断不再成立。

### 3. `codex-cli` 直连成功

使用最笨的文档式配置：

- `CODEX_HOME/config.toml`
- `CODEX_HOME/auth.json`

让 `codex-cli` 指向：

- `base_url = "https://jojocode.com/v1"`
- `wire_api = "responses"`
- `model = "gpt-5.5"`

最小 `codex exec` 已成功返回 `pong`。

这说明：

- JOJO 不只是 curl 能打通
- `codex-cli` 这一层也能打通

### 4. BureauLess 真实 live-demo 已完整跑通

这次没有改仓库逻辑，只在运行时把 demo mission 的模型白名单临时改成：

- `gpt-5.5`
- `gpt-5.4-mini`

随后调用现成 `run_live_demo()`。

最终结果：

- `implement` completed
- `review` completed
- `commit` completed
- `failure: null`
- `terminal_complete: true`

也就是说 JOJO 这次已经跑完了维护中的完整三节点 demo。

本次运行 manifest：

- `notes/jojocode_live_demo.manifest.yaml`

## 产物结果

### Ledger 与流程事实

这次 JOJO run 已产生完整链条：

- `assignment_created`
- `result_submitted`
- `review_decision_recorded`
- `node_outcome_decided`

并且三个节点都进入 completed。

所以从流程角度看：

- harness 没有失守
- ledger / review / outcome 链条是完整的
- JOJO 这次已经足够支撑维护中的 live-demo 跑通

### 代码与验证

实现节点产物显示：

- `src/demo.py` 从 `old` 改为 `new`
- `python src/demo.py` 验证输出 `new`

review 节点与 commit 节点也都有各自的验证与结果记录。

## 仍然暴露的问题

### 1. demo 模板模型白名单过旧

当前维护中的 demo 模板默认仍然偏向：

- `gpt-5`
- `gpt-5-mini`

这会让真实 provider 明明可用，却先在本地 mission 约束上撞墙。

这个问题已经被这次运行证明：

- 只要切到 JOJO 实际暴露的模型名，主流程就能跑

### 2. BureauLess proxy 线程仍有异常

虽然这次主流程跑完了，但运行输出里仍然出现：

```text
http.client.RemoteDisconnected: Remote end closed connection without response
```

这说明：

- 代理线程层面仍然不够稳
- 只是这次异常没有阻止主流程最终完成

也就是说，问题还在，只是没有把这次 run 打死。

### 3. RM5 telemetry 仍未达到 provider_attributed

这次 metrics summary 里三个节点都是：

- `provider: openai-compatible`
- `usage_source: agent_reported`
- `cost_source: agent_not_supported`

而不是：

- `usage_source: provider_attributed`

这说明 JOJO 这次虽然跑通了，但 RM5 目标中的 provider-side usage capture 仍未真正闭环。

## 这次试跑能说明什么

现在可以明确回答：

- JOJO 按暴露模型名是可用的
- `codex-cli + JOJO + BureauLess` 主流程已实际跑通
- 旧的失败结论主要来自：
  - 早期上游不稳定
  - 旧模型名
  - demo 模板白名单不匹配
- 当前真正剩下的问题不是“JOJO 不行”，而是：
  - BureauLess 的 proxy / telemetry 设计还不够稳
  - provider-side usage capture 还没落到 RM5 想要的程度

## 建议

最短建议还是两条：

1. 把维护中的 demo mission 模型白名单更新到当前真实 provider 暴露的命名。
2. 修 `src/bureauless/runtime/sessions.py` 的 proxy：支持流式透传，并从 `responses` 的流式完成事件中提取 provider usage。
