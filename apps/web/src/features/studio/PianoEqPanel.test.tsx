import {useReducer} from "react";
import {cleanup,fireEvent,render,screen} from "@testing-library/react";
import {afterEach,expect,it} from "vitest";
import {PianoEqPanel} from "./PianoEqPanel";
import {MixerPanel} from "./MixerPanel";
import {createEditorState,editorReducer,projectDraft} from "./editorState";
import {eqBase} from "./pianoEqTestFixture";
afterEach(cleanup);
function Harness(){const base=eqBase(),[state,dispatch]=useReducer(editorReducer,createEditorState("branch","revision",base));return <><PianoEqPanel arrangement={projectDraft(state)} savedArrangement={base} onCommand={command=>dispatch({type:"append",command})}/><button onClick={()=>dispatch({type:"undo"})}>测试撤销</button><output aria-label="历史数量">{state.historyCursor}</output></>}
function pointer(el:Element,type:string,y:number){const event=new MouseEvent(type,{bubbles:true,clientY:y,button:0});Object.defineProperty(event,"pointerId",{value:1});fireEvent(el,event)}
it("commits one vertical drag, keeps values when bypassed, and resets with undo",()=>{
 render(<Harness/>);const dial=screen.getByRole("slider",{name:"Piano 低频 EQ 增益"});
 pointer(dial,"pointerdown",100);pointer(dial,"pointermove",70);pointer(dial,"pointerup",70);fireEvent.blur(dial);
 expect(screen.getByLabelText("历史数量")).toHaveTextContent("1");
 const input=screen.getByRole("spinbutton",{name:"Piano 低频 EQ 数值"});expect(Number((input as HTMLInputElement).value)).toBeGreaterThan(0);
 const before=(input as HTMLInputElement).value;
 fireEvent.click(screen.getByRole("button",{name:"旁路 EQ"}));expect(input).toHaveValue(Number(before));expect(screen.getByRole("button",{name:"旁路 EQ"})).toHaveAttribute("aria-pressed","true");
 expect(screen.getByText(/实线为 0 dB/)).toBeInTheDocument();
 fireEvent.click(screen.getByRole("button",{name:"三段归零"}));expect(input).toHaveValue(0);expect(screen.getByRole("button",{name:"旁路 EQ"})).toHaveAttribute("aria-pressed","false");
 fireEvent.click(screen.getByRole("button",{name:"测试撤销"}));expect(input).toHaveValue(Number(before));expect(screen.getByRole("button",{name:"旁路 EQ"})).toHaveAttribute("aria-pressed","true");
});
it("rejects invalid numeric edits and targets keyboard changes only at the selected track",()=>{
 render(<Harness/>);const first=screen.getByRole("spinbutton",{name:"Piano 中频 EQ 数值"});
 fireEvent.change(first,{target:{value:"13"}});fireEvent.keyDown(first,{key:"Enter"});expect(first).toHaveAttribute("aria-invalid","true");expect(screen.getByLabelText("历史数量")).toHaveTextContent("0");
 fireEvent.keyDown(first,{key:"Escape"});expect(first).toHaveValue(0);
 fireEvent.change(screen.getByRole("combobox",{name:"EQ 作用轨道"}),{target:{value:"added"}});
 const dial=screen.getByRole("slider",{name:"Accompaniment 中频 EQ 增益"});fireEvent.keyDown(dial,{key:"ArrowUp"});fireEvent.keyDown(dial,{key:"ArrowUp",repeat:true});fireEvent.keyUp(dial,{key:"ArrowUp"});
 expect(screen.getByRole("spinbutton",{name:"Accompaniment 中频 EQ 数值"})).toHaveValue(1);expect(screen.getByLabelText("历史数量")).toHaveTextContent("1");
 fireEvent.change(screen.getByRole("combobox",{name:"EQ 作用轨道"}),{target:{value:"track"}});
 expect(screen.getByRole("spinbutton",{name:"Piano 中频 EQ 数值"})).toHaveValue(0);
 expect(screen.queryByText(/实时频谱/)).not.toBeInTheDocument();
});

it("does not split a held arrow gesture when Shift is released first",()=>{
 render(<Harness/>);const dial=screen.getByRole("slider",{name:"Piano 中频 EQ 增益"});
 fireEvent.keyDown(dial,{key:"ArrowUp",shiftKey:true});
 fireEvent.keyDown(dial,{key:"ArrowUp",shiftKey:true,repeat:true});
 fireEvent.keyUp(dial,{key:"Shift"});
 expect(screen.getByLabelText("历史数量")).toHaveTextContent("0");
 fireEvent.keyDown(dial,{key:"ArrowUp",repeat:true});
 fireEvent.keyUp(dial,{key:"ArrowUp"});
 expect(screen.getByRole("spinbutton",{name:"Piano 中频 EQ 数值"})).toHaveValue(.7);
 expect(screen.getByLabelText("历史数量")).toHaveTextContent("1");
 fireEvent.click(screen.getByRole("button",{name:"测试撤销"}));
 expect(screen.getByRole("spinbutton",{name:"Piano 中频 EQ 数值"})).toHaveValue(0);
});
it("waits for a saved M1 version before opening EQ on a mix draft",()=>{
 const current=eqBase();if(current.schema_version!=="arrangement-ir.v4")throw new Error("v4 fixture required");
 const {piano_mix:_mix,...prior}=current;
 const saved={...prior,schema_version:"arrangement-ir.v3" as const,render_profile:{...prior.render_profile,engine_version:"motif-forge-audio-engine.v3" as const}};
 const {rerender}=render(<MixerPanel tracks={current.tracks} pianoArrangement={current} savedArrangement={saved} onCommand={()=>{}}/>);
 expect(screen.getByText("先保存双钢琴基础混音，再启用三段 EQ。")).toBeInTheDocument();
 expect(screen.queryByRole("slider",{name:"Piano 中频 EQ 增益"})).not.toBeInTheDocument();
 rerender(<MixerPanel tracks={current.tracks} pianoArrangement={current} savedArrangement={current} onCommand={()=>{}}/>);
 expect(screen.getByRole("slider",{name:"Piano 中频 EQ 增益"})).toBeInTheDocument();
});
