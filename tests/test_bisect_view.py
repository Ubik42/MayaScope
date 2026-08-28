from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.bisect import BisectPrism


class BisectViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_prism_renders_presenter_state_and_releases_motion(self):
        prism = BisectPrism()
        plan = SimpleNamespace(
            candidates=("rig", "reference"),
            metadata={"isolation_mode": "post-open-copy"},
            source_sha256="c" * 64,
        )
        prism.begin(plan)
        self.assertEqual(prism.signal.text(), "2 个候选已装载")
        self.assertIn("打开后隔离", prism.mode.text())

        step = SimpleNamespace(candidate_ids=("reference",))
        attempt = SimpleNamespace(
            outcome="pass",
            stage="complement",
            attempt_index=0,
            duration_seconds=0.8,
            timed_out=False,
        )
        prism.add_attempt(step, attempt)
        self.assertEqual(prism.signal.text(), "通过  ·  1 / 2")
        prism.request_cancel()
        self.assertFalse(prism.cancel.isEnabled())
        self.assertEqual(prism.cancel.text(), "已排队停止")
        prism.set_motion_enabled(False)
        self.assertFalse(prism.canvas._timer.isActive())
        prism.close()


class BisectViewBoundaryTests(unittest.TestCase):
    def test_workspace_composes_prism_without_defining_it(self):
        root = Path(__file__).resolve().parents[1]
        workspace = (root / "ui" / "workspace.py").read_text(encoding="utf-8")
        view = (root / "ui" / "bisect.py").read_text(encoding="utf-8")
        presenter = (root / "presentation" / "bisect.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from .bisect import BisectPrism", workspace)
        self.assertNotIn("class BisectPrism", workspace)
        self.assertNotIn("class BisectTraceCanvas", workspace)
        self.assertIn("class BisectPrism", view)
        self.assertIn("class BisectTraceCanvas", view)
        for forbidden in ("maya.cmds", "maya.api", "collectors", "from .workspace"):
            self.assertNotIn(forbidden, view)
        for forbidden in ("PySide", "qt_compat", "maya.", "ui."):
            self.assertNotIn(forbidden, presenter)


if __name__ == "__main__":
    unittest.main()
