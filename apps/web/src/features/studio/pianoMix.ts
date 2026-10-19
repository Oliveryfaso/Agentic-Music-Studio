import type { components } from "../../generated/api-schema";
import type { ArrangementIR, EditorCommand } from "../../shared/openapi";

export type PianoMixState = components["schemas"]["PianoMixState"];
export type PianoTrackMix = components["schemas"]["PianoTrackMix"];

/** Read the effective mix without changing the protected musical Track objects. */
export function readPianoMix(arrangement: ArrangementIR): PianoMixState | null {
  if (arrangement.schema_version === "arrangement-ir.v4" || arrangement.schema_version === "arrangement-ir.v5") return structuredClone(arrangement.piano_mix);
  if (arrangement.schema_version !== "arrangement-ir.v3" || arrangement.tracks.length !== 2) return null;
  if (arrangement.tracks.some(track => !Number.isFinite(track.gain_db) || track.gain_db < -60 || track.gain_db > 6 || !Number.isFinite(track.pan) || Math.abs(track.pan) > 1 || Object.values(track.eq ?? {}).some(value => !Number.isFinite(value) || Math.abs(value) > 12))) return null;
  return { schema_version: "piano-mix.v1", tracks: arrangement.tracks.map(track => ({ track_id: track.track_id, gain_db: track.gain_db, pan: track.pan, mute: track.mute, solo: track.solo })) };
}

export function makePianoMixCommand(mix: PianoMixState, trackId: string, patch: Partial<Omit<PianoTrackMix, "track_id">>): EditorCommand {
  return { command_id: crypto.randomUUID(), command_type: "set_piano_mix", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: 0, selection: { track_ids: mix.tracks.map(track => track.track_id) }, payload: { mix: { ...mix, tracks: mix.tracks.map(track => track.track_id === trackId ? { ...track, ...patch } : { ...track }) } } };
}
