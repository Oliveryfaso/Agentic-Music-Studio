// Engineering fixture only: existing self-authored click, never real piano audio.
import { build } from "esbuild";
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
if(process.argv.length!==3)throw new Error("usage: node scripts/run_p1_piano_adapter_probe.mjs NEW_OUTPUT_ROOT");
const output=resolve(process.argv[2]);
await mkdir(output,{recursive:false});
await build({entryPoints:["packages/audio-engine/tests/fixtures/instrument-fixture.ts"],outfile:resolve(output,"fixture.mjs"),bundle:true,format:"esm",platform:"node",packages:"external"});
const {fixture}=await import(resolve(output,"fixture.mjs"));
const {pack,bytes}=await fixture();
await build({stdin:{contents:`
import * as engine from "./packages/audio-engine/src/index.ts";
import {assertPianoProbeResult} from "./packages/audio-engine/tests/fixtures/piano-probe-acceptance.ts";
window.runProbe=async(pack,raw)=>{
 const bytes=new Uint8Array(raw);
 await engine.verifyInstrumentSample(pack,"soft",bytes);
 const ctxRate=48000;
 const note=(id,midi,velocity,start=0,gate=.04)=>({noteId:id,midi,velocity,startSeconds:start,gateSeconds:gate,detuneCents:0});
 async function render(notes,loop=false){
   const ctx=new OfflineAudioContext(1,Math.ceil(.3*ctxRate),ctxRate);
   const buffer=await ctx.decodeAudioData(bytes.slice().buffer);
   const usePack={...pack,samples:pack.samples.map(s=>({...s,...(loop?{loop:{startFrame:0,endFrame:s.frames}}:{})}))};
   const voices=engine.planPianoVoices(usePack,notes,.3);
   engine.schedulePianoVoices(ctx,ctx.destination,usePack,voices,new Map(usePack.samples.map(s=>[s.sampleId,buffer])));
   return (await ctx.startRendering()).getChannelData(0);
 }
 function energy(data,start=0,end=.03){let sum=0;for(let i=Math.round(start*ctxRate);i<Math.round(end*ctxRate);i++)sum+=data[i]**2;return sum;}
 function frequency(data){let crossings=0;for(let i=241;i<1200;i++)if(data[i-1]<0&&data[i]>=0)crossings++;return crossings/(959/ctxRate);}
 const base=await render([note("base",60,64)]),octave=await render([note("octave",72,64)]);
 const soft=await render([note("soft",60,32)]);
 const released=await render([note("old",60,64,0,.02)],true);
 const retrigger=await render([note("old",60,64,0,.02),note("new",60,64,.04,.1)],true);
 const result={fixture:"self-authored builtin click, not piano",baseHz:frequency(base),octaveHz:frequency(octave),energyRatio:energy(base)/energy(soft),releasedAfterStop:energy(released,.07,.2),newVoiceSurvivesOldRelease:energy(retrigger,.09,.12),allVoicesStopped:energy(retrigger,.20,.29)};
 assertPianoProbeResult(result);
 return result;
};`,resolveDir:process.cwd(),loader:"ts"},outfile:resolve(output,"probe.js"),bundle:true,format:"iife",platform:"browser"});
await writeFile(resolve(output,"probe.html"),'<!doctype html><meta charset="utf-8"><script src="probe.js"></script>');
let browser;
try{
 browser=await chromium.launch({headless:true});
 const page=await browser.newPage();
 await page.route("http://**/*",route=>route.abort());
 await page.route("https://**/*",route=>route.abort());
 await page.goto(new URL("file://"+resolve(output,"probe.html")).href);
 const result=await page.evaluate(async({pack,bytes})=>window.runProbe(pack,bytes),{pack,bytes:Array.from(bytes)});
 const report={schemaVersion:"piano-adapter-probe.v1",date:new Date().toISOString(),chromiumVersion:browser.version(),providerRequests:0,providerTokens:0,realPianoQualityMeasured:false,result};
 await writeFile(resolve(output,"report.json"),JSON.stringify(report,null,2));
 console.log(JSON.stringify(report,null,2));
}finally{await browser?.close();}
