# User Guide

这份文档面向项目使用者，目标是回答：

- 这个工具能做什么
- 应该怎么启动
- 平时怎么使用
- 现在有哪些边界

## 这个工具是什么

`ifome` 是一个面向求职场景的信息流整理工具。

它能把这些输入统一收敛成可处理条目：

- 招聘文本
- 招聘链接
- 截图 / OCR
- PDF / 文本文件
- 本地图片或文件路径
- Boss 直聘岗位详情
- Boss 直聘 HR 对话

系统会自动完成：

- 清洗输入
- 分类
- 抽取结构化信息
- 结合你的画像做匹配
- 给出优先级
- 生成提醒
- 存储条目和 memory
- 支持后续问答

## 启动方式

### 1. 安装项目

```bash
cd ifome
pip install -e .
```

### 2. 一键启动

```bash
ifome
```

这条命令会自动完成：

- 启动 FastAPI 后端
- 启动 Next.js 前端
- 在当前终端持续输出双端日志
- 自动打开浏览器
- 前端依赖缺失时先执行一次 `npm install`

常用可选项：

```bash
ifome --no-browser
ifome --api-port 8100 --web-port 3100
ifome --project-dir /absolute/path/to/ifome
```

说明：

- 仍然需要本机先安装 `Node.js` 和 `npm`
- 如果你是通过源码仓库运行，启动器会直接使用仓库里的 `apps/web`
- 如果你是通过安装包运行，启动器会自动准备一份可运行的前端目录

### 3. 打开页面

- 前端：`http://127.0.0.1:3000`
- 后端文档：`http://127.0.0.1:8000/docs`

## 公共仓库同步

项目现在支持把“可公开、可迁移”的文件同步到单独的 GitHub 仓库。

使用方式：

```bash
ifome sync-public --target /path/to/github-repo
```

如果目标目录已经是配置好远端的 Git 仓库，可以直接一条命令同步并推送：

```bash
ifome push-public --target /path/to/github-repo
```

如果你本机是通过 token 推送 GitHub，也可以显式指定：

```bash
ifome push-public --target /path/to/github-repo --github-token-file ~/GITHUB_TOKEN
```

同步规则来自：

- `public_sync_manifest.txt`

这意味着：

- 只有清单里列出的公共文件会被同步
- `.env.local`、本地 SQLite、个人面试材料、个人画像案例和本地测试数据不会被同步
- 如果清单里删掉了某个文件，下一次同步时目标目录里的旧副本也会被清理

明确不会上传的内容举例：

- `project_extract_ifome_resume.md`
- `interview_reference.md`
- `~/GITHUB_TOKEN` 这类 token 文件
- `data/runtime/workflows.sqlite3` 这类本地数据库

## 推荐使用顺序

### 第一步：先配置 memory

打开 `/memory`，先填：

- 目标岗位
- 优先方向
- 技能
- 地点偏好
- 今日重点
- 当前优先事项

原因：

- 后面的匹配、排序、聊天都会用这些信息

### 第二步：录入求职信息

打开 `/ingest`，现在只需要一个统一输入框，可以提交：

- 一段文本
- 一个或多个链接
- 一张图片
- 一个 PDF 或文本文件
- 一行本地图片 / 文件路径

适合录入的内容包括：

- 岗位 JD
- 面试通知
- 结果消息
- 行情资讯
- 招聘截图

### 第三步：查看条目结果

打开 `/items`，查看：

- 卡片摘要
- 公司 / 岗位 / 地点
- DDL
- 优先级

### 第四步：继续追问

打开 `/chat`，可以提问：

- 今天该投什么
- 这段 JD 和我匹配吗
- 这个岗位面试可能问什么

当前 chat 已经是 grounded chat：

- 会检索历史条目
- 会检索长期画像
- 会检索项目经历
- 会检索动态求职状态
- 会返回引用来源
- 会先做 Query Rewrite、多路检索扩词和 Prompt 拼装
- 上传简历或项目说明时会先总结文件主要内容，再把结果写入画像
- 可切换到“模拟 Boss 回复”模式，把对方消息渲染成对话框并一键复制建议回复
- Boss 回复模拟会缓存最近多轮对话，上下文会自动带入下一轮生成；建议回复和回复策略会分开展示，复制按钮只复制回复正文
- Boss 回复模拟会把每一轮保存成可展开的历史列表；你可以删除单轮记录，也可以在每轮下面输入“评价 / 调整提示词”后重生成这一轮回复
- 如果之前已经上传过简历，可以直接在聊天框输入“请用简历更新项目画像”，系统会拿当前保存的简历快照重新整理项目卡片
- 聊天控制台支持多会话缓存：可以创建新对话、返回历史继续聊，关闭页面后仍会保留每个会话的输入草稿和输出结果
- 非当前会话会额外生成压缩摘要，列表优先展示摘要和关键词，减少重启后的恢复成本

## 当前主要页面

### `/ingest`

作用：

- 录入新信息

当前支持：

- 文本
- 链接
- 图片文件
- PDF / 文本文件
- 单独占一行的本地路径

补充说明：

- 输入产生的原始文本、上传图片、上传文件和本地路径副本会统一归档到 `data/runtime/source_files/`
- 直接输入的文本会存成 `.txt`
- 卡片列表和详情页会提供“访问源文件”入口

### `/items`

作用：

- 查看所有处理后的条目卡片

### `/memory`

作用：

- 编辑长期画像和当前求职状态
- 查看聊天上传后自动整理的项目画像与简历资料
- 直接打开已归档的简历或项目源文件
- 把简历原文和最近回写结果作为可展开的小卡片查看

### `/settings`

作用：

- 配置通用推理 LLM
- 配置独立 OCR LLM（Qwen-VL-OCR）
- 与长期 memory 隔离保存本地运行时设置

### `/chat`

作用：

- 在统一输入框里兼容提问、上传简历、上传项目说明、上传聊天截图
- 输出 grounded 回答
- 保守更新长期画像和动态状态
- 模拟 Boss / HR 沟通回复
- 支持在 Boss 模式单独输入“回答提示 / 回复要求”
- 支持对历史某一轮回复追加评价提示并重生成

- 基于已有条目和 memory 继续追问

会显示：

- 回答
- supporting item ids
- citations
- retrieval mode

## 主要 API

### 常规输入

- `POST /ingest/text`
- `POST /ingest/link`
- `POST /ingest/image-file`

### 条目与提醒

- `GET /items`
- `GET /items/{id}`
- `GET /reminders`

### memory

- `POST /memory/profile`
- `POST /memory/career-state`

### chat

- `POST /chat/query`

### Boss 直聘最小接入

- `POST /integrations/boss-zhipin/job`
- `POST /integrations/boss-zhipin/conversation`

## 数据存储位置

当前默认本地存储：

- `data/runtime/workflows.sqlite3`
- `data/runtime/memory.sqlite3`
- `data/runtime/reminders.sqlite3`

这意味着：

- 重启服务后，条目不会丢
- memory 不会丢
- reminder 不会丢

## 当前系统边界

当前已经够做第一轮使用和展示，但还不是生产版。

需要知道的边界有：

- OCR 对中文截图的效果还有限
- Boss 直聘还只是最小 payload 接入，不是真实自动抓取
- rerank 还是 heuristic
- chat 已经接入 RAG，但知识源还主要是当前条目和 memory

## 最推荐的一条演示链路

如果你要自己验证或者对外演示，建议按这个顺序：

1. 在 `/memory` 先填画像
2. 在 `/ingest` 输入一条岗位文本
3. 在 `/items` 看卡片和优先级
4. 在 `/chat` 问“这段 JD 和我匹配吗”
5. 再问“今天该投什么”
6. 展示 citations 和 `retrieval_mode`

## 与 GitHub 仓库的边界

如果你之后把项目公开到 GitHub：

- 这份文档可以直接公开
- `.env.local` 不应该公开
- 真实 key 不应该出现在文档、截图、日志里
