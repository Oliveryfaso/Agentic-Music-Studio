"""Explicit local-only preparation. No download, install, overwrite or VM changes."""

import argparse
import hashlib
import json
import os
import resource
import shutil
import subprocess
import tempfile
import time
from pathlib import Path, PurePosixPath

from resource_preflight import audit_resources

HERE = Path(__file__).resolve().parent
PREFIX = "UprightPianoKW-small-SFZ-20190703/"


def checked_path(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or "\\" in name or str(p) != name:
        raise ValueError("UNSAFE_MEMBER")
    return p


SEVEN_ZIP = None
DEADLINE = None


def extract(archive, member, maximum):
    tool = SEVEN_ZIP or shutil.which("bsdtar")
    if not tool:
        raise ValueError("EXTRACTOR_UNAVAILABLE")

    def limit():
        resource.setrlimit(resource.RLIMIT_FSIZE, (maximum + 1, maximum + 1))

    with tempfile.TemporaryFile() as out:
        argv = (
            [tool, "x", "-so", "-bd", "-y", "-spd", str(archive), member]
            if SEVEN_ZIP
            else [tool, "-xqOf", str(archive), member]
        )
        remaining = DEADLINE - time.monotonic() if DEADLINE is not None else 60
        if remaining <= 0:
            raise ValueError("DECODE_DEADLINE_EXCEEDED")
        result = subprocess.run(
            argv,
            stdout=out,
            stderr=subprocess.DEVNULL,
            timeout=min(60, remaining),
            preexec_fn=limit,
        )
        if DEADLINE is not None and time.monotonic() >= DEADLINE:
            raise ValueError("DECODE_DEADLINE_EXCEEDED")
        if result.returncode:
            raise ValueError("EXTRACTION_FAILED_OR_UNSUPPORTED")
        out.seek(0)
        data = out.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("MEMBER_TOO_LARGE")
    return data


def prepare(archive, destination, *, execute=False):
    global DEADLINE
    DEADLINE = time.monotonic() + 120
    contract = json.loads((HERE / "resource-contract.v1.json").read_text())
    piano = contract["piano"]
    template = (HERE / "resources/kw-small.instrument-pack.json").read_bytes()
    if hashlib.sha256(template).hexdigest() != piano["manifest_sha256"]:
        raise ValueError("TEMPLATE_PIN_MISMATCH")
    manifest = json.loads(template)
    rows = [(s["path"], s["sha256"], s["byteSize"]) for s in manifest["samples"]]
    rows += [("cc0.txt", piano["license_sha256"], 32768)]
    rows += [(n["path"], n["sha256"], 32768) for n in piano["notice_files"]]
    for name, _, _ in rows:
        checked_path(name)
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("DESTINATION_EXISTS")
    if destination.parent.resolve(strict=True) != destination.parent:
        raise ValueError("DESTINATION_PARENT_UNSAFE")
    if not execute:
        return {"status": "PLAN_ONLY", "files": len(rows) + 1}
    archive = Path(archive).absolute()
    if archive.resolve(strict=True) != archive:
        raise ValueError("ARCHIVE_PATH_UNSAFE")
    # Snapshot through a no-follow descriptor; the decoder only sees checked bytes.
    with tempfile.TemporaryDirectory(prefix="motif-piano-") as scratch:
        frozen = Path(scratch) / "source.7z"
        with os.fdopen(os.open(archive, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as inp:
            import stat

            if not stat.S_ISREG(os.fstat(inp.fileno()).st_mode):
                raise ValueError("ARCHIVE_NOT_REGULAR")
            data = inp.read(5 * 1024**2 + 1)
        if (
            len(data) > 5 * 1024**2
            or hashlib.sha256(data).hexdigest() != piano["source_archive_sha256"]
        ):
            raise ValueError("ARCHIVE_PIN_MISMATCH")
        frozen.write_bytes(data)
        staged = Path(scratch) / "pack"
        staged.mkdir()
        for name, digest, maximum in rows:
            payload = extract(frozen, PREFIX + name, maximum)
            if hashlib.sha256(payload).hexdigest() != digest:
                raise ValueError("MEMBER_HASH_MISMATCH")
            target = staged.joinpath(*checked_path(name).parts)
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(payload)
        (staged / "instrument-pack.json").write_bytes(template)
        report = audit_resources(
            contract,
            str(staged),
            str(HERE.parent / "services/api/src/motif_forge/resources/scores"),
        )
        if report["piano"]["status"] != "verified":
            raise ValueError("PREFLIGHT_FAILED")
        # Fresh-only publication; partial copies are never accepted as complete.
        destination.mkdir(mode=0o700)
        for name, _, _ in rows:
            target = destination.joinpath(*checked_path(name).parts)
            target.parent.mkdir(exist_ok=True)
            with target.open("xb") as out:
                out.write((staged / name).read_bytes())
        with (destination / "instrument-pack.json").open("xb") as out:
            out.write(template)
        report = audit_resources(
            contract,
            str(destination),
            str(HERE.parent / "services/api/src/motif_forge/resources/scores"),
        )
        if report["piano"]["status"] != "verified":
            raise ValueError("DESTINATION_PREFLIGHT_FAILED")
        return {"status": "PREPARED", "samples": piano["sample_count"]}


def main():
    global SEVEN_ZIP
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--seven-zip", type=Path, help="Explicit existing trusted 7zz; never installed"
    )
    args = parser.parse_args()
    try:
        SEVEN_ZIP = str(args.seven_zip.resolve(strict=True)) if args.seven_zip else None
        print(json.dumps(prepare(args.archive, args.destination, execute=args.execute)))
    except (ValueError, OSError, RuntimeError, subprocess.SubprocessError):
        # No raw paths or extractor output in user-facing diagnostics.
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": (
                        "PREPARATION_FAILED; check fixed archive, "
                        "extractor support and fresh target"
                    ),
                }
            )
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
