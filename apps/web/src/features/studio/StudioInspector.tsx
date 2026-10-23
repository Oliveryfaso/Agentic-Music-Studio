import { createContext, useContext, useLayoutEffect, useRef, useState, type ReactNode } from "react";

const TaskVisibility = createContext(true);
export const useTaskVisibility = () => useContext(TaskVisibility);

export function StudioInspector({ children, status = "就绪", approvalKey }: { children: ReactNode; status?: string; approvalKey?: string | undefined }) {
  const [open, setOpen] = useState(status === "待确认");
  const previousApproval = useRef(status === "待确认" ? approvalKey ?? "pending" : null);
  const content = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const approval = status === "待确认" ? approvalKey ?? "pending" : null;
    if (approval !== null && approval !== previousApproval.current) setOpen(true);
    previousApproval.current = approval;
  }, [status, approvalKey]);
  useLayoutEffect(() => {
    if (!open) content.current?.querySelectorAll<HTMLMediaElement>("audio, video").forEach(media => media.pause());
  }, [open]);
  return <aside className="studio-inspector" aria-label="Studio Inspector"><details className="studio-inspector-disclosure" open={open} onToggle={event => setOpen(event.currentTarget.open)}><summary><strong>创作任务</strong><span role="status">{status}</span></summary><div ref={content} className="studio-inspector-content" onPlayCapture={event => {
    if (!open && event.target instanceof HTMLMediaElement) { event.target.pause(); event.stopPropagation(); }
  }}><TaskVisibility.Provider value={open}>{children}</TaskVisibility.Provider></div></details></aside>;
}
