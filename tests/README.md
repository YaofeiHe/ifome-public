# Tests

测试会按三层补齐：

- schema 与纯函数单元测试
- 输入到卡片输出的工作流集成测试
- 小规模评测集回放

当前已覆盖：

- `test_schemas.py`：核心 schema 时间校验
- `test_reminders.py`：提醒规划与 SQLite 队列
- `test_memory.py`：memory 写入策略与 experimental feature flag
- `test_workflow.py`：最小工作流端到端闭环
- `test_live_llm_integration.py`：live LLM 接入路径与回退兼容性
- `test_phase11_inputs.py`：link 正文抓取与 image OCR 输入链路
- `test_phase12_persistence.py`：workflow state / memory 的 SQLite 持久化与重启读取
- `test_phase13_boss_zhipin.py`：Boss 直聘岗位详情与 HR 对话的最小 connector 路径
- `test_phase14_rag_chat.py`：grounded chat 的 live / fallback 检索与 citations
