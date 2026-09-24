import type { ReactNode } from "react";

export function StudioWorkbar({ projectName, revisionId, trackCount, bars, bpm, actions, toolbar }: {
  projectName: string;
  revisionId: string;
  trackCount: number;
  bars: number;
  bpm: number;
  actions: ReactNode;
  toolbar: ReactNode;
}) {
  return <header className="studio-workbar" aria-label="Studio 工作栏">
    <div className="studio-workbar-identity"><p className="eyebrow">STUDIO / 创作工作台</p><h1 id="studio-title">{projectName}</h1><p title={revisionId}>保存版本 · {revisionId.slice(0, 8)}</p></div>
    <div className="studio-meta"><span>{trackCount} 条音轨</span><span>{bars} 小节</span><span>{bpm} BPM</span></div>
    <div className="studio-workbar-actions">{actions}</div>
    {toolbar}
  </header>;
}
