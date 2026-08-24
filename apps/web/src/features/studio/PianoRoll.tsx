import { useEffect, useRef, useState } from "react";
import type { ArrangementIR, EditorCommand } from "../../shared/openapi";

type NoteClip = Extract<ArrangementIR["tracks"][number]["clips"][number], { clip_type: "note" }>;

export function PianoRoll({ trackId, clip, onCommand }: { trackId: string; clip: NoteClip; onCommand: (command: EditorCommand) => void }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const note = clip.notes[0];
  const [pitch, setPitch] = useState(note?.pitch ?? 60);
  useEffect(() => {
    const context = canvas.current?.getContext("2d");
    if (!context) return;
    context.fillStyle = "#111827"; context.fillRect(0, 0, 560, 160);
    context.strokeStyle = "#273246";
    for (let row = 0; row < 12; row += 1) { context.beginPath(); context.moveTo(0, row * 13); context.lineTo(560, row * 13); context.stroke(); }
    context.fillStyle = "#62e6ff";
    clip.notes.forEach((item) => context.fillRect(item.start_tick / 4, (72 - item.pitch) * 6, Math.max(8, item.duration_tick / 4), 5));
  }, [clip.notes]);
  if (!note) return <section className="dock-empty"><h3>钢琴卷帘</h3><p>所选片段没有音符。</p></section>;
  const commitPitch = () => onCommand({ command_id: crypto.randomUUID(), command_type: "update_notes", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: 0, selection: { track_ids: [trackId], start_tick: clip.start_tick, end_tick: clip.start_tick + clip.duration_tick }, payload: { track_id: trackId, clip_id: clip.clip_id, updates: [{ note_id: note.note_id, pitch }] } });
  return <section className="piano-roll" aria-label="钢琴卷帘">
    <canvas ref={canvas} width={560} height={160} aria-label="音符网格" />
    <label>音高<input aria-label="音高" type="number" min={0} max={127} value={pitch} onChange={(event) => setPitch(Number(event.target.value))} onBlur={commitPitch} /></label>
  </section>;
}
