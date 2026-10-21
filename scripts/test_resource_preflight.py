import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from resource_preflight import audit_resources


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    data = json.dumps(value, sort_keys=True).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha(data)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="motif-resource-fixture-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.piano, self.scores = self.root / "piano", self.root / "scores"
        (self.piano / "samples").mkdir(parents=True)
        self.scores.mkdir()
        # Owned integrity bytes only; production loader remains responsible for PCM.
        sample, license_text = b"owned integrity fixture", b"owned test text"
        (self.piano / "samples/own.wav").write_bytes(sample)
        (self.piano / "cc0.txt").write_bytes(license_text)
        manifest = {
            "packId": "fixture:own",
            "packVersion": "test1",
            "license": {"spdx": "CC0-1.0", "textSha256": sha(license_text)},
            "samples": [
                {
                    "sampleId": "own",
                    "path": "samples/own.wav",
                    "sha256": sha(sample),
                    "byteSize": len(sample),
                }
            ],
        }
        pin = write_json(self.piano / "instrument-pack.json", manifest)
        xml = b"owned score fixture; no music parsing requested"
        (self.scores / "own.xml").write_bytes(xml)
        score_pin = write_json(
            self.scores / "own.json", {"score_id": "fixture-own.v1", "license": "Public Domain"}
        )
        self.contract = {
            "schema_version": "motif-resource-contract.v1",
            "piano": {
                "pack_id": "fixture:own",
                "pack_version": "test1",
                "manifest_sha256": pin,
                "license_sha256": sha(license_text),
                "sample_count": 1,
            },
            "scores": [
                {
                    "score_id": "fixture-own.v1",
                    "title": "自制临时谱",
                    "manifest_path": "own.json",
                    "manifest_sha256": score_pin,
                    "license": "Public Domain",
                    "files": [{"path": "own.xml", "sha256": sha(xml)}],
                    "simplified": True,
                    "simplification_summary": "自制测试数据",
                }
            ],
        }

    def audit(self, health=None, contract=None, piano=True):
        return audit_resources(
            contract or self.contract, self.piano if piano else None, self.scores, health
        )

    def codes(self, value):
        return [x["code"] for x in value["issues"]]

    def test_read_only_assets_do_not_imply_runtime_readiness(self):
        before = {str(p): sha(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        result = self.audit()
        self.assertTrue(result["assets_verified"])
        self.assertFalse(result["resource_ready"])
        self.assertEqual(result["status"], "assets_verified")
        self.assertEqual(result["renderer_admission"], "not_checked")
        self.assertEqual(
            before, {str(p): sha(p.read_bytes()) for p in self.root.rglob("*") if p.is_file()}
        )

    def test_plain_ready_without_pack_is_blocked(self):
        result = self.audit({"status": "ready", "instrumentPacks": []})
        self.assertTrue(result["assets_verified"])
        self.assertFalse(result["resource_ready"])
        self.assertIn("RENDERER_PACK_NOT_ADMITTED", self.codes(result))

    def test_exact_supplied_health_identity_matches(self):
        p = self.contract["piano"]
        result = self.audit(
            {
                "status": "ready",
                "instrumentPacks": [
                    {
                        "packId": p["pack_id"],
                        "packVersion": p["pack_version"],
                        "manifestSha256": p["manifest_sha256"],
                    }
                ],
            }
        )
        self.assertTrue(result["resource_ready"])
        self.assertEqual(result["renderer_evidence"], "provided_health_snapshot")

    def test_missing_config_and_missing_root_are_distinct(self):
        self.assertIn("PIANO_CONFIGURATION_MISSING", self.codes(self.audit(piano=False)))
        result = audit_resources(self.contract, self.root / "not-mounted", self.scores)
        self.assertIn("PIANO_ROOT_UNAVAILABLE", self.codes(result))

    def test_missing_sample_is_located_without_host_paths(self):
        (self.piano / "samples/own.wav").unlink()
        result = self.audit()
        self.assertIn("RESOURCE_FILE_MISSING", self.codes(result))
        self.assertEqual(result["issues"][0]["relative_path"], "samples/own.wav")
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_corrupt_sample_is_rejected(self):
        file = self.piano / "samples/own.wav"
        file.write_bytes(b"x" * len(file.read_bytes()))
        self.assertIn("RESOURCE_HASH_MISMATCH", self.codes(self.audit()))

    def test_license_and_manifest_corruption_are_distinct(self):
        (self.piano / "cc0.txt").write_bytes(b"changed")
        self.assertIn("RESOURCE_LICENSE_HASH_MISMATCH", self.codes(self.audit()))
        (self.piano / "instrument-pack.json").write_bytes(b"{}")
        self.assertIn("RESOURCE_MANIFEST_HASH_MISMATCH", self.codes(self.audit()))

    def test_symlinked_sample_is_rejected(self):
        file = self.piano / "samples/own.wav"
        outside = self.root / "outside.wav"
        outside.write_bytes(file.read_bytes())
        file.unlink()
        file.symlink_to(outside)
        self.assertIn("RESOURCE_FILE_UNSAFE", self.codes(self.audit()))

    def test_missing_score_and_changed_score_manifest_are_diagnosed(self):
        (self.scores / "own.xml").unlink()
        self.assertIn("RESOURCE_FILE_MISSING", self.codes(self.audit()))
        (self.scores / "own.json").write_bytes(b"{}")
        self.assertIn("RESOURCE_MANIFEST_HASH_MISMATCH", self.codes(self.audit()))

    def test_symlink_loop_returns_safe_root_and_file_diagnostics(self):
        loop = self.root / "loop"
        loop.symlink_to("loop")
        for piano, scores, expected in (
            (loop, self.scores, "PIANO_ROOT_UNAVAILABLE"),
            (self.piano, loop, "SCORE_ROOT_UNAVAILABLE"),
        ):
            with self.subTest(expected=expected):
                result = audit_resources(self.contract, piano, scores)
                self.assertIn(expected, self.codes(result))
                self.assertFalse(result["resource_ready"])
                self.assertNotIn(str(self.root), json.dumps(result))
        sample = self.piano / "samples/own.wav"
        sample.unlink()
        sample.symlink_to(loop)
        result = self.audit()
        self.assertIn("RESOURCE_FILE_UNSAFE", self.codes(result))
        self.assertEqual(result["issues"][0]["relative_path"], "samples/own.wav")
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_pinned_unapproved_license_still_rejects(self):
        contract = copy.deepcopy(self.contract)
        contract["scores"][0]["manifest_sha256"] = write_json(
            self.scores / "own.json", {"score_id": "fixture-own.v1", "license": "Unknown"}
        )
        self.assertIn("RESOURCE_LICENSE_NOT_APPROVED", self.codes(self.audit(contract=contract)))


if __name__ == "__main__":
    unittest.main()
