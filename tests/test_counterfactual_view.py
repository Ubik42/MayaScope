from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.analysis.counterfactual import ExperimentObservation, build_counterfactual_report
from MayaScope.presentation.counterfactual import present_counterfactual_report
from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.counterfactual import CounterfactualStrip


def _state():
    observations = (
        ExperimentObservation(0, "baseline", 0, 1000, 900, 3),
        ExperimentObservation(0, "variant", 1, 700, 620, 3),
    )
    report = build_counterfactual_report(
        observations,
        target_node_id="solver",
        target_name="绑定求解器",
        attribute="nodeState",
        baseline_value=0,
        variant_value=1,
        warmup_count=1,
    )
    return present_counterfactual_report(report)


class CounterfactualViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_strip_renders_chinese_state_and_honors_reduced_motion(self):
        strip = CounterfactualStrip()
        strip.set_state(_state())
        self.assertEqual(strip.target.text(), "绑定求解器")
        self.assertIn("1 组配对", strip.design.text())
        self.assertIn("改善", strip.result_metric.text())
        self.assertIn("95% 区间", strip.interval.text())
        strip.set_motion_enabled(False)
        self.assertFalse(strip.spark._timer.isActive())
        strip.clear()
        self.assertEqual(strip.target.text(), "尚未实验")
        strip.close()


class CounterfactualViewBoundaryTests(unittest.TestCase):
    def test_workspace_composes_spectrum_without_defining_or_interpreting_it(self):
        root = Path(__file__).resolve().parents[1]
        workspace = (root / "ui" / "workspace.py").read_text(encoding="utf-8")
        view = (root / "ui" / "counterfactual.py").read_text(encoding="utf-8")
        presenter = (root / "presentation" / "counterfactual.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from .counterfactual import CounterfactualStrip", workspace)
        self.assertNotIn("class CounterfactualSpark", workspace)
        self.assertNotIn("class CounterfactualStrip", workspace)
        self.assertNotIn("report.baseline_mean_us", workspace)
        self.assertIn("class CounterfactualSpark", view)
        self.assertIn("class CounterfactualStrip", view)
        for forbidden in ("maya.cmds", "maya.api", "collectors", "from .workspace"):
            self.assertNotIn(forbidden, view)
        for forbidden in ("PySide", "qt_compat", "maya.", "ui."):
            self.assertNotIn(forbidden, presenter)


if __name__ == "__main__":
    unittest.main()
