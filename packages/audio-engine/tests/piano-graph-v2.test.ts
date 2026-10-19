import { expect, it } from 'vitest';
import { validateAudioGraphSpec } from '../src/validation.js';
import { estimateRenderCapacity } from '../src/capacity.js';
import type { AudioGraphSpec } from '../src/contracts.js';

function graph(): AudioGraphSpec {
  return {schemaVersion:'audio-graph-spec.v2',engineVersion:'motif-forge-audio-engine.v2',
    durationSeconds:2,sampleRate:48000,channels:2,masterGainDb:-5,reverbDecaySeconds:2.4,
    tracks:[{trackId:'piano',name:'piano',kind:'multisample',gainDb:0,pan:0,
      eq:{lowDb:0,midDb:0,highDb:0},reverbSend:0,
      instrumentPack:{packId:'freepats:upright-kw-small',packVersion:'2019-07-03.motif1',manifestSha256:'a'.repeat(64)},
      notes:[{noteId:'self-note',midi:60,velocity:72,startSeconds:0.01,gateSeconds:0.25,detuneCents:0}]}],
  } as unknown as AudioGraphSpec;
}

it('accepts independent pinned piano graph and estimates actual PCM capacity',()=>{
  const value=graph();
  expect(validateAudioGraphSpec(value)).toBe(value);
  expect(estimateRenderCapacity(value).wavBytes).toBe(576044);
});

it('rejects mixed engine/schema and malformed or excessive piano events',()=>{
  expect(()=>validateAudioGraphSpec({...graph(),engineVersion:'motif-forge-audio-engine.v1'} as unknown as AudioGraphSpec)).toThrow('AUDIO_ENGINE_VERSION_UNSUPPORTED');
  const value=graph() as any;
  value.tracks[0].notes[0].velocity=0;
  expect(()=>validateAudioGraphSpec(value)).toThrow('AUDIO_GRAPH_INVALID');
  const large=graph() as any;
  large.tracks[0].notes=Array.from({length:2001},(_,i)=>({...large.tracks[0].notes[0],noteId:`note-${i}`}));
  expect(()=>validateAudioGraphSpec(large)).toThrow('PIANO_NOTE_BUDGET_EXCEEDED');
});
