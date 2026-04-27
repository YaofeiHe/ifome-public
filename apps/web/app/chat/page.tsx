"use client";

import {
  ChangeEvent,
  ClipboardEvent,
  FormEvent,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  ChatQueryResponse,
  ChatSessionSummaryResponse,
  ChatSessionSummaryTurn,
  ItemListResponse,
  RenderedItemCard,
  apiRequest,
} from "../lib/api";

type AttachedFile = {
  id: string;
  file: File;
};

type ChatMode = "grounded_chat" | "boss_simulator";

type ConversationSummaryCard = {
  title: string;
  summary: string;
  keywords: string[];
  compressedTranscript: string;
  updatedAt: string;
  summarySource: string;
};

type ChatConversationTurn = {
  id: string;
  mode: ChatMode;
  createdAt: string;
  userMessage: string;
  answer: string;
  retrievalMode: string | null;
  queryPlan: ChatQueryResponse["query_plan"];
  memoryUpdate: ChatQueryResponse["memory_update"];
  attachments: ChatQueryResponse["attachments"];
  supportingItemIds: string[];
  citations: ChatQueryResponse["citations"];
  strategy?: string;
  guidancePrompt?: string;
  lastAdjustmentPrompt?: string;
};

type ChatConversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  mode: ChatMode;
  itemId: string;
  recentDays: number;
  applyMemoryUpdates: boolean;
  queryDraft: string;
  bossReplyRequirements: string;
  turns: ChatConversationTurn[];
  summaryCard: ConversationSummaryCard | null;
};

const CHAT_CONVERSATIONS_CACHE_KEY = "ifome:chat-conversations:v2";
const CHAT_ACTIVE_CONVERSATION_KEY = "ifome:chat-active-conversation:v2";

function createConversation(mode: ChatMode = "grounded_chat"): ChatConversation {
  const now = new Date().toISOString();
  return {
    id: `chat-conversation-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    title: mode === "boss_simulator" ? "新的 Boss 模拟" : "新的聊天对话",
    createdAt: now,
    updatedAt: now,
    mode,
    itemId: "",
    recentDays: 30,
    applyMemoryUpdates: true,
    queryDraft: mode === "boss_simulator" ? "" : "给我本周的 ddl",
    bossReplyRequirements: "",
    turns: [],
    summaryCard: null,
  };
}

function stripLeadingLabel(text: string, label: string) {
  return text.replace(new RegExp(`^${label}\\s*[：:]\\s*`), "").trim();
}

function parseBossAnswer(answer: string) {
  const normalized = answer.trim();
  const replyPattern = /(?:^|\n)建议回复\s*[：:]\s*/;
  const strategyPattern = /(?:^|\n)(?:回复策略|策略说明|回复思路)\s*[：:]\s*/;
  const replyMatch = normalized.match(replyPattern);
  const strategyMatch = normalized.match(strategyPattern);

  const replyStart =
    replyMatch && replyMatch.index !== undefined
      ? replyMatch.index + replyMatch[0].length
      : 0;
  const replyEnd =
    strategyMatch && strategyMatch.index !== undefined
      ? strategyMatch.index
      : normalized.length;
  const strategyStart =
    strategyMatch && strategyMatch.index !== undefined
      ? strategyMatch.index + strategyMatch[0].length
      : null;
  const replyText = stripLeadingLabel(
    normalized.slice(replyStart, replyEnd).trim() || normalized,
    "建议回复",
  );
  const strategy = strategyStart !== null
    ? normalized.slice(strategyStart).trim()
    : "这轮没有显式输出回复策略，建议结合语气和上下文再做一次人工确认。";

  return {
    replyText: replyText || normalized,
    strategy:
      strategy || "这轮没有显式输出回复策略，建议结合语气和上下文再做一次人工确认。",
  };
}

function buildBossSimulatorPrompt({
  currentMessage,
  history,
  replyRequirements,
  revisionPrompt,
  previousReply,
}: {
  currentMessage: string;
  history: ChatConversationTurn[];
  replyRequirements?: string;
  revisionPrompt?: string;
  previousReply?: string;
}) {
  const transcript = history.length
    ? history
        .slice(-12)
        .map(
          (turn, index) =>
            [
              `第 ${index + 1} 轮历史`,
              turn.mode === "boss_simulator"
                ? `Boss / HR：${turn.userMessage}`
                : `我提的问题：${turn.userMessage}`,
              `我上一轮得到的回复：${turn.answer}`,
              turn.strategy ? `当时的回复策略：${turn.strategy}` : null,
            ]
              .filter(Boolean)
              .join("\n"),
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
    "6. 如果给了回复要求或调整意见，要优先满足这些要求，但不要违背上下文。",
    "",
    "历史对话：",
    transcript,
    "",
    "当前收到的新消息：",
    currentMessage,
    "",
    "本轮回复要求：",
    replyRequirements?.trim() || "无额外要求，默认自然、专业、可直接发送。",
    "",
    "上一版回复：",
    previousReply?.trim() || "无",
    "",
    "对上一版的调整意见：",
    revisionPrompt?.trim() || "无",
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

function buildConversationTurnSummary(turn: ChatConversationTurn) {
  const inputLabel = turn.mode === "boss_simulator" ? "Boss" : "问题";
  const outputLabel = turn.mode === "boss_simulator" ? "回复" : "回答";
  const inputPreview = turn.userMessage.replace(/\s+/g, " ").trim().slice(0, 24);
  const outputPreview = turn.answer.replace(/\s+/g, " ").trim().slice(0, 24);
  return `${inputLabel}：${inputPreview || "未填写"} / ${outputLabel}：${outputPreview || "未生成"}`;
}

function formatTimestamp(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

export default function ChatPage() {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const restoredConversationIdRef = useRef<string | null>(null);
  const [items, setItems] = useState<RenderedItemCard[]>([]);
  const [conversations, setConversations] = useState<ChatConversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [selectedConversationIds, setSelectedConversationIds] = useState<string[]>([]);
  const [expandedConversationIds, setExpandedConversationIds] = useState<string[]>([]);
  const [expandedTurnIds, setExpandedTurnIds] = useState<string[]>([]);
  const [expandedStrategyTurnIds, setExpandedStrategyTurnIds] = useState<string[]>([]);
  const [query, setQuery] = useState("给我本周的 ddl");
  const [mode, setMode] = useState<ChatMode>("grounded_chat");
  const [itemId, setItemId] = useState("");
  const [recentDays, setRecentDays] = useState(30);
  const [applyMemoryUpdates, setApplyMemoryUpdates] = useState(true);
  const [bossReplyRequirements, setBossReplyRequirements] = useState("");
  const [attachedFiles, setAttachedFiles] = useState<AttachedFile[]>([]);
  const [bossAdjustmentPrompts, setBossAdjustmentPrompts] = useState<Record<string, string>>({});
  const [copiedTurnId, setCopiedTurnId] = useState<string | null>(null);
  const [pendingSummaryConversationIds, setPendingSummaryConversationIds] = useState<string[]>([]);
  const [pendingTurnId, setPendingTurnId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const activeConversation = useMemo(
    () => conversations.find((conversation) => conversation.id === activeConversationId) ?? null,
    [conversations, activeConversationId],
  );

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
      const cachedConversations = window.localStorage.getItem(CHAT_CONVERSATIONS_CACHE_KEY);
      const cachedActiveId = window.localStorage.getItem(CHAT_ACTIVE_CONVERSATION_KEY);
      if (!cachedConversations) {
        const initial = createConversation();
        setConversations([initial]);
        setActiveConversationId(initial.id);
        return;
      }
      const parsed = JSON.parse(cachedConversations) as ChatConversation[];
      if (!Array.isArray(parsed) || parsed.length === 0) {
        const initial = createConversation();
        setConversations([initial]);
        setActiveConversationId(initial.id);
        return;
      }
      setConversations(parsed);
      const activeId = parsed.some((conversation) => conversation.id === cachedActiveId)
        ? cachedActiveId
        : parsed[0].id;
      setActiveConversationId(activeId);
      setExpandedConversationIds([activeId].filter(Boolean) as string[]);
    } catch {
      const initial = createConversation();
      setConversations([initial]);
      setActiveConversationId(initial.id);
    }
  }, []);

  useEffect(() => {
    if (conversations.length === 0) {
      return;
    }
    try {
      window.localStorage.setItem(CHAT_CONVERSATIONS_CACHE_KEY, JSON.stringify(conversations));
      if (activeConversationId) {
        window.localStorage.setItem(CHAT_ACTIVE_CONVERSATION_KEY, activeConversationId);
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
    setMode(activeConversation.mode);
    setItemId(activeConversation.itemId);
    setRecentDays(activeConversation.recentDays);
    setApplyMemoryUpdates(activeConversation.applyMemoryUpdates);
    setQuery(activeConversation.queryDraft);
    setBossReplyRequirements(activeConversation.bossReplyRequirements);
    if (activeConversation.turns.length > 0) {
      setExpandedTurnIds([activeConversation.turns[activeConversation.turns.length - 1].id]);
    } else {
      setExpandedTurnIds([]);
    }
  }, [activeConversation]);

  useEffect(() => {
    if (!activeConversationId) {
      return;
    }
    setConversations((current) => {
      let changed = false;
      const nextConversations = current.map((conversation) => {
        if (conversation.id !== activeConversationId) {
          return conversation;
        }
        if (
          conversation.mode === mode &&
          conversation.itemId === itemId &&
          conversation.recentDays === recentDays &&
          conversation.applyMemoryUpdates === applyMemoryUpdates &&
          conversation.queryDraft === query &&
          conversation.bossReplyRequirements === bossReplyRequirements
        ) {
          return conversation;
        }
        changed = true;
        return {
          ...conversation,
          mode,
          itemId,
          recentDays,
          applyMemoryUpdates,
          queryDraft: query,
          bossReplyRequirements,
        };
      });
      return changed ? nextConversations : current;
    });
  }, [
    mode,
    itemId,
    recentDays,
    applyMemoryUpdates,
    query,
    bossReplyRequirements,
    activeConversationId,
  ]);

  useEffect(() => {
    const staleConversations = conversations.filter(
      (conversation) =>
        conversation.id !== activeConversationId &&
        conversation.turns.length > 0 &&
        conversation.updatedAt !== conversation.summaryCard?.updatedAt &&
        !pendingSummaryConversationIds.includes(conversation.id),
    );
    staleConversations.forEach((conversation) => {
      void summarizeConversation(conversation);
    });
  }, [conversations, activeConversationId, pendingSummaryConversationIds]);

  function updateConversation(
    conversationId: string,
    updater: (conversation: ChatConversation) => ChatConversation,
  ) {
    setConversations((current) =>
      current.map((conversation) =>
        conversation.id === conversationId ? updater(conversation) : conversation,
      ),
    );
  }

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

  async function summarizeConversation(conversation: ChatConversation) {
    if (conversation.turns.length === 0) {
      return;
    }
    setPendingSummaryConversationIds((current) =>
      current.includes(conversation.id) ? current : [...current, conversation.id],
    );
    try {
      const response = await apiRequest<ChatSessionSummaryResponse>("/chat/session-summary", {
        method: "POST",
        body: JSON.stringify({
          mode: conversation.mode,
          conversation_title: conversation.title,
          turns: conversation.turns.map<ChatSessionSummaryTurn>((turn) => ({
            mode: turn.mode,
            user_message: turn.userMessage,
            answer: turn.answer,
            strategy: turn.strategy ?? null,
          })),
        }),
      });
      updateConversation(conversation.id, (current) => ({
        ...current,
        title: response.data.title || current.title,
        summaryCard: {
          title: response.data.title,
          summary: response.data.summary,
          keywords: response.data.keywords,
          compressedTranscript: response.data.compressed_transcript,
          updatedAt: current.updatedAt,
          summarySource: response.data.summary_source,
        },
      }));
    } catch {
      return;
    } finally {
      setPendingSummaryConversationIds((current) =>
        current.filter((value) => value !== conversation.id),
      );
    }
  }

  async function activateConversation(nextConversationId: string) {
    if (activeConversation && activeConversation.id !== nextConversationId) {
      await summarizeConversation(activeConversation);
    }
    setActiveConversationId(nextConversationId);
    setExpandedConversationIds((current) =>
      current.includes(nextConversationId) ? current : [...current, nextConversationId],
    );
    setAttachedFiles([]);
    setError(null);
    setCopiedTurnId(null);
  }

  async function createNewConversation(targetMode?: ChatMode) {
    if (activeConversation) {
      await summarizeConversation(activeConversation);
    }
    const nextConversation = createConversation(targetMode ?? mode);
    setConversations((current) => [nextConversation, ...current]);
    setActiveConversationId(nextConversation.id);
    setExpandedConversationIds([nextConversation.id]);
    setExpandedTurnIds([]);
    setAttachedFiles([]);
    setBossAdjustmentPrompts({});
    setQuery(nextConversation.queryDraft);
    setBossReplyRequirements(nextConversation.bossReplyRequirements);
    setMode(nextConversation.mode);
    setItemId(nextConversation.itemId);
    setRecentDays(nextConversation.recentDays);
    setApplyMemoryUpdates(nextConversation.applyMemoryUpdates);
  }

  function deleteConversation(conversationId: string) {
    setConversations((current) => {
      const remaining = current.filter((conversation) => conversation.id !== conversationId);
      if (remaining.length === 0) {
        const nextConversation = createConversation();
        setActiveConversationId(nextConversation.id);
        return [nextConversation];
      }
      if (activeConversationId === conversationId) {
        setActiveConversationId(remaining[0].id);
      }
      return remaining;
    });
    setExpandedConversationIds((current) => current.filter((value) => value !== conversationId));
    setSelectedConversationIds((current) => current.filter((value) => value !== conversationId));
  }

  function deleteSelectedConversations() {
    if (selectedConversationIds.length === 0) {
      return;
    }
    const targets = new Set(selectedConversationIds);
    setConversations((current) => {
      const remaining = current.filter((conversation) => !targets.has(conversation.id));
      if (remaining.length === 0) {
        const nextConversation = createConversation();
        setActiveConversationId(nextConversation.id);
        setExpandedConversationIds([nextConversation.id]);
        return [nextConversation];
      }
      if (activeConversationId && targets.has(activeConversationId)) {
        setActiveConversationId(remaining[0].id);
      }
      return remaining;
    });
    setExpandedConversationIds((current) => current.filter((value) => !targets.has(value)));
    setSelectedConversationIds([]);
  }

  function toggleConversationSelection(conversationId: string) {
    setSelectedConversationIds((current) =>
      current.includes(conversationId)
        ? current.filter((value) => value !== conversationId)
        : [...current, conversationId],
    );
  }

  function deleteTurn(turnId: string) {
    if (!activeConversation) {
      return;
    }
    updateConversation(activeConversation.id, (conversation) => ({
      ...conversation,
      turns: conversation.turns.filter((turn) => turn.id !== turnId),
      updatedAt: new Date().toISOString(),
      summaryCard: null,
    }));
    setExpandedTurnIds((current) => current.filter((value) => value !== turnId));
    setExpandedStrategyTurnIds((current) => current.filter((value) => value !== turnId));
    setBossAdjustmentPrompts((current) => {
      const next = { ...current };
      delete next[turnId];
      return next;
    });
  }

  function toggleConversation(conversationId: string) {
    setExpandedConversationIds((current) =>
      current.includes(conversationId)
        ? current.filter((value) => value !== conversationId)
        : [...current, conversationId],
    );
  }

  function toggleTurn(turnId: string) {
    setExpandedTurnIds((current) =>
      current.includes(turnId) ? current.filter((value) => value !== turnId) : [...current, turnId],
    );
  }

  function toggleStrategy(turnId: string) {
    setExpandedStrategyTurnIds((current) =>
      current.includes(turnId) ? current.filter((value) => value !== turnId) : [...current, turnId],
    );
  }

  async function submitChatTurn({
    requestQuery,
    userVisibleMessage,
    replaceTurnId,
    historyForBossPrompt,
    adjustmentPrompt,
  }: {
    requestQuery: string;
    userVisibleMessage: string;
    replaceTurnId?: string;
    historyForBossPrompt?: ChatConversationTurn[];
    adjustmentPrompt?: string;
  }) {
    if (!activeConversation) {
      return;
    }
    setPending(true);
    setPendingTurnId(replaceTurnId ?? null);
    setError(null);
    setCopiedTurnId(null);

    try {
      const formData = new FormData();
      formData.append("query", requestQuery);
      formData.append("recent_days", String(recentDays));
      formData.append("apply_memory_updates", String(applyMemoryUpdates));
      if (itemId) {
        formData.append("item_id", itemId);
      }
      if (!replaceTurnId) {
        attachedFiles.forEach(({ file }) => {
          formData.append("files", file);
        });
      }

      const response = await apiRequest<ChatQueryResponse>("/chat/query-unified", {
        method: "POST",
        body: formData,
      });

      const now = new Date().toISOString();
      const nextTurnId = replaceTurnId ?? `chat-turn-${Date.now()}`;
      let nextTurn: ChatConversationTurn;
      if (mode === "boss_simulator") {
        const parsedAnswer = parseBossAnswer(response.data.answer);
        nextTurn = {
          id: nextTurnId,
          mode,
          createdAt: now,
          userMessage: userVisibleMessage,
          answer: parsedAnswer.replyText,
          retrievalMode: response.data.retrieval_mode,
          queryPlan: response.data.query_plan ?? null,
          memoryUpdate: response.data.memory_update ?? null,
          attachments: response.data.attachments ?? [],
          supportingItemIds: response.data.supporting_item_ids,
          citations: response.data.citations,
          strategy: parsedAnswer.strategy,
          guidancePrompt: bossReplyRequirements.trim(),
          lastAdjustmentPrompt: adjustmentPrompt,
        };
      } else {
        nextTurn = {
          id: nextTurnId,
          mode,
          createdAt: now,
          userMessage: userVisibleMessage,
          answer: response.data.answer,
          retrievalMode: response.data.retrieval_mode,
          queryPlan: response.data.query_plan ?? null,
          memoryUpdate: response.data.memory_update ?? null,
          attachments: response.data.attachments ?? [],
          supportingItemIds: response.data.supporting_item_ids,
          citations: response.data.citations,
        };
      }

      updateConversation(activeConversation.id, (conversation) => {
        const nextTurns = replaceTurnId
          ? conversation.turns.map((turn) => (turn.id === replaceTurnId ? nextTurn : turn))
          : [...conversation.turns, nextTurn];
        return {
          ...conversation,
          mode,
          updatedAt: now,
          queryDraft: "",
          turns: nextTurns,
          summaryCard: null,
        };
      });
      setExpandedTurnIds([nextTurn.id]);
      setAttachedFiles([]);
      setQuery("");
      if (mode === "boss_simulator" && historyForBossPrompt) {
        setBossAdjustmentPrompts((current) => {
          const next = { ...current };
          delete next[nextTurn.id];
          return next;
        });
      }
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "聊天查询失败。",
      );
    } finally {
      setPending(false);
      setPendingTurnId(null);
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeConversation) {
      return;
    }
    const visibleBossMessage = buildVisibleBossMessage(query, attachedFiles);
    const submittedQuery =
      mode === "boss_simulator"
        ? buildBossSimulatorPrompt({
            currentMessage: visibleBossMessage,
            history: activeConversation.turns,
            replyRequirements: bossReplyRequirements,
          })
        : query;
    await submitChatTurn({
      requestQuery: submittedQuery,
      userVisibleMessage: mode === "boss_simulator" ? visibleBossMessage : query,
    });
  }

  async function refineBossTurn(turnId: string) {
    if (!activeConversation) {
      return;
    }
    const targetIndex = activeConversation.turns.findIndex((turn) => turn.id === turnId);
    if (targetIndex < 0) {
      return;
    }
    const targetTurn = activeConversation.turns[targetIndex];
    const adjustmentPrompt = (bossAdjustmentPrompts[turnId] || "").trim();
    await submitChatTurn({
      requestQuery: buildBossSimulatorPrompt({
        currentMessage: targetTurn.userMessage,
        history: activeConversation.turns.slice(0, targetIndex),
        replyRequirements: bossReplyRequirements || targetTurn.guidancePrompt,
        revisionPrompt: adjustmentPrompt,
        previousReply: targetTurn.answer,
      }),
      userVisibleMessage: targetTurn.userMessage,
      replaceTurnId: turnId,
      historyForBossPrompt: activeConversation.turns.slice(0, targetIndex),
      adjustmentPrompt,
    });
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
        <h1>一个聊天控制台，同时兼容提问、画像更新、历史会话和 Boss 回复模拟</h1>
        <p className="intro">
          这里和输入页使用同一类统一输入方式。你可以直接粘贴文本、链接、在框里写本地路径，
          也可以上传或粘贴图片、PDF、README、项目说明和简历；后端会先抽取文本，需要 OCR 时自动转写，
          再把整理后的文本同时用于检索回答、画像更新、项目画像构建和 Boss 沟通建议。现在每个对话都会单独缓存，
          关闭页面后也能恢复输入和输出，旧会话会额外生成压缩摘要，降低重启后的恢复成本。
        </p>
      </section>

      <section className="panel conversation-history-panel">
        <div className="conversation-toolbar">
          <div>
            <h2>对话列表</h2>
            <p className="muted-text">
              新建对话会保留当前会话缓存；切回旧会话后，可以继续沿着原来的历史接着聊。
            </p>
          </div>
          <button
            type="button"
            className="primary-button"
            onClick={() => void createNewConversation()}
          >
            创建新对话
          </button>
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
            const expanded = expandedConversationIds.includes(conversation.id);
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
                    onClick={() => toggleConversation(conversation.id)}
                  >
                    {expanded ? "收起" : "展开"} · {conversation.title}
                  </button>
                  <div className="metric-row">
                    <span className="metric-chip">
                      {conversation.mode === "boss_simulator" ? "Boss 模拟" : "聊天问答"}
                    </span>
                    <button
                      type="button"
                      className={`segment ${isActive ? "segment-active" : ""}`}
                      onClick={() => void activateConversation(conversation.id)}
                    >
                      {isActive ? "当前对话" : "继续对话"}
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

                <p className="muted-text">
                  最近更新：{formatTimestamp(conversation.updatedAt)} · {conversation.turns.length} 轮
                </p>

                {conversation.summaryCard ? (
                  <div className="conversation-summary-box">
                    <p>{conversation.summaryCard.summary}</p>
                    {conversation.summaryCard.keywords.length > 0 ? (
                      <div className="tag-row">
                        {conversation.summaryCard.keywords.map((keyword) => (
                          <span key={`${conversation.id}-${keyword}`} className="tag-chip">
                            {keyword}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : conversation.turns.length > 0 ? (
                  <p className="muted-text">
                    {pendingSummaryConversationIds.includes(conversation.id)
                      ? "正在压缩旧会话摘要..."
                      : buildConversationTurnSummary(conversation.turns[conversation.turns.length - 1])}
                  </p>
                ) : (
                  <p className="muted-text">这还是一个空白对话。</p>
                )}

                {expanded && conversation.summaryCard?.compressedTranscript ? (
                  <div className="routing-box">
                    <h3>压缩后的历史摘要</h3>
                    <pre>{conversation.summaryCard.compressedTranscript}</pre>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      </section>

      <section className="panel">
        <form className="stack-form" onSubmit={onSubmit}>
          <div className="conversation-toolbar">
            <div>
              <h2>{mode === "boss_simulator" ? "Boss 对话框" : "聊天问答框"}</h2>
              <p className="muted-text">当前对话会持续缓存；需要另起主题时可以直接创建新对话。</p>
            </div>
            <button
              type="button"
              className="segment"
              onClick={() => void createNewConversation()}
            >
              创建新对话
            </button>
          </div>
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

          {mode === "boss_simulator" ? (
            <label className="field">
              <span>回答提示 / 回复要求</span>
              <textarea
                rows={4}
                value={bossReplyRequirements}
                onChange={(event) => setBossReplyRequirements(event.target.value)}
                placeholder="例如：更像微信聊天语气、回复简短一点、强调我下周一前可以安排、别太强势。"
              />
            </label>
          ) : null}

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
            {pending && !pendingTurnId
              ? "处理中..."
              : mode === "boss_simulator"
                ? "生成回复"
                : "发送问题"}
          </button>
        </form>
      </section>

      <section className="panel">
        <h2>当前对话历史</h2>
        {error ? <p className="error-text">{error}</p> : null}
        {!activeConversation || activeConversation.turns.length === 0 ? (
          <p className="muted-text">
            提交后，这里会把当前对话的输入和输出收成可展开的历史列表；切换会话或关闭页面后也会保留。
          </p>
        ) : (
          <div className="chat-history-list">
            {activeConversation.turns.map((turn, turnIndex) => {
              const expanded = expandedTurnIds.includes(turn.id);
              const round = turnIndex + 1;
              return (
                <article key={turn.id} className="chat-history-card">
                  <div className="chat-history-summary">
                    <button
                      type="button"
                      className="segment chat-history-toggle"
                      onClick={() => toggleTurn(turn.id)}
                    >
                      {expanded ? "收起" : "展开"} 第 {round} 轮 · {buildConversationTurnSummary(turn)}
                    </button>
                    <div className="metric-row">
                      <span className="metric-chip">{formatTimestamp(turn.createdAt)}</span>
                      <button
                        type="button"
                        className="segment"
                        onClick={() => deleteTurn(turn.id)}
                      >
                        删除
                      </button>
                    </div>
                  </div>

                  {expanded ? (
                    turn.mode === "boss_simulator" ? (
                      <div className="chat-simulator-thread">
                        <div className="chat-turn">
                          <article className="chat-bubble chat-bubble-boss">
                            <p className="workspace-kicker">Boss / HR</p>
                            <p>{turn.userMessage}</p>
                          </article>
                          <article className="chat-bubble chat-bubble-agent">
                            <div className="chat-bubble-header">
                              <p className="workspace-kicker">建议回复</p>
                              <button
                                type="button"
                                className="segment"
                                onClick={() => void copyReply(turn.answer, turn.id)}
                              >
                                {copiedTurnId === turn.id ? "已复制" : "复制回复"}
                              </button>
                            </div>
                            <p>{turn.answer}</p>
                          </article>
                          <div className="chat-feedback-box">
                            <label className="field">
                              <span>这轮回复评价 / 调整提示词</span>
                              <textarea
                                rows={3}
                                value={bossAdjustmentPrompts[turn.id] ?? turn.lastAdjustmentPrompt ?? ""}
                                onChange={(event) =>
                                  setBossAdjustmentPrompts((current) => ({
                                    ...current,
                                    [turn.id]: event.target.value,
                                  }))
                                }
                                placeholder="例如：再口语一点、补一句我明天下午也有空、弱化催促感。"
                              />
                            </label>
                            <div className="chat-feedback-actions">
                              <p className="muted-text">
                                这轮回答要求：{turn.guidancePrompt || "无额外要求"}
                              </p>
                              <button
                                type="button"
                                className="primary-button"
                                disabled={pending}
                                onClick={() => void refineBossTurn(turn.id)}
                              >
                                {pendingTurnId === turn.id ? "调整中..." : "根据评价重生成"}
                              </button>
                            </div>
                          </div>
                          <button
                            type="button"
                            className="segment chat-strategy-toggle"
                            onClick={() => toggleStrategy(turn.id)}
                          >
                            {expandedStrategyTurnIds.includes(turn.id)
                              ? "收起回复策略和分析"
                              : "展开回复策略和分析"}
                          </button>
                          {expandedStrategyTurnIds.includes(turn.id) ? (
                            <div className="chat-strategy-box">
                              <p className="workspace-kicker">回复策略</p>
                              <p>{turn.strategy || "暂无策略说明。"}</p>
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ) : (
                      <div className="result-stack">
                        <article className="chat-bubble chat-bubble-boss">
                          <p className="workspace-kicker">我的问题</p>
                          <p>{turn.userMessage}</p>
                        </article>
                        <article className="panel panel-subtle">
                          <h3>回答</h3>
                          <p className="answer-box">{turn.answer}</p>
                          {turn.retrievalMode ? (
                            <p className="muted-text">检索模式：{turn.retrievalMode}</p>
                          ) : null}
                          {turn.queryPlan ? (
                            <div className="result-stack">
                              <p className="muted-text">
                                意图：{turn.queryPlan.intent} · 时间窗口：{turn.queryPlan.recent_days} 天
                              </p>
                              {turn.queryPlan.rewritten_query ? (
                                <p className="muted-text">
                                  改写后的主查询：{turn.queryPlan.rewritten_query}
                                </p>
                              ) : null}
                              {turn.queryPlan.retrieval_queries &&
                              turn.queryPlan.retrieval_queries.length > 0 ? (
                                <p className="muted-text">
                                  多路检索查询：{turn.queryPlan.retrieval_queries.join(" ｜ ")}
                                </p>
                              ) : null}
                            </div>
                          ) : null}
                          {(turn.attachments ?? []).length > 0 ? (
                            <div className="routing-box">
                              <h3>本轮附件</h3>
                              <pre>
                                {(turn.attachments ?? [])
                                  .map(
                                    (attachment) =>
                                      `${attachment.display_name} | ${attachment.attachment_kind} | ${attachment.extraction_kind} | ${attachment.text_length} chars${attachment.persisted_to_profile ? " | 已写入画像" : ""}${attachment.processing_error ? ` | 处理失败：${attachment.processing_error}` : ""}\n主要内容：${attachment.summary || "暂无摘要"}`,
                                  )
                                  .join("\n")}
                              </pre>
                            </div>
                          ) : null}
                          {turn.memoryUpdate ? (
                            <div className="result-stack">
                              <p className="muted-text">
                                {turn.memoryUpdate.applied
                                  ? "本轮已应用低风险画像更新。"
                                  : "本轮没有写入长期画像。"}
                              </p>
                              {(turn.memoryUpdate.notes ?? []).map((note) => (
                                <p key={note} className="muted-text">
                                  {note}
                                </p>
                              ))}
                            </div>
                          ) : null}
                          {(turn.citations ?? []).length > 0 ? (
                            <div className="result-stack">
                              <h3>引用来源</h3>
                              {(turn.citations ?? []).map((citation) => (
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
                        </article>
                      </div>
                    )
                  ) : null}
                </article>
              );
            })}
          </div>
        )}
      </section>
    </main>
  );
}
