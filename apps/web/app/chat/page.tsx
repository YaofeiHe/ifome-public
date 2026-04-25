"use client";

import {
  ChangeEvent,
  ClipboardEvent,
  FormEvent,
  startTransition,
  useEffect,
  useRef,
  useState,
} from "react";

import { ChatQueryResponse, ItemListResponse, RenderedItemCard, apiRequest } from "../lib/api";

type AttachedFile = {
  id: string;
  file: File;
};

type ChatMode = "grounded_chat" | "boss_simulator";

type BossConversationTurn = {
  id: string;
  bossMessage: string;
  replyText: string;
  strategy: string;
};

const BOSS_SIMULATOR_CACHE_KEY = "ifome:boss-simulator-history:v2";

function parseBossAnswer(answer: string) {
  const normalized = answer.trim();
  const strategyPattern = /(?:^|\n)(?:回复策略|策略说明|回复思路)\s*[：:]\s*/;
  const matched = normalized.match(strategyPattern);
  if (!matched || matched.index === undefined) {
    return {
      replyText: normalized,
      strategy: "这轮没有显式输出回复策略，建议结合语气和上下文再做一次人工确认。",
    };
  }

  const replyText = normalized.slice(0, matched.index).trim();
  const strategy = normalized
    .slice(matched.index + matched[0].length)
    .trim();

  return {
    replyText: replyText || normalized,
    strategy: strategy || "这轮没有显式输出回复策略，建议结合语气和上下文再做一次人工确认。",
  };
}

function buildBossSimulatorPrompt(
  currentMessage: string,
  history: BossConversationTurn[],
) {
  const transcript = history.length
    ? history
        .slice(-12)
        .map(
          (turn, index) =>
            [
              `第 ${index + 1} 轮对话`,
              `Boss / HR：${turn.bossMessage}`,
              `我上一轮发送的回复：${turn.replyText}`,
            ].join("\n"),
        )
        .join("\n\n")
    : "暂无历史对话。";

  return [
    "请基于我的长期画像、项目画像、简历、已有岗位卡片、附件内容和下面的历史对话，模拟求职场景中的 Boss / HR 沟通回复。",
    "任务要求：",
    "1. 先理解当前这条消息和前文关系，不要把每一轮都当成全新陌生对话。",
    "2. 只输出两部分：",
    "第一部分用“建议回复：”开头，写一条我可以直接发送的中文回复正文。",
    "第二部分用“回复策略：”开头，简要说明为什么这么回。",
    "3. 建议回复要自然、礼貌、具体，不要太模板化。",
    "4. 如果我上传了附件，把附件视为聊天截图、JD、简历或上下文材料一起理解。",
    "5. 如果信息不足，也先基于已有上下文给一个稳妥版本，不要拒答。",
    "",
    "历史对话：",
    transcript,
    "",
    "当前收到的新消息：",
    currentMessage,
  ].join("\n");
}

function buildVisibleBossMessage(query: string, attachedFiles: AttachedFile[]) {
  const cleaned = query.trim();
  if (cleaned) {
    return cleaned;
  }
  if (attachedFiles.length === 0) {
    return "未填写文字消息。";
  }
  return `已上传附件：${attachedFiles.map(({ file }) => file.name).join("、")}`;
}

export default function ChatPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [mode, setMode] = useState<ChatMode>("grounded_chat");
  const [items, setItems] = useState<RenderedItemCard[]>([]);
  const [itemId, setItemId] = useState("");
  const [query, setQuery] = useState("给我本周的 ddl");
  const [recentDays, setRecentDays] = useState(30);
  const [applyMemoryUpdates, setApplyMemoryUpdates] = useState(true);
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const [answer, setAnswer] = useState<string | null>(null);
  const [supportingItemIds, setSupportingItemIds] = useState<string[]>([]);
  const [citations, setCitations] = useState<ChatQueryResponse["citations"]>([]);
  const [retrievalMode, setRetrievalMode] = useState<string | null>(null);
  const [queryPlan, setQueryPlan] = useState<ChatQueryResponse["query_plan"]>(null);
  const [memoryUpdate, setMemoryUpdate] = useState<ChatQueryResponse["memory_update"]>(null);
  const [attachments, setAttachments] = useState<ChatQueryResponse["attachments"]>([]);
  const [bossHistory, setBossHistory] = useState<BossConversationTurn[]>([]);
  const [copiedTurnId, setCopiedTurnId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  useEffect(() => {
    async function loadItems() {
      try {
        const response = await apiRequest<ItemListResponse>("/items");
        setItems(response.data.items);
      } catch (requestError) {
        setError(
          requestError instanceof Error ? requestError.message : "读取条目失败。",
        );
      }
    }

    void loadItems();
  }, []);

  useEffect(() => {
    try {
      const cached = window.localStorage.getItem(BOSS_SIMULATOR_CACHE_KEY);
      if (!cached) {
        return;
      }
      const parsed = JSON.parse(cached) as BossConversationTurn[];
      if (!Array.isArray(parsed)) {
        return;
      }
      setBossHistory(
        parsed.filter(
          (turn) =>
            Boolean(turn?.id) &&
            Boolean(turn?.bossMessage) &&
            Boolean(turn?.replyText),
        ),
      );
    } catch {
      return;
    }
  }, []);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        BOSS_SIMULATOR_CACHE_KEY,
        JSON.stringify(bossHistory),
      );
    } catch {
      return;
    }
  }, [bossHistory]);

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

  async function copyReply(replyText: string, turnId: string) {
    try {
      await navigator.clipboard.writeText(replyText);
      setCopiedTurnId(turnId);
    } catch {
      setCopiedTurnId(null);
    }
  }

  function clearBossHistory() {
    setBossHistory([]);
    setCopiedTurnId(null);
    try {
      window.localStorage.removeItem(BOSS_SIMULATOR_CACHE_KEY);
    } catch {
      return;
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setCopiedTurnId(null);

    const visibleBossMessage = buildVisibleBossMessage(query, attachedFiles);
    const submittedQuery =
      mode === "boss_simulator"
        ? buildBossSimulatorPrompt(visibleBossMessage, bossHistory)
        : query;

    try {
      const formData = new FormData();
      formData.append("query", submittedQuery);
      formData.append("recent_days", String(recentDays));
      formData.append("apply_memory_updates", String(applyMemoryUpdates));
      if (itemId) {
        formData.append("item_id", itemId);
      }
      attachedFiles.forEach(({ file }) => {
        formData.append("files", file);
      });

      const response = await apiRequest<ChatQueryResponse>("/chat/query-unified", {
        method: "POST",
        body: formData,
      });
      startTransition(() => {
        setAnswer(response.data.answer);
        setSupportingItemIds(response.data.supporting_item_ids);
        setCitations(response.data.citations);
        setRetrievalMode(response.data.retrieval_mode);
        setQueryPlan(response.data.query_plan ?? null);
        setMemoryUpdate(response.data.memory_update ?? null);
        setAttachments(response.data.attachments ?? []);
        if (mode === "boss_simulator") {
          const parsedAnswer = parseBossAnswer(response.data.answer);
          setBossHistory((current) => [
            ...current,
            {
              id: `boss-turn-${Date.now()}`,
              bossMessage: visibleBossMessage,
              replyText: parsedAnswer.replyText,
              strategy: parsedAnswer.strategy,
            },
          ]);
        }
        setAttachedFiles([]);
        setQuery("");
      });
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "聊天查询失败。",
      );
    } finally {
      setPending(false);
    }
  }

  const inputPlaceholder =
    mode === "boss_simulator"
      ? [
          "把 Boss / HR 发来的话贴进来，或直接上传聊天截图、JD、PDF、文本文件。",
          "例如：",
          "1. 您好，请问这周能安排一轮沟通吗？",
          "2. 方便发一下你的简历和项目介绍吗？",
          "3. 也可以只上传图片 / 文档，让系统先转文本再给出回复建议。",
        ].join("\n")
      : [
          "可以直接输入：",
          "1. 求职问题 / 链接 / JD 文本",
          "2. 本地图片或文件路径（单独占一行）",
          "3. 说明文字 + 路径 + 链接 + 附件混合输入",
          "4. 例如：给我本周的 ddl / 帮我润色简历 / 这段 JD 和我匹配吗",
        ].join("\n");

  return (
    <main className="dashboard-grid">
      <section className="hero panel panel-hero">
        <p className="eyebrow">Chat Console</p>
        <h1>一个聊天控制台，同时兼容提问、画像更新和 Boss 回复模拟</h1>
        <p className="intro">
          这里和输入页使用同一类统一输入方式。你可以直接粘贴文本、链接、在框里写本地路径，
          也可以上传或粘贴图片、PDF、README、项目说明和简历；后端会先抽取文本，需要 OCR 时自动转写，
          再把整理后的文本同时用于检索回答、画像更新、项目画像构建和 Boss 沟通建议。
        </p>
      </section>

      <section className="panel">
        <form className="stack-form" onSubmit={onSubmit}>
          <div className="segmented-control">
            <button
              type="button"
              className={`segment ${mode === "grounded_chat" ? "segment-active" : ""}`}
              onClick={() => setMode("grounded_chat")}
            >
              聊天问答
            </button>
            <button
              type="button"
              className={`segment ${mode === "boss_simulator" ? "segment-active" : ""}`}
              onClick={() => setMode("boss_simulator")}
            >
              模拟 Boss 回复
            </button>
          </div>

          {mode === "boss_simulator" ? (
            <div className="chat-simulator-toolbar">
              <p className="muted-text">
                历史对话会缓存在当前浏览器里，下一轮生成时会自动参考最近几轮上下文。
              </p>
              <button type="button" className="segment" onClick={clearBossHistory}>
                清空历史对话
              </button>
            </div>
          ) : null}

          <label className="field">
            <span>限定条目</span>
            <select value={itemId} onChange={(event) => setItemId(event.target.value)}>
              <option value="">全部条目</option>
              {items.map((item) => (
                <option key={item.item_id} value={item.item_id}>
                  {item.summary_one_line}
                </option>
              ))}
            </select>
          </label>

          <label className="field">
            <span>时间窗口（天）</span>
            <input
              type="number"
              min={1}
              max={365}
              value={recentDays}
              onChange={(event) => setRecentDays(Number(event.target.value) || 30)}
            />
          </label>

          <label className="field">
            <span>{mode === "boss_simulator" ? "Boss / HR 消息" : "输入消息"}</span>
            <textarea
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onPaste={onPaste}
              placeholder={inputPlaceholder}
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

          <label className="field">
            <span>画像自动更新</span>
            <input
              checked={applyMemoryUpdates}
              onChange={(event) => setApplyMemoryUpdates(event.target.checked)}
              type="checkbox"
            />
          </label>

          <button className="primary-button" disabled={pending} type="submit">
            {pending
              ? "处理中..."
              : mode === "boss_simulator"
                ? "生成回复"
                : "发送问题"}
          </button>
        </form>
      </section>

      <section className="panel">
        <h2>{mode === "boss_simulator" ? "回复建议" : "回答"}</h2>
        {error ? <p className="error-text">{error}</p> : null}
        {!answer && mode !== "boss_simulator" ? (
          <p className="muted-text">
            提交后，这里会展示回答、检索模式、预处理意图、附件转文本结果和画像更新摘要。
          </p>
        ) : null}

        {mode === "boss_simulator" ? (
          <div className="result-stack">
            {bossHistory.length === 0 ? (
              <p className="muted-text">
                这里会按社交聊天框形式展示多轮对话。每轮都会单独给出“建议回复”气泡和“回复策略”。
              </p>
            ) : (
              <div className="chat-simulator-thread">
                {bossHistory.map((turn) => (
                  <div key={turn.id} className="chat-turn">
                    <article className="chat-bubble chat-bubble-boss">
                      <p className="workspace-kicker">Boss / HR</p>
                      <p>{turn.bossMessage}</p>
                    </article>
                    <article className="chat-bubble chat-bubble-agent">
                      <div className="chat-bubble-header">
                        <p className="workspace-kicker">建议回复</p>
                        <button
                          type="button"
                          className="segment"
                          onClick={() => void copyReply(turn.replyText, turn.id)}
                        >
                          {copiedTurnId === turn.id ? "已复制" : "复制回复"}
                        </button>
                      </div>
                      <p>{turn.replyText}</p>
                    </article>
                    <div className="chat-strategy-box">
                      <p className="workspace-kicker">回复策略</p>
                      <p>{turn.strategy}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : answer ? (
          <div className="result-stack">
            <p className="answer-box">{answer}</p>
            {retrievalMode ? <p className="muted-text">检索模式：{retrievalMode}</p> : null}

            {queryPlan ? (
              <article className="panel panel-subtle">
                <h3>查询预处理</h3>
                <p className="muted-text">
                  意图：{queryPlan.intent} · 时间窗口：{queryPlan.recent_days} 天
                </p>
                {queryPlan.search_hints.length > 0 ? (
                  <div className="tag-row">
                    {queryPlan.search_hints.map((value) => (
                      <span key={value} className="tag-chip">
                        {value}
                      </span>
                    ))}
                  </div>
                ) : null}
                {queryPlan.rewritten_query ? (
                  <p className="muted-text">改写后的主查询：{queryPlan.rewritten_query}</p>
                ) : null}
                {queryPlan.retrieval_queries && queryPlan.retrieval_queries.length > 0 ? (
                  <p className="muted-text">多路检索查询：{queryPlan.retrieval_queries.join(" ｜ ")}</p>
                ) : null}
                {queryPlan.web_search_queries && queryPlan.web_search_queries.length > 0 ? (
                  <p className="muted-text">网络扩词查询：{queryPlan.web_search_queries.join(" ｜ ")}</p>
                ) : null}
                {queryPlan.profile_update_hints.length > 0 ? (
                  <p className="muted-text">
                    画像候选字段：{queryPlan.profile_update_hints.join("、")}
                  </p>
                ) : null}
                {queryPlan.career_update_hints.length > 0 ? (
                  <p className="muted-text">
                    动态状态候选字段：{queryPlan.career_update_hints.join("、")}
                  </p>
                ) : null}
              </article>
            ) : null}

            {attachments && attachments.length > 0 ? (
              <div className="routing-box">
                <h3>本轮附件已自动处理</h3>
                <pre>
                  {attachments
                    .map(
                      (attachment) =>
                        `${attachment.display_name} | ${attachment.attachment_kind} | ${attachment.extraction_kind} | ${attachment.text_length} chars${attachment.persisted_to_profile ? " | 已写入画像" : ""}${attachment.processing_error ? ` | 处理失败：${attachment.processing_error}` : ""}\n主要内容：${attachment.summary || "暂无摘要"}`,
                    )
                    .join("\n")}
                </pre>
              </div>
            ) : null}

            {memoryUpdate ? (
              <article className="panel panel-subtle">
                <h3>画像更新</h3>
                <p className="muted-text">
                  {memoryUpdate.applied ? "本轮已应用低风险更新。" : "本轮没有写入长期画像。"}
                </p>
                {memoryUpdate.profile_fields.length > 0 ? (
                  <p className="muted-text">Profile：{memoryUpdate.profile_fields.join("、")}</p>
                ) : null}
                {memoryUpdate.career_fields.length > 0 ? (
                  <p className="muted-text">Career State：{memoryUpdate.career_fields.join("、")}</p>
                ) : null}
                {memoryUpdate.notes.length > 0 ? (
                  <div className="result-stack">
                    {memoryUpdate.notes.map((value) => (
                      <p key={value} className="muted-text">
                        {value}
                      </p>
                    ))}
                  </div>
                ) : null}
              </article>
            ) : null}

            {supportingItemIds.length > 0 ? (
              <div className="tag-row">
                {supportingItemIds.map((value) => (
                  <span key={value} className="tag-chip">
                    {value}
                  </span>
                ))}
              </div>
            ) : null}

            {citations.length > 0 ? (
              <div className="result-stack">
                <h3>引用来源</h3>
                {citations.map((citation) => (
                  <article key={citation.doc_id} className="panel panel-subtle">
                    <p>
                      <strong>{citation.source_label}</strong>
                      {" · "}
                      score {citation.score.toFixed(3)}
                    </p>
                    <p className="muted-text">{citation.snippet}</p>
                  </article>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
    </main>
  );
}
