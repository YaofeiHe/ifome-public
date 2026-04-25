# classify

使用场景：
- 对 `NormalizedItem.normalized_text` 做高层分类。

输入变量：
- `normalized_text`
- `source_type`
- `rule_assessment`
- `keyword_hints`
- `search_references`
- `prompt_references`
- `user_hint`

输出结构：
- `category`
- `confidence`
- `reason`

错误案例：
- 文本过短，无法区分岗位信息和噪声。

分类原则：
- `job_posting`：出现明确岗位、投递方式、岗位要求、工作地点、截止时间等具体招聘信息。
- `interview_notice`：出现面试、笔试、OA、到场时间、面试地点、轮次等通知信息。
- `talk_event`：宣讲会、双选会、招聘会、说明会等活动通知。
- `referral`：明确的内推说明或内推入口。
- `general_update`：行业趋势、公司招聘节奏、求职建议、公众号汇总、经验贴、结果未明的泛消息。
- `noise`：寒暄、确认收到、无实际求职信息的短消息。

关键区分：
- “某类岗位变多了”“暑期实习提前启动了”“建议尽早准备”这类资讯，优先判为 `general_update`，不是 `job_posting`。
- 只有在文本里能定位到具体岗位机会时，才判为 `job_posting`。
- 不要因为出现“岗位”“实习”“招聘”几个字，就把资讯类内容误判成具体岗位。
- `rule_assessment` 是规则/数据库先给出的初判，你可以修正它，但不要无视它。
- `prompt_references` 是 SQLite 历史卡片和向量召回出来的参考片段，只能作为辅助证据，不能把旧卡片内容硬套到新输入上。
- 如果 `user_hint.force_content_category` 已存在，除非原文与 hint 明显冲突，否则应尽量保持一致。
- 如果文本是图片 OCR、文件转文本或市场监控入口产物，优先判断它描述的是“具体岗位机会”还是“泛化市场/进度信息”。

说明：
- 当前链路是“规则/SQLite 先判，低置信度时再调用 LLM”。
- 你的任务不是替代全部规则，而是在模糊样本上做更稳的最终判断。
