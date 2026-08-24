import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EditPreviewCard } from "./EditPreviewCard";

describe("Edit Preview card", () => {
  it("does not approve until authoritative rendered evidence is available", () => {
    const approve = vi.fn();
    render(<EditPreviewCard preview={{
      preview_id: "preview-1", candidate_snapshot_id: "candidate-1",
      candidate_content_hash: "a".repeat(64), preview_artifact_id: null,
      preview_availability: "rehydrating", actual_change_impact: 2,
      structural_diff: [{ summary: "selected track changed" }],
    }} busy={false} rootReady onDecision={approve} />);
    const button = screen.getByRole("button", { name: "批准 Preview" });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(approve).not.toHaveBeenCalled();
  });
});
