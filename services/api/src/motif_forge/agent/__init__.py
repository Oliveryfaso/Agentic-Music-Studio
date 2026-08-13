"""Explicit, finite orchestration for Motif Forge AI tasks."""

# Keep package import side-effect free so strict schemas can be used by domain models.
__all__ = [
    "CompositionBrief",
    "CompositionPlan",
    "build_composition_plan_graph",
    "build_parent_graph",
    "initial_import_state",
    "initial_plan_state",
    "initial_time_stretch_state",
]


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    if name in {"CompositionBrief", "CompositionPlan"}:
        from motif_forge.agent.schemas import CompositionBrief, CompositionPlan

        return {"CompositionBrief": CompositionBrief, "CompositionPlan": CompositionPlan}[name]
    if name in {"build_composition_plan_graph", "initial_plan_state"}:
        from motif_forge.agent.graph import build_composition_plan_graph, initial_plan_state

        exports = {
            "build_composition_plan_graph": build_composition_plan_graph,
            "initial_plan_state": initial_plan_state,
        }
        return exports[name]
    if name in {"build_parent_graph", "initial_import_state", "initial_time_stretch_state"}:
        from motif_forge.agent.parent_graph import (
            build_parent_graph,
            initial_import_state,
            initial_time_stretch_state,
        )

        exports = {
            "build_parent_graph": build_parent_graph,
            "initial_import_state": initial_import_state,
            "initial_time_stretch_state": initial_time_stretch_state,
        }
        return exports[name]
    raise AttributeError(name)
