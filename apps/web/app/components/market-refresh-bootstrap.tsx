"use client";

import { useEffect } from "react";

import { MarketRefreshResponse, apiRequest } from "../lib/api";

const MARKET_REFRESH_EVENT = "ifome:market-refresh";

export function MarketRefreshBootstrap() {
  useEffect(() => {
    let cancelled = false;

    async function checkScheduledRefresh() {
      try {
        const response = await apiRequest<MarketRefreshResponse>("/market/refresh", {
          method: "POST",
          body: JSON.stringify({ force: false }),
        });
        if (!response.data.refreshed || cancelled) {
          return;
        }
        window.dispatchEvent(
          new CustomEvent(MARKET_REFRESH_EVENT, {
            detail: {
              reason: response.data.reason,
              refreshedCount: response.data.refreshed_count,
              lastMarketRefreshAt: response.data.last_market_refresh_at,
            },
          }),
        );
      } catch {
        return;
      }
    }

    void checkScheduledRefresh();
    const timer = window.setInterval(() => {
      void checkScheduledRefresh();
    }, 15 * 60 * 1000);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  return null;
}

export { MARKET_REFRESH_EVENT };
