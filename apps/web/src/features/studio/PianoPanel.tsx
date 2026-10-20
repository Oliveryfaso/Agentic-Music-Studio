import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {useEffect,useRef,useState} from 'react';
import {ApiError,audioContentUrl} from '../../shared/api';
import type {ArrangementIR,PianoPreviewData,PianoPreviewOptions,ClassicalSourceData,AccompanimentIntent} from '../../shared/openapi';
import type {EditorSelection} from './editorState';
import {buildPianoPerformance} from './pianoPerformance';
import {cancelPianoPreview,decidePianoPreview,readPianoCapability,readPianoPreview,startPianoPreview} from './pianoApi';

type SemanticRequest=NonNullable<PianoPreviewOptions['semantic']>;
const APPEND_DESCRIPTION='加一个低音区钢琴伴奏，前8小节稀疏，后8小节稍活跃，不改旋律';
const MODIFY_DESCRIPTION='这几小节更稀疏、更轻，其余保持';
const PENDING_PHASES=new Set(['queued','planning','waiting_piano_worker']);
type PianoIntent={fingerprint:string;key:string;semanticFingerprint:string;request?:SemanticRequest};
function restorePendingIntent(storageKey:string):{intent:PianoIntent|null;available:boolean}{
  try{
    const raw=window.sessionStorage.getItem(storageKey);
    if(!raw||raw.length>64000)return {intent:null,available:true};
    const value=JSON.parse(raw) as PianoIntent;
    const request=value?.request;
    if(typeof value?.fingerprint!=='string'||typeof value?.key!=='string'||!value.key.startsWith('web-piano:')||typeof value?.semanticFingerprint!=='string'||!request||typeof request.intent!=='string'||request.intent.length>800||!['append','modify'].includes(request.mode)||!Number.isInteger(request.start_bar)||!Number.isInteger(request.end_bar))return {intent:null,available:true};
    return {intent:value,available:true};
  }catch{return {intent:null,available:false};}
}


export function PianoPanel({projectId,branchId,revisionId,arrangement,selection,dirty,rootReady,onSaved,classicalSource}:{
  projectId:string;branchId:string;revisionId:string;arrangement:ArrangementIR;selection:EditorSelection|null;
  dirty:boolean;rootReady:boolean;onSaved:(revision:string)=>void;classicalSource?:ClassicalSourceData;
}){
  const client=useQueryClient();
  const capability=useQuery({queryKey:['piano-capability'],queryFn:readPianoCapability,retry:false});
  const [thread,setThread]=useState<string|null>(()=>new URLSearchParams(window.location.search).get('piano_preview'));
  const single=arrangement.tracks.length===1&&arrangement.tracks[0]?.track_type==='instrument';
  const modify=Boolean(classicalSource&&arrangement.tracks.length===2&&arrangement.tracks.every(track=>track.track_type==='instrument'));
  const storageKey='motif:piano-semantic:'+projectId+':'+branchId+':'+revisionId;
  const [restoredIntent]=useState(()=>restorePendingIntent(storageKey));
  const [identityStorageAvailable,setIdentityStorageAvailable]=useState(restoredIntent.available);
  const [entry,setEntry]=useState<'rules'|'semantic'>(restoredIntent.intent?'semantic':'rules');
  const legacySemantic=classicalSource?.source.score_id==='mutopia-528-melody.v1';
  const sourceBars=classicalSource?.import_report.measure_count??16;
  const sourceBeats=classicalSource?.import_report.beats??4;
  const sourceSemantic=Boolean(classicalSource&&['mutopia-528-melody.v1','c01-minuet-g-a16.v1','c02-la-candeur-a8.v1','j01-bethena-a-first8.v1'].includes(classicalSource.source.score_id));
  const appendDescription=sourceBars===16?APPEND_DESCRIPTION:`加一个低音区钢琴伴奏，前${sourceBars/2}小节稀疏，后${sourceBars/2}小节稍活跃，不改旋律`;
  const defaultStart=sourceBars===8?5:9,defaultEnd=sourceBars===8?8:12;
  const semantic=Boolean(sourceSemantic&&(modify||entry==='semantic'));
  const [description,setDescription]=useState(restoredIntent.intent?.request?.intent??(modify?MODIFY_DESCRIPTION:appendDescription));
  const [startBar,setStartBar]=useState(restoredIntent.intent?.request?.start_bar??defaultStart),[endBar,setEndBar]=useState(restoredIntent.intent?.request?.end_bar??defaultEnd);
  const previousMode=useRef(modify);
  useEffect(()=>{if(previousMode.current!==modify){setDescription(modify?MODIFY_DESCRIPTION:appendDescription);setStartBar(9);setEndBar(12);previousMode.current=modify;}},[modify]);
  const [velocity,setVelocity]=useState(classicalSource?54:76),[onset,setOnset]=useState(8),[gate,setGate]=useState(180);
  const [confirmed,setConfirmed]=useState(false);
  const [pattern,setPattern]=useState<AccompanimentIntent['pattern']>('roots');
  const [octave,setOctave]=useState<2|3>(2);
  const [chordText,setChordText]=useState(()=>classicalSource?.source.default_chords.join(' ')??'');
  const chordNames=chordText.trim().split(/[\s,，、]+/).filter(Boolean);
  const chords=chordNames.filter((value):value is AccompanimentIntent['chords'][number]=>['G','C','D','Em','Am','Bm','F','Dm'].includes(value));
  const validRange=Number.isInteger(startBar)&&Number.isInteger(endBar)&&startBar>=1&&endBar<=sourceBars&&endBar>=startBar&&endBar-startBar<4;
  const validInputs=semantic?description.trim().length>0&&description.length<=800&&(!modify||validRange):classicalSource?chords.length===classicalSource.import_report.measure_count&&chords.length===chordNames.length&&Number.isInteger(velocity)&&velocity>=32&&velocity<=80:Number.isInteger(velocity)&&velocity>=1&&velocity<=127&&Number.isInteger(onset)&&Math.abs(onset)<=60&&Number.isInteger(gate)&&gate>=1&&gate<=9600;
  const intent=useRef<PianoIntent|null>(restoredIntent.intent);
  const semanticFingerprint=JSON.stringify({source:classicalSource?.source.score_id,beats:sourceBeats,description:description.trim(),modify,startBar:modify?startBar:1,endBar:modify?endBar:sourceBars});
  const key=['piano-preview',projectId,thread];
  const audition=useQuery({queryKey:key,queryFn:()=>readPianoPreview(projectId,thread!),enabled:thread!==null,
    refetchInterval:(query)=>PENDING_PHASES.has(query.state.data?.phase??'')?1500:false,retry:false});
  const state=audition.data;
  const active=PENDING_PHASES.has(state?.phase??'')||state?.phase==='waiting_piano_approval';
  const semanticContext=semantic||Boolean(state?.model||state?.semantic_summary||state?.phase==='queued'||state?.phase==='planning');
  function clearPendingIntent(){try{window.sessionStorage.removeItem(storageKey);}catch{setIdentityStorageAvailable(false);}}
  const change=(value:PianoPreviewData)=>{
    client.setQueryData(['piano-preview',projectId,value.thread_id],value);
    if(value.thread_id!==thread){setThread(value.thread_id);const url=new URL(window.location.href);url.searchParams.set('piano_preview',value.thread_id);window.history.replaceState({},'',url);}
    if(value.revision_id)onSaved(value.revision_id);
  };
  const start=useMutation({retry:false,mutationFn:async()=>{
    const profile=capability.data?.render_profile;
    if(!profile)throw new Error('请先连接可用的钢琴音源。');
    const scope={intent:description.trim(),mode:modify?'modify' as const:'append' as const,
      ...(modify?{target_track_id:arrangement.tracks[1]!.track_id}:{}),start_bar:modify?startBar:1,end_bar:modify?endBar:sourceBars};
    const semanticRequest:SemanticRequest=legacySemantic||!classicalSource
      ?{schema_version:'piano-semantic-request.v1',...scope}
      :{schema_version:'piano-semantic-request.v2',source_score_id:classicalSource.source.score_id as Extract<SemanticRequest,{schema_version:'piano-semantic-request.v2'}>['source_score_id'],
        beats_per_bar:sourceBeats as 3|4,...scope};
    const body:PianoPreviewOptions={branch_id:branchId,base_revision_id:revisionId,seed:0,
      render_profile:profile,performance_plan:classicalSource?{schema_version:'performance-plan.v1',notes:[],pedal_events:[]}:buildPianoPerformance(arrangement,selection,{velocity,onset,gate}),
      ...(semantic?{semantic:semanticRequest}:classicalSource?{accompaniment:{pattern,chords,octave,velocity}}:{})};
    const fingerprint=JSON.stringify(body);
    if(intent.current?.fingerprint!==fingerprint)intent.current={fingerprint,key:'web-piano:'+crypto.randomUUID(),semanticFingerprint,...(semantic?{request:semanticRequest}:{})};
    if(semantic){try{window.sessionStorage.setItem(storageKey,JSON.stringify(intent.current));}catch{setIdentityStorageAvailable(false);}}
    return startPianoPreview(projectId,body,intent.current.key);
  },onSuccess:(value)=>{change(value);if(semantic)clearPendingIntent();intent.current=null;setConfirmed(false);},onError:(error)=>{
    // Only these preparation failures are known to precede Run/Preview creation. Network failures keep the key.
    if(error instanceof ApiError&&error.status===503&&['INSTRUMENT_PACK_UNAVAILABLE','RENDER_SERVICE_UNAVAILABLE'].includes(error.code)){intent.current=null;if(semantic)clearPendingIntent();}
  }});
  const decision=useMutation({mutationFn:(action:'approve'|'reject')=>decidePianoPreview(projectId,thread!,{
    action,expected_candidate_content_hash:state!.candidate_content_hash!,
    approval_assertion:action==='approve'?'I have auditioned and approve this exact piano candidate.':'I reject this exact piano candidate.'}),
    onSuccess:change});
  const cancel=useMutation({mutationFn:()=>cancelPianoPreview(projectId,thread!),onSuccess:change});
  const busy=start.isPending||decision.isPending||cancel.isPending;
  const matches=state?.base_revision_id===revisionId;
  const ready=rootReady&&!dirty&&matches&&state?.phase==='waiting_piano_approval';
  const error=start.error||decision.error||cancel.error||audition.error;
  const canPrepare=single||(modify&&sourceSemantic);
  const keepLabel=classicalSource?(modify?'保留这次修改':'保留这条伴奏'):'保存这版钢琴表达';
  return <section className="studio-panel piano-expression" aria-labelledby="piano-expression-title">
    <div className="panel-heading"><div><p className="eyebrow">PIANO / EXPRESSION</p><h3 id="piano-expression-title">{classicalSource?(modify?'修改新增的伴奏':'给原谱加一条伴奏'):'钢琴表达'}</h3></div>
      <span className="status-pill">{classicalSource?(arrangement.tracks.length>1?'原谱 + 伴奏':'原谱旋律'):arrangement.schema_version!=='arrangement-ir.v1'?'已保存真实钢琴':'原有音色'}</span></div>
    <p className="saved-audio-note">{classicalSource?(semanticContext?'描述想要的密度、音区或力度。Flash 每次生成只发起一次请求，保留前原版本不变。':'选择每小节和弦与伴奏织体，用同一钢琴的低音声部衬托旋律。规则伴奏不消耗模型额度。'):<>调整{selection?'所选范围':'整轨音符'}的演奏表达。先比较试听，确认后保存新版本。</>}</p>
    <p className="piano-source">FreePats Upright KW · CC0 · 踏板暂不支持</p>
    {semanticContext&&!identityStorageAvailable&&<p className="field-error">浏览器无法保存请求标识。网络失败后请保持此页并重试；刷新可能丢失请求身份，请勿再次新建付费请求。</p>}
    {classicalSource&&!sourceSemantic&&<p>当前来源不支持自然语言伴奏；请使用已审核曲目。</p>}
    {!canPrepare&&<p>{classicalSource?'当前入口支持原谱加一条伴奏，请保留现有两轨范围。':'当前入口支持一条乐器轨。多轨作品仍可使用原有编辑和导出。'}</p>}
    {canPrepare&&<>
      {!capability.data?.available&&<p className="field-error">{capability.isPending?'正在检查钢琴音源…':'钢琴音源暂不可用，请检查本地渲染服务。原有音色仍可使用。'} <button type="button" onClick={()=>void capability.refetch()} disabled={capability.isFetching}>重新检查</button></p>}
      {classicalSource&&single&&<fieldset className="piano-actions" disabled={busy||active}><legend>伴奏方式</legend>
        <label><input type="radio" name="piano-entry" checked={entry==='rules'} onChange={()=>setEntry('rules')}/>规则伴奏</label>
        <label><input type="radio" name="piano-entry" checked={entry==='semantic'} disabled={!sourceSemantic} onChange={()=>setEntry('semantic')}/>自然语言伴奏</label>
      </fieldset>}
      {semantic?<fieldset className="piano-expression-fields" disabled={busy||active}>
        <label style={{gridColumn:'1 / -1'}}>伴奏描述<textarea aria-label="伴奏描述" rows={4} maxLength={800} value={description} onChange={e=>setDescription(e.target.value)} style={{width:'100%',boxSizing:'border-box'}}/></label>
        {modify?<>
          <label>开始小节<input aria-label="开始小节" type="number" min={1} max={sourceBars} step={1} value={startBar} onChange={e=>setStartBar(Number(e.target.value))}/></label>
          <label>结束小节<input aria-label="结束小节" type="number" min={1} max={sourceBars} step={1} value={endBar} onChange={e=>setEndBar(Number(e.target.value))}/></label>
          <p style={{gridColumn:'1 / -1'}}>仅修改新增的第二轨，选择第 1–{sourceBars} 小节内连续 1–4 小节。原和声、原谱与范围外内容保持不变；本轮不支持局部换和弦。{!validRange&&' 请检查小节范围。'}</p>
        </>:<p style={{gridColumn:'1 / -1'}}>为第 1–{sourceBars} 小节新增一条低音区钢琴伴奏，保留锁定的原谱旋律。</p>}
      </fieldset>:classicalSource?<fieldset className="piano-expression-fields" disabled={busy||active}>
        <label>伴奏织体<select aria-label="伴奏织体" value={pattern} onChange={e=>setPattern(e.target.value as AccompanimentIntent['pattern'])}><option value="roots">稀疏根音点奏</option><option value="broken">分解和弦</option></select></label>
        <label>低音八度<select aria-label="低音八度" value={octave} onChange={e=>setOctave(Number(e.target.value) as 2|3)}><option value={2}>第 2 八度</option><option value={3}>第 3 八度</option></select></label>
        <label>伴奏力度<input aria-label="伴奏力度" type="number" min={32} max={80} value={velocity} onChange={e=>setVelocity(Number(e.target.value))}/></label>
        <label className="piano-chord-field" style={{gridColumn:'1 / -1'}}>每小节和弦<input aria-label="每小节和弦" value={chordText} onChange={e=>setChordText(e.target.value)} maxLength={180}/></label>
        <p style={{gridColumn:'1 / -1'}}>依次填写 {classicalSource.import_report.measure_count} 个和弦，用空格分隔。当前支持 G、C、D、Em、Am、Bm、F、Dm；不支持七和弦或转位。{!validInputs&&' 请检查数量、和弦名称与力度。'}</p>
      </fieldset>:<fieldset className="piano-expression-fields" disabled={busy||active}>
        <label>力度 <input aria-label="钢琴力度" type="number" min={1} max={127} step={1} value={velocity} onChange={e=>setVelocity(Number(e.target.value))}/></label>
        <label>起音偏移（tick）<input aria-label="钢琴起音偏移" type="number" min={-60} max={60} step={1} value={onset} onChange={e=>setOnset(Number(e.target.value))}/></label>
        <label>按键时长（tick）<input aria-label="钢琴按键时长" type="number" min={1} max={9600} step={1} value={gate} onChange={e=>setGate(Number(e.target.value))}/></label>
      </fieldset>}
      {dirty&&<p className="field-error">请先保存或撤销草稿修改，再试听钢琴表达。</p>}
      <button className="secondary-inline" type="button" disabled={!rootReady||dirty||!capability.data?.available||!capability.data.render_profile||busy||active||!validInputs}
        onClick={()=>start.mutate()}>{start.isPending?'正在创建试听…':semantic?(start.isError&&intent.current?.semanticFingerprint===semanticFingerprint?'重试同一次生成请求':'按描述生成 A/B 试听'):start.isError?'重试 A/B 试听':'生成 A/B 试听'}</button>
      {semantic&&start.isError&&<p>网络失败后重试会复用同一次请求；修改描述后生成会发起新的模型请求。</p>}
    </>}
    {thread&&<div className="piano-audition" aria-live="polite">
      {audition.isPending&&<p>正在恢复试听进度…</p>}
      {(state?.phase==='queued'||state?.phase==='planning')&&<><p>Flash 正在规划伴奏，原版本保持不变。可以刷新后继续。</p><p>本次规划返回后可取消试听或放弃候选。</p></>}
      {state?.phase==='waiting_piano_worker'&&<><p>正在生成两版试听，可以刷新后继续。</p><button type="button" disabled={busy} onClick={()=>cancel.mutate()}>取消试听</button></>}
      {state?.semantic_summary&&<p>{state.semantic_summary}</p>}
      {(state?.model||state?.semantic_summary)&&<div className="saved-audio-note"><p>Flash计划 + 确定性编译</p>{state.model&&<p>模型：{state.model}</p>}
        {state.model_requests!=null&&<p>模型请求：{state.model_requests} 次</p>}
        {state.usage_status==='known'&&state.total_tokens!=null?<p>总用量：{state.total_tokens} tokens</p>:<p>用量暂不完整，费用未确认。</p>}
      </div>}
      {state?.baseline_artifact_id&&state.piano_artifact_id&&<PianoComparison key={`${thread}:${state.baseline_artifact_id}:${state.piano_artifact_id}`} baseline={state.baseline_artifact_id} piano={state.piano_artifact_id} label={classicalSource?(modify?'局部修改':'加轨版本'):'钢琴表达'}/>}
      {state?.phase==='waiting_piano_approval'&&<>
        {!matches&&<p className="field-error">这段试听属于另一个已保存版本。请打开对应版本后确认。</p>}
        <label className="piano-confirm"><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)} disabled={!ready||busy}/>我已试听，确认{keepLabel}</label>
        <div className="piano-actions"><button type="button" className="primary-inline" disabled={!ready||!confirmed||busy} onClick={()=>decision.mutate('approve')}>{keepLabel}</button>
          <button type="button" disabled={busy} onClick={()=>decision.mutate('reject')}>放弃这版</button></div>
      </>}
      {state?.phase==='completed'&&state.revision_id&&<button type="button" onClick={()=>onSaved(state.revision_id!)}>打开已保存版本</button>}
      {state?.phase==='rejected'&&<p>已放弃试听，原版本保留。</p>}
      {state?.phase==='cancelled'&&<p>试听已取消，原版本保留。</p>}
      {state?.phase==='failed'&&<p className="field-error">试听失败：{state.error_code}。原版本保留。{semantic?'修改描述后，可再次主动生成；会发起新的模型请求。':'可重新试听。'}</p>}
    </div>}
    {error&&<p className="field-error" role="alert">{error instanceof ApiError?`${error.message}（${error.code}）`:error.message}</p>}
  </section>;
}

function PianoComparison({baseline,piano,label}:{baseline:string;piano:string;label:string}){
  const audio=useRef<HTMLAudioElement>(null);
  const position=useRef({time:0,playing:false});
  const [selected,setSelected]=useState<'baseline'|'piano'>('baseline');
  const [failed,setFailed]=useState(false);
  const [switching,setSwitching]=useState(false);
  const sourceGeneration=useRef(0);
  useEffect(()=>()=>{++sourceGeneration.current;},[]);
  function choose(value:'baseline'|'piano'){
    if(value===selected||!audio.current||switching)return;
    if(audio.current.readyState>=1)position.current={time:audio.current.currentTime,playing:!audio.current.paused};++sourceGeneration.current;audio.current.pause();setFailed(false);setSwitching(true);setSelected(value);
  }
  return <div className="piano-comparison">
    <div className="piano-ab-switch" role="group" aria-label="同位置 A/B 试听" aria-busy={switching}>
      <button type="button" aria-pressed={selected==='baseline'} disabled={switching} onClick={()=>choose('baseline')}>A · 原版本</button>
      <button type="button" aria-pressed={selected==='piano'} disabled={switching} onClick={()=>choose('piano')}>B · {label}</button>
    </div>
    <audio ref={audio} controls preload="metadata" aria-label="钢琴 A/B 试听" src={audioContentUrl(selected==='baseline'?baseline:piano)}
      onPlay={event=>{document.querySelectorAll('audio').forEach(other=>{if(other!==event.currentTarget)other.pause();});}}
      onLoadedMetadata={()=>{const node=audio.current;if(!node)return;setSwitching(false);node.currentTime=Math.min(position.current.time,Math.max(0,node.duration-.01));if(position.current.playing){const token=sourceGeneration.current,source=node.src;void node.play().catch(error=>{if(token===sourceGeneration.current&&audio.current===node&&node.src===source&&error?.name!=="AbortError")setFailed(true);});}}}
      onError={()=>{setSwitching(false);setFailed(true);}}/>
    <p className="saved-audio-note">切换 A/B 保留播放位置。试听为 160 kbps MP3，正式导出提供 WAV。</p>
    {failed&&<p className="field-error">试听音频暂不可用，请重新载入后再确认。</p>}
  </div>;
}
