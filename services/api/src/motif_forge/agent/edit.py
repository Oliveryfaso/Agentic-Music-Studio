"""Finite Parent Graph branch for bounded, proposal-only AI edits."""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict, cast
from uuid import NAMESPACE_URL, UUID, uuid5

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import Field

from motif_forge.application.candidate_previews import (
    CandidatePreviewCursor,
    EnqueueCandidatePreviewRequest,
)
from motif_forge.application.edit_decisions import EditPreviewDecision
from motif_forge.application.errors import ApplicationError
from motif_forge.domain.ai_runs import (
    EDIT_RUN_STATE_SCHEMA_VERSION,
    PARENT_GRAPH_TOPOLOGY_VERSION,
    EditRunRequest,
)
from motif_forge.domain.commands import (
    Selection,
    SetTrackParamCommand,
    SetTrackParamPayload,
)
from motif_forge.domain.editing import (
    EditPatchProposal,
    EditVersionRefs,
    LockedRangeRef,
    simulate_edit_patch,
)
from motif_forge.domain.errors import DomainValidationError
from motif_forge.domain.ir import ArrangementIR, DomainModel, Section, Track
from motif_forge.domain.media_jobs import WorkerResumePayload
from motif_forge.domain.revisions import ChangeImpact


class BoundedEditContext(DomainModel):
    project_id: UUID
    branch_id: UUID | None = None
    base_revision_id: UUID | None = None
    intent: str
    selection: Selection
    selected_tracks: tuple[Track, ...] = Field(min_length=1)
    adjacent_sections: tuple[Section, ...] = ()
    locked_ranges: tuple[LockedRangeRef, ...] = ()
    contains_full_arrangement: bool = False
    base_arrangement: ArrangementIR = Field(exclude=True)

    @classmethod
    def from_arrangement(
        cls, arrangement: ArrangementIR, request: EditRunRequest
    ) -> BoundedEditContext:
        selected = set(request.selection.track_ids)
        tracks = tuple(track for track in arrangement.tracks if track.track_id in selected)
        if not tracks:
            raise ApplicationError("EDIT_SELECTION_INVALID", "selection has no matching tracks")
        start = request.selection.start_tick or 0
        end = request.selection.end_tick or max(1, arrangement.duration_tick)
        adjacent = tuple(
            section
            for section in arrangement.sections
            if section.start_tick < end + arrangement.bar_ticks * 2
            and start - arrangement.bar_ticks * 2 < section.end_tick
        )
        return cls(
            project_id=arrangement.project_id,
            intent=request.intent,
            selection=request.selection,
            selected_tracks=tracks,
            adjacent_sections=adjacent,
            locked_ranges=request.locked_ranges,
            base_arrangement=arrangement,
        )


class EditPlanner(Protocol):
    async def __call__(self, context: BoundedEditContext) -> EditPatchProposal: ...


class EditRouteHandler(Protocol):
    async def __call__(
        self, proposal: EditPatchProposal, simulation: object, state: dict[str, object]
    ) -> dict[str, object]: ...


class EditDecisionHandler(Protocol):
    async def __call__(self, decision: EditPreviewDecision) -> dict[str, object]: ...


class CandidatePreviewEnqueuer(Protocol):
    async def __call__(
        self, request: EnqueueCandidatePreviewRequest
    ) -> CandidatePreviewCursor: ...


class CandidatePreviewCollector(Protocol):
    async def __call__(
        self, cursor: CandidatePreviewCursor, completed_job_id: UUID
    ) -> CandidatePreviewCursor: ...


class PreviewArtifactAttacher(Protocol):
    async def __call__(
        self, cursor: CandidatePreviewCursor, state: dict[str, object]
    ) -> dict[str, object]: ...


class FallbackEditPlanner:
    """Small no-key allowlist: explicit track gain changes only."""

    _GAIN = re.compile(r"(?:降低|减小|lower|reduce).*?(\d+(?:\.\d+)?)\s*dB", re.I)
    _PRESET = re.compile(r"\b(builtin:[a-z0-9-]+)\b", re.I)
    _REVIEWED_PRESETS = frozenset(
        {
            "builtin:warm-pad", "builtin:glass-pluck", "builtin:sub-bass",
            "builtin:soft-pulse", "builtin:poly-synth", "builtin:short-pluck",
            "builtin:mono-bass", "builtin:drum-machine", "builtin:viola",
            "builtin:violin", "builtin:cello", "builtin:pizz-cello",
            "builtin:jazz-piano", "builtin:tenor-lead", "builtin:upright-bass",
            "builtin:brush-kit",
        }
    )

    async def __call__(self, context: BoundedEditContext) -> EditPatchProposal:
        match = self._GAIN.search(context.intent)
        preset_match = self._PRESET.search(context.intent)
        preset = preset_match.group(1).lower() if preset_match else None
        if match is None and preset not in self._REVIEWED_PRESETS:
            raise ApplicationError(
                "EDIT_FALLBACK_UNSUPPORTED", "edit is outside the deterministic allowlist"
            )
        track = context.selected_tracks[0]
        project_id = context.project_id
        branch_id = context.branch_id or UUID(int=0)
        base_revision_id = context.base_revision_id or UUID(int=0)
        identity = f"{project_id}:{branch_id}:{base_revision_id}:{context.intent}:{track.track_id}"
        if match is not None:
            amount = float(match.group(1))
            payload = SetTrackParamPayload(
                track_id=track.track_id,
                parameter="gain_db",
                value=max(-60.0, track.gain_db - amount),
            )
            impact = ChangeImpact.L0
            expected_effect = f"lower selected track by {amount:g} dB"
            rationale = "deterministic explicit gain adjustment"
        else:
            assert preset is not None
            payload = SetTrackParamPayload(
                track_id=track.track_id,
                parameter="instrument_ref",
                value=preset,
            )
            impact = ChangeImpact.L2
            expected_effect = f"switch selected track to reviewed preset {preset}"
            rationale = "deterministic reviewed local-catalog timbre selection"
        command = SetTrackParamCommand(
            command_id=uuid5(NAMESPACE_URL, f"{identity}:gain"),
            actor_kind="agent",
            client_sequence=0,
            selection=context.selection,
            payload=payload,
        )
        return EditPatchProposal(
            proposal_id=uuid5(NAMESPACE_URL, f"{identity}:proposal"),
            project_id=project_id,
            branch_id=branch_id,
            base_revision_id=base_revision_id,
            selection=context.selection,
            locked_ranges=context.locked_ranges,
            commands=(command,),
            rationale=rationale,
            evidence_refs=(f"track:{track.track_id}",),
            expected_effect=expected_effect,
            predicted_change_impact=impact,
            confidence=1.0,
            versions=EditVersionRefs(prompt="fallback-edit.v1", model="deterministic"),
        )


ContextLoader = Callable[[EditRunRequest], BoundedEditContext | Awaitable[BoundedEditContext]]


@dataclass(frozen=True)
class EditGraphDependencies:
    load_context: ContextLoader
    planner: EditPlanner | None
    auto_commit: EditRouteHandler | None = None
    create_preview: EditRouteHandler | None = None
    enqueue_candidate_preview: CandidatePreviewEnqueuer | None = None
    collect_candidate_preview: CandidatePreviewCollector | None = None
    attach_preview_artifact: PreviewArtifactAttacher | None = None
    apply_decision: EditDecisionHandler | None = None


class EditGraphState(TypedDict, total=False):
    thread_id: str
    run_id: str
    project_id: str
    branch_id: str
    base_revision_id: str
    state_schema_version: str
    graph_topology_version: str
    operation: str
    phase: str
    edit_request: dict[str, object]
    base_arrangement: dict[str, object]
    planner_context: dict[str, object]
    proposal: dict[str, object]
    simulation: dict[str, object]
    edit_route: str
    error_code: str
    terminal_status: str
    materialized_revision_id: str
    pending_preview_id: str
    candidate_snapshot_id: str
    candidate_content_hash: str
    candidate_preview_cursor: dict[str, object]
    pending_job_id: str
    preview_artifact_id: str
    last_resume_event_id: str


def initial_edit_state(
    *,
    thread_id: str,
    project_id: UUID,
    branch_id: UUID,
    base_revision_id: UUID,
    request: EditRunRequest,
    base_arrangement: ArrangementIR,
    run_id: UUID | None = None,
) -> EditGraphState:
    return EditGraphState(
        thread_id=thread_id,
        run_id=str(run_id) if run_id is not None else "",
        project_id=str(project_id),
        branch_id=str(branch_id),
        base_revision_id=str(base_revision_id),
        state_schema_version=EDIT_RUN_STATE_SCHEMA_VERSION,
        graph_topology_version=PARENT_GRAPH_TOPOLOGY_VERSION,
        operation="edit",
        phase="received",
        edit_request=request.model_dump(mode="json"),
        base_arrangement=base_arrangement.model_dump(mode="json"),
    )


def build_edit_subgraph(
    dependencies: EditGraphDependencies,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    async def plan_and_simulate(state: EditGraphState) -> EditGraphState:
        try:
            request = EditRunRequest.model_validate_json(
                json.dumps(state["edit_request"]), strict=True
            )
            loaded = dependencies.load_context(request)
            context = await loaded if inspect.isawaitable(loaded) else loaded
            context = context.model_copy(
                update={
                    "branch_id": UUID(state["branch_id"]),
                    "base_revision_id": UUID(state["base_revision_id"]),
                }
            )
            planner = dependencies.planner or FallbackEditPlanner()
            proposal = await planner(context)
            simulation = simulate_edit_patch(context.base_arrangement, proposal)
            return EditGraphState(
                phase="simulated",
                planner_context=context.model_dump(mode="json"),
                proposal=proposal.model_dump(mode="json"),
                simulation=simulation.model_dump(mode="json"),
                edit_route=(
                    "auto_commit"
                    if simulation.actual_change_impact < ChangeImpact.L2
                    else "preview_required"
                ),
            )
        except (ApplicationError, DomainValidationError, ValueError) as exc:
            code = exc.code if isinstance(exc, ApplicationError) else "EDIT_SIMULATION_FAILED"
            return EditGraphState(phase="failed", error_code=code, edit_route="failed")

    async def auto_commit(state: EditGraphState) -> EditGraphState:
        if dependencies.auto_commit is None:
            return EditGraphState(phase="simulated")
        proposal = EditPatchProposal.model_validate_json(
            json.dumps(state["proposal"]), strict=True
        )
        result = await dependencies.auto_commit(proposal, state["simulation"], dict(state))
        return cast(
            EditGraphState,
            {"phase": "committed", "terminal_status": "succeeded", **result},
        )

    async def create_preview(state: EditGraphState) -> EditGraphState:
        if dependencies.create_preview is None:
            return EditGraphState(phase="simulated")
        proposal = EditPatchProposal.model_validate_json(
            json.dumps(state["proposal"]), strict=True
        )
        result = await dependencies.create_preview(proposal, state["simulation"], dict(state))
        return cast(EditGraphState, {"phase": "preview_created", **result})

    async def enqueue_preview(state: EditGraphState) -> EditGraphState:
        if dependencies.enqueue_candidate_preview is None:
            return EditGraphState(phase="failed", error_code="EDIT_PREVIEW_RENDER_NOT_CONFIGURED")
        cursor = await dependencies.enqueue_candidate_preview(
            EnqueueCandidatePreviewRequest(
                project_id=UUID(state["project_id"]),
                candidate_snapshot_id=UUID(state["candidate_snapshot_id"]),
                expected_candidate_content_hash=state["candidate_content_hash"],
                thread_id=state["thread_id"],
                seed=0,
                idempotency_key=f"edit-run:{state['run_id']}:preview-render",
            )
        )
        return EditGraphState(
            phase="waiting_worker",
            pending_job_id=str(cursor.job_id),
            candidate_preview_cursor=cursor.model_dump(mode="json"),
        )

    async def wait_for_preview(state: EditGraphState) -> EditGraphState:
        raw = interrupt(
            {
                "kind": "worker_job",
                "job_id": state["pending_job_id"],
                "phase": "waiting_worker",
            }
        )
        payload = WorkerResumePayload.model_validate_json(json.dumps(raw), strict=True)
        cursor = CandidatePreviewCursor.model_validate_json(
            json.dumps(state["candidate_preview_cursor"]), strict=True
        )
        if (
            payload.job_id != cursor.job_id
            or payload.run_id != cursor.media_run_id
            or payload.thread_id != state["thread_id"]
        ):
            return EditGraphState(
                phase="failed", error_code="EDIT_PREVIEW_WORKER_IDENTITY_MISMATCH"
            )
        if payload.status != "succeeded":
            return EditGraphState(
                phase="failed", error_code=payload.error_code or "EDIT_PREVIEW_RENDER_FAILED"
            )
        return EditGraphState(
            phase="preview_worker_ready",
            pending_job_id="",
            last_resume_event_id=payload.resume_event_id or "",
        )

    async def collect_preview(state: EditGraphState) -> EditGraphState:
        if (
            dependencies.collect_candidate_preview is None
            or dependencies.attach_preview_artifact is None
        ):
            return EditGraphState(phase="failed", error_code="EDIT_PREVIEW_RENDER_NOT_CONFIGURED")
        cursor = CandidatePreviewCursor.model_validate_json(
            json.dumps(state["candidate_preview_cursor"]), strict=True
        )
        completed = await dependencies.collect_candidate_preview(cursor, cursor.job_id)
        if completed.preview_artifact_id is None:
            return EditGraphState(phase="failed", error_code="EDIT_PREVIEW_ARTIFACT_REQUIRED")
        attached = await dependencies.attach_preview_artifact(completed, dict(state))
        return cast(EditGraphState, {"phase": "waiting_edit_approval", **attached})

    async def approve_preview(state: EditGraphState) -> EditGraphState:
        if dependencies.apply_decision is None:
            return EditGraphState(phase="waiting_edit_approval")
        raw = interrupt(
            {
                "kind": "edit_preview_approval",
                "preview_id": state.get("pending_preview_id"),
                "candidate_content_hash": state.get("candidate_content_hash"),
            }
        )
        decision = EditPreviewDecision.model_validate_json(json.dumps(raw), strict=True)
        if str(decision.preview_id) != state.get("pending_preview_id"):
            return EditGraphState(
                phase="failed",
                error_code="EDIT_PREVIEW_IDENTITY_CONFLICT",
                terminal_status="failed",
            )
        result = await dependencies.apply_decision(decision)
        if decision.action == "approve":
            return cast(
                EditGraphState,
                {"phase": "committed", "terminal_status": "succeeded", **result},
            )
        return cast(
            EditGraphState,
            {
                "phase": "cancelled" if decision.action == "cancel" else "rejected",
                "terminal_status": decision.action,
                **result,
            },
        )

    def route(state: EditGraphState) -> str:
        if state.get("edit_route") == "auto_commit" and dependencies.auto_commit is not None:
            return "commit"
        if (
            state.get("edit_route") == "preview_required"
            and dependencies.create_preview is not None
        ):
            return "preview"
        return "end"

    graph = StateGraph(EditGraphState)
    graph.add_node("edit_plan_and_simulate", plan_and_simulate)
    graph.add_node("edit_auto_commit", auto_commit)
    graph.add_node("edit_create_preview", create_preview)
    graph.add_node("edit_enqueue_preview", enqueue_preview)
    graph.add_node("edit_wait_for_preview", wait_for_preview)
    graph.add_node("edit_collect_preview", collect_preview)
    graph.add_node("edit_preview_approval", approve_preview)
    graph.add_edge(START, "edit_plan_and_simulate")
    graph.add_conditional_edges(
        "edit_plan_and_simulate",
        route,
        {"commit": "edit_auto_commit", "preview": "edit_create_preview", "end": END},
    )
    graph.add_edge("edit_auto_commit", END)
    if dependencies.apply_decision is None:
        graph.add_edge("edit_create_preview", END)
    else:
        graph.add_edge("edit_create_preview", "edit_enqueue_preview")
        graph.add_edge("edit_enqueue_preview", "edit_wait_for_preview")
        graph.add_conditional_edges(
            "edit_wait_for_preview",
            lambda state: "collect" if state.get("phase") == "preview_worker_ready" else "end",
            {"collect": "edit_collect_preview", "end": END},
        )
        graph.add_edge("edit_collect_preview", "edit_preview_approval")
        graph.add_edge("edit_preview_approval", END)
    return graph.compile(checkpointer=checkpointer)
