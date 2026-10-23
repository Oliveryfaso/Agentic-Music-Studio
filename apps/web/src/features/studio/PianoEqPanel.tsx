import {useEffect, useMemo, useRef, useState} from "react";
import type {KeyboardEvent} from "react";
import {eqResponseDb, type PianoEqProfile, type PianoEqSettings} from "../../../../../packages/audio-engine/src/piano-eq";
import type {ArrangementIR, EditorCommand} from "../../shared/openapi";
import {eqProfileFor, makePianoEqCommand, readPianoEq, type PianoTrackEq} from "./pianoEq";

type GainKey="low_gain_db"|"mid_gain_db"|"high_gain_db";
type Patch=Partial<Pick<PianoTrackEq,GainKey|"bypass">>;
interface Props {arrangement:ArrangementIR; savedArrangement:ArrangementIR; disabled?:boolean; onCommand:(command:EditorCommand)=>void;selectedTrackId?:string;onSelectTrack?:(id:string)=>void}
const BANDS=[{key:"low_gain_db",name:"低频"},{key:"mid_gain_db",name:"中频"},{key:"high_gain_db",name:"高频"}] as const;
const FREQUENCIES=Array.from({length:160},(_,i)=>20*1000**(i/159));
function settings(track:PianoTrackEq):PianoEqSettings {
 const {track_id:_id,...value}=track;return value;
}
function sameEq(a:PianoEqSettings,b:PianoEqSettings):boolean {
 return a.bypass===b.bypass&&a.low_gain_db===b.low_gain_db&&a.mid_gain_db===b.mid_gain_db&&a.high_gain_db===b.high_gain_db;
}

export function PianoEqPanel({arrangement,savedArrangement,disabled=false,onCommand,selectedTrackId,onSelectTrack}:Props){
 const state=readPianoEq(arrangement),saved=readPianoEq(savedArrangement);
 const [selectedId,setSelectedId]=useState(arrangement.tracks[0]?.track_id??"");
 const [preview,setPreview]=useState<{trackId:string;patch:Patch}|null>(null);
 const selected=state?.tracks.find(track=>track.track_id===(selectedTrackId??selectedId))??state?.tracks[0];
 const id=selected?.track_id??"",track=arrangement.tracks.find(item=>item.track_id===id);
 const profile=eqProfileFor(arrangement);
 if((savedArrangement.schema_version!=="arrangement-ir.v4"&&savedArrangement.schema_version!=="arrangement-ir.v5")||!state||!selected||!track)return <section className="piano-eq-panel eq-unavailable"><p>先保存双钢琴基础混音，再启用三段 EQ。</p></section>;
 const authoritative=settings(selected);
 const visible={...authoritative,...(preview?.trackId===id?preview.patch:{})};
 const savedTrack=saved?.tracks.find(item=>item.track_id===id);
 const patch=(change:Patch)=>{setPreview(null);onCommand(makePianoEqCommand(state,id,change));};
 const flat=!authoritative.bypass&&BANDS.every(band=>authoritative[band.key]===0);
 const canRestore=savedTrack&&!sameEq(authoritative,settings(savedTrack));
 const labels=[`低架 ${profile.low_frequency_hz} Hz`,`峰值 ${profile.mid_frequency_hz/1000} kHz · Q ${profile.mid_q}`,`高架 ${profile.high_frequency_hz/1000} kHz`];
 return <section className="piano-eq-panel" aria-label="三段 EQ">
  <div className="eq-heading"><div><h3>三段 EQ</h3></div>
   <label>作用轨道<select aria-label="EQ 作用轨道" value={id} disabled={disabled} onChange={event=>{setPreview(null);setSelectedId(event.target.value);onSelectTrack?.(event.target.value);}}>{arrangement.tracks.map(item=><option key={item.track_id} value={item.track_id}>{item.name}</option>)}</select></label>
  </div>
  <div className="eq-control-grid">{BANDS.map((band,index)=><div className="eq-band" key={id+band.key}>
   <strong>{index+1} · {band.name}</strong>
   <EqGainControl name={`${track.name} ${band.name} EQ`} value={visible[band.key]} disabled={disabled}
    onPreview={value=>setPreview(value===null?null:{trackId:id,patch:{[band.key]:value}})} onCommit={value=>patch({[band.key]:value})}/>
   <small>{labels[index]}</small>
  </div>)}</div>
  <div className="eq-actions">
   <button type="button" aria-label="旁路 EQ" aria-pressed={authoritative.bypass} disabled={disabled} onClick={()=>patch({bypass:!authoritative.bypass})}>{authoritative.bypass?"EQ 已旁路":"旁路 EQ"}</button>
   <button type="button" disabled={disabled||flat} onClick={()=>patch({low_gain_db:0,mid_gain_db:0,high_gain_db:0,bypass:false})}>三段归零</button>
   <button type="button" disabled={disabled||!canRestore} onClick={()=>{if(savedTrack)patch(settings(savedTrack));}}>恢复保存的 EQ</button>
  </div>
  <EqCurve eq={visible} profile={profile}/>
 </section>;
}

function EqGainControl({name,value,disabled,onPreview,onCommit}:{name:string;value:number;disabled:boolean;onPreview:(value:number|null)=>void;onCommit:(value:number)=>void}){
 const gesture=useRef<{pointerId:number;y:number;value:number;step:number;current:number}|null>(null);
 const keyGesture=useRef<{base:number;current:number}|null>(null);
 const numberInput=useRef<HTMLInputElement>(null);
 const [text,setText]=useState(String(value)),[error,setError]=useState(false);
 const lastCommit=useRef(value);
 useEffect(()=>{setText(String(value));setError(false);lastCommit.current=value;},[value]);
 const cancel=()=>{gesture.current=null;keyGesture.current=null;onPreview(null);};
 const commit=(next:number)=>{onPreview(null);if(!disabled&&next!==lastCommit.current){lastCommit.current=next;onCommit(next);}};
 const numeric=()=>{
  if(disabled)return;
  const next=Number(text);
  if(text.trim()===""||!Number.isFinite(next)||next < -12||next > 12){setError(true);return;}
  setError(false);commit(next);
 };
 const finishGesture=(next:number,base:number)=>{onPreview(null);if(!disabled&&next!==base){lastCommit.current=next;onCommit(next);}};
 const finishKey=()=>{const pending=keyGesture.current;keyGesture.current=null;if(pending)finishGesture(pending.current,pending.base);};
 const bounded=(next:number)=>Math.max(-12,Math.min(12,Math.round(next*10)/10));
 const keyboard=(event:KeyboardEvent<HTMLDivElement>)=>{
  if(disabled||gesture.current)return;
  const current=keyGesture.current?.current??value;
  const step=event.shiftKey?.1:.5;
  const next=event.key==="Home"?-12:event.key==="End"?12:event.key==="PageUp"?current+3:event.key==="PageDown"?current-3:
   event.key==="ArrowUp"||event.key==="ArrowRight"?current+step:event.key==="ArrowDown"||event.key==="ArrowLeft"?current-step:null;
  if(event.key==="Escape"){event.preventDefault();cancel();return;}
  if(next!==null){event.preventDefault();keyGesture.current={base:keyGesture.current?.base??value,current:bounded(next)};onPreview(bounded(next));}
 };
 const move=(y:number)=>{const current=gesture.current;if(!current)return value;return bounded(Math.round((current.value+(current.y-y)/8)/current.step)*current.step);};
 return <>
  <div className="eq-dial" role="slider" tabIndex={disabled?-1:0} aria-label={`${name} 增益`} aria-valuemin={-12} aria-valuemax={12} aria-valuenow={value} aria-valuetext={`${value.toFixed(1)} dB`} aria-orientation="vertical" aria-disabled={disabled}
   onKeyDown={keyboard} onKeyUp={event=>{if(["ArrowUp","ArrowDown","ArrowLeft","ArrowRight","Home","End","PageUp","PageDown"].includes(event.key))finishKey();}} onDoubleClick={()=>{if(!disabled){numberInput.current?.focus();numberInput.current?.select();}}}
   onPointerDown={event=>{if(disabled||event.button!==0||gesture.current||keyGesture.current)return;event.preventDefault();event.currentTarget.focus();gesture.current={pointerId:event.pointerId,y:event.clientY,value,step:event.shiftKey?.1:.5,current:value};event.currentTarget.setPointerCapture?.(event.pointerId);}}
   onPointerMove={event=>{if(gesture.current?.pointerId!==event.pointerId)return;const next=move(event.clientY);gesture.current.current=next;onPreview(next);}}
   onPointerUp={event=>{if(gesture.current?.pointerId!==event.pointerId)return;const next=move(event.clientY),base=gesture.current.value;gesture.current=null;if(event.currentTarget.hasPointerCapture?.(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);finishGesture(next,base);}}
   onPointerCancel={cancel} onLostPointerCapture={()=>{if(gesture.current)cancel();}} onBlur={()=>{if(gesture.current)cancel();else finishKey();}}>
   <span className="eq-dial-face" aria-hidden="true"><span style={{transform:`rotate(${value/12*135}deg)`}}/></span>
  </div>
  <label className="eq-number"><input ref={numberInput} type="number" min={-12} max={12} step={.1} inputMode="decimal" aria-label={`${name} 数值`} aria-invalid={error} value={text} disabled={disabled}
   onChange={event=>{setText(event.target.value);setError(false);}} onBlur={numeric}
   onKeyDown={event=>{if(event.key==="Enter"){event.preventDefault();numeric();}else if(event.key==="Escape"){event.preventDefault();setText(String(value));setError(false);}}}/><span>dB</span></label>
  {error&&<span className="field-error" role="alert">请输入 −12 到 +12 dB，原参数保持。</span>}
 </>;
}

function EqCurve({eq,profile}:{eq:PianoEqSettings;profile:PianoEqProfile}){
 const curves=useMemo(()=>{
  const values=FREQUENCIES.map(hz=>eqResponseDb(eq,profile,hz));
  const path=(points:number[])=>points.map((db,index)=>`${index?"L":"M"}${(40+index/159*580).toFixed(2)},${(100-db*3).toFixed(2)}`).join(" ");
  return {active:path(values),ghost:eq.bypass?path(FREQUENCIES.map(hz=>eqResponseDb({...eq,bypass:false},profile,hz))):null,boost:Math.max(...values)};
 },[eq.bypass,eq.low_gain_db,eq.mid_gain_db,eq.high_gain_db,profile]);
 return <figure className="eq-response"><figcaption>{eq.bypass?"EQ 已旁路：实线为 0 dB，虚线保留原设置。":"EQ 响应：推子前的参数增减，不是音频频谱。"}</figcaption>
  <svg viewBox="0 0 640 208" role="img" aria-label="三段 EQ 响应曲线">
   {[-24,-12,0,12,24].map(db=><g key={db}><line x1={40} y1={100-db*3} x2={620} y2={100-db*3} className="eq-grid-line"/><text x={32} y={104-db*3} textAnchor="end">{db>0?"+":""}{db}</text></g>)}
   {[20,100,1000,10000,20000].map(hz=><text key={hz} x={40+Math.log10(hz/20)/3*580} y={196} textAnchor="middle">{hz>=1000?hz/1000+"k":hz}</text>)}
   {curves.ghost&&<path d={curves.ghost} className="eq-response-ghost"/>}<path d={curves.active} className="eq-response-line"/>
   <text x={5} y={15}>dB</text><text x={625} y={207} textAnchor="end">Hz</text>
  </svg>
  {curves.boost>.25&&<p>提升频段可能增加输出电平，可适当降低轨道音量。</p>}
 </figure>;
}
