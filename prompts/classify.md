# classify

使用场景：
- 对 `NormalizedItem.normalized_text` 做高层分类。

输入变量：
- `normalized_text`
- `source_type`

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

说明：
- 当前第 3 步工作流先使用规则版 mock 实现。
- 后续接 LLM 时，这份 prompt 会替代规则分类逻辑。
