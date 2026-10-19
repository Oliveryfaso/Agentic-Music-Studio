import {useQuery} from '@tanstack/react-query';
import type {ComponentProps} from 'react';
import {readClassicalSource} from '../projects/classicalApi';
import {PianoPanel} from './PianoPanel';
export function ClassicalAccompanimentPanel(props:Omit<ComponentProps<typeof PianoPanel>,'classicalSource'>){
  const source=useQuery({queryKey:['classical-source',props.projectId],queryFn:()=>readClassicalSource(props.projectId),retry:false});
  if(source.isPending)return <p role="status">正在读取原谱与导入报告…</p>;
  if(!source.data)return <section className="studio-panel"><p role="alert">暂时无法读取原谱说明。</p><button type="button" onClick={()=>void source.refetch()}>重新读取原谱</button></section>;
  return <>
    <section className="studio-panel"><details><summary>来源与导入报告</summary><p>{source.data.source.title} · {source.data.source.license}</p><p>{source.data.import_report.measure_count} 小节 / {source.data.import_report.note_count} 个音符，末尾另留一小节休止供尾音释放。</p><p>{source.data.source.conversion}</p><p>原旋律已锁定，新增内容保存在改编分支。</p><a href={source.data.source.page_url} target="_blank" rel="noreferrer">原始谱源</a> · <a href={`/projects/${encodeURIComponent(props.projectId)}/studio/${encodeURIComponent(source.data.revision_id)}`}>查看保留的原谱版本</a></details></section>
    <PianoPanel {...props} classicalSource={source.data}/>
  </>;
}
