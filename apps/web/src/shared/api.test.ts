import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, isUuid, parseFeatureSetEnvelope, parseImportRunEnvelope, uploadAndStartImport } from "./api";

const ID = "11111111-1111-4111-8111-111111111111";
const BRANCH_ID = "22222222-2222-4222-8222-222222222222";
const REVISION_ID = "33333333-3333-4333-8333-333333333333";

afterEach(() => vi.unstubAllGlobals());

describe("Feature API contract parser", () => {
  it("accepts the current four-state Feature DTO", () => {
    const parsed = parseFeatureSetEnvelope({
      request_id: ID,
      trace_id: ID,
      status: "succeeded",
      warnings: [],
      data: {
        source_audio_artifact_id: ID,
        features: [
          {
            artifact_id: ID,
            project_id: ID,
            source_audio_artifact_id: ID,
            feature_profile: "waveform-peaks.v1",
            feature_schema_version: "waveform-peaks.v1",
            availability: "evicted",
            content_hash: "a".repeat(64),
            byte_size: 120,
            payload: null,
          },
        ],
      },
    });
    expect(parsed.data.features[0]?.availability).toBe("evicted");
  });

  it("rejects undocumented availability values", () => {
    expect(() =>
      parseFeatureSetEnvelope({
        request_id: ID,
        trace_id: ID,
        status: "succeeded",
        warnings: [],
        data: {
          source_audio_artifact_id: ID,
          features: [{ artifact_id: ID, availability: "cached" }],
        },
      }),
    ).toThrow(ApiError);
  });

  it("validates UUID input before a request is sent", () => {
    expect(isUuid(ID)).toBe(true);
    expect(isUuid("../../audio.wav")).toBe(false);
  });
});

describe("Import Run API contract parser", () => {
  it("accepts a completed run with an analysis projection", () => {
    const parsed = parseImportRunEnvelope({
      request_id: ID,
      trace_id: ID,
      status: "succeeded",
      warnings: [],
      data: {
        thread_id: "import-abc123",
        run_id: ID,
        job_id: null,
        phase: "completed",
        artifact_id: ID,
        source_artifact_id: ID,
        normalized_artifact_id: ID,
        revision_id: ID,
        error_code: null,
        replayed: false,
        analysis: {
          bpm: 92,
          bpm_confidence: 0.8,
          key_tonic: "A",
          key_mode: "minor",
          key_confidence: 0.7,
          project_bpm: 120,
          policy_version: "import-analysis-policy.v1",
          explanation_code: "IMPORT_ANALYSIS_ACCEPTED",
        },
      },
    });
    expect(parsed.data.analysis?.bpm).toBe(92);
  });

  it("rejects out-of-range confidence rather than trusting a cast", () => {
    expect(() => parseImportRunEnvelope({
      request_id: ID,
      trace_id: ID,
      status: "succeeded",
      warnings: [],
      data: {
        thread_id: "import-abc123",
        run_id: ID,
        job_id: null,
        phase: "analysis_confirmation_required",
        artifact_id: null,
        source_artifact_id: ID,
        normalized_artifact_id: ID,
        revision_id: null,
        error_code: null,
        replayed: false,
        analysis: {
          bpm: 92,
          bpm_confidence: 1.2,
          key_tonic: "A",
          key_mode: "minor",
          key_confidence: 0.7,
          project_bpm: 120,
          policy_version: "import-analysis-policy.v1",
          explanation_code: null,
        },
      },
    })).toThrow(ApiError);
  });
});

describe("Project-targeted controlled upload", () => {
  it("uses an existing Project target without creating another Project", async () => {
    const requests: Array<{ path: string; body: unknown }> = [];
    stubUploadApi(requests);
    const file = new File(["RIFF"], "pad.wav", { type: "audio/wav" });

    const result = await uploadAndStartImport(
      file,
      { kind: "existing", project_id: ID, branch_id: BRANCH_ID, base_revision_id: REVISION_ID },
      "user_owned",
      "existing-target",
      () => undefined,
    );

    expect(requests.some((request) => request.path === "/api/v1/projects")).toBe(false);
    const imported = requests.find((request) => request.path === `/api/v1/projects/${ID}/imports`);
    expect(imported?.body).toMatchObject({ branch_id: BRANCH_ID, base_revision_id: REVISION_ID });
    expect(result.target).toEqual({ project_id: ID, branch_id: BRANCH_ID, base_revision_id: REVISION_ID });
  });

  it("preserves the single-file create-new-Project target", async () => {
    const requests: Array<{ path: string; body: unknown }> = [];
    stubUploadApi(requests, true);
    const file = new File(["RIFF"], "idea.wav", { type: "audio/wav" });

    await uploadAndStartImport(file, { kind: "new", name: "Idea Project" }, "licensed", "new-target", () => undefined);

    expect(requests.find((request) => request.path === "/api/v1/projects")?.body).toEqual({ name: "Idea Project" });
    expect(requests.find((request) => request.path === `/api/v1/projects/${ID}/imports`)?.body).toMatchObject({ branch_id: BRANCH_ID, base_revision_id: REVISION_ID });
  });
});

function stubUploadApi(requests: Array<{ path: string; body: unknown }>, allowProjectCreate = false) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : null;
    requests.push({ path, body });
    if (path === "/api/v1/projects" && allowProjectCreate) return response(apiEnvelope({ project_id: ID, active_branch_id: BRANCH_ID, root_revision_id: REVISION_ID, content_hash: "a".repeat(64), replayed: false }));
    if (path === "/api/v1/upload-sessions") return response(apiEnvelope({ upload_id: "44444444-4444-4444-8444-444444444444", part_size_bytes: 1024, expires_at: "2026-08-21T00:00:00Z" }));
    if (path.includes("/parts/")) return response(apiEnvelope({ upload_id: "44444444-4444-4444-8444-444444444444", part_number: 1, byte_size: 4 }));
    if (path.endsWith("/complete")) return response(apiEnvelope({ upload_id: "44444444-4444-4444-8444-444444444444", source_artifact_id: "55555555-5555-4555-8555-555555555555", byte_size: 4, detected_format: "wav", validation_status: "validated", content_hash: "b".repeat(64), replayed: false }));
    if (path.endsWith("/imports")) return response(importEnvelope());
    throw new Error(`unexpected request ${path}`);
  }));
}

function importEnvelope() {
  return { request_id: ID, trace_id: ID, status: "succeeded", warnings: [], data: { thread_id: "import-api-test", run_id: "66666666-6666-4666-8666-666666666666", job_id: null, phase: "completed", artifact_id: "55555555-5555-4555-8555-555555555555", source_artifact_id: "55555555-5555-4555-8555-555555555555", normalized_artifact_id: "55555555-5555-4555-8555-555555555555", revision_id: "77777777-7777-4777-8777-777777777777", error_code: null, replayed: false, analysis: null } };
}

function response(value: unknown): Response { return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } }); }
function apiEnvelope(data: unknown) { return { request_id: ID, trace_id: ID, status: "succeeded", warnings: [], data }; }
