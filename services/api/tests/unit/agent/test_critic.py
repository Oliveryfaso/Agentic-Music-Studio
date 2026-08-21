from __future__ import annotations

import json
from uuid import UUID, uuid4

import httpx
import pytest
from motif_forge.agent.critic import (
    CriticCandidate,
    CriticRequest,
    DeepSeekEvidenceCritic,
    DeterministicEvidenceCritic,
)
from motif_forge.agent.planner import ModelBudgetSnapshot, PlannerUsage
from motif_forge.domain.ai_runs import (
    ModelRequestKind,
    ModelRequestReservation,
)
from motif_forge.domain.candidates import CandidateEvidence, CandidateLabel
from motif_forge.providers.deepseek import DeepSeekJsonClient

RUN_ID = UUID("10000000-0000-0000-0000-000000000001")
CANDIDATE_A = UUID("20000000-0000-0000-0000-000000000001")
CANDIDATE_B = UUID("20000000-0000-0000-0000-000000000002")


class RecordingLedger:
    max_requests = 3
    max_total_tokens = 12_000

    def __init__(self) -> None:
        self.reservations: list[tuple[UUID, ModelRequestKind, int]] = []
        self.usages: list[PlannerUsage] = []

    async def reserve_request(
        self, *, run_id: UUID, kind: ModelRequestKind
    ) -> ModelRequestReservation:
        ordinal = len(self.reservations) + 2
        self.reservations.append((run_id, kind, ordinal))
        return ModelRequestReservation(
            reservation_id=uuid4(),
            run_id=run_id,
            request_ordinal=ordinal,
            kind=kind,
        )

    async def record_usage(
        self, *, reservation_id: UUID, usage: PlannerUsage
    ) -> ModelBudgetSnapshot:
        del reservation_id
        self.usages.append(usage)
        return ModelBudgetSnapshot(
            submitted_requests=len(self.reservations) + 1,
            total_tokens=sum(item.total_tokens or 0 for item in self.usages),
        )


def pair_request() -> CriticRequest:
    return CriticRequest(
        run_id=RUN_ID,
        candidates=(
            CriticCandidate(candidate_id=CANDIDATE_A, label=CandidateLabel.A),
            CriticCandidate(candidate_id=CANDIDATE_B, label=CandidateLabel.B),
        ),
        evidence=(
            CandidateEvidence(
                evidence_ref="a:structure:coverage",
                candidate_id=CANDIDATE_A,
                kind="structure",
                severity="warning",
                measured_fact="candidate A has one weak transition",
                score_delta=-8,
            ),
            CandidateEvidence(
                evidence_ref="b:structure:coverage",
                candidate_id=CANDIDATE_B,
                kind="structure",
                severity="info",
                measured_fact="candidate B covers every planned section",
                score_delta=6,
            ),
        ),
    )


@pytest.mark.asyncio
async def test_deterministic_critic_cites_only_supplied_evidence() -> None:
    request = pair_request()

    result = await DeterministicEvidenceCritic().evaluate(request)

    supplied = {item.evidence_ref for item in request.evidence}
    cited = {
        ref
        for assessment in result.critique.assessments
        for ref in assessment.evidence_refs
    } | {
        ref for finding in result.critique.findings for ref in finding.evidence_refs
    }
    assert cited <= supplied
    assert result.critique.recommended_candidate_id == CANDIDATE_B
    assert result.usage.total_tokens == 0
    assert result.model_calls == 0


@pytest.mark.asyncio
async def test_deepseek_critic_reserves_critic_request_before_http() -> None:
    ledger = RecordingLedger()
    requests: list[dict[str, object]] = []
    expected = (await DeterministicEvidenceCritic().evaluate(pair_request())).critique

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert ledger.reservations == [(RUN_ID, ModelRequestKind.CRITIC, 2)]
        return httpx.Response(
            200,
            json={
                "id": "critic-1",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": expected.model_dump_json()},
                    }
                ],
                "usage": {
                    "prompt_tokens": 80,
                    "completion_tokens": 20,
                    "total_tokens": 100,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekJsonClient(
            api_key="test-key",
            max_attempts=1,
            http_client=http_client,
            run_id=RUN_ID,
            budget_ledger=ledger,
        )
        result = await DeepSeekEvidenceCritic(client).evaluate(pair_request())

    assert len(requests) == 1
    assert requests[0]["thinking"] == {"type": "enabled"}
    assert "tools" not in requests[0]
    assert result.provider == "deepseek"
    assert result.model_calls == 1
    assert result.usage.total_tokens == 100


@pytest.mark.asyncio
async def test_invalid_critic_schema_falls_back_without_another_http_request() -> None:
    ledger = RecordingLedger()
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        del request
        request_count += 1
        return httpx.Response(
            200,
            json={
                "id": "critic-invalid",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"schema_version":"candidate-critique.v1"}'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 8,
                    "total_tokens": 48,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = DeepSeekJsonClient(
            api_key="test-key",
            max_attempts=1,
            http_client=http_client,
            run_id=RUN_ID,
            budget_ledger=ledger,
        )
        result = await DeepSeekEvidenceCritic(client).evaluate(pair_request())

    assert result.provider == "deterministic-fallback"
    assert result.model_calls == 1
    assert request_count == 1
    assert ledger.reservations == [(RUN_ID, ModelRequestKind.CRITIC, 2)]
