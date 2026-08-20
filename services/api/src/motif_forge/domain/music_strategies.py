"""Allowlisted deterministic strategy routing inside the existing Generate flow."""

from __future__ import annotations

from uuid import UUID

from motif_forge.agent.schemas import CompositionBrief, CompositionPlan
from motif_forge.domain.canonical import arrangement_content_hash
from motif_forge.domain.commands import (
    AddTrackCommand,
    EditorCommand,
    InitializeCompositionCommand,
    apply_commands,
)
from motif_forge.domain.composition import (
    CompositionBuild,
    PatternRole,
    compile_synth_ambient_plan,
)
from motif_forge.domain.ir import (
    ArrangementIR,
    Articulation,
    DomainModel,
    NoteClip,
    ProvenanceRef,
    Track,
    TrackRole,
    create_empty_arrangement,
)
from motif_forge.domain.style_packs import (
    StylePack,
    StylePackRegistry,
    builtin_style_pack_registry,
)
from motif_forge.domain.theory import TheoryEngine, TheoryReport

_CANONICAL_ROLES = tuple(role.value for role in PatternRole)
_COMPILER_VERSIONS = {
    "synth_ambient": "synth-ambient-compiler.v1",
    "minimal_electronic": "minimal-electronic-compiler.v1",
    "classical_chamber": "classical-chamber-compiler.v1",
    "jazz_harmony_improvisation": "jazz-harmony-improvisation-compiler.v1",
}
_ARTICULATION = {
    "minimal_electronic": {
        TrackRole.HARMONY: Articulation.STACCATO,
        TrackRole.MELODY: Articulation.STACCATO,
        TrackRole.BASS: Articulation.NORMAL,
        TrackRole.RHYTHM: Articulation.ACCENT,
    },
    "classical_chamber": {
        TrackRole.HARMONY: Articulation.TENUTO,
        TrackRole.MELODY: Articulation.LEGATO,
        TrackRole.BASS: Articulation.TENUTO,
        TrackRole.RHYTHM: Articulation.STACCATO,
    },
    "jazz_harmony_improvisation": {
        TrackRole.HARMONY: Articulation.TENUTO,
        TrackRole.MELODY: Articulation.ACCENT,
        TrackRole.BASS: Articulation.NORMAL,
        TrackRole.RHYTHM: Articulation.STACCATO,
    },
}


class StrategyCompilationError(ValueError):
    def __init__(self, report: TheoryReport) -> None:
        self.report = report
        super().__init__("strategy compilation produced blocking theory issues")


class StrategyResult(DomainModel):
    build: CompositionBuild
    pack: StylePack
    theory_report: TheoryReport
    compiler_version: str


def _proxy_plan(plan: CompositionPlan) -> CompositionPlan:
    instrumentation = tuple(
        item.model_copy(update={"role": role})
        for item, role in zip(plan.instrumentation, _CANONICAL_ROLES, strict=True)
    )
    return plan.model_copy(update={"genre": "synth_ambient", "instrumentation": instrumentation})


def _style_track(track: Track, pack: StylePack) -> Track:
    guide = next(item for item in pack.instrumentation if item.track_role is track.role)
    preset = next(item for item in pack.preset_palette if item.role == guide.role)
    articulation = _ARTICULATION[pack.style][track.role]
    clips = tuple(
        clip.model_copy(
            update={
                "notes": tuple(
                    note.model_copy(update={"articulation": articulation}) for note in clip.notes
                )
            }
        )
        if isinstance(clip, NoteClip)
        else clip
        for clip in track.clips
    )
    return track.model_copy(
        update={"name": guide.instrument, "instrument_ref": preset.preset_id, "clips": clips}
    )


def _restyle_build(
    project_id: UUID, build: CompositionBuild, pack: StylePack, compiler_version: str
) -> CompositionBuild:
    commands: list[EditorCommand] = []
    for command in build.commands:
        if isinstance(command, AddTrackCommand):
            track = _style_track(command.payload.track, pack)
            commands.append(
                command.model_copy(
                    update={"payload": command.payload.model_copy(update={"track": track})}
                )
            )
        elif isinstance(command, InitializeCompositionCommand):
            provenance = (
                *command.payload.provenance,
                ProvenanceRef(kind="knowledge", ref=pack.pack_id, version=pack.version),
                ProvenanceRef(
                    kind="engine", ref="motif-forge-music-strategy", version=compiler_version
                ),
            )
            commands.append(
                command.model_copy(
                    update={
                        "payload": command.payload.model_copy(update={"provenance": provenance})
                    }
                )
            )
        else:
            commands.append(command)
    typed_commands = tuple(commands)
    arrangement: ArrangementIR = apply_commands(
        create_empty_arrangement(project_id), typed_commands
    )
    return build.model_copy(
        update={
            "commands": typed_commands,
            "arrangement": arrangement,
            "content_hash": arrangement_content_hash(arrangement),
        }
    )


class MusicStrategyRouter:
    def __init__(
        self,
        registry: StylePackRegistry | None = None,
        theory_engine: TheoryEngine | None = None,
    ) -> None:
        self._registry = registry or builtin_style_pack_registry()
        self._theory = theory_engine or TheoryEngine()

    def compile(
        self,
        project_id: UUID,
        *,
        brief: CompositionBrief,
        plan: CompositionPlan,
        seed: int,
    ) -> StrategyResult:
        if brief.style != plan.genre:
            raise ValueError("Brief and Plan styles must match")
        pack = self._registry.resolve(brief.style)
        compiler_version = _COMPILER_VERSIONS[brief.style]
        if brief.style == "synth_ambient":
            build = compile_synth_ambient_plan(project_id, brief=brief, plan=plan, seed=seed)
        else:
            proxy_brief = brief.model_copy(update={"style": "synth_ambient"})
            build = compile_synth_ambient_plan(
                project_id, brief=proxy_brief, plan=_proxy_plan(plan), seed=seed
            )
            build = _restyle_build(project_id, build, pack, compiler_version)
        report = self._theory.evaluate(build.arrangement, pack)
        if report.blocking:
            raise StrategyCompilationError(report)
        return StrategyResult(
            build=build,
            pack=pack,
            theory_report=report,
            compiler_version=compiler_version,
        )
