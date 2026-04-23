# Public Showcase Guide

这份文档用于定义 public 展示仓库应该如何包装，而不是如何继续做主开发。

## 展示策略

- 主开发仓库继续保持 private。
- public 展示仓库只放：
  - 可运行的公共代码
  - 精简后的 README 展示内容
  - 架构说明、模块说明、接口说明、测试说明
  - 不含个人信息的截图、示意图和演示资产

## public 仓库首页应该回答的问题

### 1. 这个项目解决什么问题

- 求职信息来源碎片化
- 手工整理成本高
- DDL、笔试、面试、宣讲、市场行情容易遗漏
- 用户需要的是“围绕个人画像的信息治理和决策支持”，不是泛聊天机器人

### 2. 当前版本已经完成什么

- 统一输入：文本、链接、OCR
- 明确工作流：normalize / classify / extract / score / reminder_plan / render
- 卡片持久化与去重更新
- 用户画像与动态求职状态
- grounded chat / RAG
- 市场信息刷新、大卡片 / 小卡片结构
- pip 安装与一键启动
- 公共同步与一键推送

### 3. 还在迭代中的模块

- 真正独立的服务端 scheduler
- 更强的网站级抓取适配器
- 更稳定的 live LLM / ranking / retrieval 评测体系
- 更细的前端体验和更真实的产品化设计

## 展示素材建议

- README 顶部放一张系统架构图
- README 中部放 2 到 3 张前端页面示意图
- README 末尾放测试、完成度和下一步计划

## 不允许放进 public 仓库的展示素材

- 带有你个人画像、真实公司申请记录或私人面试准备的截图
- 带 token、cookie、邮箱、绝对路径的信息
- 本地数据库和运行日志

## 这轮已经落地的展示资产

- `docs/assets/system-architecture.png`
- `docs/assets/home-workbench.png`
- `docs/assets/job-cards.png`
- `docs/assets/market-cards.png`

说明：

- public 展示仓库的可视化部分只使用这几张实际截图
- 不再额外加入其他示意图，避免展示素材和真实界面脱节
- 卡片展示图当前统一使用 `job-cards.png`，不再保留旧的 `job-cards.jpg`
