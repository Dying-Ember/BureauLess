# Live Demos

这个目录是仓库内所有维护中 `live-demo` 输入、输出和审计记录的统一落点。

只要某次 demo 需要在会话结束后继续留档、复查或复跑，就不要放到 `/tmp`，而是放到这里。

## 语言要求

- 从现在开始，所有 `live-demo` 文档都使用中文。
- 包括但不限于：
  - 顶层说明
  - 每次 run 的 `README.md`
  - `notes/` 下的记录
  - 测试任务说明
  - 审计标准
  - 结论摘要

命令、路径、环境变量、模型名和协议名保持原文即可。

## 目标

- 让每次 live-demo 都能靠仓库内输入和本地产物复查。
- 把生成证据集中存放，便于审计。
- 默认不把敏感信息写进版本库。
- 默认不把嘈杂运行产物纳入 git。

## 目录结构

每次 run 建一个独立子目录：

```text
live-demos/
  README.md
  .gitignore
  2026-07-10-jojocode-live-demo/
    README.md
    inputs/
    workspace/
    notes/
```

推荐含义：

- `inputs/`：用于启动本次 demo 的稳定输入，如 mission、workflow、ledger、无密钥配置、辅助脚本。
- `workspace/`：实际交给 BureauLess 运行的可变工作区。
- `notes/`：人工记录、观察结论、后续问题、审计摘要。

`workspace/` 内的 BureauLess 原生输出应保持原样，例如：

- `generated/`
- `.bureauless/`
- `artifacts/`

不要在 run 结束后重新摊平、改名或搬运这些目录结构。

## 命名规范

run 目录使用“日期在前”的名字：

```text
YYYY-MM-DD-用途简述
```

例如：

- `2026-07-10-jojocode-live-demo`
- `2026-07-10-mutation-retry-real-agent`

## 每次 Run 的 README

每个 run 目录都应包含一个中文 `README.md`，至少写清：

- 测试目标
- 精确启动命令
- provider base URL
- 模型名
- agent id
- 本次运行是真实 agent 还是 fixture
- 重点观察哪些协议能力
- 最终结果
- 关键产物路径

不要在 README、YAML、脚本或笔记里写入原始 API Key。

## 测试任务与审计标准

今后的 live-demo 建议都单独写两段中文内容：

- `测试任务`：以任务发布人的口径描述目标、边界、约束、验收条件。
- `审计标准`：以外部观察者口径描述需要重点检查的违规、缺口和预期证据。

不要把“系统内部 orchestrator 应该怎么做”提前写死在测试任务里，除非本次 demo 的目的就是验证某条固定策略。

## 密钥与敏感信息

- 密钥只通过环境变量传入。
- 文档中只记录环境变量名，不记录具体值。
- 如果需要保存命令或日志摘录，先做脱敏。

## 默认流程

1. 创建新的日期目录。
2. 把稳定输入放入 `inputs/`。
3. 在 `workspace/` 中执行 demo。
4. 把中文摘要写入 `notes/` 或本次 run 的 `README.md`。
5. 用路径引用关键证据，不重复拷贝一份。

## 默认提交策略

通常只提交：

- 当前这个顶层 `README.md`
- 可复用的辅助脚本
- 已脱敏的示例输入
- 已脱敏的审计记录

当前 `.gitignore` 只允许每次 run 的根 `README.md`、`inputs/` 和 `notes/*.md`
进入待提交列表。提交前仍须人工确认它们不含密钥或不应公开的 provider 信息。

通常不要提交：

- `workspace/` 和 `runs/`
- `.bureauless/`
- 生成的 session 日志
- provider 认证材料
- 临时本地 workspace

如果某次 run 值得长期保留到 git，先脱敏，再只保留最小必要证据。
