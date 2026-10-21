import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ProjectHomePage} from './ProjectHomePage';
import type {ProjectSummary} from '../../shared/openapi';

afterEach(()=>{cleanup();vi.unstubAllGlobals();window.history.replaceState({},'','/');});

it('opens a saved project head from Home before its first playable MP3 exists',async()=>{
 const saved:ProjectSummary={project_id:'11111111-1111-4111-8111-111111111111',name:'已保存的审核谱',status:'active',updated_at:'2026-10-21T01:00:00Z',active_branch_id:'22222222-2222-4222-8222-222222222222',head_revision_id:'33333333-3333-4333-8333-333333333333',latest_run:null,has_playable_revision:false};
 const requests:Array<{path:string;method:string}>=[];
 vi.stubGlobal('fetch',vi.fn(async(input:RequestInfo|URL,init?:RequestInit)=>{
  const path=String(input);requests.push({path,method:init?.method??'GET'});
  if(path==='/api/v1/projects?limit=50')return Response.json({data:[saved]});
  throw new Error('Unexpected test request '+path);
 }));
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}><ProjectHomePage/></QueryClientProvider>);
 await screen.findByRole('heading',{name:saved.name});
 const open=screen.getByRole('button',{name:`打开 ${saved.name} 最新版本`});
 expect(open).toBeEnabled();fireEvent.click(open);
 expect(window.location.pathname).toBe(`/projects/${saved.project_id}/studio/${saved.head_revision_id}`);
 expect(window.location.search).toBe('');
 expect(requests.every(request=>request.method==='GET')).toBe(true);
});
