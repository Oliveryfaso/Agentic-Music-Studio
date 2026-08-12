"""Stable, transport-independent application errors."""

from __future__ import annotations

from uuid import UUID


class ApplicationError(Exception):
    """An expected application failure with a stable public code."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"{code}: {message}")


class RevisionConflictError(ApplicationError):
    """Optimistic concurrency failure for a branch head."""

    def __init__(self, current_revision_id: UUID) -> None:
        self.current_revision_id = current_revision_id
        super().__init__(
            "REVISION_CONFLICT",
            "the target branch head no longer matches base_revision_id",
            retryable=False,
        )


class IdempotencyKeyReusedError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            "IDEMPOTENCY_KEY_REUSED",
            "the idempotency key was already used with a different request",
            retryable=False,
        )


class ChangeImpactEscalatedError(ApplicationError):
    def __init__(self) -> None:
        super().__init__(
            "CHANGE_IMPACT_ESCALATED",
            "L2/L3 changes require a candidate preview and human approval",
            retryable=False,
        )


class MediaJobNotFoundError(ApplicationError):
    def __init__(self) -> None:
        super().__init__("MEDIA_JOB_NOT_FOUND", "the media job does not exist", retryable=False)


class MediaJobStateConflictError(ApplicationError):
    def __init__(self, message: str) -> None:
        super().__init__("MEDIA_JOB_STATE_CONFLICT", message, retryable=False)


class ArtifactRehydrationError(ApplicationError):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(code, message, retryable=retryable)


class UploadError(ApplicationError):
    """Stable upload failure surfaced as RFC 9457 problem details."""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(code, message, retryable=retryable)
