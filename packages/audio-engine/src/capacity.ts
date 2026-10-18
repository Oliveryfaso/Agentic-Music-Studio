import type { AudioGraphSpec } from "./contracts.js";

export const RENDER_CAPACITY_POLICY = "render-capacity.v1";
export const MAX_RENDER_EVENTS = 20_000;
export const MAX_RENDER_OUTPUT_BYTES = 96 * 1024 ** 2;
export const MAX_RENDER_BUFFER_BYTES = 320 * 1024 ** 2;

/** Raw media allocation bound, not an operating-system RSS guarantee.
 * v1 callers use zero extra tail: reverb decay never extends the score window.
 */
export function estimateRenderCapacity(
  graph: AudioGraphSpec, bitDepth: 16 | 24 = 24, tailSeconds = 0,
): Readonly<{ wavBytes: number; outputLimitBytes: number; workingBufferBytes: number }> {
  if (!graph || typeof graph !== "object" ||
      !Number.isFinite(graph.durationSeconds) || graph.durationSeconds < 0.1 ||
      graph.durationSeconds > 300 || !Number.isFinite(tailSeconds) ||
      tailSeconds < 0 || tailSeconds > 8 || graph.durationSeconds + tailSeconds > 300 ||
      (graph.sampleRate !== 44100 && graph.sampleRate !== 48000) || graph.channels !== 2 ||
      (bitDepth !== 16 && bitDepth !== 24)) {
    throw new Error("RENDER_CAPACITY_INVALID");
  }
  if (!Array.isArray(graph.tracks) || graph.tracks.length < 1 || graph.tracks.length > 12) {
    throw new Error("RENDER_RESOURCE_LIMIT_EXCEEDED");
  }
  let events = 0;
  for (const track of graph.tracks) {
    if (!track || (track.kind !== "synth" && track.kind !== "sampler")) {
      throw new Error("RENDER_CAPACITY_INVALID");
    }
    const values = track.kind === "synth" ? track.notes : track.triggers;
    if (!Array.isArray(values)) throw new Error("RENDER_CAPACITY_INVALID");
    events += values.length;
  }
  if (events > MAX_RENDER_EVENTS) throw new Error("RENDER_RESOURCE_LIMIT_EXCEEDED");
  const frames = Math.ceil((graph.durationSeconds + tailSeconds) * graph.sampleRate);
  const wavBytes = 44 + frames * graph.channels * (bitDepth / 8);
  const workingBufferBytes = frames * graph.channels * 4 + 2 * wavBytes;
  if (wavBytes > MAX_RENDER_OUTPUT_BYTES || workingBufferBytes > MAX_RENDER_BUFFER_BYTES) {
    throw new Error("RENDER_RESOURCE_LIMIT_EXCEEDED");
  }
  return { wavBytes, outputLimitBytes: Math.max(1_048_576, wavBytes), workingBufferBytes };
}
