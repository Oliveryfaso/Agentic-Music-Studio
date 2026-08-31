"""Export the deterministic Motif Forge OpenAPI document for TypeScript generation."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = ROOT / ".venv/bin/python"
if sys.prefix == sys.base_prefix and VENV_PYTHON.exists():
    raise SystemExit(
        subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve())], env=os.environ)
    )

sys.path.insert(0, str(ROOT / "services/api/src"))

from motif_forge.api.app import create_app  # noqa: E402
from motif_forge.config import Settings  # noqa: E402


class UnconfiguredAIRunUOW:
    def __call__(self) -> object:
        raise RuntimeError("OpenAPI export does not execute persistence")


class UnconfiguredProjectReadStore:
    async def list_projects(self, *, limit: int) -> tuple[object, ...]:
        raise RuntimeError("OpenAPI export does not execute persistence")


class UnconfiguredExportReadStore:
    async def read_revision_export(
        self, *, project_id: object, revision_id: object
    ) -> None:
        raise RuntimeError("OpenAPI export does not execute persistence")


class UnconfiguredRunInspectionStore:
    async def read_run_inspection(self, run_id: object) -> None:
        raise RuntimeError("OpenAPI export does not execute persistence")


    async def read_bundle(self, bundle_id: object) -> None:
        raise RuntimeError("OpenAPI export does not execute persistence")

    async def read_project(self, project_id: object) -> None:
        raise RuntimeError("OpenAPI export does not execute persistence")

    async def read_revision_studio(
        self, *, project_id: object, revision_id: object
    ) -> None:
        raise RuntimeError("OpenAPI export does not execute persistence")


class UnconfiguredRunGraphHistoryStore:
    async def read_run_graph_history(self, thread_id: str) -> None:
        raise RuntimeError("OpenAPI export does not execute persistence")


def main() -> None:
    app = create_app(
        Settings(),
        ai_run_uow_factory=UnconfiguredAIRunUOW(),  # type: ignore[arg-type]
        project_read_store=UnconfiguredProjectReadStore(),  # type: ignore[arg-type]
        export_read_store=UnconfiguredExportReadStore(),  # type: ignore[arg-type]
        run_inspection_store=UnconfiguredRunInspectionStore(),  # type: ignore[arg-type]
        run_graph_history_store=UnconfiguredRunGraphHistoryStore(),  # type: ignore[arg-type]
    )
    Path("/private/tmp/motif-forge-openapi.json").write_text(
        json.dumps(app.openapi(), sort_keys=True, separators=(",", ":")), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
