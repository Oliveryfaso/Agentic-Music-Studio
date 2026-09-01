from motif_forge.config import Settings


def test_pytest_disables_implicit_remote_tracing() -> None:
    settings = Settings()

    assert settings.langsmith_tracing is False
    assert settings.langsmith_configured is False
