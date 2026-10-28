import {cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {ArrangementTimeline} from './ArrangementTimeline';
import type {TimelineProjection} from './timelineProjection';
afterEach(()=>cleanup());
it('moves clips with Alt arrows using the same bounded snap as pointer moves',()=>{
  const move=vi.fn();
  const projection={totalBars:8,ticksPerBar:1920,widthPixels:800,sections:[],tracks:[{trackId:'t',name:'Piano',clips:[{clipId:'c',startTick:0,endTick:960,startPixels:0,widthPixels:50}]}]} as unknown as TimelineProjection;
  render(<ArrangementTimeline projection={projection} currentTime={0} onMoveClip={move}/>);
  const clip=screen.getByRole('button',{name:'Clip Piano'});
  fireEvent.keyDown(clip,{key:'ArrowRight'});expect(move).not.toHaveBeenCalled();
  fireEvent.keyDown(clip,{key:'ArrowLeft',altKey:true});expect(move).toHaveBeenLastCalledWith('t','c',0);
  fireEvent.keyDown(clip,{key:'ArrowRight',altKey:true});expect(move).toHaveBeenLastCalledWith('t','c',120);
  fireEvent.keyDown(clip,{key:'ArrowRight',altKey:true,shiftKey:true});expect(move).toHaveBeenLastCalledWith('t','c',1920);
});
