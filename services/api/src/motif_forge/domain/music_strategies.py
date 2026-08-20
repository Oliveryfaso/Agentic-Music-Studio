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
    PPQ,
    ArrangementIR,
    Articulation,
    AudioClip,
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
    clips: list[NoteClip | AudioClip] = []
    for clip in track.clips:
        if not isinstance(clip, NoteClip):
            clips.append(clip)
            continue
        notes = []
        for index, note in enumerate(clip.notes):
            update: dict[str, object] = {"articulation": articulation}
            if pack.style == "minimal_electronic":
                if track.role is TrackRole.MELODY and index % 2:
                    update["start_tick"] = min(
                        note.start_tick + PPQ // 2,
                        clip.duration_tick - note.duration_tick,
                    )
                if track.role in {TrackRole.HARMONY, TrackRole.BASS}:
                    update["duration_tick"] = min(note.duration_tick, PPQ)
                if track.role is TrackRole.RHYTHM:
                    update["pitch"] = 36 if index % 2 == 0 else 42
            elif pack.style == "classical_chamber":
                contours = {
                    TrackRole.HARMONY: (0, 2, 1, 3, 2, 1, 0, 2),
                    TrackRole.MELODY: (0, 2, 4, 5, 4, 2, 0, 1),
                    TrackRole.BASS: (0, 2, 3, 2, 0, 1, 3, 1),
                    TrackRole.RHYTHM: (0, 2, 4, 2, 0, 2, 3, 1),
                }
                base = {
                    TrackRole.HARMONY: 60,
                    TrackRole.MELODY: 67,
                    TrackRole.BASS: 43,
                    TrackRole.RHYTHM: 48,
                }[track.role]
                update["pitch"] = min(
                    guide.high_midi,
                    max(guide.low_midi, base + contours[track.role][index % 8]),
                )
                update["duration_tick"] = min(note.duration_tick, PPQ - 60)
            elif pack.style == "jazz_harmony_improvisation":
                if (note.start_tick // PPQ) % 2:
                    update["start_tick"] = min(
                        note.start_tick + PPQ // 6,
                        clip.duration_tick - note.duration_tick,
                    )
                if track.role is TrackRole.MELODY and index % 4 == 0:
                    guide_pitch_class = 4 if (index // 4) % 2 == 0 else 11
                    candidates = range(guide.low_midi, guide.high_midi + 1)
                    update["pitch"] = min(
                        (pitch for pitch in candidates if pitch % 12 == guide_pitch_class),
                        key=lambda pitch: abs(pitch - note.pitch),
                    )
            notes.append(note.model_copy(update=update))
        clips.append(clip.model_copy(update={"notes": tuple(notes)}))
    return track.model_copy(
        update={
            "name": guide.instrument,
            "instrument_ref": preset.preset_id,
            "clips": tuple(clips),
        }
    )


def _lock_minimal_bass_to_drums(tracks: tuple[Track, ...]) -> tuple[Track, ...]:
    rhythm = next(track for track in tracks if track.role is TrackRole.RHYTHM)
    drum_onsets = {
        clip.start_tick + note.start_tick
        for clip in rhythm.clips
        if isinstance(clip, NoteClip)
        for note in clip.notes
    }
    aligned: list[Track] = []
    for track in tracks:
        if track.role is not TrackRole.BASS:
            aligned.append(track)
            continue
        clips = tuple(
            clip.model_copy(
                update={
                    "notes": tuple(
                        note
                        for note in clip.notes
                        if clip.start_tick + note.start_tick in drum_onsets
                    )
                }
            )
            if isinstance(clip, NoteClip)
            else clip
            for clip in track.clips
        )
        aligned.append(track.model_copy(update={"clips": clips}))
    return tuple(aligned)


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
    if pack.style == "minimal_electronic":
        styled_tracks = tuple(
            command.payload.track
            for command in commands
            if isinstance(command, AddTrackCommand)
        )
        aligned = iter(_lock_minimal_bass_to_drums(styled_tracks))
        commands = [
            command.model_copy(
                update={"payload": command.payload.model_copy(update={"track": next(aligned)})}
            )
            if isinstance(command, AddTrackCommand)
            else command
            for command in commands
        ]
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
