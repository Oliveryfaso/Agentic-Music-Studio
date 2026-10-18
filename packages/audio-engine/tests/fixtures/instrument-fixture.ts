import { createBuiltinClickWav } from "../../../../services/render-worker/src/runtime.js";
import type { InstrumentPack } from "../../src/instruments.js";
// Existing self-authored click is an engineering fixture, never a piano recording.
export async function fixture() {
  const bytes=createBuiltinClickWav();
  const sha=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",new Uint8Array(bytes).buffer))).map(b=>b.toString(16).padStart(2,"0")).join("");
  const sample={sampleId:"soft",path:"samples/own-click.wav",sha256:sha,byteSize:bytes.length,
    frames:3840,sampleRate:48000,channels:1,bitDepth:16 as const,rootMidi:60,keyLo:48,keyHi:72,velocityLo:1,velocityHi:63};
  const pack:InstrumentPack={schemaVersion:"instrument-pack.v1",packId:"test:own-click",packVersion:"1",
    adapterVersion:"multisample-buffer-source.v1",sourceUrl:"https://example.invalid/self-authored",
    sourceArchiveSha256:"0".repeat(64),license:{spdx:"CC0-1.0",textSha256:"1".repeat(64)},
    releaseSeconds:0.04,maxVoices:4,pedal:"unsupported",releaseTriggers:"unsupported",
    samples:[sample,{...sample,sampleId:"loud",velocityLo:64,velocityHi:127}]};
  return {pack,bytes};
}
