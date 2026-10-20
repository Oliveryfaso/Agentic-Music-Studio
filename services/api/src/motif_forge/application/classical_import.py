"""One reviewed classical source, imported into a protected original and working branch."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from hashlib import sha256
from importlib.resources import files
from typing import Any
from uuid import UUID, uuid4, uuid5

from pydantic import Field

from motif_forge.application._hashing import request_hash
from motif_forge.application.errors import ApplicationError, IdempotencyKeyReusedError
from motif_forge.application.piano_capability import PianoCapability
from motif_forge.application.ports import UnitOfWorkFactory
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.reviewed_scores import REVIEWED_SCORES, ScoreId, reviewed_source
from motif_forge.domain.revisions import (
    AuthorKind,
    ChangeImpact,
    ProjectBranch,
    Revision,
    create_root_state,
    versions_for_arrangement,
)

SCORE_ID: ScoreId = "mutopia-528-melody.v1"
SOURCE_REF = "score:" + SCORE_ID


def reviewed_score(score_id: str = SCORE_ID) -> tuple[dict[str, Any], bytes]:
    entry = REVIEWED_SCORES.get(score_id)
    if entry is None:
        raise ApplicationError(
            "CLASSICAL_SOURCE_NOT_FOUND", "This score is not in the reviewed catalog."
        )
    resource = files("motif_forge").joinpath("resources/scores")
    data = resource.joinpath(entry.manifest_path).read_bytes()
    manifest = json.loads(data)
    xml = resource.joinpath(entry.xml_path).read_bytes()
    if entry.manifest_sha256 is None:
        source_valid = sha256(
            resource.joinpath("ode-original.ly").read_bytes()
        ).hexdigest() == manifest.get("sha256")
    else:
        source_valid = sha256(data).hexdigest() == entry.manifest_sha256 and all(
            sha256(
                resource.joinpath(score_id.removesuffix(".v1"), item["file"]).read_bytes()
            ).hexdigest()
            == item["sha256"]
            for item in manifest["files"]
        )
    if (
        manifest.get("score_id") != score_id
        or manifest.get("license") != "Public Domain"
        or not source_valid
        or manifest.get("musicxml_sha256") != entry.xml_sha256
        or sha256(xml).hexdigest() != entry.xml_sha256
    ):
        raise ApplicationError(
            "CLASSICAL_SOURCE_HASH_MISMATCH", "The reviewed score source has changed."
        )
    return manifest, xml


class ClassicalScoreRequest(DomainModel):
    score_id: ScoreId = SCORE_ID
    name: str = Field(default="欢乐颂 · 我的改编", min_length=1, max_length=120)


class ClassicalScoreResult(DomainModel):
    project_id: UUID
    branch_id: UUID
    source_branch_id: UUID
    revision_id: UUID
    content_hash: str
    replayed: bool = False


class CreateClassicalScore:
    def __init__(
        self, projects: UnitOfWorkFactory, capability: Callable[[], Awaitable[PianoCapability]]
    ) -> None:
        self._projects, self._capability = projects, capability

    async def __call__(
        self, request: ClassicalScoreRequest, *, idempotency_key: str
    ) -> ClassicalScoreResult:
        manifest, xml = reviewed_score(request.score_id)
        # Validate before creating even an empty Project; no model, installation or fallback.
        parse_musicxml(xml, namespace=UUID(int=0))
        key = "classical-score:" + sha256(idempotency_key.encode()).hexdigest()
        fingerprint = request_hash(
            {**request.model_dump(mode="json"), "source_hash": manifest["musicxml_sha256"]}
        )
        async with self._projects() as tx:
            hit = await tx.get_idempotency(
                operation="score-import.v1", key=key, request_hash=fingerprint
            )
            if hit is not None:
                if hit.request_hash != fingerprint:
                    raise IdempotencyKeyReusedError
                return ClassicalScoreResult.model_validate_json(
                    json.dumps({**hit.result_payload, "replayed": True}), strict=True
                )
            capability = await self._capability()
            if not capability.available:
                raise ApplicationError(
                    capability.error_code or "INSTRUMENT_PACK_UNAVAILABLE",
                    "The reviewed piano is unavailable; no score project was created.",
                )
            # A single commit owns the new project, source, fork, audits and receipt.
            # An interrupted import therefore exposes either the complete score or nothing.
            root = create_root_state(uuid4(), created_by="human:local")
            name = request.name
            if request.score_id != SCORE_ID and name == "欢乐颂 · 我的改编":
                name = manifest["title"] + " · 我的改编"
            await tx.insert_project_root(name=name, root=root)
            branch = root.branch
            await tx.insert_audit_event(
                event_id=uuid5(root.project_id, "classical-project-created.v1"),
                project_id=root.project_id,
                actor_id="human:local",
                event_type="project.created",
                resource_id=root.project_id,
                payload={
                    "active_branch_id": str(root.active_branch_id),
                    "root_revision_id": str(root.revision.revision_id),
                },
            )
            score = score_to_arrangement(
                parse_musicxml(xml, namespace=root.project_id),
                project_id=root.project_id,
                source_ref="score:" + request.score_id,
            )
            now = datetime.now(UTC)
            revision = Revision(
                revision_id=uuid5(root.project_id, "classical-score-revision.v1"),
                project_id=root.project_id,
                parent_revision_id=root.revision.revision_id,
                created_on_branch_id=root.active_branch_id,
                arrangement_ir=score,
                content_hash=arrangement_content_hash(score),
                command_batch_id=uuid5(root.project_id, "classical-import-batch.v1"),
                change_impact_predicted=ChangeImpact.L3,
                change_impact_actual=ChangeImpact.L3,
                author_kind=AuthorKind.SYSTEM,
                created_by="system:reviewed-score-import",
                reason_code="CLASSICAL_SCORE_IMPORTED",
                versions=versions_for_arrangement(score),
                created_at=now,
            )
            await tx.insert_revision(revision=revision, commands=(), idempotency_key=key)
            if not await tx.advance_branch_head(
                branch_id=branch.branch_id,
                expected_head_id=root.revision.revision_id,
                new_head_id=revision.revision_id,
            ):
                raise ApplicationError("REVISION_CONFLICT", "The score root has already changed.")
            working = ProjectBranch(
                branch_id=uuid5(root.project_id, "classical-working-branch.v1"),
                project_id=root.project_id,
                name="我的改编",
                head_revision_id=revision.revision_id,
                created_from_revision_id=revision.revision_id,
                created_at=now,
                created_by="human:local",
            )
            await tx.fork_active_branch(branch=working, expected_active_branch_id=branch.branch_id)
            await tx.insert_audit_event(
                event_id=uuid5(root.project_id, "classical-import-audit.v1"),
                project_id=root.project_id,
                actor_id="human:local",
                event_type="project.classical-score.imported",
                resource_id=revision.revision_id,
                payload={
                    "score_id": request.score_id,
                    "source_sha256": manifest["sha256"],
                    "musicxml_sha256": manifest["musicxml_sha256"],
                    "measures": manifest["measures"],
                    "notes": manifest["note_count"],
                    "model_calls": 0,
                    "source_branch_id": str(branch.branch_id),
                    "working_branch_id": str(working.branch_id),
                },
            )
            result = ClassicalScoreResult(
                project_id=root.project_id,
                branch_id=working.branch_id,
                source_branch_id=branch.branch_id,
                revision_id=revision.revision_id,
                content_hash=revision.content_hash,
            )
            await tx.save_idempotency(
                operation="score-import.v1",
                key=key,
                request_hash=fingerprint,
                resource_id=revision.revision_id,
                result_payload=result.model_dump(mode="json"),
            )
            return result


async def read_classical_source(projects: UnitOfWorkFactory, project_id: UUID) -> dict[str, Any]:
    async with projects() as tx:
        revision = await tx.get_revision(uuid5(project_id, "classical-score-revision.v1"))
    if revision is None or revision.project_id != project_id:
        raise ApplicationError(
            "CLASSICAL_SOURCE_NOT_FOUND", "No reviewed score import belongs to this project."
        )
    try:
        identity = reviewed_source(revision.arrangement_ir)
    except ValueError as exc:
        raise ApplicationError(
            "CLASSICAL_SOURCE_NOT_FOUND", "No reviewed score import belongs to this project."
        ) from exc
    manifest, xml = reviewed_score(identity.score_id)
    parsed = parse_musicxml(xml, namespace=project_id)
    return {
        "project_id": str(project_id),
        "revision_id": str(revision.revision_id),
        "source_branch_id": str(revision.created_on_branch_id),
        "source": manifest,
        "import_report": {
            "measure_count": parsed.measure_count,
            "note_count": len(parsed.notes),
            "bpm": parsed.bpm,
            "beats": parsed.beats,
            "tonic": parsed.tonic,
            "rest_tail_bars": 1,
            "note_map": [n.model_dump(mode="json") for n in parsed.notes],
        },
    }
