import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { MixerPanel } from "./MixerPanel";
import { eqBase } from "./pianoEqTestFixture";
import { StudioInspector } from "./StudioInspector";

afterEach(cleanup);
it("selects one channel and EQ target without dispatching an edit", () => {
  const base=eqBase(), command=vi.fn();
  function Mixer(){const [id,setId]=useState("track");return <MixerPanel tracks={base.tracks} pianoArrangement={base} savedArrangement={base} selectedTrackId={id} onSelectTrack={setId} onCommand={command}/>;}
  render(<Mixer/>);fireEvent.click(screen.getByRole("button",{name:"选择音轨 02 Accompaniment"}));
  expect(screen.getByLabelText("EQ 作用轨道")).toHaveValue("added");
  fireEvent.change(screen.getByLabelText("EQ 作用轨道"),{target:{value:"track"}});
  expect(screen.getByRole("button",{name:"选择音轨 01 Piano"})).toHaveAttribute("aria-pressed","true");expect(command).not.toHaveBeenCalled();
});
it("shows a vertical dB fader with a single command across pointerup and blur, no fake output slider", () => {
  const base=eqBase(),command=vi.fn();render(<MixerPanel tracks={base.tracks} pianoArrangement={base} savedArrangement={base} onCommand={command}/>);
  const gain=screen.getByLabelText("Piano 音量");expect(gain).toHaveAttribute("aria-orientation","vertical");
  fireEvent.change(gain,{target:{value:"-4"}});fireEvent.pointerUp(gain);fireEvent.blur(gain);
  expect(command).toHaveBeenCalledTimes(1);expect(command.mock.calls[0]![0].payload.mix.tracks[0].gain_db).toBe(-4);
  expect(screen.queryByRole("slider",{name:/主输出/})).toBeNull();expect(screen.queryByRole("meter")).toBeNull();
});
it("keeps waiting-approval discoverable and child draft mounted when task details close", () => {
  function Form(){const [value,setValue]=useState("");return <input aria-label="任务描述" value={value} onChange={e=>setValue(e.target.value)}/>;}
  const view=render(<StudioInspector status="处理中"><Form/></StudioInspector>);
  const details=screen.getByText("创作任务").closest("details")!;expect(details).not.toHaveAttribute("open");
  view.rerender(<StudioInspector status="待确认"><Form/></StudioInspector>);
  expect(details).toHaveAttribute("open");expect(screen.getByText("待确认")).toBeVisible();
  fireEvent.change(screen.getByLabelText("任务描述"),{target:{value:"更稀疏"}});details.open=false;fireEvent(details,new Event("toggle"));
  view.rerender(<StudioInspector status="待确认"><Form/></StudioInspector>);expect(details).not.toHaveAttribute("open");
  expect(screen.getByLabelText("任务描述")).toHaveValue("更稀疏");expect(screen.getByText("待确认")).toBeVisible();
  view.rerender(<StudioInspector status="待确认" approvalKey="another-candidate"><Form/></StudioInspector>);expect(details).toHaveAttribute("open");expect(screen.getByLabelText("任务描述")).toHaveValue("更稀疏");
});
