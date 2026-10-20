"""Exercise database rejection directly, bypassing the application record validator."""

import asyncio
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from motif_forge.application.classical_import import ClassicalScoreRequest, CreateClassicalScore
from motif_forge.application.edit_runs import CreateEditAIRun, CreateEditAIRunRequest
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.domain.ai_runs import EditRunRequest
from motif_forge.domain.commands import Selection
from motif_forge.domain.piano_record import piano_source_metadata
from motif_forge.domain.piano_requests import PianoSemanticRequestV2
from motif_forge.domain.reviewed_scores import REVIEWED_SCORES
from motif_forge.infrastructure.persistence.ai_runs import PostgresAIRunUnitOfWork
from motif_forge.infrastructure.persistence.database import (
    PostgresUnitOfWork,
    create_postgres_engine,
    create_session_factory,
)
from motif_forge.infrastructure.persistence.piano_plans import PostgresPianoPlanStore
from motif_forge.infrastructure.persistence.tables import PianoAccompanimentPlanRow
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError


@pytest_asyncio.fixture
async def stored_v2_record(test_postgres_dsn):
    await asyncio.to_thread(
        command.upgrade, Config(Path(__file__).resolve().parents[4] / "alembic.ini"), "head"
    )
    engine = create_postgres_engine(test_postgres_dsn)
    sessions = create_session_factory(engine)
    projects = PostgresUnitOfWork(sessions)
    ai = PostgresAIRunUnitOfWork(sessions)

    async def capability():
        return PianoCapability(available=True)

    try:
        score = "c02-la-candeur-a8.v1"
        imported = await CreateClassicalScore(projects, capability)(
            ClassicalScoreRequest(score_id=score), idempotency_key=uuid4().hex
        )
        semantic = PianoSemanticRequestV2(
            source_score_id=score,
            beats_per_bar=4,
            end_bar=8,
            mode="append",
            intent="DB constraint fixture",
        )
        run = await CreateEditAIRun(ai)(
            CreateEditAIRunRequest(
                project_id=imported.project_id,
                branch_id=imported.branch_id,
                base_revision_id=imported.revision_id,
                thread_id="piano-" + uuid4().hex,
                idempotency_key=uuid4().hex,
                edit_request=EditRunRequest(
                    intent=semantic.intent, selection=Selection(), piano_request=semantic
                ),
                max_model_requests=1,
                max_total_tokens=12000,
            )
        )
        record = {
            "schema_version": "piano-plan-record.v2",
            "source": piano_source_metadata(REVIEWED_SCORES[score]),
            "request": semantic.model_dump(mode="json"),
            "plan": {
                "schema_version": "accompaniment-plan.v2",
                "beats_per_bar": 4,
                "summary": "pure database fixture",
                "bars": [
                    {
                        "bar": i,
                        "chord": "F",
                        "grid": [0],
                        "octave": 2,
                        "velocity": 48,
                        "gate_steps": 3,
                    }
                    for i in range(1, 9)
                ],
            },
        }
        await PostgresPianoPlanStore(sessions).save(run.run_id, record)
        yield sessions, run.run_id, record
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_v2_json_versions_source_meter_and_null_bindings_fail_closed(
    stored_v2_record,
):
    sessions, run_id, original = stored_v2_record
    try:
        corrupt = []
        corrupt.append(("piano-plan-record.v1", deepcopy(original)))
        for path, value in [
            (("schema_version",), "piano-plan-record.v1"),
            (("plan", "schema_version"), "accompaniment-plan.v1"),
            (("request", "schema_version"), "piano-semantic-request.v1"),
            (("request", "beats_per_bar"), 7),
            (("source", "xml_sha256"), "0" * 64),
            (("source", "score_id"), "c01-minuet-g-a16.v1"),
            (("source",), None),
            (("plan", "beats_per_bar"), None),
            (("request",), None),
        ]:
            changed = deepcopy(original)
            parent = changed
            for key in path[:-1]:
                parent = parent[key]
            parent[path[-1]] = value
            corrupt.append(("piano-plan-record.v2", changed))
        for version, payload in corrupt:
            with pytest.raises(IntegrityError):
                async with sessions() as session, session.begin():
                    await session.execute(
                        update(PianoAccompanimentPlanRow)
                        .where(PianoAccompanimentPlanRow.run_id == run_id)
                        .values(schema_version=version, payload=payload)
                    )
        async with sessions() as session:
            restored = (
                await session.execute(
                    select(PianoAccompanimentPlanRow.payload).where(
                        PianoAccompanimentPlanRow.run_id == run_id
                    )
                )
            ).scalar_one()
        assert restored == original
    finally:
        pass


@pytest.mark.asyncio
async def test_populated_v2_downgrade_is_refused_and_migration_head_remains(
    test_postgres_dsn, stored_v2_record
):
    config = Config(Path(__file__).resolve().parents[4] / "alembic.ini")
    with pytest.raises(RuntimeError, match="PIANO_SEMANTIC_V2_DOWNGRADE_BLOCKED"):
        await asyncio.to_thread(command.downgrade, config, "20261019_0029")
    engine = create_postgres_engine(test_postgres_dsn)
    try:
        async with engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == "20261020_0030"
    finally:
        await engine.dispose()
