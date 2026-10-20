import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {PianoPanel} from './PianoPanel';
import {pianoScore} from './pianoTestFixture';
import * as api from './pianoApi';
vi.mock('./pianoApi',()=>({readPianoCapability:vi.fn(),readPianoPreview:vi.fn(),startPianoPreview:vi.fn(),decidePianoPreview:vi.fn(),cancelPianoPreview:vi.fn()}));
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.resetAllMocks();window.sessionStorage.clear();window.history.replaceState({},'', '/');});
it('restores pending exact-hash audition after refresh and requires explicit confirmation',async()=>{
  window.history.replaceState({},'', '/?piano_preview=piano-existing');
  vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
  vi.mocked(api.readPianoPreview).mockResolvedValue({thread_id:'piano-existing',phase:'waiting_piano_approval',base_revision_id:'revision',
    candidate_content_hash:'b'.repeat(64),baseline_artifact_id:'baseline',piano_artifact_id:'piano'} as never);
  vi.mocked(api.decidePianoPreview).mockResolvedValue({phase:'completed',revision_id:'new-revision'} as never);
  const saved=vi.fn();renderPanel(false,saved);
  const confirm=await screen.findByRole('button',{name:'保存这版钢琴表达'});
  expect(confirm).toBeDisabled();expect(screen.getByRole('button',{name:'A · 原版本'})).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('我已试听，确认保存这版钢琴表达'));
  fireEvent.click(confirm);
  await waitFor(()=>expect(saved).toHaveBeenCalledWith('new-revision'));
  expect(api.decidePianoPreview).toHaveBeenCalledWith('project','piano-existing',expect.objectContaining({action:'approve',expected_candidate_content_hash:'b'.repeat(64)}));
});
it('blocks audition creation while a draft is unsaved',async()=>{
  vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
  renderPanel(true,vi.fn());
  expect(await screen.findByRole('button',{name:'生成 A/B 试听'})).toBeDisabled();
  expect(screen.getByText('请先保存或撤销草稿修改，再试听钢琴表达。')).toBeInTheDocument();
  expect(api.startPianoPreview).not.toHaveBeenCalled();
});
function renderPanel(dirty:boolean,onSaved:(id:string)=>void){
  return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}>
    <PianoPanel projectId="project" branchId="branch" revisionId="revision" arrangement={pianoScore()} selection={null} dirty={dirty} rootReady onSaved={onSaved}/>
  </QueryClientProvider>);
}

it.each([
  ['RENDER_SERVICE_UNAVAILABLE',503,false],
  ['INSTRUMENT_PACK_UNAVAILABLE',503,false],
  ['API_UNAVAILABLE',0,true],
] as const)('retries %s with the correct intent identity',async(code,status,reuse)=>{
  const {ApiError}=await import('../../shared/api');
  vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
  const waiting={thread_id:'piano-recovered',phase:'waiting_piano_worker',base_revision_id:'revision'} as never;
  vi.mocked(api.startPianoPreview).mockRejectedValueOnce(new ApiError('Temporary outage',code,true,status)).mockResolvedValue(waiting);
  vi.mocked(api.readPianoPreview).mockResolvedValue(waiting);
  renderPanel(false,vi.fn());
  await waitFor(()=>expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'生成 A/B 试听'}));
  fireEvent.click(await screen.findByRole('button',{name:'重试 A/B 试听'}));
  await waitFor(()=>expect(api.startPianoPreview).toHaveBeenCalledTimes(2));
  const calls=vi.mocked(api.startPianoPreview).mock.calls;
  expect(calls[0]![2]===calls[1]![2]).toBe(reuse);
});

function renderClassical(added=false){
  const arrangement=pianoScore();
  if(added)arrangement.tracks.push({...structuredClone(arrangement.tracks[0]!),track_id:'added-track',role:'bass',name:'伴奏'});
  return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}>
    <PianoPanel projectId="project" branchId="branch" revisionId="revision" arrangement={arrangement} selection={null} dirty={false} rootReady onSaved={vi.fn()} classicalSource={{revision_id:'original',source:{score_id:'mutopia-528-melody.v1',default_chords:Array(16).fill('G')},import_report:{measure_count:16,note_count:62}} as never}/>
  </QueryClientProvider>);
}
it('submits an explicit Flash description without a rule accompaniment and restores planning progress',async()=>{
  vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
  const planning={thread_id:'semantic-append',phase:'planning',base_revision_id:'revision'} as never;
  vi.mocked(api.startPianoPreview).mockResolvedValue(planning);
  vi.mocked(api.readPianoPreview).mockResolvedValue(planning);
  renderClassical();
  fireEvent.click(screen.getByLabelText('自然语言伴奏'));
  const generate=screen.getByRole('button',{name:'按描述生成 A/B 试听'});
  await waitFor(()=>expect(generate).toBeEnabled());fireEvent.click(generate);
  await screen.findByText('Flash 正在规划伴奏，原版本保持不变。可以刷新后继续。');
  expect(screen.getByText('本次规划返回后可取消试听或放弃候选。')).toBeInTheDocument();
  expect(screen.queryByRole('button',{name:'取消生成'})).not.toBeInTheDocument();
  expect(api.startPianoPreview).toHaveBeenCalledTimes(1);
  const body=vi.mocked(api.startPianoPreview).mock.calls[0]![1];
  expect(body).toEqual(expect.objectContaining({semantic:{schema_version:'piano-semantic-request.v1',intent:'加一个低音区钢琴伴奏，前8小节稀疏，后8小节稍活跃，不改旋律',mode:'append',start_bar:1,end_bar:16}}));
  expect(body).not.toHaveProperty('accompaniment');expect(generate).toBeDisabled();
  expect(window.location.search).toContain('piano_preview=semantic-append');
  expect(window.sessionStorage.length).toBe(0);
});
it('restricts local rewriting to the added track and at most four in-range bars',async()=>{
  vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
  const waiting={thread_id:'semantic-modify',phase:'waiting_piano_approval',base_revision_id:'revision',candidate_content_hash:'c'.repeat(64),semantic_summary:'第 9–12 小节稀疏轻奏',model:'deepseek-v4-flash',model_requests:1,total_tokens:null,usage_status:'unknown'} as never;
  vi.mocked(api.startPianoPreview).mockResolvedValue(waiting);vi.mocked(api.readPianoPreview).mockResolvedValue(waiting);
  renderClassical(true);
  expect(screen.getByText(/原和声、原谱与范围外内容保持不变；本轮不支持局部换和弦/)).toBeInTheDocument();
  const generate=screen.getByRole('button',{name:'按描述生成 A/B 试听'});
  await waitFor(()=>expect(generate).toBeEnabled());
  fireEvent.change(screen.getByLabelText('结束小节'),{target:{value:13}});expect(generate).toBeDisabled();
  fireEvent.change(screen.getByLabelText('结束小节'),{target:{value:17}});expect(generate).toBeDisabled();
  fireEvent.change(screen.getByLabelText('结束小节'),{target:{value:12}});
  fireEvent.change(screen.getByLabelText('伴奏描述'),{target:{value:'  '}});expect(generate).toBeDisabled();
  fireEvent.change(screen.getByLabelText('伴奏描述'),{target:{value:'第9–12小节更稀疏、更轻，其余保持'}});fireEvent.click(generate);
  await screen.findByText('第 9–12 小节稀疏轻奏');
  expect(api.startPianoPreview).toHaveBeenCalledWith('project',expect.objectContaining({semantic:expect.objectContaining({mode:'modify',target_track_id:'added-track',start_bar:9,end_bar:12})}),expect.any(String));
  expect(screen.getByText('Flash计划 + 确定性编译')).toBeInTheDocument();
  expect(screen.getByText(/用量暂不完整/)).toBeInTheDocument();
  expect(screen.getByRole('button',{name:'保留这次修改'})).toBeDisabled();
  expect(screen.queryByText(/0 元/)).not.toBeInTheDocument();
});
it('reuses the same semantic idempotency key after a network failure without automatic retry',async()=>{
  const {ApiError}=await import('../../shared/api');
  vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
  vi.mocked(api.startPianoPreview).mockRejectedValue(new ApiError('网络中断','API_UNAVAILABLE',true,0));
  renderClassical();fireEvent.click(screen.getByLabelText('自然语言伴奏'));
  const generate=screen.getByRole('button',{name:'按描述生成 A/B 试听'});
  await waitFor(()=>expect(generate).toBeEnabled());fireEvent.click(generate);
  await screen.findByRole('alert');expect(api.startPianoPreview).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button',{name:'重试同一次生成请求'}));
  await waitFor(()=>expect(api.startPianoPreview).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.startPianoPreview).mock.calls[0]![2]).toBe(vi.mocked(api.startPianoPreview).mock.calls[1]![2]);
  await waitFor(()=>expect(screen.getByRole('button',{name:'重试同一次生成请求'})).toBeEnabled());
  fireEvent.change(screen.getByLabelText('伴奏描述'),{target:{value:'改为更稀疏的低音'}});
  fireEvent.click(screen.getByRole('button',{name:'按描述生成 A/B 试听'}));
  await waitFor(()=>expect(api.startPianoPreview).toHaveBeenCalledTimes(3));
  expect(vi.mocked(api.startPianoPreview).mock.calls[2]![2]).not.toBe(vi.mocked(api.startPianoPreview).mock.calls[1]![2]);
});
it('restores planning from the URL and polls to exact-hash approval without another model request',async()=>{
  window.history.replaceState({},'', '/?piano_preview=semantic-restored');
  vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
  const planning={thread_id:'semantic-restored',phase:'planning',base_revision_id:'revision'} as never;
  const approval={thread_id:'semantic-restored',phase:'waiting_piano_approval',base_revision_id:'revision',candidate_content_hash:'d'.repeat(64),semantic_summary:'测试计划摘要',model:'deepseek-v4-flash',model_requests:1,total_tokens:1200,usage_status:'known'} as never;
  vi.mocked(api.readPianoPreview).mockResolvedValueOnce(planning).mockResolvedValue(approval);
  renderClassical(true);
  await screen.findByText('Flash 正在规划伴奏，原版本保持不变。可以刷新后继续。');
  expect(await screen.findByRole('button',{name:'保留这次修改'},{timeout:3000})).toBeDisabled();
  expect(screen.getByText('总用量：1200 tokens')).toBeInTheDocument();
  expect(api.startPianoPreview).not.toHaveBeenCalled();
});

it('retains an unconfirmed semantic request key across a page remount',async()=>{
  const {ApiError}=await import('../../shared/api');
  vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
  vi.mocked(api.startPianoPreview).mockRejectedValue(new ApiError('网络中断','API_UNAVAILABLE',true,0));
  const first=renderClassical();fireEvent.click(screen.getByLabelText('自然语言伴奏'));
  fireEvent.change(screen.getByLabelText('伴奏描述'),{target:{value:'前半段稀疏低音，后半段稍活跃'}});
  await waitFor(()=>expect(screen.getByRole('button',{name:'按描述生成 A/B 试听'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'按描述生成 A/B 试听'}));await screen.findByRole('alert');first.unmount();
  renderClassical();fireEvent.click(screen.getByLabelText('自然语言伴奏'));
  expect(screen.getByLabelText('伴奏描述')).toHaveValue('前半段稀疏低音，后半段稍活跃');
  await waitFor(()=>expect(screen.getByRole('button',{name:'按描述生成 A/B 试听'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'按描述生成 A/B 试听'}));
  await waitFor(()=>expect(api.startPianoPreview).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.startPianoPreview).mock.calls[1]![2]).toBe(vi.mocked(api.startPianoPreview).mock.calls[0]![2]);
});
it('keeps a failed semantic request in memory and warns when browser identity storage is unavailable',async()=>{
  vi.spyOn(window,'sessionStorage','get').mockImplementation(()=>{throw new Error('Storage disabled');});
  const {ApiError}=await import('../../shared/api');
  vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
  vi.mocked(api.startPianoPreview).mockRejectedValue(new ApiError('网络中断','API_UNAVAILABLE',true,0));
  renderClassical();fireEvent.click(screen.getByLabelText('自然语言伴奏'));
  expect(screen.getByText(/浏览器无法保存请求标识/)).toBeInTheDocument();
  await waitFor(()=>expect(screen.getByRole('button',{name:'按描述生成 A/B 试听'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'按描述生成 A/B 试听'}));await screen.findByRole('alert');
  fireEvent.click(screen.getByRole('button',{name:'重试同一次生成请求'}));
  await waitFor(()=>expect(api.startPianoPreview).toHaveBeenCalledTimes(2));
  expect(vi.mocked(api.startPianoPreview).mock.calls[1]![2]).toBe(vi.mocked(api.startPianoPreview).mock.calls[0]![2]);
});

it('keeps a new eight-bar score on real rule chords and disables unsupported semantic requests',async()=>{
 vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);const waiting={thread_id:'new-score',phase:'waiting_piano_worker',base_revision_id:'revision'} as never;vi.mocked(api.startPianoPreview).mockResolvedValue(waiting);vi.mocked(api.readPianoPreview).mockResolvedValue(waiting);
 const arrangement=pianoScore();render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><PianoPanel projectId="p" branchId="b" revisionId="revision" arrangement={arrangement} selection={null} dirty={false} rootReady onSaved={vi.fn()} classicalSource={{source:{score_id:'c02-la-candeur-a8.v1',default_chords:['C','G','C','G','F','C','G','C']},import_report:{measure_count:8,beats:4,tonic:'C'}} as never}/></QueryClientProvider>);
 expect(screen.getByRole('radio',{name:/自然语言伴奏/})).toBeDisabled();
 const button=screen.getByRole('button',{name:'生成 A/B 试听'});await waitFor(()=>expect(button).toBeEnabled());fireEvent.click(button);
 await waitFor(()=>expect(api.startPianoPreview).toHaveBeenCalledWith('p',expect.objectContaining({accompaniment:expect.objectContaining({chords:['C','G','C','G','F','C','G','C']})}),expect.any(String)));
 expect(vi.mocked(api.startPianoPreview).mock.calls[0]![1]).not.toHaveProperty('semantic');
});
it('never opens legacy semantic modification for a new two-track score',async()=>{
 vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);const arrangement=pianoScore();arrangement.tracks.push({...structuredClone(arrangement.tracks[0]!),track_id:'added',name:'伴奏'});
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><PianoPanel projectId="p" branchId="b" revisionId="r" arrangement={arrangement} selection={null} dirty={false} rootReady onSaved={vi.fn()} classicalSource={{source:{score_id:'j01-bethena-a-first8.v1',default_chords:Array(8).fill('G')},import_report:{measure_count:8,beats:3,tonic:'G'}} as never}/></QueryClientProvider>);
 expect(screen.queryByRole('button',{name:'按描述生成 A/B 试听'})).not.toBeInTheDocument();expect(screen.getByText(/新曲目的自然语言/)).toBeInTheDocument();expect(api.startPianoPreview).not.toHaveBeenCalled();
});
