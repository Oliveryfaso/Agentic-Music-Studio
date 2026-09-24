import { useState, type ReactNode } from "react";

export function StudioDock({ piano, mixer, inspector, library }: { piano: ReactNode; mixer: ReactNode; inspector: ReactNode; library: ReactNode }) {
  const [tab, setTab] = useState<"piano" | "mixer" | "inspector" | "library">("inspector");
  const content = { piano, mixer, inspector, library }[tab];
  const tabs = [["piano", "钢琴卷帘"], ["mixer", "混音台"], ["inspector", "片段属性"], ["library", "音色库"]] as const;
  return <section className="studio-dock" aria-label="Studio Dock"><div className="studio-tabs" role="tablist" aria-label="Studio 面板">{tabs.map(([id, label], index) => <button key={id} type="button" id={`studio-tab-${id}`} role="tab" aria-selected={tab === id} aria-controls="studio-dock-panel" tabIndex={tab === id ? 0 : -1} onClick={() => setTab(id)} onKeyDown={(event) => {
    const next = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    const nextId = tabs[next]![0];
    setTab(nextId);
    document.getElementById(`studio-tab-${nextId}`)?.focus();
  }}>{label}</button>)}</div><div className="studio-dock-content" id="studio-dock-panel" role="tabpanel" aria-labelledby={`studio-tab-${tab}`} tabIndex={0}>{content}</div></section>;
}
