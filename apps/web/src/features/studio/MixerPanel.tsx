import { useEffect, useRef, useState } from "react";
import type { ArrangementIR, EditorCommand } from "../../shared/openapi";
import { makePianoMixCommand, readPianoMix } from "./pianoMix";

interface MixerTrack { track_id: string; name: string; gain_db: number; pan: number; mute: boolean; solo: boolean; locked_ranges?: unknown[] }
interface Props { tracks: MixerTrack[]; pianoArrangement?: ArrangementIR; savedArrangement?: ArrangementIR; disabled?: boolean; onCommand: (command: EditorCommand) => void }

export function MixerPanel({ tracks, pianoArrangement, savedArrangement, disabled = false, onCommand }: Props) {
  const mix = pianoArrangement ? readPianoMix(pianoArrangement) : null;
  const savedMix = savedArrangement ? readPianoMix(savedArrangement) : mix;
  if (!mix) {
    if (pianoArrangement?.schema_version === "arrangement-ir.v3" || pianoArrangement?.schema_version === "arrangement-ir.v4") return <section className="mixer-panel" aria-label="混音器"><p role="alert">现有参数超出混音模式范围，无法无损启用。请保留当前版本。</p></section>;
    return <section className="mixer-panel" aria-label="混音器"><p>此旧版本保留未锁轨道的音量编辑。静音、独奏与声像需在双钢琴混音模式中使用。</p>{tracks.map(track => <article key={track.track_id}><strong>{track.name}</strong><RangeControl label={`${track.name} gain`} title="音量" value={track.gain_db} min={-60} max={6} step={0.5} disabled={disabled || Boolean(track.locked_ranges?.length)} onCommit={value => onCommand({ command_id: crypto.randomUUID(), command_type: "set_track_param", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: 0, selection: { track_ids: [track.track_id] }, payload: { track_id: track.track_id, parameter: "gain_db", value } })}/></article>)}</section>;
  }
  const anySolo = mix.tracks.some(track => track.solo);
  return <section className="mixer-panel" aria-label="混音器"><p>保存这些调整会启用双钢琴混音模式。修改先记入草稿，保存后生成新版试听；原谱音符保持锁定，本阶段不提供实时混音。</p>{mix.tracks.map(value => {
    const track = tracks.find(item => item.track_id === value.track_id)!;
    const saved = savedMix?.tracks.find(item => item.track_id === value.track_id);
    const audible = !value.mute && (!anySolo || value.solo);
    const resetAvailable = saved && (saved.gain_db !== value.gain_db || saved.pan !== value.pan || saved.mute !== value.mute || saved.solo !== value.solo);
    const patch = (changes: Parameters<typeof makePianoMixCommand>[2]) => onCommand(makePianoMixCommand(mix, value.track_id, changes));
    return <article key={value.track_id}><strong>{track.name}</strong><span>{audible ? "可听" : value.mute ? "已静音" : "被独奏排除"}</span>
      <RangeControl label={`${track.name} 音量`} title="音量" value={value.gain_db} min={-60} max={6} step={0.5} disabled={disabled} onCommit={gain_db => patch({gain_db})}/>
      <RangeControl label={`${track.name} 声像`} title="声像（左 / 右）" value={value.pan} min={-1} max={1} step={0.05} disabled={disabled} onCommit={pan => patch({pan})}/>
      <button type="button" aria-label={`${track.name} 静音`} aria-pressed={value.mute} disabled={disabled} onClick={() => patch({mute: !value.mute})}>静音</button>
      <button type="button" aria-label={`${track.name} 独奏`} aria-pressed={value.solo} disabled={disabled} onClick={() => patch({solo: !value.solo})}>独奏</button>
      <button type="button" aria-label={`${track.name} 恢复当前保存值`} disabled={disabled || !resetAvailable} onClick={() => { if(saved) patch({gain_db:saved.gain_db,pan:saved.pan,mute:saved.mute,solo:saved.solo}); }}>恢复当前保存值</button>
    </article>;
  })}<small>多个独奏可同时发声；静音优先。全部静音会生成合法的静音音频。</small></section>;
}

function RangeControl({ label, title, value, min, max, step, disabled, onCommit }: { label: string; title: string; value: number; min: number; max: number; step: number; disabled: boolean; onCommit: (value: number) => void }) {
  const [current, setCurrent] = useState(value);
  const committed = useRef(value);
  useEffect(() => { setCurrent(value); committed.current = value; }, [value]);
  const commit = (next: number) => { if (!disabled && next !== committed.current) { committed.current = next; onCommit(next); } };
  return <label>{title}<input aria-label={label} type="range" min={min} max={max} step={step} value={current} disabled={disabled} onChange={event => setCurrent(Number(event.target.value))} onPointerUp={event => commit(Number(event.currentTarget.value))} onKeyUp={event => commit(Number(event.currentTarget.value))} onBlur={event => commit(Number(event.currentTarget.value))}/><output>{current.toFixed(step < 0.1 ? 2 : 1)}</output></label>;
}
