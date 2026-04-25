"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  RuntimeSettingsResponse,
  SourceFileCleanupReport,
  apiRequest,
} from "../lib/api";

function parseFallbackModels(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseFilterPatterns(value: string) {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

function formatBytes(value: number) {
  if (value >= 1024 * 1024 * 1024) {
    return `${(value / (1024 * 1024 * 1024)).toFixed(2)} GB`;
  }
  if (value >= 1024 * 1024) {
    return `${(value / (1024 * 1024)).toFixed(1)} MB`;
  }
  if (value >= 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  return `${value} B`;
}

type SettingsSectionKey = "models" | "source-files";

export default function SettingsPage() {
  const [openSection, setOpenSection] = useState<SettingsSectionKey | null>("models");

  const [llmEnabled, setLlmEnabled] = useState(false);
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [llmFallbackModels, setLlmFallbackModels] = useState("");
  const [llmTimeout, setLlmTimeout] = useState("30");

  const [ocrEnabled, setOcrEnabled] = useState(false);
  const [ocrProviderLabel, setOcrProviderLabel] = useState("Qwen-VL-OCR");
  const [ocrApiKey, setOcrApiKey] = useState("");
  const [ocrBaseUrl, setOcrBaseUrl] = useState("");
  const [ocrModel, setOcrModel] = useState("qwen-vl-ocr");
  const [ocrTimeout, setOcrTimeout] = useState("60");

  const [sourceFileMaxAgeDays, setSourceFileMaxAgeDays] = useState("30");
  const [sourceFileMaxTotalSizeMb, setSourceFileMaxTotalSizeMb] = useState("2048");
  const [sourceFileDeleteWhenItemDeleted, setSourceFileDeleteWhenItemDeleted] =
    useState(true);
  const [sourceFileFilterPatterns, setSourceFileFilterPatterns] = useState("");

  const [cleanupReport, setCleanupReport] = useState<SourceFileCleanupReport | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [cleanupPending, setCleanupPending] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const response = await apiRequest<RuntimeSettingsResponse>("/settings/runtime");
        const { llm, ocr, source_files: sourceFiles } = response.data;
        setLlmEnabled(llm.enabled);
        setLlmApiKey(llm.api_key || "");
        setLlmBaseUrl(llm.base_url || "");
        setLlmModel(llm.model || "");
        setLlmFallbackModels(llm.fallback_models.join(", "));
        setLlmTimeout(String(llm.request_timeout_seconds || 30));

        setOcrEnabled(ocr.enabled);
        setOcrProviderLabel(ocr.provider_label || "Qwen-VL-OCR");
        setOcrApiKey(ocr.api_key || "");
        setOcrBaseUrl(ocr.base_url || "");
        setOcrModel(ocr.model || "qwen-vl-ocr");
        setOcrTimeout(String(ocr.request_timeout_seconds || 60));

        setSourceFileMaxAgeDays(String(sourceFiles.max_age_days || 30));
        setSourceFileMaxTotalSizeMb(String(sourceFiles.max_total_size_mb || 2048));
        setSourceFileDeleteWhenItemDeleted(sourceFiles.delete_when_item_deleted);
        setSourceFileFilterPatterns(sourceFiles.filter_patterns.join("\n"));
      } catch (requestError) {
        setError(
          requestError instanceof Error ? requestError.message : "读取设置失败，请稍后重试。",
        );
      } finally {
        setLoading(false);
      }
    }

    void load();
  }, []);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError(null);
    setMessage(null);
    try {
      await apiRequest<RuntimeSettingsResponse>("/settings/runtime", {
        method: "POST",
        body: JSON.stringify({
          llm: {
            enabled: llmEnabled,
            api_key: llmApiKey || null,
            base_url: llmBaseUrl || null,
            model: llmModel || null,
            fallback_models: parseFallbackModels(llmFallbackModels),
            request_timeout_seconds: Math.min(
              300,
              Math.max(1, Number.parseInt(llmTimeout || "30", 10) || 30),
            ),
          },
          ocr: {
            enabled: ocrEnabled,
            provider_label: ocrProviderLabel || "Qwen-VL-OCR",
            api_key: ocrApiKey || null,
            base_url: ocrBaseUrl || null,
            model: ocrModel || null,
            request_timeout_seconds: Math.min(
              300,
              Math.max(1, Number.parseInt(ocrTimeout || "60", 10) || 60),
            ),
          },
          source_files: {
            max_age_days: Math.min(
              3650,
              Math.max(1, Number.parseInt(sourceFileMaxAgeDays || "30", 10) || 30),
            ),
            max_total_size_mb: Math.min(
              102400,
              Math.max(
                64,
                Number.parseInt(sourceFileMaxTotalSizeMb || "2048", 10) || 2048,
              ),
            ),
            delete_when_item_deleted: sourceFileDeleteWhenItemDeleted,
            filter_patterns: parseFilterPatterns(sourceFileFilterPatterns),
          },
        }),
      });
      setMessage("设置已保存，并已刷新到当前运行实例。");
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "保存设置失败，请稍后重试。",
      );
    } finally {
      setPending(false);
    }
  }

  async function onRunCleanup() {
    setCleanupPending(true);
    setError(null);
    setMessage(null);
    try {
      const response = await apiRequest<SourceFileCleanupReport>(
        "/settings/source-files/cleanup",
        { method: "POST" },
      );
      setCleanupReport(response.data);
      setMessage("源文件清理已执行完成。");
      setOpenSection("source-files");
    } catch (requestError) {
      setError(
        requestError instanceof Error ? requestError.message : "源文件清理失败，请稍后重试。",
      );
    } finally {
      setCleanupPending(false);
    }
  }

  return (
    <main className="dashboard-grid">
      <section className="hero panel panel-hero">
        <p className="eyebrow">Settings</p>
        <h1>设置</h1>
        <p className="intro">
          当前所有配置都只保存在本地运行时，不会写入长期记忆。现在包含模型设置和源文件管理，
          后续可以继续按类别往下扩展。
        </p>
      </section>

      {message ? <section className="panel success-banner">{message}</section> : null}
      {error ? <section className="panel error-banner">{error}</section> : null}

      <section className="panel">
        {loading ? (
          <p className="muted-text">正在读取当前设置...</p>
        ) : (
          <form className="stack-form" onSubmit={onSubmit}>
            <div className="settings-list">
              <section className="settings-section">
                <button
                  className="settings-toggle"
                  type="button"
                  onClick={() =>
                    setOpenSection((current) => (current === "models" ? null : "models"))
                  }
                >
                  <span className="settings-toggle-title">模型设置</span>
                  <span className="settings-toggle-meta">推理 LLM 与 OCR LLM</span>
                </button>
                {openSection === "models" ? (
                  <div className="settings-body">
                    <p className="settings-note">
                      OCR 默认会复用通用 LLM 的多模态接口；如果启用了独立 OCR 配置，
                      则优先走独立 OCR，最后才会回退到本地 <strong>tesseract</strong>。
                    </p>

                    <div className="settings-grid">
                      <section className="settings-card">
                        <h2>通用推理 LLM</h2>
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={llmEnabled}
                            onChange={(event) => setLlmEnabled(event.target.checked)}
                          />
                          <span>启用 classify / extract 的 live LLM 路由</span>
                        </label>
                        <p className="settings-note">
                          这里只要填了支持图片输入的模型配置，图片 OCR 默认也会优先复用它。
                        </p>
                        <label className="field">
                          <span>API Key</span>
                          <input
                            type="password"
                            value={llmApiKey}
                            onChange={(event) => setLlmApiKey(event.target.value)}
                            placeholder="sk-..."
                          />
                        </label>
                        <label className="field">
                          <span>Base URL</span>
                          <input
                            value={llmBaseUrl}
                            onChange={(event) => setLlmBaseUrl(event.target.value)}
                            placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                          />
                        </label>
                        <label className="field">
                          <span>主模型</span>
                          <input
                            value={llmModel}
                            onChange={(event) => setLlmModel(event.target.value)}
                            placeholder="qwen-plus"
                          />
                        </label>
                        <label className="field">
                          <span>候选降级模型</span>
                          <input
                            value={llmFallbackModels}
                            onChange={(event) => setLlmFallbackModels(event.target.value)}
                            placeholder="qwen-turbo, qwen-flash"
                          />
                        </label>
                        <label className="field">
                          <span>超时秒数</span>
                          <input
                            type="number"
                            min={1}
                            max={300}
                            value={llmTimeout}
                            onChange={(event) => setLlmTimeout(event.target.value)}
                          />
                        </label>
                      </section>

                      <section className="settings-card">
                        <h2>独立 OCR LLM</h2>
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={ocrEnabled}
                            onChange={(event) => setOcrEnabled(event.target.checked)}
                          />
                          <span>启用独立 OCR 覆写路线</span>
                        </label>
                        <p className="settings-note">
                          当你希望 OCR 和通用推理模型分开时，再在这里单独配置。
                        </p>
                        <label className="field">
                          <span>OCR 提供方标识</span>
                          <input
                            value={ocrProviderLabel}
                            onChange={(event) => setOcrProviderLabel(event.target.value)}
                            placeholder="Qwen-VL-OCR"
                          />
                        </label>
                        <label className="field">
                          <span>OCR API Key</span>
                          <input
                            type="password"
                            value={ocrApiKey}
                            onChange={(event) => setOcrApiKey(event.target.value)}
                            placeholder="sk-..."
                          />
                        </label>
                        <label className="field">
                          <span>OCR Base URL</span>
                          <input
                            value={ocrBaseUrl}
                            onChange={(event) => setOcrBaseUrl(event.target.value)}
                            placeholder="https://dashscope.aliyuncs.com/compatible-mode/v1"
                          />
                        </label>
                        <label className="field">
                          <span>OCR 模型</span>
                          <input
                            value={ocrModel}
                            onChange={(event) => setOcrModel(event.target.value)}
                            placeholder="qwen-vl-ocr"
                          />
                        </label>
                        <label className="field">
                          <span>OCR 超时秒数</span>
                          <input
                            type="number"
                            min={1}
                            max={300}
                            value={ocrTimeout}
                            onChange={(event) => setOcrTimeout(event.target.value)}
                          />
                        </label>
                      </section>
                    </div>
                  </div>
                ) : null}
              </section>

              <section className="settings-section">
                <button
                  className="settings-toggle"
                  type="button"
                  onClick={() =>
                    setOpenSection((current) =>
                      current === "source-files" ? null : "source-files",
                    )
                  }
                >
                  <span className="settings-toggle-title">源文件管理</span>
                  <span className="settings-toggle-meta">保留策略与清理规则</span>
                </button>
                {openSection === "source-files" ? (
                  <div className="settings-body">
                    <p className="settings-note">
                      超过时长、超过容量、命中过滤规则，或对应卡片被删除时，都可以自动移除本地源文件。
                      纯文本输入会以 <code>.txt</code> 形式归档。
                    </p>

                    <div className="settings-grid settings-grid-single">
                      <section className="settings-card">
                        <label className="field">
                          <span>最长保留天数</span>
                          <input
                            type="number"
                            min={1}
                            max={3650}
                            value={sourceFileMaxAgeDays}
                            onChange={(event) => setSourceFileMaxAgeDays(event.target.value)}
                          />
                        </label>
                        <label className="field">
                          <span>最大总容量（MB）</span>
                          <input
                            type="number"
                            min={64}
                            max={102400}
                            value={sourceFileMaxTotalSizeMb}
                            onChange={(event) =>
                              setSourceFileMaxTotalSizeMb(event.target.value)
                            }
                          />
                        </label>
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={sourceFileDeleteWhenItemDeleted}
                            onChange={(event) =>
                              setSourceFileDeleteWhenItemDeleted(event.target.checked)
                            }
                          />
                          <span>卡片删除时，同时删除失去引用的源文件</span>
                        </label>
                        <label className="field">
                          <span>过滤规则</span>
                          <textarea
                            rows={5}
                            value={sourceFileFilterPatterns}
                            onChange={(event) =>
                              setSourceFileFilterPatterns(event.target.value)
                            }
                            placeholder={"每行一个关键词\n示例科技\n请分析这个岗位\n统一输入卡片"}
                          />
                        </label>

                        <div className="settings-actions">
                          <button
                            className="secondary-button"
                            disabled={cleanupPending}
                            onClick={onRunCleanup}
                            type="button"
                          >
                            {cleanupPending ? "清理中..." : "立即清理源文件"}
                          </button>
                        </div>

                        {cleanupReport ? (
                          <div className="settings-report">
                            <div className="settings-stats">
                              <span>扫描文件 {cleanupReport.scanned_file_count}</span>
                              <span>删除文件 {cleanupReport.deleted_file_count}</span>
                              <span>释放空间 {formatBytes(cleanupReport.reclaimed_bytes)}</span>
                              <span>剩余空间 {formatBytes(cleanupReport.remaining_bytes)}</span>
                            </div>
                            <div className="settings-stats">
                              <span>孤儿文件 {cleanupReport.deleted_orphan_file_count}</span>
                              <span>超时删除 {cleanupReport.deleted_due_to_age_count}</span>
                              <span>超容删除 {cleanupReport.deleted_due_to_size_count}</span>
                              <span>规则删除 {cleanupReport.deleted_due_to_filter_count}</span>
                            </div>
                          </div>
                        ) : null}
                      </section>
                    </div>
                  </div>
                ) : null}
              </section>
            </div>

            <button className="primary-button" disabled={pending} type="submit">
              {pending ? "保存中..." : "保存设置"}
            </button>
          </form>
        )}
      </section>
    </main>
  );
}
