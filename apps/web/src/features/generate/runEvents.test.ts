import { afterEach, describe, expect, it, vi } from "vitest";

import { watchRunEvents } from "./runEvents";

const RUN_ID = "44444444-4444-4444-8444-444444444444";

function run(status: string, sequence: number) {
  return {
    run_id: RUN_ID,
    status,
    revision_id: null,
    progress: {
      phase: status,
      completed_export_steps: [],
      total_export_steps: 7,
      latest_event_sequence: sequence,
      error_code: null,
    },
  };
}

afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe("persistent Run event stream", () => {
  it("sends the stored Last-Event-ID and stops after terminal GET recovery", async () => {
    sessionStorage.setItem(`motif-forge:run:${RUN_ID}:last-sequence`, "12");
    const event = {
      sequence: 13,
      event_id: "55555555-5555-4555-8555-555555555555",
      run_id: RUN_ID,
      event_type: "ai_run.waiting_worker",
      phase: "waiting_worker",
      payload: { status: "waiting_worker" },
      dedupe_key: "progress",
      created_at: "2026-08-20T00:00:00Z",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: run("waiting_worker", 12) })))
      .mockResolvedValueOnce(new Response(
        `id: 13\nevent: ai_run.waiting_worker\ndata: ${JSON.stringify(event)}\n\n`,
        { headers: { "Content-Type": "text/event-stream" } },
      ))
      .mockResolvedValueOnce(new Response(JSON.stringify({ data: run("succeeded", 13) })));
    vi.stubGlobal("fetch", fetchMock);
    const events: number[] = [];

    await watchRunEvents(RUN_ID, {
      onEvent: (value) => events.push(value.sequence),
      onAuthoritativeRun: () => undefined,
    });

    const streamHeaders = new Headers(fetchMock.mock.calls[1]?.[1]?.headers);
    expect(streamHeaders.get("Last-Event-ID")).toBe("12");
    expect(events).toEqual([13]);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(sessionStorage.getItem(`motif-forge:run:${RUN_ID}:last-sequence`)).toBe("13");
  });

  it("does not open SSE when the initial authoritative GET is terminal", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ data: run("cancelled", 21) })),
    );
    vi.stubGlobal("fetch", fetchMock);

    await watchRunEvents(RUN_ID, {
      onEvent: () => undefined,
      onAuthoritativeRun: () => undefined,
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
