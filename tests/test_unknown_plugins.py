from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.analysis.clinic import DEFAULT_REGISTRY
from MayaScope.analysis.delta import compare_snapshots
from MayaScope.model import SceneNode, SceneSnapshot, SnapshotValidationError, UnknownPlugin
from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.workspace import ClinicRuleArray


class UnknownPluginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def snapshot(self, plugins=()):
        nodes = (
            SceneNode(
                "ghost-node", "ghostSolver1", "unknown",
                metadata={
                    "unknown_plugin": "studioGhostTools",
                    "unknown_real_class": "studioGhostSolver",
                },
            ),
        ) if plugins else ()
        return SceneSnapshot.build(nodes, (), unknown_plugins=plugins)

    def test_snapshot_round_trip_migration_validation_and_summary(self):
        plugin = UnknownPlugin(
            "studioGhostTools", "4.7", ("studioGhostSolver",), ("ghostPayload",)
        )
        snapshot = self.snapshot((plugin,))
        restored = SceneSnapshot.from_json(snapshot.to_json())
        self.assertEqual(restored.unknown_plugins, (plugin,))
        self.assertEqual(restored.summary()["unknown_plugins"], 1)
        self.assertEqual(restored.summary()["unknown_plugin_node_types"], 1)

        v5 = snapshot.to_dict()
        v5["schema_version"] = 5
        v5.pop("unknown_plugins")
        self.assertEqual(SceneSnapshot.from_dict(v5).unknown_plugins, ())
        with self.assertRaises(SnapshotValidationError):
            self.snapshot((plugin, plugin))

    def test_missing_plugin_is_a_deterministic_atomic_root_cause(self):
        snapshot = self.snapshot((
            UnknownPlugin(
                "studioGhostTools", "4.7", ("studioGhostSolver",), ("ghostPayload",)
            ),
        ))
        report = DEFAULT_REGISTRY.evaluate(
            snapshot,
            enabled_rule_ids=("missing-plugin-requirements", "unknown-nodes"),
        )
        issues = {issue.rule_id: issue for issue in report.issues}
        plugin_issue = issues["missing-plugin-requirements"]
        self.assertEqual(plugin_issue.affected_node_ids, ("ghost-node",))
        self.assertEqual(
            plugin_issue.atomic_subjects,
            (("unknown-plugin:studioGhostTools", ""),),
        )
        evidence = {item.label: item.value for item in plugin_issue.evidence}
        self.assertIn("studioGhostTools 4.7", evidence["插件 / 版本"])
        self.assertEqual(evidence["已关联未知节点"], "1")
        unknown_evidence = {
            item.label: item.value for item in issues["unknown-nodes"].evidence
        }
        self.assertEqual(unknown_evidence["来源插件"], "studioGhostTools")
        self.assertEqual(unknown_evidence["原始类型"], "studioGhostSolver")

    def test_plugin_registry_changes_are_first_class_delta(self):
        before = self.snapshot((
            UnknownPlugin("studioGhostTools", "4.7", ("studioGhostSolver",), ()),
        ))
        after = SceneSnapshot.build((), ())
        removed = compare_snapshots(before, after)
        self.assertEqual(removed.summary()["unknown_plugins_removed"], 1)
        self.assertFalse(removed.is_empty)

        changed = compare_snapshots(
            before,
            self.snapshot((
                UnknownPlugin("studioGhostTools", "5.0", ("studioGhostSolverV2",), ()),
            )),
        )
        self.assertEqual(changed.unknown_plugin_changes[0].kind, "modified")
        self.assertEqual(
            set(changed.unknown_plugin_changes[0].changed_fields),
            {"version", "node_types"},
        )

    def test_chinese_plugin_ghost_chip_exposes_risk_and_focus_action(self):
        panel = ClinicRuleArray()
        panel.set_scene_settings(
            SceneSnapshot.build((), ()).scene_settings,
            unknown_plugins=(UnknownPlugin("studioGhostTools", "4.7", ("solver",), ()),),
        )
        self.assertIn("插件幽灵 · 1", panel.plugin_chip.text())
        self.assertTrue(panel.plugin_chip.property("alert"))
        panel.rule_buttons["missing-plugin-requirements"].setChecked(False)
        panel.plugin_chip.click()
        self.assertTrue(panel.rule_buttons["missing-plugin-requirements"].isChecked())
        self.assertIn("已定位缺失插件规则", panel.telemetry.text())


if __name__ == "__main__":
    unittest.main()
