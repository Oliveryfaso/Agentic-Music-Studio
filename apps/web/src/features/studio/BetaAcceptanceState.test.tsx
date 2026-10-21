import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,beforeEach,expect,it,vi} from 'vitest';
import {App} from '../../app/App';
import type {ClassicalSourceData,PianoPreviewData,ProjectWorkspace,RevisionExportProjection,RevisionStudio} from '../../shared/openapi';
import {pianoScore} from './pianoTestFixture';
import {PianoRoll} from './PianoRoll';
import * as piano from './pianoApi';
import * as projects from '../projects/projectApi';
import * as studio from './studioApi';
import * as classical from '../projects/classicalApi';
import * as exports from '../exports/exportApi';
import {ExportPage} from '../exports/ExportPage';

vi.mock('./pianoApi',()=>({readPianoCapability:vi.fn(),readPianoPreview:vi.fn(),startPianoPreview:vi.fn(),decidePianoPreview:vi.fn(),cancelPianoPreview:vi.fn()}));
vi.mock('../projects/projectApi',()=>({readProject:vi.fn(),readRevisionStudio:vi.fn()}));
vi.mock('./studioApi',()=>({listSoundCatalog:vi.fn(),commitCommandBatch:vi.fn(),undoCommittedRevision:vi.fn()}));
vi.mock('../projects/classicalApi',()=>({readClassicalSource:vi.fn()}));
vi.mock('../exports/exportApi',()=>({readRevisionExport:vi.fn(),startRevisionExport:vi.fn(),cancelRevisionExport:vi.fn()}));
// Observe the score passed to the real canvas component, without substituting its UI.
vi.mock('./PianoRoll',async(importOriginal)=>{const actual=await importOriginal<typeof import('./PianoRoll')>();return {...actual,PianoRoll:vi.fn(actual.PianoRoll)};});

const P='11111111-1111-4111-8111-111111111111',B='22222222-2222-4222-8222-222222222222';
const R0='00000000-0000-4000-8000-000000000000',R1='11111111-0000-4000-8000-000000000001',R2='22222222-0000-4000-8000-000000000002',U='33333333-0000-4000-8000-000000000003';
const A1='aaaaaaaa-0000-4000-8000-000000000001',A2='aaaaaaaa-0000-4000-8000-000000000002';
const profile={schema_version:'render-profile.v1',engine_version:'motif-forge-audio-engine.v2',instrument_pack_id:'freepats:upright-kw-small',instrument_pack_version:'2019-07-03.motif1',manifest_sha256:'264fdbf12f3c7273a0d15fbcb86abed04b73e08b6fc4faf482eaf41040a0b813'} as const;

function snapshot(id:string,parent:string|null,pitches:number[],artifact:string|null):RevisionStudio{
 const arrangement=pianoScore();arrangement.project_id=P;arrangement.provenance=[{kind:'asset',ref:'score:c02-la-candeur-a8.v1'}];
 arrangement.sections[0]!.end_tick=8*1920;arrangement.tracks[0]!.clips[0]!.duration_tick=9*1920;
 const added=structuredClone(arrangement.tracks[0]!);added.track_id='added';added.name='第二钢琴';added.role='bass';
 const clip=added.clips[0]!;if(clip.clip_type==='note')clip.notes=pitches.map((pitch,index)=>({note_id:'bass-'+index,pitch,start_tick:4*1920+index*480,duration_tick:180,velocity:54,articulation:'normal',cents:0}));
 arrangement.tracks.push(added);
 return {project_id:P,revision_id:id,parent_revision_id:parent,source_run_id:null,reason_code:'TEST_FIXTURE',author_kind:'human',created_by:'test:fixture',created_at:'2026-10-21T00:00:00Z',arrangement_ir:arrangement,bundle_id:null,delivery_assets:artifact?[{artifact_id:artifact,availability:'available',quality_profile:'candidate-preview.v1',media_type:'audio/mpeg',byte_size:1024,duration_milliseconds:19000}]:[]};
}
function workspace(head:string):ProjectWorkspace{return {project_id:P,name:'独立多轮验收 fixture',status:'active',updated_at:'2026-10-21T00:00:00Z',active_branch_id:B,head_revision_id:head,revisions:[],runs:[],recoverable_run:null,storage_root_status:'ready',recoverable_piano_preview:null,piano_preview_recovery:{status:'ready',pending_count:0,selection_rule:'newest_created',reason_code:null}};}
function source():ClassicalSourceData{return {project_id:P,revision_id:R0,source_branch_id:B,source:{score_id:'c02-la-candeur-a8.v1',title:'测试曲目',composer:'fixture',digital_editor:'fixture',conversion:'fixture',license:'fixture',page_url:'https://example.invalid/fixture',source_url:'https://example.invalid/fixture.xml',musicxml_sha256:'a'.repeat(64),original_sha256:'b'.repeat(64),measure_count:8,note_count:2,beats:4,bpm:120,tonic:'C',default_chords:Array(8).fill('C')},import_report:{measure_count:8,note_count:2,note_map:[],rest_tail_bars:1,beats:4,bpm:120,tonic:'C'}};}

beforeEach(()=>{
 sessionStorage.clear();vi.stubGlobal('fetch',vi.fn(()=>Promise.reject(new Error('Unexpected real network in fixture test'))));
 vi.mocked(piano.readPianoCapability).mockResolvedValue({available:true,pedal_supported:false,release_triggers_supported:false,render_profile:profile,semantic_generation:{configuration:'configured',reason_code:null}});
 vi.mocked(studio.listSoundCatalog).mockResolvedValue([]);vi.mocked(classical.readClassicalSource).mockResolvedValue(source());
 vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});
});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.resetAllMocks();vi.unstubAllGlobals();sessionStorage.clear();window.history.replaceState({},'','/');});

async function expectVersion(id:string,pitches:number[],artifact:string|null){
 await waitFor(()=>expect(screen.getByLabelText('Studio 工作栏')).toHaveTextContent('保存版本 · '+id.slice(0,8)));
 expect(window.location.pathname).toBe(`/projects/${P}/studio/${id}`);expect(window.location.search).toBe('');
 expect(screen.getByRole('link',{name:'查看导出'})).toHaveAttribute('href',`/projects/${P}/exports/${id}`);
 expect(screen.getByText('0 个未保存修改')).toBeInTheDocument();
 fireEvent.click(screen.getAllByRole('button',{name:'Clip 第二钢琴'})[0]!);
 fireEvent.click(screen.getByRole('tab',{name:'钢琴卷帘'}));
 const clip=vi.mocked(PianoRoll).mock.calls.at(-1)![0].clip;
 expect(clip.notes.map(note=>note.pitch)).toEqual(pitches);
 const saved=document.querySelector('.studio-transport audio');
 if(artifact)expect(saved).toHaveAttribute('src',`/api/v1/audio-artifacts/${artifact}/content`);
 else {expect(saved).toBeNull();expect(screen.getByText('这个版本还没有可试听的 MP3。请在导出页查看处理进度。')).toBeInTheDocument();}
}

it('keeps two confirmed edit rounds and their Undo result aligned across route, score, saved audio and export',async()=>{
 const versions=new Map([[R0,snapshot(R0,null,[48,52],null)],[R1,snapshot(R1,R0,[48],A1)],[R2,snapshot(R2,R1,[55],A2)],[U,snapshot(U,R2,[48],null)]]);
 let head=R0,round=0;const candidates=new Map<string,PianoPreviewData>();
 vi.mocked(projects.readProject).mockImplementation(async()=>workspace(head));
 vi.mocked(projects.readRevisionStudio).mockImplementation(async(project,id)=>{expect(project).toBe(P);const value=versions.get(id);if(!value)throw new Error('Unknown fixture revision '+id);return structuredClone(value);});
 vi.mocked(piano.startPianoPreview).mockImplementation(async(project,body)=>{
  expect(project).toBe(P);expect(body.base_revision_id).toBe(head);round++;
  const value:PianoPreviewData={replayed:false,thread_id:'round-'+round,base_revision_id:head,phase:'waiting_piano_approval',candidate_content_hash:String(round).repeat(64)};
  candidates.set(value.thread_id,value);return value;
 });
 vi.mocked(piano.readPianoPreview).mockImplementation(async(_project,thread)=>{const value=candidates.get(thread);if(!value)throw new Error('Unknown fixture thread');return value;});
 vi.mocked(piano.decidePianoPreview).mockImplementation(async(project,thread,decision)=>{
  expect(project).toBe(P);expect(decision.action).toBe('approve');const candidate=candidates.get(thread);expect(candidate).toBeDefined();if(!candidate)throw new Error('Unknown decision thread');expect(decision.expected_candidate_content_hash).toBe(candidate.candidate_content_hash);
  head=thread==='round-1'?R1:R2;return {...candidate,phase:'completed',revision_id:head};
 });
 vi.mocked(studio.undoCommittedRevision).mockImplementation(async(project,body)=>{
  expect(project).toBe(P);expect(body).toEqual({branch_id:B,base_revision_id:R2,target_revision_id:R2});head=U;
  return {revision_id:U,branch_id:B,undone_revision_id:R2,content_hash:'f'.repeat(64),actual_change_impact:'L2',render_state:'dirty',replayed:false};
 });
 window.history.replaceState({},'',`/projects/${P}/studio/${R0}`);render(<App/>);
 for(const [index,id,pitches,artifact] of [[1,R1,[48],A1],[2,R2,[55],A2]] as const){
  const generate=await screen.findByRole('button',{name:'按描述生成 A/B 试听'});await waitFor(()=>expect(generate).toBeEnabled());
  fireEvent.change(screen.getByLabelText('伴奏描述'),{target:{value:'第5–8小节测试修改 '+index}});fireEvent.click(generate);
  const confirm=await screen.findByRole('checkbox',{name:'我已试听，确认保留这次修改'});
  expect(confirm).not.toBeChecked();expect(screen.getByRole('button',{name:'保留这次修改'})).toBeDisabled();
  fireEvent.click(confirm);fireEvent.click(screen.getByRole('button',{name:'保留这次修改'}));
  await expectVersion(id,[...pitches],artifact);
 }
 expect(piano.startPianoPreview).toHaveBeenCalledTimes(2);expect(piano.decidePianoPreview).toHaveBeenCalledTimes(2);
 expect(vi.mocked(piano.startPianoPreview).mock.calls.map(call=>call[1].base_revision_id)).toEqual([R0,R1]);
 fireEvent.click(screen.getByRole('button',{name:'撤回已保存修改'}));await expectVersion(U,[48],null);
 expect(studio.undoCommittedRevision).toHaveBeenCalledOnce();expect(piano.startPianoPreview).toHaveBeenCalledTimes(2);
 // A further edit must use the new immutable Undo revision, not its restored ancestor ID.
 const generate=screen.getByRole('button',{name:'按描述生成 A/B 试听'});await waitFor(()=>expect(generate).toBeEnabled());fireEvent.click(generate);
 await waitFor(()=>expect(piano.startPianoPreview).toHaveBeenCalledTimes(3));
 expect(vi.mocked(piano.startPianoPreview).mock.calls[2]![1]).toEqual(expect.objectContaining({base_revision_id:U,semantic:expect.objectContaining({mode:'modify',target_track_id:'added',start_bar:5,end_bar:8})}));
 expect(studio.commitCommandBatch).not.toHaveBeenCalled();expect(piano.cancelPianoPreview).not.toHaveBeenCalled();
});

it('reopens the same fixed export plan with revision-bound download and return links without generating again',async()=>{
 const plan='c'.repeat(64),artifact=A2;
 const value:RevisionExportProjection={project_id:P,revision_id:R2,source_run_id:null,status:'ready',error_code:null,bundle:null,plan_hash:plan,export_thread_id:'export-existing',steps:[],files:[{file_id:'audio:'+artifact,filename:'master.wav',category:'master',media_type:'audio/wav',byte_size:1024,availability:'available',checksum:'d'.repeat(64),content_url:`/api/v1/audio-artifacts/${artifact}/content`,artifact_id:artifact}]};
 vi.mocked(exports.readRevisionExport).mockResolvedValue(value);
 window.history.replaceState({},'',`/projects/${P}/exports/${R2}?export_plan=${plan}`);
 function mount(){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><ExportPage projectId={P} revisionId={R2}/></QueryClientProvider>);}
 for(let visit=0;visit<2;visit++){
  const view=mount();const download=await screen.findByRole('link',{name:'下载 Master WAV'});
  expect(download).toHaveAttribute('href',`/api/v1/audio-artifacts/${artifact}/content`);expect(download).toHaveAttribute('download','master.wav');
  expect(screen.getByRole('link',{name:'返回 Studio'})).toHaveAttribute('href',`/projects/${P}/studio/${R2}`);
  expect(window.location.search).toBe('?export_plan='+plan);view.unmount();
 }
 expect(exports.readRevisionExport).toHaveBeenCalledTimes(2);expect(vi.mocked(exports.readRevisionExport).mock.calls.every(call=>JSON.stringify(call)===JSON.stringify([P,R2,plan]))).toBe(true);
 expect(exports.startRevisionExport).not.toHaveBeenCalled();expect(exports.cancelRevisionExport).not.toHaveBeenCalled();
});
