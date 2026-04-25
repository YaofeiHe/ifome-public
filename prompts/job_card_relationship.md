# job_card_relationship

使用场景：
- 在两张已经确认“不直接去重”的求职卡之间，判断它们是否属于同一家公司/业务线下的并列关系或从属关系，从而决定是否要组织成 overview 父卡 + 子卡。

输入变量：
- `keyword_hints`
- `prompt_references`
- `current`
- `existing`
- `current_entity_candidates`
- `existing_entity_candidates`
- `related_existing_cards`

输出结构：
- `relation`
- `confidence`
- `reason`
- `group_title`

字段约束：
- `relation` 只能取：`none`、`parallel`、`subordinate`、`parent`
- `confidence` 必须是 0 到 1 的小数
- `group_title` 可以为 `null`

判断原则：
- 如果两张卡是同一家公司或同一业务线下的不同岗位方向、不同子部门岗位、同一批次岗位合集里的不同子项，通常应判定为 `parallel` 或 `subordinate`。
- 如果 `current` 更像子部门/子岗位，`existing` 更像公司级、业务线级或合集级主题，可以判定为 `subordinate`。
- 如果 `current` 更像主题更大的岗位总览，而 `existing` 更像具体子项，可以判定为 `parent`。
- 如果两张卡只是同公司但彼此独立、没有明显合集关系，不要勉强归类，返回 `none`。
- 这里不负责重复判断；如果只是同一条信息的更新版，外层 dedupe 应先处理掉。
- `existing_entity_candidates` 和 `related_existing_cards` 代表旧卡里可能隐藏的多个岗位/业务线实体，以及同簇旧卡摘要。你应结合这些信息重建旧卡-新卡之间的真实层级，而不是只看旧卡表面抽出的单个 `company/role`。

`group_title` 规则：
- 如果判断为 `parallel`、`subordinate` 或 `parent`，尽量给出一个稳定的合集标题。
- 优先用“公司/业务线/招聘阶段”这类稳定主题，不要用动作语、链接语、口号语。
- 例子：`阿里系-暑期实习-淘宝闪购`、`字节系-暑期实习-抖音电商`

注意事项：
- `prompt_references` 只能帮助你理解公司、业务线和历史卡片上下文，不能机械抄写旧卡标题。
- 如果旧卡里同时出现多个岗位或多个业务线，应优先通过 `existing_entity_candidates` 和 `related_existing_cards` 识别“旧卡其实是合集/上位主题”的情况，再判断是否需要建立 overview 父卡。
- 如果 `source_title`、`identity_tag`、`role_variant` 明显冲突，通常不应强行归成同一 overview。
- 只输出 JSON，不要解释过程。
