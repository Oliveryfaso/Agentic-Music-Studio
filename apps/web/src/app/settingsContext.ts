import {parseRoute} from './routes';
const BASE='http://motif.local';
const KEYS=['view','panel','track','piano_preview','export_plan'];
function target(value:string):{href:string;name:string}|null{
  try{
    const url=new URL(value,BASE),route=parseRoute(url.pathname);
    if(url.origin!==BASE||['not_found','settings','home','about','evaluation'].includes(route.name))return null;
    const query=new URLSearchParams();for(const key of KEYS){const v=url.searchParams.get(key);if(v&&v.length<=256)query.set(key,v);}
    return {href:url.pathname+(query.size?'?'+query.toString():''),name:route.name};
  }catch{return null;}
}
export function settingsHref(current:string):string{
  const back=target(current);return back?'/settings?'+new URLSearchParams({return_to:back.href}).toString():'/settings';
}
export function settingsReturn(current:string):{href:string;label:string}{
  const back=target(new URL(current,BASE).searchParams.get('return_to')??'/');
  return back?{href:back.href,label:back.name==='studio'?'返回 Studio':back.name==='brief'?'返回创作':back.name==='run'?'返回任务':back.name==='export'?'返回导出':'返回作品'}:{href:'/',label:'返回作品'};
}
