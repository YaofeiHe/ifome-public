# Prompts

Prompt 与业务逻辑分离，后续至少拆分为：

- `classify`
- `extract`
- `intake_standardize`
- `rank`
- `summarize`
- `market_watch_summarize`
- `market_watch_title_rank`
- `market_watch_overview`
- `interview_prep`
- `memory_write_gate`

每个 prompt 文件都需要说明：

- 使用场景
- 输入变量
- 输出结构
- 错误案例

当前新增约定：

- 入口类能力优先放在 `intake_standardize.md`
- 只要 `/ingest/auto` 的文本/链接标准化逻辑发生变化，就同步调整这份 prompt
- 市场信息刷新链路的总结、建议和关键词抽取放在 `market_watch_summarize.md`
- 市场标题列表的第一轮筛选现在优先走 `services.py` 里的确定性关键词规则和多样性保留逻辑，`market_watch_title_rank.md` 仅保留为后续可选扩展
- 固定来源的大卡片总览放在 `market_watch_overview.md`
- 市场信息 prompt 现在还会结合 `message_time` 判断时效性，帮助卡片生成“值得跟进 / 继续观察 / 偏旧谨慎”的建议
- 模型运行时优先从 prompt 库读取，不在 service 里硬编码 system prompt
