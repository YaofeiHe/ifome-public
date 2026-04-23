"use client";

import { FormEvent, useEffect, useState } from "react";

import { ChatQueryResponse, ItemListResponse, RenderedItemCard, apiRequest } from "../lib/api";

export default function ChatPage() {
  const [items, setItems] = useState<RenderedItemCard[]>([]);
  const [itemId, setItemId] = useState("");
  const [query, setQuery] = useState("今天该投什么");
  const [recentDays, setRecentDays] = useState(30);
  const [answer, setAnswer] = useState<string | null>(null);
  const [supportingItemIds, setSupportingItemIds] = useState<string[]>([]);
  const [citations, setCitations] = useState<ChatQueryResponse["citations"]>([]);
  const [retrievalMode, setRetrievalMode] = useState<string | null>(null);
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

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);

    try {
      const response = await apiRequest<ChatQueryResponse>("/chat/query", {
        method: "POST",
        body: JSON.stringify({
          query,
          item_id: itemId || null,
          recent_days: recentDays,
        }),
      });
      setAnswer(response.data.answer);
      setSupportingItemIds(response.data.supporting_item_ids);
      setCitations(response.data.citations);
      setRetrievalMode(response.data.retrieval_mode);
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "聊天查询失败。",
      );
    } finally {
      setPending(false);
    }
  }

  return (
    <main className="dashboard-grid">
      <section className="hero panel panel-hero">
        <p className="eyebrow">Chat Console</p>
        <h1>围绕已处理结果继续追问</h1>
        <p className="intro">
          这不是黑盒闲聊，而是基于近期卡片、卡片类型和 memory 的控制台。后端会先分析问题，再按时间窗口和信息类型做混合检索。
        </p>
      </section>

      <section className="panel">
        <form className="stack-form" onSubmit={onSubmit}>
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
            <span>问题</span>
            <textarea
              rows={6}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="今天该投什么 / 面试可能问什么 / 这条岗位我该怎么准备"
            />
          </label>
          <button className="primary-button" disabled={pending} type="submit">
            {pending ? "思考中..." : "发送问题"}
          </button>
        </form>
      </section>

      <section className="panel">
        <h2>回答</h2>
        {error ? <p className="error-text">{error}</p> : null}
        {!answer ? (
          <p className="muted-text">发出一个问题后，这里会展示基于已处理条目的回答。</p>
        ) : (
          <div className="result-stack">
            <p className="answer-box">{answer}</p>
            {retrievalMode ? <p className="muted-text">检索模式：{retrievalMode}</p> : null}
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
        )}
      </section>
    </main>
  );
}
