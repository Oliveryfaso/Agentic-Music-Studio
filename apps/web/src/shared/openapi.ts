import type { components } from "../generated/api-schema";

type Schemas = components["schemas"];

export type ArrangementIR = Schemas["ArrangementIR"];
export type EditorCommand = Schemas["CommandBatchBody"]["commands"][number];
export type CommitCommandBatchInput = Schemas["CommandBatchBody"];
export type CommandBatchData = Schemas["CommandBatchData"];
export type UndoCommittedRevisionInput = Schemas["UndoRevisionBody"];
export type UndoRevisionData = Schemas["UndoRevisionData"];
export type AIRun = Schemas["AIRunData"];
export type AIRunEvent = Schemas["AIRunEvent"];
export type AIRunStatus = Schemas["AIRunStatus"];
export type CreateAIRunInput = Schemas["CreateAIRunBody"];
export type CreateProjectInput = Schemas["CreateProjectBody"];
export type CreateProjectResult = Schemas["CreateProjectData"];
export type ProjectSummary = Schemas["ProjectSummaryData"];
export type ProjectWorkspace = Schemas["ProjectWorkspaceData"];
export type CompositionPlan = Schemas["CompositionPlan"];
export type RunPlan = Schemas["RunPlanData"];
export type ReplanAIRunInput = Schemas["ReplanAIRunBody"];
export type ResumeAIRunInput = Schemas["ResumeAIRunBody"];
export type RevisionStudio = Schemas["RevisionStudioData"];
export type RunActionInput = Schemas["RunActionBody"];
export type RunProgress = Schemas["RunProgressData"];
export type SelectCandidateInput = Schemas["SelectCandidateBody"];
