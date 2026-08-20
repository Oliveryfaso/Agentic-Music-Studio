import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ImportReviewPage } from "../features/import-review/ImportReviewPage";
import { BriefPage } from "../features/generate/BriefPage";
import { RunPage } from "../features/generate/RunPage";
import { ProjectHomePage } from "../features/projects/ProjectHomePage";
import { AppShell } from "./AppShell";
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
  useEffect(() => {
    document.title = routeTitle(route);
  }, [route]);

  return (
    <QueryClientProvider client={queryClient}>
      {route.name === "import" ? (
        <ImportReviewPage />
      ) : (
        <AppShell>
          {route.name === "home" && <ProjectHomePage />}
          {route.name === "brief" && <BriefPage projectId={route.projectId} />}
          {route.name === "run" && <RunPage runId={route.runId} />}
          {route.name === "studio" && <PendingPage title="Read-only Studio" />}
          {route.name === "not_found" && (
            <section className="route-missing">
              <StatusBanner tone="warning" message="找不到这个工作台页面" detail="URL 不属于当前冻结的 S3 路由。" />
              <button className="primary-button" type="button" onClick={() => navigate({ name: "home" })}>返回作品</button>
            </section>
          )}
        </AppShell>
      )}
    </QueryClientProvider>
  );
}

function PendingPage({ title }: { title: string }) {
  return (
    <section className="route-pending">
      <p className="eyebrow">S3 WORKSPACE</p>
      <h1>{title}</h1>
      <StatusBanner message="页面合同已冻结" detail="对应功能将在后续 S3 纵切接入真实 API。" />
    </section>
  );
}
