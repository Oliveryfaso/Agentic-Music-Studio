import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { BriefForm } from "./BriefForm";
import type { CreateAIRunInput } from "../../shared/openapi";

afterEach(cleanup);

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
