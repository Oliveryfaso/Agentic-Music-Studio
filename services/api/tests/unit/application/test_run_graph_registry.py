from __future__ import annotations

from motif_forge.application.run_graph_registry import GENERATE_GRAPH_REGISTRY


def test_generate_registry_is_stable_complete_presentation_metadata() -> None:
    registry = GENERATE_GRAPH_REGISTRY

    assert registry.graph_version == "motif-forge-parent.v2"
    assert [phase.id for phase in registry.phases] == [
        "planning",
        "approval",
        "candidates",
        "critic",
        "commit",
        "export",
        "error",
    ]
    node_ids = [node.id for node in registry.nodes]
    assert len(node_ids) == len(set(node_ids))
    assert all(":" in node_id and len(node_id) < 80 for node_id in node_ids)

    technical_names = {node.technical_name for node in registry.nodes}
    assert {
        "ValidateRequest",
        "PlanInputAdapter",
        "ValidateBrief",
        "CompositionPlanner",
        "ValidatePlan",
        "RepairPlan",
        "DeterministicPlanFallback",
        "PlanOutputAdapter",
        "PlanApproval",
        "CreateCandidateBranch",
        "CandidateFanIn",
        "EnqueueCandidatePreview",
        "WaitForCandidatePreview",
        "CriticizeCandidates",
        "ApplyCriticRepair",
        "CreateCandidateSelectionPreviews",
        "CandidateSelection",
        "MaterializeSelectedCandidate",
        "MaterializeApprovedComposition",
        "StoragePressureGate",
        "EnqueueCompleteExportStep",
        "WaitForGenerateJobEvent",
        "CompleteGenerate",
        "RouteError",
    } <= technical_names

    candidates = [node for node in registry.nodes if node.technical_name == "CreateCandidateBranch"]
    assert [node.id for node in candidates] == [
        "candidates:candidate-a",
        "candidates:candidate-b",
    ]
    assert all(node.kind == "deterministic" for node in candidates)
    assert next(node for node in registry.nodes if node.id == "approval:plan").kind == "human"
    assert next(node for node in registry.nodes if node.id == "critic:evaluate").kind == "agent"
    assert next(node for node in registry.nodes if node.id == "export:enqueue").kind == "worker"

    endpoint_ids = {edge.source for edge in registry.edges} | {
        edge.target for edge in registry.edges
    }
    assert endpoint_ids <= set(node_ids)
    assert any(edge.relation == "parallel" for edge in registry.edges)
    assert any(edge.relation == "join" for edge in registry.edges)
    assert any(edge.relation == "loop" for edge in registry.edges)
    assert any(edge.relation == "worker_boundary" for edge in registry.edges)

    hidden_names = {node.technical_name for node in registry.nodes if not node.default_visible}
    assert {
        "PlanInputAdapter",
        "PlanOutputAdapter",
        "ErrorRouter",
        "PlanningTerminalRouter",
        "MaterializeApprovedComposition",
        "RouteError",
    } <= hidden_names
    assert not hasattr(registry, "compile")
    assert not hasattr(registry, "checkpointer")
