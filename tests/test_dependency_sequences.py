from __future__ import annotations

from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.analysis.clinic import DEFAULT_REGISTRY
from MayaScope.analysis.delta import compare_snapshots
from MayaScope.collectors.dependency_sequences import inspect_local_sequence
from MayaScope.model import ExternalDependency, SceneNode, SceneSnapshot
from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.clinic import ClinicRuleArray


def sequence_dependency(**changes):
    item = ExternalDependency(
        id="external:plate",
        node_id="plate-node",
        node_name="plateTexture",
        node_type="file",
        attribute="plateTexture.fileTextureName",
        kind="texture",
        raw_path="sourceimages/plate.####.exr",
        resolved_path="D:/show/sourceimages/plate.####.exr",
        exists=True,
        path_kind="workspace-relative",
        inside_workspace=True,
        sequence_pattern="####",
        sequence_kind="frame",
        sequence_member_count=2,
        sequence_expected_count=3,
        sequence_missing_count=1,
        sequence_missing_samples=("0002",),
        sequence_scan_complete=True,
        sequence_scan_reason="complete",
    )
    return replace(item, **changes)


class DependencySequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def snapshot(self, dependency):
        return SceneSnapshot.build(
            (SceneNode("plate-node", "plateTexture", "file"),),
            (),
            external_dependencies=(dependency,),
        )

    def test_bounded_local_scanner_finds_frame_gaps_and_udim_members(self):
        with tempfile.TemporaryDirectory(prefix="mayascope-sequence-test-") as folder:
            root = Path(folder)
            for name in ("plate.0001.exr", "plate.0003.exr", "hero.1001.exr", "hero.1002.exr"):
                (root / name).write_bytes(b"probe")
            frames = inspect_local_sequence(
                str(root / "plate.####.exr"),
                "####",
                path_kind="absolute",
            )
            udim = inspect_local_sequence(
                str(root / "hero.<UDIM>.exr"),
                "<UDIM>",
                path_kind="absolute",
            )
        self.assertTrue(frames.scan_complete)
        self.assertEqual(frames.member_count, 2)
        self.assertEqual(frames.missing_count, 1)
        self.assertEqual(frames.missing_samples, ("0002",))
        self.assertEqual(udim.kind, "udim")
        self.assertEqual(udim.member_count, 2)
        self.assertIsNone(udim.missing_count)

    def test_network_and_entry_budget_are_explicit_unknown_states(self):
        network = inspect_local_sequence(
            "//server/show/cache/hero.####.abc",
            "####",
            path_kind="network",
        )
        self.assertFalse(network.scan_complete)
        self.assertEqual(network.scan_reason, "network-path")
        with tempfile.TemporaryDirectory(prefix="mayascope-sequence-budget-") as folder:
            root = Path(folder)
            for index in range(4):
                (root / ("plate.%04d.exr" % index)).write_bytes(b"probe")
            bounded = inspect_local_sequence(
                str(root / "plate.####.exr"),
                "####",
                path_kind="absolute",
                max_entries=2,
            )
        self.assertFalse(bounded.scan_complete)
        self.assertEqual(bounded.scan_reason, "entry-budget-exceeded")

    def test_sequence_gap_rule_and_summary_preserve_atomic_dependency(self):
        snapshot = self.snapshot(sequence_dependency())
        report = DEFAULT_REGISTRY.evaluate(
            snapshot, enabled_rule_ids=("external-sequence-gaps",)
        )
        self.assertFalse(report.failures)
        self.assertEqual(len(report.issues), 1)
        issue = report.issues[0]
        self.assertEqual(issue.atomic_subjects, (("external:plate", "plate-node"),))
        self.assertIn("缺失成员", {item.label for item in issue.evidence})
        self.assertEqual(snapshot.summary()["incomplete_external_sequences"], 1)

    def test_schema_seven_migrates_to_explicit_unknown_sequence_inventory(self):
        payload = self.snapshot(sequence_dependency()).to_dict()
        payload["schema_version"] = 7
        for key in (
            "sequence_kind", "sequence_member_count", "sequence_expected_count",
            "sequence_missing_count", "sequence_missing_samples",
            "sequence_scan_complete", "sequence_scan_reason",
        ):
            payload["external_dependencies"][0].pop(key)
        restored = SceneSnapshot.from_dict(payload).external_dependencies[0]
        self.assertEqual(restored.sequence_kind, "")
        self.assertFalse(restored.sequence_scan_complete)
        self.assertIn("旧版快照", restored.sequence_scan_reason)

    def test_delta_tracks_sequence_completeness_change(self):
        before = self.snapshot(sequence_dependency())
        after = self.snapshot(
            sequence_dependency(
                sequence_member_count=3,
                sequence_missing_count=0,
                sequence_missing_samples=(),
            )
        )
        change = compare_snapshots(before, after).external_dependency_changes[0]
        self.assertIn("sequence_missing_count", change.changed_fields)
        self.assertIn("sequence_member_count", change.changed_fields)

    def test_chinese_dependency_lineage_chip_focuses_highest_risk(self):
        panel = ClinicRuleArray()
        item = sequence_dependency()
        panel.set_scene_settings(SceneSnapshot.build((), ()).scene_settings, (item,))
        self.assertIn("依赖谱系 · 1 / 序列 1", panel.dependency_chip.text())
        self.assertIn("缺帧 1", panel.dependency_chip.text())
        self.assertTrue(panel.dependency_chip.property("alert"))
        panel.rule_buttons["external-sequence-gaps"].setChecked(False)
        focused = []
        panel.ruleFocusRequested.connect(focused.append)
        panel.dependency_chip.click()
        self.assertEqual(focused, ["external-sequence-gaps"])
        self.assertTrue(panel.rule_buttons["external-sequence-gaps"].isChecked())
        self.assertIn("已定位依赖谱系规则", panel.telemetry.text())


if __name__ == "__main__":
    unittest.main()
