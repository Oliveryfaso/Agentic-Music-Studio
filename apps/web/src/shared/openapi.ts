import type { components } from "../generated/api-schema";

type Schemas = components["schemas"];

export type AIRun = Schemas["AIRunData"];
export type AIRunEvent = Schemas["AIRunEvent"];
export type AIRunStatus = Schemas["AIRunStatus"];
export type CreateAIRunInput = Schemas["CreateAIRunBody"];
export type ProjectSummary = Schemas["ProjectSummaryData"];
export type ProjectWorkspace = Schemas["ProjectWorkspaceData"];
export type ReplanAIRunInput = Schemas["ReplanAIRunBody"];
export type ResumeAIRunInput = Schemas["ResumeAIRunBody"];
export type RevisionStudio = Schemas["RevisionStudioData"];
export type RunActionInput = Schemas["RunActionBody"];
export type RunProgress = Schemas["RunProgressData"];
