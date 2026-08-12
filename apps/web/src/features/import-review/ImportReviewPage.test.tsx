import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ImportReviewPage } from "./ImportReviewPage";

const ID = "11111111-1111-4111-8111-111111111111";
const FEATURE_ID = "22222222-2222-4222-8222-222222222222";

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
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><ImportReviewPage /></QueryClientProvider>);
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
