"use client";

import { FormEvent, startTransition, useState } from "react";

import { AutoIngestResponse, IngestResult, apiRequest } from "../lib/api";

type IngestMode = "mixed" | "image";

const modeLabels: Record<IngestMode, string> = {
  mixed: "文本 / 链接",
  image: "截图 OCR",
};

function formatCardTime(result: IngestResult) {
  if (!result.card) {
    return "无";
  }
  if (result.card.interview_time) {
    return result.card.interview_time;
  }
  if (result.card.event_time) {
    return result.card.event_time;
  }
  return result.card.ddl || "无";
}

export default function IngestPage() {
  const [mode, setMode] = useState<IngestMode>("mixed");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<IngestResult[]>([]);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [detectedInputKind, setDetectedInputKind] = useState<string | null>(null);
  const [analysisReasons, setAnalysisReasons] = useState<string[]>([]);
  const [visitedLinks, setVisitedLinks] = useState<string[]>([]);
  const [content, setContent] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      if (mode === "mixed") {
        const response = await apiRequest<AutoIngestResponse>("/ingest/auto", {
          method: "POST",
          body: JSON.stringify({ content }),
        });
        startTransition(() => {
          setResults(response.data.results);
          setTraceId(response.trace_id ?? null);
          setDetectedInputKind(response.data.detected_input_kind);
          setAnalysisReasons(response.data.analysis_reasons);
          setVisitedLinks(response.data.visited_links);
        });
      }

      if (mode === "image") {
        if (!imageFile) {
          throw new Error("请先选择一张图片。");
        }
        const formData = new FormData();
        formData.append("file", imageFile);

        const response = await apiRequest<IngestResult>("/ingest/image-file", {
          method: "POST",
          body: formData,
        });
        startTransition(() => {
          setResults([response.data]);
          setTraceId(response.trace_id ?? null);
          setDetectedInputKind("image");
          setAnalysisReasons(["ocr upload"]);
          setVisitedLinks([]);
        });
      }
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "提交失败，请稍后重试。",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="dashboard-grid">
      <section className="hero panel panel-hero">
        <p className="eyebrow">Input Workspace</p>
        <h1>把文本、招聘链接和上下文放进同一个入口</h1>
        <p className="intro">
          现在文本和链接共用一个输入框。后端会先判断你贴进来的内容类型，再决定是否访问链接、是否拆成多条岗位信息，以及怎样把上下文一起送进工作流。
        </p>
      </section>

      <section className="panel">
        <div className="segmented-control">
          {(Object.keys(modeLabels) as IngestMode[]).map((value) => (
            <button
              key={value}
              type="button"
              className={mode === value ? "segment segment-active" : "segment"}
              onClick={() => setMode(value)}
            >
              {modeLabels[value]}
            </button>
          ))}
        </div>

        <form className="stack-form" onSubmit={onSubmit}>
          {mode === "mixed" ? (
            <label className="field">
              <span>输入内容</span>
              <textarea
                value={content}
                onChange={(event) => setContent(event.target.value)}
                placeholder="可以直接粘贴招聘文本、纯链接，或者“说明文字 + 一个或多个链接”"
                rows={10}
              />
            </label>
          ) : null}

          {mode === "image" ? (
            <>
              <label className="field">
                <span>上传截图</span>
                <input
                  type="file"
                  accept="image/*"
                  onChange={(event) =>
                    setImageFile(event.target.files?.[0] ?? null)
                  }
                />
              </label>
              <p className="muted-text">
                当前会先走本地 OCR，再把识别结果送进同一条工作流。
              </p>
            </>
          ) : null}

          <button className="primary-button" disabled={pending} type="submit">
            {pending ? "处理中..." : "提交到工作流"}
          </button>
        </form>
      </section>

      <section className="panel">
        <h2>处理结果</h2>
        {error ? <p className="error-text">{error}</p> : null}
        {results.length === 0 ? (
          <p className="muted-text">
            提交一次输入后，这里会展示识别结果、访问过的链接以及生成的卡片。
          </p>
        ) : (
          <div className="result-stack">
            <div className="metric-row">
              {traceId ? <span className="metric-chip">trace {traceId}</span> : null}
              {detectedInputKind ? (
                <span className="metric-chip">类型 {detectedInputKind}</span>
              ) : null}
              <span className="metric-chip">生成卡片 {results.length}</span>
            </div>

            {analysisReasons.length > 0 ? (
              <div className="tag-row">
                {analysisReasons.map((reason) => (
                  <span key={reason} className="tag-chip">
                    {reason}
                  </span>
                ))}
              </div>
            ) : null}

            {visitedLinks.length > 0 ? (
              <div className="routing-box">
                <h3>访问过的链接</h3>
                <pre>{visitedLinks.join("\n")}</pre>
              </div>
            ) : null}

            {results.map((result, index) => (
              <article key={`${result.item_id ?? "result"}-${index}`} className="job-card spotlight-card">
                <div className="card-header">
                  <p className="card-summary">
                    {result.card?.summary_one_line || `第 ${index + 1} 条处理结果`}
                  </p>
                  {result.card?.priority ? (
                    <span className={`priority-badge priority-${result.card.priority.toLowerCase()}`}>
                      {result.card.priority}
                    </span>
                  ) : null}
                </div>
                <div className="card-grid">
                  <span>公司：{result.card?.company || "待识别"}</span>
                  <span>岗位：{result.card?.role || "待识别"}</span>
                  <span>地点：{result.card?.city || "待识别"}</span>
                  <span>时间：{formatCardTime(result)}</span>
                  <span>分类：{result.card?.content_category || result.status}</span>
                  <span>状态：{result.status}</span>
                </div>
                <div className="routing-box">
                  <h3>模型路由</h3>
                  <pre>{JSON.stringify(result.model_routing, null, 2)}</pre>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
