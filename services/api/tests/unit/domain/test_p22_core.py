import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import HumanMessage
from motif_forge.application.undo import build_inverse_commands
from motif_forge.domain.accompaniment import AccompanimentIntent, accompaniment_command
from motif_forge.domain.classical_score import parse_musicxml, score_to_arrangement
from motif_forge.domain.commands import EDITOR_COMMAND_ADAPTER, apply_commands
from motif_forge.domain.ir import DomainModel
from motif_forge.domain.policies import compute_change_impact
from motif_forge.domain.revisions import ChangeImpact
from motif_forge.providers.deepseek import DeepSeekJsonClient


def test_agent_append_is_a_distinct_l2_command_and_exact_undo():
    from motif_forge.domain.commands import AgentAppendPianoTrackCommand
    from motif_forge.resources import scores

    xml = Path(next(iter(scores.__path__))) / "ode-melody.musicxml"
    project = uuid4()
    base = score_to_arrangement(
        parse_musicxml(xml.read_bytes(), namespace=project),
        project_id=project,
        source_ref="score:mutopia-528-melody.v1",
    )
    human = accompaniment_command(
        base, AccompanimentIntent(pattern="roots", chords=("G",) * 16), request_id=uuid4()
    )
    command = AgentAppendPianoTrackCommand(
        command_id=uuid4(), client_sequence=0, payload=human.payload
    )
    assert EDITOR_COMMAND_ADAPTER.validate_json(command.model_dump_json()) == command
    assert command.actor_kind == "agent" and compute_change_impact((command,)) is ChangeImpact.L2
    candidate = apply_commands(base, (command,))
    assert candidate.tracks[0] == base.tracks[0]
    inverse = build_inverse_commands(base, candidate, (command,), actor_id="human:local")
    assert apply_commands(candidate, inverse) == base


def test_selected_piano_range_preserves_outside_and_restores_exact_parent():
    from motif_forge.domain.commands import (
        ReplacePianoRangeCommand,
        ReplacePianoRangePayload,
        Selection,
    )
    from motif_forge.domain.piano_plan import AccompanimentPlan, BarPlan, compile_piano_plan
    from motif_forge.resources import scores

    xml = Path(next(iter(scores.__path__))) / "ode-melody.musicxml"
    project = uuid4()
    original = score_to_arrangement(
        parse_musicxml(xml.read_bytes(), namespace=project),
        project_id=project,
        source_ref="score:mutopia-528-melody.v1",
    )
    append = accompaniment_command(
        original, AccompanimentIntent(pattern="broken", chords=("G",) * 16), request_id=uuid4()
    )
    base = apply_commands(original, (append,))
    plan = AccompanimentPlan(
        summary="更轻更稀疏",
        bars=tuple(
            BarPlan(bar=i, chord="G", grid=(0,), octave=2, velocity=36) for i in range(9, 13)
        ),
    )
    replacement = compile_piano_plan(
        base,
        plan,
        request_id=uuid4(),
        target_track_id=base.tracks[1].track_id,
        start_bar=9,
        end_bar=12,
    )
    command = ReplacePianoRangeCommand(
        command_id=uuid4(),
        client_sequence=0,
        actor_kind="agent",
        selection=Selection(
            track_ids=(replacement.track_id,), start_tick=8 * 1920, end_tick=12 * 1920
        ),
        payload=ReplacePianoRangePayload(track=replacement, start_bar=9, end_bar=12),
    )
    result = apply_commands(base, (command,))
    assert result.tracks[0] == base.tracks[0]

    def outside(t):
        return tuple(n for n in t.clips[0].notes if not 8 * 1920 <= n.start_tick < 12 * 1920)

    assert outside(result.tracks[1]) == outside(base.tracks[1])
    assert (
        apply_commands(
            result, build_inverse_commands(base, result, (command,), actor_id="human:local")
        )
        == base
    )
    bad = replacement.model_copy(update={"gain_db": -9.0})
    with pytest.raises(Exception, match="only the selected"):
        apply_commands(
            base,
            (
                command.model_copy(
                    update={"payload": command.payload.model_copy(update={"track": bad})}
                ),
            ),
        )


class SimpleOutput(DomainModel):
    result: str


@pytest.mark.asyncio
async def test_json_client_keeps_reported_model_instead_of_guessing_alias():
    async def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-flash" and body["thinking"] == {"type": "disabled"}
        return httpx.Response(
            200,
            json={
                "id": "test",
                "model": "deepseek-v4.1-flash-1017",
                "choices": [{"finish_reason": "stop", "message": {"content": '{"result":"ok"}'}}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        c = DeepSeekJsonClient(
            api_key="test-only-not-a-credential", http_client=http, max_attempts=1
        )
        result = await c.complete_json(
            messages=[HumanMessage(content="JSON only")],
            output_model=SimpleOutput,
            thinking="disabled",
            max_tokens=256,
        )
    assert result.model == "deepseek-v4.1-flash-1017"
