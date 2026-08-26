from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from MayaScope.audit import _atomic_json
from MayaScope.project_audit import (
    build_project_audit,
    main,
    verify_project_audit,
)


def write_audit(path: Path, scene: Path, *, gate_failed=False, profile="publish", fingerprint="team-a", issues=()):
    _atomic_json(
        path,
        {
            "format": "mayascope.clinic-audit",
            "schema_version": 2,
            "ok": True,
            "gate_failed": gate_failed,
            "audit_exit_code": 2 if gate_failed else 0,
            "source_scene": str(scene),
            "source_sha256": (scene.stem[0] * 64),
            "profile": profile,
            "config_fingerprint": fingerprint,
            "maya": {"version": "2025", "api": 20250000},
            "snapshot": {"scene_lifecycle": {"workspace_root": "D:/show"}},
            "issues": list(issues),
        },
    )


class ProjectAuditTests(unittest.TestCase):
    def test_signed_bundle_aggregates_scenes_and_atomic_subjects(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, second = root / "a.json", root / "b.json"
            write_audit(first, root / "a.ma")
            write_audit(
                second,
                root / "b.ma",
                gate_failed=True,
                issues=(
                    {
                        "rule_id": "missing-external-files",
                        "severity": "error",
                        "atomic_subjects": [
                            {"id": "dep-a", "node_id": "node-a"},
                            {"id": "dep-b", "node_id": "node-a"},
                        ],
                    },
                ),
            )
            bundle = root / "project.json"
            payload = build_project_audit((second, first), bundle)
            self.assertEqual(payload["summary"]["scene_count"], 2)
            self.assertEqual(payload["summary"]["blocked_scene_count"], 1)
            self.assertEqual(payload["summary"]["atomic_finding_count"], 2)
            self.assertEqual(payload["summary"]["severity_counts"]["error"], 1)
            self.assertEqual(payload["scenes"][0]["receipt"]["source_scene"], str(root / "a.ma"))
            verified = verify_project_audit(bundle)
            self.assertEqual(verified["project_sha256"], payload["project_sha256"])

    def test_bundle_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report, bundle = root / "a.json", root / "project.json"
            write_audit(report, root / "a.ma")
            build_project_audit((report,), bundle)
            payload = json.loads(bundle.read_text(encoding="utf-8"))
            payload["summary"]["scene_count"] = 99
            bundle.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "签名不匹配"):
                verify_project_audit(bundle)

    def test_mixed_context_and_duplicate_scene_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first, second = root / "a.json", root / "b.json"
            write_audit(first, root / "a.ma")
            write_audit(second, root / "b.ma", fingerprint="team-b")
            with self.assertRaisesRegex(ValueError, "上下文不一致"):
                build_project_audit((first, second))
            write_audit(second, root / "a.ma")
            with self.assertRaisesRegex(ValueError, "重复场景"):
                build_project_audit((first, second))

    def test_cli_exit_codes_follow_project_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report, bundle = root / "a.json", root / "project.json"
            write_audit(report, root / "a.ma", gate_failed=True)
            self.assertEqual(main(["build", str(report), "--report", str(bundle), "--summary"]), 2)
            self.assertEqual(main(["verify", str(bundle), "--summary"]), 2)


if __name__ == "__main__":
    unittest.main()
