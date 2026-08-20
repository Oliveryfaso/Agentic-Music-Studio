import { describe, expect, it } from "vitest";

import type { ArrangementIR } from "../../shared/openapi";
import { projectTimeline } from "./timelineProjection";

describe("Arrangement timeline projection", () => {
  it("maps PPQ ticks to bars, pixels, and media seconds while preserving track order", () => {
    const projection = projectTimeline(arrangement(), 100);

    expect(projection.ticksPerBar).toBe(1920);
    expect(projection.totalBars).toBe(2);
    expect(projection.widthPixels).toBe(200);
    expect(projection.tickToPixels(1920)).toBe(100);
    expect(projection.tickToSeconds(960)).toBe(1);
    expect(projection.sections.map((section) => section.label)).toEqual(["Opening", "Resolve"]);
    expect(projection.tracks.map((track) => track.name)).toEqual([
      "A very long atmospheric pad track name that must not widen the page",
      "Pulse",
    ]);
    expect(projection.tracks[0]?.clips.map((clip) => clip.startTick)).toEqual([0, 1920]);
  });

  it("uses the persisted 3/4 meter when deriving bar width", () => {
    const ir = arrangement();
    ir.time_signature_map = [{ tick: 0, numerator: 3, denominator: 4 }];

    const projection = projectTimeline(ir, 96);

    expect(projection.ticksPerBar).toBe(1440);
    expect(projection.tickToPixels(1440)).toBe(96);
    expect(projection.totalBars).toBe(3);
  });
});

function arrangement(): ArrangementIR {
  return {
    schema_version: "arrangement-ir.v1",
    project_id: "11111111-1111-4111-8111-111111111111",
    ppq: 480,
    sample_rate: 48000,
    tempo_map: [{ tick: 0, bpm: 120 }],
    time_signature_map: [{ tick: 0, numerator: 4, denominator: 4 }],
    key_map: [],
    markers: [],
    provenance: [],
    sections: [
      { section_id: "21111111-1111-4111-8111-111111111111", label: "Opening", start_tick: 0, end_tick: 1920, energy: 0.25, function: "establish" },
      { section_id: "31111111-1111-4111-8111-111111111111", label: "Resolve", start_tick: 1920, end_tick: 3840, energy: 0.2, function: "resolve" },
    ],
    tracks: [
      {
        track_id: "41111111-1111-4111-8111-111111111111",
        name: "A very long atmospheric pad track name that must not widen the page",
        track_type: "instrument",
        role: "harmony",
        instrument_ref: "warm-pad.v1",
        gain_db: 0,
        pan: 0,
        mute: false,
        solo: false,
        locked_ranges: [],
        clips: [noteClip("61111111-1111-4111-8111-111111111111", 1920), noteClip("51111111-1111-4111-8111-111111111111", 0)],
      },
      {
        track_id: "71111111-1111-4111-8111-111111111111",
        name: "Pulse",
        track_type: "instrument",
        role: "rhythm",
        instrument_ref: "soft-pulse.v1",
        gain_db: -3,
        pan: 0,
        mute: false,
        solo: false,
        locked_ranges: [],
        clips: [],
      },
    ],
  };
}

function noteClip(clipId: string, startTick: number): ArrangementIR["tracks"][number]["clips"][number] {
  return {
    clip_id: clipId,
    clip_type: "note",
    start_tick: startTick,
    duration_tick: 960,
    loop: false,
    gain_db: 0,
    pan: 0,
    fade_in_tick: 0,
    fade_out_tick: 0,
    notes: [],
  };
}
