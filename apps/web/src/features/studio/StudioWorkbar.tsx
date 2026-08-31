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
    <div className="studio-workbar-identity"><p className="eyebrow">ARRANGEMENT / REVISION STUDIO</p><h1 id="studio-title">{projectName} / Revision</h1><p title={revisionId}>{revisionId}</p></div>
    <div className="studio-meta"><span>{trackCount} tracks</span><span>{bars} bars</span><span>{bpm} BPM</span></div>
    <div className="studio-workbar-actions">{actions}</div>
    {toolbar}
  </header>;
}
