import type { RightsDeclaration, UploadProgress } from "../../shared/api";

export type ImportQueueStatus = "queued" | "uploading" | "analyzing" | "completed" | "failed" | "skipped";

export interface ImportQueueItem {
  itemId: string;
  file: File;
  rights: RightsDeclaration;
  rightsConfirmed: boolean;
  status: ImportQueueStatus;
  progress: UploadProgress | null;
  threadId: string | null;
  revisionId: string | null;
  errorCode: string | null;
}

export function createImportQueue(files: File[]): ImportQueueItem[] {
  return files.map((file) => ({
    itemId: crypto.randomUUID(),
    file,
    rights: "user_owned",
    rightsConfirmed: false,
    status: "queued",
    progress: null,
    threadId: null,
    revisionId: null,
    errorCode: null,
  }));
}

export function transitionQueueItem(
  queue: ImportQueueItem[],
  itemId: string,
  status: ImportQueueStatus,
  facts: { progress?: UploadProgress | null; threadId?: string | null; revisionId?: string | null; errorCode?: string | null } = {},
): ImportQueueItem[] {
  const item = queue.find((candidate) => candidate.itemId === itemId);
  if (!item) throw new Error("IMPORT_QUEUE_ITEM_NOT_FOUND");
  if (status === "uploading" && queue.some((candidate) => candidate.itemId !== itemId && ["uploading", "analyzing"].includes(candidate.status))) {
    throw new Error("IMPORT_QUEUE_ALREADY_ACTIVE");
  }
  return queue.map((candidate) => candidate.itemId === itemId ? { ...candidate, ...facts, status } : candidate);
}

export function nextQueuedItem(queue: ImportQueueItem[]): ImportQueueItem | null {
  return queue.find((item) => item.status === "queued") ?? null;
}
