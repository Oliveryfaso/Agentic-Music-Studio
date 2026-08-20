import { ApiError } from "../../shared/api";
import type { AIRun, AIRunEvent, AIRunStatus } from "../../shared/openapi";
import { readRun } from "./generateApi";
import type { RunConnectionState } from "./runState";

export interface RunEventCallbacks {
  onEvent: (event: AIRunEvent) => void;
  onAuthoritativeRun: (run: AIRun) => void;
  onConnectionChange?: (state: RunConnectionState) => void;
}

const TERMINAL_STATUSES = new Set<AIRunStatus>([
  "succeeded",
  "rejected",
  "failed",
  "cancelled",
]);

export async function watchRunEvents(
  runId: string,
  callbacks: RunEventCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  let connectedOnce = false;
  while (!signal?.aborted) {
    callbacks.onConnectionChange?.(connectedOnce ? "reconnecting" : "initial_read");
    const run = await readRun(runId);
    callbacks.onAuthoritativeRun(run);
    if (TERMINAL_STATUSES.has(run.status)) {
      callbacks.onConnectionChange?.("terminal_closed");
      return;
    }

    callbacks.onConnectionChange?.(connectedOnce ? "replaying" : "connecting");
    try {
      await consumeEventStream(runId, callbacks, signal);
      connectedOnce = true;
    } catch (error) {
      if (signal?.aborted || (error instanceof DOMException && error.name === "AbortError")) {
        return;
      }
      callbacks.onConnectionChange?.("offline_error");
      throw error;
    }
  }
}

async function consumeEventStream(
  runId: string,
  callbacks: RunEventCallbacks,
  signal?: AbortSignal,
): Promise<void> {
  const cursor = readCursor(runId);
  const headers = new Headers({ Accept: "text/event-stream" });
  if (cursor > 0) headers.set("Last-Event-ID", String(cursor));
  const response = await fetch(`/api/v1/runs/${encodeURIComponent(runId)}/events`, {
    headers,
    signal: signal ?? null,
  });
  if (!response.ok) {
    throw new ApiError("Run 事件流连接失败", "RUN_EVENT_STREAM_FAILED", true, response.status);
  }
  if (response.body === null) {
    throw new ApiError("Run 事件流没有响应内容", "RUN_EVENT_STREAM_EMPTY", true, 502);
  }

  callbacks.onConnectionChange?.("live");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done }).replaceAll("\r\n", "\n");
    const blocks = buffer.split("\n\n");
    buffer = blocks.pop() ?? "";
    for (const block of blocks) acceptEventBlock(runId, block, callbacks);
    if (done) break;
  }
  if (buffer.trim() !== "") acceptEventBlock(runId, buffer, callbacks);
}

function acceptEventBlock(
  runId: string,
  block: string,
  callbacks: RunEventCallbacks,
): void {
  if (block.trim() === "" || block.trimStart().startsWith(":")) return;
  const data = block
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (data === "") return;

  let value: unknown;
  try {
    value = JSON.parse(data) as unknown;
  } catch {
    throw new ApiError("Run 事件不是有效 JSON", "RUN_EVENT_INVALID", false, 502);
  }
  if (!isRunEvent(value) || value.run_id !== runId) {
    throw new ApiError("Run 事件不符合公开合同", "RUN_EVENT_INVALID", false, 502);
  }

  const cursor = readCursor(runId);
  if (value.sequence <= cursor) return;
  sessionStorage.setItem(cursorKey(runId), String(value.sequence));
  callbacks.onEvent(value);
  callbacks.onConnectionChange?.("live");
}

function isRunEvent(value: unknown): value is AIRunEvent {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const event = value as Record<string, unknown>;
  return (
    Number.isInteger(event.sequence) &&
    (event.sequence as number) > 0 &&
    typeof event.event_id === "string" &&
    typeof event.run_id === "string" &&
    typeof event.event_type === "string" &&
    typeof event.phase === "string" &&
    typeof event.payload === "object" &&
    event.payload !== null
  );
}

function readCursor(runId: string): number {
  const value = Number(sessionStorage.getItem(cursorKey(runId)) ?? "0");
  return Number.isSafeInteger(value) && value > 0 ? value : 0;
}

function cursorKey(runId: string): string {
  return `motif-forge:run:${runId}:last-sequence`;
}
