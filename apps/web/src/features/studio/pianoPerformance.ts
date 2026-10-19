import type {ArrangementIR,PerformancePlan} from '../../shared/openapi';
import type {EditorSelection} from './editorState';
export interface PianoExpression {velocity:number;onset:number;gate:number}
export function buildPianoPerformance(score:ArrangementIR,selection:EditorSelection|null,expression:PianoExpression):PerformancePlan {
  const previous=score.schema_version==='arrangement-ir.v2' ? score.performance_plan?.notes ?? [] : [];
  const notes=new Map(previous.map(note=>[`${note.track_id}:${note.clip_id}:${note.note_id}`,note]));
  let selected=0;
  for(const track of score.tracks){
    if(selection && !selection.trackIds.includes(track.track_id))continue;
    for(const clip of track.clips){
      if(clip.clip_type!=='note' || (selection?.clipId && selection.clipId!==clip.clip_id))continue;
      for(const note of clip.notes){
        const tick=clip.start_tick+note.start_tick;
        if(selection && (tick<selection.startTick || tick>=selection.endTick))continue;
        const value={track_id:track.track_id,clip_id:clip.clip_id,note_id:note.note_id,
          velocity_override:expression.velocity,onset_offset_tick:expression.onset,gate_duration_tick:expression.gate};
        notes.set(`${track.track_id}:${clip.clip_id}:${note.note_id}`,value);selected++;
      }
    }
  }
  if(selected===0)throw new Error('所选范围没有可调整的音符。');
  return {schema_version:'performance-plan.v1',notes:[...notes.values()].sort((a,b)=>
    `${a.track_id}:${a.clip_id}:${a.note_id}`.localeCompare(`${b.track_id}:${b.clip_id}:${b.note_id}`)),pedal_events:[]};
}
