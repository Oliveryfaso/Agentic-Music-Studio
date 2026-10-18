// Isolated P1-A1 host integration: production HTTP/executor, no DB/.env/models.
import { spawn, execFileSync } from "node:child_process";
import { mkdir, readFile, writeFile, unlink } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { performance } from "node:perf_hooks";
import { build } from "esbuild";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
if (process.argv.length !== 3) throw new Error("usage: node scripts/run_p1a_render_capacity.mjs NEW_OUTPUT_ROOT");
const output = resolve(process.argv[2]);
await mkdir(output, { recursive: false });
await mkdir(resolve(output, "temp"));
await mkdir(resolve(output, "artifacts"));
const harness = resolve(repo, "services/render-worker/dist/p1a-host-probe.js");
await mkdir(dirname(harness), { recursive: true });
await build({absWorkingDir:repo,entryPoints:["services/render-worker/src/page-entry.ts"],outfile:resolve(dirname(harness),"page-entry.js"),bundle:true,format:"esm",platform:"browser",target:"es2022"});
await build({absWorkingDir:repo,stdin:{contents:`
import {ChromiumRenderExecutor} from "./services/render-worker/src/executor.ts";
import {createRenderServiceServer} from "./services/render-worker/src/server.ts";
import {buildThirtySecondSpikeGraph} from "./packages/audio-engine/src/spike-fixture.ts";
import {writeFile} from "node:fs/promises";
import {resolve} from "node:path";
const output=process.argv[2];
const fixture=buildThirtySecondSpikeGraph();
const graph={...fixture,durationSeconds:300,tracks:fixture.tracks.map(t=>t.kind==="synth"?
 {...t,notes:Array.from({length:10},(_,i)=>t.notes.map(n=>({...n,startSeconds:n.startSeconds+30*i}))).flat()}:
 {...t,triggers:Array.from({length:10},(_,i)=>t.triggers.map(n=>({...n,startSeconds:n.startSeconds+30*i}))).flat()})};
await writeFile(resolve(output,"five-minute-graph.json"),JSON.stringify(graph));
const executor=new ChromiumRenderExecutor(resolve(output,"temp"));
await executor.start();
const service=createRenderServiceServer(executor);
await service.start();
console.log(JSON.stringify({ready:true,origin:service.origin,pid:process.pid,tracks:graph.tracks.length,events:graph.tracks.reduce((n,t)=>n+(t.notes??t.triggers).length,0)}));
let closing=false;
async function close(){if(closing)return;closing=true;await service.close();await executor.close();process.exit(0);}
process.once("SIGTERM",()=>void close());process.once("SIGINT",()=>void close());
`,resolveDir:repo,sourcefile:"p1a-host-probe.ts"},outfile:harness,bundle:true,format:"esm",platform:"node",target:"node20",packages:"external"});
const env={PATH:process.env.PATH,HOME:process.env.HOME,TMPDIR:process.env.TMPDIR};
let phase="startup";
const memory=[];
const began=performance.now();
let guardTripped=false;
let service;
let client;
let serviceExit;
const rssGuardBytes=3*1024**3;
function sample(){
  const rows=execFileSync("ps",["-axo","pid=,ppid=,rss="],{encoding:"utf8"}).trim().split("\n").map(l=>l.trim().split(/\s+/).map(Number));
  const own=new Set([process.pid]);
  for(let pass=0;pass<12;pass++)for(const [pid,ppid]of rows)if(own.has(ppid))own.add(pid);
  const bytes=rows.filter(([pid])=>own.has(pid)).reduce((n,[,,rss])=>n+rss,0)*1024;
  memory.push({phase,elapsedMs:Math.round(performance.now()-began),processTreeRssBytes:bytes});
  if(bytes>rssGuardBytes&&!guardTripped){guardTripped=true;client?.kill("SIGTERM");service?.kill("SIGTERM");}
}
function exited(child){return new Promise((ok,fail)=>{child.once("error",fail);child.once("exit",(code,signal)=>code===0?ok():fail(new Error(`probe child failed: ${code}/${signal}`)));});}
let timer;
let timeout;
try{
  service=spawn(process.execPath,[harness,output],{cwd:repo,env,stdio:["ignore","pipe","inherit"]});
  serviceExit=exited(service);
  serviceExit.catch(()=>undefined);
  const ready=await new Promise((ok,fail)=>{
    let text="";const deadline=setTimeout(()=>fail(new Error("service startup timeout")),30000);
    service.stdout.on("data",chunk=>{text+=chunk;for(const line of text.split("\n").slice(0,-1)){try{const value=JSON.parse(line);if(value.ready){clearTimeout(deadline);ok(value);}}catch{}}});
    service.once("exit",()=>{clearTimeout(deadline);fail(new Error("service exited before ready"));});
  });
  await writeFile(resolve(output,"service.json"),JSON.stringify(ready,null,2));
  sample();timer=setInterval(sample,200);
  timeout=setTimeout(()=>{client?.kill("SIGTERM");service.kill("SIGTERM");},150000);
  client=spawn(resolve(repo,".venv/bin/python"),["-m","scripts.run_p1a_render_capacity_client",output,ready.origin],{cwd:repo,env:{...env,PYTHONDONTWRITEBYTECODE:"1",PYTHONPATH:resolve(repo,"services/api/src")},stdio:["ignore","pipe","inherit"]});
  client.stdout.on("data",chunk=>{for(const line of String(chunk).trim().split("\n")){try{phase=JSON.parse(line).phase??phase;}catch{}process.stdout.write(line+"\n");}});
  await exited(client);sample();
  service.kill("SIGTERM");await serviceExit;
  const report=JSON.parse(await readFile(resolve(output,"client-report.json"),"utf8"));
  const resource={method:"200ms ps aggregate RSS of probe parent and descendants (shared pages may double count; sampled, not physical peak/P95)",rssGuardBytes,guardTripped,sampleCount:memory.length,sampledMaximumProcessTreeRssBytes:Math.max(...memory.map(m=>m.processTreeRssBytes)),byPhase:Object.fromEntries([...new Set(memory.map(m=>m.phase))].map(p=>[p,Math.max(...memory.filter(m=>m.phase===p).map(m=>m.processTreeRssBytes))]))};
  await writeFile(resolve(output,"memory-samples.json"),JSON.stringify(memory));
  await writeFile(resolve(output,"report.json"),JSON.stringify({...report,resource,sourceHead:execFileSync("git",["rev-parse","HEAD"],{cwd:repo,encoding:"utf8"}).trim(),sourceWorkingTreeDirty:true,nodeVersion:process.version,mode:"host-production-http-executor-python-adapter-no-DB-no-Docker-no-UI",providerRequests:0,providerTokens:0},null,2),{flag:"wx"});
  console.log(JSON.stringify(resource));
}finally{
  clearInterval(timer);clearTimeout(timeout);client?.kill("SIGTERM");service?.kill("SIGTERM");
  await writeFile(resolve(output,"memory-samples.json"),JSON.stringify(memory));
  let shutdownTimer;
  await Promise.race([serviceExit?.catch(()=>undefined),new Promise(ok=>{shutdownTimer=setTimeout(ok,5000);})]);
  clearTimeout(shutdownTimer);
  await unlink(harness).catch(()=>undefined);
}
