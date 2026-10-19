import type { AudioGraphSpecV4, PianoMixTrackSpec } from "../../src/contracts.js";

export function mixGraph(audible = [true, false]): AudioGraphSpecV4 {
  return {
    schemaVersion: "audio-graph-spec.v4", engineVersion: "motif-forge-audio-engine.v4",
    durationSeconds: 0.1, sampleRate: 48000, channels: 2,
    masterGainDb: -5, reverbDecaySeconds: 2.4,
    expectedSilence: !audible.some(Boolean),
    tracks: audible.map((value, index): PianoMixTrackSpec => ({
      trackId: `piano-${index}`, name: `Piano ${index}`, kind: "multisample",
      gainDb: -10, pan: index ? 1 : -1, audible: value,
      eq: { lowDb: 0, midDb: 0, highDb: 0 }, reverbSend: 0,
      instrumentPack: { packId: "freepats:upright-kw-small", packVersion: "2019-07-03.motif1", manifestSha256: "a".repeat(64) },
      notes: [{ noteId: `note-${index}`, midi: 60, velocity: 72, startSeconds: 0.01, gateSeconds: 0.05, detuneCents: 0 }],
    })),
  };
}
