"""Public release contract and local migration declarations; no Docker or DB."""

import json

import pytest

from scripts.personal_beta_release import ReleasePinError, load_release, main


@pytest.fixture
def release_repo(tmp_path):
    from pathlib import Path

    original = Path(__file__).parents[1]
    (tmp_path / "scripts").mkdir()
    contract = json.loads((original / "scripts/personal-beta-release.v1.json").read_text())
    (tmp_path / "scripts/personal-beta-release.v1.json").write_text(json.dumps(contract))
    versions = tmp_path / "infra/migrations/versions"
    versions.mkdir(parents=True)
    (versions / "head.py").write_text('revision: str = "20261020_0030"\ndown_revision = None\n')
    return tmp_path, contract


def test_release_identifies_image_and_local_schema_without_git_head_gate(release_repo, capsys):
    repo, contract = release_repo
    assert load_release(repo) == contract
    assert main(["--repo", str(repo)]) == 0
    assert capsys.readouterr().out.split() == [contract["api_image"]["reference"],
                                            contract["api_image"]["id"], "20261020_0030"]


@pytest.mark.parametrize("fault", ["wrong_head", "multiple_heads", "missing_parent", "symlink",
                                  "disconnected_cycle"])
def test_unsupported_local_migration_graph_is_rejected(release_repo, fault):
    repo, _ = release_repo
    versions = repo / "infra/migrations/versions"
    if fault == "wrong_head":
        (versions / "head.py").write_text('revision="0031"\ndown_revision=None\n')
    elif fault == "multiple_heads":
        (versions / "second.py").write_text('revision="second"\ndown_revision=None\n')
    elif fault == "missing_parent":
        (versions / "head.py").write_text('revision="20261020_0030"\ndown_revision="absent"\n')
    elif fault == "symlink":
        (versions / "head.py").rename(versions / "real.txt")
        (versions / "head.py").symlink_to(versions / "real.txt")
    else:
        (versions / "a.py").write_text('revision="a"\ndown_revision="b"\n')
        (versions / "b.py").write_text('revision="b"\ndown_revision="a"\n')
    with pytest.raises(ReleasePinError):
        load_release(repo)


@pytest.mark.parametrize("fault", ["image_id", "image_reference", "manifest_schema"])
def test_invalid_manifest_never_returns_a_fallback_selection(release_repo, fault, capsys):
    repo, contract = release_repo
    if fault == "image_id":
        contract["api_image"]["id"] = "tag-not-identity"
    elif fault == "image_reference":
        contract["api_image"]["reference"] = "some-image; run something"
    else:
        contract["schema_version"] = "unknown"
    (repo / "scripts/personal-beta-release.v1.json").write_text(json.dumps(contract))
    assert main(["--repo", str(repo)]) == 78
    output = capsys.readouterr()
    assert output.out == "" and str(repo) not in output.err


def test_actual_migration_graph_matches_declared_0030_release():
    from pathlib import Path

    value = load_release(Path(__file__).parents[1])
    assert value["compatible_database_revision"] == "20261020_0030"
