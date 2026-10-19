import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {PianoPanel} from './PianoPanel';
import {pianoScore} from './pianoTestFixture';
import * as api from './pianoApi';
vi.mock('./pianoApi',()=>({readPianoCapability:vi.fn(),readPianoPreview:vi.fn(),startPianoPreview:vi.fn(),decidePianoPreview:vi.fn(),cancelPianoPreview:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();window.history.replaceState({},'', '/');});
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
