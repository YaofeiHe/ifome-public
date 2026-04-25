# deduplicate

使用场景：
- 判断两张求职/市场信息卡片是否属于同一核心信息，以及是否应该用新卡覆盖旧卡。

输入变量：
- `heuristic_precheck`
- `keyword_hints`
- `prompt_references`
- `current`
- `existing`

输出结构：
- `same_core`
- `should_replace_existing`
- `confidence`
- `reason`

判断原则：
- 先把 `heuristic_precheck` 当作规则层的初步判断，再结合两张卡的 `company`、`role`、`city`、`source_ref`、`apply_url`、时间字段和原文片段做最终决定。
- `keyword_hints` 和 `prompt_references` 用来帮助你理解公司、业务线、岗位别名和历史卡片上下文，但不能因为它们语义相近就忽略 `source_title / role_variant / identity_tag` 的冲突。
- 只有当两张卡描述的是同一个核心岗位/同一条核心市场信息时，`same_core` 才能为 `true`。
- 如果只是同集团、同批次、同一个合集里的不同岗位方向，不应合并。
- 如果新卡只是旧卡的更新版，且时间/链接/摘要等关键信息更完整，`should_replace_existing=true`。
- 如果核心内容相同但没有明显新增，`should_replace_existing=false`。

注意事项：
- `source_title`、`role_variant`、`identity_tag` 很重要，出现冲突时通常意味着两张卡不该合并。
- 对“填写内推码”“网申链接”“投递方式”这类动作型标题要降权，不要因为这些动作文本相似就误判成同卡。
- 只输出 JSON，不要解释过程。
