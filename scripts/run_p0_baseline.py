"""Create isolated, synthetic legacy evidence without loading runtime settings or a DB."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import UUID

from motif_forge.application.generation import EXPORT_STEPS
from motif_forge.application.rendering import build_canonical_render_payload, compile_audio_graph
from motif_forge.domain.canonical import arrangement_content_hash, canonical_json_bytes
from motif_forge.domain.composition import build_s1_composition
from motif_forge.domain.ir import ArrangementIR, Articulation
from motif_forge.domain.revisions import create_root_state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--legacy-export-dir", type=Path)
    parser.add_argument("--artifact-root", type=Path)
    args = parser.parse_args()
    output = args.output_root.resolve()
    output.mkdir(parents=True, exist_ok=False)
    project_id = UUID("10000000-0000-4000-8000-000000000042")
    legacy = build_s1_composition(project_id, seed=42).arrangement
    legacy_bytes = canonical_json_bytes(legacy)
    reopened = ArrangementIR.model_validate_json(legacy.model_dump_json())
    projection = compile_audio_graph(reopened)
    canonical_reopened = ArrangementIR.model_validate_json(legacy_bytes)
    canonical_projection = compile_audio_graph(canonical_reopened)
    assert canonical_json_bytes(reopened) == legacy_bytes
    assert compile_audio_graph(legacy).graph == projection.graph
    assert projection.graph["durationSeconds"] == 72.0
    root = create_root_state(project_id, created_by="p0:synthetic-baseline")
    revision = root.revision.model_copy(
        update={"arrangement_ir": legacy, "content_hash": arrangement_content_hash(legacy)}
    )
    payload = build_canonical_render_payload(revision, seed=42)

    track = legacy.tracks[0]
    clip = track.clips[0]
    note = clip.notes[0]
    changed_note = note.model_copy(update={"articulation": Articulation.STACCATO, "cents": 25.0})
    changed_clip = clip.model_copy(update={"notes": (changed_note, *clip.notes[1:])})
    changed_track = track.model_copy(update={"clips": (changed_clip, *track.clips[1:])})
    changed = legacy.model_copy(update={"tracks": (changed_track, *legacy.tracks[1:])})
    # This records a CURRENT defect; it is not a desired behavior assertion for P1.
    expression_ignored = compile_audio_graph(changed).graph == projection.graph
    mappings = {}
    for instrument in [
        "builtin:jazz-piano",
        "builtin:violin",
        "builtin:pizz-cello",
        "builtin:brush-kit",
    ]:
        candidate = legacy.model_copy(
            update={"tracks": (track.model_copy(update={"instrument_ref": instrument}),)}
        )
        rendered = compile_audio_graph(candidate).graph["tracks"][0]
        mappings[instrument] = {
            k: rendered[k] for k in ["kind", "presetId", "sampleId"] if k in rendered
        }

    (output / "legacy-arrangement.v1.json").write_text(legacy.model_dump_json(indent=2) + "\n")
    (output / "legacy-canonical.v1.json").write_bytes(legacy_bytes)
    (output / "legacy-audio-graph.v1.json").write_text(
        json.dumps(projection.graph, indent=2) + "\n"
    )
    (output / "legacy-canonical-audio-graph.v1.json").write_text(
        json.dumps(canonical_projection.graph, indent=2) + "\n"
    )
    canonical_events_equal = all(
        sorted(json.dumps(x, sort_keys=True) for x in left.get("notes", left.get("triggers", [])))
        == sorted(
            json.dumps(x, sort_keys=True) for x in right.get("notes", right.get("triggers", []))
        )
        for left, right in zip(
            projection.graph["tracks"], canonical_projection.graph["tracks"], strict=True
        )
    )
    assert canonical_events_equal
    report = {
        "schema_version": "p0-symbolic-baseline.v1",
        "fixture_kind": "synthetic-S1-legacy-v1-not-user-project",
        "provider_requests": 0,
        "provider_tokens": 0,
        "legacy_roundtrip_identical": True,
        "canonical_roundtrip_event_multisets_identical": canonical_events_equal,
        "canonical_roundtrip_graph_identical": projection.graph == canonical_projection.graph,
        "legacy_arrangement_hash": arrangement_content_hash(legacy),
        "legacy_graph_hash": projection.graph_hash,
        "canonical_reopened_graph_hash": canonical_projection.graph_hash,
        "duration_seconds": projection.graph["durationSeconds"],
        "track_count": len(legacy.tracks),
        "known_defects_not_acceptance": {
            "articulation_and_cents_change_leaves_graph_identical": expression_ignored,
            "instrument_mappings": mappings,
            "canonical_maximum_output_bytes": payload.maximum_output_bytes,
            "five_minute_pcm24_bytes_with_header": 300 * 48000 * 2 * 3 + 44,
            "five_minute_fits_current_limit": payload.maximum_output_bytes
            >= 300 * 48000 * 2 * 3 + 44,
            "export_cursor_steps": list(EXPORT_STEPS),
        },
    }
    if args.legacy_export_dir is not None:
        if args.artifact_root is None:
            parser.error("--legacy-export-dir requires --artifact-root")
        artifact_root = args.artifact_root.resolve(strict=True)
        export_dir = args.legacy_export_dir.resolve(strict=True)
        export_dir.relative_to(artifact_root)
        project_path = export_dir / "project.json"
        project_bytes = project_path.read_bytes()
        historical = ArrangementIR.model_validate_json(project_bytes)
        manifest = json.loads((export_dir / "export-manifest.json").read_text())
        checked = []
        for item in manifest["files"]:
            filename = item["filename"]
            if Path(filename).name != filename:
                raise ValueError("P0_EXPORT_FILENAME_INVALID")
            source = (
                artifact_root / item["storage_key"]
                if "storage_key" in item
                else export_dir / filename
            ).resolve(strict=True)
            source.relative_to(artifact_root)
            digest = hashlib.sha256()
            with source.open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != item["sha256"] or source.stat().st_size != item["bytes"]:
                raise ValueError("P0_HISTORICAL_EXPORT_INTEGRITY_FAILED")
            checked.append({"filename": filename, "bytes": item["bytes"], "sha256": item["sha256"]})
        assert project_path.read_bytes() == project_bytes
        historical_graph = compile_audio_graph(historical)
        (output / "historical-audio-graph.v1.json").write_text(
            json.dumps(historical_graph.graph, indent=2) + "\n"
        )
        report["historical_export"] = {
            "project_id": str(historical.project_id),
            "revision_id": manifest["revision_id"],
            "schema_version": historical.schema_version,
            "source_project_sha256": hashlib.sha256(project_bytes).hexdigest(),
            "source_project_unchanged": True,
            "duration_seconds": historical_graph.graph["durationSeconds"],
            "graph_hash": historical_graph.graph_hash,
            "files_verified": checked,
            "database_and_ui_reopened": False,
        }
    (output / "symbolic-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
