from __future__ import annotations

import hashlib
import struct
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from motif_forge.audio.uploads import LocalUploadWorkspace, UploadWorkspaceError
from motif_forge.domain.uploads import DeclaredAudioFormat


def _minimal_wav() -> bytes:
    data = b"\x00\x00" * 8
    return (
        b"RIFF"
        + struct.pack("<I", 36 + len(data))
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, 8_000, 16_000, 2, 16)
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


async def _body(value: bytes) -> AsyncIterator[bytes]:
    yield value[:7]
    yield value[7:]


@pytest.mark.asyncio
async def test_upload_parts_promote_only_after_hash_and_magic_validation(tmp_path: Path) -> None:
    workspace = LocalUploadWorkspace(tmp_path)
    upload_id = uuid4()
    project_id = uuid4()
    value = _minimal_wav()
    stored = await workspace.write_part(
        upload_id=upload_id,
        part_number=1,
        body=_body(value),
        max_part_bytes=len(value),
    )

    assert stored.sha256 == hashlib.sha256(value).hexdigest()
    completed = workspace.complete(
        upload_id=upload_id,
        project_id=project_id,
        part_count=1,
        declared_format=DeclaredAudioFormat.WAV,
        expected_sha256=stored.sha256,
        expected_byte_size=len(value),
    )

    assert completed.detected_format is DeclaredAudioFormat.WAV
    assert completed.storage_key.startswith(f"quarantine/source-original/{project_id}/")
    assert (tmp_path / completed.storage_key).read_bytes() == value


@pytest.mark.asyncio
async def test_upload_completion_rejects_declared_format_mismatch(tmp_path: Path) -> None:
    workspace = LocalUploadWorkspace(tmp_path)
    upload_id = uuid4()
    value = _minimal_wav()
    stored = await workspace.write_part(
        upload_id=upload_id,
        part_number=1,
        body=_body(value),
        max_part_bytes=len(value),
    )

    with pytest.raises(UploadWorkspaceError, match="UPLOAD_FORMAT_MISMATCH"):
        workspace.complete(
            upload_id=upload_id,
            project_id=uuid4(),
            part_count=1,
            declared_format=DeclaredAudioFormat.MP3,
            expected_sha256=stored.sha256,
            expected_byte_size=len(value),
        )


@pytest.mark.asyncio
async def test_replayed_part_is_verified_without_overwriting_the_accepted_part(
    tmp_path: Path,
) -> None:
    workspace = LocalUploadWorkspace(tmp_path)
    value = _minimal_wav()
    stored = await workspace.write_part(
        upload_id=uuid4(),
        part_number=1,
        body=_body(value),
        max_part_bytes=len(value),
    )

    assert await workspace.verify_replayed_part(
        body=_body(value),
        expected_byte_size=stored.byte_size,
        expected_sha256=stored.sha256,
    )
    assert not await workspace.verify_replayed_part(
        body=_body(value + b"x"),
        expected_byte_size=stored.byte_size,
        expected_sha256=stored.sha256,
    )
