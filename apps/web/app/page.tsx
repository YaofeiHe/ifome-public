import Link from "next/link";

const pages = [
  {
    href: "/ingest",
    title: "输入页",
    description: "上传文本、链接和截图 OCR，并立即送进工作流。",
  },
  {
    href: "/items",
    title: "卡片列表页",
    description: "查看摘要、岗位、地点、DDL 和优先级，并做基础筛选。",
  },
  {
    href: "/memory",
    title: "记忆管理页",
    description: "拆开管理长期画像和动态求职状态，避免一团黑盒上下文。",
  },
  {
    href: "/chat",
    title: "聊天控制台页",
    description: "基于已处理数据继续追问，而不是脱离上下文的闲聊。",
  },
];

const phases = [
  "统一接收文本、链接、截图 OCR 等原始输入",
  "normalize 后转成可追溯的 NormalizedItem",
  "classify 决定岗位、通知、资讯等处理分支",
  "extract / score / reminder_plan 生成卡片与提醒池",
];

export default function HomePage() {
  return (
    <main className="dashboard-grid">
      <section className="hero panel panel-hero">
        <p className="eyebrow">ifome / Job Information Flow Agent</p>
        <h1>最小前端骨架已经接入真实 API 形态</h1>
        <p className="intro">
          当前页面不再只是占位说明，而是作为四个工作台的导航入口。后续前端增强仍将严格收敛到文档里的单 Agent 工作流设计。
        </p>
      </section>

      <section className="panel">
        <h2>主链路</h2>
        <ol className="phase-list">
          {phases.map((phase) => (
            <li key={phase}>{phase}</li>
          ))}
        </ol>
      </section>

      <section className="workspace-grid">
        {pages.map((page) => (
          <Link key={page.href} href={page.href} className="workspace-card">
            <p className="workspace-kicker">Workspace</p>
            <h2>{page.title}</h2>
            <p>{page.description}</p>
          </Link>
        ))}
      </section>
    </main>
  );
}
