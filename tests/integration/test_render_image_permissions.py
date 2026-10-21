"""Opt-in check of the actual image's declared non-root runtime user."""

from __future__ import annotations

import json
import os
import subprocess
from uuid import uuid4

import pytest


def test_render_image_runtime_files_are_readable_as_declared_user():
    image = os.environ.get("MOTIF_FORGE_TEST_RENDER_IMAGE")
    if not image:
        pytest.skip(
            "Set MOTIF_FORGE_TEST_RENDER_IMAGE to an explicitly built test image"
        )
    inspected = subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Config.User}}", image],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert inspected.returncode == 0, inspected.stderr
    assert inspected.stdout.strip() == "10001:10001"
    code = (
        "const fs=require('fs');"
        "JSON.parse(fs.readFileSync('/app/package.json','utf8'));"
        "for(const f of ['page-entry.js','service.js','spike.js'])"
        "fs.readFileSync('/app/services/render-worker/dist/'+f);"
        "console.log(JSON.stringify({uid:process.getuid(),readable:true}));"
    )
    checked = subprocess.run(
        [
            "docker",
            "run",
            "--name",
            "motif-render-permission-" + uuid4().hex[:12],
            "--rm",
            "--network",
            "none",
            "--pull",
            "never",
            image,
            "node",
            "-e",
            code,
        ],
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == {"uid": 10001, "readable": True}
