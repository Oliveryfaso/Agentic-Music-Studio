import {act,cleanup,fireEvent,render,screen} from '@testing-library/react';
import {afterEach,expect,it,vi} from 'vitest';
import {useAudioTransport} from './useAudioTransport';
import {Transport} from './Transport';

let state:ReturnType<typeof useAudioTransport>;
function Player({src='A'}:{src?:string}){
  state=useAudioTransport(21,src);
  return <Transport audioRef={state.audioRef} src={src} duration={21} currentTime={state.currentTime}
    isPlaying={state.isPlaying} mediaError={state.mediaError} onPlay={state.play} onPause={state.pause}
    onStop={state.stop} onSeek={state.seek} mediaProps={state.mediaProps}/>;
}
afterEach(()=>{cleanup();vi.restoreAllMocks();});

it('does not return to playing when an earlier play promise settles after Stop',async()=>{
  let resolve!:()=>void;
  vi.spyOn(HTMLMediaElement.prototype,'play').mockImplementation(()=>new Promise<void>(r=>{resolve=r;}));
  vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});
  vi.spyOn(window,'requestAnimationFrame').mockReturnValue(12);
  render(<Player/>);
  let pending!:Promise<void>;
  act(()=>{pending=state.play();});
  act(()=>state.stop());
  await act(async()=>{resolve();await pending;});
  expect(screen.getByRole('button',{name:'播放'})).toBeInTheDocument();
  expect(state.isPlaying).toBe(false);
});

it('follows a native pause event when another player pauses the saved version',async()=>{
  vi.spyOn(HTMLMediaElement.prototype,'play').mockImplementation(async function(this:HTMLMediaElement){Object.defineProperty(this,'paused',{configurable:true,value:false});});
  vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});
  vi.spyOn(window,'requestAnimationFrame').mockReturnValue(12);
  render(<Player/>);
  await act(async()=>state.play());
  Object.defineProperty(document.querySelector('audio')!,'paused',{configurable:true,value:true});
  fireEvent.pause(document.querySelector('audio')!);
  expect(screen.getByRole('button',{name:'播放'})).toBeInTheDocument();
});

it('resets transport state when the saved-version audio source is changed',async()=>{
  vi.spyOn(HTMLMediaElement.prototype,'play').mockImplementation(async function(this:HTMLMediaElement){Object.defineProperty(this,'paused',{configurable:true,value:false});});
  vi.spyOn(HTMLMediaElement.prototype,'pause').mockImplementation(()=>{});
  vi.spyOn(window,'requestAnimationFrame').mockReturnValue(12);
  const view=render(<Player/>);
  await act(async()=>state.play());
  act(()=>state.seek(5));
  expect(screen.getByRole('button',{name:'暂停'})).toBeInTheDocument();
  view.rerender(<Player src='B'/>);
  expect(document.querySelector('audio')!.getAttribute('src')).toBe('B');
  expect(screen.getByRole('button',{name:'播放'})).toBeInTheDocument();
  expect(state.currentTime).toBe(0);
});
