import type {ArrangementIR} from "../../shared/openapi";
export function pianoScore():ArrangementIR {
  return {schema_version:'arrangement-ir.v1',project_id:'project',ppq:480,sample_rate:48000,key_map:[],markers:[],provenance:[],
    sections:[{section_id:'section',start_tick:0,end_tick:3840,label:'Study',energy:.5,function:'main'}],
    tracks:[{track_id:'track',track_type:'instrument',name:'Piano',role:'melody',gain_db:0,pan:0,mute:false,solo:false,locked_ranges:[],clips:[{clip_type:'note',clip_id:'clip',start_tick:0,duration_tick:3840,loop:false,gain_db:0,pan:0,fade_in_tick:0,fade_out_tick:0,
      notes:[{note_id:'a',pitch:60,start_tick:0,duration_tick:180,velocity:92,articulation:"normal",cents:0},{note_id:'b',pitch:64,start_tick:480,duration_tick:180,velocity:92,articulation:"normal",cents:0}]}]}]};
}
