from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.presentation.regression import present_regression_report
from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.regression import RegressionRiftStrip


class RegressionViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_strip_renders_validated_chinese_state_and_stops_motion(self):
        payload = {
            "report_sha256": "d" * 64,
            "regression": {
                "baseline_report_sha256": "c" * 64,
                "new_findings": ({"node_id": "solver"},),
                "escalated_findings": (),
                "resolved_findings": (),
                "gate_failed": True,
                "performance": {"comparable": False},
            },
        }
        strip = RegressionRiftStrip()
        strip.set_state(present_regression_report(payload))
        self.assertEqual(strip.verdict.text(), "检测到回归裂隙")
        self.assertIn("新增 1", strip.detail.text())
        self.assertEqual(strip.identity.text(), "基线 CCCCCCCC / 当前 DDDDDDDD")
        strip.set_motion_enabled(False)
        self.assertFalse(strip.canvas._timer.isActive())
        strip.clear()
        self.assertEqual(strip.verdict.text(), "尚无证据")
        strip.close()


class RegressionViewBoundaryTests(unittest.TestCase):
    def test_workspace_composes_rift_without_defining_or_interpreting_it(self):
        root = Path(__file__).resolve().parents[1]
        workspace = (root / "ui" / "workspace.py").read_text(encoding="utf-8")
        view = (root / "ui" / "regression.py").read_text(encoding="utf-8")
        presenter = (root / "presentation" / "regression.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from .regression import RegressionRiftStrip", workspace)
        self.assertNotIn("class RegressionRiftCanvas", workspace)
        self.assertNotIn("class RegressionRiftStrip", workspace)
        self.assertNotIn("performance[\"baseline\"]", workspace)
        self.assertIn("class RegressionRiftCanvas", view)
        self.assertIn("class RegressionRiftStrip", view)
        for forbidden in ("maya.cmds", "maya.api", "collectors", "from .workspace"):
            self.assertNotIn(forbidden, view)
        for forbidden in ("PySide", "qt_compat", "maya.", "ui."):
            self.assertNotIn(forbidden, presenter)


if __name__ == "__main__":
    unittest.main()
