from __future__ import annotations

import unittest

from MayaScope.analysis.regression import compare_audit_reports, summarize_performance


def audit(issues=(), samples=(10000, 10100, 9900, 10050, 9950)):
    return {
        "format": "mayascope.clinic-audit",
        "schema_version": 1,
        "report_sha256": "a" * 64,
        "profile": "publish",
        "config_fingerprint": "config-a",
        "maya": {"version": "2025"},
        "snapshot": {"nodes": 10, "edges": 12, "references": 1},
        "issues": list(issues),
        "performance": {"samples_us": list(samples), "evaluation_mode": "parallel"},
    }


def issue(rule, node, severity="error", value=30):
    return {
        "rule_id": rule,
        "affected_node_ids": [node],
        "severity": severity,
        "severity_value": value,
        "title": rule,
    }


def scene_issue(rule, issue_id):
    return {
        "id": issue_id,
        "rule_id": rule,
        "affected_node_ids": [],
        "severity": "warning",
        "severity_value": 20,
        "title": rule,
    }


class RegressionTests(unittest.TestCase):
    def test_summary_uses_median_p95_and_mad(self):
        summary = summarize_performance((10, 11, 12, 13, 100))
        self.assertEqual(summary.median_us, 12)
        self.assertEqual(summary.p95_us, 100)
        self.assertEqual(summary.mad_us, 1)

    def test_new_and_resolved_findings_are_atomic_by_stable_node(self):
        baseline = audit((issue("unknown", "node-a"), issue("unknown", "node-b")))
        current = audit((issue("unknown", "node-b"), issue("cycle", "node-c")))
        report = compare_audit_reports(baseline, current)
        self.assertEqual(report["new_findings"][0]["node_id"], "node-c")
        self.assertEqual(report["resolved_findings"][0]["node_id"], "node-a")
        self.assertTrue(report["clinic_gate_failed"])

    def test_performance_regression_must_exceed_ratio_absolute_and_noise_bands(self):
        baseline = audit(samples=(10000, 10100, 9900, 10050, 9950))
        current = audit(samples=(15000, 15100, 14900, 15050, 14950))
        report = compare_audit_reports(baseline, current)
        self.assertTrue(report["performance"]["regressed"])
        self.assertTrue(report["gate_failed"])

        noisy = audit(samples=(9000, 11000, 10000, 12000, 8000))
        report = compare_audit_reports(baseline, noisy)
        self.assertFalse(report["performance"]["regressed"])

    def test_incompatible_environment_is_rejected(self):
        current = audit()
        current["config_fingerprint"] = "config-b"
        with self.assertRaisesRegex(ValueError, "fingerprints differ"):
            compare_audit_reports(audit(), current)

        baseline = audit()
        current = audit()
        baseline["snapshot"]["scene_lifecycle"] = {"workspace_root": "D:/showA"}
        current["snapshot"]["scene_lifecycle"] = {"workspace_root": "D:/showB"}
        with self.assertRaisesRegex(ValueError, "workspaces differ"):
            compare_audit_reports(baseline, current)

        baseline = audit()
        current = audit()
        baseline["snapshot"]["scene_settings"] = {"time_unit": "film"}
        current["snapshot"]["scene_settings"] = {"time_unit": "pal"}
        with self.assertRaisesRegex(ValueError, "settings differ"):
            compare_audit_reports(baseline, current)

    def test_scene_and_aggregated_dependency_subjects_do_not_collapse(self):
        baseline_dependency = {
            **issue("missing-external-files", "file-node"),
            "atomic_subjects": [
                {"id": "external:a", "node_id": "file-node"}
            ],
        }
        current_dependency = {
            **issue("missing-external-files", "file-node"),
            "atomic_subjects": [
                {"id": "external:a", "node_id": "file-node"},
                {"id": "external:b", "node_id": "file-node"},
            ],
        }
        baseline = audit((baseline_dependency, scene_issue("scene-contract", "scene-contract:time")))
        current = audit((current_dependency, scene_issue("scene-contract", "scene-contract:axis")))
        report = compare_audit_reports(baseline, current, severity_threshold=20)
        self.assertEqual(
            {item["subject_id"] for item in report["new_findings"]},
            {"external:b", "scene-contract:axis"},
        )
        self.assertEqual(
            {item["subject_id"] for item in report["resolved_findings"]},
            {"scene-contract:time"},
        )


if __name__ == "__main__":
    unittest.main()
