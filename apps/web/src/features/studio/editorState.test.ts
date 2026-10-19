import { describe, expect, it } from "vitest";

import type { ArrangementIR, EditorCommand } from "../../shared/openapi";
import { createEditorState, editorReducer, projectDraft } from "./editorState";

const TRACK_ID = "11111111-1111-4111-8111-111111111111";
const CLIP_ID = "22222222-2222-4222-8222-222222222222";

describe("Studio editor state", () => {
  it("keeps Base immutable while local undo and redo move the history cursor", () => {
    const arrangement = ir();
    const initial = createEditorState("branch", "revision", arrangement);
    const moved = editorReducer(initial, { type: "append", command: move(1920) });

    expect(moved.base.arrangement).toEqual(arrangement);
    expect(projectDraft(moved).tracks[0]?.clips[0]?.start_tick).toBe(1920);
    expect(projectDraft(editorReducer(moved, { type: "undo" }))).toEqual(arrangement);
    expect(projectDraft(editorReducer(editorReducer(moved, { type: "undo" }), { type: "redo" }))).toEqual(projectDraft(moved));
  });

  it("retains Draft commands when the server reports a conflict", () => {
    const initial = editorReducer(createEditorState("branch", "revision", ir()), { type: "append", command: move(1920) });
    const conflict = editorReducer(initial, { type: "conflict", serverRevisionId: "new-head" });
    expect(conflict.commands).toHaveLength(1);
    expect(conflict.conflict?.serverRevisionId).toBe("new-head");
  });
});

function move(startTick: number): EditorCommand {
  return { command_id: crypto.randomUUID(), command_type: "move_clip", schema_version: "editor-command.v1", actor_kind: "human", client_sequence: 0, selection: { track_ids: [TRACK_ID], start_tick: 0, end_tick: 3840 }, payload: { track_id: TRACK_ID, clip_id: CLIP_ID, start_tick: startTick } };
}

function ir(): ArrangementIR {
  return { schema_version: "arrangement-ir.v1", project_id: "33333333-3333-4333-8333-333333333333", ppq: 480, sample_rate: 48000, tempo_map: [{ tick: 0, bpm: 120 }], time_signature_map: [{ tick: 0, numerator: 4, denominator: 4 }], key_map: [], sections: [{ section_id: "44444444-4444-4444-8444-444444444444", start_tick: 0, end_tick: 3840, label: "A", energy: 0.5, function: "main" }], markers: [], tracks: [{ track_id: TRACK_ID, track_type: "instrument", name: "Lead", role: "melody", gain_db: 0, pan: 0, mute: false, solo: false, clips: [{ clip_id: CLIP_ID, clip_type: "note", start_tick: 0, duration_tick: 960, loop: false, gain_db: 0, pan: 0, fade_in_tick: 0, fade_out_tick: 0, notes: [] }], locked_ranges: [] }], provenance: [] };
}

it("keeps source tracks untouched through mix draft, undo and redo",()=>{
 const original=ir();original.tracks.push({...structuredClone(original.tracks[0]!),track_id:"55555555-5555-4555-8555-555555555555",gain_db:-10});
 const base={...original,schema_version:"arrangement-ir.v3",render_profile:{schema_version:"render-profile.v1",engine_version:"motif-forge-audio-engine.v3",instrument_pack_id:"freepats:upright-kw-small",instrument_pack_version:"2019-07-03.motif1",manifest_sha256:"264fdbf12f3c7273a0d15fbcb86abed04b73e08b6fc4faf482eaf41040a0b813"},performance_plan:{schema_version:"performance-plan.v1",notes:[],pedal_events:[]}} as ArrangementIR;
 const mix={schema_version:"piano-mix.v1",tracks:base.tracks.map(t=>({track_id:t.track_id,gain_db:t.gain_db,pan:t.pan,mute:false,solo:t.track_id===TRACK_ID}))};
 const command={command_id:crypto.randomUUID(),command_type:"set_piano_mix",schema_version:"editor-command.v1",actor_kind:"human",client_sequence:0,selection:{track_ids:base.tracks.map(t=>t.track_id)},payload:{mix}} as EditorCommand;
 const initial=createEditorState("branch","revision",base);const changed=editorReducer(initial,{type:"append",command});const draft=projectDraft(changed);
 expect(draft.schema_version).toBe("arrangement-ir.v4");expect(draft.tracks).toEqual(base.tracks);expect(draft).toHaveProperty("piano_mix",mix);
 expect(projectDraft(editorReducer(changed,{type:"undo"}))).toEqual(base);
 expect(projectDraft(editorReducer(editorReducer(changed,{type:"undo"}),{type:"redo"}))).toEqual(draft);
});
