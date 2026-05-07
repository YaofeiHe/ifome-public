# Boss 直聘 Read-Only MCP 接入

首期 Boss 接入只允许读取职位搜索信息，并把结果转成 ifome 现有的 `BossZhipinJobPayload` 后进入统一 ingest 链路。

## 环境

`boss-agent-cli` 不随 ifome 源码提交，也不会被同步到 GitHub 仓库。推荐使用 ifome 的可选安装命令：

```bash
ifome install-boss
```

这个命令会在当前 Python 环境里安装 `boss-agent-cli[mcp]`，并执行 `patchright install chromium` 准备 Boss 官方扫码登录和只读搜索所需的浏览器运行时。

源码安装时也可以选择可选依赖：

```bash
pip install "ifome-job-agent[boss]"
patchright install chromium
```

安装完成后，不需要为 ifome 设置 Boss 相关环境变量。ifome 会优先在当前 Python 环境和 `PATH` 中自动发现 `boss-mcp`。

当用户在输入页发起 Boss 搜索时，ifome 会先检查登录态；如果未登录或登录过期，会唤起 Boss 官方扫码登录。关闭 ifome 时，页眉关闭按钮和 `ifome stop` 都会触发 Boss 登录态清理。

## 只读白名单

ifome 只允许调用：

- `boss_status`
- `boss_search`
- `boss_detail`
- `boss_cities`

明确禁止：

- 聊天、发消息、打招呼、投递、交换联系方式
- 修改或导出本地简历
- 招聘者侧回复、索要简历、职位上下线
- 绕过验证码、安全检查或平台限制

## API

```text
POST /integrations/boss-zhipin/search-readonly
```

请求示例：

```json
{
  "query": "AI Agent",
  "city": "上海",
  "max_items": 5,
  "user_id": "demo_user",
  "workspace_id": "demo_workspace"
}
```

该接口会调用 `boss_search`，最多写入 `max_items` 条岗位卡，且强制使用 `context_only` 记忆写入模式。需要长期画像沉淀时，应由 ifome 的记忆写入门控单独判断。

## 自然语言输入

也可以直接在 ifome 输入页输入：

```text
请搜索boss直聘中有关关键词“AI 应用后端 / 智能体平台 / 开发者 AI / 数据与评测”的有关的内容
```

ifome 会把关键词拆成小批量只读搜索，默认每个关键词最多读取 2 条结果，并按“公司大卡片 + 岗位小卡片”的结构归档。
