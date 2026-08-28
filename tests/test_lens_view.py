from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.analysis.lens import build_root_cause_report
from MayaScope.model import SceneEdge, SceneNode, SceneSnapshot
from MayaScope.presentation import present_lens_result
from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.lens import LensControlBar, LensRibbon
from MayaScope.ui.clinic import SceneClinicView


class LensViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def test_control_bar_owns_direction_depth_and_compact_chrome(self):
        bar = LensControlBar()
        directions = []
        depths = []
        bar.directionChanged.connect(directions.append)
        bar.depthChanged.connect(depths.append)
        bar.set_focus("主角面部控制器", "|角色|控制器")
        bar.downstream_button.click()
        bar.depth_spin.setValue(6)
        self.assertEqual(bar.direction, "downstream")
        self.assertEqual(bar.depth, 6)
        self.assertEqual(directions, ["downstream"])
        self.assertEqual(depths, [6])
        bar.set_compact(True)
        self.assertTrue(bar.focus_label.isHidden())
        self.assertTrue(bar.maya_select_button.isHidden())
        bar.close()

    def test_ribbon_builds_keyboard_accessible_cards_from_validated_state(self):
        snapshot = SceneSnapshot.build(
            (SceneNode("driver", "共享驱动", "multiplyDivide"), SceneNode("focus", "面部控制器", "transform")),
            (SceneEdge("driver", "focus", source_plug="outputX", target_plug="translateX"),),
        )
        report = build_root_cause_report(snapshot, "focus")
        ribbon = LensRibbon()
        ribbon.set_state(present_lens_result(report, snapshot))
        card = ribbon.cards.itemAt(0).widget()
        self.assertIn("共享驱动", card.accessibleName())
        self.assertIn("结构推断", ribbon.summary.text())
        self.assertFalse(ribbon.isHidden())
        ribbon.close()

    def test_lens_mode_gives_the_evidence_rail_to_the_causal_path(self):
        view = SceneClinicView()
        view.set_lens_mode(True)
        self.assertEqual(view.eyebrow.text(), "因果证据")
        self.assertTrue(view.rule_array.isHidden())
        self.assertTrue(view.issue_scroll.isHidden())
        view.set_lens_mode(False)
        self.assertEqual(view.eyebrow.text(), "问题证据")
        view.close()


class LensViewBoundaryTests(unittest.TestCase):
    def test_workspace_composes_lens_without_defining_its_views(self):
        ui_root = Path(__file__).resolve().parents[1] / "ui"
        workspace = (ui_root / "workspace.py").read_text(encoding="utf-8")
        lens = (ui_root / "lens.py").read_text(encoding="utf-8")
        self.assertIn("from .lens import LensControlBar, LensRibbon", workspace)
        self.assertNotIn("class CandidateCard", workspace)
        self.assertNotIn("class LensRibbon", workspace)
        self.assertIn("class LensControlBar", lens)
        self.assertIn("class LensRibbon", lens)
        for forbidden in ("maya.cmds", "maya.api", "collectors", "from .workspace"):
            self.assertNotIn(forbidden, lens)


if __name__ == "__main__":
    unittest.main()
