from unittest.mock import PropertyMock, patch

import pytest
from motif_forge.api.app import create_app
from motif_forge.config import Settings


@pytest.mark.parametrize("configured", [False, True])
def test_api_injects_only_public_configuration_boolean(configured):
    settings = Settings.for_test()
    # A property override proves wiring without handling any credential value.
    with (
        patch.object(
            Settings,
            "deepseek_configured",
            new_callable=PropertyMock,
            return_value=configured,
        ),
        patch("motif_forge.api.app.ReadPianoCapability") as capability,
    ):
        create_app(settings)
    assert capability.call_count == 2
    for call in capability.call_args_list:
        assert call.kwargs["semantic_generation_configured"] is configured
        assert set(call.kwargs) == {"service_url", "semantic_generation_configured"}
