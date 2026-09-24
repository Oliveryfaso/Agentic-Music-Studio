import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { StudioDock } from "./StudioDock";

afterEach(cleanup);

it("keeps one selected panel and lets keyboard users switch and wrap tabs", () => {
  render(<StudioDock piano={<p>Notes</p>} mixer={<p>Channels</p>} inspector={<p>Clip</p>} library={<p>Sounds</p>} />);
  const selected = screen.getByRole("tab", { selected: true });
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Clip");
  selected.focus();
  fireEvent.keyDown(selected, { key: "ArrowRight" });
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Sounds");
  expect(screen.getByRole("tab", { selected: true })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("tab", { selected: true }), { key: "ArrowRight" });
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Notes");
  fireEvent.click(screen.getByRole("tab", { name: /混音/ }));
  expect(screen.getByRole("tabpanel")).toHaveTextContent("Channels");
});
