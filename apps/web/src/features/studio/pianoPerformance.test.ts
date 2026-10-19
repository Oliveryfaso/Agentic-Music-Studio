import {describe,expect,it} from 'vitest';
import type {ArrangementIR} from '../../shared/openapi';
import {pianoScore} from './pianoTestFixture';
import {buildPianoPerformance} from './pianoPerformance';
describe('explicit piano performance',()=>{
  it('changes only selected note expression while preserving notation and outside overrides',()=>{
    const base=pianoScore();
    const score={...base,schema_version:'arrangement-ir.v2',render_profile:{},performance_plan:{notes:[{track_id:'track',clip_id:'clip',note_id:'b',velocity_override:80}]}} as ArrangementIR;
    const plan=buildPianoPerformance(score,{trackIds:['track'],startTick:0,endTick:240},{velocity:64,onset:8,gate:260});
    expect(plan.notes).toEqual([{track_id:'track',clip_id:'clip',note_id:'a',velocity_override:64,onset_offset_tick:8,gate_duration_tick:260},
      {track_id:'track',clip_id:'clip',note_id:'b',velocity_override:80}]);
    expect(score.tracks).toEqual(base.tracks);
  });
});
