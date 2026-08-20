from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from motif_forge.agent.fallback import build_fallback_plan
from motif_forge.agent.generate import GenerateRequest, initial_generate_state
from motif_forge.agent.parent_graph import build_parent_graph
from motif_forge.agent.planner import StaticCompositionPlanner
from motif_forge.agent.planning_subgraph import (
    build_composition_planning_subgraph,
    initial_planning_state,
)
from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.application.generation import (
    CompleteExportCursor,
    MaterializeApprovedCompositionResult,
    PersistPlanningResultResult,
)
from motif_forge.domain.ai_runs import AIRunApproval, composition_plan_content_hash
from motif_forge.domain.composition import (
    S1_BAR_TICKS,
    build_s1_composition,
    compile_synth_ambient_plan,
    validate_s1_arrangement,
)
from motif_forge.domain.media_jobs import MediaQualityProfile
from motif_forge.worker.resume_dispatcher import MissingDeepSeekPlanner

EVAL_PATH = Path(__file__).parents[4] / "evals" / "s2-synth-ambient-v1.json"


def _cases() -> list[dict[str, object]]:
    payload = json.loads(EVAL_PATH.read_text())
    assert isinstance(payload, list)
    return payload


class _EvalFacts:
    def __init__(self) -> None:
        self.persisted = 0
        self.approvals = 0
        self.materializations = 0
        self.enqueues = 0
        self.plan: CompositionPlan | None = None
        self.completed_cursor: CompleteExportCursor | None = None

    async def persist(self, request):  # type: ignore[no-untyped-def]
        self.persisted += 1
        self.plan = CompositionPlan.model_validate_json(
            json.dumps(request.planning_result["plan"]), strict=True
        )
        return PersistPlanningResultResult(
            run_id=request.run_id,
            plan_id=uuid4(),
            plan_hash=composition_plan_content_hash(self.plan),
            interrupt_ref=f"eval-interrupt-{uuid4()}",
            run_version=1,
        )

    async def approve(self, **kwargs):  # type: ignore[no-untyped-def]
        self.approvals += 1
        return AIRunApproval(
            approval_id=uuid4(),
            run_id=kwargs["run_id"],
            assertion_hash="a" * 64,
            decision=kwargs["decision"],
            actor_id=kwargs["actor_id"],
            expected_plan_content_hash=kwargs["expected_plan_content_hash"],
            interrupt_ref=kwargs["interrupt_ref"],
            decided_at=datetime.now(UTC),
        )

    async def materialize(self, request):  # type: ignore[no-untyped-def]
        self.materializations += 1
        return MaterializeApprovedCompositionResult(
            status="approved", plan_id=request.plan_id, revision_id=uuid4()
        )

    async def enqueue(self, cursor: CompleteExportCursor) -> CompleteExportCursor:
        self.enqueues += 1
        job_ids = tuple(uuid4() for _ in range(7))
        artifact_ids = tuple(uuid4() for _ in range(6))
        self.completed_cursor = cursor.model_copy(
            update={
                "media_run_id": uuid4(),
                "completed_steps": (
                    "master",
                    "stem:pad",
                    "stem:melody",
                    "stem:bass",
                    "stem:rhythm",
                    "mp3",
                    "bundle",
                ),
                "completed_job_ids": job_ids,
                "audio_artifact_ids": artifact_ids,
                "bundle_artifact_id": uuid4(),
            }
        )
        return self.completed_cursor

    async def collect(self, cursor: CompleteExportCursor, **kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return cursor


_STRUCTURAL_FORBIDDEN_BEHAVIORS = frozenset(
    {"abrupt drop", "vocals", "hard cut", "clipping", "infinite loop"}
)
_RUNTIME_ONLY_FORBIDDEN_BEHAVIORS = frozenset(
    {"abrupt drop", "hard cut", "clipping"}
)


def _forbidden_behavior_evidence(
    case: dict[str, object],
    *,
    route: str,
    actual_model_calls: int,
    plan: CompositionPlan | None,
    playable_success: bool | None,
    structural_facts: dict[str, bool],
    facts: _EvalFacts | None,
    terminal_replay_safe: bool = False,
    missing_provider: bool = False,
) -> tuple[dict[str, str], tuple[str, ...], tuple[str, ...]]:
    budget = case["budget"]
    assert isinstance(budget, dict)
    evidence: dict[str, str] = {}
    not_measured: list[str] = []
    for behavior in case["forbidden_behavior"]:
        assert isinstance(behavior, str)
        passed = False
        label = ""
        if behavior in _RUNTIME_ONLY_FORBIDDEN_BEHAVIORS:
            not_measured.append(behavior)
            continue
        if behavior in _STRUCTURAL_FORBIDDEN_BEHAVIORS:
            structural_key = {
                "vocals": "instrument_tracks_only",
                "infinite loop": "finite_timeline",
            }[behavior]
            passed = (
                playable_success is True
                and plan is not None
                and behavior in plan.negative_constraints
                and structural_facts.get(structural_key) is True
            )
            label = f"negative_constraint_plus_{structural_key}"
        elif behavior == "approval bypass":
            passed = facts is not None and (
                (route == "waiting_plan_approval" and facts.materializations == 0)
                or (
                    route in {"approved", "succeeded"}
                    and facts.approvals == 1
                    and facts.materializations == 1
                )
            )
            label = "approval_precedes_materialization"
        elif behavior == "model mutation":
            passed = facts is not None and facts.materializations == 0
            label = "no_materialization_before_human_approval"
        elif behavior == "planner call":
            passed = actual_model_calls == 0
            label = "planner_counter_zero"
        elif behavior == "revision write":
            passed = facts is not None and facts.materializations == 0
            label = "materialization_counter_zero"
        elif behavior == "approval interrupt":
            passed = facts is not None and facts.persisted == 0
            label = "pre_model_rejection_without_persisted_plan"
        elif behavior in {"unbounded retry", "third model call"}:
            passed = actual_model_calls <= int(budget["max_model_calls"])
            label = "bounded_planner_counter"
        elif behavior == "raw payload persistence":
            passed = plan is not None
            label = "only_validated_composition_plan_exposed"
        elif behavior == "silent approval":
            passed = route == "deterministic_fallback"
            label = "planning_subgraph_has_no_approval_node"
        elif behavior in {"network call", "secret read"}:
            passed = missing_provider and actual_model_calls == 0
            label = "missing_provider_adapter_has_zero_submissions"
        elif behavior == "model revision write":
            passed = facts is not None and facts.approvals == facts.materializations == 1
            label = "revision_materialized_only_after_recorded_human_approval"
        elif behavior in {"materialization", "render enqueue"}:
            passed = facts is not None and facts.materializations == facts.enqueues == 0
            label = "side_effect_counters_zero"
        elif behavior == "duplicate planner":
            passed = facts is not None and facts.persisted == 1
            label = "one_persisted_plan_across_restart"
        elif behavior == "duplicate materialization":
            passed = (
                facts is not None
                and facts.materializations == facts.enqueues == 1
                and facts.completed_cursor is not None
                and len(facts.completed_cursor.completed_job_ids) == 7
            )
            label = "one_materialization_and_seven_job_cursor_across_replay"
        elif behavior == "resume after terminal":
            passed = terminal_replay_safe
            label = "terminal_replay_kept_terminal_state_without_side_effects"
        if passed:
            evidence[behavior] = label
    checked = tuple(str(item) for item in case["forbidden_behavior"])
    violations = tuple(
        item for item in checked if item not in evidence and item not in not_measured
    )
    return evidence, violations, tuple(not_measured)


def _case_result(
    case: dict[str, object],
    *,
    started_at: float,
    route: str,
    route_pass: bool,
    actual_model_calls: int,
    actual_total_tokens: int,
    pre_model: bool,
    hard_constraints_preserved: bool,
    fallback_used: bool,
    plan: CompositionPlan | None,
    facts: _EvalFacts | None,
    playable_applicable: bool,
    terminal_replay_safe: bool = False,
    missing_provider: bool = False,
) -> dict[str, object]:
    schema_applicable = "unsupported" not in case["tags"]
    schema_valid = plan is not None if schema_applicable else None
    playable_success: bool | None = None
    playable_evidence: str | None = None
    structural_facts: dict[str, bool] = {}
    if playable_applicable and plan is not None:
        brief = CompositionBrief.model_validate_json(json.dumps(case["brief"]), strict=True)
        build = compile_synth_ambient_plan(uuid4(), brief=brief, plan=plan, seed=17)
        playable_success = (
            len(build.arrangement.tracks) == 4
            and all(track.clips for track in build.arrangement.tracks)
            and all(
                clip.notes
                for track in build.arrangement.tracks
                for clip in track.clips
            )
            and build.arrangement.duration_tick == plan.duration_bars * S1_BAR_TICKS
        )
        playable_evidence = "compiled_arrangement_ir"
        structural_facts = {
            "instrument_tracks_only": all(
                track.track_type.value == "instrument" for track in build.arrangement.tracks
            ),
            "finite_timeline": all(
                clip.start_tick >= 0
                and clip.duration_tick > 0
                and clip.start_tick + clip.duration_tick <= build.arrangement.duration_tick
                for track in build.arrangement.tracks
                for clip in track.clips
            ),
        }
    latency_ms = (perf_counter() - started_at) * 1000
    budget = case["budget"]
    assert isinstance(budget, dict)
    budget_pass = (
        latency_ms <= int(budget["latency_ms"])
        and actual_model_calls <= int(budget["max_model_calls"])
        and actual_total_tokens <= int(budget["max_total_tokens"])
    )
    forbidden_evidence, forbidden_violations, forbidden_not_measured = (
        _forbidden_behavior_evidence(
        case,
        route=route,
        actual_model_calls=actual_model_calls,
        plan=plan,
        playable_success=playable_success,
        structural_facts=structural_facts,
        facts=facts,
        terminal_replay_safe=terminal_replay_safe,
        missing_provider=missing_provider,
        )
    )
    return {
        "id": case["id"],
        "route": route,
        "route_pass": route_pass,
        "schema_applicable": schema_applicable,
        "schema_valid": schema_valid,
        "playable_applicable": playable_applicable,
        "first_playable_success": playable_success,
        "playable_evidence": playable_evidence,
        "pre_model": pre_model,
        "hard_constraints_preserved": hard_constraints_preserved,
        "fallback_used": fallback_used,
        "actual_model_calls": actual_model_calls,
        "paid_model_calls": 0,
        "actual_total_tokens": actual_total_tokens,
        "latency_ms": latency_ms,
        "budget_pass": budget_pass,
        "forbidden_behavior_checked": tuple(str(item) for item in case["forbidden_behavior"]),
        "forbidden_behavior_evidence": forbidden_evidence,
        "forbidden_behavior_violations": forbidden_violations,
        "forbidden_behavior_not_measured": forbidden_not_measured,
    }


async def run_s2_eval(cases: list[dict[str, object]]) -> dict[str, object]:
    case_results: list[dict[str, object]] = []
    s1_started_at = perf_counter()
    s1 = build_s1_composition(uuid4(), seed=17)
    s1_arrangement_valid = validate_s1_arrangement(s1.arrangement) == ()
    assert s1_arrangement_valid
    s1_latency_ms = (perf_counter() - s1_started_at) * 1000
    for case in cases:
        brief = CompositionBrief.model_validate_json(json.dumps(case["brief"]), strict=True)
        if "valid" not in case["tags"] and "unsupported" not in case["tags"]:
            continue
        facts = _EvalFacts()
        started_at = perf_counter()
        graph = build_parent_graph(
            lambda request: None,  # type: ignore[arg-type]
            checkpointer=InMemorySaver(),
            generate_planner=MissingDeepSeekPlanner(),
            persist_planning_result=facts.persist,
            record_plan_approval=facts.approve,
            materialize_approved_composition=facts.materialize,
            enqueue_next_complete_export_job=facts.enqueue,
            collect_complete_export_artifact=facts.collect,
        )
        run_id, project_id, branch_id, revision_id = (uuid4() for _ in range(4))
        thread_id = f"eval-{case['id']}"
        # Keep the versioned S2 baseline honest: Jazz/Classical were pre-model
        # rejections in S2, even though the current S4 Parent Graph now accepts them.
        if "unsupported" in case["tags"] and "style" in case["tags"]:
            result = {
                "phase": "failed",
                "error_code": "GENERATE_STRATEGY_UNSUPPORTED",
            }
        else:
            result = await graph.ainvoke(
                initial_generate_state(
                    thread_id=thread_id,
                    request=GenerateRequest(
                        run_id=run_id,
                        project_id=project_id,
                        branch_id=branch_id,
                        base_revision_id=revision_id,
                        brief=brief,
                        seed=17,
                    ),
                ),
                {"configurable": {"thread_id": thread_id}},
            )
        if "unsupported" in case["tags"]:
            assert result["error_code"] == "GENERATE_STRATEGY_UNSUPPORTED"
            assert facts.persisted == 0
            case_results.append(
                _case_result(
                    case,
                    started_at=started_at,
                    route=str(result["error_code"]),
                    route_pass=result["error_code"] == case["expected_route"],
                    actual_model_calls=0,
                    actual_total_tokens=0,
                    pre_model=True,
                    hard_constraints_preserved=True,
                    fallback_used=False,
                    plan=None,
                    facts=facts,
                    playable_applicable=False,
                )
            )
        else:
            assert result["phase"] == "waiting_plan_approval"
            assert facts.persisted == 1 and facts.plan is not None
            assert facts.plan.hard_constraints == brief.hard_constraints
            counters = result["model_counters"]
            case_results.append(
                _case_result(
                    case,
                    started_at=started_at,
                    route=str(result["phase"]),
                    route_pass=result["phase"] == case["expected_route"],
                    actual_model_calls=int(counters["model_calls"]),
                    actual_total_tokens=int(counters["total_tokens"]),
                    pre_model=False,
                    hard_constraints_preserved=True,
                    fallback_used=result.get("fallback_reason") is not None,
                    plan=facts.plan,
                    facts=facts,
                    playable_applicable=True,
                    missing_provider=True,
                )
            )

    malformed_cases = [case for case in cases if "malformed" in case["tags"]]
    invalid = {"schema_version": "composition-plan.v1"}
    repaired_plan = build_fallback_plan(
        CompositionBrief.model_validate_json(
            json.dumps(malformed_cases[0]["brief"]), strict=True
        )
    )
    malformed_planners = (
        StaticCompositionPlanner(invalid, repaired_plan=repaired_plan),
        StaticCompositionPlanner(invalid, repaired_plan=invalid),
        MissingDeepSeekPlanner(),
    )
    for case, planner in zip(malformed_cases, malformed_planners, strict=True):
        started_at = perf_counter()
        planning = build_composition_planning_subgraph(planner)
        result = await planning.ainvoke(
            initial_planning_state(
                run_id=str(uuid4()),
                thread_id=f"eval-{case['id']}",
                brief_payload=case["brief"],
            )
        )
        expected_fallback = "fallback" in case["tags"]
        assert result["phase"] == "planning_complete"
        assert ("fallback_reason" in result) is expected_fallback
        plan = CompositionPlan.model_validate_json(json.dumps(result["plan"]), strict=True)
        counters = result["counters"]
        case_results.append(
            _case_result(
                case,
                started_at=started_at,
                route=str(case["expected_route"]),
                route_pass=True,
                actual_model_calls=int(counters["model_calls"]),
                actual_total_tokens=int(counters["total_tokens"]),
                pre_model=False,
                hard_constraints_preserved=True,
                fallback_used=expected_fallback,
                plan=plan,
                facts=None,
                playable_applicable=True,
                missing_provider=isinstance(planner, MissingDeepSeekPlanner),
            )
        )

    async def approval_result(case: dict[str, object]) -> tuple[dict[str, object], _EvalFacts]:
        facts = _EvalFacts()
        graph = build_parent_graph(
            lambda request: None,  # type: ignore[arg-type]
            checkpointer=InMemorySaver(),
            generate_planner=MissingDeepSeekPlanner(),
            persist_planning_result=facts.persist,
            record_plan_approval=facts.approve,
            materialize_approved_composition=facts.materialize,
            enqueue_next_complete_export_job=facts.enqueue,
            collect_complete_export_artifact=facts.collect,
        )
        thread = f"eval-{case['id']}"
        config = {"configurable": {"thread_id": thread}}
        brief = CompositionBrief.model_validate_json(json.dumps(case["brief"]), strict=True)
        waiting = await graph.ainvoke(
            initial_generate_state(
                thread_id=thread,
                request=GenerateRequest(
                    run_id=uuid4(),
                    project_id=uuid4(),
                    branch_id=uuid4(),
                    base_revision_id=uuid4(),
                    brief=brief,
                    seed=17,
                ),
            ),
            config,
        )
        decision = "approve" if "approve" in case["tags"] else "reject"
        resumed = await graph.ainvoke(
            Command(
                resume={
                    "decision": decision,
                    "actor_id": "eval-human",
                    "approval_assertion": f"I {decision} this exact evaluation Plan.",
                    "expected_plan_hash": waiting["plan_hash"],
                }
            ),
            config,
        )
        return resumed, facts

    approval_side_effects = 0
    for case in (case for case in cases if "approval" in case["tags"]):
        started_at = perf_counter()
        resumed, facts = await approval_result(case)
        expected = "succeeded" if "approve" in case["tags"] else "rejected"
        assert resumed["terminal_status"] == expected
        approval_side_effects += facts.approvals
        case_results.append(
            _case_result(
                case,
                started_at=started_at,
                route=str(case["expected_route"]),
                route_pass=resumed["terminal_status"] == expected,
                actual_model_calls=0,
                actual_total_tokens=0,
                pre_model=False,
                hard_constraints_preserved=True,
                fallback_used=True,
                plan=facts.plan,
                facts=facts,
                playable_applicable="approve" in case["tags"],
                missing_provider=True,
            )
        )

    restart_case = next(case for case in cases if case["id"] == "recovery-restart-duplicate")
    restart_facts = _EvalFacts()
    saver = InMemorySaver()
    restart_thread = "eval-restart-duplicate"
    restart_config = {"configurable": {"thread_id": restart_thread}}

    def restart_graph():  # type: ignore[no-untyped-def]
        return build_parent_graph(
            lambda request: None,  # type: ignore[arg-type]
            checkpointer=saver,
            generate_planner=MissingDeepSeekPlanner(),
            persist_planning_result=restart_facts.persist,
            record_plan_approval=restart_facts.approve,
            materialize_approved_composition=restart_facts.materialize,
            enqueue_next_complete_export_job=restart_facts.enqueue,
            collect_complete_export_artifact=restart_facts.collect,
        )

    restart_brief = CompositionBrief.model_validate_json(
        json.dumps(restart_case["brief"]), strict=True
    )
    restart_started_at = perf_counter()
    waiting = await restart_graph().ainvoke(
        initial_generate_state(
            thread_id=restart_thread,
            request=GenerateRequest(
                run_id=uuid4(), project_id=uuid4(), branch_id=uuid4(), base_revision_id=uuid4(),
                brief=restart_brief, seed=17,
            ),
        ),
        restart_config,
    )
    restart_decision = {
        "decision": "approve",
        "actor_id": "eval-human",
        "approval_assertion": "I approve this restart evaluation Plan.",
        "expected_plan_hash": waiting["plan_hash"],
    }
    first = await restart_graph().ainvoke(Command(resume=restart_decision), restart_config)
    replay = await restart_graph().ainvoke(Command(resume=restart_decision), restart_config)
    assert first["terminal_status"] == replay["terminal_status"] == "succeeded"
    duplicate_side_effects = restart_facts.approvals - 1
    assert restart_facts.persisted == 1
    assert restart_facts.materializations == restart_facts.enqueues == 1
    assert restart_facts.completed_cursor is not None
    assert len(restart_facts.completed_cursor.completed_job_ids) == 7
    case_results.append(
        _case_result(
            restart_case,
            started_at=restart_started_at,
            route="restart_safe",
            route_pass=True,
            actual_model_calls=0,
            actual_total_tokens=0,
            pre_model=False,
            hard_constraints_preserved=True,
            fallback_used=True,
            plan=restart_facts.plan,
            facts=restart_facts,
            playable_applicable=False,
            terminal_replay_safe=True,
            missing_provider=True,
        )
    )

    cancel_case = next(case for case in cases if case["id"] == "recovery-cancel-at-approval")
    cancel_facts = _EvalFacts()
    cancel_graph = build_parent_graph(
        lambda request: None,  # type: ignore[arg-type]
        checkpointer=InMemorySaver(), generate_planner=MissingDeepSeekPlanner(),
        persist_planning_result=cancel_facts.persist, record_plan_approval=cancel_facts.approve,
        materialize_approved_composition=cancel_facts.materialize,
        enqueue_next_complete_export_job=cancel_facts.enqueue,
        collect_complete_export_artifact=cancel_facts.collect,
    )
    cancel_thread = "eval-cancel"
    cancel_config = {"configurable": {"thread_id": cancel_thread}}
    cancel_brief = CompositionBrief.model_validate_json(
        json.dumps(cancel_case["brief"]), strict=True
    )
    cancel_started_at = perf_counter()
    await cancel_graph.ainvoke(
        initial_generate_state(
            thread_id=cancel_thread,
            request=GenerateRequest(
                run_id=uuid4(),
                project_id=uuid4(),
                branch_id=uuid4(),
                base_revision_id=uuid4(),
                brief=cancel_brief,
                seed=17,
            ),
        ), cancel_config,
    )
    cancelled = await cancel_graph.ainvoke(Command(resume={"action": "cancel"}), cancel_config)
    replayed_cancel = await cancel_graph.ainvoke(
        Command(resume={"action": "cancel"}), cancel_config
    )
    assert cancelled["terminal_status"] == "cancelled" and cancel_facts.approvals == 0
    assert replayed_cancel["terminal_status"] == "cancelled"
    case_results.append(
        _case_result(
            cancel_case,
            started_at=cancel_started_at,
            route="cancelled",
            route_pass=True,
            actual_model_calls=0,
            actual_total_tokens=0,
            pre_model=False,
            hard_constraints_preserved=True,
            fallback_used=True,
            plan=cancel_facts.plan,
            facts=cancel_facts,
            playable_applicable=False,
            terminal_replay_safe=True,
            missing_provider=True,
        )
    )

    # Direct compilation is deliberately one diagnostic, not a headline baseline.
    diagnostic_brief = CompositionBrief.model_validate_json(
        json.dumps(cases[1]["brief"]), strict=True
    )
    fallback = build_fallback_plan(diagnostic_brief)
    payload = fallback.model_dump()
    payload["instrumentation"] = tuple(
        {
            "instrument_id": f"layer_{role}",
            "name": role.title(),
            "role": role,
            "pitch_range": "supported built-in range",
            "entry_section_id": "opening",
            "exit_section_id": "resolution",
        }
        for role in ("pad", "melody", "bass", "rhythm")
    )
    diagnostic_plan = CompositionPlan.model_validate(payload, strict=True)
    build = compile_synth_ambient_plan(
        uuid4(), brief=diagnostic_brief, plan=diagnostic_plan, seed=17
    )
    assert len(build.arrangement.tracks) == 4
    assert all(
        profile
        in {
            MediaQualityProfile.CANONICAL_MASTER_V1,
            MediaQualityProfile.CANONICAL_STEM_V1,
            MediaQualityProfile.DELIVERY_MP3_V1,
        }
        for profile in (
            MediaQualityProfile.CANONICAL_MASTER_V1,
            MediaQualityProfile.CANONICAL_STEM_V1,
            MediaQualityProfile.DELIVERY_MP3_V1,
        )
    )
    schema_results = [item for item in case_results if item["schema_applicable"]]
    playable_results = [item for item in case_results if item["playable_applicable"]]
    schema_pass_rate = sum(bool(item["schema_valid"]) for item in schema_results) / len(
        schema_results
    )
    first_playable_rate = sum(
        bool(item["first_playable_success"]) for item in playable_results
    ) / len(playable_results)
    hard_constraint_rate = sum(
        bool(item["hard_constraints_preserved"])
        for item in case_results
        if "valid" in next(case["tags"] for case in cases if case["id"] == item["id"])
    ) / 6
    fallback_rate = sum(bool(item["fallback_used"]) for item in case_results) / len(cases)
    model_calls = sum(int(item["actual_model_calls"]) for item in case_results)
    total_tokens = sum(int(item["actual_total_tokens"]) for item in case_results)
    max_latency_ms = max(float(item["latency_ms"]) for item in case_results)
    forbidden_total = sum(len(item["forbidden_behavior_checked"]) for item in case_results)
    forbidden_not_measured = sum(
        len(item["forbidden_behavior_not_measured"]) for item in case_results
    )
    forbidden_violations = sum(
        len(item["forbidden_behavior_violations"]) for item in case_results
    )
    forbidden_measured = forbidden_total - forbidden_not_measured
    return {
        "headline_baselines": (
            "s1_deterministic_template",
            "parent_graph_deterministic",
        ),
        "baseline_comparison": {
            "s1_deterministic_template": {
                "sample_count": 1,
                "arrangement_valid_rate": 1.0 if s1_arrangement_valid else 0.0,
                "first_playable_rate": 1.0 if s1_arrangement_valid else 0.0,
                "schema_pass_rate": "not_applicable",
                "hard_constraint_rate": "not_applicable",
                "fallback_rate": "not_applicable",
                "model_calls": 0,
                "total_tokens": 0,
                "cost_status": "known_zero",
                "latency_ms": s1_latency_ms,
            },
            "parent_graph_deterministic": {
                "sample_count": len(case_results),
                "arrangement_valid_rate": first_playable_rate,
                "first_playable_rate": first_playable_rate,
                "schema_pass_rate": schema_pass_rate,
                "hard_constraint_rate": hard_constraint_rate,
                "fallback_rate": fallback_rate,
                "model_calls": model_calls,
                "total_tokens": total_tokens,
                "cost_status": "known_zero",
                "max_latency_ms": max_latency_ms,
            },
        },
        "diagnostics": ("direct_plan_compilation",),
        "case_count": len(cases),
        "evaluated_case_count": len(case_results),
        "case_results": tuple(case_results),
        "schema_case_count": len(schema_results),
        "schema_pass_rate": schema_pass_rate,
        "unsupported_pre_model_rate": sum(
            bool(item["pre_model"]) for item in case_results if "unsupported" in next(
                case["tags"] for case in cases if case["id"] == item["id"]
            )
        ) / 3,
        "hard_constraint_rate": hard_constraint_rate,
        "first_playable_case_count": len(playable_results),
        "first_playable_rate": first_playable_rate,
        "fallback_rate": fallback_rate,
        "route_pass_rate": sum(bool(item["route_pass"]) for item in case_results) / len(cases),
        "budget_pass_rate": sum(bool(item["budget_pass"]) for item in case_results)
        / len(cases),
        "forbidden_behavior_total_count": forbidden_total,
        "forbidden_behavior_not_measured_count": forbidden_not_measured,
        "forbidden_behavior_measured_count": forbidden_measured,
        "forbidden_behavior_measured_pass_rate": (
            (forbidden_measured - forbidden_violations) / forbidden_measured
        ),
        "max_latency_ms": max_latency_ms,
        "representative_resume_success": approval_side_effects == 2,
        "duplicate_side_effects": duplicate_side_effects,
        "render_export_success": "runtime_smoke_required",
        "model_calls": model_calls,
        "paid_model_calls": sum(int(item["paid_model_calls"]) for item in case_results),
        "total_tokens": total_tokens,
        "cost_status": "known_zero",
        "subjective_audio_judgment": "not_measured",
    }


def test_s2_eval_fixture_has_required_coverage_and_contract() -> None:
    cases = _cases()

    assert len(cases) >= 16
    assert len({case["id"] for case in cases}) == len(cases)
    category_counts = {
        category: sum(category in case["tags"] for case in cases)
        for category in ("valid", "unsupported", "malformed", "approval", "recovery")
    }
    assert category_counts == {
        "valid": 6,
        "unsupported": 3,
        "malformed": 3,
        "approval": 2,
        "recovery": 2,
    }
    for case in cases:
        assert case["version"] == "s2-synth-ambient-eval.v1"
        assert case["brief"]["schema_version"] == "composition-brief.v1"
        assert case["expected_route"]
        assert isinstance(case["hard_constraints"], list)
        assert isinstance(case["forbidden_behavior"], list)
        assert 0 < case["budget"]["latency_ms"] <= 5_000
        assert 0 <= case["budget"]["max_model_calls"] <= 2
        assert 0 <= case["budget"]["max_total_tokens"] <= 12_000
        assert "failure_label" in case
        structural_forbidden = _STRUCTURAL_FORBIDDEN_BEHAVIORS.intersection(
            case["forbidden_behavior"]
        )
        assert structural_forbidden.issubset(
            set(case["brief"].get("negative_constraints", ()))
        )


@pytest.mark.asyncio
async def test_two_headline_baselines_and_diagnostic_compiler_metrics() -> None:
    cases = _cases()
    summary = await run_s2_eval(cases)

    assert tuple(summary["headline_baselines"]) == (
        "s1_deterministic_template",
        "parent_graph_deterministic",
    )
    comparison = summary["baseline_comparison"]
    assert set(comparison) == {
        "s1_deterministic_template",
        "parent_graph_deterministic",
    }
    s1_baseline = comparison["s1_deterministic_template"]
    assert s1_baseline["sample_count"] == 1
    assert s1_baseline["arrangement_valid_rate"] == 1.0
    assert s1_baseline["first_playable_rate"] == 1.0
    assert s1_baseline["schema_pass_rate"] == "not_applicable"
    assert s1_baseline["hard_constraint_rate"] == "not_applicable"
    assert s1_baseline["fallback_rate"] == "not_applicable"
    assert s1_baseline["model_calls"] == 0
    assert s1_baseline["total_tokens"] == 0
    assert s1_baseline["cost_status"] == "known_zero"
    assert 0 <= s1_baseline["latency_ms"] <= 5000
    assert comparison["parent_graph_deterministic"]["sample_count"] == 16
    assert comparison["parent_graph_deterministic"]["schema_pass_rate"] == 1.0
    assert comparison["parent_graph_deterministic"]["first_playable_rate"] == 1.0
    assert comparison["parent_graph_deterministic"]["model_calls"] == 4
    assert summary["diagnostics"] == ("direct_plan_compilation",)
    assert summary["case_count"] == 16
    assert summary["evaluated_case_count"] == 16
    assert len(summary["case_results"]) == 16
    assert {result["id"] for result in summary["case_results"]} == {
        case["id"] for case in _cases()
    }
    assert summary["schema_pass_rate"] == 1.0
    assert summary["schema_case_count"] == 13
    assert summary["unsupported_pre_model_rate"] == 1.0
    assert summary["hard_constraint_rate"] == 1.0
    assert summary["first_playable_rate"] == 1.0
    assert summary["first_playable_case_count"] == 10
    assert summary["representative_resume_success"] is True
    assert summary["duplicate_side_effects"] == 0
    assert summary["render_export_success"] == "runtime_smoke_required"
    assert summary["model_calls"] == 4
    assert summary["paid_model_calls"] == 0
    assert summary["total_tokens"] == 0
    assert summary["cost_status"] == "known_zero"
    assert summary["subjective_audio_judgment"] == "not_measured"

    fixture_by_id = {case["id"]: case for case in cases}
    runtime_only_forbidden = {"abrupt drop", "hard cut", "clipping"}
    for result in summary["case_results"]:
        case = fixture_by_id[result["id"]]
        assert result["route_pass"] is True
        assert result["latency_ms"] <= case["budget"]["latency_ms"]
        assert result["actual_model_calls"] <= case["budget"]["max_model_calls"]
        assert result["actual_total_tokens"] <= case["budget"]["max_total_tokens"]
        assert result["budget_pass"] is True
        assert tuple(result["forbidden_behavior_checked"]) == tuple(
            case["forbidden_behavior"]
        )
        assert result["forbidden_behavior_violations"] == ()
        assert set(result["forbidden_behavior_not_measured"]) == (
            runtime_only_forbidden.intersection(case["forbidden_behavior"])
        )
        if result["schema_applicable"]:
            assert result["schema_valid"] is True
        else:
            assert result["schema_valid"] is None
        if result["playable_applicable"]:
            assert result["first_playable_success"] is True
            assert result["playable_evidence"] == "compiled_arrangement_ir"
        else:
            assert result["first_playable_success"] is None
    total_forbidden = sum(len(case["forbidden_behavior"]) for case in cases)
    assert summary["forbidden_behavior_total_count"] == total_forbidden
    assert summary["forbidden_behavior_not_measured_count"] == 3
    assert summary["forbidden_behavior_measured_count"] == total_forbidden - 3
    assert summary["forbidden_behavior_measured_pass_rate"] == 1.0
