# Memory Design

## 目标

记忆系统要服务真实求职管理，也要便于面试讲解，因此不把“记忆”简化为一段隐式 prompt 拼接，而是做成显式分层结构。

## 三层记忆

### Profile Memory

长期且相对稳定的用户画像，例如目标岗位、优先行业、技能标签、项目经历、城市偏好和明确排除项。

### Career State Memory

动态变化的求职状态，例如已投岗位、正在推进的面试、今日关注事项、最近 DDL 和重点公司。

### Document Memory

用户上传的简历、JD、项目资料、面试题整理等文档资产。

## 写入策略

- 默认不把所有输入直接写入长期记忆。
- 所有写入都应支持 `context_only` 与 `persist_to_long_term` 两种模式。
- 记忆写入需要结构化审计信息，至少包含 `trace_id`、`user_id`、`workspace_id` 和来源说明。

## 实验功能隔离

“把项目自身信息写入长期记忆”只允许放在 `core/memory/experimental`，并通过 `ENABLE_PROJECT_SELF_MEMORY` 之类的 feature flag 控制。

这项能力不能：

- 修改主链路 schema 的语义边界。
- 让职位处理流程依赖实验模块。
- 污染多用户通用逻辑。

当前实现约束：

- 实验能力单独位于 `core/memory/experimental/project_self_memory.py`
- 通过 `ENABLE_PROJECT_SELF_MEMORY` 控制是否可用
- 仅通过独立 API 旁路写入 profile memory，不自动参与主工作流
- 关闭 flag 后，主链路继续可运行，不受影响
