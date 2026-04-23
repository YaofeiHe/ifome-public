# Account Setup

这份文档是公开仓库版本的账号与配置说明，只保留：

- 需要准备哪些账号
- 应该拿到哪些配置项
- 本地应该放到哪里

不会保留任何真实 key、个人账号信息或本地机器路径。

## 使用原则

对于这个仓库，统一采用下面的规则：

- 真实 API Key 不写进文档
- 真实 API Key 不提交到 GitHub
- 真实 API Key 只放在本地环境变量或 `.env.local`
- 仓库里只保留 `.env.example` 和 `.env.local.example`

## 当前推荐技术路线

- 主模型：DashScope / Qwen
- 复杂推理升级：OpenAI，默认关闭
- Embedding：DashScope `text-embedding-v4`
- 向量数据库：Qdrant Cloud
- 可选备用：DeepSeek

## 需要准备的账号

### 必需

- 阿里云账号，开通 DashScope / 百炼
- Qdrant Cloud 账号并创建 cluster

### 可选

- OpenAI Platform
- DeepSeek Platform

说明：

- 当前项目已经可以不启用 OpenAI
- 如果你只做当前原型验证，DashScope + Qdrant 就足够

## 必需配置项

当前最小可用配置：

- `DASHSCOPE_API_KEY`
- `QDRANT_URL`
- `QDRANT_API_KEY`

推荐一起配置：

- `ENABLE_LIVE_LLM=true`
- `ENABLE_LIVE_RAG=true`
- `ENABLE_OPENAI_ROUTING=false`
- `DASHSCOPE_CHAT_MODEL=qwen-plus`
- `DASHSCOPE_EMBEDDING_MODEL=text-embedding-v4`
- `QDRANT_COLLECTION=ifome_rag`

## 本地配置位置

推荐方式：

1. 复制模板文件
2. 把真实值写进本地 `.env.local`
3. 不要把 `.env.local` 提交到仓库

项目里已经提供：

- `.env.example`
- `.env.local.example`

推荐做法：

```bash
cp .env.local.example .env.local
```

然后只在本地补真实值。

## 各平台官网入口

### DashScope / 百炼

- API Key 文档：
  `https://help.aliyun.com/zh/model-studio/get-api-key`
- 文本生成文档：
  `https://help.aliyun.com/zh/model-studio/text-generation`
- Embedding 文档：
  `https://help.aliyun.com/zh/model-studio/embedding`

你最终需要：

- `DASHSCOPE_API_KEY`

### Qdrant Cloud

- Cloud 入口：
  `https://cloud.qdrant.io/`
- Cloud account setup：
  `https://qdrant.tech/documentation/cloud-account-setup/`
- Authentication：
  `https://qdrant.tech/documentation/cloud/authentication/`

你最终需要：

- `QDRANT_URL`
- `QDRANT_API_KEY`

### OpenAI，可选

- API key：
  `https://help.openai.com/en/articles/4936850-how-to-create-and-use-an-api-key`
- Quickstart：
  `https://platform.openai.com/docs/quickstart/step-2-set-up-your-api-key`

你最终需要：

- `OPENAI_API_KEY`

### DeepSeek，可选

- API 文档：
  `https://api-docs.deepseek.com/`

你最终需要：

- `DEEPSEEK_API_KEY`

## GitHub 上传前检查

在仓库上传 GitHub 前，至少检查下面这些点：

1. `.env.local` 没有被提交
2. 文档里没有真实 key
3. 文档里没有个人绝对路径
4. 截图、测试数据、日志里没有敏感信息
5. API 示例里只使用占位符，不使用真实值

## 当前建议

如果接下来继续开发或演示，建议只把这些文件当成公开文档入口：

- `README.md`
- `docs/next_execution_plan.md`
- `docs/user_guide.md`
- `docs/interview_guide.md`

真实配置始终留在你的本地环境中，不进入仓库文档。
