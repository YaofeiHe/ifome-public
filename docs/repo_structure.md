# Repo Structure

这份文档用来回答两个问题：

1. 当前仓库每一层分别负责什么。
2. 面试时应该怎么把这套结构讲清楚。

## 顶层目录

- `apps/`：可以独立运行的应用层，负责把能力暴露给用户或外部系统。
- `core/`：项目核心业务层，负责真正的求职信息处理逻辑。
- `integrations/`：外部平台接入层，负责和 Boss 直聘、日历、邮件等系统打交道。
- `prompts/`：Prompt 资产目录，避免把复杂提示词散落在 Python 代码里。
- `tests/`：单元测试、集成测试和后续评测回放。
- `docs/`：权威设计文档、路线图和面试讲解材料。
- `docs/assets/`：public 展示仓库使用的真实截图素材，可直接嵌入 README。
- `data/`：本地运行数据，例如当前 Reminder Queue 的 SQLite 文件。
- `public_sync_manifest.txt`：公共仓库同步白名单，只允许同步和个人信息无关的文件。
- 当前主要会生成 `workflows.sqlite3`、`memory.sqlite3`、`reminders.sqlite3`。

## `apps/` 应用层

### `apps/api`

职责：

- 接收输入请求
- 调用工作流
- 返回统一 API 响应
- 提供 memory、reminder、chat、experimental 等读写入口

关键文件：

- `apps/api/src/main.py`：FastAPI 入口和所有 HTTP 路由。
- `apps/api/src/contracts.py`：API 请求与响应 contract。
- `apps/api/src/services.py`：把 API 层和 `core/` 工作流、memory、storage 接起来。

这里最近多了一层很值得在面试里强调的职责：

- `services.py` 不只是把请求转发给工作流
- 它还负责 submission analysis、prompt 标准化、画像引导的主题识别、one-shot 搜索扩词、显式搜索参考注入、section split、role variant expand、长公告 campaign card 推断、平台无关关系标签生成、抓取计划生成、逐链接访问判断、低上下文链接强制抓取、附件与本地文件先转文本、市场信息刷新和候选卡片编排
- 现在市场信息刷新里又多了一层“基础网址 -> 站点级标题抓取或站点专用搜索适配器 -> 关键词规则排序并保留 1 篇探索项 -> 按记忆配置的文章上限抓正文 -> 大卡片/小卡片组织 -> 去重/历史清理”的编排
- 当标题搜索层拿不到结果时，`services.py` 还会回退到来源站点首页抓取，保证市场刷新仍然有可用产出
- 所以多岗位合集输入的应用层 orchestration 主要落在这里，而不是放进前端或持久化层
- 新增的批量卡片分析接口也在这里编排，因为它需要整合原文、标准化文本、标签和来源链接

当前面试时值得点出来的新接口包括：

- `POST /ingest/auto`：统一文本 / 链接混合输入入口
- `PATCH /items/{id}`：单卡片手动修改
- `DELETE /items/{id}`：单卡片删除
- `POST /items/batch-delete`：批量删除所选卡片
- `GET /items/{id}`：左键点击卡片后读取完整详情
- `POST /market/refresh`：手动或定时刷新市场信息卡

### `apps/web`

职责：

- 提供最小可用前端页面
- 展示卡片、提醒、记忆和聊天控制台
- 不承载核心业务判断

关键文件：

- `apps/web/app/page.tsx`：首页总览。
- `apps/web/app/ingest/page.tsx`：统一文本 / 链接输入页和截图输入页。
- `apps/web/app/items/page.tsx`：卡片列表页，支持编辑、删除、批量删除和详情查看。
- `apps/web/app/items/page.tsx`：卡片列表页，支持点击切换 `求职活动 / 市场信息`、编辑、删除、批量删除、详情查看、市场总览卡片下“展开文章列表（N）”按钮触发的小卡片列表展开，也支持求职活动里的多岗位 overview 卡下“展开岗位列表（N）”查看子岗位卡片，以及收敛后的单一市场刷新按钮与市场信息区直接显示批量删除入口。
- `apps/web/app/items/page.tsx`：同时负责把列表里的所有时间统一格式化成 `年月日 + 时分秒` 的前端显示格式。
- `apps/web/app/memory/page.tsx`：记忆管理页，市场监控源通过可滚动表格维护，并且可以直接配置每个来源单次刷新时的市场文章抓取上限。
- `apps/web/app/chat/page.tsx`：聊天控制台页，支持按时间窗口做近期卡片检索。
- `apps/web/app/lib/api.ts`：前端请求后端的统一封装。
- `apps/web/__init__.py`：让前端源码可以随安装包一起分发，供统一启动器在非源码场景下准备运行目录。
- `scripts/market_watch_recent_titles.py`：本地命令行脚本，用来单独测试某个站点是否能直接抓出近 24 小时标题列表。
- `scripts/probe_jiqizhixin_sources.py`：机器之心专用探测脚本，先验证公开页面、重定向入口和前端脚本里有没有可继续适配的标题源或 API 线索，再决定是否改主流程。

## `core/` 核心业务层

这是面试里最值得重点讲的一层，因为它承载了“业务语义”和“执行框架”。

### `core/graph`

职责：

- 定义主工作流有哪些节点
- 维护节点顺序和 LangGraph 编排方式
- 提供没有 LangGraph 时的顺序执行回退

关键文件：

- `core/graph/workflow.py`：工作流入口，支持 `run_sequential()` 和 `build_langgraph()`。
- `core/graph/nodes/*.py`：每个独立节点的实现。

最近值得点名的节点变化：

- `classify.py`：先走规则分类和 SQLite 里的已有卡片参考，只有在低置信度或边界样本时才升级到 LLM
- `extract.py`：会优先结合 `source_title / role_variant / semantic_tags` 稳定岗位抽取；规则抽取不完整时，再把关键词提示、自动关键词搜索参考、显式搜索参考、SQLite 历史卡片和可用向量召回一起组织进 LLM prompt
- `extract.py`：会把共享上下文里的全局 DDL 传播到岗位 / 内推类卡片
- `persist.py`：会先做结构化键和 heuristic score 的去重判断，只有落入模糊区间才调用 LLM，避免每张卡都走一遍语义去重
- `render.py`：会把地点待识别说明和求职 overview 父卡 / 子卡关系一起返回到卡片层

### `core/runtime`

职责：

- 定义运行时抽象接口
- 挂载模型路由、memory provider、trace logger、LLM gateway 等依赖
- 保证业务状态和执行器解耦

关键文件：

- `core/runtime/interfaces.py`：`BaseState`、`ModelRouter`、`LLMGateway` 等协议。
- `core/runtime/dependencies.py`：节点共享依赖容器。
- `core/runtime/settings.py`：环境变量和 feature flag 读取。
- `core/runtime/time.py`：统一时区时间工具。

### `core/cli.py`

职责：

- 提供统一命令行入口
- 一条命令同时启动前端和后端
- 自动打开浏览器并持续输出双端日志
- 按清单把公共文件同步到单独的 GitHub 仓库目录

当前主要命令：

- `ifome`：默认等价于 `ifome start`
- `ifome start`：统一启动前端和后端
- `ifome sync-public --target <目录>`：按 `public_sync_manifest.txt` 同步公共文件
- `ifome push-public --target <目录>`：同步公共文件后自动提交并推送到目标 Git 仓库
- `ifome push-public --github-token-file ~/GITHUB_TOKEN`：显式指定本地 token 文件做 HTTPS 推送，不把 token 写入仓库
- `docs/public_showcase.md`：定义 public 展示仓库该如何包装、展示哪些信息、哪些素材不能进入公开版本

### `core/schemas`

职责：

- 定义整个项目的统一数据结构
- 保证节点之间交换的是显式对象而不是隐式字典

关键文件：

- `core/schemas/base.py`：枚举、基础模型、时间校验。
- `core/schemas/items.py`：`NormalizedItem`、`ExtractedJobSignal`、`EvidenceSpan`。
- `core/schemas/memory.py`：长期画像和动态求职状态。
- `core/schemas/memory.py`：长期画像、动态求职状态，以及市场监控源基础网址与上次市场更新时间。
- `core/schemas/reminders.py`：提醒任务对象。
- `core/schemas/agent.py`：工作流总状态 `AgentState`。

### `core/extraction`

职责：

- 处理输入标准化
- 完成分类和结构化抽取
- 在 live LLM 不可用时提供规则回退

关键文件：

- `core/extraction/normalize.py`：输入清洗和标准化。
- `core/extraction/parse.py`：规则分类和规则抽取。
- `core/extraction/live_llm.py`：真实模型 classify / extract 接入。
- `core/extraction/prompt_context.py`：把 SQLite 历史卡片、显式搜索参考和可用的向量召回整理成给 classify / extract / dedupe 的 prompt 参考上下文。

这层最近新增的实用点：

- 能从共享文本里提取多日期并挑出最近有效日期
- 在没有明确城市时，可以生成“地点待识别，可能为线上，需投递后确认”这类说明
- 对“算法工程师-生成器式方向 / 数据研发工程师”这类岗位方向的角色抽取更稳
- 关系识别不再局限于阿里系，改成了平台无关的 `family / stage / unit / identity_tag` 结构
- `classify / extract / dedupe` 不再是无脑每次先调 LLM，而是先走规则和已有卡片检索，只有在低置信度或模糊区间才升级到 LLM
- 新增的 `prompt_context.py` 会把自动关键词搜索结果、显式搜索参考、SQLite 相似卡片和可用向量召回整理成统一 prompt 参考，给分类、抽取和去重复用

### `core/ranking`

职责：

- 负责画像匹配和优先级评分
- 目前还是规则打底，后续会逐步接入更强的语义打分

关键文件：

- `core/ranking/scorer.py`

### `core/memory`

职责：

- 管理长期画像和动态求职状态
- 为后续聊天、匹配和提醒提供上下文
- 隔离实验功能

关键文件：

- `core/memory/experimental/project_self_memory.py`：可开关、可删除的实验模块。

### `core/chat`

职责：

- 基于历史条目和 memory 做 grounded chat
- 在 live RAG 和 local fallback 之间切换
- 给前端返回可解释的 citations

关键文件：

- `core/chat/rag.py`：当前 grounded chat / RAG 检索与回答服务，负责 query analysis、时间窗过滤、类型偏置与 citation 组织。

### `core/reminders`

职责：

- 生成提醒任务
- 维护提醒池读写

关键文件：

- `core/reminders/planner.py`
- `core/reminders/queue.py`

### `core/tools`

职责：

- 封装所有外部工具和外部服务调用
- 避免把 SDK 代码直接写进业务节点

关键文件：

- `core/tools/llm_client.py`：OpenAI-compatible live LLM 适配器。
- `core/tools/ocr_client.py`：图片 OCR 适配器，默认复用通用 LLM 的多模态能力；若启用独立 OCR 配置则优先走独立 OCR，否则回退本地 `tesseract`。
- `core/tools/embedding_client.py`：DashScope embedding 适配器。
- `core/tools/prompt_loader.py`：Prompt 读取器。
- `core/tools/search_client.py`：one-shot web search 适配器，用于在画像引导主题识别之后扩公司 / 业务线关键词，也用于发现市场监控源最近 24 小时的标题/链接候选；当前不能保证抓到站点“全部”文章，只能消费搜索结果返回的候选集合。
- `core/tools/web_page_client.py`：网页正文抓取器，会识别站点验证页 / 拦截页，避免把无效正文送入工作流，并尽量提取文章来源发布时间。
- `core/tools/recent_site_titles.py`：实验性的站点级近 24 小时标题发现器，按 `JSON-LD/listing pages -> feed -> sitemap -> homepage links` 顺序尝试直接从网站本身抓标题和链接；目前已经正式接入量子位，也已经给机器之心接上 `article_library` 标题 API。
- 机器之心这条链路现在的真实结构是：
  - 先从 `rss` / 数据服务页定位 `文章库` 入口
  - 再从前端 bundle 里确认 `article_library/articles.json` 列表 API
  - 用这个 API 导出近 24 小时标题和发布时间
  - 如果详情页匿名抓取失败，就先用 API 自带摘要回退生成市场子卡
- `prompts/market_watch_title_rank.md`：市场文章标题级筛选 prompt 预留位；当前线上主逻辑已经改成确定性关键词排序，不再把它作为第一优先级。
- `prompts/market_watch_overview.md`：固定来源标题列表的大卡片总览 prompt。
- `core/tools/vector_store.py`：Qdrant REST vector store 适配器。
- `core/tools/email_client.py`、`calendar_client.py`、`web_push_client.py`：通知接口预留。

### `core/storage`

职责：

- 承担持久化边界
- 当前包含内存仓库、workflow SQLite、memory SQLite 和 reminder SQLite

关键文件：

- `core/storage/in_memory.py`
- `core/storage/sqlite_workflows.py`
- `core/storage/sqlite_memory.py`
- `core/storage/sqlite_reminders.py`

面试时可以补一句：

- `sqlite_workflows.py` 现在不只是“保存卡片”，还承担按用户 / workspace 过滤、单条删除等卡片管理边界
- 批量删除能力在 service 层编排，保持 repository 仍然是简单稳定的持久化边界
- 多岗位合集的拆卡与逐链接访问判断放在 service 层编排，而不是塞进 repository 或前端
- “哪些卡该合并、哪些卡必须拆开”现在由 workflow + persist 节点共同决定，而不是由 repository 粗暴处理

## `integrations/` 接入层

当前主要是目录占位，后续最重要的是：

- `boss_zhipin/`：读取 Boss 直聘岗位详情和 HR 对话内容
- `email/`：邮件同步
- `calendar/`：日历事件同步

当前 `boss_zhipin/` 已经有第一版最小接入文件：

- `integrations/boss_zhipin/contracts.py`
- `integrations/boss_zhipin/translator.py`

这层的边界是“把外部平台数据转成内部统一输入”，而不是在这里做排序、提醒或聊天策略。

## `prompts/` Prompt 资产目录

职责：

- 存放 classify、extract、rank、summarize、interview_prep、memory_write_gate 等提示词
- 让 prompt 和节点执行逻辑分离

最近新增：

- `intake_standardize.md`：专门给 `/ingest/auto` 的文本 / 链接上传入口做标准化输出
- 以后只要上传接口的标准化逻辑变化，就同步调整这份 prompt

面试时可以强调：

- Prompt 是资产，不是散落在代码里的字符串
- 这样更利于 review、A/B 调整和后续迁移

## `tests/` 测试层

当前已覆盖：

- schema 时间校验
- reminder 规划与 SQLite 队列
- memory 写入策略和 feature flag
- 最小工作流端到端闭环
- link / image 真实输入接入路径
- 多岗位合集输入的拆 section、拆 role variant、抓取计划与防误去重路径
- 平台无关关系标签与批量卡片分析路径
- prompt 库驱动的 intake standardize 与搜索扩词前置路径
- SQLite workflow / memory 重启持久化
- Boss 直聘岗位 / 对话最小接入路径
- grounded chat / RAG 检索与引用路径
- 卡片去重、覆盖、手动编辑、单条删除、批量删除

后续会继续补：

- live provider 适配层测试
- Boss 直聘 connector 回放测试
- 小规模评测集

## 面试推荐讲法

推荐按这条顺序讲：

1. `apps` 是对外入口。
2. `core/schemas` 定义显式状态。
3. `core/graph + core/runtime` 决定主工作流怎么跑。
4. `core/extraction / ranking / reminders / memory` 承担业务语义。
5. `core/tools / storage / integrations` 负责外部依赖和持久化边界。

这样能把“业务语义”和“执行框架”讲得非常清楚。
