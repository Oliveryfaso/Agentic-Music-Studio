import type { ArrangementIR, EditorCommand } from "../../shared/openapi";

export interface EditorSelection {
  trackIds: string[];
  startTick: number;
  endTick: number;
  clipId?: string;
}

export interface EditorState {
  base: { branchId: string; revisionId: string; arrangement: ArrangementIR };
  commands: EditorCommand[];
  historyCursor: number;
  selection: EditorSelection | null;
  dragPreview: { clipId: string; startTick: number } | null;
  saveState: "clean" | "dirty" | "saving" | "error" | "conflict";
  conflict: { serverRevisionId: string } | null;
}

export type EditorAction =
  | { type: "append"; command: EditorCommand }
  | { type: "undo" }
  | { type: "redo" }
  | { type: "select"; selection: EditorSelection | null }
  | { type: "drag"; preview: EditorState["dragPreview"] }
  | { type: "saving" }
  | { type: "saveError" }
  | { type: "conflict"; serverRevisionId: string }
  | { type: "commitSuccess"; revisionId: string; arrangement: ArrangementIR };

export function createEditorState(branchId: string, revisionId: string, arrangement: ArrangementIR): EditorState {
  return { base: { branchId, revisionId, arrangement }, commands: [], historyCursor: 0, selection: null, dragPreview: null, saveState: "clean", conflict: null };
}

export function editorReducer(state: EditorState, action: EditorAction): EditorState {
  switch (action.type) {
    case "append": {
      const commands = [...state.commands.slice(0, state.historyCursor), action.command];
      return { ...state, commands, historyCursor: commands.length, saveState: "dirty", conflict: null, dragPreview: null };
    }
    case "undo": return { ...state, historyCursor: Math.max(0, state.historyCursor - 1), saveState: state.historyCursor <= 1 ? "clean" : "dirty" };
    case "redo": return { ...state, historyCursor: Math.min(state.commands.length, state.historyCursor + 1), saveState: "dirty" };
    case "select": return { ...state, selection: action.selection };
    case "drag": return { ...state, dragPreview: action.preview };
    case "saving": return { ...state, saveState: "saving" };
    case "saveError": return { ...state, saveState: "error" };
    case "conflict": return { ...state, saveState: "conflict", conflict: { serverRevisionId: action.serverRevisionId } };
    case "commitSuccess": return { ...createEditorState(state.base.branchId, action.revisionId, action.arrangement), selection: state.selection };
  }
}

export function canSaveDraft(state: EditorState): boolean {
  return state.historyCursor > 0 && state.saveState !== "saving" && state.saveState !== "conflict";
}

export function projectDraft(state: EditorState): ArrangementIR {
  let draft = structuredClone(state.base.arrangement);
  for (const command of state.commands.slice(0, state.historyCursor)) draft = applyDraftCommand(draft, command);
  return draft;
}

function applyDraftCommand(ir: ArrangementIR, command: EditorCommand): ArrangementIR {
  const draft = structuredClone(ir);
  const payload = command.payload as Record<string, unknown>;
  const trackId = String(payload.track_id ?? "");
  const track = draft.tracks.find((item) => item.track_id === trackId);
  if (command.command_type === "add_track") {
    draft.tracks.push(structuredClone((payload as { track: ArrangementIR["tracks"][number] }).track));
    return draft;
  }
  if (command.command_type === "delete_track") {
    draft.tracks = draft.tracks.filter((item) => item.track_id !== trackId);
    return draft;
  }
  if (!track) throw new Error(`Draft track not found: ${trackId}`);
  if (command.command_type === "set_track_param") {
    const parameter = String(payload.parameter);
    if (parameter.startsWith("eq_")) {
      const key = parameter.slice(3) as "low_db" | "mid_db" | "high_db";
      track.eq = { low_db: 0, mid_db: 0, high_db: 0, ...track.eq, [key]: payload.value as number };
    } else Object.assign(track, { [parameter]: payload.value });
    return draft;
  }
  const clipId = String(payload.clip_id ?? "");
  const clipIndex = track.clips.findIndex((item) => item.clip_id === clipId);
  const clip = track.clips[clipIndex];
  if (command.command_type === "add_clip") { track.clips.push(structuredClone((payload as { clip: typeof track.clips[number] }).clip)); return draft; }
  if (command.command_type === "delete_clip") { track.clips = track.clips.filter((item) => item.clip_id !== clipId); return draft; }
  if (!clip) throw new Error(`Draft clip not found: ${clipId}`);
  if (command.command_type === "duplicate_clip") { track.clips.push({ ...structuredClone(clip), clip_id: String(payload.duplicate_clip_id), start_tick: Number(payload.start_tick) }); return draft; }
  if (command.command_type === "move_clip") clip.start_tick = Number(payload.start_tick);
  else if (command.command_type === "trim_clip") { clip.start_tick = Number(payload.start_tick); clip.duration_tick = Number(payload.end_tick) - clip.start_tick; }
  else if (command.command_type === "set_clip_param") Object.assign(clip, { [String(payload.parameter)]: payload.value });
  else if (command.command_type === "add_notes" && clip.clip_type === "note") clip.notes.push(...structuredClone(payload.notes as typeof clip.notes));
  else if (command.command_type === "delete_notes" && clip.clip_type === "note") { const ids = new Set(payload.note_ids as string[]); clip.notes = clip.notes.filter((note) => !ids.has(note.note_id)); }
  else if (command.command_type === "update_notes" && clip.clip_type === "note") { const updates = payload.updates as Array<Record<string, unknown>>; clip.notes = clip.notes.map((note) => ({ ...note, ...(updates.find((item) => item.note_id === note.note_id) ?? {}) })); }
  else if (!(["move_clip", "trim_clip", "set_clip_param"] as string[]).includes(command.command_type)) throw new Error(`Unsupported Draft command: ${command.command_type}`);
  return draft;
}
