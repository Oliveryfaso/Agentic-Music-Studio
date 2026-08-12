import { describe, expect, it } from "vitest";

import { parseAnalysisPayload, parseWaveformPayload } from "./featurePayloads";

describe("Feature payload parsers", () => {
  it("parses deterministic waveform buckets", () => {
    const result = parseWaveformPayload({
      schema_version: "waveform-peaks.v1",
      sample_rate_hz: 48_000,
      source_channels: 2,
      source_frames: 96_000,
      bucket_size_frames: 100,
      peaks: [{ minimum: -1200, maximum: 1400 }],
    });
    expect(result?.peaks).toHaveLength(1);
  });

  it("rejects a malformed analysis profile", () => {
    expect(
      parseAnalysisPayload({
        schema_version: "imported-audio-analysis.v1",
        analysis_version: "unknown",
      }),
    ).toBeNull();
  });
});
