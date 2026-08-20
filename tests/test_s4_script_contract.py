from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

import pytest


@pytest.mark.asyncio
async def test_s4_smoke_reuses_the_public_no_cost_acceptance_for_all_four_styles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]))
    from scripts import run_s2_deterministic_smoke as s2
    from scripts import run_s4_deterministic_smoke as s4

    observed: list[tuple[str, int, int]] = []
    original = dict(s2.BRIEF)

    async def observe() -> None:
        observed.append(
            (
                str(s2.BRIEF["style"]),
                int(s2.BRIEF["duration_seconds"]),
                int(s2.BRIEF["target_bpm"]),
            )
        )

    monkeypatch.setattr(s2, "main", observe)
    await s4.main()

    assert observed == [(style, 60, 120) for style in s4.STYLES]
    assert original == s2.BRIEF


def test_render_worker_uses_the_media_worker_identity_for_shared_temp_files() -> None:
    dockerfile = (
        Path(__file__).parents[1] / "services" / "render-worker" / "Dockerfile"
    ).read_text(encoding="utf-8")

    assert "groupadd --gid 10001 motif-forge" in dockerfile
    assert "useradd --uid 10001 --gid 10001" in dockerfile
    assert "USER 10001:10001" in dockerfile


def test_physical_artifacts_can_be_verified_inside_the_runtime_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from scripts import run_s2_deterministic_smoke as s2

    calls: list[list[str]] = []

    def execute(command: list[str], **_: object) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(command, 0, stdout=f"{'a' * 64}  /artifacts/{command[-1]}\n")

    monkeypatch.setattr(s2.subprocess, "run", execute)

    digest = s2._physical_digest(
        Path("/host-not-shared"),
        "protected/exports/project/revision/audio/master.wav",
        "motif-forge-s4-media-worker-1",
    )

    assert digest == "a" * 64
    assert calls == [
        [
            "docker",
            "exec",
            "motif-forge-s4-media-worker-1",
            "sha256sum",
            "/artifacts/protected/exports/project/revision/audio/master.wav",
        ]
    ]
    with pytest.raises(RuntimeError, match="storage key"):
        s2._physical_digest(
            Path("/unused"),
            "../outside.wav",
            "motif-forge-s4-media-worker-1",
        )
