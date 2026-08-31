import type { ReactNode } from "react";

export function StudioInspector({ children }: { children: ReactNode }) {
  return <aside className="studio-inspector" aria-label="Studio Inspector">
    <details className="studio-inspector-disclosure" open>
      <summary><span>AI / DELIVERY</span><strong>Inspector</strong></summary>
      <div className="studio-inspector-content">{children}</div>
    </details>
  </aside>;
}
