# extract

使用场景：
- 从岗位文本、HR 对话或通知文本中抽取结构化字段。

输入变量：
- `normalized_text`
- `category`

输出结构：
- `company`
- `role`
- `city`
- `ddl`
- `event_time`
- `interview_time`
- `apply_url`
- `summary_one_line`
- `confidence`

错误案例：
- 文本只提到活动，不提公司和岗位。
- 时间表达模糊，例如“下周一下午”。

抽取约束：
- `role` 必须是单个字符串或 `null`，不要返回数组。
- 如果文本里提到多个岗位方向，不要把整个列表塞进 `role`；优先返回最核心的一个，或者返回 `null` 并把多岗位信息放到 `tags`/`summary_one_line` 的语义里。
- 如果 `category` 是 `general_update`，通常不应该强行抽出具体 `company`、`role`、`ddl`。
- 如果没有明确公司，就返回 `null`，不要根据常识猜测。
- 如果没有明确投递入口，就返回 `null`，不要从上下文臆造 URL。
- `summary_one_line` 应该忠实概括文本，而不是强行写成岗位卡片标题。

针对资讯类内容：
- 可以保留趋势信息在 `summary_one_line` 中。
- 如果文本只是说“AI Infra 和 Agent Engineering 岗位增多”，不应把“明显增多”当作 `role`。
