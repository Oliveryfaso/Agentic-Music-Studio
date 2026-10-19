import type { components } from "../generated/api-schema";

type Schemas = components["schemas"];

export type ArrangementIR = Schemas["ArrangementIR"] | Schemas["ArrangementIRV2"] | Schemas["ArrangementIRV3"] | Schemas["ArrangementIRV4"];
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
export type EditPreviewDecisionInput = Schemas["EditPreviewDecisionBody"];
export type RunEditPreview = Schemas["RunEditPreviewData"];
export type RevisionExportProjection = Schemas["RevisionExportProjection"];
export type RunInspectionFacts = Schemas["RunInspectionFacts"];
export type RunGraphReadModel = Schemas["RunGraphReadModel"];
export type GraphPhaseView = Schemas["GraphPhaseView"];
export type GraphNodeView = Schemas["GraphNodeView"];
export type GraphEdgeView = Schemas["GraphEdgeView"];

export type RevisionExportOptions = Schemas["RevisionExportOptions"];
export type RevisionExportRun = Schemas["RevisionExportRunData"];

export type PianoCapability = Schemas["PianoCapability"];
export type PianoPreviewOptions = Schemas["PianoPreviewOptions"];
export type PianoPreviewData = Schemas["PianoPreviewData"];
export type PianoPreviewDecision = Schemas["PianoPreviewDecision"];
export type PianoStudyResult = Schemas["PianoStudyResult"];
export type PerformancePlan = Schemas["PerformancePlan"];

export type ClassicalScoreDescription = Schemas["ClassicalScoreDescription"];
export type ClassicalScoreResult = Schemas["ClassicalScoreResult"];
export type ClassicalSourceData = Schemas["ClassicalSourceData"];
export type AccompanimentIntent = Schemas["AccompanimentIntent"];
