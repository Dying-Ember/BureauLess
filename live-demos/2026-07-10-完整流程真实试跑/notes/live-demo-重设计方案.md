# live-demo 重设计方案

## 结论先行

本次需要重设计的不是 BureauLess 的核心理念，而是维护中的 `live-demo`
验证路径。

旧路径更擅长证明：

- 真实 worker 能否执行
- dispatch packet 能否落地
- result / review / outcome / ledger 能否闭环

旧路径不够严谨的地方在于：

- 它在代码里直接预构造了 routing decision。
- 它直接预设了 demo workflow。
- 它把很多控制平面动作变成了“demo helper 的默认行为”。

这样会削弱一个关键验证点：

**BureauLess 不只是约束 worker，也约束 orchestrator。**

## 重设计目标

新的 live-demo 应该优先验证：

1. orchestrator 的控制平面产物是否被 harness 约束。
2. worker 是否只在 assignment 边界内执行。
3. 新增 agent / role 的申请是否必须显式上报。
4. workflow mutation 是否只能以 proposal 进入系统。
5. canonical ledger 是否只接收经过 acceptance 的事实。
6. OpenAI-compatible telemetry 是否被稳定提取成可供历史统计和回测使用的运行证据。

换句话说：

新的 live-demo 不应再主要证明“worker 会不会干活”，而应证明：

**控制平面和执行平面是否同时被 BureauLess 管住。**

## 旧版 live-demo 的问题

以当前 `run_live_demo()` 为例，主要问题有三类。

### 1. 控制平面决策被 helper 预填

当前路径会在 demo helper 里直接生成：

- routing decision
- advisor gate decision
- assignment created event
- review decision

这会让人看到一条“能跑通的路径”，但看不清：

- 这些决策是如何被提出的
- 它们是否可以被替换、拒绝、校验
- orchestrator 是否真的也在 harness 规则之内

### 2. 验证重点偏执行平面

当前 live-demo 的主要成功标准更偏向：

- session 能跑
- 结果能打包
- ledger 能推进

而不是：

- control-plane artifact 是否规范
- orchestrator 是否越权
- 新 role / 新 agent 的请求是否被 gate

### 3. 演示路径替代了协议路径

当前 demo helper 实际上在替系统“把很多应该显式出现的决策产物先写好”。

这对快速验收有帮助，但会弱化 BureauLess 最重要的主张：

**不是谁写代码，而是谁被允许决定、谁被允许推进 canonical state。**

## 新版 live-demo 设计原则

### 原则 1：任务入口只给任务，不替 orchestrator 写答案

live-demo 的外部输入只提供：

- 任务目标
- 任务边界
- 验收条件
- 审计重点

不要在入口阶段默认替 orchestrator 预写：

- 选什么 workflow mode
- 要不要新增 role
- 要不要 mutation
- 怎么分配 node

这些都应变成显式产物。

### 原则 2：控制平面产物必须可见、可校验、可拒绝

至少要把以下产物显式化：

- routing decision
- workflow proposal
- assignment
- dispatch packet
- review decision
- mutation proposal
- mutation acceptance / rejection

这些都不应只存在于 helper 函数内部。

### 原则 3：worker 只验证执行，不替控制平面补洞

worker 的职责仍然是：

- 在 assignment 边界内完成工作
- 上报结果
- 在允许的情况下提出 mutation intent

worker 不应：

- 私自新增 agent
- 私自扩大 scope
- 私自修改 canonical workflow
- 私自推进 ledger 事实

### 原则 4：live-demo 要允许失败，而且失败本身是证据

如果某个任务因为：

- workflow 不足
- verification gate 不足
- 缺少 role
- 缺少控制平面入口

而无法自然完成，那么这不是 demo 失败，而是架构/产品边界的真实证据。

## 新版 live-demo 建议结构

建议把新版 live-demo 拆成四段。

### A. 任务发布阶段

由任务发布人提供：

- `task.md`
- mission 边界
- 风险与验收条件
- 审计标准

此阶段不写 routing answer。

### B. 控制平面阶段

要求系统显式生成并保存：

- `routing_decision.yaml`
- `workflow_proposal.yaml` 或现有 workflow 引用
- 必要的 assignment artifact

此阶段重点检查：

- 是否试图直接跳过 routing artifact
- 是否试图隐式扩编 agent
- 是否用默认 helper 行为替代显式决策

### C. 执行平面阶段

只有在控制平面产物被 harness 接受后，才允许：

- compile dispatch packet
- launch worker session
- package result
- apply review
- decide outcome
- update ledger

### D. 变更与审计阶段

如果系统认为 workflow 不足，必须通过：

- mutation proposal
- mutation intake
- mutation acceptance / rejection
- supersession / resumed assignment

来推进，而不是直接改 workflow。

## 对本次测试任务的重设计建议

仍然沿用当前任务主题，但换一种验证方式。

### 任务主题

将 `src/demo.py` 升级为最小 CLI，并要求提交前必须有独立 verification
证据。

### 不再预设的内容

以下内容不应提前写死：

- 一定是 `small_dag`
- 一定是 coder / reviewer / committer 三节点
- 一定不需要新 role
- 一定需要 mutation

### 需要观察的内容

1. 系统会不会先尝试 `single_agent` 或 `single_agent_with_review`
2. 系统什么时候认定“需要独立 verification”
3. 系统是否会申请新增 `verifier` role 或等价结构
4. 如果申请新增，是否通过显式 proposal / mutation 上报
5. harness 是否会阻止未批准的结构变更

## 最小落地改法

如果只做最小重构，不推翻现有实现，我建议：

1. 保留真实 worker session 路径。
2. 弱化 `run_live_demo()` 里的“一键全包”职责。
3. 把以下内容从 helper 内部拉成显式输入或中间产物：
   - routing decision
   - workflow proposal / workflow selection explanation
   - review decision
4. 让 live-demo 的主入口更像：
   - 准备任务输入
   - 生成或读取控制平面产物
   - 校验控制平面产物
   - 执行 worker
   - 接受或拒绝结果
   - 生成 run bundle

## 本次试跑的调整建议

本次不应再直接使用“旧的一键 live-demo 路径”作为主要证据。

更合理的顺序是：

1. 先把本次任务作为任务发布输入固定下来。
2. 再明确记录旧 live-demo 哪些地方替 orchestrator 预填了答案。
3. 把这些预填部分单独作为“当前实现限制”列出。
4. 在此基础上继续跑真实 worker / mutation / ledger 路径。
5. 最终区分两类结论：
   - BureauLess 协议与 harness 是否成立
   - 现有 live-demo 是否足够严谨

## 最终判断口径

如果后续试跑显示：

- worker 受控
- mutation 受控
- ledger 受控
- telemetry 提取受控且可追溯
- 但控制平面产物仍主要靠 helper 预填

那么最终结论不应写成“BureauLess 架构有问题”，而应写成：

**BureauLess 的控制平面约束设计成立，但维护中的 live-demo 仍然过度脚本化，尚不足以严格证明 orchestrator 也被同等强度地约束。**
