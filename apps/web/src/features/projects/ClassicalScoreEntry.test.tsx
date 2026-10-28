import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ClassicalScoreEntry} from './ClassicalScoreEntry';
import * as api from './classicalApi';
vi.mock('./classicalApi',()=>({listClassicalScores:vi.fn(),importClassicalScore:vi.fn()}));
afterEach(()=>{cleanup();vi.resetAllMocks();window.history.replaceState({},'','/');window.sessionStorage.clear();});
it('reviews the exact source conversion before import and opens its saved project',async()=>{
  vi.mocked(api.listClassicalScores).mockResolvedValue([{score_id:'mutopia-528-melody.v1',title:'欢乐颂 · 16 小节旋律',license:'Public Domain',composer:'Beethoven',digital_editor:'Mutopia 528',page_url:'https://www.mutopiaproject.org/cgibin/piece-info.cgi?id=528',conversion:'仅提取旋律，省略另外三个声部与slur。',measure_count:16,note_count:62}] as never);
  vi.mocked(api.importClassicalScore).mockResolvedValue({project_id:'11111111-1111-4111-8111-111111111111',revision_id:'22222222-2222-4222-8222-222222222222'} as never);
  render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><ClassicalScoreEntry/></QueryClientProvider>);
  expect(api.listClassicalScores).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'查看经典谱'}));
  await screen.findByRole('radio',{name:/欢乐颂 · 16 小节旋律/});
  const submit=screen.getByRole('button',{name:'导入这份旋律谱'});expect(submit).toBeDisabled();
  expect(screen.getByText(/省略另外三个声部/)).toBeInTheDocument();
  fireEvent.click(screen.getByLabelText('我已了解来源与转换范围，保留原谱并创建改编副本'));
  fireEvent.click(submit);
  await waitFor(()=>expect(api.importClassicalScore).toHaveBeenCalledWith('mutopia-528-melody.v1',expect.any(String)));
  await waitFor(()=>expect(window.location.pathname).toContain('/studio/22222222-2222-4222-8222-222222222222'));
});

function entries(){return ['c01-minuet-g-a16.v1','c02-la-candeur-a8.v1','j01-bethena-a-first8.v1'].map((score_id,i)=>({score_id,title:['小步舞曲','坦诉','Bethena'][i]!,composer:'Composer',digital_editor:'Mutopia',license:'Public Domain',source_url:'https://example.test/source',page_url:'https://example.test/score',original_sha256:'a'.repeat(64),musicxml_sha256:String(i+1).repeat(64),conversion:'只选旋律，不还原完整原谱',measure_count:i===0?16:8,note_count:20,default_chords:Array(i===0?16:8).fill(i===1?'C':'G'),beats:i===1?4:3,bpm:100,tonic:i===1?'C':'G'}));}
function renderEntry(client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})){return render(<QueryClientProvider client={client}><ClassicalScoreEntry/></QueryClientProvider>);}
async function openScores(){fireEvent.click(screen.getByRole('button',{name:'查看经典谱'}));await screen.findByRole('radio',{name:/坦诉/});}
it('selects the exact reviewed score and requires new consent after switching',async()=>{
 vi.mocked(api.listClassicalScores).mockResolvedValue(entries());vi.mocked(api.importClassicalScore).mockResolvedValue({project_id:'p',revision_id:'r'} as never);renderEntry();await openScores();
 fireEvent.click(screen.getByLabelText(/我已了解.*来源/));fireEvent.click(screen.getByRole('radio',{name:/坦诉/}));
 expect(screen.getByRole('button',{name:'导入这份旋律谱'})).toBeDisabled();
 fireEvent.click(screen.getByLabelText(/我已了解.*来源/));fireEvent.click(screen.getByRole('button',{name:'导入这份旋律谱'}));
 await waitFor(()=>expect(api.importClassicalScore).toHaveBeenCalledWith('c02-la-candeur-a8.v1',expect.any(String)));
});
it('locks an unknown import receipt and reuses its exact score and key after remount',async()=>{
 vi.mocked(api.listClassicalScores).mockResolvedValue(entries());vi.mocked(api.importClassicalScore).mockRejectedValueOnce(new Error('Network lost')).mockResolvedValue({project_id:'p',revision_id:'r'} as never);
 const view=renderEntry();await openScores();fireEvent.click(screen.getByRole('radio',{name:/坦诉/}));fireEvent.click(screen.getByLabelText(/我已了解.*来源/));fireEvent.click(screen.getByRole('button',{name:'导入这份旋律谱'}));
 await screen.findByRole('button',{name:'重试同一次导入'});expect(screen.getByRole('radio',{name:/Bethena/})).toBeDisabled();
 const first=vi.mocked(api.importClassicalScore).mock.calls[0]!;view.unmount();renderEntry();
 fireEvent.click(await screen.findByRole('button',{name:'重试同一次导入'}));await waitFor(()=>expect(api.importClassicalScore).toHaveBeenCalledTimes(2));
 expect(vi.mocked(api.importClassicalScore).mock.calls[1]).toEqual(first);
});
it('invalidates consent when the same score identity has different review metadata',async()=>{
 const catalog=entries();vi.mocked(api.listClassicalScores).mockResolvedValue(catalog);const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});renderEntry(client);await openScores();
 fireEvent.click(screen.getByLabelText(/我已了解.*来源/));expect(screen.getByRole('button',{name:'导入这份旋律谱'})).toBeEnabled();
 client.setQueryData(['classical-scores'],catalog.map((s,i)=>i===0?{...s,beats:4}:s));
 await waitFor(()=>expect(screen.getByRole('button',{name:'导入这份旋律谱'})).toBeDisabled());expect(api.importClassicalScore).not.toHaveBeenCalled();
});

it('unlocks selection only after a known failure before persistence',async()=>{
 const {ApiError}=await import('../../shared/api');vi.mocked(api.listClassicalScores).mockResolvedValue(entries());vi.mocked(api.importClassicalScore).mockRejectedValueOnce(new ApiError('Piano unavailable','INSTRUMENT_PACK_UNAVAILABLE',true,503));renderEntry();await openScores();
 fireEvent.click(screen.getByLabelText(/我已了解.*来源/));fireEvent.click(screen.getByRole('button',{name:'导入这份旋律谱'}));
 await screen.findByText('Piano unavailable');expect(screen.getByRole('radio',{name:/坦诉/})).toBeEnabled();expect(sessionStorage.length).toBe(0);
});

it.each(['success','known failure'])('keeps another page and its import intent after a late %s',async(outcome)=>{
 let resolve!:(value:never)=>void,reject!:(error:Error)=>void;
 vi.mocked(api.listClassicalScores).mockResolvedValue(entries());
 vi.mocked(api.importClassicalScore).mockImplementation(()=>new Promise((yes,no)=>{resolve=yes;reject=no;}));
 const view=renderEntry();await openScores();fireEvent.click(screen.getByLabelText(/我已了解.*来源/));fireEvent.click(screen.getByRole('button',{name:'导入这份旋律谱'}));
 await waitFor(()=>expect(api.importClassicalScore).toHaveBeenCalledTimes(1));
 view.unmount();window.history.replaceState({},'', '/settings');
 const newer=JSON.stringify({scoreId:'another',reviewKey:'another',key:'web-classical:newer'});sessionStorage.setItem('motif:classical-import:v1',newer);
 if(outcome==='success')resolve({project_id:'old',revision_id:'old'} as never);
 else {const {ApiError}=await import('../../shared/api');reject(new ApiError('Not available','INSTRUMENT_PACK_UNAVAILABLE',true,503));}
 await new Promise(done=>setTimeout(done,20));
 expect(window.location.pathname).toBe('/settings');expect(sessionStorage.getItem('motif:classical-import:v1')).toBe(newer);
});
it('ignores an import success when the path changed before unmount',async()=>{
 let finish!:(value:never)=>void;vi.mocked(api.listClassicalScores).mockResolvedValue(entries());vi.mocked(api.importClassicalScore).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
 renderEntry();await openScores();fireEvent.click(screen.getByLabelText(/我已了解.*来源/));fireEvent.click(screen.getByRole('button',{name:'导入这份旋律谱'}));await waitFor(()=>expect(finish).toBeTypeOf('function'));
 const pending=sessionStorage.getItem('motif:classical-import:v1');window.history.replaceState({},'', '/settings');finish({project_id:'old',revision_id:'old'} as never);
 await new Promise(done=>setTimeout(done,20));expect(window.location.pathname).toBe('/settings');expect(sessionStorage.getItem('motif:classical-import:v1')).toBe(pending);
});

it('does not clear the re-entered Home intent when an older import completes',async()=>{
 let finish!:(value:never)=>void;vi.mocked(api.listClassicalScores).mockResolvedValue(entries());vi.mocked(api.importClassicalScore).mockImplementation(()=>new Promise(resolve=>{finish=resolve;}));
 const old=renderEntry();await openScores();fireEvent.click(screen.getByLabelText(/我已了解.*来源/));fireEvent.click(screen.getByRole('button',{name:'导入这份旋律谱'}));await waitFor(()=>expect(finish).toBeTypeOf('function'));
 old.unmount();renderEntry();await screen.findByRole('button',{name:'重试同一次导入'});
 const pending=sessionStorage.getItem('motif:classical-import:v1');finish({project_id:'old',revision_id:'old'} as never);
 await new Promise(done=>setTimeout(done,20));expect(window.location.pathname).toBe('/');expect(sessionStorage.getItem('motif:classical-import:v1')).toBe(pending);expect(screen.getByRole('button',{name:'重试同一次导入'})).toBeInTheDocument();expect(api.importClassicalScore).toHaveBeenCalledTimes(1);
});
