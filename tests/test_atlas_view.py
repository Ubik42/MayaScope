from __future__ import annotations

import os
from pathlib import Path
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from MayaScope.analysis.rules import Evidence, Issue, Severity
from MayaScope.model import SceneEdge, SceneNode, SceneSnapshot
from MayaScope.qt_compat import QtWidgets
from MayaScope.ui.atlas import MAX_RENDER_NODES, SpectralAtlasView


class SpectralAtlasViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.view = SpectralAtlasView()
        self.view.set_motion_enabled(False)

    def tearDown(self):
        self.view.close()
        self.view.deleteLater()
        self.app.processEvents()

    @staticmethod
    def _snapshot(count=3):
        nodes = tuple(
            SceneNode(str(index), "节点_%03d" % index, "network")
            for index in range(count)
        )
        edges = tuple(
            SceneEdge(str(index), str(index + 1))
            for index in range(max(0, count - 1))
        )
        return SceneSnapshot.build(nodes, edges, source_scene="atlas_demo.ma")

    def test_snapshot_materializes_real_nodes_edges_and_chinese_accessible_name(self):
        self.view.set_snapshot(self._snapshot(), ())
        self.assertEqual(set(self.view._node_items), {"0", "1", "2"})
        self.assertEqual(len(self.view._edge_items), 2)
        self.assertIn("场景图谱", self.view.accessibleName())

    def test_issue_nodes_are_prioritized_inside_bounded_render_budget(self):
        snapshot = self._snapshot(MAX_RENDER_NODES + 5)
        last_id = str(MAX_RENDER_NODES + 4)
        issue = Issue(
            id="issue:last",
            rule_id="test-priority",
            title="末端节点异常",
            description="验证异常节点不会因图谱预算被静默省略。",
            severity=Severity.WARNING,
            affected_node_ids=(last_id,),
            evidence=(Evidence("节点", last_id),),
        )
        self.view.set_snapshot(snapshot, (issue,))
        self.assertEqual(len(self.view._node_items), MAX_RENDER_NODES)
        self.assertIn(last_id, self.view._node_items)

    def test_external_selection_does_not_echo_back_as_user_activation(self):
        self.view.set_snapshot(self._snapshot(), ())
        activated = []
        self.view.nodeActivated.connect(activated.append)
        self.view.select_node_ids(("1",), center=True)
        self.app.processEvents()
        self.assertEqual(activated, [])
        self.assertTrue(self.view._node_items["1"].isSelected())

    def test_motion_switch_owns_only_the_atlas_timer(self):
        self.assertFalse(self.view._timer.isActive())
        self.view.set_motion_enabled(True)
        self.assertTrue(self.view._timer.isActive())
        self.view.set_motion_enabled(False)
        self.assertFalse(self.view._timer.isActive())


class UiBoundarySourceTests(unittest.TestCase):
    def test_workspace_composes_atlas_instead_of_defining_graphics_items(self):
        ui_root = Path(__file__).resolve().parents[1] / "ui"
        workspace = (ui_root / "workspace.py").read_text(encoding="utf-8")
        atlas = (ui_root / "atlas.py").read_text(encoding="utf-8")
        self.assertNotIn("class SpectralAtlasView", workspace)
        self.assertNotIn("class AtlasNodeItem", workspace)
        self.assertIn("from .atlas import MAX_RENDER_NODES, SpectralAtlasView", workspace)
        self.assertNotIn("maya.cmds", atlas)
        self.assertNotIn("maya.api", atlas)


if __name__ == "__main__":
    unittest.main()
