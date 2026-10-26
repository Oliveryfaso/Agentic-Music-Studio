import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {act,cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,describe,expect,it,vi} from 'vitest';
import {StudioPage} from './StudioPage';
import {PianoPanel} from './PianoPanel';
import {pianoScore} from './pianoTestFixture';
import type {ClassicalSourceData,PianoCapability,ProjectWorkspace,RevisionStudio} from '../../shared/openapi';
import {ApiError} from '../../shared/api';
import {navigateHref} from '../../app/routes';
import {App} from '../../app/App';
import {eqBase} from './pianoEqTestFixture';
import * as piano from './pianoApi';
import * as projects from '../projects/projectApi';
import * as studioApi from './studioApi';
vi.mock('./pianoApi',()=>({readPianoCapability:vi.fn(),readPianoPreview:vi.fn(),startPianoPreview:vi.fn(),decidePianoPreview:vi.fn(),cancelPianoPreview:vi.fn()}));
vi.mock('../projects/projectApi',()=>({readProject:vi.fn(),readRevisionStudio:vi.fn()}));
vi.mock('./studioApi',()=>({listSoundCatalog:vi.fn(),commitCommandBatch:vi.fn(),undoCommittedRevision:vi.fn()}));
const P='11111111-1111-4111-8111-111111111111',B='22222222-2222-4222-8222-222222222222',R='33333333-3333-4333-8333-333333333333',OLD='44444444-4444-4444-8444-444444444444',T='piano-'+ 'a'.repeat(32);
const profile={schema_version:'render-profile.v1',engine_version:'motif-forge-audio-engine.v2',instrument_pack_id:'freepats:upright-kw-small',instrument_pack_version:'2019-07-03.motif1',manifest_sha256:'264fdbf12f3c7273a0d15fbcb86abed04b73e08b6fc4faf482eaf41040a0b813'} as const;
function workspace():ProjectWorkspace{return {project_id:P,name:'合同试听作品',status:'active',updated_at:'2026-10-21T00:00:00Z',active_branch_id:B,head_revision_id:R,revisions:[],runs:[],recoverable_run:null,storage_root_status:'ready',recoverable_piano_preview:{thread_id:T,branch_id:B,base_revision_id:R,phase:'waiting_piano_approval',updated_at:'2026-10-21T00:00:00Z'},piano_preview_recovery:{status:'ready',pending_count:1,selection_rule:'newest_created',reason_code:null}};}
function saved():RevisionStudio{return {project_id:P,revision_id:R,parent_revision_id:OLD,source_run_id:null,reason_code:'CLASSICAL_SCORE_IMPORTED',author_kind:'system',created_by:'test:fixture',created_at:'2026-10-21T00:00:00Z',arrangement_ir:pianoScore(),delivery_assets:[],bundle_id:null};}
function mount(child:React.ReactNode,client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})){return {client,...render(<QueryClientProvider client={client}>{child}</QueryClientProvider>)};}
function mountStudio(value=workspace(),revision=saved()){
 vi.mocked(projects.readProject).mockResolvedValue(value);vi.mocked(projects.readRevisionStudio).mockResolvedValue(revision);
 return mount(<StudioPage projectId={P} revisionId={revision.revision_id}/>);
}
beforeEach(()=>{vi.mocked(piano.readPianoCapability).mockResolvedValue({pedal_supported:false,release_triggers_supported:false,available:true,render_profile:profile});vi.mocked(studioApi.listSoundCatalog).mockResolvedValue([]);});
afterEach(()=>{cleanup();vi.resetAllMocks();sessionStorage.clear();window.history.replaceState({},'','/');});
function noWrites(){expect(piano.startPianoPreview).not.toHaveBeenCalled();expect(piano.decidePianoPreview).not.toHaveBeenCalled();expect(piano.cancelPianoPreview).not.toHaveBeenCalled();expect(studioApi.commitCommandBatch).not.toHaveBeenCalled();expect(studioApi.undoCommittedRevision).not.toHaveBeenCalled();}

describe('workspace candidate recovery',()=>{
 it('keeps the actual mixer Draft across view queries and guards a workspace href',async()=>{
  window.history.replaceState({},'',`/projects/${P}/studio/${R}`);
  vi.mocked(projects.readProject).mockResolvedValue(workspace());vi.mocked(projects.readRevisionStudio).mockResolvedValue({...saved(),arrangement_ir:eqBase()});
  render(<App/>);await screen.findByRole('heading',{name:'合同试听作品'});fireEvent.click(screen.getByRole('button',{name:'混音'}));
  const gain=screen.getByLabelText('Piano 音量');fireEvent.change(gain,{target:{value:'-4'}});fireEvent.pointerUp(gain);fireEvent.blur(gain);
  expect(screen.getByText('1 个未保存修改')).toBeInTheDocument();fireEvent.click(screen.getByRole('button',{name:'编排'}));
  expect(screen.getByText('1 个未保存修改')).toBeInTheDocument();fireEvent.click(screen.getByRole('link',{name:'作品'}));
  expect(screen.getByRole('alertdialog')).toBeVisible();fireEvent.click(screen.getByText('留在此页'));
  expect(screen.getByText('1 个未保存修改')).toBeInTheDocument();noWrites();
 });
 it('reads an explicitly selected recovery query on the same mounted Studio without generating',async()=>{
  window.history.replaceState({},'',`/projects/${P}/studio/${R}`);
  vi.mocked(piano.readPianoPreview).mockResolvedValue({replayed:false,thread_id:T,base_revision_id:R,phase:'cancelled'});
  mountStudio();await screen.findByRole('link',{name:'恢复这版试听'});
  navigateHref(`/projects/${P}/studio/${R}?piano_preview=${T}`);
  await waitFor(()=>expect(piano.readPianoPreview).toHaveBeenCalledWith(P,T));
  expect(await screen.findByText('试听已取消，原版本保留。')).toBeInTheDocument();noWrites();
 });
 it('offers the exact existing base/thread link without automatically opening or regenerating it',async()=>{
  mountStudio();const link=await screen.findByRole('link',{name:'恢复这版试听'});
  expect(link).toHaveAttribute('href',`/projects/${P}/studio/${R}?piano_preview=${T}`);expect(window.location.search).toBe('');
  expect(piano.readPianoPreview).not.toHaveBeenCalled();expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeDisabled();noWrites();
 });
 it('reports multiple pending candidates without claiming the newest is the only one',async()=>{
  const value=workspace();value.piano_preview_recovery!.pending_count=2;mountStudio(value);
  expect(await screen.findByText(/当前分支有 2 版未完成试听/)).toHaveTextContent('这里只列出最新创建的一版');
  expect(screen.getAllByRole('link',{name:'恢复这版试听'})).toHaveLength(1);noWrites();
 });
 it('links a stale candidate to its original base and explains the approval restriction',async()=>{
  const value=workspace();value.recoverable_piano_preview!.base_revision_id=OLD;mountStudio(value);
  expect(await screen.findByRole('link',{name:'恢复这版试听'})).toHaveAttribute('href',`/projects/${P}/studio/${OLD}?piano_preview=${T}`);
  expect(screen.getByText(/这版试听基于较早版本/)).toHaveTextContent('不能保留');noWrites();
 });
 it('distinguishes an unavailable directory from no candidate and retries only the workspace read',async()=>{
  const value=workspace();value.recoverable_piano_preview=null;value.piano_preview_recovery={status:'unavailable',pending_count:null,selection_rule:'newest_created',reason_code:'PIANO_RECOVERY_UNAVAILABLE'};
  mountStudio(value);const retry=await screen.findByRole('button',{name:'重新读取未完成试听'});
  expect(screen.getByText(/暂时无法读取未完成试听/)).toHaveTextContent('PIANO_RECOVERY_UNAVAILABLE');
  expect(screen.queryByText('当前分支没有可恢复的未完成试听。')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeDisabled();
  const empty=workspace();empty.recoverable_piano_preview=null;empty.piano_preview_recovery!.pending_count=0;vi.mocked(projects.readProject).mockResolvedValue(empty);fireEvent.click(retry);
  expect(await screen.findByText('当前分支没有可恢复的未完成试听。')).toBeInTheDocument();expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeEnabled();
  expect(vi.mocked(projects.readProject).mock.calls.every(call=>call[0]===P)).toBe(true);expect(piano.readPianoPreview).not.toHaveBeenCalled();noWrites();
 });
 it('shows the lookup limit without misreporting zero pending candidates',async()=>{
  const value=workspace();value.recoverable_piano_preview=null;value.piano_preview_recovery={status:'limit_reached',pending_count:null,selection_rule:'newest_created',reason_code:'PIANO_RECOVERY_LIMIT_REACHED'};mountStudio(value);
  expect(await screen.findByText(/未完成试听的查询达到上限/)).toHaveTextContent('PIANO_RECOVERY_LIMIT_REACHED');
  expect(screen.queryByRole('link',{name:'恢复这版试听'})).not.toBeInTheDocument();expect(screen.queryByText('当前分支没有可恢复的未完成试听。')).not.toBeInTheDocument();noWrites();
 });
 it('treats missing legacy recovery fields as unconfirmed rather than empty',async()=>{
  const value=workspace();delete value.piano_preview_recovery;delete value.recoverable_piano_preview;mountStudio(value);
  expect(await screen.findByText(/尚未确认是否有未完成试听/)).toBeInTheDocument();expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeDisabled();noWrites();
 });
 it('keeps an explicit failing thread and never substitutes the directory candidate',async()=>{
  window.history.replaceState({},'','/?piano_preview=explicit-failure');vi.mocked(piano.readPianoPreview).mockRejectedValue(new ApiError('not found','AI_RUN_NOT_FOUND',false,404));mountStudio();
  const retry=await screen.findByRole('button',{name:'重新读取试听进度'});expect(screen.queryByRole('link',{name:'恢复这版试听'})).not.toBeInTheDocument();
  fireEvent.click(retry);await waitFor(()=>expect(piano.readPianoPreview).toHaveBeenCalledTimes(2));
  expect(vi.mocked(piano.readPianoPreview).mock.calls.every(call=>call[1]==='explicit-failure')).toBe(true);expect(window.location.search).toBe('?piano_preview=explicit-failure');noWrites();
 });
 it('protects unsaved draft edits from the full-page recovery link',async()=>{
  mountStudio();await screen.findByRole('link',{name:'恢复这版试听'});
  fireEvent.change(screen.getByLabelText('片段增益'),{target:{value:'-2'}});fireEvent.blur(screen.getByLabelText('片段增益'));
  expect(await screen.findByText('请先保存或撤销草稿，再打开已有试听。')).toBeInTheDocument();expect(screen.queryByRole('link',{name:'恢复这版试听'})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'恢复这版试听'})).toBeDisabled();noWrites();
 });
 it('blocks a cached empty directory while its authoritative workspace read is still pending',async()=>{
  const value=workspace();value.recoverable_piano_preview=null;value.piano_preview_recovery!.pending_count=0;
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});client.setQueryData(['project',P],value);client.setQueryData(['revision-studio',P,R],saved());client.setQueryData(['piano-capability'],{pedal_supported:false,release_triggers_supported:false,available:true,render_profile:profile});
  vi.mocked(projects.readProject).mockReturnValue(new Promise(()=>{}));vi.mocked(projects.readRevisionStudio).mockResolvedValue(saved());mount(<StudioPage projectId={P} revisionId={R}/>,client);
  await screen.findByRole('heading',{name:'合同试听作品'});expect(screen.queryByText('当前分支没有可恢复的未完成试听。')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeDisabled();expect(screen.getByText(/正在读取未完成试听/)).toBeInTheDocument();noWrites();
 });
 it('keeps generation locked after an explicit terminal thread until a fresh directory read confirms zero pending',async()=>{
  window.history.replaceState({},'','/?piano_preview='+T);vi.mocked(piano.readPianoPreview).mockResolvedValue({replayed:false,thread_id:T,base_revision_id:R,phase:'rejected'});mountStudio();
  await screen.findByText('已放弃试听，原版本保留。');expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeDisabled();
  const empty=workspace();empty.recoverable_piano_preview=null;empty.piano_preview_recovery!.pending_count=0;vi.mocked(projects.readProject).mockResolvedValue(empty);fireEvent.click(screen.getByRole('button',{name:'重新读取未完成试听'}));
  await waitFor(()=>expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeEnabled());expect(window.location.search).toBe('?piano_preview='+T);noWrites();
 });
 it('keeps other pending candidates protected after the explicit thread reaches a terminal state',async()=>{
  window.history.replaceState({},'','/?piano_preview='+T);vi.mocked(piano.readPianoPreview).mockResolvedValue({replayed:false,thread_id:T,base_revision_id:R,phase:'cancelled'});
  const value=workspace();value.piano_preview_recovery!.pending_count=2;mountStudio(value);await screen.findByText('试听已取消，原版本保留。');expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeDisabled();
  const remaining=workspace();remaining.recoverable_piano_preview!.thread_id='piano-'+ 'b'.repeat(32);vi.mocked(projects.readProject).mockResolvedValue(remaining);fireEvent.click(screen.getByRole('button',{name:'重新读取未完成试听'}));
  expect(await screen.findByRole('link',{name:'恢复这版试听'})).toHaveAttribute('href',`/projects/${P}/studio/${R}?piano_preview=${remaining.recoverable_piano_preview!.thread_id}`);expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeDisabled();expect(window.location.search).toBe('?piano_preview='+T);noWrites();
 });
 it('protects dirty edits from the new latest-version navigation on an older base',async()=>{
  const value=saved();value.revision_id=OLD;mountStudio(workspace(),value);await screen.findByRole('link',{name:'打开最新版本'});fireEvent.change(screen.getByLabelText('片段增益'),{target:{value:'-2'}});fireEvent.blur(screen.getByLabelText('片段增益'));
  expect(screen.queryByRole('link',{name:'打开最新版本'})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'打开最新版本'})).toBeDisabled();expect(screen.getByText('请先保存或撤销草稿，再打开最新版本。')).toBeInTheDocument();noWrites();
 });
 it('disables committed Undo for a root and explains that there is no parent version',async()=>{
  const value=saved();value.parent_revision_id=null;mountStudio(workspace(),value);
  const undo=await screen.findByRole('button',{name:'撤回已保存修改'});expect(undo).toBeDisabled();fireEvent.click(undo);
  expect(screen.getByText('初始版本没有上一版可撤回。')).toBeInTheDocument();expect(screen.queryByText('保存失败，草稿仍保留')).not.toBeInTheDocument();noWrites();
 });
});

const source={source:{score_id:'c02-la-candeur-a8.v1',default_chords:Array(8).fill('C')},import_report:{measure_count:8,beats:4,tonic:'C'}} as ClassicalSourceData;
function showPiano(capability:PianoCapability,headRevisionId=R){vi.mocked(piano.readPianoCapability).mockResolvedValue(capability);return mount(<PianoPanel projectId={P} branchId={B} revisionId={R} headRevisionId={headRevisionId} arrangement={pianoScore()} selection={null} dirty={false} rootReady onSaved={vi.fn()} classicalSource={source}/>);}
describe('independent model configuration and current head',()=>{
 it('blocks only semantic submission when not configured and preserves the description and selected mode',async()=>{
  showPiano({pedal_supported:false,release_triggers_supported:false,available:true,render_profile:profile,semantic_generation:{configuration:'not_configured',reason_code:'MODEL_NOT_CONFIGURED'}});
  expect(await screen.findByText(/自然语言服务尚未配置/)).toHaveTextContent('MODEL_NOT_CONFIGURED');
  expect(screen.getByRole('link',{name:'配置 API Key'})).toHaveAttribute('href','/settings');
  expect(screen.queryByText(/钢琴音源暂不可用/)).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeEnabled();
  fireEvent.click(screen.getByRole('radio',{name:'自然语言伴奏'}));fireEvent.change(screen.getByLabelText('伴奏描述'),{target:{value:'稀疏一点，保留旋律'}});
  const submit=screen.getByRole('button',{name:'按描述生成 A/B 试听'});expect(submit).toBeDisabled();fireEvent.click(submit);
  expect(screen.getByRole('radio',{name:'自然语言伴奏'})).toBeChecked();expect(screen.getByLabelText('伴奏描述')).toHaveValue('稀疏一点，保留旋律');noWrites();
 });
 it('reports unavailable semantic modification without offering a rules action that is absent for two tracks',async()=>{
  vi.mocked(piano.readPianoCapability).mockResolvedValue({pedal_supported:false,release_triggers_supported:false,available:true,render_profile:profile,semantic_generation:{configuration:'not_configured',reason_code:'MODEL_NOT_CONFIGURED'}});
  const arrangement=pianoScore();arrangement.tracks.push({...structuredClone(arrangement.tracks[0]!),track_id:'added',name:'第二钢琴'});
  mount(<PianoPanel projectId={P} branchId={B} revisionId={R} headRevisionId={R} arrangement={arrangement} selection={null} dirty={false} rootReady onSaved={vi.fn()} classicalSource={source}/>);
  expect(await screen.findByText(/自然语言服务尚未配置/)).toHaveTextContent('暂不能按描述修改伴奏');expect(screen.queryByText(/规则伴奏仍可使用/)).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'按描述生成 A/B 试听'})).toBeDisabled();noWrites();
 });
 it('labels configured as local configuration only and keeps renderer failure separate',async()=>{
  showPiano({pedal_supported:false,release_triggers_supported:false,available:false,render_profile:profile,error_code:'RENDER_SERVICE_UNAVAILABLE',semantic_generation:{configuration:'configured',reason_code:null}});
  expect(await screen.findByText(/自然语言服务已在本地配置/)).toHaveTextContent('未验证远端可用性');expect(screen.getByText(/钢琴音源暂不可用/)).toHaveTextContent('RENDER_SERVICE_UNAVAILABLE');
  fireEvent.click(screen.getByRole('radio',{name:'自然语言伴奏'}));expect(screen.getByRole('button',{name:'按描述生成 A/B 试听'})).toBeDisabled();noWrites();
 });
 it.each([undefined,{configuration:'unknown' as const,reason_code:null}])('treats missing or unknown configuration as unknown without disabling the rules path (%j)',async(semantic_generation)=>{
  showPiano({pedal_supported:false,release_triggers_supported:false,available:true,render_profile:profile,...(semantic_generation?{semantic_generation}:{})});
  expect(await screen.findByText(/暂不能确认自然语言服务的本地配置/)).toBeInTheDocument();await waitFor(()=>expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeEnabled());noWrites();
 });
 it('treats capability read failure as unknown configuration rather than not configured',async()=>{
  vi.mocked(piano.readPianoCapability).mockRejectedValue(new ApiError('offline','API_UNAVAILABLE',true,0));
  mount(<PianoPanel projectId={P} branchId={B} revisionId={R} arrangement={pianoScore()} selection={null} dirty={false} rootReady onSaved={vi.fn()} classicalSource={source}/>);
  expect(await screen.findByText(/无法读取钢琴音源状态/)).toBeInTheDocument();expect(screen.getByText(/暂不能确认自然语言服务的本地配置/)).toBeInTheDocument();expect(screen.queryByText(/自然语言服务尚未配置/)).not.toBeInTheDocument();noWrites();
 });
 it('does not gate an already-rendered current candidate approval on model configuration',async()=>{
  window.history.replaceState({},'','/?piano_preview='+T);vi.mocked(piano.readPianoPreview).mockResolvedValue({replayed:false,thread_id:T,base_revision_id:R,phase:'waiting_piano_approval',candidate_content_hash:'c'.repeat(64)});
  showPiano({pedal_supported:false,release_triggers_supported:false,available:true,render_profile:profile,semantic_generation:{configuration:'not_configured',reason_code:'MODEL_NOT_CONFIGURED'}});
  expect(await screen.findByRole('checkbox',{name:'我已试听，确认保留这条伴奏'})).toBeEnabled();noWrites();
 });
 it('keeps a candidate on the opened old base unapprovable when the branch head has advanced',async()=>{
  window.history.replaceState({},'','/?piano_preview='+T);vi.mocked(piano.readPianoPreview).mockResolvedValue({replayed:false,thread_id:T,base_revision_id:R,phase:'waiting_piano_approval',candidate_content_hash:'c'.repeat(64)});
  showPiano({pedal_supported:false,release_triggers_supported:false,available:true,render_profile:profile},OLD);
  expect(await screen.findByRole('checkbox',{name:'我已试听，确认保留这条伴奏'})).toBeDisabled();expect(screen.getByText(/当前打开的保存版本已不是分支最新版/)).toBeInTheDocument();
  expect(screen.getByRole('link',{name:'打开最新版本'})).toHaveAttribute('href',`/projects/${P}/studio/${OLD}`);noWrites();
 });
});

it('does not transfer listened confirmation to another candidate on the same revision',async()=>{
 const second='piano-'+ 'b'.repeat(32);let release:((value:Awaited<ReturnType<typeof piano.readPianoPreview>>)=>void)|undefined;
 window.history.replaceState({},'','/?piano_preview='+T);
 vi.mocked(piano.readPianoPreview).mockImplementation(async(_p,thread)=>thread===T?{replayed:false,thread_id:T,base_revision_id:R,phase:'waiting_piano_approval',candidate_content_hash:'c'.repeat(64)}:await new Promise(resolve=>{release=resolve;}));
 showPiano({pedal_supported:false,release_triggers_supported:false,available:true,render_profile:profile});
 const confirmation=await screen.findByRole('checkbox',{name:/我已试听/});await waitFor(()=>expect(confirmation).toBeEnabled());fireEvent.click(confirmation);
 expect(screen.getByRole('button',{name:'保留这条伴奏'})).toBeEnabled();
 act(()=>navigateHref('/?piano_preview='+second));await waitFor(()=>expect(release).toBeDefined());
 const oldButton=screen.queryByRole('button',{name:'保留这条伴奏'});expect(!oldButton||(oldButton as HTMLButtonElement).disabled).toBe(true);
 await act(async()=>release!({replayed:false,thread_id:second,base_revision_id:R,phase:'waiting_piano_approval',candidate_content_hash:'d'.repeat(64)}));
 expect(await screen.findByRole('checkbox',{name:/我已试听/})).not.toBeChecked();expect(screen.getByRole('button',{name:'保留这条伴奏'})).toBeDisabled();noWrites();
});

it.each([false,true])('ignores old A save in a different or remounted editor (reopen A: %s)',async(reopen)=>{
 const secondProject='55555555-5555-4555-8555-555555555555',secondRevision='66666666-6666-4666-8666-666666666666';
 const aPath=`/projects/${P}/studio/${R}`,bPath=`/projects/${secondProject}/studio/${secondRevision}`;
 let release:((value:Awaited<ReturnType<typeof studioApi.commitCommandBatch>>)=>void)|undefined;
 window.history.replaceState({},'',aPath);
 vi.mocked(projects.readProject).mockImplementation(async id=>({...workspace(),project_id:id,name:id===P?'作品A':'作品B',head_revision_id:id===P?R:secondRevision}));
 vi.mocked(projects.readRevisionStudio).mockImplementation(async(id,revision)=>({...saved(),project_id:id,revision_id:revision,arrangement_ir:eqBase()}));
 vi.mocked(studioApi.commitCommandBatch).mockReturnValue(new Promise(resolve=>{release=resolve;}));
 render(<App/>);await screen.findByRole('heading',{name:'作品A'});fireEvent.click(screen.getByRole('button',{name:'混音'}));
 const aGain=screen.getByLabelText('Piano 音量');fireEvent.change(aGain,{target:{value:'-4'}});fireEvent.pointerUp(aGain);fireEvent.click(screen.getByRole('button',{name:'保存新版本'}));
 await waitFor(()=>expect(studioApi.commitCommandBatch).toHaveBeenCalledTimes(1));
 act(()=>navigateHref(bPath));fireEvent.click(screen.getByRole('button',{name:'放弃草稿并离开'}));
 await screen.findByRole('heading',{name:'作品B'});
 if(reopen){act(()=>navigateHref(aPath));await screen.findByRole('heading',{name:'作品A'});}
 fireEvent.click(screen.getByRole('button',{name:'混音'}));
 const bGain=screen.getByLabelText('Piano 音量');fireEvent.change(bGain,{target:{value:'-8'}});fireEvent.pointerUp(bGain);
 const bLocation=window.location.href;expect(screen.getByText('1 个未保存修改')).toBeInTheDocument();
 await act(async()=>release!({branch_id:B,revision_id:OLD,content_hash:'a'.repeat(64),actual_change_impact:'L0',render_state:'dirty',replayed:false}));
 expect(window.location.href).toBe(bLocation);expect(screen.getByRole('heading',{name:reopen?'作品A':'作品B'})).toBeInTheDocument();
 expect(screen.getByLabelText('Piano 音量')).toHaveValue('-8');expect(screen.getByText('1 个未保存修改')).toBeInTheDocument();
 fireEvent.click(screen.getByRole('link',{name:'作品'}));expect(screen.getByRole('alertdialog')).toBeVisible();fireEvent.click(screen.getByText('留在此页'));
 expect(window.location.pathname).toBe(reopen?aPath:bPath);expect(studioApi.commitCommandBatch).toHaveBeenCalledTimes(1);expect(piano.startPianoPreview).not.toHaveBeenCalled();
});

it('retains a newer same-page Draft when an earlier saved snapshot completes',async()=>{
 const path=`/projects/${P}/studio/${R}`;let release:((value:Awaited<ReturnType<typeof studioApi.commitCommandBatch>>)=>void)|undefined;
 window.history.replaceState({},'',path);vi.mocked(projects.readProject).mockResolvedValue(workspace());
 vi.mocked(projects.readRevisionStudio).mockResolvedValue({...saved(),arrangement_ir:eqBase()});
 vi.mocked(studioApi.commitCommandBatch).mockReturnValue(new Promise(resolve=>{release=resolve;}));
 render(<App/>);await screen.findByRole('heading',{name:'合同试听作品'});fireEvent.click(screen.getByRole('button',{name:'混音'}));
 let gain=screen.getByLabelText('Piano 音量');fireEvent.change(gain,{target:{value:'-4'}});fireEvent.pointerUp(gain);fireEvent.click(screen.getByRole('button',{name:'保存新版本'}));
 await waitFor(()=>expect(studioApi.commitCommandBatch).toHaveBeenCalledTimes(1));fireEvent.click(screen.getByRole('button',{name:'撤销'}));
 gain=screen.getByLabelText('Piano 音量');fireEvent.change(gain,{target:{value:'-8'}});fireEvent.pointerUp(gain);const location=window.location.href;
 await act(async()=>release!({branch_id:B,revision_id:OLD,content_hash:'a'.repeat(64),actual_change_impact:'L0',render_state:'dirty',replayed:false}));
 expect(window.location.href).toBe(location);expect(screen.getByLabelText('Piano 音量')).toHaveValue('-8');expect(screen.getByText('1 个未保存修改')).toBeInTheDocument();
 expect(screen.getByText(/分支已更新到/)).toHaveTextContent(OLD);fireEvent.click(screen.getByRole('link',{name:'作品'}));expect(screen.getByRole('alertdialog')).toBeVisible();
});

it.each(['success','failure'] as const)('keeps normal save ownership behavior for %s',async(outcome)=>{
 const path=`/projects/${P}/studio/${R}`;let release:((value:Awaited<ReturnType<typeof studioApi.commitCommandBatch>>)=>void)|undefined;let fail:((error:Error)=>void)|undefined;let savedResult=false;
 window.history.replaceState({},'',path);vi.mocked(projects.readProject).mockImplementation(async()=>({...workspace(),head_revision_id:savedResult?OLD:R}));
 vi.mocked(projects.readRevisionStudio).mockImplementation(async(_id,revision)=>({...saved(),revision_id:revision,arrangement_ir:eqBase()}));
 vi.mocked(studioApi.commitCommandBatch).mockReturnValue(new Promise((resolve,reject)=>{release=resolve;fail=reject;}));
 render(<App/>);await screen.findByRole('heading',{name:'合同试听作品'});fireEvent.click(screen.getByRole('button',{name:'混音'}));
 const gain=screen.getByLabelText('Piano 音量');fireEvent.change(gain,{target:{value:'-4'}});fireEvent.pointerUp(gain);fireEvent.click(screen.getByRole('button',{name:'保存新版本'}));
 await waitFor(()=>expect(studioApi.commitCommandBatch).toHaveBeenCalledTimes(1));
 if(outcome==='success'){savedResult=true;await act(async()=>release!({branch_id:B,revision_id:OLD,content_hash:'a'.repeat(64),actual_change_impact:'L0',render_state:'dirty',replayed:false}));
  await waitFor(()=>expect(window.location.pathname).toBe(`/projects/${P}/studio/${OLD}`));await waitFor(()=>expect(screen.getByText('0 个未保存修改')).toBeInTheDocument());expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
 }else{await act(async()=>fail!(new Error('offline')));expect(window.location.pathname).toBe(path);expect(screen.getByText('保存失败，草稿仍保留')).toBeInTheDocument();
  expect(screen.getByLabelText('Piano 音量')).toHaveValue('-4');expect(screen.getByText('1 个未保存修改')).toBeInTheDocument();fireEvent.click(screen.getByRole('link',{name:'作品'}));expect(screen.getByRole('alertdialog')).toBeVisible();}
 expect(studioApi.commitCommandBatch).toHaveBeenCalledTimes(1);expect(piano.startPianoPreview).not.toHaveBeenCalled();
});

it.each(['undo','read'] as const)('retains a new Draft while committed Undo waits for %s',async(stage)=>{
 const path=`/projects/${P}/studio/${R}`;let releaseUndo:((value:Awaited<ReturnType<typeof studioApi.undoCommittedRevision>>)=>void)|undefined;let releaseRead:((value:RevisionStudio)=>void)|undefined;
 window.history.replaceState({},'',path);vi.mocked(projects.readProject).mockResolvedValue(workspace());
 vi.mocked(projects.readRevisionStudio).mockImplementation(async(_id,revision)=>revision===OLD&&stage==='read'?await new Promise(resolve=>{releaseRead=resolve;}):{...saved(),revision_id:revision,arrangement_ir:eqBase()});
 vi.mocked(studioApi.undoCommittedRevision).mockImplementation(async()=>stage==='undo'?await new Promise(resolve=>{releaseUndo=resolve;}):{branch_id:B,revision_id:OLD,undone_revision_id:R,content_hash:'a'.repeat(64),actual_change_impact:'L0',render_state:'dirty',replayed:false});
 render(<App/>);await screen.findByRole('heading',{name:'合同试听作品'});fireEvent.click(screen.getByRole('button',{name:'混音'}));
 fireEvent.click(screen.getByRole('button',{name:'撤回已保存修改'}));await waitFor(()=>expect(studioApi.undoCommittedRevision).toHaveBeenCalledTimes(1));
 if(stage==='read')await waitFor(()=>expect(releaseRead).toBeDefined());
 const gain=screen.getByLabelText('Piano 音量');fireEvent.change(gain,{target:{value:'-8'}});fireEvent.pointerUp(gain);const location=window.location.href;
 if(stage==='undo')await act(async()=>releaseUndo!({branch_id:B,revision_id:OLD,undone_revision_id:R,content_hash:'a'.repeat(64),actual_change_impact:'L0',render_state:'dirty',replayed:false}));
 else await act(async()=>releaseRead!({...saved(),revision_id:OLD,arrangement_ir:eqBase()}));
 expect(window.location.href).toBe(location);expect(screen.getByLabelText('Piano 音量')).toHaveValue('-8');expect(screen.getByText('1 个未保存修改')).toBeInTheDocument();
 expect(screen.getByText(/分支已更新到/)).toHaveTextContent(OLD);expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
 fireEvent.click(screen.getByRole('link',{name:'作品'}));expect(screen.getByRole('alertdialog')).toBeVisible();
 expect(studioApi.commitCommandBatch).not.toHaveBeenCalled();expect(studioApi.undoCommittedRevision).toHaveBeenCalledTimes(1);expect(piano.startPianoPreview).not.toHaveBeenCalled();
});
