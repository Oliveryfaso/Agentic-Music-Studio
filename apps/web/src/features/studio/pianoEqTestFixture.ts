import type { ArrangementIR } from "../../shared/openapi";
import { pianoScore } from "./pianoTestFixture";
export function eqBase(): ArrangementIR {
 const source=pianoScore(),first=source.tracks[0]!;
 const tracks=[{...first,locked_ranges:[{start_tick:0,end_tick:3840}]},{...structuredClone(first),track_id:"added",name:"Accompaniment",gain_db:-10}];
 return {...source,schema_version:"arrangement-ir.v4",tracks,
 render_profile:{schema_version:"render-profile.v1",engine_version:"motif-forge-audio-engine.v4",instrument_pack_id:"freepats:upright-kw-small",instrument_pack_version:"2019-07-03.motif1",manifest_sha256:"264fdbf12f3c7273a0d15fbcb86abed04b73e08b6fc4faf482eaf41040a0b813"},
 performance_plan:{schema_version:"performance-plan.v1",notes:[],pedal_events:[]},
 piano_mix:{schema_version:"piano-mix.v1",tracks:tracks.map(t=>({track_id:t.track_id,gain_db:t.gain_db,pan:t.pan,mute:t.mute,solo:t.solo}))}} as ArrangementIR;
}
