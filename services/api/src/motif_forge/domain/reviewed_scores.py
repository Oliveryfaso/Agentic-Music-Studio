"""Version-pinned score identities, independent of HTTP, storage and model providers."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from motif_forge.domain.ir import ArrangementIR, MusicalMode

ScoreId = Literal[
    "mutopia-528-melody.v1",
    "c01-minuet-g-a16.v1",
    "c02-la-candeur-a8.v1",
    "j01-bethena-a-first8.v1",
]


@dataclass(frozen=True, slots=True)
class ReviewedScore:
    score_id: str
    xml_sha256: str
    beats: int
    tonic: str
    measures: int
    bpm: int
    manifest_path: str
    xml_path: str
    manifest_sha256: str | None = None

    @property
    def bar_ticks(self) -> int:
        return self.beats * 480


_SCORES = [
    ReviewedScore(
        "mutopia-528-melody.v1",
        "995a1d612fd073be18902ada308a525ee973206e0113e5010e1af3520b628907",
        4,
        "G",
        16,
        100,
        "ode-manifest.json",
        "ode-melody.musicxml",
    ),
    ReviewedScore(
        "c01-minuet-g-a16.v1",
        "7f223a9cc8b64af65a28f4a12892acca6b65a7acf8391a820bfba0ff4cd3ac72",
        3,
        "G",
        16,
        100,
        "c01-minuet-g-a16/manifest.json",
        "c01-minuet-g-a16/melody-principal.musicxml",
        "e4011f6fb2045343017b791e74939af15fa986b98a05f239d88c54514113186d",
    ),
    ReviewedScore(
        "c02-la-candeur-a8.v1",
        "3bbe6a5e4e1487679e87570835039ffe143092176f49b097168c54b7f9376663",
        4,
        "C",
        8,
        112,
        "c02-la-candeur-a8/manifest.json",
        "c02-la-candeur-a8/melody-principal.musicxml",
        "283a4db2c65c406a3aafa80a27977965bd3b18c3644977fba7b3cff012fc9818",
    ),
    ReviewedScore(
        "j01-bethena-a-first8.v1",
        "1f7116b0950708f16bfc3ef3434fc7c34c810a646715aae92f3d4ce8dc72ecc6",
        3,
        "G",
        8,
        120,
        "j01-bethena-a-first8/manifest.json",
        "j01-bethena-a-first8/melody-principal.musicxml",
        "46cb8ca145db776348c7304422a238b5a6acca45b53b5d9f4ace132fd288832f",
    ),
]
REVIEWED_SCORES = MappingProxyType({s.score_id: s for s in _SCORES})


def reviewed_source(base: ArrangementIR) -> ReviewedScore:
    refs = [p for p in base.provenance if p.ref.startswith("score:")]
    source = REVIEWED_SCORES.get(refs[0].ref.removeprefix("score:")) if len(refs) == 1 else None
    if (
        source is None
        or refs[0].kind != "asset"
        or refs[0].version != source.xml_sha256
        or base.ppq != 480
        or base.duration_tick != (source.measures + 1) * source.bar_ticks
        or len(base.time_signature_map) != 1
        or base.time_signature_map[0].tick != 0
        or base.time_signature_map[0].numerator != source.beats
        or base.time_signature_map[0].denominator != 4
        or len(base.key_map) != 1
        or base.key_map[0].tick != 0
        or base.key_map[0].tonic != source.tonic
        or base.key_map[0].mode is not MusicalMode.MAJOR
    ):
        raise ValueError("CLASSICAL_SOURCE_REQUIRED")
    return source
