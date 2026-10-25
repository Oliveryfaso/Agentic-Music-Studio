"""Read the reviewed public API release and validate its local migration head.

No Docker, database, credentials or migration module execution occurs here.
The database revision is a compatibility declaration, not a live DB check.
"""

from __future__ import annotations

import argparse
import ast
import graphlib
import json
import os
import re
import stat
import sys
from pathlib import Path


class ReleasePinError(ValueError):
    pass


def _source_text(path: Path, limit: int) -> str:
    with os.fdopen(
        os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), encoding="utf-8"
    ) as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise ValueError
        text = source.read(limit + 1)
        if len(text) > limit:
            raise ValueError
        return text


def load_release(repo: Path) -> dict:
    try:
        manifest = repo / "scripts/personal-beta-release.v1.json"
        release = json.loads(_source_text(manifest, 8192))
        if (
            release["schema_version"] != "motif-personal-beta-release.v1"
            or not re.fullmatch(r"[0-9a-f]{40}", release["application_commit"])
            or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._/:@-]+",
                                release["api_image"]["reference"])
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", release["api_image"]["id"])
            or not re.fullmatch(r"[a-z0-9_]+", release["compatible_database_revision"])
        ):
            raise ValueError
        revisions, parents, graph = set(), set(), {}
        files = [p for p in (repo / "infra/migrations/versions").glob("*.py")
                 if not p.name.startswith("._") and p.name != "__init__.py"]
        if not 0 < len(files) <= 128:
            raise ValueError
        for source in files:
            values = {}
            for node in ast.parse(_source_text(source, 1024**2)).body:
                targets = node.targets if isinstance(node, ast.Assign) else (
                    [node.target] if isinstance(node, ast.AnnAssign) else []
                )
                for target in targets:
                    if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                        if target.id in values:
                            raise ValueError
                        values[target.id] = ast.literal_eval(node.value)
            revision = values["revision"]
            if not isinstance(revision, str) or revision in revisions:
                raise ValueError
            revisions.add(revision)
            parent = values["down_revision"]
            graph[revision] = ()
            if parent is not None:
                links = (parent,) if isinstance(parent, str) else parent
                if not isinstance(links, (tuple, list)) or not all(
                    isinstance(x, str) for x in links
                ):
                    raise ValueError
                graph[revision] = links
                parents.update(links)
        tuple(graphlib.TopologicalSorter(graph).static_order())
        if parents - revisions or revisions - parents != {release["compatible_database_revision"]}:
            raise ValueError
        return release
    except (OSError, ValueError, KeyError, TypeError, SyntaxError, RuntimeError):
        raise ReleasePinError("BETA_RELEASE_CONTRACT_OR_LOCAL_SCHEMA_INVALID") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        release = load_release(args.repo)
    except ReleasePinError as exc:
        print(str(exc), file=sys.stderr)
        return 78
    print(release["api_image"]["reference"], release["api_image"]["id"],
          release["compatible_database_revision"], sep="\t")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
