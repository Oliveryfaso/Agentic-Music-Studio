"""Small, bounded public restore diagnostics; never serialize exception text."""

from __future__ import annotations

import copy

STAGES = frozenset(
    [
        "contract",
        "archive_open",
        "archive_verify",
        "child_admission",
        "media_extract",
        "target_readmit",
        "restore_dispatch",
        "dump_copy",
        "pg_restore",
        "db_snapshot",
        "db_compare",
        "archive_close",
        "client_close",
        "device_separation",
        "parent_admission",
        "worker_spawn",
        "worker_wait",
        "target_stop",
        "worker_exit",
        "parent_close",
        "signal_restore",
        "entry",
        "event_transport",
    ]
)
SAFE_CODES = frozenset(
    [
        "UNKNOWN_EXCEPTION",
        "RESTORE_CANCELLED",
        "RESTORE_EVENT_PIPE_UNKNOWN",
        "RESTORE_EVENT_LIMIT",
        "RESTORE_DIAGNOSTIC_INVALID",
        "RESTORE_ARCHIVE_PIN",
        "RESTORE_ARCHIVE_PIN_INVALID",
        "RESTORE_ARCHIVE_SIZE",
        "RESTORE_CONTRACT_FIELDS",
        "RESTORE_DAEMON_MISMATCH",
        "RESTORE_DATABASE_MISMATCH",
        "RESTORE_DATABASE_NOT_EMPTY",
        "RESTORE_DEADLINE",
        "RESTORE_DEVICE_NOT_ISOLATED",
        "RESTORE_DEVICE_QUERY",
        "RESTORE_HASH",
        "RESTORE_HOST_ACCESS",
        "RESTORE_HOST_DESCENDANT_EXIT_UNKNOWN",
        "RESTORE_HOST_EXIT_UNKNOWN",
        "RESTORE_IDENTITY",
        "RESTORE_NETWORK",
        "RESTORE_NOT_OWNED",
        "RESTORE_OWNER",
        "RESTORE_PERSISTENT_MOUNT",
        "RESTORE_PG_IDENTITY",
        "RESTORE_PG_NOT_NEW",
        "RESTORE_PG_STATE",
        "RESTORE_PUBLISHED_PORT",
        "RESTORE_REQUIRES_WRITABLE_APFS",
        "RESTORE_RESOURCE_LIMIT",
        "RESTORE_RESTART_POLICY",
        "RESTORE_SCHEMA",
        "RESTORE_SIZE",
        "RESTORE_SOURCE_OVERLAP",
        "RESTORE_SOURCE_IDENTITY_UNKNOWN",
        "RESTORE_SPACE",
        "RESTORE_STOPPED",
        "RESTORE_STOP_DAEMON",
        "RESTORE_STOP_IDENTITY",
        "RESTORE_STOP_MOUNT",
        "RESTORE_STOP_OWNER",
        "RESTORE_TARGET_EXIT_UNKNOWN",
        "RESTORE_TARGET_NOT_FRESH",
        "RESTORE_TMPFS",
        "RESTORE_TMPFS_BUDGET",
        "RESTORE_TMPFS_OPTION",
        "RESTORE_TMPFS_SIZE",
        "RESTORE_VOLUME_CHANGED",
        "RESTORE_VOLUME_IDENTITY",
        "RESTORE_WORKER_FAILED",
        "RESTORE_WORKER_UNKNOWN",
        "BACKUP_CATALOG_DUPLICATE",
        "BACKUP_CATALOG_EMPTY",
        "BACKUP_CATALOG_IDENTIFIER",
        "BACKUP_CATALOG_INVALID",
        "BACKUP_CATALOG_LIMIT",
        "BACKUP_CLI_CLOSED_OR_LIMIT",
        "BACKUP_CLI_EXIT_UNKNOWN",
        "BACKUP_CLI_FAILED",
        "BACKUP_CLI_IO_FAILED",
        "BACKUP_CLI_LOCAL_SOCKET_UNAVAILABLE",
        "BACKUP_CLI_SERVICE_FILE_ERROR",
        "BACKUP_CLI_SPAWN_UNKNOWN",
        "BACKUP_CLI_TIMEOUT",
        "BACKUP_DATABASE_BUDGET",
        "BACKUP_DATABASE_MISMATCH",
        "BACKUP_OTHER_DATABASE_SESSIONS",
        "BACKUP_OUTPUT_LIMIT",
        "BACKUP_OUTPUT_LIMIT_INVALID",
        "BACKUP_OUTPUT_WRITE_FAILED",
        "BACKUP_REMOTE_EXEC_EXIT_UNKNOWN",
        "BACKUP_RUNTIME_DEADLINE",
        "BACKUP_SCHEMA_MISMATCH",
        "BACKUP_SEQUENCE_SUMMARY_INVALID",
        "BACKUP_TABLE_SUMMARY_INVALID",
        "BACKUP_FILE_CHANGED",
        "BACKUP_ARCHIVE_BUSY",
        "BACKUP_STDIN_INVALID",
    ]
)
ERROR_TYPES = frozenset(
    {
        "RuntimeError",
        "ValueError",
        "OSError",
        "KeyboardInterrupt",
        "BackupCheckError",
        "BackupRuntimeError",
        "UnknownError",
    }
)


def _check(condition):
    if not condition:
        raise ValueError("RESTORE_DIAGNOSTIC_INVALID")


def _issue(stage, error):
    _check(stage in STAGES)
    # Only equality against a fixed code table; never include an arbitrary message.
    code = str(error) if type(error).__name__ in ERROR_TYPES else "UNKNOWN_EXCEPTION"
    code = code if code in SAFE_CODES else "UNKNOWN_EXCEPTION"
    name = type(error).__name__
    if isinstance(error, KeyboardInterrupt):
        code, name = "RESTORE_CANCELLED", "KeyboardInterrupt"
    elif isinstance(error, OSError):
        name = "OSError"
    elif name not in ERROR_TYPES:
        name = "UnknownError"
    result = {"stage": stage, "error_code": code, "error_type": name}
    if isinstance(error, OSError) and type(error.errno) is int and 0 < error.errno < 4096:
        result["errno"] = error.errno
    return result


def _valid_issue(value):
    _check(isinstance(value, dict) and set(value) <= {"stage", "error_code", "error_type", "errno"})
    _check(value["stage"] in STAGES and value["error_code"] in SAFE_CODES)
    _check(value["error_type"] in ERROR_TYPES)
    _check("errno" not in value or (type(value["errno"]) is int and 0 < value["errno"] < 4096))
    return copy.deepcopy(value)


class RestoreFailure(RuntimeError):
    def __init__(self, result):
        _check(isinstance(result, dict) and result.get("status") == "FAILED_OR_UNKNOWN")
        _check(
            result.get("reason") == "RESTORE_STOPPED" and result.get("preserve_evidence") is True
        )
        _check(result.get("restore_state") in {"not_started", "unverified", "verified"})
        _check(
            result.get("restore_performed") is None or type(result.get("restore_performed")) is bool
        )
        checked = Diagnostics()
        checked.adopt(result, include_events=True)
        for name in ("host_child_waited", "target_exit_proven"):
            _check(type(result.get(name)) is bool)
            setattr(checked, name, result[name])
        if result["restore_state"] == "unverified":
            checked.uncertain = True
        self._result = checked.result()
        super().__init__("RESTORE_STOPPED")

    def as_result(self):
        return copy.deepcopy(self._result)


class Diagnostics:
    def __init__(self, observer=None):
        self.events = []
        self.events_truncated = False
        self.first_error = None
        self.cleanup_errors = []
        self.pg_restore_started = False
        self.pg_restore_cli_exit = None
        self.db_verified = False
        self.host_child_waited = False
        self.target_exit_proven = False
        self.uncertain = False
        self.current_stage = "entry"
        self.observer = observer

    def stage(self, name, state="started"):
        _check(name in STAGES and state in {"started", "completed"})
        self.current_stage = name
        event = {"stage": name, "state": state}
        if len(self.events) >= 48:
            self.events_truncated = True
            return
        self.events.append(event)
        if self.observer is not None:
            try:
                self.observer(
                    {
                        "kind": "stage",
                        "event": event,
                        "pg_restore_started": self.pg_restore_started,
                        "pg_restore_cli_exit": self.pg_restore_cli_exit,
                        "db_verified": self.db_verified,
                    }
                )
            except BaseException:
                self.fail("event_transport", RuntimeError("RESTORE_EVENT_PIPE_UNKNOWN"))
                raise RuntimeError("RESTORE_EVENT_PIPE_UNKNOWN") from None

    def fail(self, stage, error):
        if isinstance(error, RestoreFailure):
            self.adopt(error.as_result(), include_events=not self.events)
        elif self.first_error is None:
            self.first_error = _issue(stage, error)

    def cleanup_error(self, stage, error):
        if isinstance(error, RestoreFailure):
            result = error.as_result()
            issues = (
                [result["first_error"]] if result["first_error"] is not None else []
            ) + result["cleanup_errors"]
        else:
            issues = [_issue(stage, error)]
        for issue in issues:
            issue = _valid_issue(issue)
            if self.first_error is None:
                self.first_error = issue
            if len(self.cleanup_errors) < 6 and issue not in self.cleanup_errors:
                self.cleanup_errors.append(issue)

    def cleanup(self, stage, action):
        # Telemetry transport must never prevent the original close/wait action.
        try:
            self.stage(stage)
        except BaseException as error:
            self.cleanup_error("event_transport", error)
        try:
            action()
        except BaseException as error:
            self.cleanup_error(stage, error)
            return False
        try:
            self.stage(stage, "completed")
        except BaseException as error:
            self.cleanup_error("event_transport", error)
        return True

    def accept_event(self, frame):
        _check(
            set(frame)
            == {"kind", "event", "pg_restore_started", "pg_restore_cli_exit", "db_verified"}
        )
        _check(frame["kind"] == "stage" and set(frame["event"]) == {"stage", "state"})
        _check(type(frame["pg_restore_started"]) is bool and type(frame["db_verified"]) is bool)
        code = frame["pg_restore_cli_exit"]
        _check(code is None or (type(code) is int and -128 <= code <= 255))
        self.pg_restore_started = self.pg_restore_started or frame["pg_restore_started"]
        if code is not None:
            self.pg_restore_cli_exit = code
        self.db_verified = self.db_verified or frame["db_verified"]
        self.stage(frame["event"]["stage"], frame["event"]["state"])

    def adopt(self, result, include_events=False):
        _check(isinstance(result, dict))
        if result.get("first_error") is not None and self.first_error is None:
            self.first_error = _valid_issue(result["first_error"])
        errors = result.get("cleanup_errors", [])
        _check(isinstance(errors, list) and len(errors) <= 6)
        for error in errors:
            checked = _valid_issue(error)
            if len(self.cleanup_errors) < 6 and checked not in self.cleanup_errors:
                self.cleanup_errors.append(checked)
        for name in ("db_verified", "events_truncated"):
            value = result.get(name, False)
            _check(type(value) is bool)
            setattr(self, name, getattr(self, name) or value)
        started = result.get("pg_restore_started", False)
        _check(started is None or type(started) is bool)
        if started is True:
            self.pg_restore_started = True
        elif started is None:
            self.uncertain = True
        code = result.get("pg_restore_cli_exit")
        _check(code is None or (type(code) is int and -128 <= code <= 255))
        if code is not None:
            self.pg_restore_cli_exit = code
        if include_events:
            events = result.get("events", [])
            _check(isinstance(events, list) and len(events) <= 48)
            for event in events:
                _check(set(event) == {"stage", "state"})
                self.stage(event["stage"], event["state"])

    def result(self, success=False):
        if self.events_truncated and self.first_error is None:
            self.fail("event_transport", RuntimeError("RESTORE_EVENT_LIMIT"))
        passed = (
            success
            and self.db_verified
            and not self.first_error
            and not self.cleanup_errors
            and not self.uncertain
        )
        state = (
            "verified"
            if self.db_verified
            else "unverified"
            if self.pg_restore_started or self.uncertain
            else "not_started"
        )
        result = {
            "status": "RESTORED_PG_AND_MEDIA" if passed else "FAILED_OR_UNKNOWN",
            "restore_performed": True
            if state == "verified"
            else False
            if state == "not_started"
            else None,
            "restore_state": state,
            "api_verified": False,
            "first_error": copy.deepcopy(self.first_error),
            "cleanup_errors": copy.deepcopy(self.cleanup_errors),
            "pg_restore_started": None
            if self.uncertain and not self.pg_restore_started
            else self.pg_restore_started,
            "pg_restore_cli_exit": self.pg_restore_cli_exit,
            "db_verified": self.db_verified,
            "host_child_waited": self.host_child_waited,
            "target_exit_proven": self.target_exit_proven,
            "events": copy.deepcopy(self.events),
            "events_truncated": self.events_truncated,
        }
        if not passed:
            result.update(reason="RESTORE_STOPPED", preserve_evidence=True)
        return result
