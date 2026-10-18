/** Preparation contract only. License approval and catalog admission stay outside the renderer. */
export type InstrumentSample = Readonly<{
  sampleId: string; path: string; sha256: string; byteSize: number;
  frames: number; sampleRate: number; channels: number; bitDepth: 16 | 24;
  rootMidi: number; keyLo: number; keyHi: number; velocityLo: number; velocityHi: number;
  // Source-frame bounds; endFrame is exclusive, unlike some SFZ loop opcodes.
  loop?: Readonly<{ startFrame: number; endFrame: number }>;
}>;
export type InstrumentPack = Readonly<{
  schemaVersion: "instrument-pack.v1"; adapterVersion: "multisample-buffer-source.v1";
  packId: string; packVersion: string; sourceUrl: string; sourceArchiveSha256: string;
  license: Readonly<{ spdx: "CC0-1.0"; textSha256: string }>;
  releaseSeconds: number; maxVoices: number;
  pedal: "unsupported"; releaseTriggers: "unsupported";
  samples: readonly InstrumentSample[];
}>;
export type PianoNote = Readonly<{
  noteId: string; midi: number; velocity: number; startSeconds: number;
  gateSeconds: number; detuneCents: number;
}>;
export type PianoVoice = Readonly<{
  noteId: string; sampleId: string; playbackRate: number; gain: number;
  // releaseSeconds is the absolute note-off time; pack.releaseSeconds is a duration.
  startSeconds: number; releaseSeconds: number; stopSeconds: number;
}>;
const hash = (v: unknown): boolean => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const id = (v: unknown): boolean => typeof v === "string" && /^[A-Za-z0-9:._-]{1,100}$/.test(v);
const range = (n: number, lo: number, hi: number): boolean => Number.isFinite(n) && n >= lo && n <= hi;
const integer = (n: number, lo: number, hi: number): boolean => Number.isSafeInteger(n) && range(n, lo, hi);
function requireValue(ok: unknown, code = "INSTRUMENT_PACK_INVALID"): asserts ok {
  if (!ok) throw new Error(code);
}

export function validateInstrumentPack(pack: InstrumentPack): InstrumentPack {
  requireValue(pack && typeof pack === "object");
  requireValue(pack.pedal === "unsupported","PIANO_PEDAL_UNSUPPORTED");
  requireValue(pack.releaseTriggers === "unsupported","PIANO_RELEASE_TRIGGER_UNSUPPORTED");
  requireValue(pack.schemaVersion === "instrument-pack.v1" &&
    pack.adapterVersion === "multisample-buffer-source.v1" && id(pack.packId) && id(pack.packVersion) &&
    typeof pack.sourceUrl === "string" && /^https:\/\/[^\s]+$/.test(pack.sourceUrl) &&
    hash(pack.sourceArchiveSha256) && pack.license?.spdx === "CC0-1.0" && hash(pack.license.textSha256) &&
    pack.pedal === "unsupported" && pack.releaseTriggers === "unsupported" &&
    range(pack.releaseSeconds,0.005,2) && integer(pack.maxVoices,1,32) &&
    Array.isArray(pack.samples) && pack.samples.length >= 1 && pack.samples.length <= 64);
  let encoded = 0;
  let decoded = 0;
  const ids = new Set<string>();
  for (const s of pack.samples) {
    requireValue(s && typeof s === "object" && id(s.sampleId) && !ids.has(s.sampleId));
    ids.add(s.sampleId);
    requireValue(typeof s.path === "string" && s.path.length <= 180 &&
      /^[A-Za-z0-9_#./-]+\.wav$/.test(s.path) && !s.path.startsWith("/") &&
      s.path.split("/").every((p: string) => p !== ".." && p !== "." && p !== "") && hash(s.sha256) &&
      integer(s.byteSize,44,4*1024**2) && integer(s.frames,1,48_000_000) &&
      [22050,44100,48000].includes(s.sampleRate) && (s.channels === 1 || s.channels === 2) &&
      (s.bitDepth === 16 || s.bitDepth === 24) && integer(s.rootMidi,0,127) &&
      integer(s.keyLo,0,127) && integer(s.keyHi,s.keyLo,127) &&
      integer(s.velocityLo,1,127) && integer(s.velocityHi,s.velocityLo,127));
    encoded += s.byteSize;
    // decodeAudioData resamples to the context: budget at the maximum 48k target.
    decoded += Math.ceil(s.frames / s.sampleRate * 48000) * s.channels * 4;
    requireValue(encoded <= 16*1024**2 && decoded <= 64*1024**2 && s.frames/s.sampleRate <= 60,
      "INSTRUMENT_RESOURCE_LIMIT");
    requireValue(s.byteSize >= 44 + s.frames * s.channels * s.bitDepth / 8);
    if (s.loop !== undefined) requireValue(s.loop && integer(s.loop.startFrame,0,s.frames-2) &&
      integer(s.loop.endFrame,s.loop.startFrame+2,s.frames));
  }
  for (let i=0;i<pack.samples.length;i++) for (let j=i+1;j<pack.samples.length;j++) {
    const a=pack.samples[i]!, b=pack.samples[j]!;
    requireValue(a.keyHi < b.keyLo || b.keyHi < a.keyLo ||
      a.velocityHi < b.velocityLo || b.velocityHi < a.velocityLo,"INSTRUMENT_ZONE_OVERLAP");
  }
  return pack;
}

/** Caller must use an approved catalog manifest. A matching hash is not a license review. */
export async function verifyInstrumentSample(pack: InstrumentPack, sampleId: string, bytes: Uint8Array): Promise<void> {
  validateInstrumentPack(pack);
  const s=pack.samples.find(v=>v.sampleId === sampleId);
  requireValue(s,"INSTRUMENT_PACK_UNAVAILABLE");
  requireValue(bytes.byteLength === s.byteSize,"INSTRUMENT_SAMPLE_SIZE_MISMATCH");
  const digest=await crypto.subtle.digest("SHA-256",new Uint8Array(bytes).buffer);
  const actual=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,"0")).join("");
  requireValue(actual === s.sha256,"INSTRUMENT_SAMPLE_HASH_MISMATCH");
  const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
  const text=(offset:number,n:number):string=>String.fromCharCode(...bytes.subarray(offset,offset+n));
  requireValue(text(0,4)==="RIFF" && text(8,4)==="WAVE" && view.getUint32(4,true)+8 === bytes.length,"INSTRUMENT_WAV_INVALID");
  let format=false, data=false;
  for (let offset=12;offset+8<=bytes.length;) {
    const size=view.getUint32(offset+4,true), start=offset+8;
    requireValue(start+size<=bytes.length,"INSTRUMENT_WAV_INVALID");
    if (text(offset,4)==="fmt ") {
      requireValue(!format && size>=16 && view.getUint16(start,true)===1 &&
        view.getUint16(start+2,true)===s.channels && view.getUint32(start+4,true)===s.sampleRate &&
        view.getUint16(start+14,true)===s.bitDepth,"INSTRUMENT_MEDIA_PROFILE_INVALID");
      format=true;
    }
    if (text(offset,4)==="data") {
      requireValue(!data && size===s.frames*s.channels*s.bitDepth/8,"INSTRUMENT_MEDIA_PROFILE_INVALID");
      data=true;
    }
    offset=start+size+(size%2);
  }
  requireValue(format && data,"INSTRUMENT_WAV_INVALID");
}

export function planPianoVoices(pack: InstrumentPack, notes: readonly PianoNote[], durationSeconds: number,
  pedalEvents: readonly unknown[] = []): readonly PianoVoice[] {
  validateInstrumentPack(pack);
  requireValue(pedalEvents.length === 0,"PIANO_PEDAL_UNSUPPORTED");
  requireValue(range(durationSeconds,0.1,300) && Array.isArray(notes) && notes.length <= 2000,"PIANO_PLAN_INVALID");
  const seen=new Set<string>();
  const voices=notes.map(n=>{
    requireValue(n && id(n.noteId) && !seen.has(n.noteId) && integer(n.midi,0,127) && integer(n.velocity,1,127) &&
      range(n.startSeconds,0,durationSeconds) && range(n.gateSeconds,0.005,30) && range(n.detuneCents,-100,100),"PIANO_PLAN_INVALID");
    seen.add(n.noteId);
    const sample=pack.samples.find(s=>n.midi>=s.keyLo && n.midi<=s.keyHi && n.velocity>=s.velocityLo && n.velocity<=s.velocityHi);
    requireValue(sample,"INSTRUMENT_NOTE_UNMAPPED");
    const playbackRate=2**((n.midi-sample.rootMidi+n.detuneCents/100)/12);
    requireValue(range(playbackRate,0.25,4),"INSTRUMENT_PITCH_RANGE_EXCEEDED");
    const releaseSeconds=n.startSeconds+n.gateSeconds, stopSeconds=releaseSeconds+pack.releaseSeconds;
    requireValue(stopSeconds<=durationSeconds+1e-9,"PIANO_RELEASE_OUT_OF_RANGE");
    return {noteId:n.noteId,sampleId:sample.sampleId,playbackRate,gain:n.velocity/127,
      startSeconds:n.startSeconds,releaseSeconds,stopSeconds};
  });
  assertPolyphony(voices,pack.maxVoices);
  return voices;
}

function assertPolyphony(voices: readonly PianoVoice[], maximum: number): void {
  const edges=voices.flatMap(v=>[{time:v.startSeconds,delta:1},{time:v.stopSeconds,delta:-1}])
    .sort((a,b)=>a.time-b.time||a.delta-b.delta);
  let active=0;
  for (const e of edges) { active+=e.delta; requireValue(active<=maximum,"INSTRUMENT_POLYPHONY_EXCEEDED"); }
}

/** Uses only buffers decoded from verifyInstrumentSample-approved bytes. No fetch or catalog admission.
 * Tone's raw OfflineAudioContext can consume this adapter in a later v2 compiler.
 */
export function schedulePianoVoices(context: BaseAudioContext, destination: AudioNode,
  pack: InstrumentPack, voices: readonly PianoVoice[], buffers: ReadonlyMap<string,AudioBuffer>): readonly AudioBufferSourceNode[] {
  validateInstrumentPack(pack);
  requireValue(context.sampleRate === 44100 || context.sampleRate === 48000,"INSTRUMENT_MEDIA_PROFILE_INVALID");
  requireValue(Array.isArray(voices) && voices.length <= 2000,"PIANO_PLAN_INVALID");
  const allocated=[...new Set(buffers.values())].reduce((sum,b)=>sum+b.length*b.numberOfChannels*4,0);
  requireValue(allocated<=64*1024**2,"INSTRUMENT_RESOURCE_LIMIT");
  // Resolve every dependency before creating the first voice.
  const resolved=voices.map(v=>{
    const sample=pack.samples.find(s=>s.sampleId === v.sampleId), buffer=buffers.get(v.sampleId);
    requireValue(sample && buffer,"INSTRUMENT_PACK_UNAVAILABLE");
    requireValue(buffer.numberOfChannels === sample.channels &&
      Math.abs(buffer.duration-sample.frames/sample.sampleRate)<=1/sample.sampleRate+1/buffer.sampleRate,
      "INSTRUMENT_MEDIA_PROFILE_INVALID");
    requireValue(range(v.startSeconds,0,300) && range(v.releaseSeconds,v.startSeconds+.005,300) &&
      range(v.releaseSeconds,v.startSeconds+.005,v.startSeconds+30) &&
      range(v.stopSeconds,v.releaseSeconds+.005,300) &&
      Math.abs(v.stopSeconds-v.releaseSeconds-pack.releaseSeconds)<1e-9 && range(v.gain,0,1) &&
      range(v.playbackRate,.25,4),"PIANO_PLAN_INVALID");
    return {voice:v,sample,buffer};
  });
  assertPolyphony(voices,pack.maxVoices);
  return resolved.map(({voice:v,sample,buffer})=>{
    const source=context.createBufferSource(), envelope=context.createGain();
    source.buffer=buffer;
    source.playbackRate.value=v.playbackRate;
    if(sample.loop){
      source.loop=true;
      source.loopStart=sample.loop.startFrame/sample.sampleRate;
      source.loopEnd=sample.loop.endFrame/sample.sampleRate;
    }
    envelope.gain.setValueAtTime(0,v.startSeconds);
    envelope.gain.linearRampToValueAtTime(v.gain,v.startSeconds+Math.min(.005,(v.releaseSeconds-v.startSeconds)/2));
    envelope.gain.setValueAtTime(v.gain,v.releaseSeconds);
    envelope.gain.linearRampToValueAtTime(0,v.stopSeconds);
    source.connect(envelope);envelope.connect(destination);
    source.onended=()=>{source.disconnect();envelope.disconnect();};
    source.start(v.startSeconds);source.stop(v.stopSeconds);
    return source;
  });
}
