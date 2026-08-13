"""The versioned production Parent Graph, introduced one durable branch at a time."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from typing import Any, Literal, NotRequired, Protocol, TypedDict
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from motif_forge.agent.generate import (
    PARENT_GRAPH_TOPOLOGY_VERSION,
    PARENT_STATE_SCHEMA_VERSION,
    GenerateNodes,
    build_generate_nodes,
)
from motif_forge.agent.planner import CompositionPlanner
from motif_forge.agent.worker_gate import wait_for_job_event
from motif_forge.application.ai_runs import RecordAIRunApproval
from motif_forge.application.generation import (
    CollectCompleteExportArtifact,
    EnqueueNextCompleteExportJob,
    MaterializeApprovedComposition,
    PersistPlanningResult,
)
from motif_forge.application.imports import (
    ImportAnalysisContext,
    MaterializeImportRequest,
)
from motif_forge.application.media_jobs import (
    EnqueueFollowupMediaJobRequest,
    EnqueueMediaJobRequest,
    EnqueueMediaJobResult,
    StartArtifactRehydrationRequest,
)
from motif_forge.domain.import_policy import decide_import_alignment
from motif_forge.domain.media_jobs import (
    FeatureRehydrateJobPayload,
    IngestJobPayload,
    MediaJobType,
    MediaQualityProfile,
    RehydrateJobPayload,
    TimeStretchJobPayload,
)
from motif_forge.domain.storage import StoragePressureDecision, StorageRoute

PARENT_TIME_STRETCH_RUN_TYPE = "parent.time_stretch.v1"
PARENT_IMPORT_RUN_TYPE = "parent.import_audio.v1"
PARENT_REHYDRATE_RUN_TYPE = "parent.artifact_rehydrate.v1"


class MediaJobEnqueuer(Protocol):
    async def __call__(self, request: EnqueueMediaJobRequest) -> EnqueueMediaJobResult: ...


class FollowupMediaJobEnqueuer(Protocol):
    async def __call__(self, request: EnqueueFollowupMediaJobRequest) -> EnqueueMediaJobResult: ...


class ArtifactRehydrationEnqueuer(Protocol):
    async def __call__(self, request: StartArtifactRehydrationRequest) -> EnqueueMediaJobResult: ...


class ArtifactRehydrationLoader(Protocol):
    async def __call__(
        self, *, artifact_id: UUID
    ) -> tuple[UUID, RehydrateJobPayload | FeatureRehydrateJobPayload]: ...


class ImportMaterializer(Protocol):
    async def __call__(self, request: MaterializeImportRequest) -> Any: ...


class ImportContextLoader(Protocol):
    async def __call__(
        self, *, project_id: UUID, base_revision_id: UUID, normalized_artifact_id: UUID
    ) -> ImportAnalysisContext: ...


class StoragePressureGate(Protocol):
    async def __call__(
        self,
        *,
        operation_id: str,
        project_id: UUID,
        estimated_artifact_bytes: int,
        estimated_temp_bytes: int,
        dependency_artifact_ids: tuple[UUID, ...] = (),
        requires_artifact_io: bool = True,
    ) -> StoragePressureDecision: ...


class ImportAnalysisConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: Literal["confirm", "override", "skip_alignment", "cancel"]
    source_bpm: float | None = Field(default=None, ge=30.0, le=300.0)
    key_tonic: Literal["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"] | None = (
        None
    )
    key_mode: Literal["major", "minor"] | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> ImportAnalysisConfirmation:
        if self.action == "override" and self.source_bpm is None:
            raise ValueError("override requires source_bpm")
        if (self.key_tonic is None) != (self.key_mode is None):
            raise ValueError("key_tonic and key_mode must be provided together")
        return self


class ParentGraphState(TypedDict):
    thread_id: str
    project_id: str
    operation: Literal["generate", "time_stretch", "import_audio", "artifact_rehydrate"]
    graph_topology_version: str
    state_schema_version: str
    request_payload: Mapping[str, Any]
    phase: str
    run_id: NotRequired[str]
    pending_job_id: NotRequired[str | None]
    artifact_refs: NotRequired[list[str]]
    pending_action: NotRequired[str]
    error_code: NotRequired[str]
    last_resume_event_id: NotRequired[str]
    terminal_status: NotRequired[Literal["succeeded", "failed"]]
    branch_id: NotRequired[str]
    base_revision_id: NotRequired[str]
    materialized_revision_id: NotRequired[str]
    request_idempotency_key: NotRequired[str]
    normalized_artifact_id: NotRequired[str]
    selected_artifact_id: NotRequired[str]
    project_bpm: NotRequired[float]
    source_bpm: NotRequired[float]
    key_tonic: NotRequired[str]
    key_mode: NotRequired[str]
    bpm_confidence: NotRequired[float]
    key_confidence: NotRequired[float]
    analysis_policy_version: NotRequired[str]
    analysis_explanation_code: NotRequired[str]
    alignment_required: NotRequired[bool]
    storage_policy_version: NotRequired[str]
    storage_explanation_code: NotRequired[str]
    storage_route: NotRequired[str]
    storage_gate_attempt: NotRequired[int]
    plan_id: NotRequired[str]
    plan_hash: NotRequired[str]
    plan_summary: NotRequired[dict[str, object]]
    plan_interrupt_ref: NotRequired[str]
    run_version: NotRequired[int]
    model_counters: NotRequired[dict[str, int]]
    fallback_reason: NotRequired[str]
    approval_decision: NotRequired[str]
    approval_actor_id: NotRequired[str]
    approval_assertion: NotRequired[str]
    approval_note: NotRequired[str]
    export_cursor: NotRequired[dict[str, object]]
    media_run_id: NotRequired[str | None]


def initial_time_stretch_state(
    *, thread_id: str, project_id: UUID, request: TimeStretchJobPayload
) -> ParentGraphState:
    if not thread_id or len(thread_id) > 160:
        raise ValueError("thread_id must contain between 1 and 160 characters")
    return ParentGraphState(
        thread_id=thread_id,
        project_id=str(project_id),
        operation="time_stretch",
        graph_topology_version=PARENT_GRAPH_TOPOLOGY_VERSION,
        state_schema_version=PARENT_STATE_SCHEMA_VERSION,
        request_payload=request.model_dump(mode="json"),
        phase="received",
    )


def initial_import_state(
    *,
    thread_id: str,
    project_id: UUID,
    branch_id: UUID,
    base_revision_id: UUID,
    source_artifact_id: UUID,
    idempotency_key: str,
) -> ParentGraphState:
    if not thread_id or len(thread_id) > 160:
        raise ValueError("thread_id must contain between 1 and 160 characters")
    if not 8 <= len(idempotency_key) <= 160:
        raise ValueError("idempotency_key must contain between 8 and 160 characters")
    request = IngestJobPayload(source_artifact_id=source_artifact_id)
    return ParentGraphState(
        thread_id=thread_id,
        project_id=str(project_id),
        branch_id=str(branch_id),
        base_revision_id=str(base_revision_id),
        operation="import_audio",
        graph_topology_version=PARENT_GRAPH_TOPOLOGY_VERSION,
        state_schema_version=PARENT_STATE_SCHEMA_VERSION,
        request_payload=request.model_dump(mode="json"),
        phase="received",
        request_idempotency_key=idempotency_key,
    )


def initial_artifact_rehydrate_state(
    *,
    thread_id: str,
    artifact_id: UUID,
    idempotency_key: str,
) -> ParentGraphState:
    if not thread_id or len(thread_id) > 160:
        raise ValueError("thread_id must contain between 1 and 160 characters")
    if not 8 <= len(idempotency_key) <= 160:
        raise ValueError("idempotency_key must contain between 8 and 160 characters")
    return ParentGraphState(
        thread_id=thread_id,
        project_id="",
        operation="artifact_rehydrate",
        graph_topology_version=PARENT_GRAPH_TOPOLOGY_VERSION,
        state_schema_version=PARENT_STATE_SCHEMA_VERSION,
        request_payload={"target_artifact_id": str(artifact_id)},
        phase="received",
        request_idempotency_key=idempotency_key,
    )


def _idempotency_key(state: ParentGraphState) -> str:
    if state["operation"] in {"import_audio", "artifact_rehydrate"}:
        public_key = state.get("request_idempotency_key")
        if public_key is None:
            raise ValueError("import state requires request_idempotency_key")
        return f"parent-{state['operation']}:{sha256(public_key.encode()).hexdigest()}"
    fingerprint = sha256(
        json.dumps(
            {
                "thread_id": state["thread_id"],
                "operation": state["operation"],
                "request": state["request_payload"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return f"parent-{state['operation']}:{fingerprint}"


def _estimate_initial_output_bytes(state: ParentGraphState) -> int:
    """Conservative v1 estimate before exact media duration is available."""

    if state["operation"] == "import_audio":
        return 256 * 1024**2
    return 128 * 1024**2


def build_parent_graph(
    enqueue_media_job: MediaJobEnqueuer,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    materialize_import: ImportMaterializer | None = None,
    load_import_context: ImportContextLoader | None = None,
    enqueue_followup_media_job: FollowupMediaJobEnqueuer | None = None,
    enqueue_artifact_rehydration: ArtifactRehydrationEnqueuer | None = None,
    load_artifact_rehydration: ArtifactRehydrationLoader | None = None,
    storage_pressure_gate: StoragePressureGate | None = None,
    generate_planner: CompositionPlanner | None = None,
    persist_planning_result: PersistPlanningResult | None = None,
    record_plan_approval: RecordAIRunApproval | None = None,
    materialize_approved_composition: MaterializeApprovedComposition | None = None,
    enqueue_next_complete_export_job: EnqueueNextCompleteExportJob | None = None,
    collect_complete_export_artifact: CollectCompleteExportArtifact | None = None,
) -> CompiledStateGraph[ParentGraphState, None, ParentGraphState, ParentGraphState]:
    """Compile Import and standalone time-stretch inside one Parent topology."""

    async def validate_request(state: ParentGraphState) -> dict[str, Any]:
        if state.get("graph_topology_version") != PARENT_GRAPH_TOPOLOGY_VERSION:
            return {"phase": "failed", "error_code": "GRAPH_TOPOLOGY_VERSION_UNSUPPORTED"}
        try:
            if state["operation"] == "generate":
                if generate_nodes is None:
                    return {"phase": "failed", "error_code": "GENERATE_NOT_CONFIGURED"}
                return await generate_nodes.validate_generate(state)
            if state["operation"] == "time_stretch":
                UUID(state["project_id"])
                TimeStretchJobPayload.model_validate_json(
                    json.dumps(state["request_payload"]), strict=True
                )
            elif state["operation"] == "import_audio":
                UUID(state["project_id"])
                UUID(state["branch_id"])
                UUID(state["base_revision_id"])
                IngestJobPayload.model_validate_json(
                    json.dumps(state["request_payload"]), strict=True
                )
            elif state["operation"] == "artifact_rehydrate":
                UUID(str(state["request_payload"]["target_artifact_id"]))
            else:
                raise ValueError
        except (KeyError, ValueError, ValidationError):
            return {"phase": "failed", "error_code": "PARENT_REQUEST_INVALID"}
        return {"phase": "request_validated"}

    def validation_route(
        state: ParentGraphState,
    ) -> Literal["generate", "load", "storage", "error"]:
        if state.get("phase") == "generate_validated":
            return "generate"
        if state.get("phase") != "request_validated":
            return "error"
        return "load" if state["operation"] == "artifact_rehydrate" else "storage"

    async def load_rehydration(state: ParentGraphState) -> dict[str, Any]:
        if load_artifact_rehydration is None:
            return {
                "phase": "failed",
                "error_code": "ARTIFACT_REHYDRATION_NOT_CONFIGURED",
            }
        try:
            artifact_id = UUID(str(state["request_payload"]["target_artifact_id"]))
            project_id, payload = await load_artifact_rehydration(artifact_id=artifact_id)
        except Exception as exc:
            return {
                "phase": "failed",
                "error_code": getattr(exc, "code", "ARTIFACT_REHYDRATION_RECIPE_INVALID"),
            }
        return {
            "project_id": str(project_id),
            "request_payload": payload.model_dump(mode="json"),
            "phase": "request_validated",
        }

    async def check_storage(state: ParentGraphState) -> dict[str, Any]:
        if storage_pressure_gate is None:
            return {
                "phase": "storage_ready",
                "storage_policy_version": "storage-pressure-policy.v1",
                "storage_route": StorageRoute.PROCEED.value,
                "storage_explanation_code": "STORAGE_GATE_NOT_CONFIGURED_TEST_ONLY",
            }
        estimated_bytes = _estimate_initial_output_bytes(state)
        if state["operation"] == "import_audio":
            dependency_id = IngestJobPayload.model_validate_json(
                json.dumps(state["request_payload"]), strict=True
            ).source_artifact_id
        elif state["operation"] == "time_stretch":
            dependency_id = TimeStretchJobPayload.model_validate_json(
                json.dumps(state["request_payload"]), strict=True
            ).source_artifact_id
        else:
            try:
                dependency_id = RehydrateJobPayload.model_validate_json(
                    json.dumps(state["request_payload"]), strict=True
                ).source_artifact_id
            except ValidationError:
                dependency_id = FeatureRehydrateJobPayload.model_validate_json(
                    json.dumps(state["request_payload"]), strict=True
                ).source_artifact_id
        decision = await storage_pressure_gate(
            operation_id=f"{_idempotency_key(state)}:storage-v1",
            project_id=UUID(state["project_id"]),
            estimated_artifact_bytes=estimated_bytes,
            estimated_temp_bytes=estimated_bytes,
            dependency_artifact_ids=(dependency_id,),
        )
        update: dict[str, Any] = {
            "storage_policy_version": decision.policy_version,
            "storage_route": decision.route.value,
            "storage_explanation_code": decision.explanation_code,
        }
        if decision.route is StorageRoute.PROCEED:
            update["phase"] = "storage_ready"
        elif decision.route is StorageRoute.WAIT_FOR_STORAGE:
            update["phase"] = "storage_wait_required"
            update["error_code"] = decision.error_code or "ARTIFACT_ROOT_UNAVAILABLE"
        elif decision.route is StorageRoute.REHYDRATE_THEN_RESUME:
            update["phase"] = "failed"
            update["error_code"] = decision.error_code or "ARTIFACT_EVICTED"
        else:
            update["phase"] = "failed"
            update["error_code"] = decision.error_code or "STORAGE_QUOTA_EXCEEDED"
        return update

    def storage_route(state: ParentGraphState) -> Literal["enqueue", "human", "error"]:
        if state.get("phase") == "storage_ready":
            return "enqueue"
        if state.get("phase") == "storage_wait_required":
            return "human"
        return "error"

    async def wait_for_storage(state: ParentGraphState) -> dict[str, Any]:
        resumed = interrupt(
            {
                "kind": "storage_unavailable",
                "phase": "waiting_human",
                "error_code": state.get("error_code", "ARTIFACT_ROOT_UNAVAILABLE"),
                "explanation_code": state.get("storage_explanation_code"),
                "options": ["retry", "cancel"],
            }
        )
        if not isinstance(resumed, Mapping) or resumed.get("action") not in {"retry", "cancel"}:
            return {"phase": "failed", "error_code": "STORAGE_RESUME_INVALID"}
        if resumed["action"] == "cancel":
            return {"phase": "failed", "error_code": "STORAGE_OPERATION_CANCELLED"}
        return {
            "phase": "request_validated",
            "error_code": "",
            "storage_gate_attempt": state.get("storage_gate_attempt", 0) + 1,
        }

    async def enqueue_initial_job(state: ParentGraphState) -> dict[str, Any]:
        is_import = state["operation"] == "import_audio"
        if state["operation"] == "artifact_rehydrate":
            if enqueue_artifact_rehydration is None:
                return {
                    "phase": "failed",
                    "error_code": "ARTIFACT_REHYDRATION_NOT_CONFIGURED",
                }
            try:
                payload: RehydrateJobPayload | FeatureRehydrateJobPayload = (
                    RehydrateJobPayload.model_validate_json(
                        json.dumps(state["request_payload"]), strict=True
                    )
                )
            except ValidationError:
                payload = FeatureRehydrateJobPayload.model_validate_json(
                    json.dumps(state["request_payload"]), strict=True
                )
            result = await enqueue_artifact_rehydration(
                StartArtifactRehydrationRequest(
                    project_id=UUID(state["project_id"]),
                    artifact_id=payload.target_artifact_id,
                    thread_id=state["thread_id"],
                    idempotency_key=_idempotency_key(state),
                )
            )
            return {
                "run_id": str(result.run_id),
                "pending_job_id": str(result.job_id),
                "phase": "waiting_worker",
            }
        result = await enqueue_media_job(
            EnqueueMediaJobRequest(
                project_id=UUID(state["project_id"]),
                thread_id=state["thread_id"],
                run_type=PARENT_IMPORT_RUN_TYPE if is_import else PARENT_TIME_STRETCH_RUN_TYPE,
                job_type=MediaJobType.INGEST if is_import else MediaJobType.TIME_STRETCH,
                input_payload=dict(state["request_payload"]),
                output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                idempotency_key=_idempotency_key(state),
            )
        )
        return {
            "run_id": str(result.run_id),
            "pending_job_id": str(result.job_id),
            "phase": "waiting_worker",
        }

    def wait_for_worker(state: ParentGraphState) -> dict[str, Any]:
        return dict(wait_for_job_event(dict(state)))

    def worker_route(state: ParentGraphState) -> Literal["ingest", "stretch", "complete", "error"]:
        if state.get("pending_action") != "validate_artifact":
            return "error"
        if state["operation"] in {"time_stretch", "artifact_rehydrate"}:
            return "complete"
        return "stretch" if state.get("normalized_artifact_id") else "ingest"

    async def load_analysis(state: ParentGraphState) -> dict[str, Any]:
        refs = state.get("artifact_refs", [])
        if len(refs) != 1 or load_import_context is None:
            return {"phase": "failed", "error_code": "IMPORT_ANALYSIS_NOT_CONFIGURED"}
        try:
            artifact_id = UUID(refs[0])
            context = await load_import_context(
                project_id=UUID(state["project_id"]),
                base_revision_id=UUID(state["base_revision_id"]),
                normalized_artifact_id=artifact_id,
            )
        except Exception as exc:
            return {
                "phase": "failed",
                "error_code": getattr(exc, "code", "IMPORT_ANALYSIS_UNAVAILABLE"),
            }
        decision = decide_import_alignment(context.analysis, project_bpm=context.project_bpm)
        update: dict[str, Any] = {
            "normalized_artifact_id": str(context.normalized_artifact_id),
            "selected_artifact_id": str(context.normalized_artifact_id),
            "project_bpm": context.project_bpm,
            "bpm_confidence": context.analysis.bpm_confidence,
            "key_confidence": context.analysis.key_confidence,
            "analysis_policy_version": decision.policy_version,
            "analysis_explanation_code": decision.explanation_code,
            "phase": "analysis_ready",
            "alignment_required": decision.route == "align",
        }
        if context.analysis.bpm is not None:
            update["source_bpm"] = context.analysis.bpm
        if context.analysis.key_tonic is not None:
            update["key_tonic"] = context.analysis.key_tonic
            update["key_mode"] = context.analysis.key_mode
        if decision.route == "confirm":
            update["phase"] = "analysis_confirmation_required"
        return update

    def analysis_route(
        state: ParentGraphState,
    ) -> Literal["human", "align", "materialize", "error"]:
        if state.get("phase") == "analysis_confirmation_required":
            return "human"
        if state.get("phase") != "analysis_ready":
            return "error"
        return "align" if state.get("alignment_required") else "materialize"

    def confirm_analysis(state: ParentGraphState) -> dict[str, Any]:
        resumed = interrupt(
            {
                "kind": "import_analysis_confirmation",
                "phase": "waiting_human",
                "analysis": {
                    "bpm": state.get("source_bpm"),
                    "bpm_confidence": state.get("bpm_confidence", 0.0),
                    "key_tonic": state.get("key_tonic"),
                    "key_mode": state.get("key_mode"),
                    "key_confidence": state.get("key_confidence", 0.0),
                    "project_bpm": state["project_bpm"],
                    "explanation_code": state.get("analysis_explanation_code"),
                },
                "options": ["confirm", "override", "skip_alignment", "cancel"],
            }
        )
        try:
            decision = ImportAnalysisConfirmation.model_validate(resumed)
        except ValidationError:
            return {"phase": "failed", "error_code": "IMPORT_CONFIRMATION_INVALID"}
        if decision.action == "cancel":
            return {"phase": "failed", "error_code": "IMPORT_CANCELLED_BY_USER"}
        source_bpm: float | None = decision.source_bpm
        if source_bpm is None:
            source_bpm = state.get("source_bpm")
        update: dict[str, Any] = {
            "phase": "analysis_ready",
            "alignment_required": decision.action != "skip_alignment",
            "analysis_explanation_code": f"IMPORT_ANALYSIS_USER_{decision.action.upper()}",
        }
        if decision.action == "skip_alignment" and source_bpm is None:
            return update
        if source_bpm is None:
            update.update(phase="failed", error_code="IMPORT_SOURCE_BPM_REQUIRED")
            return update
        update["source_bpm"] = source_bpm
        if decision.key_tonic is not None:
            update["key_tonic"] = decision.key_tonic
            update["key_mode"] = decision.key_mode
        if abs(source_bpm - state["project_bpm"]) / state["project_bpm"] <= 0.01:
            update["alignment_required"] = False
        return update

    async def enqueue_alignment(state: ParentGraphState) -> dict[str, Any]:
        if enqueue_followup_media_job is None or state.get("source_bpm") is None:
            return {"phase": "failed", "error_code": "IMPORT_ALIGNMENT_NOT_CONFIGURED"}
        try:
            payload = TimeStretchJobPayload(
                source_artifact_id=UUID(state["normalized_artifact_id"]),
                source_bpm=state["source_bpm"],
                target_bpm=state["project_bpm"],
            )
            result = await enqueue_followup_media_job(
                EnqueueFollowupMediaJobRequest(
                    run_id=UUID(state["run_id"]),
                    project_id=UUID(state["project_id"]),
                    thread_id=state["thread_id"],
                    job_type=MediaJobType.TIME_STRETCH,
                    input_payload=payload.model_dump(mode="json"),
                    output_quality_profile=MediaQualityProfile.WORKING_PCM_V1,
                    idempotency_key=f"{_idempotency_key(state)}:alignment-v1",
                )
            )
        except (ValueError, ValidationError) as exc:
            return {
                "phase": "failed",
                "error_code": getattr(exc, "code", "IMPORT_STRETCH_RATIO_UNSUPPORTED"),
            }
        return {"pending_job_id": str(result.job_id), "phase": "waiting_worker"}

    async def select_stretched_artifact(state: ParentGraphState) -> dict[str, Any]:
        refs = state.get("artifact_refs", [])
        if len(refs) != 1:
            return {"phase": "failed", "error_code": "WORKER_ARTIFACT_REF_INVALID"}
        try:
            UUID(refs[0])
        except ValueError:
            return {"phase": "failed", "error_code": "WORKER_ARTIFACT_REF_INVALID"}
        return {"selected_artifact_id": refs[0], "phase": "alignment_ready"}

    async def materialize(state: ParentGraphState) -> dict[str, Any]:
        if materialize_import is None:
            return {"phase": "failed", "error_code": "IMPORT_MATERIALIZER_NOT_CONFIGURED"}
        selected = state.get("selected_artifact_id")
        if selected is None:
            return {"phase": "failed", "error_code": "IMPORT_ARTIFACT_REF_INVALID"}
        stretched = selected != state.get("normalized_artifact_id")
        try:
            result = await materialize_import(
                MaterializeImportRequest(
                    project_id=UUID(state["project_id"]),
                    branch_id=UUID(state["branch_id"]),
                    base_revision_id=UUID(state["base_revision_id"]),
                    normalized_artifact_id=UUID(selected),
                    original_normalized_artifact_id=(
                        UUID(state["normalized_artifact_id"]) if stretched else None
                    ),
                    source_bpm=state.get("source_bpm") if stretched else None,
                    target_bpm=state.get("project_bpm") if stretched else None,
                )
            )
        except Exception as exc:
            return {
                "phase": "failed",
                "error_code": getattr(exc, "code", "IMPORT_MATERIALIZATION_FAILED"),
            }
        return {
            "phase": "completed",
            "terminal_status": "succeeded",
            "materialized_revision_id": str(result.revision_id),
        }

    async def complete_time_stretch(state: ParentGraphState) -> dict[str, Any]:
        refs = state.get("artifact_refs", [])
        if len(refs) != 1:
            return {"phase": "failed", "error_code": "WORKER_ARTIFACT_REF_INVALID"}
        return {"phase": "completed", "terminal_status": "succeeded"}

    async def route_error(state: ParentGraphState) -> dict[str, Any]:
        return {
            "phase": "failed",
            "terminal_status": "failed",
            "error_code": state.get("error_code", "PARENT_GRAPH_FAILED"),
        }

    generate_nodes: GenerateNodes | None = None
    if all(
        item is not None
        for item in (
            generate_planner,
            persist_planning_result,
            record_plan_approval,
            materialize_approved_composition,
            enqueue_next_complete_export_job,
            collect_complete_export_artifact,
        )
    ):
        assert generate_planner is not None
        assert persist_planning_result is not None
        assert record_plan_approval is not None
        assert materialize_approved_composition is not None
        assert enqueue_next_complete_export_job is not None
        assert collect_complete_export_artifact is not None
        generate_nodes = build_generate_nodes(
            generate_planner,
            persist_planning_result=persist_planning_result,
            record_plan_approval=record_plan_approval,
            materialize_approved_composition=materialize_approved_composition,
            enqueue_next_complete_export_job=enqueue_next_complete_export_job,
            collect_complete_export_artifact=collect_complete_export_artifact,
        )

    graph = StateGraph(ParentGraphState)
    graph.add_node("ValidateRequest", validate_request)
    graph.add_node("LoadArtifactMetadata", load_rehydration)
    graph.add_node("StoragePressureGate", check_storage)
    graph.add_node("StorageUnavailableInterrupt", wait_for_storage)
    graph.add_node("EnqueueInitialMediaJob", enqueue_initial_job)
    graph.add_node("WaitForJobEvent", wait_for_worker)
    graph.add_node("LoadImportAnalysis", load_analysis)
    graph.add_node("AnalysisConfirmationInterrupt", confirm_analysis)
    graph.add_node("EnqueueTimeStretchJob", enqueue_alignment)
    graph.add_node("SelectTimeStretchArtifact", select_stretched_artifact)
    graph.add_node("MaterializeImportRevision", materialize)
    graph.add_node("CompleteTimeStretch", complete_time_stretch)
    graph.add_node("RouteError", route_error)
    if generate_nodes is not None:
        graph.add_node("PlanInputAdapter", generate_nodes.plan_input_adapter)
        graph.add_node("PlanOutputAdapter", generate_nodes.plan_output_adapter)
        graph.add_node("PlanApproval", generate_nodes.approval_interrupt)
        graph.add_node("MaterializeApprovedComposition", generate_nodes.materialize)
        graph.add_node("EnqueueCompleteExportStep", generate_nodes.enqueue_export)
        graph.add_node("WaitForGenerateJobEvent", generate_nodes.wait_for_export)
        graph.add_node("CompleteGenerate", generate_nodes.complete)
    graph.add_edge(START, "ValidateRequest")
    graph.add_conditional_edges(
        "ValidateRequest",
        validation_route,
        {
            "generate": "PlanInputAdapter" if generate_nodes is not None else "RouteError",
            "load": "LoadArtifactMetadata",
            "storage": "StoragePressureGate",
            "error": "RouteError",
        },
    )
    if generate_nodes is not None:
        graph.add_edge("PlanInputAdapter", "PlanOutputAdapter")
        graph.add_conditional_edges(
            "PlanOutputAdapter",
            lambda state: (
                "approval" if state.get("phase") == "waiting_plan_approval" else "error"
            ),
            {"approval": "PlanApproval", "error": "RouteError"},
        )
        graph.add_conditional_edges(
            "PlanApproval",
            lambda state: (
                "materialize"
                if state.get("phase") == "approved"
                else "end"
                if state.get("terminal_status") in {"rejected", "cancelled"}
                else "error"
            ),
            {
                "materialize": "MaterializeApprovedComposition",
                "end": END,
                "error": "RouteError",
            },
        )
        graph.add_conditional_edges(
            "MaterializeApprovedComposition",
            lambda state: "enqueue" if state.get("phase") == "revision_materialized" else "error",
            {"enqueue": "EnqueueCompleteExportStep", "error": "RouteError"},
        )
        graph.add_conditional_edges(
            "EnqueueCompleteExportStep",
            lambda state: (
                "wait"
                if state.get("phase") == "waiting_generate_worker"
                else "complete"
                if state.get("phase") == "completed"
                else "error"
            ),
            {
                "wait": "WaitForGenerateJobEvent",
                "complete": "CompleteGenerate",
                "error": "RouteError",
            },
        )
        graph.add_conditional_edges(
            "WaitForGenerateJobEvent",
            lambda state: (
                "enqueue"
                if state.get("phase") == "export_step_collected"
                else "wait"
                if state.get("phase") == "waiting_generate_worker"
                else "error"
            ),
            {
                "enqueue": "EnqueueCompleteExportStep",
                "wait": "WaitForGenerateJobEvent",
                "error": "RouteError",
            },
        )
        graph.add_edge("CompleteGenerate", END)
    graph.add_conditional_edges(
        "LoadArtifactMetadata",
        lambda state: "storage" if state.get("phase") == "request_validated" else "error",
        {"storage": "StoragePressureGate", "error": "RouteError"},
    )
    graph.add_conditional_edges(
        "StoragePressureGate",
        storage_route,
        {
            "enqueue": "EnqueueInitialMediaJob",
            "human": "StorageUnavailableInterrupt",
            "error": "RouteError",
        },
    )
    graph.add_conditional_edges(
        "StorageUnavailableInterrupt",
        lambda state: "retry" if state.get("phase") == "request_validated" else "error",
        {"retry": "StoragePressureGate", "error": "RouteError"},
    )
    graph.add_edge("EnqueueInitialMediaJob", "WaitForJobEvent")
    graph.add_conditional_edges(
        "WaitForJobEvent",
        worker_route,
        {
            "ingest": "LoadImportAnalysis",
            "stretch": "SelectTimeStretchArtifact",
            "complete": "CompleteTimeStretch",
            "error": "RouteError",
        },
    )
    graph.add_conditional_edges(
        "LoadImportAnalysis",
        analysis_route,
        {
            "human": "AnalysisConfirmationInterrupt",
            "align": "EnqueueTimeStretchJob",
            "materialize": "MaterializeImportRevision",
            "error": "RouteError",
        },
    )
    graph.add_conditional_edges(
        "AnalysisConfirmationInterrupt",
        analysis_route,
        {
            "human": "AnalysisConfirmationInterrupt",
            "align": "EnqueueTimeStretchJob",
            "materialize": "MaterializeImportRevision",
            "error": "RouteError",
        },
    )
    graph.add_conditional_edges(
        "EnqueueTimeStretchJob",
        lambda state: "wait" if state.get("phase") == "waiting_worker" else "error",
        {"wait": "WaitForJobEvent", "error": "RouteError"},
    )
    graph.add_edge("SelectTimeStretchArtifact", "MaterializeImportRevision")
    graph.add_edge("MaterializeImportRevision", END)
    graph.add_edge("CompleteTimeStretch", END)
    graph.add_edge("RouteError", END)
    return graph.compile(checkpointer=checkpointer)
