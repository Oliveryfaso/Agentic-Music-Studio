import type { ReactNode } from "react";

import { parseRoute } from "./routes";

export function AppShell({ children }: { children: ReactNode }) {
  const route = parseRoute();
  const section = route.name === "about" || route.name === "evaluation" ? route.name : "home";
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳至正文</a>
      <header className="topbar">
        <a className="brand-button" href="/" aria-label="Motif Forge 首页">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span className="brand-lockup-copy">
            <strong>Motif Forge<span> / </span></strong>
            <small>音乐，从一个想法开始</small>
          </span>
        </a>
        <nav className="shell-nav" aria-label="主导航">
          <a href="/" aria-current={section === "home" ? "page" : undefined}>作品</a>
          <a href="/about" aria-current={section === "about" ? "page" : undefined}>关于</a>
          <a href="/evaluation" aria-current={section === "evaluation" ? "page" : undefined}>评估</a>
        </nav>
        <div className="runtime-badge">本地创作空间 <span>LOCAL STUDIO</span></div>
      </header>
      <main id="main-content" tabIndex={-1}>{children}</main>
      <footer><span>Motif Forge · 与 Agent 一起创作</span><span>本地保存 · 由你决定</span></footer>
    </div>
  );
}
