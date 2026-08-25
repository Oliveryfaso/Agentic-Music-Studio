import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import type { RevisionExportProjection } from "../../shared/openapi";
import { ExportPage } from "./ExportPage";

const PROJECT_ID = "11111111-1111-4111-8111-111111111111";
const REVISION_ID = "22222222-2222-4222-8222-222222222222";
const RUN_ID = "33333333-3333-4333-8333-333333333333";
const MASTER_ID = "44444444-4444-4444-8444-444444444444";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("renders the seven authoritative steps and delivery links", async () => {
  stubProjection(projection("ready"));
  renderPage();

  expect(await screen.findAllByTestId("export-step")).toHaveLength(7);
  expect(screen.getByRole("link", { name: /Master WAV/ })).toHaveAttribute(
    "href", `/api/v1/audio-artifacts/${MASTER_ID}/content`,
  );
  expect(screen.getByRole("link", { name: "检查 Run" })).toHaveAttribute(
    "href", `/runs/${RUN_ID}/inspect`,
  );
});

it("keeps safe files visible while labeling partial failure", async () => {
  const value = projection("failed");
  value.steps[1]!.status = "failed";
  value.steps[1]!.error_code = "RENDER_FAILED";
  stubProjection(value);
  renderPage();

  expect(await screen.findByText("导出部分完成")).toBeInTheDocument();
  expect(screen.getByText("RENDER_FAILED")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /Master WAV/ })).toBeInTheDocument();
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ExportPage projectId={PROJECT_ID} revisionId={REVISION_ID} />
    </QueryClientProvider>,
  );
}

function stubProjection(value: RevisionExportProjection) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ data: value }), {
    status: 200, headers: { "Content-Type": "application/json" },
  })));
}

function projection(status: "ready" | "failed"): RevisionExportProjection {
  return {
    project_id: PROJECT_ID,
    revision_id: REVISION_ID,
    source_run_id: RUN_ID,
    status,
    error_code: status === "failed" ? "EXPORT_PARTIAL_FAILURE" : null,
    bundle: status === "ready" ? {
      bundle_id: "55555555-5555-4555-8555-555555555555",
      project_id: PROJECT_ID, revision_id: REVISION_ID, availability: "available",
      content_hash: "a".repeat(64), byte_size: 2048, file_count: 13,
    } : null,
    steps: ["master", "stem:pad", "stem:melody", "stem:bass", "stem:rhythm", "mp3", "bundle"].map((step, index) => ({
      step, job_id: `00000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
      status: "succeeded", artifact_id: null, error_code: null,
    })),
    files: [{
      file_id: `audio:${MASTER_ID}`, filename: "master.wav", category: "master",
      media_type: "audio/wav", byte_size: 1024, availability: "available",
      checksum: "b".repeat(64),
      content_url: `/api/v1/audio-artifacts/${MASTER_ID}/content`, artifact_id: MASTER_ID,
    }],
  };
}
