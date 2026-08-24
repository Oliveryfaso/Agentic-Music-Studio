import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { EditPanel } from "./EditPanel";
import * as api from "./editRunApi";

describe("AI selection edit panel", () => {
  it("submits only visible selection, locks, intent, and current Base identity", async () => {
    const create = vi.spyOn(api, "createEditRun").mockResolvedValue({ run_id: "run-1" } as never);
    render(<EditPanel
      projectId="project-1" branchId="branch-1" baseRevisionId="revision-1"
      selection={{ trackIds: ["track-1"], startTick: 0, endTick: 1920 }}
      lockedRanges={[]} rootReady onRunCreated={() => undefined}
    />);
    fireEvent.change(screen.getByLabelText("AI 编辑要求"), {
      target: { value: "把这里的 Pad 降低 2 dB" },
    });
    fireEvent.click(screen.getByRole("button", { name: "运行选区编辑" }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0]?.[1]).toMatchObject({
      branch_id: "branch-1", base_revision_id: "revision-1", run_type: "edit",
      edit_request: {
        intent: "把这里的 Pad 降低 2 dB",
        selection: { track_ids: ["track-1"], start_tick: 0, end_tick: 1920 },
        locked_ranges: [],
      },
    });
  });
});
