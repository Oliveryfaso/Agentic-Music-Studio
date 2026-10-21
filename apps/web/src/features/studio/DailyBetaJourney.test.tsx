import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {PianoPanel} from './PianoPanel';
import {ExportPage} from '../exports/ExportPage';
import {ClassicalScoreEntry} from '../projects/ClassicalScoreEntry';
import {pianoScore} from './pianoTestFixture';
import * as piano from './pianoApi';
import * as exports from '../exports/exportApi';
import {ApiError} from '../../shared/api';
vi.mock('./pianoApi',()=>({readPianoCapability:vi.fn(),readPianoPreview:vi.fn(),startPianoPreview:vi.fn(),decidePianoPreview:vi.fn(),cancelPianoPreview:vi.fn()}));
vi.mock('../exports/exportApi',()=>({readRevisionExport:vi.fn(),startRevisionExport:vi.fn(),cancelRevisionExport:vi.fn()}));
vi.mock('../projects/classicalApi',()=>({listClassicalScores:vi.fn(),importClassicalScore:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();sessionStorage.clear();window.history.replaceState({},'','/');});
function provider(child:React.ReactNode){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}>{child}</QueryClientProvider>);}
function showPiano(){
 const arrangement=pianoScore();arrangement.tracks.push({...structuredClone(arrangement.tracks[0]!),track_id:'added',name:'第二钢琴'});
 return provider(<PianoPanel projectId="p" branchId="b" revisionId="r" arrangement={arrangement} selection={{trackIds:['track'],startTick:0,endTick:1920}} dirty={false} rootReady onSaved={vi.fn()} classicalSource={{source:{score_id:'c02-la-candeur-a8.v1',default_chords:Array(8).fill('C')},import_report:{measure_count:8,beats:4,tonic:'C'}} as never}/>);
}
it('reads an existing thread after failure without unlocking or posting a new generation',async()=>{
 window.history.replaceState({},'','/?piano_preview=existing');vi.mocked(piano.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
 vi.mocked(piano.readPianoPreview).mockRejectedValueOnce(new ApiError('offline','API_UNAVAILABLE',true,0)).mockResolvedValue({thread_id:'existing',base_revision_id:'r',phase:'rejected'} as never);
 showPiano();const retry=await screen.findByRole('button',{name:'重新读取试听进度'});
 expect(screen.getByRole('button',{name:'按描述生成 A/B 试听'})).toBeDisabled();expect(piano.startPianoPreview).not.toHaveBeenCalled();
 fireEvent.click(retry);await waitFor(()=>expect(piano.readPianoPreview).toHaveBeenCalledTimes(2));
 await waitFor(()=>expect(screen.getByRole('button',{name:'按描述生成 A/B 试听'})).toBeEnabled());expect(piano.startPianoPreview).not.toHaveBeenCalled();
 expect(vi.mocked(piano.readPianoPreview).mock.calls.every(call=>call[1]==='existing')).toBe(true);
});
it('blocks a new request while recovering an existing thread and keeps the scope explicit',async()=>{
 window.history.replaceState({},'','/?piano_preview=existing');vi.mocked(piano.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);vi.mocked(piano.readPianoPreview).mockReturnValue(new Promise(()=>{}));
 showPiano();await waitFor(()=>expect(piano.readPianoCapability).toHaveBeenCalled());
 expect(screen.getByRole('button',{name:'按描述生成 A/B 试听'})).toBeDisabled();
 expect(screen.getByText(/本次范围以开始、结束小节为准，不跟随时间线选区/)).toBeInTheDocument();expect(screen.getByText(/第二钢琴.*第 5–8 小节/)).toBeInTheDocument();
});
it('explains missing resource profile and retains the capability failure code',async()=>{
 vi.mocked(piano.readPianoCapability).mockResolvedValue({available:true,error_code:'PROFILE_UNAVAILABLE'} as never);showPiano();
 expect(await screen.findByText(/钢琴音源配置不完整/)).toHaveTextContent('PROFILE_UNAVAILABLE');expect(screen.getByRole('button',{name:'按描述生成 A/B 试听'})).toBeDisabled();
});
it('keeps a failed read of cached approval locked until authoritative progress is read again',async()=>{
 window.history.replaceState({},'','/?piano_preview=existing');vi.mocked(piano.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
 const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});client.setQueryData(['piano-preview','p','existing'],{thread_id:'existing',base_revision_id:'r',phase:'waiting_piano_approval',candidate_content_hash:'c'.repeat(64)});
 vi.mocked(piano.readPianoPreview).mockRejectedValue(new Error('offline'));
 const arrangement=pianoScore();arrangement.tracks.push({...structuredClone(arrangement.tracks[0]!),track_id:'added'});
 render(<QueryClientProvider client={client}><PianoPanel projectId="p" branchId="b" revisionId="r" arrangement={arrangement} selection={null} dirty={false} rootReady onSaved={vi.fn()} classicalSource={{source:{score_id:'c02-la-candeur-a8.v1',default_chords:Array(8).fill('C')},import_report:{measure_count:8,beats:4}} as never}/></QueryClientProvider>);
 await screen.findByRole('button',{name:'重新读取试听进度'});expect(screen.getByRole('checkbox',{name:'我已试听，确认保留这次修改'})).toBeDisabled();expect(piano.decidePianoPreview).not.toHaveBeenCalled();
});
const emptyExport={project_id:'p',revision_id:'r',source_run_id:null,status:'partial',error_code:null,bundle:null,export_thread_id:null,files:[],steps:[{step:'master',job_id:null,status:'pending',artifact_id:null}]};
it('distinguishes export not requested from a running job and never starts on page load',async()=>{
 vi.mocked(exports.readRevisionExport).mockResolvedValue(emptyExport as never);provider(<ExportPage projectId="p" revisionId="r"/>);
 expect(await screen.findByText('尚未生成导出')).toBeInTheDocument();expect(screen.queryByText('导出部分完成')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'生成导出文件'})).toBeEnabled();expect(exports.startRevisionExport).not.toHaveBeenCalled();
});
it('retains the running state when a real export thread exists',async()=>{
 vi.mocked(exports.readRevisionExport).mockResolvedValue({...emptyExport,export_thread_id:'export-existing',steps:[{step:'master',job_id:'job',status:'queued'}]} as never);provider(<ExportPage projectId="p" revisionId="r"/>);
 expect(await screen.findByRole('button',{name:'取消导出'})).toBeInTheDocument();expect(screen.getByRole('button',{name:'生成导出文件'})).toBeDisabled();expect(screen.queryByText('尚未生成导出')).not.toBeInTheDocument();
});
it('states reviewed-catalog and post-render confirmation boundaries at the classic entry',()=>{
 provider(<ClassicalScoreEntry/>);expect(screen.getByText(/固定审核的主旋律摘录/)).toBeInTheDocument();expect(screen.getByText(/试听 A\/B 后再决定是否保留/)).toBeInTheDocument();
});
it('does not promise same-request retry for a failed terminal preview',async()=>{
 window.history.replaceState({},'','/?piano_preview=failed');vi.mocked(piano.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
 vi.mocked(piano.readPianoPreview).mockResolvedValue({thread_id:'failed',base_revision_id:'r',phase:'failed',error_code:'PIANO_SEMANTIC_UNAVAILABLE'} as never);showPiano();
 expect(await screen.findByText(/自然语言伴奏服务暂不可用。请先检查本地服务，原版本保留。/)).toBeInTheDocument();
 expect(screen.queryByText(/检查本地服务后重试同一次请求/)).not.toBeInTheDocument();expect(piano.startPianoPreview).not.toHaveBeenCalled();
});
