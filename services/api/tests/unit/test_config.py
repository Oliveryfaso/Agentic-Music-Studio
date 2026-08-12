from pathlib import Path

import pytest
from motif_forge.config import Settings
from pydantic import ValidationError


def test_storage_defaults_are_portable_and_bounded() -> None:
    settings = Settings(
        environment="test",
        storage_profile="portable",
        artifact_root=Path("var/artifacts"),
        temp_root=Path("var/tmp"),
    )

    assert settings.storage_profile == "portable"
    assert settings.artifact_root == Path("var/artifacts")
    assert settings.temp_root == Path("var/tmp")
    assert settings.artifact_project_quota_bytes == 2 * 1024**3
    assert settings.artifact_global_quota_bytes == 10 * 1024**3
    assert settings.temp_quota_bytes == 2 * 1024**3
    assert settings.preview_ttl_hours == 24
    assert settings.derived_cache_ttl_hours == 7 * 24
    assert settings.terminal_checkpoint_ttl_hours == 7 * 24
    assert settings.media_worker_queue == "media"
    assert settings.media_worker_soft_time_limit_seconds == 600
    assert settings.media_worker_hard_time_limit_seconds == 660
    assert settings.media_job_lease_seconds == 720
    assert settings.outbox_batch_size == 16


def test_storage_settings_can_target_one_external_volume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MOTIF_FORGE_ARTIFACT_ROOT", "/mnt/external/motif-forge/artifacts")
    monkeypatch.setenv("MOTIF_FORGE_TEMP_ROOT", "/mnt/external/motif-forge/tmp")
    monkeypatch.setenv("MOTIF_FORGE_STORAGE_PROFILE", "lean")
    monkeypatch.setenv("MOTIF_FORGE_ARTIFACT_GLOBAL_QUOTA_BYTES", "8589934592")
    monkeypatch.setenv("MOTIF_FORGE_ARTIFACT_PROJECT_QUOTA_BYTES", "1073741824")

    settings = Settings(environment="test")

    assert settings.storage_profile == "lean"
    assert settings.artifact_root == Path("/mnt/external/motif-forge/artifacts")
    assert settings.temp_root == Path("/mnt/external/motif-forge/tmp")
    assert settings.artifact_global_quota_bytes == 8 * 1024**3
    assert settings.artifact_project_quota_bytes == 1024**3


def test_project_artifact_quota_cannot_exceed_global_quota() -> None:
    with pytest.raises(ValidationError, match="must not exceed"):
        Settings(
            environment="test",
            artifact_global_quota_bytes=1024,
            artifact_project_quota_bytes=2048,
        )


def test_lean_storage_profile_rejects_implicit_relative_roots() -> None:
    with pytest.raises(ValidationError, match="requires absolute"):
        Settings(
            environment="test",
            storage_profile="lean",
            artifact_root=Path("var/artifacts"),
            temp_root=Path("var/tmp"),
        )
