"use client";

import {
  ChangeEvent,
  ClipboardEvent,
  FormEvent,
  startTransition,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { IngestResult, UnifiedAttachmentResult, UnifiedIngestResponse, apiRequest } from "../lib/api";

type AttachedFile = {
  id: string;
  file: File;
};

type IngestConversationTurn = {
  id: string;
  createdAt: string;
  userMessage: string;
  traceId: string | null;
  detectedInputKind: string | null;
  analysisReasons: string[];
  visitedLinks: string[];
  attachments: UnifiedAttachmentResult[];
  resolvedPaths: string[];
  results: IngestResult[];
};

type IngestConversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  contentDraft: string;
  turns: IngestConversationTurn[];
  summary: string;
};

const INGEST_CONVERSATIONS_CACHE_KEY = "ifome:ingest-conversations:v1";
const INGEST_ACTIVE_CONVERSATION_KEY = "ifome:ingest-active-conversation:v1";

function createIngestConversation(): IngestConversation {
  const now = new Date().toISOString();
  return {
    id: `ingest-conversation-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: "新的输入对话",
    createdAt: now,
    updatedAt: now,
    contentDraft: "",
    turns: [],
    summary: "空白输入历史",
  };
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function buildInputSummary(content: string, results: IngestResult[]) {
  const cleaned = content.replace(/\s+/g, " ").trim();
  const firstCard = results.find((result) => result.card)?.card?.summary_one_line;
  return firstCard || cleaned.slice(0, 42) || "附件输入";
}

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
  const restoredConversationIdRef = useRef<string | null>(null);
  const [conversations, setConversations] = useState<IngestConversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [selectedConversationIds, setSelectedConversationIds] = useState<string[]>([]);
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

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) ?? null,
    [conversations, activeConversationId],
  );

  useEffect(() => {
    try {
      const cachedConversations = window.localStorage.getItem(INGEST_CONVERSATIONS_CACHE_KEY);
      const cachedActiveId = window.localStorage.getItem(INGEST_ACTIVE_CONVERSATION_KEY);
      if (!cachedConversations) {
        const initial = createIngestConversation();
        setConversations([initial]);
        setActiveConversationId(initial.id);
        return;
      }
      const parsed = JSON.parse(cachedConversations) as IngestConversation[];
      if (!Array.isArray(parsed) || parsed.length === 0) {
        const initial = createIngestConversation();
        setConversations([initial]);
        setActiveConversationId(initial.id);
        return;
      }
      setConversations(parsed);
      setActiveConversationId(
        parsed.some((conversation) => conversation.id === cachedActiveId)
          ? cachedActiveId
          : parsed[0].id,
      );
    } catch {
      const initial = createIngestConversation();
      setConversations([initial]);
      setActiveConversationId(initial.id);
    }
  }, []);

  useEffect(() => {
    if (conversations.length === 0) {
      return;
    }
    try {
      window.localStorage.setItem(INGEST_CONVERSATIONS_CACHE_KEY, JSON.stringify(conversations));
      if (activeConversationId) {
        window.localStorage.setItem(INGEST_ACTIVE_CONVERSATION_KEY, activeConversationId);
      }
    } catch {
      return;
    }
  }, [conversations, activeConversationId]);

  useEffect(() => {
    if (!activeConversation) {
      return;
    }
    if (restoredConversationIdRef.current === activeConversation.id) {
      return;
    }
    restoredConversationIdRef.current = activeConversation.id;
    setContent(activeConversation.contentDraft);
    const lastTurn = activeConversation.turns[activeConversation.turns.length - 1];
    setResults(lastTurn?.results ?? []);
    setTraceId(lastTurn?.traceId ?? null);
    setDetectedInputKind(lastTurn?.detectedInputKind ?? null);
    setAnalysisReasons(lastTurn?.analysisReasons ?? []);
    setVisitedLinks(lastTurn?.visitedLinks ?? []);
    setAttachments(lastTurn?.attachments ?? []);
    setResolvedPaths(lastTurn?.resolvedPaths ?? []);
  }, [activeConversation]);

  useEffect(() => {
    if (!activeConversationId) {
      return;
    }
    setConversations((current) => {
      let changed = false;
      const next = current.map((conversation) => {
        if (conversation.id !== activeConversationId) {
          return conversation;
        }
        if (conversation.contentDraft === content) {
          return conversation;
        }
        changed = true;
        return { ...conversation, contentDraft: content };
      });
      return changed ? next : current;
    });
  }, [content, activeConversationId]);

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

  function createNewConversation() {
    const nextConversation = createIngestConversation();
    setConversations((current) => [nextConversation, ...current]);
    setActiveConversationId(nextConversation.id);
    setContent("");
    setResults([]);
    setTraceId(null);
    setDetectedInputKind(null);
    setAnalysisReasons([]);
    setVisitedLinks([]);
    setAttachments([]);
    setResolvedPaths([]);
    setAttachedFiles([]);
    setError(null);
  }

  function activateConversation(conversationId: string) {
    setActiveConversationId(conversationId);
    setAttachedFiles([]);
    setError(null);
  }

  function deleteConversation(conversationId: string) {
    setConversations((current) => {
      const remaining = current.filter((conversation) => conversation.id !== conversationId);
      if (remaining.length === 0) {
        const nextConversation = createIngestConversation();
        setActiveConversationId(nextConversation.id);
        return [nextConversation];
      }
      if (activeConversationId === conversationId) {
        setActiveConversationId(remaining[0].id);
      }
      return remaining;
    });
    setSelectedConversationIds((current) => current.filter((value) => value !== conversationId));
  }

  function toggleConversationSelection(conversationId: string) {
    setSelectedConversationIds((current) =>
      current.includes(conversationId)
        ? current.filter((value) => value !== conversationId)
        : [...current, conversationId],
    );
  }

  function deleteSelectedConversations() {
    if (selectedConversationIds.length === 0) {
      return;
    }
    const targets = new Set(selectedConversationIds);
    setConversations((current) => {
      const remaining = current.filter((conversation) => !targets.has(conversation.id));
      if (remaining.length === 0) {
        const nextConversation = createIngestConversation();
        setActiveConversationId(nextConversation.id);
        return [nextConversation];
      }
      if (activeConversationId && targets.has(activeConversationId)) {
        setActiveConversationId(remaining[0].id);
      }
      return remaining;
    });
    setSelectedConversationIds([]);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeConversation) {
      return;
    }
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
        const now = new Date().toISOString();
        const turn: IngestConversationTurn = {
          id: `ingest-turn-${Date.now()}`,
          createdAt: now,
          userMessage: content.trim() || `已上传附件：${attachedFiles.map(({ file }) => file.name).join("、")}`,
          traceId: response.trace_id ?? null,
          detectedInputKind: response.data.detected_input_kind,
          analysisReasons: response.data.analysis_reasons,
          visitedLinks: response.data.visited_links,
          attachments: response.data.attachments,
          resolvedPaths: response.data.resolved_local_paths,
          results: response.data.results,
        };
        const summary = buildInputSummary(content, response.data.results);
        setConversations((current) =>
          current.map((conversation) =>
            conversation.id === activeConversation.id
              ? {
                  ...conversation,
                  title: conversation.turns.length === 0 ? summary : conversation.title,
                  updatedAt: now,
                  contentDraft: "",
                  turns: [...conversation.turns, turn],
                  summary,
                }
              : conversation,
          ),
        );
        setResults(response.data.results);
        setTraceId(response.trace_id ?? null);
        setDetectedInputKind(response.data.detected_input_kind);
        setAnalysisReasons(response.data.analysis_reasons);
        setVisitedLinks(response.data.visited_links);
        setAttachments(response.data.attachments);
        setResolvedPaths(response.data.resolved_local_paths);
        setAttachedFiles([]);
        setContent("");
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
          <div className="conversation-toolbar">
            <div>
              <h2>当前输入对话</h2>
              <p className="muted-text">一次主题里的多轮输入会保存在同一个历史中。</p>
            </div>
            <button type="button" className="segment" onClick={createNewConversation}>
              创建新对话
            </button>
          </div>
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
        <h2>当前对话输出</h2>
        {error ? <p className="error-text">{error}</p> : null}
        {!activeConversation || activeConversation.turns.length === 0 ? (
          <p className="muted-text">
            提交后，这里会按时间顺序展示本次输入对话中的每一轮输入和输出。
          </p>
        ) : (
          <div className="result-stack">
            {activeConversation.turns.map((turn, turnIndex) => (
              <article key={turn.id} className="job-card spotlight-card">
                <div className="card-header">
                  <p className="card-summary">第 {turnIndex + 1} 轮：{buildInputSummary(turn.userMessage, turn.results)}</p>
                  <span className="metric-chip">{formatTimestamp(turn.createdAt)}</span>
                </div>
                <div className="routing-box">
                  <h3>输入</h3>
                  <pre>{turn.userMessage}</pre>
                </div>
                <div className="metric-row">
                  {turn.traceId ? <span className="metric-chip">trace {turn.traceId}</span> : null}
                  {turn.detectedInputKind ? (
                    <span className="metric-chip">类型 {turn.detectedInputKind}</span>
                  ) : null}
                  <span className="metric-chip">生成卡片 {turn.results.length}</span>
                  {turn.attachments.length > 0 ? (
                    <span className="metric-chip">附件 {turn.attachments.length}</span>
                  ) : null}
                </div>
                {turn.analysisReasons.length > 0 ? (
                  <div className="tag-row">
                    {turn.analysisReasons.map((reason, reasonIndex) => (
                      <span key={`${turn.id}-${reason}-${reasonIndex}`} className="tag-chip">
                        {reason}
                      </span>
                    ))}
                  </div>
                ) : null}
                {turn.attachments.length > 0 ? (
                  <div className="routing-box">
                    <h3>已转文字的附件</h3>
                    <pre>
                      {turn.attachments
                        .map(
                          (attachment) =>
                            `${attachment.display_name} | ${attachment.extraction_kind} | ${attachment.text_length} chars`,
                        )
                        .join("\n")}
                    </pre>
                  </div>
                ) : null}
                {turn.resolvedPaths.length > 0 ? (
                  <div className="routing-box">
                    <h3>识别到的本地路径</h3>
                    <pre>{turn.resolvedPaths.join("\n")}</pre>
                  </div>
                ) : null}
                {turn.visitedLinks.length > 0 ? (
                  <div className="routing-box">
                    <h3>访问过的链接</h3>
                    <pre>{turn.visitedLinks.join("\n")}</pre>
                  </div>
                ) : null}
                {turn.results.map((result, index) => (
                  <article key={`${turn.id}-${result.item_id ?? "result"}-${index}`} className="panel panel-subtle">
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
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="panel conversation-history-panel">
        <div className="conversation-toolbar">
          <div>
            <h2>输入历史</h2>
            <p className="muted-text">默认展示前 5 条摘要，其余可以滚动查看；点击继续可回到原历史并继续输入。</p>
          </div>
          <button
            type="button"
            className="segment"
            disabled={selectedConversationIds.length === 0}
            onClick={deleteSelectedConversations}
          >
            删除选中（{selectedConversationIds.length}）
          </button>
        </div>
        <div className="conversation-list">
          {conversations.map((conversation) => {
            const isActive = conversation.id === activeConversationId;
            return (
              <article
                key={conversation.id}
                className={`conversation-card ${isActive ? "conversation-card-active" : ""}`}
              >
                <div className="conversation-card-header">
                  <label className="checkbox-row">
                    <input
                      type="checkbox"
                      checked={selectedConversationIds.includes(conversation.id)}
                      onChange={() => toggleConversationSelection(conversation.id)}
                    />
                    <span>选择</span>
                  </label>
                  <button
                    type="button"
                    className="segment chat-history-toggle"
                    onClick={() => activateConversation(conversation.id)}
                  >
                    {conversation.title} · {conversation.summary}
                  </button>
                  <div className="metric-row">
                    <span className="metric-chip">{conversation.turns.length} 轮</span>
                    <button
                      type="button"
                      className={`segment ${isActive ? "segment-active" : ""}`}
                      onClick={() => activateConversation(conversation.id)}
                    >
                      {isActive ? "当前历史" : "继续输入"}
                    </button>
                    <button
                      type="button"
                      className="segment"
                      onClick={() => deleteConversation(conversation.id)}
                    >
                      删除
                    </button>
                  </div>
                </div>
                <p className="muted-text">最近更新：{formatTimestamp(conversation.updatedAt)}</p>
              </article>
            );
          })}
        </div>
      </section>
    </main>
  );
}
