import {jsonHeaders,readData,requestJson} from '../../shared/api';
import type {ClassicalScoreDescription,ClassicalScoreResult,ClassicalSourceData} from '../../shared/openapi';
export async function listClassicalScores():Promise<ClassicalScoreDescription[]>{return readData(await requestJson('/api/v1/classical-scores'));}
export async function importClassicalScore(scoreId:string,key:string):Promise<ClassicalScoreResult>{return readData(await requestJson('/api/v1/classical-score-imports',{method:'POST',headers:jsonHeaders(key),body:JSON.stringify({score_id:scoreId})}));}
export async function readClassicalSource(project:string):Promise<ClassicalSourceData>{return readData(await requestJson(`/api/v1/projects/${encodeURIComponent(project)}/classical-source`));}
