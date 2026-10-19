import {expect,it} from "vitest";
import {createEditorState,editorReducer,projectDraft} from "./editorState";
import {makePianoEqCommand,readPianoEq} from "./pianoEq";
import {makePianoMixCommand,readPianoMix} from "./pianoMix";
import {eqBase} from "./pianoEqTestFixture";

it("preserves EQ and protected tracks when mixing after an EQ draft, including undo and redo",()=>{
 const base=eqBase(),eq=readPianoEq(base)!;
 const change=makePianoEqCommand(eq,"track",{mid_gain_db:6});
 let editor=editorReducer(createEditorState("branch","revision",base),{type:"append",command:change});
 const first=projectDraft(editor);expect(first.schema_version).toBe("arrangement-ir.v5");
 expect(first.tracks).toEqual(base.tracks);expect(first).toHaveProperty("piano_mix",readPianoMix(base));
 const mix=readPianoMix(first)!;
 editor=editorReducer(editor,{type:"append",command:makePianoMixCommand(mix,"added",{gain_db:-15})});
 const mixed=projectDraft(editor);expect(mixed.schema_version).toBe("arrangement-ir.v5");expect(mixed).toHaveProperty("piano_eq",readPianoEq(first));
 expect(mixed).toHaveProperty("piano_mix.tracks.1.gain_db",-15);expect(mixed.tracks).toEqual(base.tracks);
 const previous=editorReducer(editor,{type:"undo"});expect(projectDraft(previous)).toEqual(first);
 expect(projectDraft(editorReducer(previous,{type:"undo"}))).toEqual(base);
 expect(projectDraft(editorReducer(previous,{type:"redo"}))).toEqual(mixed);
 expect(base.schema_version).toBe("arrangement-ir.v4");expect(base).not.toHaveProperty("piano_eq");
});
it("builds a finite human EQ snapshot for the selected track and rejects an unknown target",()=>{
 const state=readPianoEq(eqBase())!;const command=makePianoEqCommand(state,"added",{low_gain_db:-3,bypass:true});
 expect(command).toMatchObject({command_type:"set_piano_eq",actor_kind:"human",selection:{track_ids:["track","added"]},payload:{eq:{tracks:[{track_id:"track",low_gain_db:0,mid_gain_db:0,high_gain_db:0,bypass:false},{track_id:"added",low_gain_db:-3,mid_gain_db:0,high_gain_db:0,bypass:true}]}}});
 expect(state.tracks[1]!.low_gain_db).toBe(0);expect(()=>makePianoEqCommand(state,"missing",{mid_gain_db:3})).toThrow();
});
