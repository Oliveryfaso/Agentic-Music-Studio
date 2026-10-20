import type {ClassicalScoreDescription} from '../../shared/openapi';

// Reuses generated host DTOs. This is a local review identity, not a server hash.
export function reviewKey(score:ClassicalScoreDescription):string {
 return JSON.stringify([score.score_id,score.musicxml_sha256,score.original_sha256,score.title,score.composer,score.digital_editor,score.license,score.conversion,score.measure_count,score.note_count,score.page_url,score.source_url,score.default_chords,score.beats,score.bpm,score.tonic]);
}
export function canImportScore(catalog:readonly ClassicalScoreDescription[],id:string,acknowledgedKey:string|null,busy:boolean):boolean {
 const selected=catalog.find(item=>item.score_id===id);
 return !busy&&!!selected&&reviewKey(selected)===acknowledgedKey;
}
