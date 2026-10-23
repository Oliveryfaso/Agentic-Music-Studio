import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { BEFORE_NAVIGATION_EVENT, ensureHistoryIndex, HISTORY_INDEX, navigateHref, NAVIGATION_EVENT, parseRoute } from "./routes";

interface DraftOwner { scope: string; active: boolean }
let dirtyOwner: DraftOwner | null = null;
function clearUnsavedNavigation(owner: DraftOwner | null): void {
  if (owner !== null && dirtyOwner === owner) dirtyOwner = null;
}
export function useUnsavedNavigation(dirty: boolean, scope: string) {
  const owner = useMemo<DraftOwner>(() => ({ scope, active: false }), [scope]);
  useLayoutEffect(() => {
    owner.active = true;
    return () => { owner.active = false; clearUnsavedNavigation(owner); };
  }, [owner]);
  useLayoutEffect(() => {
    if (dirty) dirtyOwner = owner;
    else clearUnsavedNavigation(owner);
    return () => clearUnsavedNavigation(owner);
  }, [dirty, owner]);
  const isCurrent = () => owner.active && window.location.pathname === owner.scope;
  return {
    isCurrent,
    clear: () => {
      if (!isCurrent() || (dirtyOwner !== null && dirtyOwner !== owner)) return false;
      clearUnsavedNavigation(owner);
      return true;
    },
  };
}
const watchLocation = (listener: () => void) => {
  window.addEventListener(NAVIGATION_EVENT, listener);
  window.addEventListener("popstate", listener);
  return () => { window.removeEventListener(NAVIGATION_EVENT, listener); window.removeEventListener("popstate", listener); };
};
export function useLocationSearch(): string {
  return useSyncExternalStore(watchLocation, () => window.location.search);
}

interface Pending { proceed: () => void; trigger: HTMLElement | null; owner: DraftOwner | null }
export function NavigationGuard({ children }: { children: ReactNode }) {
  const [pending, setPending] = useState<Pending | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (pending) cancel.current?.focus(); }, [pending]);
  useLayoutEffect(() => {
    ensureHistoryIndex();
    let current = { href: window.location.href, state: window.history.state };
    let restoring: { index: number; targetIndex: number; target: string } | null = null;
    const blocked = (url: URL) => dirtyOwner !== null && url.pathname !== dirtyOwner.scope;
    const ask = (proceed: () => void) => setPending({ proceed, owner: dirtyOwner, trigger: document.activeElement instanceof HTMLElement ? document.activeElement : null });
    const before = (event: Event) => {
      const request = event as CustomEvent<{ url: URL; proceed: () => void }>;
      // The browser has changed entries, but the mounted Draft has not left.
      // Finish restoring that entry before accepting any new navigation.
      if (restoring) { event.preventDefault(); return; }
      if (blocked(request.detail.url)) { event.preventDefault(); ask(request.detail.proceed); }
    };
    const sync = () => { current = { href: window.location.href, state: window.history.state }; setPending(null); };
    const pop = (event: PopStateEvent) => {
      const observed = event.state?.[HISTORY_INDEX];
      if (restoring) {
        event.stopImmediatePropagation();
        const restoration = restoring;
        if (observed !== restoration.index) {
          if (typeof observed === "number") window.history.go(restoration.index - observed);
          else window.history.replaceState(current.state, "", current.href);
          if (typeof observed === "number") return;
        }
        restoring = null;
        sync();
        ask(() => {
          const actual = window.history.state?.[HISTORY_INDEX];
          if (typeof actual === "number" && actual !== restoration.targetIndex) window.history.go(restoration.targetIndex - actual);
          else navigateHref(restoration.target);
        });
        return;
      }
      if (!blocked(new URL(window.location.href))) { sync(); return; }
      event.stopImmediatePropagation();
      setPending(null);
      const target = window.location.href;
      const from = current.state?.[HISTORY_INDEX], to = observed;
      if (typeof from === "number" && typeof to === "number" && from !== to) {
        restoring = { index: from, targetIndex: to, target };
        window.history.go(from - to);
      } else {
        // A same-document history entry created outside our router has no index.
        // Restore the current URL before offering a new, explicit navigation.
        window.history.replaceState(current.state, "", current.href);
        ask(() => navigateHref(target));
      }
    };
    const click = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>("a[href]") : null;
      if (!anchor || anchor.hasAttribute("download") || (anchor.target && anchor.target !== "_self")) return;
      const url = new URL(anchor.href);
      if (url.origin !== window.location.origin || url.hash || parseRoute(url.pathname).name === "not_found") return;
      event.preventDefault(); navigateHref(url.href);
    };
    const close = (event: BeforeUnloadEvent) => { if (dirtyOwner !== null) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener(BEFORE_NAVIGATION_EVENT, before);
    window.addEventListener(NAVIGATION_EVENT, sync);
    window.addEventListener("popstate", pop, true);
    window.addEventListener("beforeunload", close);
    document.addEventListener("click", click, true);
    return () => {
      window.removeEventListener(BEFORE_NAVIGATION_EVENT, before); window.removeEventListener(NAVIGATION_EVENT, sync);
      window.removeEventListener("popstate", pop, true); window.removeEventListener("beforeunload", close); document.removeEventListener("click", click, true);
    };
  }, []);
  const stay = () => { const trigger = pending?.trigger; setPending(null); trigger?.focus(); };
  return <>{children}{pending && <div className="dialog-backdrop"><div ref={dialog} className="navigation-dialog" role="alertdialog" aria-modal="true" aria-labelledby="leave-title" aria-describedby="leave-description" onKeyDown={event => {
    if (event.key === "Escape") { event.preventDefault(); stay(); }
    if (event.key === "Tab") {
      const buttons = dialog.current?.querySelectorAll<HTMLButtonElement>("button");
      const first = buttons?.[0], last = buttons?.[buttons.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  }}><h2 id="leave-title">有未保存的草稿</h2><p id="leave-description">离开将放弃这些修改。</p><div><button ref={cancel} type="button" onClick={stay}>留在此页</button><button className="danger-button" type="button" onClick={() => { const proceed = pending.proceed; clearUnsavedNavigation(pending.owner); setPending(null); proceed(); }}>放弃草稿并离开</button></div></div></div>}</>;
}
