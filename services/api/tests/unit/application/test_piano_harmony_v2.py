from types import SimpleNamespace
from uuid import uuid4

import pytest
from motif_forge.application.classical_import import reviewed_score
from motif_forge.application.errors import ApplicationError
from motif_forge.application.piano_harmony import resolve_piano_harmony
from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.commands import apply_commands


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "score,beats,bars,chord,pattern",
    [
        ("c01-minuet-g-a16.v1", 3, 16, "G", "broken"),
        ("c02-la-candeur-a8.v1", 4, 8, "Dm", "broken"),
        ("j01-bethena-a-first8.v1", 3, 8, "G", "roots"),
        ("c02-la-candeur-a8.v1", 4, 8, "F", "roots"),
    ],
)
async def test_explicit_rule_harmony_uses_real_meter_and_chord_tones(
    score, beats, bars, chord, pattern
):
    project = uuid4()
    _, xml = reviewed_score(score)
    source = score_to_arrangement(
        parse_musicxml(xml, namespace=project), project_id=project, source_ref="score:" + score
    )
    cmd = accompaniment_command(
        source, AccompanimentIntent(pattern=pattern, chords=(chord,) * bars), request_id=uuid4()
    )
    base = apply_commands(source, (cmd,))
    revision = uuid4()

    class Tx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get_revision(self, _):
            return SimpleNamespace(
                revision_id=revision,
                project_id=project,
                source_run_id=None,
                parent_revision_id=None,
                arrangement_ir=base,
            )

        async def list_revision_commands(self, _):
            return (cmd,)

    class Store:
        async def read(self, _):
            raise AssertionError("human recipe has no model record")

    assert await resolve_piano_harmony(
        Tx, Store(), revision_id=revision, base=base, start_bar=5, end_bar=8
    ) == dict.fromkeys(range(5, 9), chord)


@pytest.mark.asyncio
async def test_single_d_root_cannot_prove_major_or_minor_in_new_rule_vocabulary():
    project = uuid4()
    _, xml = reviewed_score("c02-la-candeur-a8.v1")
    source = score_to_arrangement(
        parse_musicxml(xml, namespace=project),
        project_id=project,
        source_ref="score:c02-la-candeur-a8.v1",
    )
    cmd = accompaniment_command(
        source, AccompanimentIntent(pattern="roots", chords=("Dm",) * 8), request_id=uuid4()
    )
    base = apply_commands(source, (cmd,))
    revision = uuid4()

    class Tx:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def get_revision(self, _):
            return SimpleNamespace(
                revision_id=revision,
                project_id=project,
                source_run_id=None,
                parent_revision_id=None,
                arrangement_ir=base,
            )

        async def list_revision_commands(self, _):
            return (cmd,)

    with pytest.raises(ApplicationError, match="verified"):
        await resolve_piano_harmony(
            Tx, None, revision_id=revision, base=base, start_bar=5, end_bar=8
        )
