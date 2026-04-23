# Future Roadmap

这份文档现在只保留“未来规划”，不再重复已经完成的阶段。

已完成的历史阶段统一见：

- `docs/next_execution_plan.md`

## 未来主线 1：抽取语义继续细化

在当前通用 `ExtractedJobSignal` 之外，后续规划补一层“按分类的二级抽取 schema”，避免所有输入都硬塞进同一抽取对象。

建议演进方向：

- `JobPostingSignal`
- `InterviewNoticeSignal`
- `ResultNoticeSignal`
- `MarketUpdateSignal`

设计目标：

- 岗位、面试通知、结果消息、行情资讯分别保留更适合自己的字段
- 提醒、整理、后续问答可以按分类走不同策略
- 主链路仍共享统一的 `NormalizedItem` 与 `AgentState`，但抽取层语义更清晰

## 未来主线 2：验证后逐步脱离 LangGraph

这一点刻意保留在未来规划中，而不是当前阶段直接落地。

原因：

- 当前项目已经完成了第一轮可用性验证
- 现在更重要的是继续验证输入质量、检索质量、连接器价值
- runtime 替换应该建立在真实使用反馈和更稳定的核心链路上

未来方向：

- 让 `core/runtime` 逐步接管更多执行逻辑
- 保留 `core/schemas` 和节点接口不变
- 把 LangGraph 从“主执行器”降级成“可替代的 POC 编排层”

## 未来主线 3：公开仓库后的长期维护

项目上传 GitHub 后，未来规划默认包括：

- 每次功能增强同步更新文档
- 每次接口变化同步更新用户指南
- 每次架构变化同步更新执行总文档和面试文档
- 所有敏感信息只保留在本地环境，不进入仓库

## Future Schema Evolution

如果未来要继续细化 schema，优先考虑：

- item 去重标识
- 版本化抽取结果
- conversation thread 增量结构
- interview prep 与 project memory 的专用检索对象
