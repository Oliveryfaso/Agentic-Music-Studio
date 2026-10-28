import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ImportReviewPage } from "../features/import-review/ImportReviewPage";
import { BriefPage } from "../features/generate/BriefPage";
import { RunPage } from "../features/generate/RunPage";
import { ProjectHomePage } from "../features/projects/ProjectHomePage";
import { StudioPage } from "../features/studio/StudioPage";
import { ExportPage } from "../features/exports/ExportPage";
import { RunInspectorPage } from "../features/inspection/RunInspectorPage";
import { EvaluationPage } from "../features/evaluation/EvaluationPage";
import { PortfolioPage } from "../features/portfolio/PortfolioPage";
import { ModelSettingsPage } from "../features/settings/ModelSettingsPage";
import { AppShell } from "./AppShell";
import { NavigationGuard } from "./NavigationGuard";
import { StatusBanner } from "./StatusBanner";
import { navigate, parseRoute, routeTitle, subscribeToRoute } from "./routes";
import type { AppRoute } from "./routes";

export function App() {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { retry: 1, refetchOnWindowFocus: false },
          mutations: { retry: false },
        },
      }),
  );
  const [route, setRoute] = useState<AppRoute>(() => parseRoute());
  useEffect(() => subscribeToRoute(setRoute), []);
  const pathname=window.location.pathname;
  useEffect(() => {
    document.title = routeTitle(parseRoute());
    document.getElementById("main-content")?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [pathname]);

  return (
    <QueryClientProvider client={queryClient}>
      <NavigationGuard>{route.name === "import" ? (
        route.projectId ? <ImportReviewPage projectId={route.projectId} /> : <ImportReviewPage />
      ) : (
        <AppShell>
          {route.name === "home" && <ProjectHomePage />}
          {route.name === "about" && <PortfolioPage />}
          {route.name === "evaluation" && <EvaluationPage />}
          {route.name === "settings" && <ModelSettingsPage />}
          {route.name === "brief" && <BriefPage key={route.projectId} projectId={route.projectId} />}
          {route.name === "run" && <RunPage runId={route.runId} />}
          {route.name === "studio" && <StudioPage key={`${route.projectId}:${route.revisionId}`} projectId={route.projectId} revisionId={route.revisionId} />}
          {route.name === "export" && <ExportPage key={`${route.projectId}:${route.revisionId}`} projectId={route.projectId} revisionId={route.revisionId} />}
          {route.name === "inspect" && <RunInspectorPage runId={route.runId} />}
          {route.name === "not_found" && (
            <section className="route-missing">
              <StatusBanner tone="warning" message="找不到这个工作台页面" detail="链接可能不完整。返回作品列表，重新打开你的作品即可。" />
              <button className="primary-button" type="button" onClick={() => navigate({ name: "home" })}>返回作品</button>
            </section>
          )}
        </AppShell>
      )}</NavigationGuard>
    </QueryClientProvider>
  );
}
