import type { ReactNode } from "react";

import { parseRoute } from "./routes";

export function AppShell({ children }: { children: ReactNode }) {
  const route = parseRoute();
  const section = route.name === "about" || route.name === "evaluation" || route.name === "settings" ? route.name : "home";
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">跳至正文</a>
      <header className="topbar">
        <a className="brand-button" href="/" aria-label="Motif Forge 首页">
          <span className="brand-mark" aria-hidden="true"><i /><i /><i /></span>
          <span className="brand-lockup-copy">
            <strong>Motif Forge</strong>
            
          </span>
        </a>
        <nav className="shell-nav" aria-label="主导航">
          <a href="/" aria-current={section === "home" ? "page" : undefined}>作品</a>
          <a href="/settings" aria-current={section === "settings" ? "page" : undefined}>设置</a>
          <details className="shell-more" open={section === "about" || section === "evaluation"}><summary>更多</summary><div><a href="/about" aria-current={section === "about" ? "page" : undefined}>关于</a><a href="/evaluation" aria-current={section === "evaluation" ? "page" : undefined}>评估</a></div></details>
        </nav>
        <div className="runtime-badge">本地工作台</div>
      </header>
      <main id="main-content" tabIndex={-1}>{children}</main>
    </div>
  );
}
