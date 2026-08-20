import type { ReactNode } from "react";

import { navigate } from "./routes";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand-button" type="button" onClick={() => navigate({ name: "home" })}>
          <span className="brand-mark" aria-hidden="true"><span /></span>
          <span className="brand-lockup-copy">
            <strong>MOTIF FORGE</strong>
            <small>INSTRUMENTAL AGENT STUDIO</small>
          </span>
        </button>
        <nav className="shell-nav" aria-label="主导航">
          <button type="button" onClick={() => navigate({ name: "home" })}>作品</button>
          <span>Brief · Plan · Stem</span>
          <span>只读 Studio · MP3</span>
        </nav>
        <div className="runtime-badge"><i /> LOCAL WORKSPACE</div>
      </header>
      <main>{children}</main>
      <footer><span>Motif Forge / local-first</span><span>PostgreSQL authoritative</span></footer>
    </div>
  );
}
