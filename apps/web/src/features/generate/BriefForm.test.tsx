import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { BriefForm } from "./BriefForm";
import type { CreateAIRunInput } from "../../shared/openapi";

afterEach(cleanup);

it("starts with the current work title and exposes required musical fields",()=>{
  render(<BriefForm initialTitle="First piece" disabled={false} onSubmit={()=>{}}/>);
  expect(screen.getByLabelText("作品标题")).toHaveValue("First piece");
  expect(screen.getByLabelText("作品标题")).toBeRequired();
  expect(screen.getByLabelText("用途")).toBeRequired();
  expect(screen.getByLabelText("情绪")).toBeRequired();
});

it("accepts Chinese and English separators without merging multiple creative constraints", () => {
  let result: NonNullable<CreateAIRunInput["brief"]> | undefined;
  render(<BriefForm disabled={false} onSubmit={(brief) => { result = brief; }} />);
  fireEvent.change(screen.getByLabelText("作品标题"), { target: { value: "晨间" } });
  fireEvent.change(screen.getByLabelText("用途"), { target: { value: "影片配乐" } });
  fireEvent.change(screen.getByLabelText("情绪"), { target: { value: " 温暖，明亮、平静, airy " } });
  fireEvent.change(screen.getByLabelText("偏好乐器"), { target: { value: "钢琴，弦乐" } });
  fireEvent.submit(screen.getByLabelText("作品标题").closest("form")!);
  expect(result?.moods).toEqual(["温暖", "明亮", "平静", "airy"]);
  expect(result?.preferred_instruments).toEqual(["钢琴", "弦乐"]);
});

it('locks the submitted draft while pending and restores editing with its values after failure',()=>{
 const props={disabled:false,initialTitle:'Saved title',onSubmit:()=>{}};
 const view=render(<BriefForm {...props}/>);
 fireEvent.change(screen.getByLabelText('用途'),{target:{value:'Keep this idea'}});
 fireEvent.change(screen.getByLabelText('偏好乐器'),{target:{value:'Piano'}});
 view.rerender(<BriefForm {...props} disabled isSubmitting/>);
 for(const label of ['作品标题','音乐策略','用途','情绪','目标时长（秒）','目标 BPM','偏好乐器'])expect(screen.getByLabelText(label)).toBeDisabled();
 view.rerender(<BriefForm {...props}/>);
 expect(screen.getByLabelText('用途')).toBeEnabled();expect(screen.getByLabelText('用途')).toHaveValue('Keep this idea');expect(screen.getByLabelText('偏好乐器')).toHaveValue('Piano');
});
it('allows drafting when configuration alone blocks submission',()=>{
 render(<BriefForm disabled initialTitle='A work' onSubmit={()=>{}}/>);
 expect(screen.getByLabelText('用途')).toBeEnabled();expect(screen.getByRole('button',{name:'提交 Brief 并规划'})).toBeDisabled();
});
