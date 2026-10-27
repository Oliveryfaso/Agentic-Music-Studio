"""Small public backup errors without private exception text or paths."""

from __future__ import annotations

import hashlib
import re

_PUBLIC_CODE = re.compile(r"BACKUP_[A-Z0-9_]{1,64}")
_STAGES = frozenset(
    {
        "contract",
        "maintenance_lock",
        "inventory_before",
        "database_snapshot_before",
        "target_create",
        "archive_open",
        "dump_write",
        "artifact_copy",
        "inventory_after",
        "database_snapshot_after",
        "writer_quiescence",
        "archive_manifest",
        "archive_close",
        "archive_fsync",
        "archive_verify",
        "runtime_close",
        "legacy_copy",
        "unknown",
    }
)
_BUILTIN_ERROR_TYPES = frozenset(
    {
        BaseException,
        Exception,
        OSError,
        FileExistsError,
        FileNotFoundError,
        PermissionError,
        IsADirectoryError,
        NotADirectoryError,
        InterruptedError,
        BlockingIOError,
        TimeoutError,
        ValueError,
        RuntimeError,
        TypeError,
        KeyError,
        UnicodeError,
        KeyboardInterrupt,
        SystemExit,
    }
)


def _public_code(value: str) -> str:
    return value if _PUBLIC_CODE.fullmatch(value) else "BACKUP_OPERATION_FAILED"


class BackupStageError(ValueError):
    """A fixed public code and a separate, narrowly bounded diagnostic."""

    def __init__(
        self,
        code: str,
        *,
        stage: str = "unknown",
        number: int | None = None,
        exception_type: str = "Exception",
        logical_key_sha256: str | None = None,
        item_index: int | None = None,
    ) -> None:
        super().__init__(_public_code(code))
        self._diagnostic: dict[str, str | int | None] = {
            "stage": stage if isinstance(stage, str) and stage in _STAGES else "unknown",
            "errno": number if type(number) is int else None,
            "exception_type": (
                exception_type
                if exception_type in {error_type.__name__ for error_type in _BUILTIN_ERROR_TYPES}
                else "Exception"
            ),
        }
        if logical_key_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", logical_key_sha256):
            self._diagnostic["logical_key_sha256"] = logical_key_sha256
        if type(item_index) is int and 0 <= item_index < 1024:
            self._diagnostic["item_index"] = item_index

    @property
    def diagnostic(self) -> dict[str, str | int | None]:
        """Return a copy so callers cannot accidentally append private fields."""
        return self._diagnostic.copy()


def make_failure(
    stage: str,
    error: BaseException,
    logical_key: str | None = None,
    *,
    item_index: int | None = None,
) -> BackupStageError:
    """Keep the first safe error; never retain the source exception itself."""
    if isinstance(error, BackupStageError):
        return error
    number = None
    if isinstance(error, KeyboardInterrupt):
        code = "BACKUP_CANCELLED"
    elif isinstance(error, OSError):
        code = "BACKUP_IO_ERROR"
        number = error.errno
    else:
        try:
            code = _public_code(str(error))
        except BaseException:
            code = "BACKUP_OPERATION_FAILED"
    error_type = type(error)
    key_hash = (
        hashlib.sha256(logical_key.encode("utf-8", "surrogatepass")).hexdigest()
        if isinstance(logical_key, str)
        else None
    )
    return BackupStageError(
        code,
        stage=stage,
        number=number,
        exception_type=error_type.__name__ if error_type in _BUILTIN_ERROR_TYPES else "Exception",
        logical_key_sha256=key_hash,
        item_index=item_index,
    )


def attach_cleanup(first: BackupStageError, cleanup_error: BaseException) -> BackupStageError:
    """Record cleanup failure without replacing any part of the first error."""
    first._diagnostic.setdefault("cleanup_code", str(make_failure("runtime_close", cleanup_error)))
    return first
