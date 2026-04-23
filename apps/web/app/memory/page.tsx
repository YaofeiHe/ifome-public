"use client";

import { FormEvent, useState } from "react";

import { MemoryResponse, apiRequest } from "../lib/api";

function parseLines(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

const DEFAULT_MARKET_WATCH_SOURCES = [
  "https://www.jiqizhixin.com/",
  "https://www.qbitai.com/",
];

export default function MemoryPage() {
  const [targetRoles, setTargetRoles] = useState(
    "AI 应用工程师\n智能体平台工程师\nLLM 应用后端\nAI 搜索工程师\nRAG/知识库工程师",
  );
  const [priorityDomains, setPriorityDomains] = useState(
    "AI 大模型工程化\n企业级 agent 平台\n办公 agent\n编程 agent\nAI 搜索与信息助手\n本地生活与旅行 agent\n电商经营与客服 agent\n产业与医疗 agent\n智能驾驶",
  );
  const [skills, setSkills] = useState("Python\nFastAPI\nRAG\nAgent\nMCP\n评测\n工作流编排");
  const [locations, setLocations] = useState("上海\n杭州\n北京\n远程");
  const [softPreferences, setSoftPreferences] = useState(
    "高匹配岗位优先\n有明确 DDL 更好\n优先关注 AI agent 工程化相关岗位",
  );
  const [excludedCompanies, setExcludedCompanies] = useState("");
  const [summary, setSummary] = useState(
    "重点关注中国市场里 AI agent 工程化应用岗位，不局限于智能驾驶，同时覆盖企业级智能体平台、办公 agent、编程 agent、AI 搜索助手和电商 agent。",
  );

  const [watchedCompanies, setWatchedCompanies] = useState("阿里云\n钉钉\n夸克\n高德\n淘天");
  const [marketWatchSources, setMarketWatchSources] = useState(DEFAULT_MARKET_WATCH_SOURCES);
  const [marketArticleFetchLimit, setMarketArticleFetchLimit] = useState("5");
  const [todayFocus, setTodayFocus] = useState("筛选高匹配岗位\n跟进 AI agent 工程化方向的市场信号");
  const [activePriorities, setActivePriorities] = useState(
    "重要时间点不遗漏\n今天先投高匹配岗位\n持续更新市场信息",
  );
  const [notes, setNotes] = useState("当前优先关注 AI agent 工程化相关岗位与市场动态。");

  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [lastSnapshot, setLastSnapshot] = useState<MemoryResponse | null>(null);

  async function submitProfile(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setMessage(null);
    try {
      const response = await apiRequest<MemoryResponse>("/memory/profile", {
        method: "POST",
        body: JSON.stringify({
          target_roles: parseLines(targetRoles),
          priority_domains: parseLines(priorityDomains),
          skills: parseLines(skills),
          location_preferences: parseLines(locations),
          soft_preferences: parseLines(softPreferences),
          excluded_companies: parseLines(excludedCompanies),
          summary,
        }),
      });
      setLastSnapshot(response.data);
      setMessage("长期画像已更新。");
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "写入 profile memory 失败。",
      );
    } finally {
      setPending(false);
    }
  }

  async function submitCareerState(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setMessage(null);
    try {
      const response = await apiRequest<MemoryResponse>("/memory/career-state", {
        method: "POST",
        body: JSON.stringify({
          watched_companies: parseLines(watchedCompanies),
          market_watch_sources: marketWatchSources.map((item) => item.trim()).filter(Boolean),
          today_focus: parseLines(todayFocus),
          active_priorities: parseLines(activePriorities),
          notes,
          market_article_fetch_limit: Math.min(
            20,
            Math.max(1, Number.parseInt(marketArticleFetchLimit || "5", 10) || 5),
          ),
        }),
      });
      setLastSnapshot(response.data);
      setMessage("动态求职状态已更新。");
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "写入 career-state memory 失败。",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="dashboard-grid">
      <section className="hero panel panel-hero">
        <p className="eyebrow">Memory Control</p>
        <h1>把长期画像和当前状态拆开管理</h1>
        <p className="intro">
          这里对应两个不同接口：`/memory/profile` 和 `/memory/career-state`。前者存稳定偏好，后者存近期状态。
        </p>
      </section>

      {message ? <section className="panel success-banner">{message}</section> : null}
      {error ? <section className="panel error-banner">{error}</section> : null}

      <section className="memory-grid">
        <form className="panel stack-form" onSubmit={submitProfile}>
          <h2>长期画像</h2>
          <label className="field">
            <span>目标岗位</span>
            <textarea rows={5} value={targetRoles} onChange={(event) => setTargetRoles(event.target.value)} />
          </label>
          <label className="field">
            <span>重点方向</span>
            <textarea rows={4} value={priorityDomains} onChange={(event) => setPriorityDomains(event.target.value)} />
          </label>
          <label className="field">
            <span>技能标签</span>
            <textarea rows={4} value={skills} onChange={(event) => setSkills(event.target.value)} />
          </label>
          <label className="field">
            <span>地点偏好</span>
            <textarea rows={4} value={locations} onChange={(event) => setLocations(event.target.value)} />
          </label>
          <label className="field">
            <span>软偏好</span>
            <textarea rows={4} value={softPreferences} onChange={(event) => setSoftPreferences(event.target.value)} />
          </label>
          <label className="field">
            <span>排除公司</span>
            <textarea rows={3} value={excludedCompanies} onChange={(event) => setExcludedCompanies(event.target.value)} />
          </label>
          <label className="field">
            <span>摘要</span>
            <textarea rows={4} value={summary} onChange={(event) => setSummary(event.target.value)} />
          </label>
          <button className="primary-button" disabled={pending} type="submit">
            {pending ? "保存中..." : "保存长期画像"}
          </button>
        </form>

        <form className="panel stack-form" onSubmit={submitCareerState}>
          <h2>动态状态</h2>
          <label className="field">
            <span>重点公司</span>
            <textarea rows={4} value={watchedCompanies} onChange={(event) => setWatchedCompanies(event.target.value)} />
          </label>
          <label className="field">
            <span>每日关注网站</span>
            <div className="source-table-shell">
              <div className="source-table-header">
                <span>基础网址</span>
                <button
                  type="button"
                  className="segment"
                  onClick={() => setMarketWatchSources((current) => [...current, ""])}
                >
                  新增一行
                </button>
              </div>
              <div className="source-table-scroll">
                {marketWatchSources.map((source, index) => (
                  <div key={`${index}-${source}`} className="source-row">
                    <span className="source-index">{index + 1}</span>
                    <input
                      value={source}
                      onChange={(event) =>
                        setMarketWatchSources((current) =>
                          current.map((value, currentIndex) =>
                            currentIndex === index ? event.target.value : value,
                          ),
                        )
                      }
                      placeholder="https://example.com/"
                    />
                    <button
                      type="button"
                      className="segment"
                      onClick={() =>
                        setMarketWatchSources((current) =>
                          current.length === 1
                            ? [""]
                            : current.filter((_, currentIndex) => currentIndex !== index),
                        )
                      }
                    >
                      删除
                    </button>
                  </div>
                ))}
              </div>
            </div>
          </label>
          <label className="field">
            <span>市场文章抓取上限</span>
            <input
              type="number"
              min={1}
              max={20}
              value={marketArticleFetchLimit}
              onChange={(event) => setMarketArticleFetchLimit(event.target.value)}
              placeholder="每个来源最多抓取多少篇正文"
            />
          </label>
          <label className="field">
            <span>今天重点</span>
            <textarea rows={4} value={todayFocus} onChange={(event) => setTodayFocus(event.target.value)} />
          </label>
          <label className="field">
            <span>当前优先级</span>
            <textarea rows={4} value={activePriorities} onChange={(event) => setActivePriorities(event.target.value)} />
          </label>
          <label className="field">
            <span>备注</span>
            <textarea rows={6} value={notes} onChange={(event) => setNotes(event.target.value)} />
          </label>
          <button className="primary-button" disabled={pending} type="submit">
            {pending ? "保存中..." : "保存动态状态"}
          </button>
        </form>
      </section>

      <section className="panel">
        <h2>最近回写结果</h2>
        {!lastSnapshot ? (
          <p className="muted-text">提交一次 profile 或 career-state 后，这里会展示最新回写结果。</p>
        ) : (
          <pre className="snapshot-box">{JSON.stringify(lastSnapshot, null, 2)}</pre>
        )}
      </section>
    </main>
  );
}
