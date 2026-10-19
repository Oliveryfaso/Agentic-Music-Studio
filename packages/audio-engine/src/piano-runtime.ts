/** Resolve only nonce-bound samples from the admitted host catalog. */
import type { InstrumentBinding, PianoTrackSpec } from './contracts.js';
import { planPianoVoices, verifyInstrumentSample, type InstrumentPack, type PianoVoice } from './instruments.js';

export type PreparedPiano = Readonly<{pack:InstrumentPack;voices:readonly PianoVoice[];buffers:ReadonlyMap<string,AudioBuffer>}>;
export async function preparePiano(track:PianoTrackSpec,binding:InstrumentBinding|undefined,durationSeconds:number,sampleRate:number):Promise<PreparedPiano>{
  const ref=track.instrumentPack;
  if(!binding) throw new Error('INSTRUMENT_PACK_UNAVAILABLE');
  if(binding.manifestSha256!==ref.manifestSha256 || binding.manifest.packId!==ref.packId || binding.manifest.packVersion!==ref.packVersion)
    throw new Error('INSTRUMENT_MANIFEST_HASH_MISMATCH');
  if(!/^\/instrument-packs\/[a-f0-9]{32}$/.test(binding.baseUrl)) throw new Error('INSTRUMENT_BINDING_INVALID');
  const pack=binding.manifest;
  const voices=planPianoVoices(pack,track.notes,durationSeconds);
  const context=new OfflineAudioContext(1,1,sampleRate);
  const buffers=new Map<string,AudioBuffer>();
  for(const id of new Set(voices.map(v=>v.sampleId))){
    const response=await fetch(`${binding.baseUrl}/${encodeURIComponent(id)}.wav`,{redirect:'error'});
    if(!response.ok) throw new Error('INSTRUMENT_PACK_UNAVAILABLE');
    const bytes=new Uint8Array(await response.arrayBuffer());
    await verifyInstrumentSample(pack,id,bytes);
    buffers.set(id,await context.decodeAudioData(new Uint8Array(bytes).buffer));
  }
  return {pack,voices,buffers};
}
