// Local launcher ownership only. Never read container Env or manage a VM.
import * as fs from 'node:fs';
import path from 'node:path';
import {createHash,randomUUID} from 'node:crypto';
import {execFileSync} from 'node:child_process';

function fail(code){throw new Error(code);}
function docker(args,timeout=3000){
  try{return execFileSync('docker',args,{encoding:'utf8',timeout,killSignal:'SIGKILL',stdio:['ignore','pipe','pipe']}).trim();}
  catch{fail('DOCKER_OPERATION_UNAVAILABLE');}
}
function metadata(file){return fs.lstatSync(file,{throwIfNoEntry:false});}
function privateDirectory(directory,create=false){
  let stat=metadata(directory);
  if(!stat&&create){fs.mkdirSync(directory,{recursive:true,mode:0o700});stat=metadata(directory);}
  if(!stat)return;
  if(stat.isSymbolicLink()||!stat.isDirectory())fail('RUNTIME_DIRECTORY_INVALID');
  if(stat.uid!==process.getuid()||(stat.mode&0o077)!==0)fail('RUNTIME_DIRECTORY_NOT_PRIVATE');
}
function loadRecord(root,directory){
  const file=path.join(directory,'stack.json'),stat=metadata(file);
  if(!stat)return null;
  if(stat.isSymbolicLink()||!stat.isFile()||stat.uid!==process.getuid()||(stat.mode&0o077)!==0)fail('OWNERSHIP_RECORD_INVALID');
  let r;try{r=JSON.parse(fs.readFileSync(file,'utf8'));}catch{fail('OWNERSHIP_RECORD_INVALID');}
  if(r.schema!=='motif-owned-stack.v1'||r.project_root!==root||
     !/^[a-z0-9][a-z0-9_-]{1,62}$/.test(r.compose_project)||
     !/^[a-f0-9-]{36}$/.test(r.owner)||typeof r.daemon_id!=='string'||!r.daemon_id)fail('OWNERSHIP_IDENTITY_MISMATCH');
  return r;
}
function daemon(){const id=docker(['info','--format','{{.ID}}']);if(!id)fail('DOCKER_IDENTITY_MISSING');return id;}
function projectContainers(project){
  const text=docker(['ps','-a','--no-trunc','--filter','label=com.docker.compose.project='+project,'--format','{{.ID}}']);
  const ids=text?text.split('\n'):[];
  if(ids.some(id=>!(/^[a-f0-9]{64}$/).test(id)))fail('CONTAINER_ID_INVALID');
  return [...new Set(ids)];
}
function inspectOwned(id,record){
  // A default inspect would expose container credentials. Request these fields only.
  const format='{"Id":{{json .Id}},"Project":{{json (index .Config.Labels "com.docker.compose.project")}},"Owner":{{json (index .Config.Labels "io.motif-forge.runtime-owner")}},"Running":{{json .State.Running}}}';
  let c;try{c=JSON.parse(docker(['inspect','--format',format,id]));}catch{fail('CONTAINER_IDENTITY_UNAVAILABLE');}
  if(c.Id!==id||c.Project!==record.compose_project||
     c.Owner!==record.owner||typeof c.Running!=='boolean')fail('UNOWNED_CONTAINER_REFUSED');
  return c;
}
// These are the effective persistent names in the checked-in Compose contract.
function projectResources(project,kind){
  const expected=project+(kind==='volume'?'_motif_forge_postgres':'_default');
  const scoped=docker([kind,'ls','--filter','label=com.docker.compose.project='+project,'--format','{{.Name}}']);
  const named=docker([kind,'ls','--filter','name=^'+expected+'$','--format','{{.Name}}']);
  const names=[...new Set([scoped,named].filter(Boolean).flatMap(text=>text.split('\n')))];
  if(names.some(name=>!(/^[a-zA-Z0-9][a-zA-Z0-9_.-]+$/).test(name)))fail('RESOURCE_NAME_INVALID');
  return names;
}
function inspectOwnedResource(kind,name,record){
  const format='{"Name":{{json .Name}},"Project":{{json (index .Labels "com.docker.compose.project")}},"Owner":{{json (index .Labels "io.motif-forge.runtime-owner")}}}';
  let r;try{r=JSON.parse(docker([kind,'inspect','--format',format,name]));}catch{fail('RESOURCE_IDENTITY_UNAVAILABLE');}
  if(r.Name!==name||r.Project!==record.compose_project||r.Owner!==record.owner)fail('UNOWNED_RESOURCE_REFUSED');
}
function createRecord(file,r){
  const temporary=file+'.'+randomUUID()+'.tmp';
  const fd=fs.openSync(temporary,'wx',0o600);
  try{fs.writeFileSync(fd,JSON.stringify(r,null,2)+'\n');fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
  try{fs.linkSync(temporary,file);}finally{fs.unlinkSync(temporary);}
}
function main(){
  const [command,rootArg,directoryArg,projectArg]=process.argv.slice(2);
  if(!['prepare','stop','probe','init'].includes(command)||!rootArg||!directoryArg||!path.isAbsolute(directoryArg))fail('RUNTIME_ARGUMENTS_INVALID');
  const root=fs.realpathSync(rootArg),directory=path.resolve(directoryArg);
  if(command==='probe'){daemon();return;}
  if(command==='init'){
    privateDirectory(directory,true);
    const file=path.join(directory,'operation.lock');
    const fd=fs.openSync(file,fs.constants.O_CREAT|fs.constants.O_RDWR|fs.constants.O_NOFOLLOW,0o600);
    try{
      const stat=fs.fstatSync(fd);
      if(!stat.isFile()||stat.uid!==process.getuid()||(stat.mode&0o777)!==0o600||stat.nlink!==1)fail('RUNTIME_LOCK_INVALID');
    }finally{fs.closeSync(fd);}
    return;
  }
  privateDirectory(directory,command==='prepare');
  let record=loadRecord(root,directory);
  if(command==='stop'&&!record){console.log('No recorded owned Motif Forge stack; shared services were not touched.');return;}
  const id=daemon();
  if(record&&record.daemon_id!==id)fail('DOCKER_DAEMON_MISMATCH');
  if(command==='prepare'){
    const project=projectArg||'motif-forge-'+process.getuid()+'-'+createHash('sha256').update(root).digest('hex').slice(0,10);
    if(!/^[a-z0-9][a-z0-9_-]{1,62}$/.test(project))fail('COMPOSE_PROJECT_INVALID');
    if(record&&record.compose_project!==project)fail('COMPOSE_PROJECT_MISMATCH');
    const containers=projectContainers(project);
    const resources=['volume','network'].flatMap(kind=>projectResources(project,kind).map(name=>({kind,name})));
    if(!record&&(containers.length||resources.length))fail('UNOWNED_PROJECT_REFUSED');
    if(record){
      for(const container of containers)inspectOwned(container,record);
      for(const {kind,name} of resources)inspectOwnedResource(kind,name,record);
    }else{
      record={schema:'motif-owned-stack.v1',project_root:root,compose_project:project,daemon_id:id,owner:randomUUID()};
      createRecord(path.join(directory,'stack.json'),record);
    }
    console.log(record.compose_project+'\t'+record.owner);return;
  }
  // Validate the whole set before the first side effect; no compose down or orphan removal.
  const containers=projectContainers(record.compose_project).map(id=>inspectOwned(id,record));
  const running=containers.filter(c=>c.Running).map(c=>c.Id);
  if(running.length){console.log('Stopping owned Motif Forge containers; volumes and VM are preserved.');docker(['stop',...running],30000);}
  else console.log('Recorded Motif Forge containers are already stopped.');
}
try{main();}catch(error){console.error(error?.message||'RUNTIME_OWNERSHIP_FAILED');process.exitCode=1;}
