# rank

使用场景：
- 基于抽取结果和用户画像生成匹配解释与优先级建议。

输入变量：
- `extracted_signal`
- `profile_memory`
- `career_state_memory`

输出结构：
- `fit_score`
- `urgency_score`
- `priority`
- `recommended_action`
- `reasoning`

错误案例：
- 职位描述过短，难以判断真实匹配度。
