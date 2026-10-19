import {jsonHeaders,readData,requestJson} from '../../shared/api';
import type {PianoCapability,PianoPreviewData,PianoPreviewOptions,PianoPreviewDecision,PianoStudyResult} from '../../shared/openapi';
export async function readPianoCapability():Promise<PianoCapability>{return readData(await requestJson('/api/v1/piano-capability'));}
export async function createPianoStudy(key:string):Promise<PianoStudyResult>{return readData(await requestJson('/api/v1/piano-studies',{
  method:'POST',headers:jsonHeaders(key),body:JSON.stringify({name:'钢琴练习谱'})}));}
function base(projectId:string):string{return `/api/v1/projects/${encodeURIComponent(projectId)}/piano-previews`;}
export async function startPianoPreview(projectId:string,body:PianoPreviewOptions,key:string):Promise<PianoPreviewData>{
  return readData(await requestJson(base(projectId),{method:'POST',headers:jsonHeaders(key),body:JSON.stringify(body)}));
}
export async function readPianoPreview(projectId:string,thread:string):Promise<PianoPreviewData>{return readData(await requestJson(base(projectId)+'/'+encodeURIComponent(thread)));}
export async function decidePianoPreview(projectId:string,thread:string,body:PianoPreviewDecision):Promise<PianoPreviewData>{return readData(await requestJson(base(projectId)+'/'+encodeURIComponent(thread)+'/decision',{
  method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));}
export async function cancelPianoPreview(projectId:string,thread:string):Promise<PianoPreviewData>{return readData(await requestJson(base(projectId)+'/'+encodeURIComponent(thread)+'/cancel',{method:'POST'}));}
