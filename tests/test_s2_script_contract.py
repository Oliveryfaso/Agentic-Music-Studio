from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "run_s2_deterministic_smoke.py"


def test_s2_smoke_requires_human_approval_and_uses_public_http_actions() -> None:
    source = SCRIPT.read_text()

    assert "MOTIF_FORGE_S2_APPROVAL_ACTOR" in source
    assert "MOTIF_FORGE_S2_APPROVAL_ASSERTION" in source
    assert "/api/v1/projects" in source
    assert "/ai-runs" in source
    assert "/resume" in source
    assert "pending_plan_hash" in source
    assert "pending_action" in source
    assert "execute_media_job" not in source
    assert "_assert_no_paid_runtime()" in source
    first_project_post = source.index('"POST",\n                "/api/v1/projects"')
    assert source.index("_assert_no_paid_runtime()") < first_project_post
    assert 'test -z "$DEEPSEEK_API_KEY"' in source
    assert "stdout=subprocess.DEVNULL" in source
    assert "stderr=subprocess.DEVNULL" in source
    assert '"no_paid_model_usage": no_paid_model_usage' in source
    assert '"no_paid_model_usage": True' not in source


def test_s2_smoke_verifies_authoritative_lineage_and_physical_checksums() -> None:
    source = SCRIPT.read_text()

    for contract in (
        "app.composition_plans",
        "app.project_revisions",
        "app.jobs",
        "app.artifacts",
        "app.export_bundle_artifacts",
        "source_job_id",
        "app.runs",
        "ai_model_request_reservations",
        "sha256",
        "canonical-master.v1",
        "canonical-stem.v1",
        "delivery-mp3.v1",
        "cost_status",
    ):
        assert contract in source


def test_s1_stage_gate_includes_s2_host_eval_and_smoke() -> None:
    source = (ROOT / "scripts" / "check_s1.sh").read_text()

    assert "test_s2_generate_eval.py" in source
    assert "test_s2_script_contract.py" in source
    assert "run_s2_deterministic_smoke.py" in source
