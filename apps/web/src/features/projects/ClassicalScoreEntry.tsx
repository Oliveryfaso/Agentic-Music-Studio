import {useMutation,useQuery,useQueryClient} from '@tanstack/react-query';
import {useRef,useState} from 'react';
import {navigate} from '../../app/routes';
import {ApiError} from '../../shared/api';
import {importClassicalScore,listClassicalScores} from './classicalApi';
export function ClassicalScoreEntry(){
  const client=useQueryClient(),[open,setOpen]=useState(false),[acknowledged,setAcknowledged]=useState(false);
  const intent=useRef<string|null>(null);
  const catalog=useQuery({queryKey:['classical-scores'],queryFn:listClassicalScores,enabled:open,retry:false});
  const selected=catalog.data?.[0];
  const creation=useMutation({mutationFn:()=>{if(!selected)throw new Error('请先载入曲谱。');intent.current??='web-classical:'+crypto.randomUUID();return importClassicalScore(selected.score_id,intent.current);},onSuccess:(value)=>{intent.current=null;void client.invalidateQueries({queryKey:['projects']});navigate({name:'studio',projectId:value.project_id,revisionId:value.revision_id});}});
  return <section className="studio-panel classical-score-entry" aria-label="经典谱入口">
    <div className="panel-heading"><div><p className="eyebrow">START WITH A CLASSIC</p><h2>在经典旋律上继续创作</h2><p>先保留原谱，再按你的想法增加一条伴奏，试听后决定。</p></div><button type="button" className="secondary-inline" aria-expanded={open} onClick={()=>setOpen(!open)}>查看经典谱</button></div>
    {open&&<div>
      {catalog.isPending&&<p role="status">正在载入审核谱源…</p>}
      {catalog.error&&<p role="alert">谱源暂不可用。<button type="button" onClick={()=>void catalog.refetch()}>重试载入曲谱</button></p>}
      {selected&&<><h3>{selected.title}</h3><p>{selected.composer} · {selected.digital_editor} · {selected.license}</p><p>{selected.measure_count} 小节 / {selected.note_count} 个音符；使用已审核的小型钢琴音源。</p><p>{selected.conversion}</p><p><a href={selected.page_url} target="_blank" rel="noreferrer">查看原始谱源</a> · <a href={`/api/v1/classical-scores/${encodeURIComponent(selected.score_id)}/musicxml`}>下载本次旋律谱</a></p>
        <label className="piano-confirm"><input type="checkbox" checked={acknowledged} onChange={e=>setAcknowledged(e.target.checked)} disabled={creation.isPending}/>我已了解来源与转换范围，保留原谱并创建改编副本</label>
        <button className="primary-inline" type="button" disabled={!acknowledged||creation.isPending} onClick={()=>creation.mutate()}>{creation.isPending?'正在导入…':'导入这份旋律谱'}</button>
      </>}
      {creation.error&&<p role="alert" className="field-error">{creation.error instanceof ApiError?creation.error.message:'导入暂未完成，请重试。'}（原有作品不受影响）</p>}
    </div>}
  </section>;
}
