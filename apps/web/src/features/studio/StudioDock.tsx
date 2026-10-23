import { useState, type ReactNode } from "react";
import {useLocationSearch} from "../../app/NavigationGuard";
import {navigateHref} from "../../app/routes";

export function StudioDock({ piano, mixer, inspector, library, workspaceMode }: { piano: ReactNode; mixer: ReactNode; inspector: ReactNode; library: ReactNode; workspaceMode?: "arrange" | "mix" }) {
  const search=useLocationSearch();
  const [localTab, setLocalTab] = useState<"piano" | "mixer" | "inspector" | "library">("inspector");
  const panel=new URLSearchParams(search).get("panel");
  const tab=workspaceMode ? (panel === "piano" || panel === "library" ? panel : "inspector") : localTab;
  const setTab=(id:"piano"|"mixer"|"inspector"|"library")=>{setLocalTab(id);if(workspaceMode){const url=new URL(window.location.href);url.searchParams.set("panel",id);navigateHref(url.href,true);}};
  if(workspaceMode === "mix")return <section className="studio-dock studio-mix-dock" aria-label="Studio Dock">{mixer}</section>;
  const content = { piano, mixer, inspector, library }[tab];
  const tabs = [["piano", "钢琴卷帘"], ["mixer", "混音台"], ["inspector", "片段属性"], ["library", "音色库"]] as const;
  const visibleTabs=workspaceMode ? tabs.filter(([id])=>id!=="mixer") : tabs;
  return <section className="studio-dock" aria-label="Studio Dock"><div className="studio-tabs" role="tablist" aria-label="Studio 面板">{visibleTabs.map(([id, label], index) => <button key={id} type="button" id={`studio-tab-${id}`} role="tab" aria-selected={tab === id} aria-controls="studio-dock-panel" tabIndex={tab === id ? 0 : -1} onClick={() => setTab(id)} onKeyDown={(event) => {
    const next = event.key === "ArrowRight" ? (index + 1) % visibleTabs.length : event.key === "ArrowLeft" ? (index + visibleTabs.length - 1) % visibleTabs.length : event.key === "Home" ? 0 : event.key === "End" ? visibleTabs.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    const nextId = visibleTabs[next]![0];
    setTab(nextId);
    document.getElementById(`studio-tab-${nextId}`)?.focus();
  }}>{label}</button>)}</div><div className="studio-dock-content" id="studio-dock-panel" role="tabpanel" aria-labelledby={`studio-tab-${tab}`} tabIndex={0}>{content}</div></section>;
}
