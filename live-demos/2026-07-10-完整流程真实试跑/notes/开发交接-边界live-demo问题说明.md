# 开发交接：边界 live-demo 问题说明

## 背景

这次 live-demo 的目标不是验证“旧 demo 能不能跑完”，而是验证：

- 外部任务约束能否真正进入 BureauLess 执行语义
- orchestrator / workflow / assignment 是否会被 harness 约束
- 当任务要求“独立最终验收验证”时，系统是否会自然触发：
  - 新 role / agent 申请
  - workflow proposal / mutation
  - 新 gate / 新事件

## 当前结论

当前问题不在单一 provider，而在维护中的 `run_live_demo()` 入口本身。

它仍然带有较强的 demo helper 预制语义，导致高压任务即使写清楚了，也可能被压扁成旧的：

- `coder / reviewer / committer`
- `old -> new`
- `patch_ready -> review_approved -> commit_created`

这会让 live-demo 更像“固定脚本验收”，而不是“任务发布人把真实约束交给 BureauLess 决策”。

## 两次关键试跑结论

### 1. Right Codes 边界脚本试跑

目录：

- `live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-10-rightcodes-boundary-script-official`

观察：

- 运行阶段再次出现 `RemoteDisconnected`
- 说明 `openai-compatible` 代理链路在这条 provider 上仍不稳定
- 因为没有稳定收口，这轮不能作为控制平面边界验证的主证据

### 2. JOJO 边界脚本试跑

目录：

- `live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-10-jojocode-boundary-script-official`

观察：

- implement 节点已经开始真正读取 `task-publisher/*.md`
- implement 结果不再只是 `old -> new`
- 已经实现并验证了：
  - `python src/demo.py -> new`
  - `python src/demo.py --check -> 自检通过`
  - `scripts/verify_demo.py` 作为独立验证入口
- 但推进到 review 前失败，报：
  - `ProtocolError: Node review is not runnable: Waiting for event patch_ready`

这说明：

- 任务语义已经部分进入执行面
- 但当前 live-demo 入口对“实现完成、独立最终验收待后续 assignment”这种任务还不兼容

## 建议开发方向

优先看这三个问题：

1. `run_live_demo()` 是否仍然预制了过强的 workflow / routing / artifact 语义，覆盖了任务发布输入。
2. implement result 中已经表达的“独立最终验收待单独 assignment”是否没有被正确映射到后续可运行状态。
3. `openai-compatible` 代理链路在 Right Codes 上为什么仍会出现 `RemoteDisconnected`。

## 本次交接建议先看的文件

### 任务发布输入

- [task.md](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/inputs/task.md)
- [orchestrator_request.md](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/inputs/orchestrator_request.md)
- [assignment_expectations.md](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/inputs/assignment_expectations.md)
- [workflow_proposal.md](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/inputs/workflow_proposal.md)

### 脚本入口

- [live-demo-boundary-run](/home/sean/vibe-coding/bureauless/scripts/live-demo-boundary-run)
- [live_demo_boundary_run.py](/home/sean/vibe-coding/bureauless/scripts/live_demo_boundary_run.py)

### JOJO 关键证据

- [implement_result.yaml](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-10-jojocode-boundary-script-official/generated/results/implement_result.yaml)
- [implement_session.yaml](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-10-jojocode-boundary-script-official/generated/sessions/implement_session.yaml)
- [README.md](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-10-jojocode-boundary-script-official/README.md)

### Right Codes 关键证据

- [rightcodes-试跑记录.md](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/notes/rightcodes-试跑记录.md)
- [publisher_audit.md](/home/sean/vibe-coding/bureauless/live-demos/2026-07-10-完整流程真实试跑/runs/2026-07-10-rightcodes-boundary-script-rerun/notes/publisher_audit.md)

## 预期交付

希望开发 agent 最终能回答：

1. 怎样让任务发布输入真正决定 live-demo 执行语义，而不是被 helper 默认值覆盖。
2. 怎样让“独立最终验收待后续 assignment”这种任务合法推进到 review / verification / commit。
3. Right Codes 的代理断链是 provider 差异，还是当前 proxy 实现仍有缺口。
