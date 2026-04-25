"use client";

import { ChangeEvent, ClipboardEvent, FormEvent, startTransition, useRef, useState } from "react";

import { IngestResult, UnifiedAttachmentResult, UnifiedIngestResponse, apiRequest } from "../lib/api";

type AttachedFile = {
  id: string;
  file: File;
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
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<IngestResult[]>([]);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [detectedInputKind, setDetectedInputKind] = useState<string | null>(null);
  const [analysisReasons, setAnalysisReasons] = useState<string[]>([]);
  const [visitedLinks, setVisitedLinks] = useState<string[]>([]);
  const [attachments, setAttachments] = useState<UnifiedAttachmentResult[]>([]);
  const [resolvedPaths, setResolvedPaths] = useState<string[]>([]);
  const [content, setContent] = useState("");
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);

  function appendFiles(nextFiles: FileList | File[] | null) {
    if (!nextFiles || nextFiles.length === 0) {
      return;
    }

    const normalizedFiles = Array.from(nextFiles);
    setAttachedFiles((current) => [
      ...current,
      ...normalizedFiles.map((file, index) => ({
        id: `${file.name}-${file.size}-${file.lastModified}-${current.length + index}`,
        file,
      })),
    ]);
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    appendFiles(event.target.files);
    event.target.value = "";
  }

  function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    appendFiles(event.clipboardData?.files ?? null);
  }

  function removeAttachedFile(targetId: string) {
    setAttachedFiles((current) => current.filter((item) => item.id !== targetId));
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("content", content);
      attachedFiles.forEach(({ file }) => {
        formData.append("files", file);
      });

      const response = await apiRequest<UnifiedIngestResponse>("/ingest/unified", {
        method: "POST",
        body: formData,
      });
      startTransition(() => {
        setResults(response.data.results);
        setTraceId(response.trace_id ?? null);
        setDetectedInputKind(response.data.detected_input_kind);
        setAnalysisReasons(response.data.analysis_reasons);
        setVisitedLinks(response.data.visited_links);
        setAttachments(response.data.attachments);
        setResolvedPaths(response.data.resolved_local_paths);
        setAttachedFiles([]);
      });
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
        <p className="eyebrow">Unified Composer</p>
        <h1>一个聊天框，同时接文字、图片、PDF、文本文件和本地路径</h1>
        <p className="intro">
          现在输入页只保留一个消息框。你可以直接粘贴文本、在框里写本地图片或文件路径、粘贴截图/文件，
          或点击按钮上传。图片会先走独立的 Qwen-VL-OCR，PDF/文本文件会先转文字，再进入同一条分析工作流。
        </p>
      </section>

      <section className="panel">
        <form className="stack-form" onSubmit={onSubmit}>
          <label className="field">
            <span>输入消息</span>
            <textarea
              value={content}
              onChange={(event) => setContent(event.target.value)}
              onPaste={onPaste}
              placeholder={[
                "可以直接输入：",
                "1. 招聘文本 / 链接",
                "2. 本地图片或文件路径（单独占一行）",
                "3. 说明文字 + 路径 + 链接混合输入",
              ].join("\n")}
              rows={12}
            />
          </label>

          <div className="composer-toolbar">
            <button
              type="button"
              className="segment"
              onClick={() => fileInputRef.current?.click()}
            >
              上传图片 / 文件
            </button>
            <span className="muted-text">
              支持图片、PDF、TXT/MD/JSON/CSV 等文本文件，也支持直接粘贴剪贴板里的图片或文件。
            </span>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="image/*,.pdf,.txt,.md,.markdown,.json,.csv,.log,.yaml,.yml"
            onChange={onFileChange}
            hidden
          />

          {attachedFiles.length > 0 ? (
            <div className="attachment-list">
              {attachedFiles.map(({ id, file }) => (
                <div key={id} className="attachment-chip">
                  <span>{file.name}</span>
                  <button
                    type="button"
                    className="segment"
                    onClick={() => removeAttachedFile(id)}
                  >
                    移除
                  </button>
                </div>
              ))}
            </div>
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
            提交后，这里会展示解析出来的文件、识别路径、访问过的链接和最终生成的卡片。
          </p>
        ) : (
          <div className="result-stack">
            <div className="metric-row">
              {traceId ? <span className="metric-chip">trace {traceId}</span> : null}
              {detectedInputKind ? (
                <span className="metric-chip">类型 {detectedInputKind}</span>
              ) : null}
              <span className="metric-chip">生成卡片 {results.length}</span>
              {attachments.length > 0 ? (
                <span className="metric-chip">附件 {attachments.length}</span>
              ) : null}
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

            {attachments.length > 0 ? (
              <div className="routing-box">
                <h3>已转文字的附件</h3>
                <pre>
                  {attachments
                    .map(
                      (attachment) =>
                        `${attachment.display_name} | ${attachment.extraction_kind} | ${attachment.text_length} chars`,
                    )
                    .join("\n")}
                </pre>
              </div>
            ) : null}

            {resolvedPaths.length > 0 ? (
              <div className="routing-box">
                <h3>识别到的本地路径</h3>
                <pre>{resolvedPaths.join("\n")}</pre>
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
