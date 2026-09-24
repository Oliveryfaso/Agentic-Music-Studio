import type { ReactNode } from "react";

export function StudioInspector({ children }: { children: ReactNode }) {
  return <aside className="studio-inspector" aria-label="Studio Inspector">
    <details className="studio-inspector-disclosure" open>
      <summary><strong>创作助手与试听</strong><span>AI / LISTEN</span></summary>
      <div className="studio-inspector-content">{children}</div>
    </details>
  </aside>;
}
