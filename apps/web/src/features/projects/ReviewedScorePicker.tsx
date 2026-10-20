import {useId,useState} from 'react';
import type {ClassicalScoreDescription} from '../../shared/openapi';
import {reviewKey,canImportScore} from './scoreChoice';
import './reviewedScorePicker.css';
interface Props{
 catalog:readonly ClassicalScoreDescription[];loading:boolean;error:boolean;busy:boolean;
 locked:{scoreId:string;reviewKey:string}|null;onRetry:()=>void;onImport:(score:ClassicalScoreDescription)=>void;
}
export function ReviewedScorePicker({catalog,loading,error,busy,locked,onRetry,onImport}:Props){
 const uid=useId(),[selectedId,setSelectedId]=useState(''),[ack,setAck]=useState<string|null>(null);
 const chosen=locked?.scoreId??selectedId;
 const selected=catalog.find(score=>score.score_id===chosen)??(chosen===''?catalog[0]:undefined);
 const key=selected?reviewKey(selected):null,acknowledged=locked?.reviewKey??ack;
 return <div className="reviewed-score-picker">
  {loading&&<p role="status">正在载入审核谱源…</p>}
  {error&&<p role="alert">谱源暂不可用。<button type="button" disabled={busy} onClick={onRetry}>重试载入曲谱</button></p>}
  {!loading&&!error&&catalog.length===0&&<p role="status">暂时没有可导入的审核短谱。</p>}
  {catalog.length>0&&<fieldset disabled={busy||loading||error||!!locked}><legend>选择曲目</legend><div className="score-cards">
   {catalog.map(score=><label className="score-card" key={score.score_id}><input type="radio" name={uid+'-score'} checked={selected?.score_id===score.score_id} value={score.score_id} onChange={()=>{setSelectedId(score.score_id);setAck(null);}}/>
    <span><strong>{score.title}</strong><span>{score.composer}</span><small>{score.measure_count} 小节 · {score.beats}/4 · {score.tonic} · {score.bpm} BPM</small></span></label>)}
  </div></fieldset>}
  {selected&&<div className="score-detail"><h3>{selected.title}</h3><p>{selected.composer} · {selected.digital_editor} · {selected.license}</p>
   <p>{selected.measure_count} 小节 / {selected.note_count} 个音符；末尾另留一小节供尾音释放。使用已审核的小型钢琴音源。</p><p>{selected.conversion}</p>
   <p><a href={selected.page_url} target="_blank" rel="noreferrer">查看原始谱源</a> · <a href={'/api/v1/classical-scores/'+encodeURIComponent(selected.score_id)+'/musicxml'}>下载本次旋律谱</a></p>
   <label className="piano-confirm"><input type="checkbox" checked={acknowledged===key} onChange={e=>setAck(e.target.checked?key:null)} disabled={busy||loading||error||!!locked}/>我已了解来源与转换范围，保留原谱并创建改编副本</label>
   <button className="primary-inline" type="button" disabled={loading||error||!canImportScore(catalog,selected.score_id,acknowledged,busy)} onClick={()=>{if(canImportScore(catalog,selected.score_id,acknowledged,busy))onImport(selected);}}>{busy?'正在导入…':locked?'重试同一次导入':'导入这份旋律谱'}</button>
  </div>}
  {chosen!==''&&!selected&&!loading&&<p role="alert">刚才选择的谱已不在目录中，请重新载入目录。</p>}
  {locked&&<p role="status">这次导入尚未确认；曲目与请求保持锁定。重试只会查询或完成同一次导入，不会换曲新建。</p>}
  {locked&&selected&&locked.reviewKey!==key&&<p role="alert">这份谱的审核信息已改变，不能继续旧请求。请先检查作品列表和来源记录。</p>}
 </div>;
}
