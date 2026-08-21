import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AIRun } from "../../shared/openapi";
import { CandidateCompare } from "./CandidateCompare";

const A = "11111111-1111-4111-8111-111111111111";
const B = "22222222-2222-4222-8222-222222222222";
const PREVIEW_A = "33333333-3333-4333-8333-333333333333";
const PREVIEW_B = "44444444-4444-4444-8444-444444444444";
const ARTIFACT_A = "55555555-5555-4555-8555-555555555555";
const ARTIFACT_B = "66666666-6666-4666-8666-666666666666";

afterEach(cleanup);

describe("Candidate A/B compare", () => {
  it("keeps one authoritative preview active and submits explicit B identity", () => {
    const onSelect = vi.fn();
    render(<CandidateCompare run={waitingSelectionRun()} busy={false} onSelect={onSelect} />);

    fireEvent.click(screen.getByRole("button", { name: "试听候选 B" }));
    const player = screen.getByLabelText("候选 B 试听");
    expect(player).toHaveAttribute(
      "src",
      `/api/v1/audio-artifacts/${ARTIFACT_B}/content`,
    );
    expect(screen.queryByLabelText("候选 A 试听")).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("选择确认"), {
      target: { value: "I compared both authoritative previews and select B." },
    });
    fireEvent.click(screen.getByRole("button", { name: "选择候选 B" }));
    expect(onSelect).toHaveBeenCalledWith({
      decision: "select",
      previewId: PREVIEW_B,
      candidateId: B,
      candidateContentHash: "b".repeat(64),
      assertion: "I compared both authoritative previews and select B.",
      note: "",
    });
  });

  it("shows evidence recommendation without auto-selecting and supports reject", () => {
    const onSelect = vi.fn();
    render(<CandidateCompare run={waitingSelectionRun()} busy={false} onSelect={onSelect} />);
    expect(screen.getByText("Agent 建议：候选 B")).toBeVisible();
    expect(screen.getByText("B has stronger continuity.")).toBeVisible();
    expect(screen.getByText("已改善")).toBeVisible();
    expect(onSelect).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("选择确认"), {
      target: { value: "I reject both candidates after comparing their evidence." },
    });
    fireEvent.click(screen.getByRole("button", { name: "拒绝两个候选" }));
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ decision: "reject" }));
  });

  it("blocks selection while a Preview is rehydrating", () => {
    const run = waitingSelectionRun();
    run.candidates[1]!.preview_availability = "rehydrating";
    render(<CandidateCompare run={run} busy={false} onSelect={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Preview 恢复中" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "选择候选 B" })).toBeDisabled();
  });
});

function waitingSelectionRun(): AIRun {
  return {
    run_id: "77777777-7777-4777-8777-777777777777",
    parent_run_id: null,
    project_id: "88888888-8888-4888-8888-888888888888",
    branch_id: "99999999-9999-4999-8999-999999999999",
    base_revision_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    thread_id: "candidate-compare",
    status: "materializing",
    version: 4,
    pending_action: "select_candidate",
    pending_plan_id: null,
    pending_plan_hash: null,
    submitted_model_requests: 2,
    max_model_requests: 3,
    prompt_tokens: 100,
    completion_tokens: 200,
    total_tokens: 300,
    model_usage_status: "known",
    cost_status: "unknown",
    cost_amount_microusd: null,
    cost_pricing_version: null,
    candidates: [
      {
        label: "a", candidate_id: A,
        candidate_snapshot_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        candidate_content_hash: "a".repeat(64), preview_id: PREVIEW_A,
        preview_artifact_id: ARTIFACT_A, parent_candidate_snapshot_id: null,
        preview_availability: "available",
        repair_status: "not_requested",
      },
      {
        label: "b", candidate_id: B,
        candidate_snapshot_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
        candidate_content_hash: "b".repeat(64), preview_id: PREVIEW_B,
        preview_artifact_id: ARTIFACT_B,
        preview_availability: "available",
        parent_candidate_snapshot_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        repair_status: "improved",
      },
    ],
    critique: {
      schema_version: "candidate-critique.v1", evidence: [],
      assessments: [
        { candidate_id: A, label: "a", score: 70, evidence_refs: [] },
        { candidate_id: B, label: "b", score: 82, evidence_refs: [] },
      ],
      findings: [], repair_proposal: null, recommended_candidate_id: B,
      rationale: "B has stronger continuity.",
    },
    selected_candidate_id: null,
    selected_preview_id: null,
    revision_id: null, bundle_id: null, fallback_reason: null, error_code: null,
    plan: null,
    progress: {
      phase: "materializing", completed_export_steps: [], total_export_steps: 7,
      latest_event_sequence: 9, error_code: null,
    },
  };
}
