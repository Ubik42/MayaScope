from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.capture import SceneCaptureStrip


class SceneCaptureViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def test_loading_progress_cancel_and_clear_have_distinct_chinese_states(self):
        strip = SceneCaptureStrip()
        strip.start(required=False)
        self.assertFalse(strip.isHidden())
        self.assertEqual(strip.heading.text(), "建立稳定场景快照")
        self.assertEqual(strip.progress.property("state"), "active")
        self.assertTrue(strip.sweep._timer.isActive())
        strip.update_progress("读取节点身份", 32, 128)
        self.assertEqual(strip.heading.text(), "读取节点身份")
        self.assertEqual(strip.progress.text(), "32 / 128")
        strip.show_cancelling()
        self.assertEqual(strip.progress.property("state"), "cancelling")
        self.assertIn("部分快照不会进入", strip.meta.text())
        strip.clear()
        self.assertTrue(strip.isHidden())
        self.assertFalse(strip.sweep._timer.isActive())
        strip.close()

    def test_required_recheck_compact_and_reduced_motion_are_explicit(self):
        strip = SceneCaptureStrip()
        strip.set_motion_enabled(False)
        strip.start(required=True)
        self.assertEqual(strip.heading.text(), "执行后强制复检")
        self.assertEqual(strip.progress.text(), "强制验证")
        self.assertFalse(strip.sweep._timer.isActive())
        strip.set_compact(True)
        self.assertTrue(strip.meta.isHidden())
        self.assertTrue(strip.boundary.isHidden())
        self.assertEqual(strip.mark.text(), "▦  探针")
        strip.close()


class SceneCaptureViewBoundaryTests(unittest.TestCase):
    def test_workspace_composes_capture_strip_without_defining_it(self):
        ui_root = Path(__file__).resolve().parents[1] / "ui"
        workspace = (ui_root / "workspace.py").read_text(encoding="utf-8")
        capture = (ui_root / "capture.py").read_text(encoding="utf-8")
        self.assertIn("from .capture import SceneCaptureStrip", workspace)
        self.assertNotIn("class SceneCaptureStrip", workspace)
        self.assertIn("class SceneCaptureStrip", capture)
        for forbidden in ("maya.cmds", "maya.api", "collectors", "from .workspace"):
            self.assertNotIn(forbidden, capture)


if __name__ == "__main__":
    unittest.main()
