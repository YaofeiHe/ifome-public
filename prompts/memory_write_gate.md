# memory_write_gate

使用场景：
- 判断一段内容是否应该写入长期记忆。

输入变量：
- `normalized_item`
- `memory_write_mode`
- `current_profile_summary`

输出结构：
- `allow_write`
- `memory_type`
- `reason`

错误案例：
- 聊天噪声被误判成长期画像信息。
