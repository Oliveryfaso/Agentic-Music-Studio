import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {useState} from 'react';
import {navigate} from '../../app/routes';
import {ApiError} from '../../shared/api';
import type {ClassicalScoreDescription} from '../../shared/openapi';
import {importClassicalScore,listClassicalScores} from './classicalApi';
import {ReviewedScorePicker} from './ReviewedScorePicker';
import {reviewKey} from './scoreChoice';
type ImportIntent={scoreId:string;reviewKey:string;key:string};
const STORAGE='motif:classical-import:v1';
function restoreIntent():ImportIntent|null{
 try{const raw=sessionStorage.getItem(STORAGE);if(!raw||raw.length>32000)return null;const value=JSON.parse(raw) as ImportIntent;
  return typeof value.scoreId==='string'&&value.scoreId.length<120&&typeof value.reviewKey==='string'&&typeof value.key==='string'&&value.key.startsWith('web-classical:')&&value.key.length<160?value:null;
 }catch{return null;}
}
export function ClassicalScoreEntry(){
 const client=useQueryClient(),[pending,setPending]=useState(restoreIntent),[open,setOpen]=useState(()=>restoreIntent()!==null),[storageAvailable,setStorageAvailable]=useState(true);
 const catalog=useQuery({queryKey:['classical-scores'],queryFn:listClassicalScores,enabled:open,retry:false});
 function clearIntent(){setPending(null);try{sessionStorage.removeItem(STORAGE);}catch{setStorageAvailable(false);}}
 const creation=useMutation({retry:false,mutationFn:(score:ClassicalScoreDescription)=>{
  if(pending&&(pending.scoreId!==score.score_id||pending.reviewKey!==reviewKey(score)))throw new Error('未确认的导入身份已锁定，请先核对来源。');
  const intent=pending??{scoreId:score.score_id,reviewKey:reviewKey(score),key:'web-classical:'+crypto.randomUUID()};
  setPending(intent);try{sessionStorage.setItem(STORAGE,JSON.stringify(intent));}catch{setStorageAvailable(false);}
  return importClassicalScore(intent.scoreId,intent.key);
 },onSuccess:value=>{clearIntent();void client.invalidateQueries({queryKey:['projects']});navigate({name:'studio',projectId:value.project_id,revisionId:value.revision_id});},onError:error=>{
  if(error instanceof ApiError&&['CLASSICAL_SOURCE_NOT_FOUND','CLASSICAL_SOURCE_HASH_MISMATCH','INSTRUMENT_PACK_UNAVAILABLE','RENDER_SERVICE_UNAVAILABLE'].includes(error.code))clearIntent();
 }});
 return <section className="studio-panel classical-score-entry" aria-label="经典谱入口">
  <div className="panel-heading"><div><p className="eyebrow">START WITH A CLASSIC</p><h2>在经典旋律上继续创作</h2><p>从固定审核的主旋律摘录开始，保留原谱，再增加一条钢琴伴奏。</p><p>这是审核曲库内的双钢琴 Beta，暂不支持任意 MusicXML / MIDI 文件导入。生成后，试听 A/B 后再决定是否保留。</p></div><button type="button" className="secondary-inline" aria-expanded={open} disabled={creation.isPending} onClick={()=>setOpen(!open)}>查看经典谱</button></div>
  {open&&<ReviewedScorePicker catalog={catalog.data??[]} loading={catalog.isPending} error={catalog.isError} busy={creation.isPending} locked={pending} onRetry={()=>void catalog.refetch()} onImport={score=>creation.mutate(score)}/>}
  {creation.error&&<p role="alert" className="field-error">{creation.error instanceof ApiError?creation.error.message:'尚未收到导入确认。请重试同一次导入，或先查看作品列表。'}</p>}
  {!storageAvailable&&<p role="alert">浏览器无法保存请求标识。请保持此页并重试；刷新可能丢失这次导入身份。</p>}
 </section>;
}
