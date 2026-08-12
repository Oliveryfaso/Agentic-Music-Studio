import {
  AUDIO_ENGINE_VERSION,
  AUDIO_GRAPH_SCHEMA_VERSION,
  type AudioGraphSpec,
  type NoteSpec,
} from "./contracts.js";

function repeatingNotes(
  pitches: readonly number[],
  stepSeconds: number,
  durationSeconds: number,
  totalSeconds: number,
  velocity: number,
): readonly NoteSpec[] {
  const notes: NoteSpec[] = [];
  let index = 0;
  for (let start = 0; start + durationSeconds <= totalSeconds; start += stepSeconds) {
    notes.push({
      midi: pitches[index % pitches.length] ?? pitches[0] ?? 60,
      startSeconds: start,
      durationSeconds,
      velocity,
    });
    index += 1;
  }
  return notes;
}

export function buildThirtySecondSpikeGraph(): AudioGraphSpec {
  return {
    schemaVersion: AUDIO_GRAPH_SCHEMA_VERSION,
    engineVersion: AUDIO_ENGINE_VERSION,
    durationSeconds: 30,
    sampleRate: 48000,
    channels: 2,
    masterGainDb: -5,
    reverbDecaySeconds: 2.2,
    tracks: [
      {
        kind: "synth",
        trackId: "pad",
        name: "Warm Pad",
        presetId: "warm_pad",
        gainDb: -10,
        pan: -0.15,
        eq: { lowDb: -2, midDb: 0, highDb: 1 },
        reverbSend: 0.28,
        notes: repeatingNotes([50, 57, 62, 65], 3.75, 3.5, 30, 0.48),
      },
      {
        kind: "synth",
        trackId: "pluck",
        name: "Glass Pluck",
        presetId: "glass_pluck",
        gainDb: -13,
        pan: 0.2,
        eq: { lowDb: -5, midDb: 1, highDb: 2 },
        reverbSend: 0.18,
        notes: repeatingNotes([74, 77, 81, 69], 0.75, 0.22, 30, 0.38),
      },
      {
        kind: "sampler",
        trackId: "click",
        name: "Built-in Click",
        sampleId: "builtin:click",
        sampleUrl: "/assets/builtin-click.wav",
        gainDb: -18,
        pan: 0,
        eq: { lowDb: -4, midDb: 0, highDb: 1 },
        reverbSend: 0.04,
        triggers: Array.from({ length: 40 }, (_, index) => ({
          startSeconds: index * 0.75,
          gain: index % 4 === 0 ? 0.8 : 0.45,
        })),
      },
    ],
  };
}
