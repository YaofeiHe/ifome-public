"use client";

import { useState } from "react";

import { apiRequest } from "../lib/api";

export function ShutdownButton() {
  const [busy, setBusy] = useState(false);

  async function handleShutdown() {
    setBusy(true);
    try {
      await apiRequest("/runtime/shutdown", {
        method: "POST",
      });
    } catch {
      // The backend may terminate before the response reaches the browser.
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      className="shutdown-button"
      onClick={() => {
        void handleShutdown();
      }}
      disabled={busy}
      aria-label="关闭 ifome"
      title="关闭 ifome"
    >
      <span aria-hidden="true">⏻</span>
      <span>{busy ? "关闭中" : "关闭 ifome"}</span>
    </button>
  );
}
