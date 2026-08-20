from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "run_s3_browser_smoke.mjs"


def test_s3_smoke_is_browser_driven_and_attests_no_paid_runtime_first() -> None:
    source = SCRIPT.read_text()

    assert 'from "playwright"' in source
    assert "assertNoPaidRuntime" in source
    assert 'test -z "$DEEPSEEK_API_KEY"' in source
    assert source.index("await assertNoPaidRuntime()") < source.index("chromium.launch")
    assert 'WEB_URL === "http://127.0.0.1:5173"' in source
    assert 'API_URL === "http://127.0.0.1:8000"' in source
    assert '"--strictPort"' in source
    for visible_control in (
        "创建作品",
        "提交 Brief 并规划",
        "批准并生成",
        "创建调整后的 Plan",
        "开始顺序导入",
        "播放",
    ):
        assert visible_control in source
    for forbidden in (
        "motif_forge.agent",
        "execute_media_job",
        "resume_dispatcher",
        "CreateAIRun",
    ):
        assert forbidden not in source


def test_s3_smoke_covers_refresh_replan_mobile_and_same_project_imports() -> None:
    source = SCRIPT.read_text()

    assert "page.reload" in source
    assert "390" in source
    assert "scrollWidth" in source
    assert "old_plan_readable" in source
    assert "child_run_id" in source
    assert "head_before_imports" in source
    assert "head_after_first_import" in source
    assert "head_after_second_import" in source
    assert "provider_requests" in source
    assert "provider_tokens" in source
    assert "job_count" in source
    assert "audio_artifact_count" in source
    assert "bundle_count" in source
    assert "source_lineage_distinct_count" in source
    assert "distinct.length === 2" in source
    assert "import_revision_count" in source
    assert "import_run_count" in source
    assert "只读时间线" in source
    assert "track_count" in source
    assert "JSON.stringify(summary)" in source
    assert "process.env" not in source[source.index("const summary ="):]


def test_s3_stage_gate_exposes_browser_smoke() -> None:
    package = (ROOT / "package.json").read_text()
    gate = (ROOT / "scripts" / "check_s1.sh").read_text()

    assert '"smoke:s3": "node scripts/run_s3_browser_smoke.mjs"' in package
    assert "test_s3_browser_smoke_contract.py" in gate
    assert "npm run smoke:s3" in gate
