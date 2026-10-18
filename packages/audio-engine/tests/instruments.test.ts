import { describe, expect, it } from "vitest";
import { fixture } from "./fixtures/instrument-fixture.js";
import * as engine from "../src/index.js";
import type { InstrumentPack, PianoNote } from "../src/instruments.js";

const note=(overrides:Partial<PianoNote>={}):PianoNote=>({noteId:"n1",midi:60,velocity:63,
  startSeconds:0,gateSeconds:0.04,detuneCents:0,...overrides});

describe("versioned instrument pack preparation",()=>{
  it("binds local PCM bytes and metadata to their manifest hash",async()=>{
    const {pack,bytes}=await fixture();
    expect(engine.validateInstrumentPack(pack)).toBe(pack);
    await expect(engine.verifyInstrumentSample(pack,"soft",bytes)).resolves.toBeUndefined();
    const changed=bytes.slice();changed[44]=changed[44]!^1;
    await expect(engine.verifyInstrumentSample(pack,"soft",changed)).rejects.toThrow("INSTRUMENT_SAMPLE_HASH_MISMATCH");
  });
  it("selects separate velocity zones at the exact MIDI boundary",async()=>{
    const {pack}=await fixture();
    const voices=engine.planPianoVoices(pack,[note(),note({noteId:"n2",velocity:64})],0.2);
    expect(voices.map(v=>v.sampleId)).toEqual(["soft","loud"]);
    expect(voices[0]!.gain).toBeCloseTo(63/127);
  });
  it("transposes by rootMidi and creates independent release gates",async()=>{
    const {pack}=await fixture();
    const voices=engine.planPianoVoices(pack,[note({midi:72}),note({noteId:"n2",startSeconds:0.02})],0.2);
    expect(voices[0]!.playbackRate).toBe(2);
    expect(voices.map(v=>v.stopSeconds)).toEqual([0.08,0.1]);
  });
  it("rejects pedal input explicitly instead of silently ignoring it",async()=>{
    const {pack}=await fixture();
    expect(()=>engine.planPianoVoices(pack,[note()],0.2,[{seconds:0,value:127}])).toThrow("PIANO_PEDAL_UNSUPPORTED");
  });
  it.each(["../user.wav","/tmp/user.wav","https://evil.invalid/a.wav","samples/../user.wav"])("rejects unsafe sample path %s",async path=>{
    const {pack}=await fixture();
    const invalid={...pack,samples:[{...pack.samples[0]!,path}]};
    expect(()=>engine.validateInstrumentPack(invalid)).toThrow("INSTRUMENT_PACK_INVALID");
  });
  it("rejects ambiguous zones, unknown version and unbounded buffers",async()=>{
    const {pack}=await fixture();
    expect(()=>engine.validateInstrumentPack({...pack,schemaVersion:"instrument-pack.v9" as "instrument-pack.v1"})).toThrow("INSTRUMENT_PACK_INVALID");
    expect(()=>engine.validateInstrumentPack({...pack,samples:[pack.samples[0]!,{...pack.samples[0]!,sampleId:"ambiguous"}]})).toThrow("INSTRUMENT_ZONE_OVERLAP");
    expect(()=>engine.validateInstrumentPack({...pack,samples:[{...pack.samples[0]!,frames:48_000_000}]})).toThrow("INSTRUMENT_RESOURCE_LIMIT");
  });
  it("rejects missing samples, excess polyphony and release outside output window",async()=>{
    const {pack}=await fixture();
    expect(()=>engine.planPianoVoices(pack,[note({midi:90})],0.2)).toThrow("INSTRUMENT_NOTE_UNMAPPED");
    expect(()=>engine.planPianoVoices({...pack,maxVoices:1},[note(),note({noteId:"n2"})],0.2)).toThrow("INSTRUMENT_POLYPHONY_EXCEEDED");
    expect(()=>engine.planPianoVoices(pack,[note({gateSeconds:0.1})],0.1)).toThrow("PIANO_RELEASE_OUT_OF_RANGE");
  });
});

it("enforces the pack voice bound again at the audio scheduling boundary",async()=>{
  const {pack}=await fixture();
  const voices=engine.planPianoVoices(pack,[note(),note({noteId:"n2"})],.2);
  const fakeBuffer={length:3840,numberOfChannels:1,sampleRate:48000,duration:.08} as AudioBuffer;
  const context={sampleRate:48000} as BaseAudioContext;
  expect(()=>engine.schedulePianoVoices(context,{} as AudioNode,{...pack,maxVoices:1},voices,
    new Map([["soft",fakeBuffer]]))).toThrow("INSTRUMENT_POLYPHONY_EXCEEDED");
});

it("rejects release-trigger capability and out-of-buffer loop markers",async()=>{
  const {pack}=await fixture();
  expect(()=>engine.validateInstrumentPack({...pack,releaseTriggers:"samples" as "unsupported"})).toThrow("PIANO_RELEASE_TRIGGER_UNSUPPORTED");
  expect(()=>engine.validateInstrumentPack({...pack,samples:[{...pack.samples[0]!,loop:{startFrame:0,endFrame:3841}}]})).toThrow("INSTRUMENT_PACK_INVALID");
});

it("refuses missing decoded dependencies before starting any voice",async()=>{
  const {pack}=await fixture();
  const voices=engine.planPianoVoices(pack,[note()],.2);
  expect(()=>engine.schedulePianoVoices({sampleRate:48000} as BaseAudioContext,{} as AudioNode,pack,voices,new Map())).toThrow("INSTRUMENT_PACK_UNAVAILABLE");
});

it("rejects altered release times at the scheduling boundary",async()=>{
  const {pack}=await fixture();
  const voices=engine.planPianoVoices(pack,[note()],.2).map(v=>({...v,stopSeconds:30}));
  const fakeBuffer={length:3840,numberOfChannels:1,sampleRate:48000,duration:.08} as AudioBuffer;
  expect(()=>engine.schedulePianoVoices({sampleRate:48000} as BaseAudioContext,{} as AudioNode,pack,voices,
    new Map([["soft",fakeBuffer]]))).toThrow("PIANO_PLAN_INVALID");
});

it("schedules the shortest valid gate from a nonzero onset",async()=>{
  const {pack}=await fixture();
  const voices=engine.planPianoVoices(pack,[note({startSeconds:1,gateSeconds:.005})],1.2);
  let starts=0;
  const source={playbackRate:{value:1},connect(){},disconnect(){},start(){starts++;},stop(){}};
  const gain={gain:{setValueAtTime(){},linearRampToValueAtTime(){}},connect(){},disconnect(){}};
  const context={sampleRate:48000,createBufferSource:()=>source,createGain:()=>gain} as unknown as BaseAudioContext;
  const buffer={length:3840,numberOfChannels:1,sampleRate:48000,duration:.08} as AudioBuffer;
  engine.schedulePianoVoices(context,{} as AudioNode,pack,voices,new Map([["soft",buffer]]));
  expect(starts).toBe(1);
});
