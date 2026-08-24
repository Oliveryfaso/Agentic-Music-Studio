import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { MixerPanel } from "./MixerPanel";

it("commits a single gain command on interaction end", () => {
  const onCommand = vi.fn();
  render(<MixerPanel tracks={[{ track_id: "track", name: "Warm Pad", gain_db: 0, pan: 0, mute: false, solo: false }]} onCommand={onCommand} />);
  fireEvent.change(screen.getByLabelText("Warm Pad gain"), { target: { value: "-4" } });
  expect(onCommand).not.toHaveBeenCalled();
  fireEvent.pointerUp(screen.getByLabelText("Warm Pad gain"));
  expect(onCommand).toHaveBeenCalledTimes(1);
});
