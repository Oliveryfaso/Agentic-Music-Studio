import { useEffect, useRef, useState, type ReactNode } from "react";
import type { ArrangementIR, EditorCommand } from "../../shared/openapi";
import { PianoEqPanel } from "./PianoEqPanel";
import { makePianoMixCommand, readPianoMix } from "./pianoMix";

interface MixerTrack { track_id: string; name: string; gain_db: number; pan: number; mute: boolean; solo: boolean; locked_ranges?: unknown[] }
interface Props { tracks: MixerTrack[]; pianoArrangement?: ArrangementIR; savedArrangement?: ArrangementIR; disabled?: boolean; onCommand: (command: EditorCommand) => void; selectedTrackId?: string; onSelectTrack?: (id: string) => void; output?: ReactNode }
export function MixerPanel({ tracks, pianoArrangement, savedArrangement, disabled = false, onCommand, selectedTrackId, onSelectTrack, output }: Props) {
  const [localId, setLocalId] = useState(tracks[0]?.track_id ?? "");
  const id = tracks.some(track => track.track_id === (selectedTrackId ?? localId)) ? (selectedTrackId ?? localId) : tracks[0]?.track_id ?? "";
  const choose = (next: string) => { setLocalId(next); onSelectTrack?.(next); };
  const mix = pianoArrangement ? readPianoMix(pianoArrangement) : null;
  const savedMix = savedArrangement ? readPianoMix(savedArrangement) : mix;
  if (!mix) {
    if (pianoArrangement && ["arrangement-ir.v3", "arrangement-ir.v4", "arrangement-ir.v5"].includes(pianoArrangement.schema_version)) return <section className="mixer-panel" aria-label="混音器"><p role="alert">现有参数超出混音模式范围，无法无损启用。请保留当前版本。</p></section>;
    return <section className="mixer-panel" aria-label="混音器"><p>旧版混音 · 仅音量</p><div className="channel-bank">{tracks.map((track,index) => <article className="channel-strip" key={track.track_id}><strong>{String(index+1).padStart(2,"0")} · {track.name}</strong><RangeControl vertical label={`${track.name} gain`} title="音量" value={track.gain_db} min={-60} max={6} step={0.5} disabled={disabled || Boolean(track.locked_ranges?.length)} onCommit={value => onCommand({ command_id: crypto.randomUUID(), command_type: "set_track_param", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: 0, selection: { track_ids: [track.track_id] }, payload: { track_id: track.track_id, parameter: "gain_db", value } })}/></article>)}</div></section>;
  }
  const anySolo = mix.tracks.some(track => track.solo);
  const audible = mix.tracks.filter(track => !track.mute && (!anySolo || track.solo));
  return <section className="mixer-panel" aria-label="混音器">
    <div className="mixer-heading"><strong>混音</strong><span className="status-pill">草稿参数 · 保存后渲染</span><details className="mix-help"><summary aria-label="混音帮助">帮助</summary><p>调整先记入草稿。保存后，在导出页生成新版试听；推子不会实时改变当前播放器。多个独奏可同时发声，静音优先。</p></details></div>
    {audible.length === 0 && <p className="mix-silence" role="status">草稿：全部静音</p>}
    <div className="mix-console"><div className="channel-bank">{mix.tracks.map((value,index) => {
      const track = tracks.find(item => item.track_id === value.track_id);
      if (!track) return null;
      const saved = savedMix?.tracks.find(item => item.track_id === value.track_id);
      const heard = audible.some(item => item.track_id === value.track_id);
      const resetAvailable = saved && (saved.gain_db !== value.gain_db || saved.pan !== value.pan || saved.mute !== value.mute || saved.solo !== value.solo);
      const patch = (changes: Parameters<typeof makePianoMixCommand>[2]) => onCommand(makePianoMixCommand(mix, value.track_id, changes));
      const number = String(index + 1).padStart(2,"0");
      return <article className="channel-strip" data-channel={index % 2} data-selected={id === value.track_id} key={value.track_id}>
        <button className="channel-identity" type="button" aria-label={`选择音轨 ${number} ${track.name}`} aria-pressed={id === value.track_id} onClick={() => choose(value.track_id)}><span>{number} · {track.locked_ranges?.length ? "锁定素材" : "乐器"}</span><strong title={track.name}>{track.name}</strong></button>
        <button className="channel-eq" type="button" onClick={() => choose(value.track_id)} aria-label={`${track.name} EQ`}>EQ</button>
        <RangeControl label={`${track.name} 声像`} title="声像" value={value.pan} min={-1} max={1} step={0.05} disabled={disabled} onCommit={pan => patch({pan})}/>
        <div className="channel-switches"><button type="button" title="静音" aria-label={`${track.name} 静音`} aria-pressed={value.mute} disabled={disabled} onClick={() => patch({mute: !value.mute})}>M</button><button type="button" title="独奏" aria-label={`${track.name} 独奏`} aria-pressed={value.solo} disabled={disabled} onClick={() => patch({solo: !value.solo})}>S</button></div>
        <RangeControl vertical label={`${track.name} 音量`} title="音量" value={value.gain_db} min={-60} max={6} step={0.5} disabled={disabled} onCommit={gain_db => patch({gain_db})}/>
        <span className="channel-state">{heard ? "输出" : value.mute ? "已静音" : "Solo 排除"}</span>
        <button className="channel-restore" type="button" aria-label={`${track.name} 恢复当前保存值`} title="还原到保存版" disabled={disabled || !resetAvailable} onClick={() => { if(saved) patch({gain_db:saved.gain_db,pan:saved.pan,mute:saved.mute,solo:saved.solo}); }}>还原</button>
      </article>;
    })}</div><div className="mix-detail">{pianoArrangement && <PianoEqPanel arrangement={pianoArrangement} savedArrangement={savedArrangement ?? pianoArrangement} disabled={disabled} onCommand={onCommand} selectedTrackId={id} onSelectTrack={choose}/>} {output}</div></div>
  </section>;
}

function RangeControl({ label, title, value, min, max, step, disabled, onCommit, vertical = false }: { label: string; title: string; value: number; min: number; max: number; step: number; disabled: boolean; onCommit: (value: number) => void; vertical?: boolean }) {
  const [current, setCurrent] = useState(value);
  const committed = useRef(value);
  useEffect(() => { setCurrent(value); committed.current = value; }, [value]);
  const commit = (next: number) => { if (!disabled && next !== committed.current) { committed.current = next; onCommit(next); } };
  const formatted = vertical ? `${current.toFixed(1)} dB` : current === 0 ? "C" : `${current < 0 ? "L" : "R"}${Math.round(Math.abs(current)*100)}`;
  return <label className={vertical ? "channel-fader" : "channel-pan"}><span>{title}</span><output>{formatted}</output><input aria-label={label} aria-orientation={vertical ? "vertical" : "horizontal"} aria-valuetext={formatted} type="range" min={min} max={max} step={step} value={current} disabled={disabled} onChange={event => setCurrent(Number(event.target.value))} onPointerUp={event => commit(Number(event.currentTarget.value))} onKeyUp={event => commit(Number(event.currentTarget.value))} onBlur={event => commit(Number(event.currentTarget.value))}/></label>;
}
