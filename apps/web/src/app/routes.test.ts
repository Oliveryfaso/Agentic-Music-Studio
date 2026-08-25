import { afterEach, describe, expect, it } from "vitest";

import { navigate, parseRoute, routePath, routeTitle, subscribeToRoute } from "./routes";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const REVISION_ID = "22222222-2222-4222-8222-222222222222";
const RUN_ID = "33333333-3333-4333-8333-333333333333";

afterEach(() => window.history.replaceState({}, "", "/"));

describe("native application routes", () => {
  it("parses and formats all five frozen S3 routes", () => {
    const cases = [
      ["/", { name: "home" }],
      [`/projects/${PROJECT_ID}/new-composition`, { name: "brief", projectId: PROJECT_ID }],
      [`/runs/${RUN_ID}`, { name: "run", runId: RUN_ID }],
      [
        `/projects/${PROJECT_ID}/studio/${REVISION_ID}`,
        { name: "studio", projectId: PROJECT_ID, revisionId: REVISION_ID },
      ],
      [`/projects/${PROJECT_ID}/import`, { name: "import", projectId: PROJECT_ID }],
      [
        `/projects/${PROJECT_ID}/exports/${REVISION_ID}`,
        { name: "export", projectId: PROJECT_ID, revisionId: REVISION_ID },
      ],
    ] as const;

    for (const [path, route] of cases) {
      expect(parseRoute(path)).toEqual(route);
      expect(routePath(route)).toBe(path);
    }
    expect(parseRoute("/projects/not-a-route")).toEqual({ name: "not_found" });
    expect(routeTitle({ name: "home" })).toBe("Motif Forge · Project Home");
    expect(routeTitle({ name: "import", projectId: PROJECT_ID })).toBe(
      "Motif Forge · Import Review",
    );
  });

  it("publishes push navigation and restores routes from popstate", () => {
    const restored: string[] = [];
    const unsubscribe = subscribeToRoute((route) => restored.push(route.name));

    navigate({ name: "run", runId: RUN_ID });
    expect(window.location.pathname).toBe(`/runs/${RUN_ID}`);

    window.history.replaceState({}, "", `/projects/${PROJECT_ID}/import`);
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(restored).toEqual(["run", "import"]);

    unsubscribe();
  });
});
