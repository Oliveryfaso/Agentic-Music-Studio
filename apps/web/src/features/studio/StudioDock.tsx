import { useState, type ReactNode } from "react";

export function StudioDock({ piano, mixer, inspector, library }: { piano: ReactNode; mixer: ReactNode; inspector: ReactNode; library: ReactNode }) {
  const [tab, setTab] = useState<"piano" | "mixer" | "inspector" | "library">("inspector");
  const content = { piano, mixer, inspector, library }[tab];
  return <section className="studio-dock" aria-label="Studio Dock"><nav aria-label="Studio 面板"><button onClick={() => setTab("piano")}>钢琴卷帘</button><button onClick={() => setTab("mixer")}>Mixer</button><button onClick={() => setTab("inspector")}>Inspector</button><button onClick={() => setTab("library")}>音色库</button></nav><div className="studio-dock-content">{content}</div></section>;
}
