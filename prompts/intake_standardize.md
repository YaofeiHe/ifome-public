# intake_standardize

使用场景：
- 对 `/ingest/auto` 的文本、链接或混合输入做入口标准化。
- 在真正切 section、扩关键词、访问链接之前，先让模型输出稳定的 intake 结构。

输入变量：
- `content`
- `heuristic_input_kind`
- `heuristic_urls`
- `heuristic_context_text`

输出结构：
- `input_kind`
- `should_visit_links`
- `shared_context_summary`
- `seed_entities`
- `relationship_family`
- `relationship_stage`
- `section_hints`
- `reason`

抽取约束：
- `input_kind` 只能是 `text`、`link`、`mixed` 三者之一。
- `should_visit_links` 必须是布尔值。
- `seed_entities` 和 `section_hints` 必须是字符串数组，去掉重复和空值。
- 如果文本包含“公司系 / 业务线 / 岗位方向”的明显信号，优先保留这些词。
- 如果文本包含统一的笔试、面试、DDL 或投递规则，要在 `shared_context_summary` 中保留。
- 不要直接改写原文事实，不要补充未出现的公司、岗位或时间。

标准化目标：
- 帮助后续流程把共享规则和岗位片段区分开。
- 帮助后续流程在访问链接前识别应该扩展哪些关键词。
- 帮助后续流程生成更稳定的 section / role variant / keyword hints。

错误案例：
- 只因为出现一个链接，就把 `input_kind` 判成 `link`，忽略了大量上下文说明。
- 把整个长文本原样塞进 `shared_context_summary`，没有压缩重点。
- 返回很多与招聘无关的泛词，例如“今天”“大家”“欢迎转发”。
