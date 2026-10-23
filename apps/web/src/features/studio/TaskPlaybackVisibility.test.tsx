import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import {PianoPanel} from './PianoPanel';
import {EditPreviewCard} from './EditPreviewCard';
import {StudioInspector} from './StudioInspector';
import {pianoScore} from './pianoTestFixture';
import * as api from './pianoApi';
vi.mock('./pianoApi',()=>({readPianoCapability:vi.fn(),readPianoPreview:vi.fn(),startPianoPreview:vi.fn(),decidePianoPreview:vi.fn(),cancelPianoPreview:vi.fn()}));
const thread='piano-'+ 'a'.repeat(32);
beforeEach(()=>{
 window.history.replaceState({},'',`/?piano_preview=${thread}`);
 vi.mocked(api.readPianoCapability).mockResolvedValue({available:false,pedal_supported:false,release_triggers_supported:false});
 vi.mocked(api.readPianoPreview).mockResolvedValue({replayed:false,thread_id:thread,base_revision_id:'r',phase:'waiting_piano_approval',candidate_content_hash:'c'.repeat(64),baseline_artifact_id:'11111111-1111-4111-8111-111111111111',piano_artifact_id:'22222222-2222-4222-8222-222222222222'});
 vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(function(this:HTMLMediaElement){Object.defineProperty(this,'paused',{configurable:true,value:true});});
 vi.spyOn(HTMLMediaElement.prototype,'play').mockImplementation(async function(this:HTMLMediaElement){Object.defineProperty(this,'paused',{configurable:true,value:false});});
});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.resetAllMocks();window.history.replaceState({},'','/');});
async function playing(){
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
 render(<QueryClientProvider client={client}><StudioInspector status="待确认"><PianoPanel projectId="p" branchId="b" revisionId="r" headRevisionId="r" arrangement={pianoScore()} selection={null} dirty={false} rootReady onSaved={vi.fn()}/></StudioInspector></QueryClientProvider>);
 const details=screen.getByText('创作任务').closest('details')!;details.open=true;fireEvent(details,new Event('toggle'));
 const audio=await screen.findByLabelText('钢琴 A/B 试听') as HTMLAudioElement;
 Object.defineProperties(audio,{paused:{configurable:true,value:false},readyState:{configurable:true,value:4},duration:{configurable:true,value:30}});audio.currentTime=7.5;
 return {details,audio};
}
it('pauses hidden candidate audio on collapse without losing position or candidate',async()=>{
 const {details,audio}=await playing();details.open=false;fireEvent(details,new Event('toggle'));
 expect(audio.paused).toBe(true);expect(audio.currentTime).toBe(7.5);expect(audio).toBeInTheDocument();
 expect(api.startPianoPreview).not.toHaveBeenCalled();expect(api.decidePianoPreview).not.toHaveBeenCalled();
});
it('does not resume a switching candidate when metadata arrives after task collapse',async()=>{
 const {details,audio}=await playing();fireEvent.click(screen.getByRole('button',{name:'B · 钢琴表达'}));
 vi.mocked(audio.play).mockClear();details.open=false;fireEvent(details,new Event('toggle'));fireEvent.loadedMetadata(audio);
 expect(audio.play).not.toHaveBeenCalled();expect(audio.paused).toBe(true);expect(audio.currentTime).toBe(7.5);
});

it('also pauses edit-preview audio on collapse and blocks a late hidden play event',()=>{
 const decide=vi.fn();
 const {container}=render(<StudioInspector status="待确认"><EditPreviewCard preview={{preview_id:'preview-1',candidate_snapshot_id:'candidate-1',candidate_content_hash:'a'.repeat(64),preview_artifact_id:'11111111-1111-4111-8111-111111111111',preview_availability:'available',actual_change_impact:2,structural_diff:[]}} busy={false} rootReady onDecision={decide}/></StudioInspector>);
 const details=screen.getByText('创作任务').closest('details')!;details.open=true;fireEvent(details,new Event('toggle'));
 const audio=container.querySelector('audio')!;Object.defineProperty(audio,'paused',{configurable:true,value:false});audio.currentTime=5;
 details.open=false;fireEvent(details,new Event('toggle'));expect(audio.paused).toBe(true);expect(audio.currentTime).toBe(5);
 Object.defineProperty(audio,'paused',{configurable:true,value:false});fireEvent.play(audio);expect(audio.paused).toBe(true);expect(decide).not.toHaveBeenCalled();
});
