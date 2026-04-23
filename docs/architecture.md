# Architecture

## 权威约束

后续所有实现都必须以以下文档为准：

- `docs/job_agent_whitepaper.md`
- `docs/job_agent_engineering_doc.md`

如果某次实现和这两份文档冲突，应优先修正文档或显式记录偏差，而不是让代码 silently 漂移。

## 分层设计

### 1. 接入层

- `apps/api`
- `integrations/*`

负责接收文本、链接、图片和未来连接器输入，并生成请求级 `trace_id`。

其中：

- `apps/` 是可独立运行的应用层，负责把系统能力暴露成 HTTP API、Web 页面或未来的 worker 进程。
- `integrations/` 是平台接入层，负责和外部系统交互，例如读取 Boss 直聘岗位详情、同步 HR 对话记录、接入邮件或日历接口。
- 当前 `integrations/boss_zhipin` 已落下最小 connector contract 与 translator，用来把平台 payload 转成统一 workflow 输入。

### 2. 工作流层

- `core/graph`
- `core/runtime`

负责执行 `ingest -> normalize -> classify -> extract -> match_profile -> score -> reminder_plan -> persist -> render` 这条主链路。

LangGraph 只作为 POC 编排框架，节点接口与状态对象必须保持框架无关，方便迁移到手写 Runtime。

其中：

- `core/graph` 负责定义“有哪些节点、节点之间怎么流转”。
- `core/runtime` 负责定义“由谁驱动这些节点执行”，也就是执行器抽象、状态传递契约、工具分发和模型路由接口。
- `core/runtime` 不是业务规则本身，而是业务规则的承载与执行方式。

### 3. 领域层

- `core/schemas`
- `core/memory`
- `core/extraction`
- `core/ranking`
- `core/reminders`
- `core/chat`

负责保存业务语义，禁止把复杂业务逻辑塞进 UI 或第三方 SDK 包装代码。

这里的 `core/` 就是项目核心业务层。它和 `apps/` 的区别是：

- `apps/` 关心“系统怎么被访问”。
- `core/` 关心“系统拿到请求后应该怎么处理”。
- 同一套 `core/` 逻辑理论上可以被 API、Web、worker 甚至命令行复用。

### 4. 工具与基础设施层

- `core/tools`
- `core/observability`
- `core/storage`

负责工具调用、日志、持久化和成本观测。

提醒系统在当前阶段的落地方式：

- `core/reminders/planner.py` 负责生成提醒任务
- `core/reminders/queue.py` 负责提醒池写入和读取
- `core/storage/sqlite_reminders.py` 负责把提醒任务落到本地 SQLite
- `core/storage/sqlite_workflows.py` 负责把 item / workflow state 快照落到本地 SQLite
- `core/storage/sqlite_memory.py` 负责把 profile / career-state memory 落到本地 SQLite
- `core/tools/*_client.py` 预留邮件、日历、Web Push 的适配器接口
- `core/tools/web_page_client.py` 负责轻量网页正文抽取
- `core/tools/ocr_client.py` 负责本地 OCR 适配

## 关键架构原则

- 单节点单职责。
- 状态显式传递。
- Prompt 与业务逻辑分离。
- 实验功能通过 `core/memory/experimental` 和 feature flag 隔离。
- 模型路由必须为成本控制留接口，不默认所有请求都走高成本模型。

实验模块当前落地方式：

- `core/memory/experimental/project_self_memory.py` 负责实验性项目记忆写入逻辑
- `ENABLE_PROJECT_SELF_MEMORY` 控制开关
- `POST /experimental/project-self-memory` 作为独立入口
- 主 `ingest -> ... -> render` 工作流不依赖实验模块

## 模型与 RAG 收敛方案

当前项目后续默认按以下方案收敛：

- 生成主路由：DashScope / Qwen
- 复杂推理升级路由：OpenAI GPT-5.4，默认先关闭
- Embedding：DashScope `text-embedding-v4`
- 向量数据库：Qdrant
- 可选低成本备用推理路由：DeepSeek

设计原则：

- 模型层优先采用 OpenAI-compatible HTTP API，降低接入与切换成本。
- 向量库层保留各自原生协议或官方 SDK，不强行套成统一外部协议。
- 项目内部通过自定义 adapter 层统一成 `generate / embed / search / rerank` 这类接口。
- MCP 更适合作为未来对外暴露工具能力的协议，而不是替代底层向量库或模型 SDK。

当前落地进度：

- `core/tools/llm_client.py` 已提供 OpenAI-compatible live LLM adapter
- `core/tools/embedding_client.py` 已提供 DashScope embedding adapter
- `core/tools/vector_store.py` 已提供 Qdrant REST adapter
- `core/extraction/live_llm.py` 已接入第一批真实服务替换点
- `core/chat/rag.py` 已把聊天控制台升级成 grounded chat
- 当前优先替换的节点是 `classify` 与 `extract`
- 调试阶段默认 `ENABLE_OPENAI_ROUTING=false`
- DashScope 当前支持主模型加候选降级模型链
- 当未配置 API Key 或 live 调用失败时，节点会自动回退到规则逻辑

## 账号与环境变量准备

后续真正接入外部模型与检索组件前，需要准备：

- 阿里云账号，开通 DashScope / 百炼并生成 `DASHSCOPE_API_KEY`
- OpenAI Platform 账号，开通 billing 并生成 `OPENAI_API_KEY`
- Qdrant Cloud 集群，记录 `QDRANT_URL` 与 `QDRANT_API_KEY`
- 可选：DeepSeek Platform 账号与 `DEEPSEEK_API_KEY`

仓库根目录提供了 `.env.example`，后续可按它补全本地环境变量。
