"""Runtime configuration with secret-safe representations."""

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Motif Forge service settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MOTIF_FORGE_",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    readiness_timeout_seconds: float = Field(default=2.0, gt=0.0, le=10.0)
    postgres_dsn: SecretStr | None = None
    redis_url: SecretStr | None = None
    media_worker_queue: str = Field(default="media", min_length=1, max_length=80)
    render_service_url: str = Field(
        default="http://render-worker:8090", min_length=8, max_length=240
    )
    media_worker_soft_time_limit_seconds: int = Field(default=600, ge=30, le=1800)
    media_worker_hard_time_limit_seconds: int = Field(default=660, ge=31, le=1900)
    media_job_lease_seconds: int = Field(default=720, ge=60, le=2100)
    outbox_batch_size: int = Field(default=16, ge=1, le=100)
    outbox_lease_seconds: int = Field(default=60, ge=10, le=300)
    outbox_poll_interval_seconds: float = Field(default=0.5, ge=0.1, le=10.0)
    storage_profile: Literal["portable", "lean"] = "portable"
    artifact_root: Path = Path("var/artifacts")
    temp_root: Path = Path("var/tmp")
    artifact_global_quota_bytes: int = Field(default=10 * 1024**3, gt=0)
    artifact_project_quota_bytes: int = Field(default=2 * 1024**3, gt=0)
    temp_quota_bytes: int = Field(default=2 * 1024**3, gt=0)
    upload_max_bytes: int = Field(default=256 * 1024**2, gt=0)
    upload_part_size_bytes: int = Field(default=4 * 1024**2, ge=64 * 1024, le=16 * 1024**2)
    upload_session_ttl_hours: int = Field(default=24, ge=1, le=168)
    storage_min_free_bytes: int = Field(default=512 * 1024**2, ge=64 * 1024**2)
    preview_ttl_hours: int = Field(default=24, gt=0)
    derived_cache_ttl_hours: int = Field(default=7 * 24, gt=0)
    terminal_checkpoint_ttl_hours: int = Field(default=7 * 24, gt=0)
    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="DEEPSEEK_API_KEY",
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias="DEEPSEEK_BASE_URL",
    )
    deepseek_model: str = Field(
        default="deepseek-v4-flash",
        validation_alias="DEEPSEEK_MODEL",
    )

    @model_validator(mode="after")
    def validate_storage_configuration(self) -> Self:
        """Reject impossible budgets and implicit local roots in the Lean profile."""
        if self.artifact_project_quota_bytes > self.artifact_global_quota_bytes:
            raise ValueError(
                "artifact_project_quota_bytes must not exceed artifact_global_quota_bytes"
            )
        if self.upload_max_bytes > self.artifact_project_quota_bytes:
            raise ValueError("upload_max_bytes must not exceed artifact_project_quota_bytes")
        if self.upload_part_size_bytes > self.upload_max_bytes:
            raise ValueError("upload_part_size_bytes must not exceed upload_max_bytes")
        if self.storage_profile == "lean" and (
            not self.artifact_root.is_absolute() or not self.temp_root.is_absolute()
        ):
            raise ValueError("lean storage profile requires absolute artifact_root and temp_root")
        if self.media_worker_hard_time_limit_seconds <= self.media_worker_soft_time_limit_seconds:
            raise ValueError("media worker hard time limit must exceed the soft time limit")
        if self.media_job_lease_seconds <= self.media_worker_hard_time_limit_seconds:
            raise ValueError("media job lease must exceed the Worker hard time limit")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
