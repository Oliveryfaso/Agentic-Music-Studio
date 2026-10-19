import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ClassicalAccompanimentPanel} from './ClassicalAccompanimentPanel';
import {pianoScore} from './pianoTestFixture';
import * as sourceApi from '../projects/classicalApi';
import * as api from './pianoApi';
vi.mock('../projects/classicalApi',()=>({readClassicalSource:vi.fn()}));
vi.mock('./pianoApi',()=>({readPianoCapability:vi.fn(),readPianoPreview:vi.fn(),startPianoPreview:vi.fn(),decidePianoPreview:vi.fn(),cancelPianoPreview:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();window.history.replaceState({},'','/');});
it.each(['approve','reject'] as const)('previews a user-selected part without expression changes then %s',async(action)=>{
  vi.mocked(sourceApi.readClassicalSource).mockResolvedValue({revision_id:'original',source:{title:'欢乐颂',license:'Public Domain',page_url:'https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=528',conversion:'仅提取旋律',default_chords:Array(16).fill('G')},import_report:{measure_count:16,note_count:62}} as never);
  vi.mocked(api.readPianoCapability).mockResolvedValue({available:true,render_profile:{}} as never);
  const waiting={replayed:false,thread_id:'piano-accompaniment',phase:'waiting_piano_approval',base_revision_id:'revision',candidate_content_hash:'b'.repeat(64),baseline_artifact_id:'baseline',piano_artifact_id:'piano'} as const;
  vi.mocked(api.startPianoPreview).mockResolvedValue(waiting);
  vi.mocked(api.readPianoPreview).mockResolvedValue(waiting);
  vi.mocked(api.decidePianoPreview).mockResolvedValue({...waiting,phase:action==='approve'?'completed':'rejected',revision_id:action==='approve'?'saved':null});
  const saved=vi.fn(),arrangement=pianoScore(),before=JSON.stringify(arrangement);
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><ClassicalAccompanimentPanel projectId="project" branchId="branch" revisionId="revision" arrangement={arrangement} selection={null} dirty={false} rootReady onSaved={saved}/></QueryClientProvider>);
  await screen.findByLabelText('伴奏织体');
  fireEvent.change(screen.getByLabelText('伴奏织体'),{target:{value:'broken'}});
  fireEvent.change(screen.getByLabelText('每小节和弦'),{target:{value:'G'}});
  expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeDisabled();
  fireEvent.change(screen.getByLabelText('每小节和弦'),{target:{value:Array(16).fill('G').join(' ')}});
  await waitFor(()=>expect(screen.getByRole('button',{name:'生成 A/B 试听'})).toBeEnabled());
  fireEvent.click(screen.getByRole('button',{name:'生成 A/B 试听'}));
  const save=await screen.findByRole('button',{name:'保留这条伴奏'});expect(save).toBeDisabled();
  expect(api.startPianoPreview).toHaveBeenCalledWith('project',expect.objectContaining({base_revision_id:'revision',accompaniment:expect.objectContaining({pattern:'broken',chords:Array(16).fill('G'),velocity:54}),performance_plan:{schema_version:'performance-plan.v1',notes:[],pedal_events:[]}}),expect.any(String));
  expect(screen.getByRole('button',{name:'B · 加轨版本'})).toBeInTheDocument();
  if(action==='approve'){fireEvent.click(screen.getByLabelText('我已试听，确认保留这条伴奏'));fireEvent.click(save);await waitFor(()=>expect(saved).toHaveBeenCalledWith('saved'));}
  else{fireEvent.click(screen.getByRole('button',{name:'放弃这版'}));await screen.findByText('已放弃试听，原版本保留。');expect(saved).not.toHaveBeenCalled();}
  expect(api.decidePianoPreview).toHaveBeenCalledWith('project','piano-accompaniment',expect.objectContaining({action,expected_candidate_content_hash:'b'.repeat(64)}));
  expect(JSON.stringify(arrangement)).toBe(before);
});
