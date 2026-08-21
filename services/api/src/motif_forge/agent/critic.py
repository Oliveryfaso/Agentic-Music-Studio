"""Evidence-grounded pairwise candidate critic boundary."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Protocol, Self, cast
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field, model_validator

from motif_forge.agent.planner import PlannerUsage
from motif_forge.domain.ai_runs import ModelRequestKind, ModelUsageStatus
from motif_forge.domain.candidates import (
    CandidateAssessment,
    CandidateCritique,
    CandidateEvidence,
    CandidateFinding,
    CandidateLabel,
    RepairProposal,
)
from motif_forge.domain.ir import DomainModel
from motif_forge.providers.deepseek import (
    DEEPSEEK_MODEL,
    DeepSeekJsonClient,
    DeepSeekProviderError,
)

CRITIC_PROMPT_VERSION = "candidate-evidence-critic.v1"
CRITIC_PROMPT = """You are Motif Forge's bounded pairwise Evidence Critic.
Return exactly one CandidateCritique JSON object and no prose.
Use only the supplied evidence records. Never invent, edit, render, call tools, or cite an
evidence_ref that is not present. Assess exactly candidate A and B, recommend one candidate,
and propose at most one allowlisted segment repair when the evidence justifies it.
"""


class CriticCandidate(DomainModel):
    candidate_id: UUID
    label: CandidateLabel


class CriticRequest(DomainModel):
    schema_version: str = "critic-request.v1"
    run_id: UUID
    candidates: tuple[CriticCandidate, ...] = Field(min_length=2, max_length=2)
    evidence: tuple[CandidateEvidence, ...] = Field(min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_pair(self) -> Self:
        if {item.label for item in self.candidates} != {
            CandidateLabel.A,
            CandidateLabel.B,
        }:
            raise ValueError("critic request requires candidate A and B")
        candidate_ids = {item.candidate_id for item in self.candidates}
        if len(candidate_ids) != 2:
            raise ValueError("critic request candidates must have distinct identities")
        if any(item.candidate_id not in candidate_ids for item in self.evidence):
            raise ValueError("critic evidence must belong to the assessed pair")
        refs = [item.evidence_ref for item in self.evidence]
        if len(refs) != len(set(refs)):
            raise ValueError("critic evidence refs must be unique")
        return self


@dataclass(frozen=True, slots=True)
class CriticResult:
    critique: CandidateCritique
    usage: PlannerUsage = field(default_factory=PlannerUsage)
    provider: str = "deterministic"
    model: str = "deterministic"
    prompt_version: str = CRITIC_PROMPT_VERSION
    model_calls: int = 0
    operation_id: str | None = None


class EvidenceCritic(Protocol):
    async def evaluate(self, request: CriticRequest) -> CriticResult: ...


class DeterministicEvidenceCritic:
    """Transparent no-cost baseline over already-computed evidence facts."""

    async def evaluate(self, request: CriticRequest) -> CriticResult:
        scores: dict[UUID, int] = {}
        assessments: list[CandidateAssessment] = []
        for candidate in sorted(request.candidates, key=lambda item: item.label.value):
            evidence = tuple(
                item for item in request.evidence if item.candidate_id == candidate.candidate_id
            )
            score = max(0, min(100, 75 + sum(item.score_delta for item in evidence)))
            scores[candidate.candidate_id] = score
            assessments.append(
                CandidateAssessment(
                    candidate_id=candidate.candidate_id,
                    label=candidate.label,
                    score=score,
                    evidence_refs=tuple(item.evidence_ref for item in evidence),
                )
            )
        recommended = max(
            request.candidates,
            key=lambda item: (scores[item.candidate_id], item.label is CandidateLabel.A),
        )
        actionable = next(
            (
                item
                for item in request.evidence
                if item.severity in {"error", "warning"} and item.segment_id is not None
            ),
            None,
        )
        findings = tuple(
            CandidateFinding(
                finding_code=f"EVIDENCE_{item.severity.upper()}",
                candidate_id=item.candidate_id,
                segment_id=item.segment_id,
                severity=cast(Literal["error", "warning", "advice"], item.severity),
                evidence_refs=(item.evidence_ref,),
            )
            for item in request.evidence
            if item.severity in {"error", "warning", "advice"}
        )
        repair = (
            RepairProposal(
                candidate_id=actionable.candidate_id,
                segment_id=actionable.segment_id,
                operation="density_reduction",
                evidence_refs=(actionable.evidence_ref,),
            )
            if actionable is not None and actionable.segment_id is not None
            else None
        )
        critique = CandidateCritique(
            evidence=request.evidence,
            assessments=tuple(assessments),
            findings=findings,
            repair_proposal=repair,
            recommended_candidate_id=recommended.candidate_id,
            rationale="Deterministic ranking from supplied evidence score deltas.",
        )
        return CriticResult(critique=critique)


class DeepSeekEvidenceCritic:
    """One paid, tool-free pairwise call with deterministic schema fallback."""

    def __init__(
        self,
        client: DeepSeekJsonClient,
        *,
        fallback: EvidenceCritic | None = None,
        max_tokens: int = 1600,
    ) -> None:
        self._client = client
        self._fallback = fallback or DeterministicEvidenceCritic()
        self._max_tokens = max_tokens

    async def evaluate(self, request: CriticRequest) -> CriticResult:
        messages = (
            SystemMessage(
                content=(
                    f"{CRITIC_PROMPT}\nJSON Schema:\n"
                    f"{json.dumps(CandidateCritique.model_json_schema(), separators=(',', ':'))}"
                )
            ),
            HumanMessage(
                content=json.dumps(
                    {"kind": "candidate_evidence", "payload": request.model_dump(mode="json")},
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            ),
        )
        try:
            response = await self._client.complete_json(
                messages=messages,
                output_model=CandidateCritique,
                thinking="enabled",
                reasoning_effort="high",
                max_tokens=self._max_tokens,
                schema_repair_attempts=0,
                request_kind=ModelRequestKind.CRITIC,
            )
            if response.output.evidence != request.evidence:
                raise ValueError("critic output changed authoritative evidence")
        except DeepSeekProviderError as exc:
            if exc.code != "DEEPSEEK_SCHEMA_INVALID":
                raise
            return await self._fallback_result(request)
        except ValueError:
            return await self._fallback_result(request)
        return CriticResult(
            critique=response.output,
            usage=response.usage,
            provider=response.provider,
            model=response.model,
            model_calls=response.model_calls,
            operation_id=response.operation_id,
        )

    async def _fallback_result(self, request: CriticRequest) -> CriticResult:
        fallback = await self._fallback.evaluate(request)
        return CriticResult(
            critique=fallback.critique,
            usage=PlannerUsage(
                status=ModelUsageStatus.UNKNOWN,
                prompt_tokens=None,
                completion_tokens=None,
                total_tokens=None,
                prompt_cache_hit_tokens=None,
                prompt_cache_miss_tokens=None,
                reasoning_tokens=None,
            ),
            provider="deterministic-fallback",
            model=DEEPSEEK_MODEL,
            model_calls=1,
        )
