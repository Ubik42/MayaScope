from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.analysis.rules import Evidence, Issue, Severity
from MayaScope.analysis.runtime import RuntimeReport
from MayaScope.model import (
    ProfilerCapture,
    ProfilerCategory,
    ProfilerEvent,
    RuntimeSnapshot,
)
from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.profiler import PulseHorizon
from MayaScope.ui.runtime import RuntimeConstellationStrip


class InstrumentViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    @staticmethod
    def _capture():
        return ProfilerCapture(
            events=(
                ProfilerEvent(
                    0, 0, 160, 160, 0, 0, 0, "DG", 0, "节点_A", node_id="a"
                ),
            ),
            categories=(ProfilerCategory(0, "DG"),),
            source_snapshot_id="scene-a",
        )

    @staticmethod
    def _runtime():
        return RuntimeSnapshot(
            source_snapshot_id="scene-a",
            script_jobs=(),
            expressions=(),
            plugins=(),
            node_callbacks=(),
            script_jobs_available=True,
            batch_mode=False,
            maya_version="2025",
            runtime_id="runtime-a",
        )

    def test_profiler_horizon_exposes_safe_chinese_clear_action(self):
        view = PulseHorizon()
        view.set_motion_enabled(False)
        self.assertTrue(view.clear_button.isHidden())
        view.set_capture(self._capture())
        view.resize(800, 142)
        view.show()
        self.app.processEvents()
        self.assertFalse(view.clear_button.isHidden())
        self.assertEqual(view.selected_range, (0, 160))
        self.assertIn("不会修改 Maya 场景", view.clear_button.toolTip())
        self.assertLess(
            view.clear_button.geometry().right(),
            view.counterfactual_button.geometry().left(),
        )
        self.assertLess(
            view.counterfactual_button.geometry().right(),
            view.profile_button.geometry().left(),
        )
        dismissed = []
        view.dismissRequested.connect(lambda: dismissed.append(True))
        view.clear_button.click()
        self.assertEqual(dismissed, [True])
        view.set_capture(None)
        self.assertTrue(view.clear_button.isHidden())
        view.close()
        view.deleteLater()

    def test_runtime_constellation_renders_and_clears_real_report_shape(self):
        runtime = self._runtime()
        issue = Issue(
            "runtime:a",
            "runtime-test",
            "运行时信号",
            "用于测试生产视图。",
            Severity.INFO,
            (),
            (Evidence("边界", "只读"),),
        )
        view = RuntimeConstellationStrip()
        view.set_motion_enabled(False)
        view.set_report(runtime, RuntimeReport(runtime.runtime_id, (issue,), ()))
        self.assertEqual(view.signal.text(), "1 个运行时信号")
        self.assertIn("scriptJob 可读取", view.boundary.text())
        self.assertIn("运行时执行表面", view.accessibleName())
        self.assertFalse(view.canvas._timer.isActive())
        view.clear()
        self.assertEqual(view.signal.text(), "尚未采集")
        view.close()
        view.deleteLater()


class InstrumentViewBoundaryTests(unittest.TestCase):
    def test_workspace_composes_profiler_and_runtime_without_defining_them(self):
        ui_root = Path(__file__).resolve().parents[1] / "ui"
        workspace = (ui_root / "workspace.py").read_text(encoding="utf-8")
        profiler = (ui_root / "profiler.py").read_text(encoding="utf-8")
        runtime = (ui_root / "runtime.py").read_text(encoding="utf-8")
        self.assertIn("from .profiler import PulseHorizon", workspace)
        self.assertIn("from .runtime import RuntimeConstellationStrip", workspace)
        self.assertNotIn("class PulseHorizon", workspace)
        self.assertNotIn("class RuntimeConstellationCanvas", workspace)
        self.assertIn("class PulseHorizon", profiler)
        self.assertIn("class RuntimeConstellationStrip", runtime)
        for source in (profiler, runtime):
            for forbidden in (
                "maya.cmds",
                "maya.api",
                "collectors",
                "from .workspace",
                "import workspace",
            ):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
