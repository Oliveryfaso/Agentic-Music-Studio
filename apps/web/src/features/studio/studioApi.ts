import { jsonHeaders, readData, requestJson } from "../../shared/api";
import type {
  CommandBatchData,
  CommitCommandBatchInput,
  UndoCommittedRevisionInput,
  UndoRevisionData,
} from "../../shared/openapi";
import type { SoundCatalogEntry } from "./SampleLibrary";

export async function listSoundCatalog(): Promise<SoundCatalogEntry[]> {
  return readData<SoundCatalogEntry[]>(await requestJson("/api/v1/sound-catalog"));
}

export async function commitCommandBatch(
  projectId: string,
  input: CommitCommandBatchInput,
  idempotencyKey: string,
): Promise<CommandBatchData> {
  return readData<CommandBatchData>(await requestJson(`/api/v1/projects/${encodeURIComponent(projectId)}/command-batches`, {
    method: "POST",
    headers: jsonHeaders(idempotencyKey),
    body: JSON.stringify(input),
  }));
}

export async function undoCommittedRevision(
  projectId: string,
  input: UndoCommittedRevisionInput,
  idempotencyKey: string,
): Promise<UndoRevisionData> {
  return readData<UndoRevisionData>(await requestJson(`/api/v1/projects/${encodeURIComponent(projectId)}/undo`, {
    method: "POST",
    headers: jsonHeaders(idempotencyKey),
    body: JSON.stringify(input),
  }));
}
