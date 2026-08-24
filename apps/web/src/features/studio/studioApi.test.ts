import { afterEach, describe, expect, it, vi } from "vitest";

import { commitCommandBatch, undoCommittedRevision } from "./studioApi";

afterEach(() => vi.unstubAllGlobals());

describe("Studio write API", () => {
  it("uses explicit idempotency keys for commit and Undo", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ data: { branch_id: "b", revision_id: "r2", undone_revision_id: "r1", content_hash: "a".repeat(64), actual_change_impact: "L0", render_state: "dirty", replayed: false } }), { status: 201, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await commitCommandBatch("project", { branch_id: "b", base_revision_id: "r1", commands: [], client_sequence: 0, reason: "EDIT" }, "commit-key");
    await undoCommittedRevision("project", { branch_id: "b", base_revision_id: "r2", target_revision_id: "r2" }, "undo-key");
    const calls = fetchMock.mock.calls as unknown as Array<[string, RequestInit]>;
    expect(calls[0]?.[1].headers).toMatchObject({ "Idempotency-Key": "commit-key" });
    expect(calls[1]?.[1].headers).toMatchObject({ "Idempotency-Key": "undo-key" });
  });
});
