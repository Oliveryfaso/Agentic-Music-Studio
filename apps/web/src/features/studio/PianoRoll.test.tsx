import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { PianoRoll } from "./PianoRoll";

it("emits one update_notes command when pitch editing completes", () => {
  const onCommand = vi.fn();
  render(<PianoRoll trackId="track" clip={{ clip_id: "clip", clip_type: "note", start_tick: 0, duration_tick: 960, loop: false, gain_db: 0, pan: 0, fade_in_tick: 0, fade_out_tick: 0, notes: [{ note_id: "note", pitch: 64, start_tick: 0, duration_tick: 480, velocity: 90, articulation: "normal", cents: 0 }] }} onCommand={onCommand} />);
  fireEvent.change(screen.getByLabelText("音高"), { target: { value: "67" } });
  fireEvent.blur(screen.getByLabelText("音高"));
  expect(onCommand).toHaveBeenCalledWith(expect.objectContaining({ command_type: "update_notes" }));
});
