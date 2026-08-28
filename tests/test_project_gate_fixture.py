from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from MayaScope.audit import _canonical_json, verify_audit_report
from MayaScope.examples.generate.project_gate_fixture import build_fixture
from MayaScope.project_audit import verify_project_audit


class ProjectGateFixtureTests(unittest.TestCase):
    def test_fixture_generates_real_signed_reports_and_blocked_project_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            result = build_fixture(Path(folder))
            bundle = verify_project_audit(Path(result["bundle"]))
            self.assertEqual(bundle["summary"]["scene_count"], 3)
            self.assertEqual(bundle["summary"]["passed_scene_count"], 2)
            self.assertEqual(bundle["summary"]["blocked_scene_count"], 1)
            self.assertEqual(bundle["summary"]["atomic_finding_count"], 2)
            manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))
            checksum = manifest.pop("report_sha256")
            import hashlib

            self.assertEqual(hashlib.sha256(_canonical_json(manifest)).hexdigest(), checksum)
            self.assertEqual(manifest["format"], "mayascope.project-gate-fixture")
            for item in manifest["materials"]:
                self.assertTrue(Path(item["scene"]).is_file())
                self.assertTrue(Path(item["report"]).is_file())
                verify_audit_report(Path(item["report"]))

    def test_repository_manifest_tracks_generator_and_expected_boundary(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "examples" / "manifest.json").read_text(encoding="utf-8"))
        entry = next(
            item
            for item in manifest["materials"]
            if item["path"] == "generate/project_gate_fixture.py"
        )
        self.assertTrue((root / "examples" / entry["path"]).is_file())
        self.assertEqual(entry["expected"]["blocked_scene_count"], 1)


if __name__ == "__main__":
    unittest.main()
