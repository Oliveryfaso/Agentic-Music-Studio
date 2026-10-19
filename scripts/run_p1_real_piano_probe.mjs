// Real audited piano boundary only. Does not create a project, v2 Revision or user-facing Job.
import { build } from "esbuild";
import { chromium } from "playwright";
import { randomBytes, createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdir, writeFile, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { execFileSync } from "node:child_process";
if(process.argv.length!==5)throw new Error("usage: node scripts/run_p1_real_piano_probe.mjs SOURCE_ROOT MANIFEST_SHA256 NEW_OUTPUT_ROOT");
const sourceRoot=resolve(process.argv[2]), manifestSha256=process.argv[3], output=resolve(process.argv[4]);
await mkdir(output,{recursive:false});
const notes=[];
const melody=[60,64,67,72,71,67,64,62];
for(let i=0;i<48;i++)notes.push({noteId:"melody-"+i,midi:melody[i%8],velocity:88,startSeconds:i*.5,gateSeconds:.33,detuneCents:0});
for(let i=0;i<12;i++)notes.push({noteId:"bass-"+i,midi:[48,45,53,43][i%4],velocity:88,startSeconds:i*2,gateSeconds:1.2,detuneCents:0});
notes.push({noteId:"loop-sustain",midi:24,velocity:64,startSeconds:12,gateSeconds:10,detuneCents:0},
 {noteId:"retrigger-old",midi:60,velocity:88,startSeconds:23.5,gateSeconds:.4,detuneCents:0},
 {noteId:"retrigger-new",midi:60,velocity:88,startSeconds:23.8,gateSeconds:.8,detuneCents:0},
 {noteId:"upper-range",midi:107,velocity:88,startSeconds:24,gateSeconds:.2,detuneCents:0});
const noteHash=createHash("sha256").update(JSON.stringify(notes)).digest("hex");
await writeFile(resolve(output,"self-authored-score.json"),JSON.stringify({schemaVersion:"experimental-piano-score.v1",durationSeconds:30,notes},null,2));
let browser,server,timer,deadline;
let phase="setup",guardTripped=false,deadlineTripped=false;
const memory=[],began=performance.now(),rssGuardBytes=3*1024**3;
function sample(){
 const rows=execFileSync("ps",["-axo","pid=,ppid=,rss="],{encoding:"utf8"}).trim().split("\n").map(l=>l.trim().split(/\s+/).map(Number));
 const own=new Set([process.pid]);
 for(let pass=0;pass<12;pass++)for(const [pid,ppid] of rows)if(own.has(ppid))own.add(pid);
 const bytes=rows.filter(([pid])=>own.has(pid)).reduce((n,[,,rss])=>n+rss,0)*1024;
 memory.push({phase,elapsedMs:Math.round(performance.now()-began),processTreeRssBytes:bytes});
 if(bytes>rssGuardBytes&&!guardTripped){guardTripped=true;void browser?.close().catch(()=>undefined);}
}
const tokens=[];
try{
 sample();timer=setInterval(sample,200);
 await build({stdin:{contents:'export {loadReviewedInstrumentCatalog} from "./services/render-worker/src/instrument-catalog.ts"; export {LoopbackRenderServer,createBuiltinClickWav,launchWithinProbeBudget} from "./services/render-worker/src/runtime.ts";',resolveDir:process.cwd(),loader:"ts"},outfile:resolve(output,"host.mjs"),bundle:true,format:"esm",platform:"node",packages:"external"});
 const host=await import(resolve(output,"host.mjs"));
 phase="catalog";
 const catalog=await host.loadReviewedInstrumentCatalog({root:sourceRoot,manifestSha256});
 await build({stdin:{contents:`
import * as engine from "./packages/audio-engine/src/index.ts";
window.runRealPianoProbe=async({pack,packToken,outputTokens,notes})=>{
 const original=JSON.stringify(notes),rate=48000,duration=30;
 engine.validateInstrumentPack(pack);
 const decoding=new OfflineAudioContext(2,1,rate),buffers=new Map();
 const loadStart=performance.now();
 for(const sample of pack.samples){
  const response=await fetch("/instrument-packs/"+packToken+"/"+sample.sampleId+".wav");
  if(!response.ok)throw new Error("INSTRUMENT_PACK_UNAVAILABLE");
  const bytes=new Uint8Array(await response.arrayBuffer());
  await engine.verifyInstrumentSample(pack,sample.sampleId,bytes);
  buffers.set(sample.sampleId,await decoding.decodeAudioData(bytes.slice().buffer));
 }
 const loadDecodeMs=performance.now()-loadStart;
 const missing=await fetch("/instrument-packs/"+"0".repeat(32)+"/missing.wav");
 if(missing.status!==404)throw new Error("MISSING_PACK_NOT_REJECTED");
 const graph={schemaVersion:"audio-graph-spec.v1",engineVersion:"motif-forge-audio-engine.v1",durationSeconds:duration,sampleRate:rate,channels:2,masterGainDb:-12,reverbDecaySeconds:.2,
  tracks:[{trackId:"legacy",name:"unchanged legacy warm pad",gainDb:-6,pan:0,eq:{lowDb:0,midDb:0,highDb:0},reverbSend:0,kind:"synth",presetId:"warm_pad",notes:notes.map(n=>({midi:n.midi,startSeconds:n.startSeconds,durationSeconds:n.gateSeconds,velocity:n.velocity/127}))}]};
 function normalize(buffer){
  let sum=0,peak=0;
  for(let ch=0;ch<2;ch++)for(const x of buffer.getChannelData(ch)){sum+=x*x;peak=Math.max(peak,Math.abs(x));}
  const rms=Math.sqrt(sum/(buffer.length*2));
  if(!Number.isFinite(rms)||rms<=0||!Number.isFinite(peak))throw new Error("PIANO_PROBE_SILENT_OR_INVALID");
  const gain=Math.min(.04/rms,.95/peak);
  for(let ch=0;ch<2;ch++){const data=buffer.getChannelData(ch);for(let i=0;i<data.length;i++)data[i]*=gain;}
  let tail=0;
  for(let ch=0;ch<2;ch++){const data=buffer.getChannelData(ch);for(let i=28*rate;i<data.length;i++)tail+=data[i]*data[i];}
  return {rawRms:rms,gain,normalizedRms:rms*gain,tailRmsAfter28:Math.sqrt(tail/(2*2*rate))};
 }
 const results=[];
 for(const variant of ["legacy","piano-mechanical","piano-expression","rollback"]){
  const start=performance.now();let buffer;
  if(variant==="legacy"||variant==="rollback")buffer=await engine.renderAudioGraphOffline(graph);
  else{
   const performanceNotes=notes.map((n,i)=>variant==="piano-expression"&&n.noteId.startsWith("melody")?{...n,velocity:[60,76,92,108][i%4],startSeconds:Math.max(0,n.startSeconds+[-.01,0,.01,0][i%4]),gateSeconds:n.gateSeconds*[.8,1,1.2][i%3]}:{...n});
   const context=new OfflineAudioContext(2,duration*rate,rate),master=context.createGain();master.gain.value=.2;master.connect(context.destination);
   const voices=engine.planPianoVoices(pack,performanceNotes,duration);
   engine.schedulePianoVoices(context,master,pack,voices,buffers);
   buffer=await context.startRendering();
  }
  const metrics=normalize(buffer);
  if(!Number.isFinite(metrics.tailRmsAfter28)||metrics.tailRmsAfter28>1e-7)throw new Error("PIANO_PROBE_TAIL_NOT_RELEASED");
  const wav=engine.encodeStereoPcm24(buffer);
  const result=await fetch("/outputs/"+outputTokens[variant],{method:"POST",headers:{"Content-Type":"audio/wav"},body:wav.buffer});
  if(!result.ok)throw new Error("PIANO_PROBE_OUTPUT_REJECTED");
  results.push({variant,renderAndWriteMs:performance.now()-start,bytes:wav.length,...metrics});
 }
 if(JSON.stringify(notes)!==original)throw new Error("PIANO_PROBE_SCORE_MUTATED");
 return {loadDecodeMs,decodedBufferBytes:[...buffers.values()].reduce((n,b)=>n+b.length*b.numberOfChannels*4,0),verifiedSamples:buffers.size,originalScoreUnchanged:true,missingPackHttpStatus:missing.status,results};
};`,resolveDir:process.cwd(),loader:"ts"},outfile:resolve(output,"probe.js"),bundle:true,format:"iife",platform:"browser"});
 server=new host.LoopbackRenderServer(resolve(output,"probe.js"),host.createBuiltinClickWav());
 const packToken=randomBytes(16).toString("hex");server.registerInstrumentPack(packToken,catalog);await server.start();
 const outputTokens={};
 for(const variant of ["legacy","piano-mechanical","piano-expression","rollback"]){const token=randomBytes(16).toString("hex");tokens.push(token);outputTokens[variant]=token;server.registerSink(token,resolve(output,variant+".wav"),8640044);}
 if(guardTripped)throw new Error("PIANO_PROBE_RESOURCE_GUARD");
 deadline=setTimeout(()=>{deadlineTripped=true;void browser?.close().catch(()=>undefined);},150000);
 phase="browser";browser=await host.launchWithinProbeBudget(
  ()=>chromium.launch({headless:true,args:["--mute-audio"]}),()=>guardTripped||deadlineTripped);
 const page=await browser.newPage();
 await page.route("**/*",route=>{try{return new URL(route.request().url()).origin===server.origin?route.continue():route.abort();}catch{return route.abort();}});
 await page.goto(server.origin+"/render");
 phase="real-piano-render";
 const report=await page.evaluate(async args=>window.runRealPianoProbe(args),{pack:catalog.manifest,packToken,outputTokens,notes});
 sample();if(guardTripped||deadlineTripped)throw new Error("PIANO_PROBE_RESOURCE_GUARD");
 const files=[];
 for(const row of report.results){const path=resolve(output,row.variant+".wav"),hash=createHash("sha256");for await(const chunk of createReadStream(path))hash.update(chunk);files.push({filename:row.variant+".wav",bytes:(await stat(path)).size,sha256:hash.digest("hex")});}
 const resource={method:"200ms aggregate RSS of this Node process and descendants; shared pages may double count; sampled, excludes VM/PG and other services",rssGuardBytes,guardTripped,sampleCount:memory.length,sampledMaximumProcessTreeRssBytes:Math.max(...memory.map(x=>x.processTreeRssBytes))};
 const result={schemaVersion:"real-piano-boundary.v1",date:new Date().toISOString(),scope:"audited pack -> nonce catalog -> shared adapter -> OfflineAudioContext WAV; no production v2 IR/Job/UI",packId:catalog.manifest.packId,packVersion:catalog.manifest.packVersion,manifestSha256,sourceArchiveSha256:catalog.manifest.sourceArchiveSha256,scoreSha256:noteHash,chromiumVersion:browser.version(),pedalSupported:false,subjectiveQualityMeasured:false,providerRequests:0,providerTokens:0,normalization:"common full-buffer RMS target .04, capped at peak .95; not LUFS or perceived loudness matching",...report,files,resource};
 await writeFile(resolve(output,"report.json"),JSON.stringify(result,null,2));
 console.log(JSON.stringify(result,null,2));
}finally{
 clearInterval(timer);clearTimeout(deadline);await browser?.close();
 for(const token of tokens)await server?.cancelSink(token);
 await server?.close();await writeFile(resolve(output,"memory-samples.json"),JSON.stringify(memory));
}
