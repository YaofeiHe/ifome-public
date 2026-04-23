# Next Execution Plan

这份文档现在是项目的总执行文档，统一承担三件事：

1. 记录项目已经完成了哪些阶段。
2. 记录每个阶段的执行细节、验证结果和当前边界。
3. 给出后续继续推进的计划，尤其是 `Phase 15` 之后怎么收尾、怎么上 GitHub、怎么继续迭代。

从现在开始，阶段性说明以这份文档为主。`phase10_*` 到 `phase14_*` 这些文件保留为归档入口，但不再作为主文档继续扩写。

## 文档同步约定

从现在开始，项目默认执行下面这条工程约束：

- 只要代码能力、接口、页面、数据结构或架构边界发生变化，就必须同步更新 `docs/`
- 如果改动会影响项目讲述方式或演示路径，也必须同步更新面试相关文档
- 面试相关文档当前至少包括：
  - `docs/interview_guide.md`
  - `interview_reference.md`
  - `docs/demo_script.md`
  - `docs/repo_structure.md`

这条约束的目的不是“补文档”，而是保证三件事始终一致：

- 实际代码能力
- 仓库内说明文档
- 面试时的项目讲述口径

另外，针对站点抓取器和市场刷新这类高不确定性改动，执行顺序固定为：

- 先写独立小脚本或最小适配器做真实站点验证
- 再根据测试结果决定是否接回主流程
- 不允许跳过“小脚本先验证”直接改主链路

## 公开仓库原则

这个项目后续会上传到 GitHub，所以文档和仓库内容默认按“可公开”标准维护。

必须遵守：

- 不在任何文档里保存真实 API Key、token、cookie、账号密码。
- 不在文档里写个人机器绝对路径、个人账号信息、私有链接。
- 真实配置只放本地环境变量或本地忽略文件里。
- 仓库内只保留：
  - `.env.example`
  - `.env.local.example`
  - 文档中的占位符写法

当前项目的敏感信息边界是：

- `docs/account_setup.md`：只保留公开配置方式和占位符
- `.env.local`：只作为本地私有配置，不上传 GitHub
- 所有面向 GitHub 的文档都默认不包含你的个人信息

为了让本地项目和 GitHub 公共版本稳定同步，这轮又补了两项固定机制：

- `public_sync_manifest.txt`
  - 作为唯一公共文件白名单
  - 只有它列出的文件允许同步到公开仓库
- `ifome sync-public --target <目录>`
  - 按白名单同步公共文件
  - 同步时会记录上一次输出结果，并清理已经不再允许同步的旧文件
- `ifome push-public --target <目录>`
  - 在同步之后自动完成 `git add / commit / push`
  - 前提是目标目录本身已经是绑定好远端的 Git 仓库
  - 如果本机有 `GH_TOKEN`、`GITHUB_TOKEN_FILE` 或 `~/GITHUB_TOKEN`，脚本会优先用 token 完成 HTTPS 推送
- 同步状态文件 `.ifome_public_sync_state.json` 只用于本地增量同步，不进入 GitHub 版本控制

明确不允许进入 GitHub 公共版本的内容包括：

- 私人化面试准备文档
  - 例如 `project_extract_ifome_resume.md`
  - 例如 `interview_reference.md`
- 本地私有配置
  - 例如 `.env.local`
  - 例如 `~/GITHUB_TOKEN`
- 本地运行数据和用户画像样例
  - 例如 `data/runtime/*.sqlite3`
  - 例如仅用于你个人测试的 API、memory、案例数据

这样以后本地继续开发时，同步 GitHub 不再靠手动判断“哪些能传、哪些不能传”，而是靠清单驱动。

## 最新补充：统一启动入口与 pip 安装

这轮开始为上传 GitHub 和后续复用做打包收口：

- `pyproject.toml` 新增了 console script：
  - `ifome`
- 默认运行 `ifome` 就会等价于 `ifome start`
- 启动器会：
  - 同时拉起 FastAPI 后端和 Next.js 前端
  - 在当前终端持续输出前后端日志
  - 自动打开浏览器
  - 当前端依赖不存在时先执行一次 `npm install`

同时补了两个兼容点：

- 如果当前是在源码仓库里运行，统一启动器优先使用仓库中的 `apps/web`
- 如果当前是通过安装包运行，启动器会从安装包资源中准备一份可运行的前端目录再启动

为了支持安装场景读取本地配置，环境加载也新增了：

- `IFOME_PROJECT_ROOT`
  - 启动器会自动设置它
  - `core/runtime/env.py` 会优先从这个目录加载 `.env.local` / `.env`

这意味着当前项目已经满足：

- `pip install -e .`
- `ifome`

这一套更接近真实可交付项目的安装体验，而不是只停留在“开发者手动开两个终端”。

## 最新补充：public 展示仓库包装

这轮又继续往前收口了一层，不只是“能同步到 GitHub”，而是把公共版本整理成更像展示仓库的形态：

- 主开发仓库继续 private
- public 版本承担：
  - 项目目标说明
  - 系统架构
  - 技术栈
  - 当前完成度
  - 下一步计划
  - 接口说明、模块说明、测试说明
  - 可直接嵌入 README 的可视化示意图

新增内容包括：

- `docs/assets/system-architecture.png`
- `docs/assets/home-workbench.png`
- `docs/assets/job-cards.png`
- `docs/assets/market-cards.png`
- `docs/public_showcase.md`

README 现在已经被改造成更接近 public showcase 首页的风格，而不只是开发者自用说明。
这次又额外收口了一条展示规则：

- public 仓库 README 中的可视化部分只使用目录里真实存在的截图
- 不再额外补充与实际界面无关的示意图

当前仓库路径关系也固定下来：

- 本地主开发目录：
  - `/Users/makinohara_shoko/Downloads/master_save/informe/ifome`
- private 仓库本地镜像：
  - `/tmp/ifome-private-repo`
- public 展示仓库本地镜像：
  - `/tmp/ifome-public-repo`
- private 仓库远端：
  - `https://github.com/YaofeiHe/ifome`
- public 仓库远端：
  - `https://github.com/YaofeiHe/ifome-public`

## 当前阶段总览

截至当前版本，项目状态可以概括为：

- `Phase 1` 到 `Phase 14` 已完成
- 项目已经从“骨架 POC”推进到“本地可运行、可演示、可做第一轮可行性验证”的状态
- 后续核心逻辑脱离 LangGraph、迁移到自定义 runtime 的计划保留在未来规划中
- 在第一次验证之后，再推进 runtime 替换更合适

一句话总结当前项目：

- 它已经是一个可用的求职信息流工具原型
- 不是最终生产版
- 但已经足够用于第一轮验证、项目展示和面试讲解

## 最新补充：卡片检索、统一输入与卡片管理收口

本轮针对真实使用里暴露出来的三个核心问题，新增了下面几项收口能力：

- 聊天检索不再只依赖“成功渲染出来的卡片”
- 聊天入口会先分析问题，再结合卡片类型、时间窗口、关键词与近期性做混合检索
- Qdrant 继续承担向量索引，但真正的 RAG 逻辑放在项目内部的检索编排层
- 统一输入页把“文本 + 链接”收敛成一个输入框，后端负责识别纯文本、纯链接和混合输入
- 检测到链接后，会结合上下文决定是否访问链接，并尝试把一个链接里的多条岗位拆成多张卡片
- 对于“岗位合集”类长文本，会先拆成多个业务线 section，再按 section 判断是否访问对应链接
- 一个业务线 section 内如果显式列出了多个岗位方向，会进一步拆成多张岗位卡片
- 卡片列表支持手动编辑和删除
- 卡片列表支持批量选取删除
- 卡片支持左键点击查看详细信息，包括原始内容、标准化文本、来源 metadata、证据和提醒任务
- 新卡片入库时会先做相似度判断：核心信息相同则合并，同岗位更新则覆盖旧卡片

对应这轮 API / 页面补充包括：

- `POST /items/batch-delete`
- `/items` 页面支持单选、多选、全选当前筛选结果、批量删除

这里的 RAG 取舍结论也顺便固定一下：

- 需要“自己的 RAG 系统”，但它不是再造一个新的向量数据库
- Qdrant 负责存向量和召回
- 项目内部负责 query analysis、时间窗过滤、卡片类型过滤、rerank、citation 组织，以及把 profile / career-state / 卡片上下文一起交给 LLM
- 也就是说，正确结构是“Qdrant + 应用层 RAG 编排”，而不是“只接一个向量库就算完成 RAG”

## 最新补充：阿里系多岗位输入修正

这轮又收到了一个更贴近真实使用的问题：输入页里已经生成了很多候选卡片，但最后卡片列表只保存了一张，说明问题不在“拆卡”，而在“抽取污染 + 去重误判”。

这次的修正点是：

- 先把整段输入拆成两层：
  - `shared_context`：如阿里系、暑期实习、剩余笔试日期这类共享信息
  - `section / role_variant`：如阿里云、淘宝闪购、菜鸟，以及每个业务线下的具体岗位方向
- 共享上下文不再直接混进每张岗位卡的抽取正文里，避免把不同业务线污染成相同 company / role
- 每张卡在访问链接前都会先生成 `fetch_plan`，明确本次访问要补什么：
  - 岗位名称与业务线
  - 岗位职责与要求
  - 投递方式与截止时间
  - 地点或线上信息
  - 笔试 / 面试 / 测评提示
- 抓到网页文本后，不是直接覆盖原文，而是只抽当前 card candidate 最相关的片段再回写工作流
- 卡片去重从“链接 / 公司 / 岗位相同就很像”升级成“岗位身份键”判断，优先看：
  - `source_title`
  - `role_variant`
  - 业务线关系标签，如 `阿里系-暑期实习-淘宝闪购`
- 如果是同一个招聘站里的不同岗位方向，就不会再被误合并成一张卡
- 如果当前文本没有明确地点，但语义上需要“投递后确认”或“可能线上”，卡片会显式展示地点待识别说明
- 共享笔试日期会进入 metadata，并在岗位卡本身没有明确 DDL 时回填到 `ddl`

这轮修正之后，阿里系这类“多链接 + 多业务线 + 多岗位方向 + 共享考试信息”的输入，系统内部流程已经变成：

1. submission analysis
2. split shared context / sections
3. expand role variants
4. build fetch plan per candidate
5. visit selected links
6. extract candidate-specific snippets
7. normalize / extract with isolated card context
8. identity-aware dedupe
9. render relation-aware cards

面试里可以把这轮问题直接讲成一个很好的工程案例：

- 不是“模型不够聪明”
- 而是“共享上下文和实体主语义不能混在同一抽取输入里”
- 同时“卡片去重不能只看链接和粗粒度字段，还要看业务身份键”

## 最新补充：平台无关关系识别与批量模型分析

这轮又继续往前收口了几个真实使用问题：

- 关系标签不再只对阿里系做特化规则
- 现在统一改成平台无关的关系识别：
  - `relationship_family`：如 `阿里系`、`字节系`，或者从共享上下文推断出的公司族标签
  - `relationship_stage`：如 `暑期实习`、`校招`、`秋招`
  - `primary_unit`：如 `淘宝闪购`、`阿里云`、`抖音电商`
  - `identity_tag`：例如 `字节系-暑期实习-抖音电商`
- 这意味着字节系、腾讯系、美团系、京东系以及其他公司文本，都会走同一套 section / variant / dedupe 规则，而不是继续按公司写补丁

同时新增了两项使用层能力：

- 卡片详情里的重要信息现在会显式展示原链接
- 卡片列表页新增“批量分析”操作，可以在批量删除旁边直接对已选卡片调用模型做进一步分析
- 卡片详情不再固定展开在页面底部，而是会在当前点击卡片附近弹出对话框，减少列表跳转感

这次批量分析的输入不是只靠摘要，而是会把卡片里已经存下来的这些内容一起带给模型：

- `raw_content`
- `normalized_text`
- `original_section_text`
- `shared_context`
- `source_ref`
- 结构化字段与关系标签

也就是说，卡片已经具备“拿原文做二次分析”的基础，而不是只能拿一行摘要继续问答。

另外，针对“阿里系剩余笔试日期没有真正落进卡片 DDL”的问题，这轮也固定了规则：

- 如果一段岗位合集输入在共享上下文里给出了统一笔试 / 投递剩余日期
- 那么这个 shared deadline 会在一开始就作为这一批岗位卡的 `global_deadline`
- 对于 `job_posting` 和 `referral` 类型卡片，渲染与提醒默认优先使用这个全局 DDL
- 如果链接页里还有岗位自己的截止时间，会额外记到 metadata 的 `job_specific_deadline`

这样卡片层面就能同时满足两件事：

- 列表里优先看到“这一批岗位共同需要尽快处理的时间”
- 详情里保留岗位页面自身的截止信息，不会丢证据

## 最新补充：上传接口标准化提示词库与搜索扩词前置

这轮继续解决了一个更细的输入问题：

- 有些合理的卡片不能只看一个 section 片段
- 它还必须带上共享规则片段，例如统一的笔试、投递和内推约束
- 但如果把共享上下文整段硬拼回去，又会重新污染抽取

这次的改法是：

- 在 `/ingest/auto` 前面新增了一层 intake standardize
- 这层会优先从 prompt 库读取 `prompts/intake_standardize.md`
- 如果 live LLM 可用，就先对“文本 / 链接上传接口”做一次标准化输出
- 标准化输出重点包括：
  - `input_kind`
  - `should_visit_links`
  - `shared_context_summary`
  - `seed_entities`
  - `relationship_family`
  - `relationship_stage`
  - `section_hints`

同时，真正切 section 之前又补了一步：

1. 先结合用户画像和当前求职状态识别 profile-guided theme
2. 做一次 one-shot web search 扩关键词
3. 得到 `keyword_hints`
4. 再用这些 hints 去做：
   - section relationship 识别
   - shared context 过滤
   - link fetched segment 相关性筛选

这里有一个重要约束这次也明确了：

- 不能靠维护一份“主题头库”来识别赛道
- 主题头只作为文本里的候选线索
- 真正决定要不要拿它做扩词，要结合 `profile_memory` 和 `career_state_memory`
- 例如用户画像里关注 `智能驾驶`，输入里出现 `#自动驾驶相关`
- 系统会基于画像重叠把它识别成值得扩词的赛道主题，再去搜索 `滴滴 / 地平线 / 蔚来` 这类公司关键词

这样之后，每张卡拿到的不是“全文硬拼接”，而是一份结构化的上下文包：

- `岗位标题`
- `关系标签`
- `关键词提示`

## 最新补充：机器之心小脚本探测结论

这轮先严格按“小脚本先验证，再改主流程”推进，没有直接修改市场刷新主链路。

新增：

- `scripts/probe_jiqizhixin_sources.py`

它的作用不是直接产出卡片，而是探测机器之心当前公开页面还能暴露哪些入口：

- 首页和 `/rss`、`/articles`、`/ai_shortlist` 当前返回的都更接近“数据服务”落地页
- `/rss` 页面仍然暴露出少量可见入口，例如：
  - `articles`
  - `short_urls/*`
  - `ai_shortlist`
- 可见 `short_url` 会重定向到 `sota.jiqizhixin.com`
- `sota` 前端脚本里还能挖到一批 `short_urls/*` 和 `/api/sota/*` 接口线索

这次真实测试进一步确认了两个关键边界：

- `short_urls/*` 直接访问后大多还是落回“数据服务”页，拿不到可用的文章标题和发布时间
- `sota` 的确有公开 API 能访问，但目前验证到的 `issues/list` 是旧问答流，时间停留在 `2022-07-22`，不能当作“近 24 小时文章标题”

当前结论：

- 机器之心还不能像量子位那样，直接接成“站点级近 24 小时标题抓取”
- 但已经定位出下一步最值得继续试的方向：继续挖 `sota.jiqizhixin.com` 的公开 API，而不是再抠首页 HTML
- 在没有验证出“近 24 小时标题”入口前，不把这个未证实能力接回主流程

后续又继续推进了一步，并且这次真正找到了可用的“文章库”入口：

- `rss` / 数据服务页里的 `文章库` 只是导航入口
- 真正的标题列表来自前端包里暴露的 API：
  - `https://www.jiqizhixin.com/api/article_library/articles.json?sort=time&page=1&per=24`
- 这条接口可以稳定返回：
  - `title`
  - `slug`
  - `publishedAt`
  - `content` 摘要

现在主流程已经按量子位类似的方式接回来了：

- `recent_site_titles.py` 对机器之心优先走 `article_library` API
- 只保留近 24 小时内的标题列表
- 结果会作为正式的 `site_recent_titles:jiqizhixin_article_library_api` 候选进入市场刷新链路
- 如果文章详情页匿名抓取失败，就回退使用标题列表 API 自带的 `content` 摘要先生成市场子卡，而不是整条丢掉
- 如果这条 API 后续不可用，才继续回退到原来的机器之心搜索适配器

2026-04-23 的真实小脚本结果已经变成：

- `python ifome/scripts/market_watch_recent_titles.py https://www.jiqizhixin.com/ --limit 10 --pretty`
- 返回 `count = 9`
- 说明机器之心现在已经能站点级导出近 24 小时文章标题列表

同时保留一个明确边界：

- 文章详情页 `https://www.jiqizhixin.com/articles/<slug>` 匿名访问时仍可能回到“数据服务”页
- 所以机器之心当前是“列表层稳定可抓，详情层部分受限”
- 已经通过“列表摘要回退落卡”规避这层限制
- `共享规则`
- `当前岗位片段`
- `链接解析结果`

这条链路的目标是同时解决两个冲突：

- 不能把共享规则丢掉，否则卡片会失去统一的笔试 / 投递语义
- 也不能把共享规则生硬混进全文，否则会把 company / role / dedupe 再次污染

这轮又额外补了一种真实输入：

- 不是所有招聘信息都会天然带编号 section
- 像“滴滴 2026 届春季校招正式启动”这种长公告，本质上也是一张有效卡片
- 现在如果输入没有显式 section，但文本本身明显是完整的招聘公告，系统会先生成一个 `campaign card candidate`
- 这个 candidate 会优先推断：
  - 公司名，例如 `滴滴`
  - 招聘批次，例如 `2026届春季校招`
- bare domain，例如 `campus.didiglobal.com`，会提升成可用 `source_ref`
- 这样它不会再退回成 `统一输入卡片`

这轮还补了一条很重要的链接处理约束：

- 当输入是纯链接，或者只有很少的说明文字加一个链接时，系统不能偷懒直接按短文本分析
- 这类输入现在会主动先访问链接、抓取正文，再把抓到的文本送回既有的 section / campaign / 画像驱动分析链路
- 也就是说，“链接正文抓取”现在是这类输入的前置步骤，不再是可有可无的补充步骤
- 如果抓到的是站点验证页，而不是真正文，系统会把它识别成访问拦截，而不是把“环境异常 / 去验证”这类页面当成岗位内容继续生成脏卡片

这轮同时把“显式搜索”和“市场信息”也串起来了：

- 如果用户在输入框里明确写了“请在网页上搜索有关内容”这类指令
- 后端现在会真的执行一次 web search
- 搜出来的结果不会直接替代正文，而是作为 `搜索参考` 附加到后续分析链路
- 这样它会影响后续分类、抽取和总结，但不会无边界地覆盖原始输入

卡片列表也调整成了双区结构：

- `求职活动`
  - 放宣讲会、双选会、面试、笔试、投递、内推、岗位等内容
  - 默认按最近 DDL / 时间从近到远排序
- `市场信息`
  - 放就业市场信息、行业动态、方向信号和画像相关的 AI 评分
  - 默认按 `ai_score` 从高到低排序
  - 每张市场卡会额外显示：
    - 简要总结
    - 给用户的建议
    - 与画像相关的市场关键词

这部分 UI 后来又继续收口成了“切换式视图”：

- 列表页不再同时铺开两组卡片
- 顶部通过点击按钮切换 `求职活动` / `市场信息`
- 求职活动卡片继续强调：
  - DDL / 活动时间
  - 地点
  - 生成时间
- 市场卡片则改成更适合信息研判的布局：
  - 消息时间
  - 生成时间
  - 简要总结
  - 建议
  - 结合时间和用户画像的评分

市场信息新增了一条独立刷新链路：

- Items 页支持“更新今日市场信息”
- 也支持输入一个链接，单独生成市场信息卡
- 长期记忆里新增 `market_watch_sources`
- 系统默认每天强制检查两个时间点：`10:00` 和 `21:00`
- 前端每 `15` 分钟触发一次检查
- 如果发现“上一次成功刷新”落在最近一个强制更新时间之前，就会在当前时间点补一次刷新
- 对市场信息，后端会优先用 `market_watch_summarize` prompt 生成：
  - summary
  - advice
  - keywords

另外，这轮也把 prompt 资产层固定成新的工程约束：

- 只要 `/ingest/auto` 的文本 / 链接标准化逻辑变化，就同步修改 `prompts/intake_standardize.md`
- 模型运行优先从 prompt 库读取入口标准化 prompt，而不是把 prompt 写死在 service 里

市场信息链路这轮又继续往前推进了一步：

- `market_watch_sources` 现在明确对应“市场监控源基础网址”，默认值改成：
  - `https://www.jiqizhixin.com/`
  - `https://www.qbitai.com/`
  - `https://36kr.com/information/web_news/`
- 记忆管理页不再用一个大文本框维护这些源，而是改成可上下滚动、可手动增删的表格
- 定时刷新不再直接抓基础网址首页，而是会先按站点做一次“近 24 小时标题/链接候选”搜索，再抓文章正文
- 网页抓取器会尽量提取文章来源发布时间，并把它作为卡片 `消息时间`
- 求职活动卡片和市场卡片现在都会展示 `消息时间 + 生成时间`
- 市场卡片的 `ai_score` 不再只依赖原有总分，而是结合：
  - 画像相关性
  - 关键词重叠
  - 信息新鲜度
- 市场来源刷新现在改成“两级筛选”：
  - 第一级先导出标题列表，只基于标题/摘要做关键词规则排序和总结
  - 标题层不再默认依赖 LLM 复排，而是优先走“画像关键词 + 拆分词 + 市场价值词”的组合匹配
  - 在高相关标题之外，额外保留 1 篇“市场价值较高但和当前方向有一定距离”的探索文章
  - 第二级再按记忆管理里的“市场文章抓取上限”抓正文，再逐篇转成市场文章卡片
- 固定来源现在会生成一张“大卡片”：
  - 大标题固定成 `网站域名 + 更新`
  - 摘要单独展示为关键词总结
  - 大卡片上会直接显示 `展开文章列表（N）` 按钮，点击后就在当前大卡片正下方弹出对应的小卡片列表
  - 再把按上限抓取到的文章小卡片挂在大卡片下面
  - 大卡片分数取“标题总览分”和“小卡片平均分”的平均值，而不是直接求和
- 记忆管理页现在新增了 `市场文章抓取上限` 输入框，用来控制每个市场来源在一次刷新里最多抓取多少篇文章正文
- 前端市场信息区现在额外放了一个更明确的按钮：
  - 之前曾出现 `手动启用每日关注网站更新` 和 `更新今日市场信息` 两个语义重复的按钮
  - 现在已经收敛成一个按钮：`更新每日关注网站`
- 前端批量删除现在会先把已选大卡片关联的小卡片 id 一起展开，再发起删除并强制刷新列表
- 市场信息区的批量工具栏现在也会直接显示 `删除已选 N 项`
- 市场刷新链路现在额外支持一个回退策略：
  - 如果标题搜索拿不到文章列表
  - 就直接回退到来源站点首页抓取和分析
  - 这样不会再只返回“本次市场刷新未获取到可用正文”
- 当前这条链路的边界也更明确了：
  - `search_client` 现在拿到的是搜索结果里的标题和链接候选
  - 还不能保证等价于“抓到某个网站过去 24 小时的全部文章标题”
  - 如果后面要做到真正完整覆盖，需要再补专门的站点级标题抓取器或 RSS/站内接口适配
- 这轮还额外补了一个实验性脚本：
  - `scripts/market_watch_recent_titles.py`
  - 底层使用 `core/tools/recent_site_titles.py`
  - 先按 `JSON-LD/listing pages -> feed -> sitemap -> homepage links` 的顺序尝试直接从站点本身抓“近 24 小时标题 + 链接”
  - 本地单测已经覆盖 feed 路径、homepage fallback 路径和 JSON-LD 列表页路径
- 真实站点二轮测试结果：
    - `qbitai.com`：可直接抓到近 24 小时 `13` 篇文章标题和链接，主要来自 homepage article links
    - `jiqizhixin.com`：仍然返回 `0`，当前首页 / `/rss` / `/articles` 都更像数据服务页，不是公开资讯流入口
    - `36kr.com/information/web_news/`：仍然返回 `0`，主要卡在验证码 / 反爬链路
- 这轮又把站点级抓取正式接回了市场刷新主链路：
  - `qbitai.com` 现在优先走站点级近 24 小时标题抓取，再进入关键词筛选和正文抓取
  - `jiqizhixin.com` 现在新增了专用搜索适配器，不再只依赖通用 `site:` 查询
  - 市场文章子卡 metadata 会记录 `market_candidate_source`，区分是 `site_recent_titles:*` 还是 `search_adapter:*`
- 这轮继续做了两处收口：
  - 已把 `36kr.com/information/web_news/` 从默认市场关注源和当前运行时记忆里移除
  - `jiqizhixin.com` 的站点级标题抓取又加了一层“首页当前可见站内链接探测”
- 当前最新真实结果：
  - `jiqizhixin.com` 的“首页可见链接适配”单测已通过
  - 但在真实站点上仍然返回 `0`，说明首页当前实际暴露出来的可用链接还不足以形成近 24 小时标题列表
- 列表展示时间现在统一成：
  - `YYYY年MM月DD日 HH:MM:SS`
  - 不显示时区
  - 使用前端系统时间格式化显示
- 每次市场刷新后还会检查历史卡片：
  - 同一文章来源的重复卡片只保留一张
  - 过旧且低分的市场历史会被清理
- 列表展示层和持久化层都会尽量避免市场信息重复堆积

## 阶段执行记录

### Phase 1：项目骨架初始化

目标：

- 固定目录结构
- 放入权威文档
- 提供最小 API / Web 入口

已完成：

- 固定了 `apps/`、`core/`、`integrations/`、`prompts/`、`tests/`、`docs/`、`data/`
- 建立了最小 `FastAPI` 入口
- 建立了最小 Next.js 前端占位页
- 建立了 runtime 抽象边界

结果：

- 项目不再是散文件，而是可继续生长的工程骨架

### Phase 2：核心 schema 定义

目标：

- 把输入、抽取、memory、reminder、agent state 全部显式建模

已完成：

- `NormalizedItem`
- `ExtractedJobSignal`
- `ProfileMemory`
- `CareerStateMemory`
- `ReminderTask`
- `AgentState`

结果：

- 节点之间交换的是显式对象，而不是随手拼接的 dict

### Phase 3：最小工作流闭环

目标：

- 先打通最小主链路

已完成：

- `ingest -> normalize -> classify -> extract -> match_profile -> score -> reminder_plan -> persist -> render`
- LangGraph 兼容工作流
- 顺序 fallback

结果：

- 主链路已经闭环
- 即使本地没有 LangGraph 运行环境，也能顺序执行

### Phase 4：基础 API

目标：

- 把工作流能力暴露成可调的 HTTP 接口

已完成：

- `POST /ingest/text`
- `POST /ingest/link`
- `POST /ingest/image`
- `GET /items`
- `GET /items/{id}`
- `GET /reminders`
- `POST /memory/profile`
- `POST /memory/career-state`
- `POST /chat/query`

结果：

- API 层可以驱动整个最小系统

### Phase 5：最小前端

目标：

- 做出最小可演示界面

已完成：

- `/ingest`
- `/items`
- `/memory`
- `/chat`

结果：

- 项目已经不是只靠命令行和 curl 演示

### Phase 6：Reminder Queue

目标：

- 让提醒从“概念”变成“真正有持久化队列”

已完成：

- `ReminderQueue`
- `SQLiteReminderRepository`
- 邮件 / 日历 / Web Push adapter 预留

结果：

- 提醒任务已经能持久化保存

### Phase 7：实验模块隔离

目标：

- 让实验能力可开关、可删、可独立演示

已完成：

- `ENABLE_PROJECT_SELF_MEMORY`
- `POST /experimental/project-self-memory`
- `GET /experimental/flags`

结果：

- 实验功能不污染主工作流

### Phase 8：测试与基础讲解文档

目标：

- 给项目补最小测试闭环和面试材料

已完成：

- schema 测试
- reminder 测试
- memory 测试
- workflow 测试
- demo / interview 文档初稿

结果：

- 项目不再是纯手工验证

### Phase 9：本地真实运行验证

目标：

- 真正把前后端跑起来

已完成：

- Python 依赖安装
- 前端依赖安装
- FastAPI 启动
- Next.js 启动
- `text -> workflow -> items -> reminders` 联调

结果：

- 本地运行验证通过
- 项目从“代码存在”进入“真实可运行”

### Phase 10：Live LLM 替换第一批 mock

目标：

- 用 DashScope / Qwen 接管 `classify` 与 `extract`

已完成：

- `classify` 支持 live LLM + fallback
- `extract` 支持 live LLM + fallback
- DashScope 候选模型链
- OpenAI 路由默认关闭
- prompt 调优

验证结论：

- 岗位 JD：live 明显优于 fallback
- 面试通知：live 明显优于 fallback
- 行情/资讯：通过 prompt 调优后能稳定从误判中拉回
- 噪声消息：live 更自然，但不一定必须走 live

当前边界：

- `ranking` 仍主要是规则
- 还没覆盖更大的真实样本集

### Phase 11：真实输入接入

目标：

- 链接输入不再依赖手填文本
- 图片输入不再依赖手填 OCR 文本

已完成：

- 网页正文轻量抓取
- 页面标题和抓取元数据保留
- 图片上传接口
- 本地 OCR 接入
- 前端输入页联动更新

验证结果：

- `POST /ingest/link` 已能抓正文并完成 workflow
- `POST /ingest/image-file` 已能上传、OCR、进入 workflow

当前边界：

- 当前 OCR 更适合英文截图
- 中文 OCR 还需要语言包或云端增强
- 网页正文抽取还是轻量实现

### Phase 12：主数据持久化

目标：

- item / workflow state / memory 从内存迁到 SQLite

已完成：

- `workflow_repository -> workflows.sqlite3`
- `memory_provider -> memory.sqlite3`
- `reminder_queue -> reminders.sqlite3`
- 完整 `AgentState` 快照持久化
- profile / career state 持久化

验证结果：

- 重启后 item、memory、reminder 都能读回来

当前边界：

- 还没有正式迁移机制
- 还没有 item 去重、版本合并、事件表

### Phase 13：Boss 直聘最小连接器

目标：

- 先把 Boss 直聘岗位详情和 HR 对话纳入统一输入边界

已完成：

- `BossZhipinJobPayload`
- `BossZhipinConversationPayload`
- connector translator
- `POST /integrations/boss-zhipin/job`
- `POST /integrations/boss-zhipin/conversation`

验证结果：

- 岗位详情可以进入 workflow
- HR 对话可以进入 workflow
- metadata 会显式标记 `connector=boss_zhipin`

当前边界：

- 还没有真实登录态 / 自动抓取
- 还没有 conversation 的二级抽取 schema

### Phase 14：聊天控制台升级为 RAG

目标：

- 让 chat 从模板问答升级成 grounded chat

已完成：

- `core/chat/rag.py`
- DashScope embedding adapter
- Qdrant REST adapter
- local fallback retrieval
- live Qdrant retrieval
- `citations`
- `retrieval_mode`
- 前端聊天页引用展示

验证结果：

- 本地 fallback 路径通过
- live RAG 注入测试通过
- 真实 DashScope embedding + Qdrant 联调通过
- 最终真实结果：
  - `retrieval_mode=live_qdrant`
  - `citations_count=4`

当前边界：

- rerank 还是 heuristic
- 还没有把独立面经库 / 文档库接入检索
- 还没有 retrieval evaluation

## 当前系统你可以怎么用

用户当前已经可以：

1. 在 `/memory` 配置长期画像和动态求职状态
2. 在 `/ingest` 输入文本、链接、图片
3. 在 `/items` 查看卡片和状态结果
4. 在 `/chat` 做 grounded follow-up
5. 通过 API 接入 Boss 直聘岗位 / 对话 payload

默认本地存储位置：

- `data/runtime/workflows.sqlite3`
- `data/runtime/memory.sqlite3`
- `data/runtime/reminders.sqlite3`

## 当前仍未完成的增强项

这些不是当前阻塞项，但属于后续继续做会显著提升质量的方向：

- 中文 OCR 增强
- 网页正文抽取增强
- Boss 直聘真实自动化读取
- 分类后的二级抽取 schema
- reranker 接入
- retrieval evaluation / 回放测试
- item 去重与幂等
- 通知真正发送
- 基础鉴权

## Phase 15：面试展示收尾

目标：

- 把项目整理成一套能稳定讲、能稳定演示、能公开放到 GitHub 的作品

需要完成：

1. 准备一份稳定 demo 数据和固定演示链路
2. 把用户指南、执行总文档、面试参考文档整理成清晰阅读顺序
3. 明确哪些部分已经是真实服务，哪些部分仍然是 POC / heuristic
4. 明确未来规划，尤其是“验证后再迁自定义 runtime”
5. 明确公开仓库的敏感信息边界
6. 准备 GitHub 上传后的维护约定

本轮文档整理的收口方向就是 Phase 15 的一部分。

## 验证后的未来规划

第一次验证后，下一阶段最重要的规划不是继续堆更多杂项，而是两条主线：

### 1. 继续把输入和检索质量做实

- Boss 直聘真实接入
- 更强 OCR / 网页抽取
- retrieval 评测和 rerank

### 2. 验证后逐步脱离 LangGraph

注意：

- 当前还没有开始替换核心执行框架
- 这一点故意保留在未来规划中
- 原因是：现在项目已经完成第一轮可用性验证，下一步应该基于真实使用反馈再决定 runtime 替换节奏

所以未来的表达应该是：

- 目前：LangGraph 作为 POC 编排器
- 后续：在验证后逐步迁到自定义 runtime
- 目的：降低框架耦合、增强可解释性、掌握状态迁移和故障回放

## GitHub 维护约定

项目上传 GitHub 后，后续每次修改都应该同步维护仓库内容，至少包括：

1. 改代码时同步更新相关文档
2. 改接口时同步更新用户指南
3. 改架构边界时同步更新 `architecture.md` / 本文档 / 面试文档
4. 新增真实服务能力时同步写验证结果
5. 不把真实 key、个人账号、个人路径提交到仓库

推荐把这几份文档当成公开仓库的稳定入口：

- `README.md`
- `docs/next_execution_plan.md`
- `docs/user_guide.md`
- `docs/interview_guide.md`
- `docs/repo_structure.md`

## 推荐阅读顺序

如果是自己继续开发，建议按这个顺序看：

1. `README.md`
2. `docs/repo_structure.md`
3. `docs/next_execution_plan.md`
4. `docs/architecture.md`
5. `docs/readiness_gap.md`

如果是给用户或面试官看，建议按这个顺序看：

1. `README.md`
2. `docs/user_guide.md`
3. `docs/interview_guide.md`
4. `docs/next_execution_plan.md`
