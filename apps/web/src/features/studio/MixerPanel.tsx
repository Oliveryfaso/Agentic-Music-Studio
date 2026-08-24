import { useState } from "react";
import type { EditorCommand } from "../../shared/openapi";

interface MixerTrack { track_id: string; name: string; gain_db: number; pan: number; mute: boolean; solo: boolean }

export function MixerPanel({ tracks, onCommand }: { tracks: MixerTrack[]; onCommand: (command: EditorCommand) => void }) {
  const [gains, setGains] = useState<Record<string, number>>(() => Object.fromEntries(tracks.map((track) => [track.track_id, track.gain_db])));
  const command = (track: MixerTrack, parameter: "gain_db" | "pan" | "mute" | "solo", value: number | boolean) => onCommand({ command_id: crypto.randomUUID(), command_type: "set_track_param", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: 0, selection: { track_ids: [track.track_id] }, payload: { track_id: track.track_id, parameter, value } });
  return <section className="mixer-panel" aria-label="混音器">{tracks.map((track) => <article key={track.track_id}>
    <strong>{track.name}</strong>
    <label>Gain<input aria-label={`${track.name} gain`} type="range" min={-24} max={6} step={0.5} value={gains[track.track_id] ?? track.gain_db} onChange={(event) => setGains({ ...gains, [track.track_id]: Number(event.target.value) })} onPointerUp={() => command(track, "gain_db", gains[track.track_id] ?? track.gain_db)} /></label>
    <button type="button" aria-pressed={track.mute} onClick={() => command(track, "mute", !track.mute)}>静音</button>
    <button type="button" aria-pressed={track.solo} onClick={() => command(track, "solo", !track.solo)}>独奏</button>
  </article>)}</section>;
}
