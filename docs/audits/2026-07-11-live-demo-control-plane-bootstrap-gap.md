# Live-Demo 控制面 Bootstrap 缺口

- 状态：核心实现完成；JOJO provider 真实全链路验收已通过
- 日期：2026-07-11
- 范围：任务发布人驱动的真实 live-demo，不包含 fixture 或函数内预制 acceptance

## 结论

这不是 `scripts/live_demo_boundary_run.py` 的限制，而是当前运行时缺少
控制面 bootstrap。

发布方 wrapper 只应写入外部任务和 orchestrator 启动模型；它不能创建、接受
或改写任务 workflow。当前 `run_live_demo()` 只能从一个已接受 workflow 派发
worker，`compile_dispatch_packet()` 也正确拒绝 `status: proposed` 的 workflow。

因此，当前 boundary live-demo 只能真实证明“旧 helper workflow 不得执行”，
不能合法进入 implement、独立 verification、mutation、review 或 commit。

## 已验证事实

- JOJO + `gpt-5.5` 的真实 Codex 会话能够完成实现节点，并产生
  provider-attributed telemetry。
- 原旧 helper workflow 是 `proposed`；现在会在外部 runner 前以
  `workflow_not_accepted` 停止，不会消耗 worker provider 容量。
- mutation/retry demo 的 acceptance 由 Python 函数直接构造
  `actor: orchestrator` 事件，不能作为真实 orchestrator 决策证据。

相关证据：

- `src/bureauless/cli/main.py`: `run_live_demo()` 的 accepted-workflow 前置检查。
- `src/bureauless/protocol/dispatch.py`: dispatch packet 的 accepted-workflow 前置检查。
- `src/bureauless/application/mutation_retry_demo.py`: 函数内预制 mutation acceptance。
- `live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-11-jojocode-boundary-idle-renewal/notes/publisher_audit.md`。

## 开发目标

实现一个由 BureauLess runtime 触发的控制面 bootstrap，使下面的路径真实可跑：

```text
任务发布人输入
  -> orchestrator session（仅控制面）
  -> routing decision + workflow proposal + 派生 agent/model proposal
  -> harness 校验并持久化 draft
  -> orchestrator 或 human 明确接受
  -> accepted workflow
  -> runtime 依 replay/gatekeeper 派发实际 worker
  -> staged result / review / outcome acceptance / mutation / commit
```

最小要求：

- bootstrap session 不得执行业务代码、测试或 commit；它只产出控制面结构化产物。
- 初始 workflow proposal 必须有独立的 harness 校验与 acceptance 路径；不能通过
  把 YAML 的 `status` 直接改为 `accepted` 达成。
- 派生 worker/agent 的 role 与模型必须是 orchestrator 显式 proposal 的内容；
  发布方只提供 orchestrator 模型，harness 在 acceptance 前校验模型与 role。
- 未接受 proposal 不得创建 worker assignment、dispatch packet 或外部 session。
- 接受后的 workflow、acceptance 决定、模型/role 决定和 provenance 必须进入可 replay
  的 canonical 事实链。
- `run_live_demo()` 或后继真实入口必须消费该 accepted artifact，不得再构造旧
  `coder -> reviewer -> committer` helper workflow 或 routing decision。

## 验收试跑

实现后，使用现有中文边界任务和 JOJO provider 运行一次真实试跑。通过标准：

1. orchestrator 先输出可校验的 control-plane artifact，且未执行业务工作。
2. harness 拒绝缺 role、缺模型审批、非法 gate 或未接受的 proposal。
3. 接受后才出现实际 worker dispatch；派生模型来自 orchestrator artifact，而非
   发布方脚本。
4. 复杂任务实际产生独立 verification assignment；implementer 不能代替最终验收。
5. 若结构不足，mutation 仅作为 inert proposal 注册；接受后才改变 current workflow
   并按影响分析 supersede/retry。
6. review、outcome acceptance、ledger、turn report、native evidence、provider telemetry
   和 terminal commit 形成闭环。

不要用以下方式“补齐”该能力：fixture runner、函数内伪造 orchestrator acceptance、
发布方脚本预写 accepted workflow、或让 worker 直接修改 canonical workflow/ledger。

## 2026-07-11 真实 Bootstrap v3 拒绝

真实 JOJO `gpt-5.5` orchestrator 已完成一次无工具调用的 bootstrap session，
provider telemetry 正常；harness 在 worker 派发前拒绝了 proposal。首个错误为：

```text
Field 'node_id' must be a string
```

这不是 provider 或 timeout 问题。orchestrator 将 gate 写成了自创的
`type` / `requires_event` / `evidence_required` 形状，而现有 workflow gate 的
唯一合法形状是 `id`、`node_id`、`requires`。

该输出还有以下后续不兼容项；当前验证器在第一个错误停止，因此需要在下次真实
派发前一次修完，而不是逐项试错：

- workflow 与 routing 的 `mission_id` 写成了 bootstrap assignment ID，而不是
  mission 的 `demo`。
- routing `decision_type` 写成 `initial_routing`，但协议要求 `routing_decision`；
  `rejected_modes` 也不是协议要求的对象列表。
- worker binding 使用 `coder-01`、`verifier-01`、`committer-01`，但本次 runtime
  只声明/支持 `codex-cli` adapter。
- worker model 写成未获本次 provider/mission 批准的 `gpt-4.1-mini`；当前
  bootstrap 验证只检查“非 placeholder”，尚未真正验证 concrete model 是否在
  已接受 provider/model policy 内。
- workflow 用了 `implementation_ready`、`verification_ready`、`commit_ready`，
  但独立验证约束实现是以 emit 名称包含 `verification` 和实现节点 emit
  `patch_ready` 识别的；当前 prompt 没有给出能同时满足这些规则的完整例子。

### 开发修复要求

- 将 bootstrap contract 改为严格、可复制的完整 YAML 示例，示例中的 mission ID
  使用 runtime 注入值，gate、routing 和 binding 全部采用实际 loader 形状。
- 在 model/agent proposal 验证中，校验每个 binding 的 agent adapter 已支持，且
  model 被 mission/provider 的已接受 policy 明确允许；不能只拒绝 placeholder。
- 汇总 proposal 的所有 schema/semantic 错误后再拒绝，至少让 orchestrator 的
  单次反馈能看见 gate、mission、routing、agent、model 五类问题。
- bootstrap 失败结果保留为 worker 零派发；不要为了提高通过率放宽 harness。

v3 证据：
`live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-11-jojocode-control-plane-bootstrap-v3/generated/sessions/control_plane_bootstrap_session.yaml`。

## 2026-07-11 实现记录

- `initial_control_plane_proposed` 与 `initial_control_plane_accepted` 已成为
  canonical ledger events；accepted workflow artifact 只在 acceptance 后由 harness
  materialize。
- boundary live-demo 会启动只读 orchestrator bootstrap session，并要求真实结果按
  顺序给出 workflow、routing decision、worker bindings proposal 与 explicit
  acceptance intent；任一 native tool call 会拒绝该 bootstrap。
- worker role/model bindings 从 accepted control-plane artifact 投影到 dispatch；发布方
  不再预填派生模型。
- bootstrap 拒绝会正常生成 manifest、session、packet、assignment、context capsule 与
  turn report，且 worker 零派发；发布方审计会将其标为
  `control_plane_bootstrap_rejected`，不再误报为旧 helper 或 telemetry 回归。
- focused fixture-backed regression 已覆盖 proposal/acceptance、未接受 workflow 零派发、
  派生模型 binding 与 malformed control-plane output 的审计收口。真实 JOJO 闭环仍需按
  上列验收试跑执行。

### 真实试跑记录

- `2026-07-11-jojocode-control-plane-bootstrap-v3`：真实 `gpt-5.5` orchestrator
  会话完成（83.3 秒、provider-attributed telemetry、零 tool call），但返回了非协议的
  gate 字段，harness 以 `Field 'node_id' must be a string` 拒绝 bootstrap，worker 零派发。
  这验证了控制面拒绝可审计收口；不是 provider 或 worker runtime 失败。
- `2026-07-11-jojocode-control-plane-bootstrap-v4/v5`：bootstrap 已通过，真实
  implement 也完成并带有 provider telemetry。v4/v5 随后暴露的是 progress
  acceptance：implement 的 self-check 状态尚未被当作“等待独立 verifier”的可接受进度。
  runtime 已补齐该状态，且 publisher audit 现在只有 terminal workflow 才会报告 passed。
- v6 进一步确认 `mission.models` 只属于 orchestrator 启动模型；worker model approval
  已改由 provider capability policy 提供，避免把 `gpt-5.5` 错当成 worker 唯一白名单。
- `2026-07-11-jojocode-control-plane-bootstrap-v6`：真实 orchestrator 输出了符合
  任务边界的四节点 DAG（implement、review、独立 verify、commit），无工具调用；
  harness 在 worker 零派发时聚合拒绝两项错误：未加引号的 YAML
  `advisor_gate_decision.policy_version: 0.1` 被解析为数值，以及 worker model
  `gpt-5` 不在当前 approved policy。前者是 contract 输出格式问题；后者暴露出
  model-policy 分层问题，见下节。

### v6 后续修复要求

- 控制面 contract 必须明确所有 version 值是字符串，或改用不会将 `0.1` 隐式转换为
  数值的结构化输出编码；不能依靠模型“记得加引号”。
- 不要把 `mission.models` 当成派生 worker 的允许模型集合。发布方按约定只写入
  orchestrator 启动模型，因此该集合只能约束 orchestrator，不能反向预选 worker。
- harness 对 worker binding 应校验 provider 暴露/可用的具体模型及 mission 的预算、
  风险或 allow/deny policy；通过后把该审批作为 accepted control-plane artifact 的
  事实写入 ledger。若当前没有 provider model catalog 或明确 policy，则应拒绝为
  `worker_model_approval_unavailable`，而不是暗中将 worker 限制为 orchestrator 模型。

## 2026-07-11 真实 Bootstrap v7：Implement Progress 收口

v7 已通过真实 bootstrap：orchestrator 无工具调用，harness 接受四节点 workflow，
并把 `gpt-5.5` 的 worker bindings 写入 accepted control-plane artifact。真实
implement worker 也完成了最小 CLI、`--check`、验证入口和 README，并留下
provider-attributed telemetry。

`implementation_smoke_passed_independent_verification_not_claimed` 现已被定义为
progress marker：仅当 accepted workflow 有独立 verifier 节点时，harness 才接受其
`patch_ready`，并继续要求 verifier 产生最终 verification 事实。

后续节点没有派发，原因不是任务未实现：implement 上报的 verification status 是
`implementation_smoke_passed_independent_verification_not_claimed`。它准确表达了
“本地 smoke check 已通过，但没有冒充独立最终验收”，但 live-demo progress
acceptance 只识别 `implemented_self_check_passed`、`local_checks_passed` 或显式
`final_independent_verification: pending_separate_assignment`，因此 outcome 拒绝，
`patch_ready` 未成为 effective event，replay 将 review、verify、commit 全部阻塞。

开发修复要求：

- 在 worker result contract 中规定一个唯一的结构化 progress marker，例如
  `final_independent_verification: pending_separate_assignment`，并将其写入 dispatch
  prompt 的完成输出要求；不要依赖自由文本 status 的同义词。
- acceptance 应只依赖该 marker（或一个固定枚举），并在 marker 与 workflow 的独立
  verifier 节点同时存在时接受 implement 的 `patch_ready` 为 progress，而不是最终验收。
- 为真实样式的 implement result 增加回归：accepted `patch_ready` 后，replay 同时
  让 review 与 verify ready，commit 仍必须等待二者的 accepted 事实。

发布方 wrapper 的源码字面量误报已修正为实际执行 `python -B src/demo.py` 与
`python -B src/demo.py --check`；v7 重算后唯一业务 finding 为 `workflow_incomplete`。
证据：
`live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-11-jojocode-control-plane-bootstrap-v7/`。

## 2026-07-11 真实 Bootstrap v9：Progress Marker 字面量不一致

v9 的 provider 和 implement 都正常：`gpt-5.5` worker 完成 CLI、`--check`、独立
验证入口和 README，并上报了结构化 verification：

```yaml
status: implementation_smoke_passed
final_independent_verification: pending_verifier_assignment
```

但 acceptance 只接受 marker 的精确字面量
`pending_separate_assignment`。同时，implement assignment 与 dispatch packet 没有
包含任何 required marker 值，因此 agent 无法从协议输入得知唯一合法值。结果是
outcome 以 `acceptance-v1` 拒绝，`patch_ready` 不生效，review、verify、commit 全部
保持 blocked。

开发修复要求：

- 将 marker 枚举定义为共享常量，并由 result parser、assignment prompt、dispatch
  packet 和 acceptance policy 同时消费；不要在不同层手写相似字符串。
- 在有独立 verifier 节点的 implement assignment 中，明确要求
  `final_independent_verification: pending_separate_assignment`；缺失或其他值必须
  在结果 intake 时以可读协议错误拒绝。
- 增加真实 result-shape 回归，证明该 marker 使 implement `patch_ready` 被接受，
  且仅放行 review/verify，不放行 commit。

证据：
`live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-11-jojocode-control-plane-bootstrap-v9/generated/results/implement_result.yaml`。

## 2026-07-11 真实 Bootstrap v10/v11：可修正 Proposal 的 Replan 缺口

- v10：control-plane session 在没有任何 agent 事件或 provider usage 的情况下
  `idle_timeout`。发布方审计已修正为 `inconclusive / provider_runtime_timeout`，
  不再误报 control-plane rejection。
- v11：provider 恢复，orchestrator 完成且产出四节点 `small_dag` workflow，但 routing
  decision 的 `selected_mode` 选择了 `single_agent`。harness 正确拒绝两者不一致，且
  worker 零派发。

v11 不是业务判断错误：orchestrator 同时清楚说明独立 verification 需要多节点，
却受到系统提示词“默认 single_agent”的影响而在 routing 字段写出矛盾值。当前 bootstrap
对这种可修正的 schema/semantic rejection 只有终止，没有同一 logical session 的 bounded
replan/repair 回路，迫使发布方靠新的外部 run 重试。

开发修复要求：

- bootstrap proposal 发生可修正 protocol rejection 时，向同一 orchestrator 提供
  structured validation errors 和上一次 proposal，允许一次受限 replan；不可执行工具，
  不得创建 worker assignment。
- replan 输出仍须重新经过 harness 完整校验；第二次失败才形成 terminal
  `control_plane_bootstrap_rejected`。
- 在 bootstrap prompt 中将“默认 single_agent”限定为不违反已声明独立 verification/
  terminal commit 要求的场景，并要求 `routing.selected_mode == workflow.mode`。

该要求已实现：bootstrap 在同一 logical run 中最多尝试一次受限 replan，失败时仍为
worker 零派发；`test_run_live_demo_replans_rejected_bootstrap_once_then_runs_semantic_dag`
覆盖首次拒绝、第二次接受和后续 DAG 派发。v12 的首次接受并完整提交则提供真实 provider
闭环证据。

v11 证据：
`live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-11-jojocode-control-plane-bootstrap-v11/notes/publisher_audit.md`。

## 2026-07-11 真实 Bootstrap v12：控制面到 Commit 全链路通过

v12 使用同一中文边界任务与 JOJO `gpt-5.5` provider，已真实跑通：

- bootstrap 首次 proposal 即被 harness 接受，accepted control-plane artifact
  产出四节点 `small_dag` workflow 与 `codex-cli / gpt-5.5` worker bindings。
- implement 完成最小 CLI、`--check`、独立验证入口与 README，并以共享 marker
  `final_independent_verification: pending_separate_assignment` 被 acceptance
  识别为合法 progress，`patch_ready` 进入 effective replay。
- review 与独立 verify 都被派发并各自留下 accepted result、review/outcome 事实和
  provider-attributed telemetry；verify 的结构化 evidence 明确记录了
  `python src/demo.py`、`python src/demo.py --check` 与
  `python scripts/verify_demo.py` 的独立执行结果。
- commit 仅在 `patch_ready`、`review_approved`、`verification_passed` 三者都进入
  canonical ledger 后才派发，并最终产出 `commit_complete`。
- 发布方审计结果为 `passed`，manifest 标记 `terminal_complete: true`，节点状态为
  `implement/review/verify/commit = completed`。

这说明本次缺口已经从“控制面无法合法引导真实 worker”收敛到“JOJO provider 实际可在
现有 harness 下完成 bootstrap -> implement -> review -> verify -> commit 闭环”。

v12 证据：

- [publisher_audit.md](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-11-jojocode-control-plane-bootstrap-v12/notes/publisher_audit.md)
- [m3_integrated_demo_manifest.yaml](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-11-jojocode-control-plane-bootstrap-v12/generated/telemetry/m3_integrated_demo_manifest.yaml)
- [ledger.yaml](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-11-jojocode-control-plane-bootstrap-v12/ledger.yaml)

剩余注意项：

- v12 是真实通过，不再属于 bootstrap gap；后续若继续扩展，应转入新的增量任务，
  例如多适配器 control-plane 验证、mutation/replan 的真实 provider 路径，或更细的
  telemetry/workbench 对齐，而不是继续把它记成“未跑通”。
