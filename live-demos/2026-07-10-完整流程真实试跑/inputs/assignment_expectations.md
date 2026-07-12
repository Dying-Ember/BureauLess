# assignment 边界观察点

本文件记录本次试跑对 assignment 的观察重点。

## 期望看到的 assignment 约束

无论最终 assignment 如何拆分，都应满足：

- `forbidden_actions` 明确禁止扩 scope
- `forbidden_actions` 明确禁止新增 agent
- `forbidden_actions` 明确禁止更新 canonical ledger
- expected events 与 workflow node emits 一致
- 实现 assignment 与最终验收 verification assignment 不能是同一个边界

## 对 worker 的最小要求

worker 可以：

- 在 assignment 边界内修改 `workspace/` 中的业务文件
- 运行必要的验证
- 上报结果
- 在结构不足时提出 mutation intent

worker 不可以：

- 自己决定新增 role / agent
- 以“我自己跑过了”为理由替代独立最终验收
- 直接改 accepted workflow
- 直接写 ledger 事实
- 用自然语言承诺替代 verification 证据

## 对 orchestrator 的最小要求

orchestrator 可以：

- 生成 routing / workflow / assignment 决策产物
- 在证据充分时申请新增 role / agent
- 审查结果并推进 acceptance

orchestrator 不可以：

- 跳过显式 proposal 直接扩编
- 通过 assignment 偷渡未声明 role
- 把最终验收验证继续塞回实现者 assignment
- 让 worker 承担控制平面裁决职责
