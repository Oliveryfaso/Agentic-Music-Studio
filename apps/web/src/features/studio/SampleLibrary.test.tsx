import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { SampleLibrary } from "./SampleLibrary";

it("shows an honest empty local library without external search", () => {
  render(<SampleLibrary entries={[]} />);
  expect(screen.getByText("本地审核音色库为空")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /联网搜索/ })).not.toBeInTheDocument();
});
