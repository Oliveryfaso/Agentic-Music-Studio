import {expect,it} from 'vitest';
import {settingsHref,settingsReturn} from './settingsContext';
it('returns to the same Studio revision and only keeps supported view state',()=>{
 const current='/projects/p/studio/r?view=mix&track=t&piano_preview=c&unrecognized=private';
 const href=settingsHref(current);
 expect(settingsReturn(href)).toEqual({href:'/projects/p/studio/r?view=mix&track=t&piano_preview=c',label:'返回 Studio'});
 expect(href).not.toContain('private');
});
it.each(['/settings?return_to=https%3A%2F%2Foutside.test%2Fx','/settings?return_to=javascript%3Aalert(1)','/settings?return_to=%2Funknown','/settings?return_to=%2Fsettings'])('rejects unsafe or irrelevant return targets: %s',href=>{
 expect(settingsReturn(href)).toEqual({href:'/',label:'返回作品'});
});
it('keeps the normal home entry simple and returns to creation explicitly',()=>{
 expect(settingsHref('/')).toBe('/settings');
 expect(settingsReturn(settingsHref('/projects/p/new-composition'))).toEqual({href:'/projects/p/new-composition',label:'返回创作'});
});
