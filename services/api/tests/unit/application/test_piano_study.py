from uuid import uuid4

from motif_forge.application.piano_study import study_commands
from motif_forge.domain.commands import apply_commands
from motif_forge.domain.ir import create_empty_arrangement


def test_self_authored_study_is_deterministic_30_seconds_with_rest_tail():
    project = uuid4()
    commands = study_commands(project)
    score = apply_commands(create_empty_arrangement(project), commands)
    assert score == apply_commands(create_empty_arrangement(project), study_commands(project))
    assert score.tempo_map[0].bpm == 128 and score.duration_tick == 30720
    notes = score.tracks[0].clips[0].notes
    assert len(notes) == 96 and max(n.start_tick + n.duration_tick for n in notes) < 23040
    assert all(c.actor_kind == "system" for c in commands)
