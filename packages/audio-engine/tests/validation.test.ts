import { describe, expect, it } from "vitest";

import {
  BUILTIN_SYNTH_PRESETS,
  buildThirtySecondSpikeGraph,
  validateAudioGraphSpec,
  encodeStereoPcm24,
} from "../src/index.js";

describe("AudioGraphSpec validation", () => {
  it("accepts the representative 30-second graph", () => {
    expect(validateAudioGraphSpec(buildThirtySecondSpikeGraph()).tracks).toHaveLength(3);
  });

  it("rejects notes outside the render range", () => {
    const graph = buildThirtySecondSpikeGraph();
    const invalid = {
      ...graph,
      tracks: [
        {
          ...graph.tracks[0],
          notes: [{ midi: 60, startSeconds: 29.9, durationSeconds: 1, velocity: 0.5 }],
        },
      ],
    };
    expect(() => validateAudioGraphSpec(invalid as typeof graph)).toThrow(
      "AUDIO_GRAPH_INVALID:pad.note.range",
    );
  });

  it("accepts every versioned built-in synth preset", () => {
    const graph = buildThirtySecondSpikeGraph();
    const synthTrack = graph.tracks.find((track) => track.kind === "synth");
    expect(synthTrack).toBeDefined();
    if (synthTrack === undefined) {
      throw new Error("TEST_FIXTURE_SYNTH_TRACK_MISSING");
    }
    for (const presetId of Object.keys(BUILTIN_SYNTH_PRESETS)) {
      const candidate = {
        ...graph,
        tracks: [{ ...synthTrack, presetId }],
      };
      expect(() => validateAudioGraphSpec(candidate as typeof graph)).not.toThrow();
    }
  });

  it("encodes canonical stereo PCM24 with a correct RIFF header", () => {
    const left = new Float32Array([-1, -0.5, 0, 0.5, 1]);
    const right = new Float32Array([1, 0.5, 0, -0.5, -1]);
    const buffer = {
      numberOfChannels: 2,
      length: left.length,
      sampleRate: 48000,
      getChannelData: (channel: number) => (channel === 0 ? left : right),
    } as AudioBuffer;

    const wav = encodeStereoPcm24(buffer);
    const view = new DataView(wav.buffer, wav.byteOffset, wav.byteLength);

    expect(String.fromCharCode(...wav.subarray(0, 4))).toBe("RIFF");
    expect(view.getUint16(22, true)).toBe(2);
    expect(view.getUint32(24, true)).toBe(48000);
    expect(view.getUint16(34, true)).toBe(24);
    expect(view.getUint32(40, true)).toBe(left.length * 2 * 3);
  });
});
