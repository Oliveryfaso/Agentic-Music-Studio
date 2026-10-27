import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {PianoPanel} from './PianoPanel';
import {ApiError} from '../../shared/api';
import {pianoScore} from './pianoTestFixture';
import * as api from './pianoApi';
vi.mock('./pianoApi',()=>({readPianoCapability:vi.fn(),readPianoPreview:vi.fn(),startPianoPreview:vi.fn(),decidePianoPreview:vi.fn(),cancelPianoPreview:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();window.sessionStorage.clear();window.history.replaceState({},'','/');});
function show(state?:Record<string,unknown>,configuration?:'configured'|'not_configured'){
 vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{},semantic_generation:configuration?{configuration,reason_code:configuration==='not_configured'?'MODEL_NOT_CONFIGURED':null}:undefined} as never);
 if(state){window.history.replaceState({},'','/?piano_preview=daily');vi.mocked(api.readPianoPreview).mockResolvedValue({thread_id:'daily',base_revision_id:'r',...state} as never);}
 const arrangement=pianoScore();arrangement.tracks.push({...structuredClone(arrangement.tracks[0]!),track_id:'added',name:'伴奏'});
 return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><PianoPanel projectId="p" branchId="b" revisionId="r" arrangement={arrangement} selection={null} dirty={false} rootReady onSaved={vi.fn()} classicalSource={{source:{score_id:'c02-la-candeur-a8.v1',default_chords:Array(8).fill('C')},import_report:{measure_count:8,beats:4,tonic:'C'}} as never}/></QueryClientProvider>);
}
it('keeps descriptive piano modification model-only while showing the configuration destination',async()=>{
 show(undefined,'not_configured');
 expect(await screen.findByText(/自然语言服务尚未配置，暂不能按描述修改伴奏/)).toBeInTheDocument();
 expect(screen.getByRole('link',{name:'配置 API Key'})).toHaveAttribute('href','/settings');
 expect(screen.getByRole('button',{name:'按描述生成 A/B 试听'})).toBeDisabled();
 expect(api.startPianoPreview).not.toHaveBeenCalled();
});
it('fills an explicit register-preserving intent only on request and never submits automatically',async()=>{
 show();const text=screen.getByLabelText('伴奏描述');expect(text).toHaveValue('这几小节更稀疏、更轻，其余保持');
 expect(screen.getByText(/当前曲目：8 小节，4\/4/)).toBeInTheDocument();
 fireEvent.click(screen.getByRole('button',{name:'填入保留音区的描述'}));
 expect(text).toHaveValue('这几小节更稀疏、更轻，保留原和声与音区，其余保持不变。');
 expect(api.startPianoPreview).not.toHaveBeenCalled();
 vi.mocked(api.startPianoPreview).mockResolvedValue({thread_id:'sent',phase:'planning',base_revision_id:'r'} as never);vi.mocked(api.readPianoPreview).mockResolvedValue({thread_id:'sent',phase:'planning',base_revision_id:'r'} as never);
 const button=screen.getByRole('button',{name:'按描述生成 A/B 试听'});await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);
 await waitFor(()=>expect(api.startPianoPreview).toHaveBeenCalledTimes(1));
 expect(vi.mocked(api.startPianoPreview).mock.calls[0]![1].semantic).toEqual(expect.objectContaining({intent:'这几小节更稀疏、更轻，保留原和声与音区，其余保持不变。',start_bar:5,end_bar:8,target_track_id:'added'}));
});
it('shows reported total with partial usage without claiming confirmed cost or inventing zero',async()=>{
 show({phase:'waiting_piano_approval',candidate_content_hash:'c'.repeat(64),model:'deepseek-flash',usage_status:'partial',total_tokens:2501,model_requests:1});
 expect(await screen.findByText('已报告用量：2501 tokens（明细不完整，费用未确认）')).toBeInTheDocument();
 expect(screen.queryByText(/0 元|费用已确认/)).not.toBeInTheDocument();
 expect(api.startPianoPreview).not.toHaveBeenCalled();
});
it.each([
 ['PIANO_REGISTER_UNVERIFIED','无法核实这段伴奏的保存音区，未调用模型。请打开有生成计划的保存版本，或先移除描述中的音区保持要求。'],
 ['PIANO_REGISTER_CHANGED','生成结果没有保留要求的音区，候选已拒绝，原版本不变。'],
 ['REVISION_CONFLICT','保存版本已变化。请从作品列表打开最新版本，再检查选区并生成。'],
])('explains %s while retaining the observable code and making no automatic request',async(code,message)=>{
 show({phase:'failed',error_code:code});expect(await screen.findByText(message,{exact:false})).toBeInTheDocument();
 expect(screen.getByText(new RegExp(code))).toBeInTheDocument();expect(api.startPianoPreview).not.toHaveBeenCalled();
});
it('keeps approval disabled when recovered audition belongs to an older revision',async()=>{
 show({phase:'waiting_piano_approval',base_revision_id:'older',candidate_content_hash:'d'.repeat(64)});
 expect(await screen.findByText(/这段试听属于另一个已保存版本/)).toBeInTheDocument();
 expect(screen.getByRole('button',{name:'保留这次修改'})).toBeDisabled();
 expect(api.decidePianoPreview).not.toHaveBeenCalled();expect(api.startPianoPreview).not.toHaveBeenCalled();
});

it('explains an actual stale start response without retrying automatically',async()=>{
 vi.mocked(api.startPianoPreview).mockRejectedValue(new ApiError('Base revision is stale','AI_RUN_BASE_REVISION_CONFLICT',false,409));
 show();const button=screen.getByRole('button',{name:'按描述生成 A/B 试听'});
 await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);
 const alert=await screen.findByRole('alert');
 expect(alert).toHaveTextContent('保存版本已变化。请从作品列表打开最新版本，再检查选区并生成。');
 expect(alert).toHaveTextContent('AI_RUN_BASE_REVISION_CONFLICT');
 expect(api.startPianoPreview).toHaveBeenCalledTimes(1);
});
