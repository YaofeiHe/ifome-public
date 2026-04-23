# 求职信息流 Agent 工程说明文档

## 1. 文档目的
本文件用于指导项目开发，目标是：
- 确保系统不是黑盒
- 确保代码结构便于讲解、调试和扩展
- 确保后续可以从框架迁移到手写 Runtime
- 确保“项目自身写入长期记忆”是可拆卸的临时功能

---

## 2. 仓库建议结构

```text
job-hunt-agent/
├─ apps/
│  ├─ api/
│  ├─ web/
│  └─ worker/
├─ core/
│  ├─ graph/
│  ├─ runtime/
│  ├─ schemas/
│  ├─ memory/
│  │  ├─ profile/
│  │  ├─ career_state/
│  │  ├─ docs/
│  │  └─ experimental/
│  ├─ extraction/
│  ├─ ranking/
│  ├─ reminders/
│  ├─ tools/
│  ├─ chat/
│  ├─ observability/
│  └─ storage/
├─ integrations/
│  ├─ xhs/
│  ├─ calendar/
│  ├─ email/
│  ├─ wechat/
│  └─ boss_zhipin/
├─ prompts/
├─ tests/
├─ data/
├─ docs/
└─ README.md
```

---

## 3. 核心数据模型建议

### 3.1 NormalizedItem
表示统一化后的输入。

建议字段：
- `id`
- `user_id`
- `source_type` (`text` / `link` / `image`)
- `source_ref`
- `raw_content`
- `normalized_text`
- `created_at`
- `trace_id`

### 3.2 ExtractedJobSignal
表示抽取出的招聘信息。

建议字段：
- `company`
- `role`
- `city`
- `interview_location`
- `ddl`
- `event_time`
- `apply_url`
- `summary_one_line`
- `confidence`
- `source_item_id`

### 3.3 ProfileMemory
长期画像。

建议字段：
- `target_roles`
- `priority_domains`
- `skills`
- `projects`
- `location_preferences`
- `hard_filters`
- `soft_preferences`

### 3.4 CareerStateMemory
动态求职状态。

建议字段：
- `applied_jobs`
- `active_interviews`
- `watched_companies`
- `today_focus`
- `upcoming_deadlines`

### 3.5 ReminderTask
建议字段：
- `id`
- `user_id`
- `source_item_id`
- `title`
- `trigger_time`
- `priority`
- `channel`
- `status`
- `payload`

---

## 4. 代码组织原则

### 4.1 每个节点单一职责
每个工作流节点只做一件事，不要：
- 在 `extract` 里顺便写提醒
- 在 `match_profile` 里顺便发通知
- 在 `render` 里顺便落库

### 4.2 Prompt 与业务逻辑分离
Prompt 应放在 `prompts/`，不要把复杂 prompt 直接写在函数体里。

### 4.3 工具调用必须封装
例如：
- `tools/calendar_client.py`
- `tools/email_client.py`
- `tools/ocr_client.py`

不要把第三方 SDK 直接散落到业务代码中。

### 4.4 状态对象显式传递
无论使用 LangGraph 还是手写 Runtime，节点都应基于显式 `state` 读写，而不是靠全局变量。

### 4.5 连接器命名要指向具体平台
连接器目录不要用模糊名称，应该直接体现外部平台语义，例如：
- `integrations/boss_zhipin/`
- `integrations/wechat/`
- `integrations/xhs/`

这样在讲架构时可以直接说明“这是 Boss 直聘连接器”，避免把招聘平台、业务模块和聊天策略混为一谈。

### 4.6 Boss 直聘连接器的职责边界
`integrations/boss_zhipin/` 负责：
- 读取 Boss 直聘岗位详情
- 读取 HR 发来的对话内容
- 把平台原始数据转换成主链路可处理的标准输入

它不负责：
- 做岗位匹配打分
- 直接决定回复策略
- 自动代替用户给 HR 发消息

聊天辅助能力应放在 `core/chat/`，连接器只提供平台数据接入与必要的读写封装。

### 4.7 Reminder Queue 的实现边界
提醒系统应明确拆成三层：

- planner：从业务字段生成提醒任务
- queue：把提醒任务放入可调度队列
- adapter：把提醒任务转换成邮件、日历、Web Push 等外部发送格式

当前阶段要求：

- reminder task 先落本地 SQLite
- 不在 planner 或 queue 中直接调用真实通知服务
- 真实通知适配器仅保留接口预留，不进入主链路

---

## 5. 注释与文档标准

### 5.1 类注释
每个核心类必须有 docstring，至少说明：
- 它是什么
- 它负责什么
- 它不负责什么
- 关键输入输出

示例：

```python
class ReminderPlanner:
    """
    Build reminder tasks from extracted job signals.

    Responsibilities:
    - Inspect ddl/event_time/interview_time fields.
    - Convert them into normalized reminder tasks.

    Non-responsibilities:
    - Sending notifications.
    - Updating career state memory.
    """
```

### 5.2 函数注释
每个节点函数建议说明：
- 输入 state 依赖哪些字段
- 输出写回哪些字段
- 失败时如何处理
- 是否允许回退或重试

### 5.3 Prompt 文件注释
每个 prompt 文件开头建议注明：
- 使用场景
- 输入变量
- 输出结构
- 错误案例

### 5.4 为什么必须这样做
因为这个项目本身是一个面试型项目。你需要能对面试官解释：
- 为什么这样拆节点
- 为什么不做成黑盒对话
- 为什么这一步用低成本模型
- 为什么这一步要人工介入

---

## 6. 可观测性设计

### 6.1 必备指标
- trace_id
- request_id
- source_type
- model_name
- latency_ms
- token_estimate
- estimated_cost
- node_status
- error_reason

### 6.2 日志级别
- `INFO`：任务开始、结束、模型路由、提醒创建
- `WARNING`：抽取置信度低、字段缺失、提醒时间模糊
- `ERROR`：OCR 失败、外部工具失败、持久化失败

### 6.3 样本回放
建议保存一组真实样例作为回放输入：
- 一条标准岗位链接
- 一张聊天截图
- 一段纯文本通知
- 一条容易误判的噪声消息

---

## 7. 记忆系统实现建议

### 7.1 写入长期记忆必须显式确认
不要默认把所有上传内容都写进长期记忆。

建议提供两个入口：
- `context_only`
- `persist_to_long_term`

### 7.2 临时功能：项目自身写入长期记忆
建议实现为：
- `core/memory/experimental/project_self_memory.py`
- 由 feature flag 控制，例如 `ENABLE_PROJECT_SELF_MEMORY`

移除时只需要：
1. 关闭 feature flag
2. 删除 experimental 模块
3. 移除相关 UI 配置入口

不应污染：
- Profile Memory 的基础 schema
- 多用户画像逻辑
- 职位处理主链路

当前实现约束：
- 实验逻辑只通过独立 service 和独立 API 调用
- 关闭 flag 后 API 应拒绝写入，但主链路仍然正常
- 删除该能力时，不应修改主 workflow 节点顺序或核心 schema 语义

---

## 8. Prompt 设计建议

### 8.1 prompt 不要做成一把梭
至少拆成：
- `classify`
- `extract`
- `rank`
- `summarize`
- `interview_prep`
- `memory_write_gate`

### 8.2 输出尽量 JSON 化
例如：

```json
{
  "company": "xxx",
  "role": "xxx",
  "ddl": "2026-05-01T18:00:00+08:00",
  "priority": "P1",
  "reason": "role matches backend + AI engineering profile"
}
```

### 8.3 失败策略
当模型无法确定时：
- 输出 `unknown`
- 给出 `confidence`
- 不要伪造字段

---

## 9. 测试建议

### 9.1 单元测试
覆盖：
- schema 校验
- 时间解析
- reminder 生成
- memory 写入策略

### 9.2 集成测试
覆盖：
- 文本输入到卡片输出全链路
- 链接输入到提醒创建
- 图片输入 OCR 后抽取

### 9.3 评测集
建立一个小型 eval 数据集，记录：
- 是否正确抽出 DDL
- 是否识别岗位方向
- 是否误报为高优先级
- 是否错误创建提醒

---

## 10. 迁移到手写 Runtime 的接口预留

建议尽早定义以下抽象接口：
- `BaseNode`
- `BaseState`
- `ToolDispatcher`
- `MemoryProvider`
- `TraceLogger`
- `ModelRouter`

这样可以让业务逻辑尽量不依赖具体框架。

## 10.1 当前默认 Provider 方案

为了减少后续选型漂移，当前仓库默认按以下组合实现：

- 主生成模型：DashScope / Qwen
- 高复杂度升级模型：OpenAI GPT-5.4
- Embedding：DashScope `text-embedding-v4`
- 向量数据库：Qdrant
- 可选 fallback：DeepSeek

要求：

- 模型调用层优先采用 OpenAI-compatible API 适配。
- 向量库使用官方 SDK 或原生协议。
- 项目内部统一通过 adapter 封装，不让业务模块直接依赖第三方 SDK。

## 10.2 本地环境变量

后续接真实服务时，至少预留以下环境变量：

- `DASHSCOPE_API_KEY`
- `OPENAI_API_KEY`
- `QDRANT_URL`
- `QDRANT_API_KEY`
- `DEEPSEEK_API_KEY`（可选）

对应示例文件位于仓库根目录 `.env.example`。

---

## 11. 研发过程中的“别做”清单

- 不要把整个系统写成一个超长 prompt
- 不要所有请求都走最强模型
- 不要在 UI 层直接调用第三方 SDK
- 不要把用户画像硬编码在代码里
- 不要让实验功能污染主链路
- 不要为了炫技过早引入多 Agent

---

## 12. 推荐开发节奏

1. 先把输入、抽取、展示跑通
2. 再加匹配分和提醒池
3. 再加聊天控制台
4. 再补可观测性和评测
5. 最后再考虑手写 Runtime

这能最大程度降低黑盒感，并确保你始终知道系统每一步在做什么。
