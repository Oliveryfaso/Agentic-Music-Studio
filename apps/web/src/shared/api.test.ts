import { describe, expect, it } from "vitest";

import { ApiError, isUuid, parseFeatureSetEnvelope, parseImportRunEnvelope } from "./api";

const ID = "11111111-1111-4111-8111-111111111111";

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
