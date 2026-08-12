from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import pytest
from motif_forge.audio.atomic_promote import AtomicPromoteError, promote_verified_file


def test_promote_cancellation_removes_destination_partial(tmp_path: Path) -> None:
    source = tmp_path / "temp" / "source.bin"
    source.parent.mkdir()
    source.write_bytes(b"audio-bytes")
    final = tmp_path / "artifacts" / "protected" / "final.bin"
    cancelled = threading.Event()
    cancelled.set()

    with pytest.raises(AtomicPromoteError, match="PROMOTE_CANCELLED"):
        promote_verified_file(
            source=source,
            final=final,
            expected_sha256=hashlib.sha256(b"audio-bytes").hexdigest(),
            expected_bytes=len(b"audio-bytes"),
            cancel_event=cancelled,
            chunk_bytes=2,
        )

    assert not final.exists()
    assert list(final.parent.glob("*.partial")) == []
    assert source.read_bytes() == b"audio-bytes"


def test_promote_rejects_bad_expected_checksum_without_publishing(tmp_path: Path) -> None:
    source = tmp_path / "temp" / "source.bin"
    source.parent.mkdir()
    source.write_bytes(b"audio-bytes")
    final = tmp_path / "artifacts" / "protected" / "final.bin"

    with pytest.raises(AtomicPromoteError, match="PROMOTE_CHECKSUM_MISMATCH"):
        promote_verified_file(
            source=source,
            final=final,
            expected_sha256="0" * 64,
            expected_bytes=len(b"audio-bytes"),
        )

    assert not final.exists()
    assert list(final.parent.glob("*.partial")) == []
