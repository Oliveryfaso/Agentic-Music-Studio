/** Synthetic first-use states only. No actual API, Key, model, or generated music. */
import assert from 'node:assert/strict';
import {mkdir,writeFile} from 'node:fs/promises';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {resolve} from 'node:path';
import react from '@vitejs/plugin-react';
import {createServer} from 'vite';
import {chromium} from 'playwright';
import {build} from 'esbuild';
import {projectId,revisionId,runId,project,studio,run,graph,exportData} from './fixtures/product-ui.mjs';
const root=fileURLToPath(new URL('../',import.meta.url)),out=resolve(root,'output/playwright/first-run-v2');
await mkdir(out,{recursive:true});
await build({entryPoints:[resolve(root,'apps/web/src/features/studio/pianoEqTestFixture.ts')],bundle:true,platform:'node',format:'esm',outfile:resolve(out,'piano-fixture.mjs')});
const {eqBase}=await import(pathToFileURL(resolve(out,'piano-fixture.mjs')).href);
const piano=eqBase();piano.project_id=projectId;piano.sections[0].end_tick=15360;piano.provenance=[{kind:'asset',ref:'score:c02-la-candeur-a8.v1'}];
piano.tracks.forEach(track=>track.clips.forEach((clip,c)=>{clip.clip_id=`${track.track_id}-clip-${c}`;clip.notes?.forEach((note,n)=>{note.note_id=`${track.track_id}-note-${c}-${n}`;});}));
const workspace={...project,recoverable_piano_preview:null,piano_preview_recovery:{status:'ready',pending_count:0,selection_rule:'newest_created',reason_code:null}};
const server=await createServer({configFile:false,root:resolve(root,'apps/web'),plugins:[react()],cacheDir:resolve(out,'.vite'),server:{host:'127.0.0.1',port:0,strictPort:true,hmr:false}});
let browser,origin,page,configured=false,readFailure=false,created=false,failCreate=false,runMode='approval',exportsReady=false,modelRequired=false;
const cases=[],errors=[],unexpected=[],writes=[],generationRequests=[];
const silent=Buffer.alloc(44+8000*2*2);silent.write('RIFF');silent.writeUInt32LE(silent.length-8,4);silent.write('WAVEfmt ',8);silent.writeUInt32LE(16,16);silent.writeUInt16LE(1,20);silent.writeUInt16LE(1,22);silent.writeUInt32LE(8000,24);silent.writeUInt32LE(16000,28);silent.writeUInt16LE(2,32);silent.writeUInt16LE(16,34);silent.write('data',36);silent.writeUInt32LE(silent.length-44,40);
async function check(name,fn){try{await fn();cases.push({name,status:'PASS'});console.log('PASS '+name);}catch(error){await writeFile(resolve(out,'failed-state.json'),JSON.stringify({name,url:page.url(),text:await page.locator('main').innerText(),errors},null,2));throw error;}}
const submit=()=>page.getByRole('button',{name:'提交 Brief 并规划',exact:true});
const freeSubmit=()=>page.getByRole('button',{name:'使用免费模板规划',exact:true});
async function capture(name){await page.evaluate(()=>{const badge=document.querySelector('.runtime-badge');if(badge)badge.textContent='隔离mock · 合成数据 / 静音';window.scrollTo(0,0);});await page.screenshot({path:resolve(out,name+'.png'),fullPage:true,animations:'disabled'});}
try{
 await server.listen();origin='http://127.0.0.1:'+server.httpServer.address().port;
 browser=await chromium.launch({headless:true,args:['--mute-audio']});
 const context=await browser.newContext({viewport:{width:1440,height:1000},locale:'zh-CN',serviceWorkers:'block',acceptDownloads:false});
 await context.addInitScript(()=>{const original=fetch.bind(window);window.fetch=(input,init)=>String(input).endsWith('/events')?Promise.resolve(new Response(new ReadableStream({start(c){c.enqueue(new TextEncoder().encode(': mock\n\n'));init?.signal?.addEventListener('abort',()=>c.close(),{once:true});}}),{headers:{'Content-Type':'text/event-stream'}})):original(input,init);});
 await context.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname;
  if(url.origin!==origin){unexpected.push('outside isolated origin');return route.abort();}
  const json=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify({data})});
  if(req.method()==='POST'){
   writes.push(path);
   if(path==='/api/v1/projects'){created=true;return json({project_id:projectId,active_branch_id:project.active_branch_id,root_revision_id:revisionId,content_hash:'fixture',replayed:false},201);}
   if(path===`/api/v1/projects/${projectId}/ai-runs`){generationRequests.push({key:req.headers()['idempotency-key'],body:req.postData()});return failCreate?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'模拟：规划暂不可用',error_code:'PLANNING_UNAVAILABLE'})}):json(run('approval'),202);}
   unexpected.push('unexpected write '+path);return route.abort();
  }
  if(req.method()!=='GET'){unexpected.push('unexpected method');return route.abort();}
  if(!path.startsWith('/api/'))return route.continue();
  if(path==='/api/v1/model-settings')return readFailure?route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'mock private upstream detail'})}):json({state:configured?'configured':'not_configured',error_code:null});
  if(path==='/api/v1/projects')return json(created?[{...project,latest_run:null,has_playable_revision:false}]:[]);
  if(path===`/api/v1/projects/${projectId}`)return json(workspace);
  if(path==='/api/v1/sound-catalog')return json([]);
  if(path==='/api/v1/piano-capability')return json({available:modelRequired,error_code:modelRequired?null:'INSTRUMENT_PACK_UNAVAILABLE',pedal_supported:false,release_triggers_supported:false,render_profile:modelRequired?piano.render_profile:null,semantic_generation:{configuration:configured?'configured':'not_configured',reason_code:configured?null:'MODEL_NOT_CONFIGURED'}});
  if(path.endsWith('/classical-source'))return json({revision_id:revisionId,source:{score_id:'c02-la-candeur-a8.v1',title:'合成源谱',license:'CC0-1.0',conversion:'Synthetic UI fixture only',page_url:'https://example.invalid/mock-score',default_chords:Array(8).fill('C')},import_report:{measure_count:8,beats:4,tonic:'C',note_count:4}});
  if(path.endsWith('/studio'))return json({...studio,...(modelRequired?{arrangement_ir:piano}:{}),delivery_assets:[{...studio.delivery_assets[0],media_type:'audio/wav',duration_milliseconds:2000}]});
  if(path.endsWith('/exports'))return json(exportsReady?exportData:{...exportData,status:'partial',bundle:null,plan_hash:null,export_thread_id:null,files:[],steps:exportData.steps.map(s=>({...s,job_id:null,status:'pending',artifact_id:null}))});
  if(path===`/api/v1/runs/${runId}`)return json(run(runMode));
  if(path.endsWith('/graph'))return json(graph);
  if(path.endsWith('/content'))return route.fulfill({status:200,contentType:'audio/wav',body:silent});
  unexpected.push('unmocked '+path);return route.fulfill({status:404,body:'Unmocked'});
 });
 page=await context.newPage();page.setDefaultTimeout(10000);page.on('pageerror',e=>errors.push(e.message));
 await check('welcome-and-settings-official-Key-destination',async()=>{
  await page.goto(origin+'/about');await page.getByRole('navigation',{name:'主导航'}).getByRole('link',{name:'设置',exact:true}).click();
  await page.locator('.model-settings-status').getByText('未配置',{exact:true}).waitFor();
  const key=page.getByRole('link',{name:'获取 DeepSeek API Key（新窗口）'});assert.equal(await key.getAttribute('href'),'https://platform.deepseek.com/api_keys');
  await page.getByText(/若已保存 Key/).waitFor();assert(await page.getByRole('button',{name:'测试连接',exact:true}).isDisabled());assert.equal(writes.length,0);
 });
 await check('empty-home-first-project-route-without-a-Key',async()=>{
  await page.goto(origin);const empty=page.locator('.empty-state');await empty.getByRole('link',{name:'配置 API Key'}).waitFor();await capture('01-empty-home');
  await page.getByLabel('作品名称').fill('合成首作');await page.getByRole('button',{name:'创建作品',exact:true}).click();
  await page.getByText('未启用模型 · 可使用免费模板',{exact:true}).waitFor();assert(await freeSubmit().isEnabled());assert.equal(writes.length,1);await capture('02-brief-free-fallback');
 });
 await check('no-Key-explicit-template-plan-reaches-approval',async()=>{
  await page.getByLabel('作品标题',{exact:true}).fill('合成首作');await page.getByRole('textbox',{name:'用途',exact:true}).fill('纯器乐短片配乐');await page.getByLabel('情绪',{exact:true}).fill('明亮，轻盈');
  assert.equal(writes.length,1);await freeSubmit().click();await page.waitForURL('**/runs/'+runId);await page.getByText(/当前使用规则生成的备用计划/).waitFor();assert.equal(writes.length,2);assert.equal(generationRequests.length,1);await capture('03-fallback-plan-approval');
 });
 await check('configuration-read-recovery-preserves-first-idea',async()=>{
  readFailure=true;await page.goto(origin+`/projects/${projectId}/new-composition`);await page.getByText('无法读取模型配置',{exact:true}).waitFor();
  await page.getByLabel('作品标题',{exact:true}).fill('合成首作');await page.getByRole('textbox',{name:'用途',exact:true}).fill('纯器乐短片配乐');await page.getByLabel('情绪',{exact:true}).fill('明亮，轻盈');
  assert(await submit().isDisabled());assert.equal(await freeSubmit().count(),0);
  assert.equal(await page.getByText('mock private upstream detail',{exact:true}).count(),0);
  readFailure=false;configured=true;await page.getByRole('button',{name:'刷新模型配置'}).click();await submit().waitFor();await page.waitForFunction(()=>!document.querySelector('button[type="submit"]').disabled);
  const purpose=page.getByRole('textbox',{name:'用途',exact:true});assert.equal(await purpose.inputValue(),'纯器乐短片配乐');assert.equal(writes.length,2);
 });
 await check('untested-enabled-explicit-submit-failure-and-retry',async()=>{
  failCreate=true;await submit().click();await page.getByText('Brief 提交失败',{exact:true}).waitFor();assert.equal(await page.getByRole('textbox',{name:'用途',exact:true}).inputValue(),'纯器乐短片配乐');assert.equal(writes.length,3);await capture('04-brief-request-failure');
  failCreate=false;await submit().click();await page.waitForURL('**/runs/'+runId);await page.locator('.plan-review').waitFor();assert.equal(writes.length,4);assert(generationRequests[1].key);assert.deepEqual(generationRequests[2],generationRequests[1]);
 });
 await check('completed-run-state-to-muted-playback',async()=>{
  // Independent completed fixture: not evidence that planning/approval/rendering actually ran.
  runMode='done';await page.reload();await page.getByRole('button',{name:'打开 Studio',exact:true}).click();
  const audio=page.locator('.studio-transport audio');await audio.waitFor({state:'attached'});await audio.evaluate(a=>{a.muted=true;a.defaultMuted=true;});
  await page.locator('.studio-transport').getByRole('button',{name:'播放',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.studio-transport audio')?.currentTime>0.2);
  await page.locator('.studio-transport').getByRole('button',{name:'暂停',exact:true}).click();assert(await audio.evaluate(a=>a.paused&&a.muted&&!a.error));
 });
 await check('export-not-started-and-existing-ready-states-do-not-auto-render',async()=>{
  await page.getByRole('link',{name:'查看导出',exact:true}).click();await page.getByText('编排已保存，导出文件尚未生成',{exact:true}).waitFor();assert.equal(writes.length,4);await capture('05-export-not-started');
  exportsReady=true;await page.reload();await page.getByRole('heading',{name:'交付文件',exact:true}).waitFor();assert.equal(await page.locator('a[download]').count(),exportData.files.length);assert.equal(writes.length,4);
  await page.getByRole('link',{name:'返回 Studio',exact:true}).click();await page.locator('.studio-transport audio').waitFor({state:'attached'});
 });
 await check('descriptive-piano-edit-requires-model-and-links-to-settings',async()=>{
  configured=false;modelRequired=true;await page.goto(origin+`/projects/${projectId}/studio/${revisionId}`);
  const task=page.locator('.studio-inspector-disclosure');if(!await task.evaluate(e=>e.open))await task.locator(':scope > summary').click();
  const panel=page.locator('.piano-expression');await panel.getByText(/自然语言服务尚未配置，暂不能按描述修改伴奏/).waitFor();
  assert.equal(await panel.getByRole('link',{name:'配置 API Key'}).getAttribute('href'),'/settings');assert(await panel.getByRole('button',{name:'按描述生成 A/B 试听'}).isDisabled());assert.equal(writes.length,4);await capture('06-piano-model-required');
 });
 await check('390px-configuration-discoverability',async()=>{
  configured=false;await page.setViewportSize({width:390,height:844});await page.goto(origin+'/settings');await page.locator('.model-settings-status').getByText('未配置',{exact:true}).waitFor();
  assert(await page.getByRole('link',{name:'获取 DeepSeek API Key（新窗口）'}).isVisible());assert(await page.getByRole('navigation',{name:'主导航'}).getByRole('link',{name:'设置',exact:true}).isVisible());
  assert(await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth)<=1);await capture('07-settings-390');
 });
 assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[]);assert(!writes.some(p=>p.includes('model-settings/check')||p.endsWith('/exports')));
 console.log('PASS '+cases.length+' synthetic first-run scenarios; no real generation');
}finally{
 await browser?.close();await server.close();await writeFile(resolve(out,'evidence.json'),JSON.stringify({origin,fixture:'public product-ui + pianoEqTestFixture; first project, fallback plan, completed-run and export states are mocked; silent PCM, not music',cases,writes,retry_same_identity_and_payload:generationRequests.length===3&&generationRequests[1].key===generationRequests[2].key&&generationRequests[1].body===generationRequests[2].body,errors,unexpected,cleanup:'own browser and Vite stopped'},null,2)+'\n');console.log('Own browser and Vite stopped.');
}
