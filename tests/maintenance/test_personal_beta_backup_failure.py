"""Safe backup diagnostics from synthetic exceptions; no runtime resources."""

from __future__ import annotations

import errno
import hashlib
import importlib
import importlib.util
import json

import pytest


def test_backup_failure_helper_exists():
    assert importlib.util.find_spec("scripts.personal_beta_backup_failure") is not None


@pytest.fixture
def module():
    return importlib.import_module("scripts.personal_beta_backup_failure")


@pytest.mark.parametrize("number", [errno.EEXIST, errno.ENOSPC, errno.EACCES])
def test_oserror_preserves_errno_without_private_text(module, number):
    error = OSError(number, "synthetic-secret-token", "/private/synthetic-secret/audio.wav")
    failure = module.make_failure("artifact_copy", error, "protected/audio.wav")
    assert isinstance(failure, ValueError)
    assert str(failure) == "BACKUP_IO_ERROR"
    assert failure.diagnostic == {
        "stage": "artifact_copy",
        "errno": number,
        "exception_type": type(error).__name__,
        "logical_key_sha256": hashlib.sha256(b"protected/audio.wav").hexdigest(),
    }
    encoded = json.dumps(failure.diagnostic) + str(failure) + repr(failure)
    assert "synthetic-secret" not in encoded and "/private/" not in encoded
    assert "protected/audio.wav" not in encoded


def test_real_exclusive_file_error_keeps_only_safe_fields(module, tmp_path):
    target = tmp_path / "private-synthetic-filename"
    target.write_text("keep")
    try:
        target.open("x")
    except OSError as error:
        failure = module.make_failure("archive_open", error)
    else:
        pytest.fail("exclusive create should have failed")
    assert str(failure) == "BACKUP_IO_ERROR"
    assert failure.diagnostic["errno"] == errno.EEXIST
    assert failure.diagnostic["exception_type"] == "FileExistsError"
    assert "private-synthetic-filename" not in repr(failure) + json.dumps(failure.diagnostic)
    assert target.read_text() == "keep"


def test_oserror_without_errno_does_not_fabricate_one(module):
    failure = module.make_failure("archive_fsync", OSError("secret"))
    assert failure.diagnostic["errno"] is None
    assert failure.diagnostic["exception_type"] == "OSError"
    assert str(failure) == "BACKUP_IO_ERROR"


@pytest.mark.parametrize("stage", ["/private/secret", "SECRET_TOKEN", "copy\nsecret", "", None])
def test_invalid_stage_is_unknown_and_not_reflected(module, stage):
    failure = module.make_failure(stage, RuntimeError("internal text"))
    assert failure.diagnostic["stage"] == "unknown"
    assert set(failure.diagnostic) == {"stage", "errno", "exception_type"}
    assert str(failure) == "BACKUP_OPERATION_FAILED"


@pytest.mark.parametrize(
    "code", ["BACKUP_SOURCE_CHANGED", "BACKUP_CLI_EXIT_UNKNOWN", "BACKUP_IO_ERROR"]
)
def test_fixed_public_codes_survive(module, code):
    failure = module.make_failure("archive_verify", RuntimeError(code))
    assert str(failure) == code
    assert failure.diagnostic["errno"] is None
    assert failure.diagnostic["stage"] == "archive_verify"


@pytest.mark.parametrize(
    "text",
    [
        "secret-token",
        "/private/audio.wav",
        "BACKUP_SECRET=value",
        "BACKUP_BAD\nSECRET",
        "BACKUP_" + "A" * 65,
    ],
)
def test_non_public_exception_text_is_never_echoed(module, text):
    failure = module.make_failure("database_snapshot_before", ValueError(text))
    assert str(failure) == "BACKUP_OPERATION_FAILED"
    assert text not in repr(failure) + json.dumps(failure.diagnostic)


def test_custom_exception_name_is_not_reflected(module):
    class SyntheticSecretName(RuntimeError):
        pass

    failure = module.make_failure("archive_close", SyntheticSecretName("secret"))
    assert failure.diagnostic["exception_type"] == "Exception"
    assert "SyntheticSecretName" not in json.dumps(failure.diagnostic)


def test_unprintable_exception_still_produces_safe_first_error(module):
    class Unprintable(Exception):
        def __str__(self):
            raise RuntimeError("nested-secret")

    failure = module.make_failure("archive_close", Unprintable())
    assert str(failure) == "BACKUP_OPERATION_FAILED"
    assert failure.diagnostic["stage"] == "archive_close"


def test_keyboard_interrupt_is_cancelled_not_raw_text(module):
    failure = module.make_failure("dump_write", KeyboardInterrupt("secret"))
    assert str(failure) == "BACKUP_CANCELLED"
    assert failure.diagnostic["exception_type"] == "KeyboardInterrupt"


def test_existing_wrapped_failure_keeps_first_stage_and_errno(module):
    first = module.make_failure("artifact_copy", OSError(errno.ENOSPC, "secret"), "a.wav")
    original = first.diagnostic
    assert module.make_failure("runtime_close", first, "different") is first
    assert first.diagnostic == original


def test_cleanup_error_does_not_replace_original_failure(module):
    first = module.make_failure("archive_manifest", OSError(errno.EACCES, "secret"), "manifest")
    original = first.diagnostic
    assert module.attach_cleanup(first, RuntimeError("BACKUP_CLI_EXIT_UNKNOWN")) is first
    assert str(first) == "BACKUP_IO_ERROR"
    assert first.diagnostic == original | {"cleanup_code": "BACKUP_CLI_EXIT_UNKNOWN"}
    assert module.attach_cleanup(first, RuntimeError("later-secret")) is first
    assert first.diagnostic["cleanup_code"] == "BACKUP_CLI_EXIT_UNKNOWN"


def test_diagnostic_copy_cannot_be_extended_with_private_fields(module):
    failure = module.make_failure("archive_open", OSError(errno.EEXIST, "secret"))
    diagnostic = failure.diagnostic
    diagnostic["filename"] = "/private/secret"
    assert "filename" not in failure.diagnostic


def test_surrogate_logical_key_is_hashable_without_raw_key(module):
    key = "source/\udcff.wav"
    failure = module.make_failure("artifact_copy", OSError(errno.EIO, "secret"), key)
    assert (
        failure.diagnostic["logical_key_sha256"]
        == hashlib.sha256(key.encode("utf-8", "surrogatepass")).hexdigest()
    )
    assert key not in json.dumps(failure.diagnostic)


def test_item_index_is_bounded_and_does_not_record_a_filename(module):
    failure = module.make_failure("artifact_copy", OSError(errno.EIO, "secret"), item_index=7)
    assert failure.diagnostic["item_index"] == 7
    for invalid in (-1, 1024, True, "private-name"):
        assert (
            "item_index"
            not in module.make_failure(
                "artifact_copy", OSError(errno.EIO, "secret"), item_index=invalid
            ).diagnostic
        )
