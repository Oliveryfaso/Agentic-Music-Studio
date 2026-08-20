import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImportReviewPage } from "./ImportReviewPage";

const ID = "11111111-1111-4111-8111-111111111111";
const FEATURE_ID = "22222222-2222-4222-8222-222222222222";
const BRANCH_ID = "33333333-3333-4333-8333-333333333333";
const HEAD_ONE = "44444444-4444-4444-8444-444444444444";
const HEAD_TWO = "55555555-5555-4555-8555-555555555555";
const HEAD_THREE = "66666666-6666-4666-8666-666666666666";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("ImportReviewPage", () => {
  it("shows the empty entry state without inventing a project", () => {
    renderPage();
    expect(screen.getByText("等待一个真实导入结果")).toBeInTheDocument();
  });

  it("validates source Artifact IDs before calling the API", () => {
    const fetchMock = vi.spyOn(window, "fetch");
    renderPage();
    fireEvent.change(screen.getByLabelText("源 Audio Artifact ID"), { target: { value: "audio.wav" } });
    fireEvent.click(screen.getByRole("button", { name: "载入分析" }));
    expect(screen.getByText("请输入完整的源 Audio Artifact UUID")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("renders an evicted Feature with an explicit rebuild action", async () => {
    vi.spyOn(window, "fetch").mockResolvedValue(
      jsonResponse({
        request_id: ID,
        trace_id: ID,
        status: "succeeded",
        warnings: [],
        data: {
          source_audio_artifact_id: ID,
          features: [
            {
              artifact_id: FEATURE_ID,
              project_id: ID,
              source_audio_artifact_id: ID,
              feature_profile: "waveform-peaks.v1",
              feature_schema_version: "waveform-peaks.v1",
              availability: "evicted",
              content_hash: "a".repeat(64),
              byte_size: 42,
              payload: null,
            },
          ],
        },
      }),
    );
    renderPage();
    fireEvent.change(screen.getByLabelText("源 Audio Artifact ID"), { target: { value: ID } });
    fireEvent.click(screen.getByRole("button", { name: "载入分析" }));
    expect(await screen.findByText("已回收")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "显式重建" })).toBeInTheDocument();
  });

  it("loads and presents an available analysis payload from the real profile name", async () => {
    const fetchMock = vi.spyOn(window, "fetch");
    fetchMock
      .mockResolvedValueOnce(
        jsonResponse({
          request_id: ID,
          trace_id: ID,
          status: "succeeded",
          warnings: [],
          data: {
            source_audio_artifact_id: ID,
            features: [featureData("available", "imported-audio-analysis.v1")],
          },
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          request_id: ID,
          trace_id: ID,
          status: "succeeded",
          warnings: [],
          data: {
            ...featureData("available", "imported-audio-analysis.v1"),
            payload: {
              schema_version: "imported-audio-analysis.v1",
              analysis_version: "import-analysis.v1",
              bpm: 112,
              bpm_confidence: 0.81,
              key_tonic: "D",
              key_mode: "minor",
              key_confidence: 0.52,
              analyzed_seconds: 30,
            },
          },
        }),
      );
    renderPage();
    fireEvent.change(screen.getByLabelText("源 Audio Artifact ID"), { target: { value: ID } });
    fireEvent.click(screen.getByRole("button", { name: "载入分析" }));
    expect(await screen.findByText("112.0")).toBeInTheDocument();
    expect(screen.getByText("D 小调")).toBeInTheDocument();
  });

  it("shows an actionable API error", async () => {
    vi.spyOn(window, "fetch").mockResolvedValue(
      jsonResponse({ detail: "source not found", error_code: "ARTIFACT_NOT_FOUND", retryable: false }, 404),
    );
    renderPage();
    fireEvent.change(screen.getByLabelText("源 Audio Artifact ID"), { target: { value: ID } });
    fireEvent.click(screen.getByRole("button", { name: "载入分析" }));
    await waitFor(() => expect(screen.getByText(/source not found/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
  });

  it("requires an explicit rights confirmation before controlled upload", async () => {
    const fetchMock = vi.spyOn(window, "fetch");
    renderPage();
    const file = new File(["RIFF"], "idea.wav", { type: "audio/wav" });
    fireEvent.change(document.querySelector("#audio-file") as HTMLInputElement, { target: { files: [file] } });
    fireEvent.click(screen.getByRole("button", { name: "上传并开始分析" }));
    expect(await screen.findByText(/请确认你有权使用这段音频/)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("restores a completed Import Run and exposes original/aligned previews", async () => {
    window.history.replaceState({}, "", "/?run=import-restored");
    vi.spyOn(window, "fetch").mockImplementation(async (input) => {
      const path = String(input);
      if (path.includes("/api/v1/imports/")) return jsonResponse(importRun("completed"));
      if (path.includes("/features")) return jsonResponse({
        request_id: ID, trace_id: ID, status: "succeeded", warnings: [],
        data: { source_audio_artifact_id: FEATURE_ID, features: [] },
      });
      throw new Error(`unexpected request ${path}`);
    });
    renderPage();
    expect(await screen.findByText("导入与对齐已完成")).toBeInTheDocument();
    expect(screen.getByText("原始上传")).toBeInTheDocument();
    expect(screen.getByText("保持音高对齐")).toBeInTheDocument();
  });

  it("restores analysis HITL and resumes the same thread with a user decision", async () => {
    window.history.replaceState({}, "", "/?run=import-restored");
    const fetchMock = vi.spyOn(window, "fetch").mockImplementation(async (input, init) => {
      const path = String(input);
      if (init?.method === "POST" && path.includes("confirm-analysis")) {
        return jsonResponse(importRun("completed"));
      }
      if (path.includes("/features")) return jsonResponse({
        request_id: ID, trace_id: ID, status: "succeeded", warnings: [],
        data: { source_audio_artifact_id: FEATURE_ID, features: [] },
      });
      return jsonResponse(importRun("analysis_confirmation_required"));
    });
    renderPage();
    expect(await screen.findByText("等待分析确认")).toBeInTheDocument();
    expect(screen.getByText("检测 BPM")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "不对齐，直接导入" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/imports/import-restored/confirm-analysis",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "skip_alignment", source_bpm: 80 }) }),
    ));
  });

  it("imports two files sequentially into one Project and refreshes the branch head", async () => {
    const events: string[] = [];
    const importBodies: Array<Record<string, unknown>> = [];
    let projectReads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      events.push(path);
      if (path === `/api/v1/projects/${ID}`) {
        const heads = [HEAD_ONE, HEAD_TWO, HEAD_THREE];
        return jsonResponse({ data: projectWorkspace(heads[Math.min(projectReads++, 2)]!) });
      }
      if (path === "/api/v1/upload-sessions") {
        const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
        const suffix = String(body.filename).startsWith("pad") ? "pad" : "pulse";
        const uploadId = suffix === "pad" ? "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa" : "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
        return jsonResponse(successEnvelope({ upload_id: uploadId, part_size_bytes: 1024, expires_at: "2026-08-21T00:00:00Z" }));
      }
      if (path.includes("/parts/")) return jsonResponse(successEnvelope({ upload_id: path.split("/")[4], part_number: 1, byte_size: 4 }));
      if (path.endsWith("/complete")) {
        const pulse = path.includes("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb");
        return jsonResponse(successEnvelope({ upload_id: pulse ? "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" : "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", source_artifact_id: pulse ? "88888888-8888-4888-8888-888888888888" : "77777777-7777-4777-8777-777777777777", byte_size: 4, detected_format: "wav", validation_status: "validated", content_hash: "a".repeat(64), replayed: false }));
      }
      if (path === `/api/v1/projects/${ID}/imports`) {
        importBodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return jsonResponse(queueImportRun(importBodies.length === 1 ? HEAD_TWO : HEAD_THREE, importBodies.length));
      }
      if (path === "/api/v1/projects") throw new Error("existing target must not create Project");
      if (path.includes("/features")) return jsonResponse({ request_id: ID, trace_id: ID, status: "succeeded", warnings: [], data: { source_audio_artifact_id: FEATURE_ID, features: [] } });
      throw new Error(`unexpected request ${path}`);
    }));

    renderPage(ID);
    const files = [new File(["RIFF"], "pad.wav", { type: "audio/wav" }), new File(["RIFF"], "pulse.wav", { type: "audio/wav" })];
    fireEvent.change(await screen.findByLabelText("选择多个 Stem"), { target: { files } });
    fireEvent.click(screen.getByLabelText("确认 pad.wav 的权利"));
    fireEvent.change(screen.getByLabelText("pulse.wav 权利声明"), { target: { value: "cc_by" } });
    fireEvent.click(screen.getByLabelText("确认 pulse.wav 的权利"));
    fireEvent.click(screen.getByRole("button", { name: "开始顺序导入" }));

    expect(await screen.findByText("2/2 Stem 已导入")).toBeInTheDocument();
    expect(importBodies).toHaveLength(2);
    expect(importBodies[0]).toMatchObject({ branch_id: BRANCH_ID, base_revision_id: HEAD_ONE });
    expect(importBodies[1]).toMatchObject({ branch_id: BRANCH_ID, base_revision_id: HEAD_TWO });
    expect(events.indexOf(`/api/v1/projects/${ID}`)).toBeLessThan(events.lastIndexOf("/api/v1/upload-sessions"));
  });

  it("stops and reloads the Project on a Revision conflict", async () => {
    let projectReads = 0;
    let uploads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === `/api/v1/projects/${ID}`) { projectReads += 1; return jsonResponse({ data: projectWorkspace(projectReads === 1 ? HEAD_ONE : HEAD_TWO) }); }
      if (path === "/api/v1/upload-sessions") { uploads += 1; return jsonResponse(successEnvelope({ upload_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", part_size_bytes: 1024, expires_at: "2026-08-21T00:00:00Z" })); }
      if (path.includes("/parts/")) return jsonResponse(successEnvelope({ upload_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", part_number: 1, byte_size: 4 }));
      if (path.endsWith("/complete")) return jsonResponse(successEnvelope({ upload_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", source_artifact_id: "77777777-7777-4777-8777-777777777777", byte_size: 4, detected_format: "wav", validation_status: "validated", content_hash: "a".repeat(64), replayed: false }));
      if (path.endsWith("/imports")) return jsonResponse({ detail: "stale base", error_code: "REVISION_CONFLICT", retryable: false }, 409);
      throw new Error(`unexpected request ${path}`);
    }));
    renderPage(ID);
    const files = [new File(["RIFF"], "one.wav"), new File(["RIFF"], "two.wav")];
    fireEvent.change(await screen.findByLabelText("选择多个 Stem"), { target: { files } });
    fireEvent.click(screen.getByLabelText("确认 one.wav 的权利"));
    fireEvent.click(screen.getByLabelText("确认 two.wav 的权利"));
    fireEvent.click(screen.getByRole("button", { name: "开始顺序导入" }));

    expect(await screen.findByText("Revision 已变化，队列已停止")).toBeInTheDocument();
    expect(projectReads).toBe(2);
    expect(uploads).toBe(1);
  });
});

function renderPage(projectId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      {projectId ? <ImportReviewPage projectId={projectId} /> : <ImportReviewPage />}
    </QueryClientProvider>,
  );
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json" } });
}

function featureData(availability: "available" | "evicted", profile: string) {
  return {
    artifact_id: FEATURE_ID,
    project_id: ID,
    source_audio_artifact_id: ID,
    feature_profile: profile,
    feature_schema_version: profile,
    availability,
    content_hash: "a".repeat(64),
    byte_size: 128,
    payload: null,
  };
}

function importRun(phase: "completed" | "analysis_confirmation_required") {
  return {
    request_id: ID,
    trace_id: ID,
    status: "succeeded",
    warnings: [],
    data: {
      thread_id: "import-restored",
      run_id: ID,
      job_id: null,
      phase,
      artifact_id: ID,
      source_artifact_id: "33333333-3333-4333-8333-333333333333",
      normalized_artifact_id: FEATURE_ID,
      revision_id: ID,
      error_code: null,
      replayed: false,
      analysis: {
        bpm: 80,
        bpm_confidence: 0.8,
        key_tonic: "A",
        key_mode: "major",
        key_confidence: 0.7,
        project_bpm: 120,
        policy_version: "import-analysis-policy.v1",
        explanation_code: "IMPORT_ANALYSIS_ACCEPTED",
      },
    },
  };
}

function projectWorkspace(headRevisionId: string) {
  return { project_id: ID, name: "Stem Session", status: "active", updated_at: "2026-08-20T08:00:00Z", active_branch_id: BRANCH_ID, head_revision_id: headRevisionId, revisions: [], runs: [], recoverable_run: null, storage_root_status: "ready" };
}

function queueImportRun(revisionId: string, index: number) {
  const artifactId = index === 1 ? "77777777-7777-4777-8777-777777777777" : "88888888-8888-4888-8888-888888888888";
  return { request_id: ID, trace_id: ID, status: "succeeded", warnings: [], data: { thread_id: `import-queue-${index}`, run_id: `99999999-9999-4999-8999-99999999999${index}`, job_id: null, phase: "completed", artifact_id: artifactId, source_artifact_id: artifactId, normalized_artifact_id: artifactId, revision_id: revisionId, error_code: null, replayed: false, analysis: null } };
}

function successEnvelope(data: unknown) {
  return { request_id: ID, trace_id: ID, status: "succeeded", warnings: [], data };
}
