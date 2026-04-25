"use client";

import { FormEvent, useEffect, useState } from "react";

import { API_BASE_URL, MemoryResponse, apiRequest } from "../lib/api";

function parseLines(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinLines(values: string[] | undefined) {
  return (values ?? []).join("\n");
}

const DEFAULT_MARKET_WATCH_SOURCES = [
  "https://www.jiqizhixin.com/",
  "https://www.qbitai.com/",
];

export default function MemoryPage() {
  const [targetRoles, setTargetRoles] = useState("");
  const [priorityDomains, setPriorityDomains] = useState("");
  const [skills, setSkills] = useState("");
  const [locations, setLocations] = useState("");
  const [softPreferences, setSoftPreferences] = useState("");
  const [excludedCompanies, setExcludedCompanies] = useState("");
  const [summary, setSummary] = useState("");

  const [watchedCompanies, setWatchedCompanies] = useState("");
  const [marketWatchSources, setMarketWatchSources] = useState(DEFAULT_MARKET_WATCH_SOURCES);
  const [marketArticleFetchLimit, setMarketArticleFetchLimit] = useState("5");
  const [todayFocus, setTodayFocus] = useState("");
  const [activePriorities, setActivePriorities] = useState("");
  const [notes, setNotes] = useState("");

  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [loadingSnapshot, setLoadingSnapshot] = useState(true);
  const [lastSnapshot, setLastSnapshot] = useState<MemoryResponse | null>(null);

  useEffect(() => {
    async function loadMemory() {
      try {
        const response = await apiRequest<MemoryResponse>("/memory");
        const snapshot = response.data;
        setLastSnapshot(snapshot);

        if (snapshot.profile_memory) {
          setTargetRoles(joinLines(snapshot.profile_memory.target_roles));
          setPriorityDomains(joinLines(snapshot.profile_memory.priority_domains));
          setSkills(joinLines(snapshot.profile_memory.skills));
          setLocations(joinLines(snapshot.profile_memory.location_preferences));
          setSoftPreferences(joinLines(snapshot.profile_memory.soft_preferences));
          setExcludedCompanies(joinLines(snapshot.profile_memory.excluded_companies));
          setSummary(snapshot.profile_memory.summary ?? "");
        }

        if (snapshot.career_state_memory) {
          setWatchedCompanies(joinLines(snapshot.career_state_memory.watched_companies));
          setMarketWatchSources(
            snapshot.career_state_memory.market_watch_sources.length > 0
              ? snapshot.career_state_memory.market_watch_sources
              : DEFAULT_MARKET_WATCH_SOURCES,
          );
          setMarketArticleFetchLimit(String(snapshot.career_state_memory.market_article_fetch_limit));
          setTodayFocus(joinLines(snapshot.career_state_memory.today_focus));
          setActivePriorities(joinLines(snapshot.career_state_memory.active_priorities));
          setNotes(snapshot.career_state_memory.notes ?? "");
        }
      } catch (requestError) {
        setError(
          requestError instanceof Error ? requestError.message : "读取 memory 快照失败。",
        );
      } finally {
        setLoadingSnapshot(false);
      }
    }

    void loadMemory();
  }, []);

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

  const resumeSnapshot = lastSnapshot?.profile_memory?.resume_snapshot ?? null;
  const projectEntries = lastSnapshot?.profile_memory?.projects ?? [];
  const resumeFileUrl = `${API_BASE_URL}/memory/profile/resume-file`;

  return (
    <main className="dashboard-grid">
      <div className="memory-page-shell">
        <section className="hero panel panel-hero">
          <p className="eyebrow">Memory Control</p>
          <h1>把长期画像、动态状态、项目画像和简历资料拆开管理</h1>
          <p className="intro">
            这里现在除了 `profile` 和 `career-state` 之外，还会展示聊天上传后即时整理好的项目画像和简历网页版本。你可以直接打开源文件，也可以把整理好的条目拷去其他表单或后续工具调用。
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

        <section className="panel memory-secondary-panel">
        <h2>项目画像</h2>
        {loadingSnapshot ? (
          <p className="muted-text">正在读取当前 memory 快照...</p>
        ) : projectEntries.length === 0 ? (
          <p className="muted-text">
            还没有导入项目说明。你可以在聊天框上传 README、项目说明、架构设计或方案文档，系统会自动整理成项目画像并在后续聊天里参与检索。
          </p>
        ) : (
          <div className="result-stack">
            {projectEntries.map((project) => {
              const projectFileUrl = `${API_BASE_URL}/memory/profile/project-file?project_name=${encodeURIComponent(project.name)}`;
              return (
                <article key={project.name} className="panel panel-subtle">
                  <div className="metric-row">
                    <span className="metric-chip">{project.name}</span>
                    {project.role ? <span className="metric-chip">{project.role}</span> : null}
                    {project.source_file_name ? <span className="metric-chip">{project.source_file_name}</span> : null}
                  </div>
                  <p>{project.summary}</p>
                  {project.tech_stack.length > 0 ? (
                    <div className="tag-row">
                      {project.tech_stack.map((value) => (
                        <span key={value} className="tag-chip">
                          {value}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {project.highlight_points.length > 0 ? (
                    <div className="result-stack">
                      <h3>亮点整理</h3>
                      {project.highlight_points.map((value) => (
                        <p key={value} className="muted-text">
                          {value}
                        </p>
                      ))}
                    </div>
                  ) : null}
                  {project.interview_story_hooks.length > 0 ? (
                    <div className="result-stack">
                      <h3>面试切入口</h3>
                      {project.interview_story_hooks.map((value) => (
                        <p key={value} className="muted-text">
                          {value}
                        </p>
                      ))}
                    </div>
                  ) : null}
                  {project.source_file_name ? (
                    <p>
                      <a className="segment" href={projectFileUrl} rel="noreferrer" target="_blank">
                        打开项目源文件
                      </a>
                    </p>
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
        </section>

        <section className="panel memory-secondary-panel">
        <h2>简历资料</h2>
        {loadingSnapshot ? (
          <p className="muted-text">正在读取当前 memory 快照...</p>
        ) : !resumeSnapshot ? (
          <p className="muted-text">
            还没有导入简历。你可以在聊天框上传简历 PDF/图片/文本，系统会自动提取原文、结构化整理，并在这里显示。
          </p>
        ) : (
          <div className="result-stack">
            <div className="metric-row">
              {resumeSnapshot.file_name ? (
                <span className="metric-chip">{resumeSnapshot.file_name}</span>
              ) : null}
              {resumeSnapshot.updated_at ? (
                <span className="metric-chip">更新于 {resumeSnapshot.updated_at}</span>
              ) : null}
            </div>

            <div className="routing-box">
              <h3>导入源文件</h3>
              <p className="muted-text">
                {resumeSnapshot.source_file_name || resumeSnapshot.file_name || "已归档简历源文件"}
              </p>
              <p>
                <a className="segment" href={resumeFileUrl} rel="noreferrer" target="_blank">
                  打开简历 PDF 源文件
                </a>
              </p>
            </div>

            {resumeSnapshot.summary ? (
              <div className="routing-box">
                <h3>简历摘要</h3>
                <p>{resumeSnapshot.summary}</p>
              </div>
            ) : null}

            {resumeSnapshot.structured_profile?.headline ? (
              <div className="routing-box">
                <h3>网页版概览</h3>
                <p>{resumeSnapshot.structured_profile.headline}</p>
              </div>
            ) : null}

            {resumeSnapshot.structured_profile?.sections?.length ? (
              <div className="result-stack">
                <h3>网页整理版</h3>
                {resumeSnapshot.structured_profile.sections.map((section) => (
                  <article key={section.title} className="panel panel-subtle">
                    <p>
                      <strong>{section.title}</strong>
                    </p>
                    {section.items.length > 0 ? (
                      <div className="result-stack">
                        {section.items.map((item) => (
                          <p key={item} className="muted-text">
                            {item}
                          </p>
                        ))}
                      </div>
                    ) : (
                      <p className="muted-text">暂无条目。</p>
                    )}
                  </article>
                ))}
              </div>
            ) : null}

            <div className="routing-box">
              <h3>简历原文</h3>
              <pre>{resumeSnapshot.text}</pre>
            </div>
          </div>
        )}
        </section>

        <section className="panel memory-secondary-panel">
          <h2>最近回写结果</h2>
          {!lastSnapshot ? (
            <p className="muted-text">提交一次 profile、career-state 或简历导入后，这里会展示最新回写结果。</p>
          ) : (
            <pre className="snapshot-box memory-snapshot-box">{JSON.stringify(lastSnapshot, null, 2)}</pre>
          )}
        </section>
      </div>
    </main>
  );
}
