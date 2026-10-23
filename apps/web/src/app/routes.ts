export type AppRoute =
  | { name: "home" }
  | { name: "about" }
  | { name: "evaluation" }
  | { name: "brief"; projectId: string }
  | { name: "run"; runId: string }
  | { name: "studio"; projectId: string; revisionId: string }
  | { name: "import"; projectId: string }
  | { name: "export"; projectId: string; revisionId: string }
  | { name: "inspect"; runId: string }
  | { name: "not_found" };

export const NAVIGATION_EVENT = "motif-forge:navigate";
export const BEFORE_NAVIGATION_EVENT = "motif-forge:before-navigate";
export const HISTORY_INDEX = "motifHistoryIndex";

export function ensureHistoryIndex(): number {
  const value = window.history.state?.[HISTORY_INDEX];
  if (typeof value === "number") return value;
  window.history.replaceState({ ...window.history.state, [HISTORY_INDEX]: 0 }, "");
  return 0;
}

export function navigateHref(href: string, replace = false): void {
  const target = new URL(href, window.location.href);
  if (target.origin !== window.location.origin) return;
  const commit = () => {
    const index = ensureHistoryIndex();
    const state = { [HISTORY_INDEX]: replace ? index : index + 1 };
    if (replace) window.history.replaceState(state, "", target);
    else window.history.pushState(state, "", target);
    window.dispatchEvent(new Event(NAVIGATION_EVENT));
  };
  const event = new CustomEvent(BEFORE_NAVIGATION_EVENT, { cancelable: true, detail: { url: target, proceed: commit } });
  if (window.dispatchEvent(event)) commit();
}

export function parseRoute(pathname = window.location.pathname): AppRoute {
  const parts = pathname.split("/").filter(Boolean).map(decodePart);
  if (pathname === "/" || parts.length === 0) return { name: "home" };
  if (pathname === "/about") return { name: "about" };
  if (pathname === "/evaluation") return { name: "evaluation" };
  if (parts.length === 2 && parts[0] === "runs" && parts[1]) {
    return { name: "run", runId: parts[1] };
  }
  if (parts.length === 3 && parts[0] === "projects" && parts[1]) {
    if (parts[2] === "new-composition") return { name: "brief", projectId: parts[1] };
    if (parts[2] === "import") return { name: "import", projectId: parts[1] };
  }
  if (
    parts.length === 4 &&
    parts[0] === "projects" &&
    parts[1] &&
    parts[2] === "studio" &&
    parts[3]
  ) {
    return { name: "studio", projectId: parts[1], revisionId: parts[3] };
  }
  if (
    parts.length === 4 && parts[0] === "projects" && parts[1]
    && parts[2] === "exports" && parts[3]
  ) return { name: "export", projectId: parts[1], revisionId: parts[3] };
  if (parts.length === 3 && parts[0] === "runs" && parts[1] && parts[2] === "inspect") {
    return { name: "inspect", runId: parts[1] };
  }
  return { name: "not_found" };
}

export function routePath(route: Exclude<AppRoute, { name: "not_found" }>): string {
  switch (route.name) {
    case "home":
      return "/";
    case "about":
      return "/about";
    case "evaluation":
      return "/evaluation";
    case "brief":
      return `/projects/${encodeURIComponent(route.projectId)}/new-composition`;
    case "run":
      return `/runs/${encodeURIComponent(route.runId)}`;
    case "studio":
      return `/projects/${encodeURIComponent(route.projectId)}/studio/${encodeURIComponent(route.revisionId)}`;
    case "import":
      return `/projects/${encodeURIComponent(route.projectId)}/import`;
    case "export":
      return `/projects/${encodeURIComponent(route.projectId)}/exports/${encodeURIComponent(route.revisionId)}`;
    case "inspect":
      return `/runs/${encodeURIComponent(route.runId)}/inspect`;
  }
}

export function routeTitle(route: AppRoute): string {
  switch (route.name) {
    case "home":
      return "Motif Forge · Project Home";
    case "about":
      return "Motif Forge · Agentic Portfolio";
    case "evaluation":
      return "Motif Forge · Evaluation";
    case "brief":
      return "Motif Forge · New Composition";
    case "run":
      return "Motif Forge · Plan & Progress";
    case "studio":
      return "Motif Forge · Studio";
    case "import":
      return "Motif Forge · Import Review";
    case "export":
      return "Motif Forge · Export";
    case "inspect":
      return "Motif Forge · Run Inspector";
    case "not_found":
      return "Motif Forge · Not Found";
  }
}

export function navigate(
  route: Exclude<AppRoute, { name: "not_found" }>,
  options: { replace?: boolean } = {},
): void {
  navigateHref(routePath(route), options.replace);
}

export function subscribeToRoute(listener: (route: AppRoute) => void): () => void {
  const publish = () => listener(parseRoute());
  window.addEventListener("popstate", publish);
  window.addEventListener(NAVIGATION_EVENT, publish);
  return () => {
    window.removeEventListener("popstate", publish);
    window.removeEventListener(NAVIGATION_EVENT, publish);
  };
}

function decodePart(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return "";
  }
}
