# workflow proposal 观察点

这不是最终 workflow 答案，而是本次试跑希望检查的控制平面问题清单。

## 最小要求

如果系统提交 workflow proposal，应至少能回答：

- 为什么 `single_agent` 不足
- 为什么 `single_agent_with_review` 不足
- 为什么现有结构能或不能表达“实现者不得执行最终验收验证”
- 为什么需要新增 role，而不是只调整 gate 或 verification 方式
- 新 role 是否真的降低风险，而不是只增加组织结构

## 需要重点看

### 1. 不允许默认沿用旧 demo 形状

如果系统最后仍选择：

- `coder`
- `reviewer`
- `committer`

三段式结构，也必须显式说明：

- 为什么这是此任务所需，而不是因为现有 demo helper 正好这么写

### 2. verifier 角色不是默认成立

如果系统提出：

- `verifier`
- `verification_reviewer`
- 其他等价新 role

则必须说明：

- 为什么独立 verification 不能由现有 worker + review 机制满足
- 为什么“reviewer 复查实现者自跑结果”仍然不算本任务要求的最终验收分离
- 为什么新增 role 不构成无证据扩编

### 3. mutation 与 workflow proposal 的边界

如果系统认为现有 accepted workflow 不足：

- 应优先以显式 workflow proposal 或 mutation proposal 的方式上报
- 不应通过临时 assignment 或直接改 workflow 文件绕过

## 本次我们接受的结果

本次试跑接受三种结果中的任意一种，只要证据链完整：

1. 维持简单模式，并证明无需新增 role 也能让“最终验收验证”脱离实现者 assignment
2. 升级到带 review 的简单模式，并证明 reviewer 不只是口头复核，而是真正承担独立验收
3. 显式提出新增 role / mutation，并通过正常 acceptance 链推进

不接受：

- 没有显式控制平面说明却直接进入旧 demo DAG
- 没有 proposal / mutation 却凭 assignment 偷渡新 role
- 让实现者自己执行最终验收，却把结果包装成“独立 verification”
