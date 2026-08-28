from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.analysis.clinic import DEFAULT_REGISTRY
from MayaScope.analysis.delta import compare_snapshots
from MayaScope.model import SceneNode, SceneReference, SceneSnapshot
from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.clinic import ClinicRuleArray


class ReferenceHealthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def snapshot(self, *, exists=False, copy_number=1, intruder=True):
        nodes = [
            SceneNode(
                "asset-node", "assetA:assetRoot", "transform",
                referenced=True, reference_file="D:/show/missing/asset.ma",
                namespace="assetA",
            )
        ]
        if intruder:
            nodes.append(
                SceneNode(
                    "local-intruder", "assetA:localIntruder", "transform",
                    namespace="assetA",
                )
            )
        references = (
            SceneReference(
                "assetARN", "D:/show/missing/asset.ma",
                unresolved_path="missing/asset.ma",
                canonical_path="D:/show/missing/asset.ma",
                exists=exists,
                namespace="assetA",
                loaded=False,
                node_ids=("asset-node",),
            ),
            SceneReference(
                "assetBRN", "D:/show/missing/asset.ma{%s}" % copy_number,
                unresolved_path="missing/asset.ma{%s}" % copy_number,
                canonical_path="D:/show/missing/asset.ma",
                copy_number=copy_number,
                exists=exists,
                namespace="assetB",
                loaded=False,
            ),
        )
        return SceneSnapshot.build(nodes, (), references)

    def test_reference_resolution_round_trip_migration_and_summary(self):
        snapshot = self.snapshot()
        restored = SceneSnapshot.from_json(snapshot.to_json())
        self.assertEqual(restored.references, snapshot.references)
        summary = restored.summary()
        self.assertEqual(summary["references"], 2)
        self.assertEqual(summary["reference_source_files"], 1)
        self.assertEqual(summary["missing_reference_files"], 2)
        self.assertEqual(summary["reference_copy_instances"], 1)

        v6 = snapshot.to_dict()
        v6["schema_version"] = 6
        for reference in v6["references"]:
            reference.pop("canonical_path")
            reference.pop("copy_number")
            reference.pop("exists")
        migrated = SceneSnapshot.from_dict(v6)
        self.assertEqual(migrated.schema_version, 8)
        self.assertEqual(migrated.references[1].copy_number, 1)
        self.assertIsNone(migrated.references[0].exists)

    def test_missing_source_and_namespace_intrusion_are_atomic_root_causes(self):
        report = DEFAULT_REGISTRY.evaluate(
            self.snapshot(),
            enabled_rule_ids=(
                "missing-reference-files",
                "reference-namespace-intrusion",
            ),
        )
        issues = {issue.rule_id: issue for issue in report.issues}
        missing = issues["missing-reference-files"]
        self.assertEqual(len(missing.atomic_subjects), 1)
        self.assertIn("缺失源文件", {item.label for item in missing.evidence})
        intrusion = issues["reference-namespace-intrusion"]
        self.assertEqual(intrusion.affected_node_ids, ("local-intruder",))
        self.assertEqual(
            intrusion.atomic_subjects,
            (("reference-namespace-intrusion:local-intruder", "local-intruder"),),
        )

    def test_reference_resolution_changes_are_first_class_delta(self):
        before = self.snapshot()
        after = self.snapshot(exists=True, copy_number=2, intruder=False)
        delta = compare_snapshots(before, after)
        changed = {item.reference_node: item for item in delta.reference_changes}
        self.assertIn("exists", changed["assetARN"].changed_fields)
        self.assertIn("copy_number", changed["assetBRN"].changed_fields)
        self.assertIn("local-intruder", delta.changed_node_ids)

    def test_chinese_reference_orbit_exposes_risk_and_focus_action(self):
        panel = ClinicRuleArray()
        snapshot = self.snapshot()
        panel.set_scene_settings(
            snapshot.scene_settings,
            references=snapshot.references,
            nodes=snapshot.nodes,
        )
        self.assertIn("引用轨道 · 2 实例 / 1 源", panel.reference_chip.text())
        self.assertIn("缺 2 · 越界 1", panel.reference_chip.text())
        self.assertTrue(panel.reference_chip.property("danger"))
        panel.rule_buttons["missing-reference-files"].setChecked(False)
        focused = []
        panel.ruleFocusRequested.connect(focused.append)
        panel.reference_chip.click()
        self.assertTrue(panel.rule_buttons["missing-reference-files"].isChecked())
        self.assertEqual(focused, ["missing-reference-files"])
        self.assertIn("已定位引用健康规则", panel.telemetry.text())


if __name__ == "__main__":
    unittest.main()
