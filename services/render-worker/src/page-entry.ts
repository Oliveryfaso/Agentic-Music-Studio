import {
  peakAmplitude,
  renderAudioGraphOffline,
  type RenderBridgeReceipt,
  type RenderBridgeRequest,
  validateAudioGraphSpec,
} from "../../../packages/audio-engine/src/index.js";
import { encodeStereoPcm16 } from "../../../packages/audio-engine/src/wav.js";

declare global {
  interface Window {
    motifForgeRender: (request: RenderBridgeRequest) => Promise<RenderBridgeReceipt>;
  }
}

window.motifForgeRender = async (request) => {
  if (request.requestVersion !== "render-bridge-request.v1") {
    throw new Error("RENDER_BRIDGE_VERSION_UNSUPPORTED");
  }
  validateAudioGraphSpec(request.graph);
  const buffer = await renderAudioGraphOffline(request.graph, request.renderTrackIds);
  const wav = encodeStereoPcm16(buffer);
  const response = await fetch(`/outputs/${encodeURIComponent(request.outputToken)}`, {
    method: "POST",
    headers: { "Content-Type": "audio/wav" },
    body: wav.buffer as ArrayBuffer,
  });
  if (!response.ok) {
    throw new Error(`RENDER_OUTPUT_SINK_FAILED:${response.status}`);
  }
  return {
    receiptVersion: "render-bridge-receipt.v1",
    requestId: request.requestId,
    bytes: wav.byteLength,
    durationSeconds: buffer.duration,
    sampleRate: buffer.sampleRate,
    channels: buffer.numberOfChannels,
    peak: peakAmplitude(buffer),
  };
};
