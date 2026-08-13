from uuid import uuid4

from motif_forge.observability.models import UsageRecord


def test_usage_record_keeps_unknown_cost_unknown() -> None:
    usage = UsageRecord(
        operation_id=str(uuid4()),
        provider="provider",
        model="model",
        input_tokens=1,
        output_tokens=2,
        estimated_cost_microusd=None,
    )
    assert usage.estimated_cost_microusd is None
    assert usage.cost_status == "unknown"
