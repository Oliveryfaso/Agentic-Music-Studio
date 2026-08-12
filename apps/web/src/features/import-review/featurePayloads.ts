export interface WaveformPeak {
  minimum: number;
  maximum: number;
}

export interface WaveformPayload {
  schema_version: "waveform-peaks.v1";
  sample_rate_hz: number;
  source_channels: number;
  source_frames: number;
  bucket_size_frames: number;
  peaks: WaveformPeak[];
}

export interface AnalysisPayload {
  schema_version: "imported-audio-analysis.v1";
  analysis_version: "import-analysis.v1";
  bpm: number | null;
  bpm_confidence: number;
  key_tonic: string | null;
  key_mode: "major" | "minor" | null;
  key_confidence: number;
  analyzed_seconds: number;
}

export function parseWaveformPayload(value: Record<string, unknown>): WaveformPayload | null {
  if (
    value.schema_version !== "waveform-peaks.v1" ||
    !isPositiveNumber(value.sample_rate_hz) ||
    !isPositiveNumber(value.source_channels) ||
    !isPositiveNumber(value.source_frames) ||
    !isPositiveNumber(value.bucket_size_frames) ||
    !Array.isArray(value.peaks) ||
    value.peaks.length === 0
  ) {
    return null;
  }
  const peaks: WaveformPeak[] = [];
  for (const peak of value.peaks) {
    if (
      typeof peak !== "object" ||
      peak === null ||
      !("minimum" in peak) ||
      !("maximum" in peak) ||
      typeof peak.minimum !== "number" ||
      typeof peak.maximum !== "number"
    ) {
      return null;
    }
    peaks.push({ minimum: peak.minimum, maximum: peak.maximum });
  }
  return {
    schema_version: "waveform-peaks.v1",
    sample_rate_hz: value.sample_rate_hz,
    source_channels: value.source_channels,
    source_frames: value.source_frames,
    bucket_size_frames: value.bucket_size_frames,
    peaks,
  };
}

export function parseAnalysisPayload(value: Record<string, unknown>): AnalysisPayload | null {
  if (
    value.schema_version !== "imported-audio-analysis.v1" ||
    value.analysis_version !== "import-analysis.v1" ||
    (value.bpm !== null && typeof value.bpm !== "number") ||
    typeof value.bpm_confidence !== "number" ||
    (value.key_tonic !== null && typeof value.key_tonic !== "string") ||
    (value.key_mode !== null && value.key_mode !== "major" && value.key_mode !== "minor") ||
    typeof value.key_confidence !== "number" ||
    typeof value.analyzed_seconds !== "number"
  ) {
    return null;
  }
  return value as unknown as AnalysisPayload;
}

function isPositiveNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}
