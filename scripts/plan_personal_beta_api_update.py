"""Print the no-Key 14ce937 API/Web update proposal; never apply or run it."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

try:
    from scripts.personal_beta_release import ReleasePinError, _source_text, load_release
except ModuleNotFoundError:  # Direct script invocation.
    from personal_beta_release import ReleasePinError, _source_text, load_release

SOURCE = "14ce93714123edeb61a6e71a413882e68dd08385"
OLD_APPLICATION = "a3bfb1abc91a6fca820ff5a2367ef449879632aa"
OLD_ID = "sha256:b133641886492ffeb3a73c3905beda303ad19d07319cb905ca0969841b6aa3d4"
NEW_REFERENCE = "motif-forge-beta-api:settings-14ce937"
EXPECTED_FILES = {
    "motif_forge/api/app.py": ("e050fdec682537042ed9a883534b3ee5488584fb46334afc4e28e6a640c83a51"),
    "motif_forge/api/model_settings.py": (
        "b84852cd80a949e9acbcf331080daa4a9aea32249e58af00761769b6e53b6ebe"
    ),
}
PROTECTED_SOURCE = [
    "services/api/src",
    "infra/migrations",
    "services/render-worker",
    "packages/audio-engine",
    "pyproject.toml",
    "uv.lock",
    "services/api/Dockerfile",
]


class UpdatePlanError(ValueError):
    pass


def plan_update(repo: Path, evidence: dict) -> dict:
    """Validate reported identity against the frozen source, not against live Docker.

    The report is not independently authenticated here. A plan always retains the
    actual image, activity, ownership and health gates before any maintenance.
    """
    try:
        old = load_release(repo)
        if (
            old["application_commit"] != OLD_APPLICATION
            or old["api_image"]
            != {"reference": "motif-forge-beta-api:inspector-a3bfb1a", "id": OLD_ID}
            or old["compatible_database_revision"] != "20261020_0030"
        ):
            raise ValueError
        prefix = ["git", "-C", str(repo)]
        subprocess.run(
            [*prefix, "diff", "--quiet", SOURCE, "--", *PROTECTED_SOURCE],
            capture_output=True,
            check=True,
            timeout=10,
        )
        extra = subprocess.run(
            [*prefix, "ls-files", "--others", "--", *PROTECTED_SOURCE],
            capture_output=True,
            check=True,
            timeout=10,
        )
        if extra.stdout:
            raise ValueError
        if (
            set(evidence) != {"source_commit", "reference", "id", "files"}
            or evidence["source_commit"] != SOURCE
            or evidence["reference"] != NEW_REFERENCE
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", evidence["id"])
            or evidence["id"] == OLD_ID
            or evidence["files"] != EXPECTED_FILES
        ):
            raise ValueError
        future_pin = {
            "schema_version": "motif-personal-beta-release.v1",
            "application_commit": SOURCE,
            "api_image": {"reference": NEW_REFERENCE, "id": evidence["id"]},
            "compatible_database_revision": "20261020_0030",
        }
        return {
            "status": "NOT_READY_OFFLINE_PROPOSAL",
            "source_commit": SOURCE,
            "compatible_database_revision": "20261020_0030",
            "future_release_pin": future_pin,
            "api_override": {"services": {"api": {"image": evidence["id"]}}},
            "rollback_override": {"services": {"api": {"image": OLD_ID}}},
            "compose_suffix": ["up", "-d", "--no-deps", "--no-build", "--pull", "never", "api"],
            "never_start": ["migrate", "storage-init"],
            "retain_services": [
                "postgres",
                "redis",
                "dispatcher",
                "resume-dispatcher",
                "media-worker",
                "render-worker",
            ],
            "web_source": {"old": "81b1cffc8bf8d20686a80bac6d6ae1cf242df9c4", "new": SOURCE},
            "pending_live_gates": [
                "actual_new_image_identity",
                "complete_activity_check",
                "current_runtime_ownership",
                "live_schema0030",
                "same_data_and_resource_mounts",
                "health_and_versioned_read",
                "exact_old_image_and_web_rollback",
            ],
        }
    except (ReleasePinError, ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError):
        raise UpdatePlanError("BETA_UPDATE_SOURCE_BASELINE_OR_IDENTITY_INVALID") from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--image-evidence", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        evidence = json.loads(_source_text(args.image_evidence, 8192))
        result = plan_update(args.repo, evidence)
    except (UpdatePlanError, OSError, ValueError, UnicodeError):
        print("BETA_UPDATE_SOURCE_BASELINE_OR_IDENTITY_INVALID", file=sys.stderr)
        return 78
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
