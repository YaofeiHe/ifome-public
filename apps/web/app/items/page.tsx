"use client";

import { type MouseEvent, useDeferredValue, useEffect, useMemo, useState } from "react";

import {
  BatchAnalyzeItemsResponse,
  BatchDeleteItemsResponse,
  ItemDetailResponse,
  ItemListResponse,
  MarketRefreshResponse,
  ReminderListResponse,
  RenderedItemCard,
  apiRequest,
} from "../lib/api";
import { MARKET_REFRESH_EVENT } from "../components/market-refresh-bootstrap";

type EditDraft = {
  summary_one_line: string;
  company: string;
  role: string;
  city: string;
  tags: string;
  priority: string;
  content_category: string;
};

function createDraft(item: RenderedItemCard): EditDraft {
  return {
    summary_one_line: item.summary_one_line,
    company: item.company || "",
    role: item.role || "",
    city: item.city || "",
    tags: item.tags.join(", "),
    priority: item.priority || "",
    content_category: item.content_category,
  };
}

function getTimeLabel(item: RenderedItemCard) {
  if (item.content_category === "interview_notice") {
    return ["面试时间", item.interview_time || "无"];
  }
  if (item.content_category === "talk_event") {
    return ["活动时间", item.event_time || "无"];
  }
  return ["DDL", item.ddl || "无"];
}

function getLocationLabel(item: RenderedItemCard) {
  if (item.city && item.location_note) {
    return `${item.city}（${item.location_note}）`;
  }
  return item.city || item.location_note || "待识别";
}

function looksLikeUrl(value: string | null | undefined) {
  return Boolean(value && /^https?:\/\//i.test(value));
}

function getSourceFileHref(itemId: string) {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
  return `${apiBaseUrl}/items/${itemId}/source-file`;
}

function isMarketItem(item: RenderedItemCard) {
  return item.is_market_signal || item.content_category === "general_update";
}

function isMarketChildItem(item: RenderedItemCard) {
  return isMarketItem(item) && item.market_group_kind === "article" && Boolean(item.market_parent_item_id);
}

function isJobChildItem(item: RenderedItemCard) {
  return item.job_group_kind === "role" && Boolean(item.job_parent_item_id);
}

function getMarketPreviewCount(
  item: RenderedItemCard,
  childrenByParent: Map<string, RenderedItemCard[]>,
) {
  const loadedChildren = childrenByParent.get(item.item_id)?.length || 0;
  return Math.max(
    loadedChildren,
    item.market_child_item_ids.length,
    item.market_child_previews.length,
  );
}

function getJobPreviewCount(
  item: RenderedItemCard,
  childrenByParent: Map<string, RenderedItemCard[]>,
) {
  const loadedChildren = childrenByParent.get(item.item_id)?.length || 0;
  return Math.max(
    loadedChildren,
    item.job_child_item_ids.length,
    item.job_child_previews.length,
  );
}

function getOrderedChildCards(
  item: RenderedItemCard,
  itemMap: Map<string, RenderedItemCard>,
  childrenByParent: Map<string, RenderedItemCard[]>,
) {
  const explicitChildren: RenderedItemCard[] = [];
  const explicitIds = new Set<string>();
  const childIds = isMarketItem(item)
    ? item.market_child_item_ids || []
    : item.job_child_item_ids || [];
  for (const childId of childIds) {
    const child = itemMap.get(childId);
    if (!child) {
      continue;
    }
    explicitChildren.push(child);
    explicitIds.add(child.item_id);
  }
  const inferredChildren = (childrenByParent.get(item.item_id) || []).filter(
    (child) => !explicitIds.has(child.item_id),
  );
  return [...explicitChildren, ...inferredChildren];
}

function collectRelatedItemIds(itemIds: string[], items: RenderedItemCard[]) {
  const relatedIds = new Set<string>();
  const itemMap = new Map(items.map((item) => [item.item_id, item]));

  for (const itemId of itemIds) {
    relatedIds.add(itemId);
    const target = itemMap.get(itemId);
    if (!target) {
      continue;
    }
    for (const childItemId of target.market_child_item_ids || []) {
      relatedIds.add(childItemId);
    }
    for (const childItemId of target.job_child_item_ids || []) {
      relatedIds.add(childItemId);
    }
  }

  return Array.from(relatedIds);
}

function formatTime(value: string | null | undefined) {
  if (!value) {
    return "无";
  }
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) {
    return value;
  }
  const year = parsed.getFullYear();
  const month = String(parsed.getMonth() + 1).padStart(2, "0");
  const day = String(parsed.getDate()).padStart(2, "0");
  const hour = String(parsed.getHours()).padStart(2, "0");
  const minute = String(parsed.getMinutes()).padStart(2, "0");
  const second = String(parsed.getSeconds()).padStart(2, "0");
  return `${year}年${month}月${day}日 ${hour}:${minute}:${second}`;
}

function getSortTimestamp(item: RenderedItemCard) {
  return item.ddl || item.interview_time || item.event_time || item.updated_at || "";
}

function getSortTimeValue(item: RenderedItemCard) {
  const value = getSortTimestamp(item);
  if (!value) {
    return Number.MAX_SAFE_INTEGER;
  }
  const parsed = new Date(value).getTime();
  return Number.isFinite(parsed) ? parsed : Number.MAX_SAFE_INTEGER;
}

export default function ItemsPage() {
  const [visibleSection, setVisibleSection] = useState<"activity" | "market">("activity");
  const [items, setItems] = useState<RenderedItemCard[]>([]);
  const [selectedItemIds, setSelectedItemIds] = useState<string[]>([]);
  const [detailItem, setDetailItem] = useState<ItemDetailResponse["item"] | null>(null);
  const [detailDialogStyle, setDetailDialogStyle] = useState<Record<string, string> | null>(null);
  const [reminderCount, setReminderCount] = useState(0);
  const [query, setQuery] = useState("");
  const [analysisPrompt, setAnalysisPrompt] = useState("");
  const [marketLinkInput, setMarketLinkInput] = useState("");
  const [marketRefreshMessage, setMarketRefreshMessage] = useState<string | null>(null);
  const [expandedMarketIds, setExpandedMarketIds] = useState<string[]>([]);
  const [expandedJobIds, setExpandedJobIds] = useState<string[]>([]);
  const [batchAnalysis, setBatchAnalysis] = useState<BatchAnalyzeItemsResponse | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [deletingBatch, setDeletingBatch] = useState(false);
  const [analyzingBatch, setAnalyzingBatch] = useState(false);
  const [refreshingMarket, setRefreshingMarket] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const deferredQuery = useDeferredValue(query);

  async function loadDashboardData() {
    const [itemsResponse, remindersResponse] = await Promise.all([
      apiRequest<ItemListResponse>("/items"),
      apiRequest<ReminderListResponse>("/reminders"),
    ]);
    setItems(itemsResponse.data.items);
    setReminderCount(remindersResponse.data.reminders.length);
  }

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        await loadDashboardData();
      } catch (requestError) {
        setError(
          requestError instanceof Error ? requestError.message : "读取列表失败，请稍后重试。",
        );
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  useEffect(() => {
    async function onAutoRefresh(event: Event) {
      const customEvent = event as CustomEvent<{ reason?: string }>;
      try {
        await loadDashboardData();
        setMarketRefreshMessage(customEvent.detail?.reason || "已完成本轮市场信息刷新。");
      } catch {
        return;
      }
    }

    window.addEventListener(MARKET_REFRESH_EVENT, onAutoRefresh as EventListener);
    return () => {
      window.removeEventListener(MARKET_REFRESH_EVENT, onAutoRefresh as EventListener);
    };
  }, []);

  useEffect(() => {
    if (!detailItem) {
      return;
    }

    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setDetailItem(null);
        setDetailDialogStyle(null);
      }
    }

    function onResize() {
      setDetailDialogStyle(null);
    }

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
    };
  }, [detailItem]);

  const filteredItems = useMemo(() => {
    const normalized = deferredQuery.trim().toLowerCase();
    if (!normalized) {
      return items;
    }
    return items.filter((item) =>
      [
        item.summary_one_line,
        item.company,
        item.role,
        item.city,
        item.priority,
        item.content_category,
        item.source_type,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
        .includes(normalized),
    );
  }, [deferredQuery, items]);

  const activityItems = useMemo(
    () =>
      filteredItems
        .filter((item) => !isMarketItem(item) && !isJobChildItem(item))
        .sort((left, right) => getSortTimeValue(left) - getSortTimeValue(right)),
    [filteredItems],
  );

  const jobChildrenByParent = useMemo(() => {
    const mapping = new Map<string, RenderedItemCard[]>();
    for (const item of items) {
      if (!isJobChildItem(item) || !item.job_parent_item_id) {
        continue;
      }
      const current = mapping.get(item.job_parent_item_id) || [];
      current.push(item);
      mapping.set(item.job_parent_item_id, current);
    }
    for (const [key, value] of mapping.entries()) {
      value.sort((left, right) => getSortTimeValue(left) - getSortTimeValue(right));
      mapping.set(key, value);
    }
    return mapping;
  }, [items]);

  const itemMap = useMemo(
    () => new Map(items.map((item) => [item.item_id, item])),
    [items],
  );

  const marketItems = useMemo(
    () =>
      filteredItems
        .filter((item) => isMarketItem(item) && !isMarketChildItem(item))
        .sort((left, right) => {
          const scoreGap = (right.ai_score || 0) - (left.ai_score || 0);
          if (scoreGap !== 0) {
            return scoreGap;
          }
          return new Date(right.message_time || 0).getTime() - new Date(left.message_time || 0).getTime();
        }),
    [filteredItems],
  );

  const marketChildrenByParent = useMemo(() => {
    const mapping = new Map<string, RenderedItemCard[]>();
    for (const item of filteredItems) {
      if (!isMarketChildItem(item) || !item.market_parent_item_id) {
        continue;
      }
      const current = mapping.get(item.market_parent_item_id) || [];
      current.push(item);
      mapping.set(item.market_parent_item_id, current);
    }
    for (const [key, value] of mapping.entries()) {
      value.sort((left, right) => (right.ai_score || 0) - (left.ai_score || 0));
      mapping.set(key, value);
    }
    return mapping;
  }, [filteredItems]);

  const allFilteredSelected =
    (visibleSection === "activity" ? activityItems : marketItems).length > 0 &&
    (visibleSection === "activity" ? activityItems : marketItems).every((item) =>
      selectedItemIds.includes(item.item_id),
    );

  const visibleItems = visibleSection === "activity" ? activityItems : marketItems;

  async function onDelete(itemId: string) {
    setError(null);
    try {
      const targetItem = items.find((item) => item.item_id === itemId) || null;
      await apiRequest(`/items/${itemId}`, {
        method: "DELETE",
      });
      const hiddenChildIds = new Set(targetItem?.market_child_item_ids || []);
      for (const childId of targetItem?.job_child_item_ids || []) {
        hiddenChildIds.add(childId);
      }
      hiddenChildIds.add(itemId);
      setItems((current) => current.filter((item) => !hiddenChildIds.has(item.item_id)));
      setSelectedItemIds((current) => current.filter((value) => !hiddenChildIds.has(value)));
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "删除失败，请稍后重试。",
      );
    }
  }

  async function onBatchDelete() {
    if (selectedItemIds.length === 0) {
      return;
    }
    setDeletingBatch(true);
    setError(null);
    try {
      const relatedDeleteIds = collectRelatedItemIds(selectedItemIds, items);
      const response = await apiRequest<BatchDeleteItemsResponse>("/items/batch-delete", {
        method: "POST",
        body: JSON.stringify({
          item_ids: relatedDeleteIds,
        }),
      });
      const itemsResponse = await apiRequest<ItemListResponse>("/items");
      setItems(itemsResponse.data.items);
      setSelectedItemIds([]);
      setExpandedMarketIds((current) =>
        current.filter((itemId) => !response.data.deleted_item_ids.includes(itemId)),
      );
      setExpandedJobIds((current) =>
        current.filter((itemId) => !response.data.deleted_item_ids.includes(itemId)),
      );
      if (response.data.missing_item_ids.length > 0) {
        setError(`部分卡片未找到：${response.data.missing_item_ids.join("、")}`);
      }
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "批量删除失败，请稍后重试。",
      );
    } finally {
      setDeletingBatch(false);
    }
  }

  async function onBatchAnalyze() {
    if (selectedItemIds.length === 0) {
      return;
    }
    setAnalyzingBatch(true);
    setError(null);
    try {
      const response = await apiRequest<BatchAnalyzeItemsResponse>("/items/batch-analyze", {
        method: "POST",
        body: JSON.stringify({
          item_ids: selectedItemIds,
          question: analysisPrompt.trim() || null,
        }),
      });
      setBatchAnalysis(response.data);
      if (response.data.missing_item_ids.length > 0) {
        setError(`部分卡片未找到：${response.data.missing_item_ids.join("、")}`);
      }
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "批量分析失败，请稍后重试。",
      );
    } finally {
      setAnalyzingBatch(false);
    }
  }

  async function onRefreshMarket(force: boolean, inputLink?: string) {
    setRefreshingMarket(true);
    setError(null);
    try {
      const response = await apiRequest<MarketRefreshResponse>("/market/refresh", {
        method: "POST",
        body: JSON.stringify({
          force,
          input_link: inputLink || null,
        }),
      });
      await loadDashboardData();
      setMarketRefreshMessage(response.data.reason);
      if (inputLink) {
        setMarketLinkInput("");
      }
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "更新市场信息失败，请稍后重试。",
      );
    } finally {
      setRefreshingMarket(false);
    }
  }

  async function onSave(itemId: string) {
    if (!draft) {
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const response = await apiRequest<ItemDetailResponse>(`/items/${itemId}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...draft,
          priority: draft.priority || null,
          content_category: draft.content_category || null,
          tags: draft.tags
            .split(",")
            .map((value) => value.trim())
            .filter(Boolean),
        }),
      });
      const updatedCard = response.data.item.render_card;
      if (updatedCard) {
        setItems((current) =>
          current.map((item) => (item.item_id === itemId ? updatedCard : item)),
        );
      }
      setEditingId(null);
      setDraft(null);
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "保存失败，请稍后重试。",
      );
    } finally {
      setSaving(false);
    }
  }

  function buildDetailDialogStyle(cardRect: DOMRect) {
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    if (viewportWidth <= 760) {
      return {
        top: "50%",
        left: "50%",
        width: `min(${viewportWidth - 24}px, 560px)`,
        maxHeight: `${Math.max(280, viewportHeight - 48)}px`,
        transform: "translate(-50%, -50%)",
      };
    }

    const dialogWidth = Math.min(560, Math.max(360, viewportWidth * 0.34));
    const preferredLeft = cardRect.left + Math.min(48, Math.max(12, cardRect.width * 0.15));
    const left = Math.max(16, Math.min(preferredLeft, viewportWidth - dialogWidth - 16));
    const top = Math.max(16, Math.min(cardRect.top + 12, viewportHeight - 320));
    return {
      top: `${top}px`,
      left: `${left}px`,
      width: `${dialogWidth}px`,
      maxHeight: `${Math.max(280, viewportHeight - top - 20)}px`,
      transform: "none",
    };
  }

  async function onOpenDetail(itemId: string, event: MouseEvent<HTMLElement>) {
    setDetailLoading(true);
    setError(null);
    setDetailDialogStyle(buildDetailDialogStyle(event.currentTarget.getBoundingClientRect()));
    try {
      const response = await apiRequest<ItemDetailResponse>(`/items/${itemId}`);
      setDetailItem(response.data.item);
    } catch (requestError) {
      setDetailItem(null);
      setDetailDialogStyle(null);
      setError(
        requestError instanceof Error ? requestError.message : "读取详情失败，请稍后重试。",
      );
    } finally {
      setDetailLoading(false);
    }
  }

  return (
    <main className="dashboard-grid">
      <section className="hero panel panel-hero">
        <p className="eyebrow">Card List</p>
        <h1>把不同类型的信息整理成可维护的卡片</h1>
        <p className="intro">
          现在列表支持按信息类型组织展示，也支持手动编辑和删除。新卡片插入时，后端会先做相似度判断，重复内容会合并，同岗位更新会覆盖旧卡片。
        </p>
      </section>

      <section className="panel toolbar-panel">
        <label className="field compact-field">
          <span>筛选</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="按公司、岗位、地点、分类或来源筛选"
          />
        </label>
        <div className="metric-row">
          <span className="metric-chip">条目 {items.length}</span>
          <span className="metric-chip">提醒 {reminderCount}</span>
          <span className="metric-chip">命中 {filteredItems.length}</span>
          <span className="metric-chip">已选 {selectedItemIds.length}</span>
        </div>
      </section>

      <section className="panel">
        <h2>{visibleSection === "activity" ? "求职活动" : "市场信息"}</h2>
        {loading ? <p className="muted-text">正在读取条目...</p> : null}
        {detailLoading ? <p className="muted-text">正在读取卡片详情...</p> : null}
        {error ? <p className="error-text">{error}</p> : null}
        <div className="metric-row">
          <button
            type="button"
            className={`segment ${visibleSection === "activity" ? "segment-active" : ""}`}
            onClick={() => setVisibleSection("activity")}
          >
            求职活动
          </button>
          <button
            type="button"
            className={`segment ${visibleSection === "market" ? "segment-active" : ""}`}
            onClick={() => setVisibleSection("market")}
          >
            市场信息
          </button>
        </div>

        {visibleSection === "activity" && !loading && !error && activityItems.length === 0 ? (
          <p className="muted-text">当前没有可显示的求职活动条目，先去输入页提交一条数据。</p>
        ) : null}
        {visibleSection === "market" && !loading && !error && marketItems.length === 0 ? (
          <p className="muted-text">当前还没有市场信息卡，可以手动更新或等待定时检查。</p>
        ) : null}

        {visibleItems.length > 0 || visibleSection === "market" ? (
          <div className="batch-toolbar">
            <div className="checkbox-row">
              <input
                id="select-visible-items"
                type="checkbox"
                checked={allFilteredSelected}
                onChange={(event) => {
                  if (event.target.checked) {
                    setSelectedItemIds((current) =>
                      Array.from(new Set([...current, ...visibleItems.map((item) => item.item_id)])),
                    );
                    return;
                  }
                  const visibleIds = new Set(visibleItems.map((item) => item.item_id));
                  setSelectedItemIds((current) =>
                    current.filter((itemId) => !visibleIds.has(itemId)),
                  );
                }}
              />
              <label htmlFor="select-visible-items">全选当前筛选结果</label>
            </div>
            {visibleSection === "activity" ? (
              <>
                <label className="field compact-field batch-input">
                  <span>批量分析提示词</span>
                  <input
                    value={analysisPrompt}
                    onChange={(event) => setAnalysisPrompt(event.target.value)}
                    placeholder="可选：比如帮我比较这些岗位差异、DDL 和投递优先级"
                  />
                </label>
                <button
                  type="button"
                  className="segment"
                  disabled={selectedItemIds.length === 0 || analyzingBatch}
                  onClick={() => void onBatchAnalyze()}
                >
                  {analyzingBatch ? "分析中..." : `分析已选 ${selectedItemIds.length} 项`}
                </button>
                <button
                  type="button"
                  className="segment"
                  disabled={selectedItemIds.length === 0 || deletingBatch}
                  onClick={() => void onBatchDelete()}
                >
                  {deletingBatch ? "批量删除中..." : `删除已选 ${selectedItemIds.length} 项`}
                </button>
              </>
            ) : (
              <>
                <button
                  type="button"
                  className="primary-button"
                  disabled={refreshingMarket}
                  onClick={() => void onRefreshMarket(true)}
                >
                  {refreshingMarket ? "更新中..." : "更新每日关注网站"}
                </button>
                <label className="field compact-field batch-input">
                  <span>市场链接</span>
                  <input
                    value={marketLinkInput}
                    onChange={(event) => setMarketLinkInput(event.target.value)}
                    placeholder="输入一个链接，单独生成市场信息卡"
                  />
                </label>
                <button
                  type="button"
                  className="segment"
                  disabled={refreshingMarket || !marketLinkInput.trim()}
                  onClick={() => void onRefreshMarket(true, marketLinkInput.trim())}
                >
                  用链接更新
                </button>
                <button
                  type="button"
                  className="segment"
                  disabled={selectedItemIds.length === 0 || deletingBatch}
                  onClick={() => void onBatchDelete()}
                >
                  {deletingBatch ? "批量删除中..." : `删除已选 ${selectedItemIds.length} 项`}
                </button>
              </>
            )}
          </div>
        ) : null}

        {batchAnalysis ? (
          <div className="routing-box">
            <div className="card-header">
              <div>
                <h3>批量分析结果</h3>
                <p className="muted-text">
                  模式：{batchAnalysis.retrieval_mode}，已分析 {batchAnalysis.analyzed_item_ids.length} 张卡片
                </p>
              </div>
              <button
                type="button"
                className="segment"
                onClick={() => setBatchAnalysis(null)}
              >
                关闭
              </button>
            </div>
            <pre>{batchAnalysis.analysis}</pre>
          </div>
        ) : null}

        {visibleSection === "activity" ? (
        <div className="card-list">
          {activityItems.map((item) => {
            const [timeLabel, timeValue] = getTimeLabel(item);
            const isEditing = editingId === item.item_id && draft !== null;
            const childCards = getOrderedChildCards(item, itemMap, jobChildrenByParent);
            const previewCount = getJobPreviewCount(item, jobChildrenByParent);
            const showExpandButton =
              item.job_group_kind === "overview" || previewCount > 0;

            return (
              <article
                key={item.item_id}
                className="job-card clickable-card"
                onClick={(event) => void onOpenDetail(item.item_id, event)}
              >
                <div className="card-header">
                  <div className="metric-row">
                    <input
                      type="checkbox"
                      checked={selectedItemIds.includes(item.item_id)}
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => {
                        if (event.target.checked) {
                          setSelectedItemIds((current) => [...current, item.item_id]);
                          return;
                        }
                        setSelectedItemIds((current) =>
                          current.filter((value) => value !== item.item_id),
                        );
                      }}
                    />
                    <p className="card-summary">{item.summary_one_line}</p>
                  </div>
                  <div className="metric-row">
                    <span className="tag-chip">{item.content_category}</span>
                    {item.job_group_kind ? (
                      <span className="tag-chip">
                        {item.job_group_kind === "overview" ? "job_overview" : item.job_group_kind}
                      </span>
                    ) : null}
                    {item.priority ? (
                      <span className={`priority-badge priority-${item.priority.toLowerCase()}`}>
                        {item.priority}
                      </span>
                    ) : null}
                  </div>
                </div>
                <div className="card-grid">
                  <span>公司：{item.company || "待识别"}</span>
                  <span>岗位：{item.role || "待识别"}</span>
                  <span>地点：{getLocationLabel(item)}</span>
                  <span>{timeLabel}：{formatTime(timeValue)}</span>
                  <span>消息时间：{formatTime(item.message_time)}</span>
                  <span>生成时间：{formatTime(item.generated_at)}</span>
                  <span>
                    原链接：
                    {looksLikeUrl(item.source_ref) ? (
                      <a
                        className="inline-link"
                        href={item.source_ref || "#"}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {item.source_ref}
                      </a>
                    ) : (
                      item.source_ref || "无"
                    )}
                  </span>
                  <span>
                    源文件：
                    {item.has_source_file ? (
                      <a
                        className="inline-link"
                        href={getSourceFileHref(item.item_id)}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(event) => event.stopPropagation()}
                      >
                        访问源文件
                      </a>
                    ) : (
                      "无"
                    )}
                  </span>
                  <span>来源：{item.source_type || "unknown"}</span>
                  <span>状态：{item.workflow_status}</span>
                </div>
                {showExpandButton ? (
                  <div className="tag-row">
                    <button
                      type="button"
                      className="segment"
                      onClick={(event) => {
                        event.stopPropagation();
                        setExpandedJobIds((current) =>
                          current.includes(item.item_id)
                            ? current.filter((value) => value !== item.item_id)
                            : [...current, item.item_id],
                        );
                      }}
                    >
                      {expandedJobIds.includes(item.item_id)
                        ? `收起岗位列表（${previewCount}）`
                        : `展开岗位列表（${previewCount}）`}
                    </button>
                    {item.job_child_previews.map((preview, previewIndex) => (
                      <button
                        key={`${item.item_id}-${preview}-${previewIndex}`}
                        type="button"
                        className="tag-chip tag-chip-button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setExpandedJobIds((current) =>
                            current.includes(item.item_id) ? current : [...current, item.item_id],
                          );
                        }}
                      >
                        {preview}
                      </button>
                    ))}
                  </div>
                ) : null}
                {item.tags.length > 0 ? (
                  <div className="tag-row">
                    {item.tags.map((tag) => (
                      <span key={tag} className="tag-chip">
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : null}
                {expandedJobIds.includes(item.item_id) ? (
                  childCards.length > 0 ? (
                    <div className="market-children-list">
                      {childCards.map((child) => {
                        const [childTimeLabel, childTimeValue] = getTimeLabel(child);
                        return (
                          <article
                            key={child.item_id}
                            className="job-card market-child-card"
                            onClick={(event) => {
                              event.stopPropagation();
                              void onOpenDetail(child.item_id, event);
                            }}
                          >
                            <div className="card-header">
                              <div>
                                <p className="card-summary">{child.summary_one_line}</p>
                                {child.insight_summary ? (
                                  <p className="muted-text">{child.insight_summary}</p>
                                ) : null}
                              </div>
                              <span className="tag-chip">role</span>
                            </div>
                            <div className="card-grid">
                              <span>公司：{child.company || "待识别"}</span>
                              <span>岗位：{child.role || "待识别"}</span>
                              <span>地点：{getLocationLabel(child)}</span>
                              <span>
                                {childTimeLabel}：{formatTime(childTimeValue)}
                              </span>
                              <span>消息时间：{formatTime(child.message_time)}</span>
                              <span>生成时间：{formatTime(child.generated_at)}</span>
                              <span>
                                原链接：
                                {looksLikeUrl(child.source_ref) ? (
                                  <a
                                    className="inline-link"
                                    href={child.source_ref || "#"}
                                    target="_blank"
                                    rel="noreferrer"
                                    onClick={(event) => event.stopPropagation()}
                                  >
                                    {child.source_ref}
                                  </a>
                                ) : (
                                  child.source_ref || "无"
                                )}
                              </span>
                              <span>
                                源文件：
                                {child.has_source_file ? (
                                  <a
                                    className="inline-link"
                                    href={getSourceFileHref(child.item_id)}
                                    target="_blank"
                                    rel="noreferrer"
                                    onClick={(event) => event.stopPropagation()}
                                  >
                                    访问源文件
                                  </a>
                                ) : (
                                  "无"
                                )}
                              </span>
                            </div>
                            {child.tags.length > 0 ? (
                              <div className="tag-row">
                                {child.tags.map((tag) => (
                                  <span key={tag} className="tag-chip">
                                    {tag}
                                  </span>
                                ))}
                              </div>
                            ) : null}
                          </article>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="market-children-list">
                      <p className="muted-text">这张岗位总览卡本轮还没有生成可展示的子岗位卡。</p>
                    </div>
                  )
                ) : null}

                <div className="metric-row">
                  <button
                    type="button"
                    className="segment"
                    onClick={(event) => {
                      event.stopPropagation();
                      setEditingId(item.item_id);
                      setDraft(createDraft(item));
                    }}
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    className="segment"
                    onClick={(event) => {
                      event.stopPropagation();
                      void onDelete(item.item_id);
                    }}
                  >
                    删除
                  </button>
                </div>

                {isEditing ? (
                  <div className="stack-form" onClick={(event) => event.stopPropagation()}>
                    <label className="field">
                      <span>摘要</span>
                      <input
                        value={draft.summary_one_line}
                        onChange={(event) =>
                          setDraft({ ...draft, summary_one_line: event.target.value })
                        }
                      />
                    </label>
                    <label className="field">
                      <span>公司</span>
                      <input
                        value={draft.company}
                        onChange={(event) =>
                          setDraft({ ...draft, company: event.target.value })
                        }
                      />
                    </label>
                    <label className="field">
                      <span>岗位</span>
                      <input
                        value={draft.role}
                        onChange={(event) =>
                          setDraft({ ...draft, role: event.target.value })
                        }
                      />
                    </label>
                    <label className="field">
                      <span>地点</span>
                      <input
                        value={draft.city}
                        onChange={(event) =>
                          setDraft({ ...draft, city: event.target.value })
                        }
                      />
                    </label>
                    <label className="field">
                      <span>标签</span>
                      <input
                        value={draft.tags}
                        onChange={(event) =>
                          setDraft({ ...draft, tags: event.target.value })
                        }
                        placeholder="用英文逗号分隔"
                      />
                    </label>
                    <label className="field">
                      <span>优先级</span>
                      <select
                        value={draft.priority}
                        onChange={(event) =>
                          setDraft({ ...draft, priority: event.target.value })
                        }
                      >
                        <option value="">不修改</option>
                        <option value="P0">P0</option>
                        <option value="P1">P1</option>
                        <option value="P2">P2</option>
                        <option value="P3">P3</option>
                      </select>
                    </label>
                    <label className="field">
                      <span>分类</span>
                      <select
                        value={draft.content_category}
                        onChange={(event) =>
                          setDraft({ ...draft, content_category: event.target.value })
                        }
                      >
                        <option value="job_posting">job_posting</option>
                        <option value="interview_notice">interview_notice</option>
                        <option value="talk_event">talk_event</option>
                        <option value="referral">referral</option>
                        <option value="general_update">general_update</option>
                        <option value="noise">noise</option>
                        <option value="unknown">unknown</option>
                      </select>
                    </label>
                    <div className="metric-row">
                      <button
                        type="button"
                        className="primary-button"
                        disabled={saving}
                        onClick={() => void onSave(item.item_id)}
                      >
                        {saving ? "保存中..." : "保存"}
                      </button>
                      <button
                        type="button"
                        className="segment"
                        onClick={() => {
                          setEditingId(null);
                          setDraft(null);
                        }}
                      >
                        取消
                      </button>
                    </div>
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
        ) : (
        <>
        {marketRefreshMessage ? <p className="muted-text">{marketRefreshMessage}</p> : null}
        <div className="card-list">
          {marketItems.map((item) => {
            const childCards = getOrderedChildCards(item, itemMap, marketChildrenByParent);
            const previewOnlyCards = item.market_child_previews.slice(childCards.length);
            const previewCount = getMarketPreviewCount(item, marketChildrenByParent);
            const showExpandButton =
              item.market_group_kind === "overview" || previewCount > 0;

            return (
              <article
                key={item.item_id}
                className="job-card clickable-card"
                onClick={(event) => void onOpenDetail(item.item_id, event)}
              >
                <div className="card-header">
                  <div className="metric-row">
                    <input
                      type="checkbox"
                      checked={selectedItemIds.includes(item.item_id)}
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => {
                        if (event.target.checked) {
                          setSelectedItemIds((current) => [...current, item.item_id]);
                          return;
                        }
                        setSelectedItemIds((current) =>
                          current.filter((value) => value !== item.item_id),
                        );
                      }}
                    />
                    <div>
                      <p className="card-summary">{item.summary_one_line}</p>
                      {item.insight_summary ? (
                        <p className="muted-text">{item.insight_summary}</p>
                      ) : null}
                    </div>
                  </div>
                  <div className="metric-row">
                    <span className="tag-chip">market_info</span>
                    <span className="metric-chip">AI 评分 {item.ai_score?.toFixed(2) || "0.00"}</span>
                  </div>
                </div>

                <div className="card-grid">
                  <span>消息时间：{formatTime(item.message_time)}</span>
                  <span>生成时间：{formatTime(item.generated_at)}</span>
                  <span>摘要：{item.insight_summary || item.summary_one_line}</span>
                  <span>建议：{item.advice || "建议继续观察并结合原文确认。"}</span>
                  <span>结合画像评分：{item.ai_score?.toFixed(2) || "0.00"}</span>
                  <span>
                    原链接：
                    {looksLikeUrl(item.source_ref) ? (
                      <a
                        className="inline-link"
                        href={item.source_ref || "#"}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(event) => event.stopPropagation()}
                      >
                        {item.source_ref}
                      </a>
                    ) : (
                      item.source_ref || "无"
                    )}
                  </span>
                  <span>
                    源文件：
                    {item.has_source_file ? (
                      <a
                        className="inline-link"
                        href={getSourceFileHref(item.item_id)}
                        target="_blank"
                        rel="noreferrer"
                        onClick={(event) => event.stopPropagation()}
                      >
                        访问源文件
                      </a>
                    ) : (
                      "无"
                    )}
                  </span>
                </div>

                {item.tags.length > 0 ? (
                  <div className="tag-row">
                    <span className="muted-text">市场关键词：</span>
                    {item.tags.map((tag) => (
                      <span key={tag} className="tag-chip">
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : null}

                {showExpandButton ? (
                  <div className="tag-row">
                    <button
                      type="button"
                      className="segment"
                      onClick={(event) => {
                        event.stopPropagation();
                        setExpandedMarketIds((current) =>
                          current.includes(item.item_id)
                            ? current.filter((value) => value !== item.item_id)
                            : [...current, item.item_id],
                        );
                      }}
                    >
                      {expandedMarketIds.includes(item.item_id)
                        ? `收起文章列表（${previewCount}）`
                        : `展开文章列表（${previewCount}）`}
                    </button>
                    {item.market_child_previews.map((preview, previewIndex) => (
                      <button
                        key={`${item.item_id}-${preview}-${previewIndex}`}
                        type="button"
                        className="tag-chip tag-chip-button"
                        onClick={(event) => {
                          event.stopPropagation();
                          setExpandedMarketIds((current) =>
                            current.includes(item.item_id)
                              ? current
                              : [...current, item.item_id],
                          );
                        }}
                      >
                        {preview}
                      </button>
                    ))}
                  </div>
                ) : null}

                {expandedMarketIds.includes(item.item_id) ? (
                  childCards.length > 0 || previewOnlyCards.length > 0 ? (
                    <div className="market-children-list">
                      {childCards.map((child) => (
                        <article
                          key={child.item_id}
                          className="job-card market-child-card"
                          onClick={(event) => {
                            event.stopPropagation();
                            void onOpenDetail(child.item_id, event);
                          }}
                        >
                          <div className="card-header">
                            <div>
                              <p className="card-summary">{child.summary_one_line}</p>
                              {child.insight_summary ? (
                                <p className="muted-text">{child.insight_summary}</p>
                              ) : null}
                            </div>
                            <span className="tag-chip">article</span>
                          </div>
                          <div className="card-grid">
                            <span>消息时间：{formatTime(child.message_time)}</span>
                            <span>生成时间：{formatTime(child.generated_at)}</span>
                            <span>摘要：{child.insight_summary || child.summary_one_line}</span>
                            <span>建议：{child.advice || "建议打开详情查看原文。"}</span>
                            <span>结合画像评分：{child.ai_score?.toFixed(2) || "0.00"}</span>
                            <span>
                              原链接：
                              {looksLikeUrl(child.source_ref) ? (
                                <a
                                  className="inline-link"
                                  href={child.source_ref || "#"}
                                  target="_blank"
                                  rel="noreferrer"
                                  onClick={(event) => event.stopPropagation()}
                                >
                                  {child.source_ref}
                                </a>
                              ) : (
                                child.source_ref || "无"
                              )}
                            </span>
                            <span>
                              源文件：
                              {child.has_source_file ? (
                                <a
                                  className="inline-link"
                                  href={getSourceFileHref(child.item_id)}
                                  target="_blank"
                                  rel="noreferrer"
                                  onClick={(event) => event.stopPropagation()}
                                >
                                  访问源文件
                                </a>
                              ) : (
                                "无"
                              )}
                            </span>
                          </div>
                          {child.tags.length > 0 ? (
                            <div className="tag-row">
                              <span className="muted-text">市场关键词：</span>
                              {child.tags.map((tag) => (
                                <span key={tag} className="tag-chip">
                                  {tag}
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </article>
                      ))}
                      {previewOnlyCards.map((preview) => (
                        <article
                          key={`${item.item_id}-${preview}`}
                          className="job-card market-child-card"
                        >
                          <div className="card-header">
                            <div>
                              <p className="card-summary">{preview}</p>
                              <p className="muted-text">
                                这篇文章已经进入标题级收集，但当前还没有抓到完整正文卡片。
                              </p>
                            </div>
                            <span className="tag-chip">preview_only</span>
                          </div>
                          <div className="card-grid">
                            <span>状态：仅标题预览</span>
                            <span>建议：如需全文分析，可提高“市场文章抓取上限”后再刷新。</span>
                          </div>
                        </article>
                      ))}
                    </div>
                  ) : (
                    <div className="market-children-list">
                      <p className="muted-text">这张总览卡本轮还没有生成可展示的文章子卡片。</p>
                    </div>
                  )
                ) : null}

                <div className="metric-row">
                  <button
                    type="button"
                    className="segment"
                    onClick={(event) => {
                      event.stopPropagation();
                      void onDelete(item.item_id);
                    }}
                  >
                    删除
                  </button>
                </div>
              </article>
            );
          })}
        </div>
        </>
        )}
      </section>

      {detailItem ? (
        <div
          className="detail-dialog-backdrop"
          onClick={() => {
            setDetailItem(null);
            setDetailDialogStyle(null);
          }}
        >
          <section
            className="panel detail-panel detail-dialog"
            style={detailDialogStyle ?? undefined}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="card-header">
              <div>
                <p className="eyebrow">Card Detail</p>
                <h2>{detailItem.render_card?.summary_one_line || "卡片详情"}</h2>
              </div>
              <button
                type="button"
                className="segment"
                onClick={() => {
                  setDetailItem(null);
                  setDetailDialogStyle(null);
                }}
              >
                关闭
              </button>
            </div>

            <div className="card-grid">
              <span>公司：{detailItem.extracted_signal?.company || "待识别"}</span>
              <span>岗位：{detailItem.extracted_signal?.role || "待识别"}</span>
              <span>地点：{detailItem.extracted_signal?.city || "待识别"}</span>
              <span>地点说明：{detailItem.extracted_signal?.location_note || "无"}</span>
              <span>DDL：{formatTime(detailItem.extracted_signal?.ddl || null)}</span>
              <span>生成时间：{formatTime(detailItem.render_card?.generated_at || null)}</span>
              <span>消息时间：{formatTime(detailItem.render_card?.message_time || null)}</span>
              <span>
                原链接：
                {looksLikeUrl(detailItem.source_ref || detailItem.extracted_signal?.apply_url) ? (
                  <a
                    className="inline-link"
                    href={(detailItem.source_ref || detailItem.extracted_signal?.apply_url) || "#"}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {detailItem.source_ref || detailItem.extracted_signal?.apply_url}
                  </a>
                ) : (
                  detailItem.source_ref || detailItem.extracted_signal?.apply_url || "无"
                )}
              </span>
              <span>
                源文件：
                {detailItem.render_card?.has_source_file ? (
                  <a
                    className="inline-link"
                    href={getSourceFileHref(detailItem.render_card.item_id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {detailItem.render_card.source_file_name || "访问源文件"}
                  </a>
                ) : (
                  "无"
                )}
              </span>
              <span>源文件路径：{detailItem.render_card?.source_file_path || "无"}</span>
              <span>面试时间：{formatTime(detailItem.extracted_signal?.interview_time || null)}</span>
              <span>活动时间：{formatTime(detailItem.extracted_signal?.event_time || null)}</span>
            </div>

            {detailItem.extracted_signal?.tags?.length ? (
              <div className="tag-row">
                {detailItem.extracted_signal.tags.map((tag) => (
                  <span key={tag} className="tag-chip">
                    {tag}
                  </span>
                ))}
              </div>
            ) : null}

            <div className="result-stack">
              <div className="routing-box">
                <h3>原始内容</h3>
                <pre>{detailItem.normalized_item?.raw_content || "无"}</pre>
              </div>
              <div className="routing-box">
                <h3>标准化文本</h3>
                <pre>{detailItem.normalized_item?.normalized_text || "无"}</pre>
              </div>
              <div className="routing-box">
                <h3>来源信息</h3>
                <pre>{JSON.stringify(detailItem.source_metadata, null, 2)}</pre>
              </div>
              {detailItem.source_metadata?.fetch_plan ? (
                <div className="routing-box">
                  <h3>抓取计划</h3>
                  <pre>{JSON.stringify(detailItem.source_metadata.fetch_plan, null, 2)}</pre>
                </div>
              ) : null}
              {detailItem.source_metadata?.shared_context ? (
                <div className="routing-box">
                  <h3>共享上下文</h3>
                  <pre>{String(detailItem.source_metadata.shared_context)}</pre>
                </div>
              ) : null}
              {detailItem.extracted_signal?.evidence?.length ? (
                <div className="routing-box">
                  <h3>抽取证据</h3>
                  <pre>{JSON.stringify(detailItem.extracted_signal.evidence, null, 2)}</pre>
                </div>
              ) : null}
              {detailItem.reminder_tasks?.length ? (
                <div className="routing-box">
                  <h3>提醒任务</h3>
                  <pre>{JSON.stringify(detailItem.reminder_tasks, null, 2)}</pre>
                </div>
              ) : null}
              {detailItem.issues?.length ? (
                <div className="routing-box">
                  <h3>处理问题</h3>
                  <pre>{JSON.stringify(detailItem.issues, null, 2)}</pre>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </main>
  );
}
