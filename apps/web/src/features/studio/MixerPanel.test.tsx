import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { MixerPanel } from "./MixerPanel";

it("commits a single gain command on interaction end", () => {
  const onCommand = vi.fn();
  render(<MixerPanel tracks={[{ track_id: "track", name: "Warm Pad", gain_db: 0, pan: 0, mute: false, solo: false }]} onCommand={onCommand} />);
  fireEvent.change(screen.getByLabelText("Warm Pad gain"), { target: { value: "-4" } });
  expect(onCommand).not.toHaveBeenCalled();
  fireEvent.pointerUp(screen.getByLabelText("Warm Pad gain"));
  expect(onCommand).toHaveBeenCalledTimes(1);
});

import type { ArrangementIR } from "../../shared/openapi";
import { pianoScore } from "./pianoTestFixture";
afterEach(cleanup);

function mixScore(): ArrangementIR {
  const base=pianoScore();
  return {...base,schema_version:"arrangement-ir.v3",render_profile:{schema_version:"render-profile.v1",engine_version:"motif-forge-audio-engine.v3",instrument_pack_id:"freepats:upright-kw-small",instrument_pack_version:"2019-07-03.motif1",manifest_sha256:"264fdbf12f3c7273a0d15fbcb86abed04b73e08b6fc4faf482eaf41040a0b813"},performance_plan:{schema_version:"performance-plan.v1",notes:[],pedal_events:[]},tracks:[{...base.tracks[0]!,locked_ranges:[{start_tick:0,end_tick:3840}]},{...structuredClone(base.tracks[0]!),track_id:"added",name:"Accompaniment",gain_db:-10}]} as ArrangementIR;
}
it("permits piano pan on a locked original using the complete mix layer and keyboard commit",()=>{
  const base=mixScore(); const onCommand=vi.fn();
  render(<MixerPanel tracks={base.tracks} pianoArrangement={base} savedArrangement={base} onCommand={onCommand}/>);
  const pan=screen.getByLabelText("Piano 声像");
  fireEvent.change(pan,{target:{value:-0.5}});expect(onCommand).not.toHaveBeenCalled();
  fireEvent.keyUp(pan,{key:"ArrowLeft"});fireEvent.blur(pan);
  expect(onCommand).toHaveBeenCalledTimes(1);
  expect(onCommand.mock.calls[0]![0]).toMatchObject({command_type:"set_piano_mix",actor_kind:"human",selection:{track_ids:["track","added"]},payload:{mix:{schema_version:"piano-mix.v1",tracks:[{track_id:"track",gain_db:0,pan:-0.5,mute:false,solo:false},{track_id:"added",gain_db:-10,pan:0,mute:false,solo:false}]}}});
  expect(base.tracks[0]!.pan).toBe(0);expect(base.tracks[0]!.locked_ranges).toHaveLength(1);
});
it("resets a controlled gain after authoritative props change rather than keeping a stale slider",()=>{
  const onCommand=vi.fn();const tracks=[{track_id:"track",name:"Warm Pad",gain_db:0,pan:0,mute:false,solo:false}];
  const view=render(<MixerPanel tracks={tracks} onCommand={onCommand}/>);
  fireEvent.change(screen.getByLabelText("Warm Pad gain"),{target:{value:-4}});fireEvent.pointerUp(screen.getByLabelText("Warm Pad gain"));
  view.rerender(<MixerPanel tracks={[{...tracks[0]!,gain_db:-10}]} onCommand={onCommand}/>);
  expect(screen.getByLabelText("Warm Pad gain")).toHaveValue("-10");
});
it("restores the opened saved mix for only one track rather than resetting its gain to zero",()=>{
  const base=mixScore();
  const draft={...base,schema_version:"arrangement-ir.v4",render_profile:{...(base as {render_profile:object}).render_profile,engine_version:"motif-forge-audio-engine.v4"},piano_mix:{schema_version:"piano-mix.v1",tracks:[{track_id:"track",gain_db:0,pan:0,mute:true,solo:false},{track_id:"added",gain_db:-3,pan:0.4,mute:false,solo:true}]}} as ArrangementIR;
  const onCommand=vi.fn();render(<MixerPanel tracks={draft.tracks} pianoArrangement={draft} savedArrangement={base} onCommand={onCommand}/>);
  fireEvent.click(screen.getByRole("button",{name:"Accompaniment 恢复当前保存值"}));
  expect(onCommand.mock.calls[0]![0].payload.mix.tracks).toEqual([{track_id:"track",gain_db:0,pan:0,mute:true,solo:false},{track_id:"added",gain_db:-10,pan:0,mute:false,solo:false}]);
});
it("does not silently clamp an old out-of-range gain while enabling a mix profile",()=>{
  const base=mixScore();base.tracks[1]!.gain_db=8;const onCommand=vi.fn();
  render(<MixerPanel tracks={base.tracks} pianoArrangement={base} savedArrangement={base} onCommand={onCommand}/>);
  expect(screen.getByText(/现有参数超出混音模式范围/)).toBeInTheDocument();
  expect(screen.queryByRole("button",{name:"独奏"})).not.toBeInTheDocument();expect(onCommand).not.toHaveBeenCalled();
});
it("does not offer ineffective solo or locked legacy gain controls",()=>{
  const track={...pianoScore().tracks[0]!,locked_ranges:[{start_tick:0,end_tick:3840}]};
  render(<MixerPanel tracks={[track]} onCommand={vi.fn()}/>);
  expect(screen.getByLabelText("Piano gain")).toBeDisabled();
  expect(screen.queryByRole("button",{name:"独奏"})).not.toBeInTheDocument();
});

it("preserves a valid legacy minus60 dB gain on blur without clamping it to minus24",()=>{
 const onCommand=vi.fn();render(<MixerPanel tracks={[{track_id:"track",name:"Quiet",gain_db:-60,pan:0,mute:false,solo:false}]} onCommand={onCommand}/>);
 const gain=screen.getByLabelText("Quiet gain");expect(gain).toHaveValue("-60");fireEvent.blur(gain);expect(onCommand).not.toHaveBeenCalled();
});
