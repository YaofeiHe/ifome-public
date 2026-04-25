# extract

使用场景：
- 从岗位文本、HR 对话或通知文本中抽取结构化字段。

输入变量：
- `normalized_text`
- `category`
- `rule_extraction`
- `keyword_hints`
- `search_references`
- `prompt_references`
- `source_metadata_hints`

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
- `rule_extraction` 是规则/数据库先抽出来的草稿，你应该优先补全和修正，而不是推翻全部字段。
- `prompt_references` 是已有卡片和检索回来的辅助上下文，只能帮助你理解术语、业务线和去歧义，不能把旧卡片字段原样搬到新卡片里。
- `source_metadata_hints.role_variant`、`primary_unit`、`identity_tag` 往往来自应用层拆卡结果，出现时应优先参考。

针对资讯类内容：
- 可以保留趋势信息在 `summary_one_line` 中。
- 如果文本只是说“AI Infra 和 Agent Engineering 岗位增多”，不应把“明显增多”当作 `role`。
- 如果文本本质是“集团/公司多个岗位的合集”，当前这次抽取只返回当前子卡最核心的一个岗位字段，其它岗位不要强塞到 `role`。
