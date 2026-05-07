import "./globals.css";
import type { Metadata } from "next";
import { ReactNode } from "react";

import { AppNav } from "./components/app-nav";
import { MarketRefreshBootstrap } from "./components/market-refresh-bootstrap";
import { ShutdownButton } from "./components/shutdown-button";

export const metadata: Metadata = {
  title: "ifome Job Agent",
  description: "Scaffold for a job information flow agent.",
};

type RootLayoutProps = {
  children: ReactNode;
};

export default function RootLayout({ children }: RootLayoutProps) {
  return (
    <html lang="zh-CN">
      <body>
        <MarketRefreshBootstrap />
        <div className="site-shell">
          <header className="site-header">
            <div className="brand-block">
              <p className="eyebrow">ifome</p>
              <p className="brand-copy">单 Agent 求职信息流控制台</p>
            </div>
            <div className="site-header-actions">
              <AppNav />
              <ShutdownButton />
            </div>
          </header>
          {children}
        </div>
      </body>
    </html>
  );
}
