import { describe, expect, it } from "vitest";

import { createImportQueue, transitionQueueItem } from "./importQueue";

describe("sequential import queue", () => {
  it("allows only one active file and advances after a committed Revision", () => {
    const files = [new File(["pad"], "pad.wav"), new File(["pulse"], "pulse.wav")];
    let queue = createImportQueue(files);

    queue = transitionQueueItem(queue, queue[0]!.itemId, "uploading");
    expect(() => transitionQueueItem(queue, queue[1]!.itemId, "uploading")).toThrow("IMPORT_QUEUE_ALREADY_ACTIVE");
    queue = transitionQueueItem(queue, queue[0]!.itemId, "completed", { revisionId: "revision-1" });
    queue = transitionQueueItem(queue, queue[1]!.itemId, "uploading");

    expect(queue.map((item) => item.status)).toEqual(["completed", "uploading"]);
    expect(queue[0]?.revisionId).toBe("revision-1");
  });

  it("keeps rights and failure recovery independent per file", () => {
    const files = [new File(["pad"], "pad.wav"), new File(["pulse"], "pulse.wav")];
    let queue = createImportQueue(files);
    queue = queue.map((item, index) => index === 1 ? { ...item, rights: "cc_by" as const, rightsConfirmed: true } : { ...item, rightsConfirmed: true });
    queue = transitionQueueItem(queue, queue[0]!.itemId, "uploading");
    queue = transitionQueueItem(queue, queue[0]!.itemId, "failed", { errorCode: "UPLOAD_FAILED" });
    queue = transitionQueueItem(queue, queue[0]!.itemId, "skipped");

    expect(queue[0]).toMatchObject({ status: "skipped", rights: "user_owned" });
    expect(queue[1]).toMatchObject({ status: "queued", rights: "cc_by", rightsConfirmed: true });
  });
});
