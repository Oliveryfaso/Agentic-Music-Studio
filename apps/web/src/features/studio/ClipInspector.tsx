import type { ArrangementIR, EditorCommand } from "../../shared/openapi";

type Clip = ArrangementIR["tracks"][number]["clips"][number];

export function ClipInspector({ trackId, clip, onCommand }: { trackId: string; clip: Clip | null; onCommand: (command: EditorCommand) => void }) {
  if (!clip) return <section className="dock-empty"><h3>片段 Inspector</h3><p>选择一个片段以编辑 Loop、增益和淡入淡出。</p></section>;
  const set = (parameter: "loop" | "gain_db" | "fade_in_tick" | "fade_out_tick", value: boolean | number) => onCommand({ command_id: crypto.randomUUID(), command_type: "set_clip_param", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: 0, selection: { track_ids: [trackId], start_tick: clip.start_tick, end_tick: clip.start_tick + clip.duration_tick }, payload: { track_id: trackId, clip_id: clip.clip_id, parameter, value } });
  return <section className="clip-inspector" aria-label="片段 Inspector">
    <label><input type="checkbox" checked={clip.loop} onChange={(event) => set("loop", event.target.checked)} /> Loop</label>
    <label>片段增益<input type="number" defaultValue={clip.gain_db} onBlur={(event) => set("gain_db", Number(event.target.value))} /></label>
    <label>淡入 ticks<input type="number" defaultValue={clip.fade_in_tick} onBlur={(event) => set("fade_in_tick", Number(event.target.value))} /></label>
    <label>淡出 ticks<input type="number" defaultValue={clip.fade_out_tick} onBlur={(event) => set("fade_out_tick", Number(event.target.value))} /></label>
  </section>;
}
