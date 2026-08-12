import { describe, expect, it } from "vitest";

import {
  BUILTIN_SYNTH_PRESETS,
  buildThirtySecondSpikeGraph,
  validateAudioGraphSpec,
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
});
