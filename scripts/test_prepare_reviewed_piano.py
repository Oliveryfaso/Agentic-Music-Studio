import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import prepare_reviewed_piano as p


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.archive = self.root / "input.7z"
        self.archive.write_bytes(b"synthetic archive")
        self.dest = self.root / "output"
        self.here = self.root / "scripts"
        (self.here / "resources").mkdir(parents=True)
        self.payloads = {
            "samples/a.wav": b"fake PCM",
            "cc0.txt": b"license",
            "readme.txt": b"notice",
        }

        def sha(value):
            return hashlib.sha256(value).hexdigest()

        m = {
            "packId": "fixture",
            "packVersion": "1",
            "license": {"spdx": "CC0-1.0", "textSha256": sha(b"license")},
            "samples": [{"path": "samples/a.wav", "byteSize": 8, "sha256": sha(b"fake PCM")}],
        }
        raw = json.dumps(m).encode()
        (self.here / "resources/kw-small.instrument-pack.json").write_bytes(raw)
        c = {
            "scores": [],
            "piano": {
                "pack_id": "fixture",
                "pack_version": "1",
                "manifest_sha256": sha(raw),
                "license_sha256": sha(b"license"),
                "source_archive_sha256": sha(self.archive.read_bytes()),
                "sample_count": 1,
                "notice_files": [{"path": "readme.txt", "sha256": sha(b"notice")}],
            },
        }
        (self.here / "resource-contract.v1.json").write_text(json.dumps(c))
        (self.root / "services/api/src/motif_forge/resources/scores").mkdir(parents=True)
        self.addCleanup(patch.stopall)
        patch.object(p, "HERE", self.here).start()
        self.reader = patch.object(
            p, "extract", side_effect=lambda a, n, b: self.payloads[n.removeprefix(p.PREFIX)]
        ).start()

    def test_plan_reads_no_archive(self):
        self.archive.unlink()
        self.assertEqual(p.prepare(self.archive, self.dest)["status"], "PLAN_ONLY")
        self.reader.assert_not_called()

    def test_prepare_and_duplicate(self):
        self.assertEqual(p.prepare(self.archive, self.dest, execute=True)["status"], "PREPARED")
        with self.assertRaisesRegex(ValueError, "DESTINATION_EXISTS"):
            p.prepare(self.archive, self.dest, execute=True)

    def test_wrong_archive(self):
        self.archive.write_bytes(b"wrong version")
        with self.assertRaisesRegex(ValueError, "ARCHIVE_PIN_MISMATCH"):
            p.prepare(self.archive, self.dest, execute=True)
        self.assertFalse(self.dest.exists())

    def test_missing_sample(self):
        self.reader.side_effect = ValueError("EXTRACTION_FAILED_OR_UNSUPPORTED")
        with self.assertRaises(ValueError):
            p.prepare(self.archive, self.dest, execute=True)
        self.assertFalse(self.dest.exists())

    def test_corrupt_sample(self):
        self.payloads["samples/a.wav"] = b"wrong"
        with self.assertRaisesRegex(ValueError, "MEMBER_HASH_MISMATCH"):
            p.prepare(self.archive, self.dest, execute=True)
        self.assertFalse(self.dest.exists())

    def test_path_traversal(self):
        for name in ["../x", "/x", "samples/../x", "a\\x", "a//x"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                p.checked_path(name)

    def test_target_symlink(self):
        self.dest.symlink_to(self.root / "absent")
        with self.assertRaisesRegex(ValueError, "DESTINATION_EXISTS"):
            p.prepare(self.archive, self.dest, execute=True)

    def test_archive_symlink(self):
        link = self.root / "link"
        link.symlink_to(self.archive)
        with self.assertRaisesRegex(ValueError, "ARCHIVE_PATH_UNSAFE"):
            p.prepare(link, self.dest, execute=True)


class ReviewRegressionTests(unittest.TestCase):
    def test_expired_deadline_never_spawns(self):
        with (
            patch.object(p, "DEADLINE", 10),
            patch.object(p.time, "monotonic", return_value=11),
            patch.object(p.shutil, "which", return_value="/trusted/decoder"),
            patch.object(p.subprocess, "run") as run,
        ):
            with self.assertRaisesRegex(ValueError, "DECODE_DEADLINE_EXCEEDED"):
                p.extract(Path("fixture"), "member", 10)
            run.assert_not_called()

    def test_late_return_rejected(self):
        from types import SimpleNamespace

        def reply(*args, **kwargs):
            kwargs["stdout"].write(b"ok")
            return SimpleNamespace(returncode=0)

        with (
            patch.object(p, "DEADLINE", 10),
            patch.object(p.time, "monotonic", side_effect=[9, 11]),
            patch.object(p.shutil, "which", return_value="/trusted/decoder"),
            patch.object(p.subprocess, "run", side_effect=reply),
            self.assertRaisesRegex(ValueError, "DECODE_DEADLINE_EXCEEDED"),
        ):
            p.extract(Path("fixture"), "member", 10)

    def test_cli_private_path_errors(self):
        import subprocess
        import sys

        script = Path(p.__file__).resolve()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            loop = root / "PRIVATE-loop"
            loop.symlink_to(loop)
            cases = [
                ["--seven-zip", str(root / "PRIVATE-missing")],
                ["--seven-zip", str(loop)],
                ["--destination", str(loop / "output")],
                ["--archive", str(loop), "--execute"],
            ]
            for extra in cases:
                with self.subTest(extra=extra):
                    result = subprocess.run(
                        [
                            sys.executable,
                            str(script),
                            "--archive",
                            str(root / "unused"),
                            "--destination",
                            str(root / "new"),
                            *extra,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stderr, "")
                    self.assertEqual(json.loads(result.stdout)["status"], "BLOCKED")
                    self.assertNotIn(str(root), result.stdout)


if __name__ == "__main__":
    unittest.main()
