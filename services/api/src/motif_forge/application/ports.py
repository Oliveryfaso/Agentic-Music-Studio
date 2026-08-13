"""Persistence ports owned by the application layer."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from motif_forge.domain.ai_runs import (
    AIRun,
    AIRunEvent,
    ModelRequestKind,
    ModelRequestReservation,
    PersistedCompositionPlan,
)
from motif_forge.domain.commands import EditorCommand
from motif_forge.domain.media_jobs import (
    AudioArtifact,
    ExportBundleArtifact,
    FeatureArtifact,
    FeatureProfile,
    MediaJob,
    MediaRun,
    RunStatus,
    WorkerEvent,
)
from motif_forge.domain.revisions import (
    CandidateSnapshot,
    PreviewCandidate,
    ProjectBranch,
    ProjectRootState,
    Revision,
)
from motif_forge.domain.storage import (
    StorageCandidateFact,
    StorageDependencyFact,
    StoragePressureDecision,
)
from motif_forge.domain.uploads import UploadPart, UploadSession


@dataclass(frozen=True, slots=True)
class IdempotencyHit:
    resource_id: UUID
    request_hash: str
    result_payload: dict[str, object]


class ProjectTransaction(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def get_idempotency(
        self, *, operation: str, key: str, request_hash: str
    ) -> IdempotencyHit | None: ...

    async def save_idempotency(
        self,
        *,
        operation: str,
        key: str,
        request_hash: str,
        resource_id: UUID,
        result_payload: dict[str, object],
    ) -> None: ...

    async def get_project_root(self, project_id: UUID) -> ProjectRootState | None: ...

    async def insert_project_root(self, *, name: str, root: ProjectRootState) -> None: ...

    async def lock_branch(self, *, project_id: UUID, branch_id: UUID) -> ProjectBranch | None: ...

    async def get_revision(self, revision_id: UUID) -> Revision | None: ...

    async def get_candidate_snapshot(
        self, candidate_snapshot_id: UUID
    ) -> CandidateSnapshot | None: ...

    async def insert_candidate_preview(
        self, *, snapshot: CandidateSnapshot, preview: PreviewCandidate
    ) -> None: ...

    async def lock_preview(self, preview_id: UUID) -> PreviewCandidate | None: ...

    async def update_preview(self, preview: PreviewCandidate) -> None: ...

    async def insert_revision(
        self,
        *,
        revision: Revision,
        commands: tuple[EditorCommand, ...],
        idempotency_key: str,
    ) -> None: ...

    async def insert_materialized_revision(
        self,
        *,
        revision: Revision,
        snapshot: CandidateSnapshot,
        preview: PreviewCandidate,
        idempotency_key: str,
        command_id: UUID,
    ) -> None: ...

    async def insert_approval(
        self,
        *,
        approval_id: UUID,
        preview: PreviewCandidate,
        decision: str,
        actor_id: str,
        payload_hash: str,
        decided_at: datetime,
    ) -> None: ...

    async def advance_branch_head(
        self, *, branch_id: UUID, expected_head_id: UUID, new_head_id: UUID
    ) -> bool: ...

    async def insert_audit_event(
        self,
        *,
        event_id: UUID,
        project_id: UUID,
        actor_id: str,
        event_type: str,
        resource_id: UUID,
        payload: dict[str, object],
    ) -> None: ...


UnitOfWorkFactory = Callable[[], ProjectTransaction]


class MediaJobTransaction(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def find_media_job_by_key(
        self, *, project_id: UUID, job_type: str, idempotency_key: str
    ) -> MediaJob | None: ...

    async def get_media_job(self, job_id: UUID, *, for_update: bool = False) -> MediaJob | None: ...

    async def get_revision(self, revision_id: UUID) -> Revision | None: ...

    async def get_audio_artifact(self, artifact_id: UUID) -> AudioArtifact | None: ...

    async def get_export_bundle_artifact(
        self, artifact_id: UUID
    ) -> ExportBundleArtifact | None: ...

    async def get_feature_artifact(self, artifact_id: UUID) -> FeatureArtifact | None: ...

    async def get_feature_artifact_for_source(
        self, source_artifact_id: UUID, feature_profile: FeatureProfile
    ) -> FeatureArtifact | None: ...

    async def list_feature_artifacts_for_source(
        self, source_artifact_id: UUID
    ) -> tuple[FeatureArtifact, ...]: ...

    async def claim_media_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> MediaJob | None: ...

    async def cancel_media_job(
        self, job_id: UUID, *, actor_id: str, now: datetime
    ) -> MediaJob | None: ...

    async def heartbeat_media_job(
        self,
        job_id: UUID,
        *,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        progress_percent: int,
    ) -> bool: ...

    async def has_inbox_receipt(self, *, consumer: str, event_id: str) -> bool: ...

    async def insert_media_run_job(
        self,
        *,
        run: MediaRun,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> None: ...

    async def lock_audio_artifact(self, artifact_id: UUID) -> AudioArtifact | None: ...

    async def lock_feature_artifact(self, artifact_id: UUID) -> FeatureArtifact | None: ...

    async def insert_rehydration_run_job(
        self,
        *,
        target_artifact_id: UUID,
        run: MediaRun,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> None: ...

    async def insert_feature_rehydration_run_job(
        self,
        *,
        target_artifact_id: UUID,
        run: MediaRun,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> None: ...

    async def append_media_job_to_run(
        self,
        *,
        expected_thread_id: str,
        job: MediaJob,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
    ) -> bool: ...

    async def apply_worker_event(
        self,
        *,
        event: WorkerEvent,
        updated_job: MediaJob,
        run_status: RunStatus,
        artifact: AudioArtifact | FeatureArtifact | ExportBundleArtifact | None,
        feature_artifacts: tuple[FeatureArtifact, ...],
        validated_source_artifact: AudioArtifact | None,
        consumer: str,
        inbox_receipt_id: UUID,
        run_event_id: UUID,
        job_event_id: UUID,
        outbox_event_id: UUID,
        outbox_topic: str,
    ) -> AudioArtifact | FeatureArtifact | ExportBundleArtifact | None: ...


MediaJobUnitOfWorkFactory = Callable[[], MediaJobTransaction]


class UploadTransaction(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def project_exists(self, project_id: UUID) -> bool: ...

    async def insert_upload_session(self, upload: UploadSession) -> None: ...

    async def find_upload_session_by_key(
        self, *, project_id: UUID, idempotency_key: str
    ) -> UploadSession | None: ...

    async def get_upload_session(
        self, upload_id: UUID, *, for_update: bool = False
    ) -> UploadSession | None: ...

    async def update_upload_session(self, upload: UploadSession) -> None: ...

    async def get_upload_part(self, upload_id: UUID, part_number: int) -> UploadPart | None: ...

    async def insert_upload_part(self, part: UploadPart) -> None: ...

    async def register_source_artifact(self, artifact: AudioArtifact) -> AudioArtifact: ...


UploadUnitOfWorkFactory = Callable[[], UploadTransaction]


class StorageTransaction(Protocol):
    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def load_storage_facts(
        self,
        *,
        project_id: UUID,
        dependency_artifact_ids: tuple[UUID, ...],
        now: datetime,
    ) -> tuple[
        int,
        int,
        int,
        tuple[StorageDependencyFact, ...],
        tuple[StorageCandidateFact, ...],
    ]: ...

    async def record_storage_decision(self, decision: StoragePressureDecision) -> None: ...

    async def lock_artifact_for_eviction(
        self, artifact_id: UUID
    ) -> AudioArtifact | FeatureArtifact | None: ...

    async def mark_artifact_evicted(
        self, *, artifact_id: UUID, operation_id: str, evicted_at: datetime
    ) -> bool: ...


StorageUnitOfWorkFactory = Callable[[], StorageTransaction]


class AIRunTransaction(Protocol):
    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...
    async def get_ai_run_idempotency(
        self, *, project_id: UUID, key: str
    ) -> IdempotencyHit | None: ...
    async def create_ai_run(
        self, *, run: AIRun, created_event: AIRunEvent, outbox_event_id: UUID, request_hash: str
    ) -> None: ...
    async def read_ai_run(self, run_id: UUID) -> AIRun: ...
    async def persist_composition_plan(
        self, plan: PersistedCompositionPlan
    ) -> PersistedCompositionPlan: ...
    async def record_ai_run_event(self, event: AIRunEvent) -> AIRunEvent: ...
    async def list_ai_run_events(
        self, run_id: UUID, *, after_sequence: int
    ) -> tuple[AIRunEvent, ...]: ...
    async def request_ai_run_action(
        self,
        *,
        run_id: UUID,
        action: str,
        expected_version: int,
        idempotency_key: str,
        outbox_event_id: UUID,
        now: datetime,
    ) -> AIRun: ...
    async def reserve_model_request(
        self, *, run_id: UUID, kind: ModelRequestKind, reservation_id: UUID, now: datetime
    ) -> ModelRequestReservation: ...
    async def record_model_usage(
        self,
        *,
        run_id: UUID,
        reservation_id: UUID,
        provider_operation_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        now: datetime,
    ) -> ModelRequestReservation: ...


AIRunUnitOfWorkFactory = Callable[[], AIRunTransaction]
