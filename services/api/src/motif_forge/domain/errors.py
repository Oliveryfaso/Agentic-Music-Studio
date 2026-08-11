"""Stable pure-domain issues and aggregate validation errors."""

from __future__ import annotations

from collections.abc import Iterable

from motif_forge.domain.ir import DomainModel


class DomainIssue(DomainModel):
    code: str
    path: str
    message: str


class DomainValidationError(ValueError):
    """A deterministic collection of user-safe domain validation issues."""

    def __init__(self, issues: Iterable[DomainIssue]) -> None:
        ordered = tuple(sorted(issues, key=lambda issue: (issue.path, issue.code, issue.message)))
        if not ordered:
            raise ValueError("DomainValidationError requires at least one issue")
        self.issues = ordered
        message = "; ".join(f"{issue.code}@{issue.path}: {issue.message}" for issue in ordered)
        super().__init__(message)


def issue(code: str, path: str, message: str) -> DomainValidationError:
    return DomainValidationError((DomainIssue(code=code, path=path, message=message),))
