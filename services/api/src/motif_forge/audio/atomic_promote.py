"""Cross-filesystem-safe promotion into an immutable content-addressed path."""

from __future__ import annotations

import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


class AtomicPromoteError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AtomicPromoteResult:
    created_new: bool


def promote_verified_file(
    *,
    source: Path,
    final: Path,
    expected_sha256: str,
    expected_bytes: int,
    cancel_event: threading.Event | None = None,
    chunk_bytes: int = 1024 * 1024,
) -> AtomicPromoteResult:
    """Copy into the final directory, verify, then atomically publish in-place."""

    if not source.is_file() or source.is_symlink():
        raise AtomicPromoteError("PROMOTE_SOURCE_UNAVAILABLE")
    if final.exists():
        if final.is_symlink() or _sha256_file(final) != expected_sha256:
            raise AtomicPromoteError("PROMOTE_IMMUTABLE_OUTPUT_CONFLICT")
        return AtomicPromoteResult(created_new=False)

    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.parent / f".{final.name}.{uuid4().hex}.partial"
    try:
        digest = hashlib.sha256()
        copied = 0
        with source.open("rb") as reader, partial.open("xb") as writer:
            while chunk := reader.read(chunk_bytes):
                if cancel_event is not None and cancel_event.is_set():
                    raise AtomicPromoteError("PROMOTE_CANCELLED")
                writer.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if copied != expected_bytes or digest.hexdigest() != expected_sha256:
            raise AtomicPromoteError("PROMOTE_CHECKSUM_MISMATCH")
        if cancel_event is not None and cancel_event.is_set():
            raise AtomicPromoteError("PROMOTE_CANCELLED")
        if final.exists():
            if final.is_symlink() or _sha256_file(final) != expected_sha256:
                raise AtomicPromoteError("PROMOTE_IMMUTABLE_OUTPUT_CONFLICT")
            return AtomicPromoteResult(created_new=False)
        os.replace(partial, final)
        return AtomicPromoteResult(created_new=True)
    finally:
        partial.unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
