import type {components} from "../../generated/api-schema";
import type {ArrangementIR,EditorCommand} from "../../shared/openapi";
import {PIANO_EQ_PROFILE,type PianoEqProfile} from "../../../../../packages/audio-engine/src/piano-eq";

export type PianoEqState=components["schemas"]["PianoEqState"];
export type PianoTrackEq=components["schemas"]["PianoTrackEq"];
export function readPianoEq(arrangement:ArrangementIR):PianoEqState|null{
 if(arrangement.schema_version==="arrangement-ir.v5")return structuredClone(arrangement.piano_eq);
 if(arrangement.schema_version!=="arrangement-ir.v4")return null;
 return {schema_version:"piano-eq-state.v1",tracks:arrangement.tracks.map(track=>({track_id:track.track_id,schema_version:"piano-eq.v1",profile_id:PIANO_EQ_PROFILE.profile_id,bypass:false,low_gain_db:0,mid_gain_db:0,high_gain_db:0}))};
}
export function eqProfileFor(arrangement:ArrangementIR):PianoEqProfile{
 return arrangement.schema_version==="arrangement-ir.v5"?arrangement.render_profile.eq_profile:PIANO_EQ_PROFILE;
}
export function makePianoEqCommand(eq:PianoEqState,trackId:string,patch:Partial<Pick<PianoTrackEq,"low_gain_db"|"mid_gain_db"|"high_gain_db"|"bypass">>):EditorCommand{
 if(!eq.tracks.some(track=>track.track_id===trackId))throw new Error("EQ target track is unavailable");
 return {command_id:crypto.randomUUID(),command_type:"set_piano_eq",schema_version:"editor-command.v1",actor_kind:"human",client_sequence:0,selection:{track_ids:eq.tracks.map(track=>track.track_id)},payload:{eq:{...eq,tracks:eq.tracks.map(track=>track.track_id===trackId?{...track,...patch}:{...track})}}};
}
