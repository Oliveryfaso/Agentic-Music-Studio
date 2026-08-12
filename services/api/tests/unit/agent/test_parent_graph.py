from __future__ import annotations

from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from motif_forge.agent.parent_graph import (
    PARENT_IMPORT_RUN_TYPE,
    PARENT_REHYDRATE_RUN_TYPE,
    PARENT_TIME_STRETCH_RUN_TYPE,
    build_parent_graph,
    initial_artifact_rehydrate_state,
    initial_import_state,
    initial_time_stretch_state,
)
from motif_forge.application.imports import ImportAnalysisContext
from motif_forge.application.media_jobs import (
    EnqueueFollowupMediaJobRequest,
    EnqueueMediaJobRequest,
    EnqueueMediaJobResult,
    StartArtifactRehydrationRequest,
)
from motif_forge.domain.media_jobs import (
    ImportedAudioAnalysis,
    JobStatus,
    RehydrateJobPayload,
    TimeStretchJobPayload,
)
from motif_forge.domain.storage import StoragePressureDecision, StorageRoute


class FakeEnqueuer:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.job_id = uuid4()
        self.requests: list[EnqueueMediaJobRequest] = []

    async def __call__(self, request: EnqueueMediaJobRequest) -> EnqueueMediaJobResult:
        self.requests.append(request)
        return EnqueueMediaJobResult(
            run_id=self.run_id,
            job_id=self.job_id,
            status=JobStatus.QUEUED,
        )


class FakeMaterializer:
    def __init__(self) -> None:
        self.revision_id = uuid4()
        self.requests: list[object] = []

    async def __call__(self, request: object) -> object:
        self.requests.append(request)

        class Result:
            revision_id = self.revision_id

        return Result()


class FakeImportContextLoader:
    def __init__(self, *, bpm: float | None = 120.0, bpm_confidence: float = 0.9) -> None:
        self.bpm = bpm
        self.bpm_confidence = bpm_confidence

    async def __call__(self, **kwargs: object) -> ImportAnalysisContext:
        return ImportAnalysisContext(
            normalized_artifact_id=kwargs["normalized_artifact_id"],
            duration_seconds=8.0,
            project_bpm=120.0,
            analysis=ImportedAudioAnalysis(
                bpm=self.bpm,
                bpm_confidence=self.bpm_confidence if self.bpm is not None else 0.0,
                key_tonic="C",
                key_mode="major",
                key_confidence=0.8,
                analyzed_seconds=8.0,
            ),
        )


class FakeFollowupEnqueuer:
    def __init__(self, run_id: object) -> None:
        self.run_id = run_id
        self.job_id = uuid4()
        self.requests: list[EnqueueFollowupMediaJobRequest] = []

    async def __call__(self, request: EnqueueFollowupMediaJobRequest) -> EnqueueMediaJobResult:
        self.requests.append(request)
        return EnqueueMediaJobResult(
            run_id=request.run_id,
            job_id=self.job_id,
            status=JobStatus.QUEUED,
        )


class FakeRehydrationEnqueuer:
    def __init__(self) -> None:
        self.run_id = uuid4()
        self.job_id = uuid4()
        self.requests: list[StartArtifactRehydrationRequest] = []

    async def __call__(self, request: StartArtifactRehydrationRequest) -> EnqueueMediaJobResult:
        self.requests.append(request)
        return EnqueueMediaJobResult(
            run_id=self.run_id,
            job_id=self.job_id,
            status=JobStatus.QUEUED,
        )


class FakeRehydrationLoader:
    def __init__(self, project_id: object, payload: RehydrateJobPayload) -> None:
        self.project_id = project_id
        self.payload = payload

    async def __call__(self, **_: object) -> tuple[object, RehydrateJobPayload]:
        return self.project_id, self.payload


class SequencedStorageGate:
    def __init__(self, routes: list[StorageRoute]) -> None:
        self.routes = routes
        self.calls: list[str] = []
        self.dependencies: list[tuple[object, ...]] = []

    async def __call__(self, **kwargs: object) -> StoragePressureDecision:
        operation_id = str(kwargs["operation_id"])
        self.calls.append(operation_id)
        self.dependencies.append(tuple(kwargs["dependency_artifact_ids"]))
        route = self.routes.pop(0)
        return StoragePressureDecision(
            operation_id=operation_id,
            project_id=kwargs["project_id"],
            route=route,
            matched_rule_id="STO-001" if route is StorageRoute.WAIT_FOR_STORAGE else "STO-010",
            explanation_code=(
                "STORAGE_ROOT_NOT_READY"
                if route is StorageRoute.WAIT_FOR_STORAGE
                else "STORAGE_CAPACITY_AVAILABLE"
            ),
            error_code=(
                "ARTIFACT_ROOT_UNAVAILABLE" if route is StorageRoute.WAIT_FOR_STORAGE else None
            ),
        )


@pytest.mark.asyncio
async def test_parent_time_stretch_waits_and_resumes_same_checkpoint() -> None:
    enqueuer = FakeEnqueuer()
    graph = build_parent_graph(enqueuer, checkpointer=MemorySaver())
    thread_id = f"parent-{uuid4().hex}"
    state = initial_time_stretch_state(
        thread_id=thread_id,
        project_id=uuid4(),
        request=TimeStretchJobPayload(
            source_artifact_id=uuid4(),
            source_bpm=120,
            target_bpm=96,
        ),
    )
    config = {"configurable": {"thread_id": thread_id}}

    interrupted = await graph.ainvoke(state, config)

    assert interrupted["phase"] == "waiting_worker"
    assert interrupted["pending_job_id"] == str(enqueuer.job_id)
    assert len(enqueuer.requests) == 1
    assert enqueuer.requests[0].run_type == PARENT_TIME_STRETCH_RUN_TYPE
    assert enqueuer.requests[0].input_payload["preserve_pitch"] is True

    artifact_id = uuid4()
    completed = await graph.ainvoke(
        Command(
            resume={
                "schema_version": "worker-resume.v1",
                "run_id": str(enqueuer.run_id),
                "thread_id": thread_id,
                "run_type": PARENT_TIME_STRETCH_RUN_TYPE,
                "resume_event_id": "worker-event-1",
                "job_id": str(enqueuer.job_id),
                "status": "succeeded",
                "artifact_id": str(artifact_id),
                "error_code": None,
            }
        ),
        config,
    )

    assert completed["terminal_status"] == "succeeded"
    assert completed["artifact_refs"] == [str(artifact_id)]
    assert len(enqueuer.requests) == 1


@pytest.mark.asyncio
async def test_parent_time_stretch_routes_terminal_worker_failure_without_model() -> None:
    enqueuer = FakeEnqueuer()
    graph = build_parent_graph(enqueuer, checkpointer=MemorySaver())
    thread_id = f"parent-{uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke(
        initial_time_stretch_state(
            thread_id=thread_id,
            project_id=uuid4(),
            request=TimeStretchJobPayload(
                source_artifact_id=uuid4(), source_bpm=120, target_bpm=140
            ),
        ),
        config,
    )

    failed = await graph.ainvoke(
        Command(
            resume={
                "schema_version": "worker-resume.v1",
                "run_id": str(enqueuer.run_id),
                "thread_id": thread_id,
                "run_type": PARENT_TIME_STRETCH_RUN_TYPE,
                "resume_event_id": "worker-event-failed",
                "job_id": str(enqueuer.job_id),
                "status": "failed_terminal",
                "artifact_id": None,
                "error_code": "TIME_STRETCH_ENGINE_FAILED",
            }
        ),
        config,
    )

    assert failed["terminal_status"] == "failed"
    assert failed["error_code"] == "TIME_STRETCH_ENGINE_FAILED"


@pytest.mark.asyncio
async def test_parent_waits_for_external_root_then_resumes_same_checkpoint() -> None:
    enqueuer = FakeEnqueuer()
    storage = SequencedStorageGate([StorageRoute.WAIT_FOR_STORAGE, StorageRoute.PROCEED])
    graph = build_parent_graph(
        enqueuer,
        checkpointer=MemorySaver(),
        storage_pressure_gate=storage,
    )
    thread_id = f"storage-{uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}
    source_artifact_id = uuid4()
    waiting = await graph.ainvoke(
        initial_time_stretch_state(
            thread_id=thread_id,
            project_id=uuid4(),
            request=TimeStretchJobPayload(
                source_artifact_id=source_artifact_id, source_bpm=120, target_bpm=100
            ),
        ),
        config,
    )

    assert waiting["phase"] == "storage_wait_required"
    assert waiting["__interrupt__"][0].value["kind"] == "storage_unavailable"
    assert enqueuer.requests == []

    resumed = await graph.ainvoke(Command(resume={"action": "retry"}), config)

    assert resumed["phase"] == "waiting_worker"
    assert len(enqueuer.requests) == 1
    assert storage.calls[0] == storage.calls[1]
    assert storage.dependencies == [(source_artifact_id,), (source_artifact_id,)]


@pytest.mark.asyncio
async def test_parent_rejects_invalid_request_before_enqueue() -> None:
    enqueuer = FakeEnqueuer()
    graph = build_parent_graph(enqueuer)
    invalid_state = {
        "thread_id": "invalid-request",
        "project_id": "not-a-uuid",
        "operation": "time_stretch",
        "graph_topology_version": "motif-forge-parent.v1",
        "state_schema_version": "motif-forge-parent-state.v1",
        "request_payload": {},
        "phase": "received",
    }

    result = await graph.ainvoke(invalid_state)

    assert result["terminal_status"] == "failed"
    assert result["error_code"] == "PARENT_REQUEST_INVALID"
    assert enqueuer.requests == []


@pytest.mark.asyncio
async def test_parent_rehydrate_uses_source_dependency_and_same_worker_wait() -> None:
    enqueuer = FakeEnqueuer()
    rehydration = FakeRehydrationEnqueuer()
    storage = SequencedStorageGate([StorageRoute.PROCEED])
    project_id = uuid4()
    source_id = uuid4()
    target_id = uuid4()
    payload = RehydrateJobPayload(
        target_artifact_id=target_id,
        source_artifact_id=source_id,
        source_bpm=120,
        target_bpm=100,
        expected_content_hash="1" * 64,
        expected_recipe_hash="2" * 64,
    )
    graph = build_parent_graph(
        enqueuer,
        checkpointer=MemorySaver(),
        enqueue_artifact_rehydration=rehydration,
        load_artifact_rehydration=FakeRehydrationLoader(project_id, payload),
        storage_pressure_gate=storage,
    )
    thread_id = f"rehydrate-{uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}
    state = initial_artifact_rehydrate_state(
        thread_id=thread_id,
        artifact_id=target_id,
        idempotency_key="rehydrate-public-key",
    )

    waiting = await graph.ainvoke(state, config)

    assert waiting["phase"] == "waiting_worker"
    assert storage.dependencies == [(source_id,)]
    assert enqueuer.requests == []
    assert rehydration.requests[0].artifact_id == target_id

    completed = await graph.ainvoke(
        Command(
            resume={
                "schema_version": "worker-resume.v1",
                "run_id": str(rehydration.run_id),
                "thread_id": thread_id,
                "run_type": PARENT_REHYDRATE_RUN_TYPE,
                "resume_event_id": "rehydrate-worker-complete",
                "job_id": str(rehydration.job_id),
                "status": "succeeded",
                "artifact_id": str(target_id),
                "error_code": None,
            }
        ),
        config,
    )
    assert completed["terminal_status"] == "succeeded"
    assert completed["artifact_refs"] == [str(target_id)]


@pytest.mark.asyncio
async def test_parent_import_uses_same_worker_wait_and_resume_path() -> None:
    enqueuer = FakeEnqueuer()
    materializer = FakeMaterializer()
    graph = build_parent_graph(
        enqueuer,
        checkpointer=MemorySaver(),
        materialize_import=materializer,
        load_import_context=FakeImportContextLoader(),
    )
    thread_id = f"import-{uuid4().hex}"
    state = initial_import_state(
        thread_id=thread_id,
        project_id=uuid4(),
        branch_id=uuid4(),
        base_revision_id=uuid4(),
        source_artifact_id=uuid4(),
        idempotency_key="import-request-001",
    )
    config = {"configurable": {"thread_id": thread_id}}

    interrupted = await graph.ainvoke(state, config)

    assert interrupted["phase"] == "waiting_worker"
    assert enqueuer.requests[0].run_type == PARENT_IMPORT_RUN_TYPE
    assert enqueuer.requests[0].job_type.value == "ingest"

    artifact_id = uuid4()
    completed = await graph.ainvoke(
        Command(
            resume={
                "schema_version": "worker-resume.v1",
                "run_id": str(enqueuer.run_id),
                "thread_id": thread_id,
                "run_type": PARENT_IMPORT_RUN_TYPE,
                "resume_event_id": "worker-import-completed",
                "job_id": str(enqueuer.job_id),
                "status": "succeeded",
                "artifact_id": str(artifact_id),
                "error_code": None,
            }
        ),
        config,
    )

    assert completed["terminal_status"] == "succeeded"
    assert completed["artifact_refs"] == [str(artifact_id)]
    assert completed["materialized_revision_id"] == str(materializer.revision_id)
    assert len(materializer.requests) == 1


@pytest.mark.asyncio
async def test_parent_import_low_confidence_interrupts_then_skips_alignment() -> None:
    enqueuer = FakeEnqueuer()
    materializer = FakeMaterializer()
    graph = build_parent_graph(
        enqueuer,
        checkpointer=MemorySaver(),
        materialize_import=materializer,
        load_import_context=FakeImportContextLoader(bpm_confidence=0.2),
    )
    thread_id = f"import-{uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke(
        initial_import_state(
            thread_id=thread_id,
            project_id=uuid4(),
            branch_id=uuid4(),
            base_revision_id=uuid4(),
            source_artifact_id=uuid4(),
            idempotency_key="import-low-confidence",
        ),
        config,
    )
    waiting = await graph.ainvoke(
        Command(
            resume={
                "schema_version": "worker-resume.v1",
                "run_id": str(enqueuer.run_id),
                "thread_id": thread_id,
                "run_type": PARENT_IMPORT_RUN_TYPE,
                "resume_event_id": "ingest-low-confidence",
                "job_id": str(enqueuer.job_id),
                "status": "succeeded",
                "artifact_id": str(uuid4()),
                "error_code": None,
            }
        ),
        config,
    )

    assert waiting["phase"] == "analysis_confirmation_required"
    assert waiting["__interrupt__"][0].value["kind"] == "import_analysis_confirmation"

    completed = await graph.ainvoke(Command(resume={"action": "skip_alignment"}), config)
    assert completed["terminal_status"] == "succeeded"
    assert len(materializer.requests) == 1


@pytest.mark.asyncio
async def test_parent_import_unknown_bpm_can_skip_alignment_without_inventing_value() -> None:
    enqueuer = FakeEnqueuer()
    materializer = FakeMaterializer()
    graph = build_parent_graph(
        enqueuer,
        checkpointer=MemorySaver(),
        materialize_import=materializer,
        load_import_context=FakeImportContextLoader(bpm=None),
    )
    thread_id = f"import-{uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke(
        initial_import_state(
            thread_id=thread_id,
            project_id=uuid4(),
            branch_id=uuid4(),
            base_revision_id=uuid4(),
            source_artifact_id=uuid4(),
            idempotency_key="import-unknown-bpm",
        ),
        config,
    )
    waiting = await graph.ainvoke(
        Command(
            resume={
                "schema_version": "worker-resume.v1",
                "run_id": str(enqueuer.run_id),
                "thread_id": thread_id,
                "run_type": PARENT_IMPORT_RUN_TYPE,
                "resume_event_id": "ingest-unknown-bpm",
                "job_id": str(enqueuer.job_id),
                "status": "succeeded",
                "artifact_id": str(uuid4()),
                "error_code": None,
            }
        ),
        config,
    )
    assert waiting["phase"] == "analysis_confirmation_required"

    completed = await graph.ainvoke(Command(resume={"action": "skip_alignment"}), config)
    assert completed["terminal_status"] == "succeeded"
    assert len(materializer.requests) == 1


@pytest.mark.asyncio
async def test_parent_import_confident_mismatch_appends_stretch_to_same_run() -> None:
    enqueuer = FakeEnqueuer()
    followup = FakeFollowupEnqueuer(enqueuer.run_id)
    materializer = FakeMaterializer()
    graph = build_parent_graph(
        enqueuer,
        checkpointer=MemorySaver(),
        materialize_import=materializer,
        load_import_context=FakeImportContextLoader(bpm=100.0),
        enqueue_followup_media_job=followup,
    )
    thread_id = f"import-{uuid4().hex}"
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke(
        initial_import_state(
            thread_id=thread_id,
            project_id=uuid4(),
            branch_id=uuid4(),
            base_revision_id=uuid4(),
            source_artifact_id=uuid4(),
            idempotency_key="import-auto-stretch",
        ),
        config,
    )
    after_ingest = await graph.ainvoke(
        Command(
            resume={
                "schema_version": "worker-resume.v1",
                "run_id": str(enqueuer.run_id),
                "thread_id": thread_id,
                "run_type": PARENT_IMPORT_RUN_TYPE,
                "resume_event_id": "ingest-confident",
                "job_id": str(enqueuer.job_id),
                "status": "succeeded",
                "artifact_id": str(uuid4()),
                "error_code": None,
            }
        ),
        config,
    )

    assert after_ingest["phase"] == "waiting_worker"
    assert after_ingest["pending_job_id"] == str(followup.job_id)
    assert followup.requests[0].run_id == enqueuer.run_id
    assert followup.requests[0].input_payload["preserve_pitch"] is True

    derived_id = uuid4()
    completed = await graph.ainvoke(
        Command(
            resume={
                "schema_version": "worker-resume.v1",
                "run_id": str(enqueuer.run_id),
                "thread_id": thread_id,
                "run_type": PARENT_IMPORT_RUN_TYPE,
                "resume_event_id": "stretch-completed",
                "job_id": str(followup.job_id),
                "status": "succeeded",
                "artifact_id": str(derived_id),
                "error_code": None,
            }
        ),
        config,
    )

    assert completed["terminal_status"] == "succeeded"
    request = materializer.requests[0]
    assert request.normalized_artifact_id == derived_id
    assert request.original_normalized_artifact_id is not None
