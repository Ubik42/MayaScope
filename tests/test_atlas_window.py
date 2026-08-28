from __future__ import annotations

from pathlib import Path
import unittest

from MayaScope.analysis.graph import GraphIndex
from MayaScope.model import SceneEdge, SceneNode, SceneSnapshot
from MayaScope.presentation.atlas_window import (
    build_atlas_window,
    diff_atlas_windows,
)


class AtlasWindowPlanTests(unittest.TestCase):
    @staticmethod
    def _snapshot(count=8, *, snapshot_id="atlas-a", extra_edges=()):
        nodes = tuple(
            SceneNode(str(index), "节点_%03d" % index, "network")
            for index in range(count)
        )
        edges = tuple(SceneEdge(str(index), str(index + 1)) for index in range(count - 1))
        return SceneSnapshot.build(
            nodes,
            edges + tuple(extra_edges),
            source_scene="atlas-scale.ma",
            snapshot_id=snapshot_id,
        )

    def test_priority_nodes_enter_bounded_window_in_declared_order(self):
        snapshot = self._snapshot()
        graph = GraphIndex(snapshot, ("dg", "dag"))
        plan = build_atlas_window(snapshot, graph, graph.ranked_node_ids(), ("7", "6"), limit=4)
        self.assertEqual(plan.node_ids[:2], ("7", "6"))
        self.assertEqual(len(plan.node_ids), 4)
        self.assertEqual(plan.total_node_count, 8)

    def test_layout_and_parallel_edge_identity_are_deterministic(self):
        parallels = (
            SceneEdge("0", "1", source_plug="a", target_plug="b"),
            SceneEdge("0", "1", source_plug="a", target_plug="b"),
        )
        snapshot = self._snapshot(extra_edges=parallels)
        graph = GraphIndex(snapshot, ("dg", "dag"))
        first = build_atlas_window(snapshot, graph, snapshot.node_map, limit=8)
        second = build_atlas_window(snapshot, graph, snapshot.node_map, limit=8)
        self.assertEqual(first, second)
        duplicate = [edge for edge in first.edges if edge.source_plug == "a"]
        self.assertEqual([edge.ordinal for edge in duplicate], [0, 1])

    def test_diff_reports_only_actual_window_changes(self):
        first_snapshot = self._snapshot(snapshot_id="first")
        first_graph = GraphIndex(first_snapshot, ("dg", "dag"))
        first = build_atlas_window(first_snapshot, first_graph, first_snapshot.node_map, limit=5)
        same_snapshot = self._snapshot(snapshot_id="second")
        same_graph = GraphIndex(same_snapshot, ("dg", "dag"))
        same = build_atlas_window(same_snapshot, same_graph, same_snapshot.node_map, limit=5)
        unchanged = diff_atlas_windows(first, same)
        self.assertTrue(unchanged.unchanged)
        self.assertEqual(len(unchanged.retained_node_ids), 5)
        swapped = build_atlas_window(same_snapshot, same_graph, same_snapshot.node_map, ("7",), limit=5)
        diff = diff_atlas_windows(same, swapped)
        self.assertEqual(diff.added_node_ids, ("7",))
        self.assertEqual(len(diff.removed_node_ids), 1)
        self.assertTrue(diff.moved_node_ids)

    def test_rejects_mismatched_graph_and_invalid_limit(self):
        first = self._snapshot(snapshot_id="first")
        second = self._snapshot(snapshot_id="second")
        graph = GraphIndex(first, ("dg", "dag"))
        with self.assertRaisesRegex(ValueError, "does not belong"):
            build_atlas_window(second, graph, (), limit=4)
        with self.assertRaisesRegex(ValueError, "positive"):
            build_atlas_window(first, graph, (), limit=0)
        with self.assertRaisesRegex(ValueError, "edge render limit"):
            build_atlas_window(first, graph, (), edge_limit=0)

    def test_dense_visible_topology_stops_at_explicit_edge_budget(self):
        size = 50
        nodes = tuple(SceneNode(str(index), "密集_%03d" % index, "network") for index in range(size))
        edges = tuple(
            SceneEdge(str(source), str(target))
            for source in range(size)
            for target in range(size)
            if source != target
        )
        snapshot = SceneSnapshot.build(nodes, edges, snapshot_id="dense")
        graph = GraphIndex(snapshot, ("dg", "dag"))
        plan = build_atlas_window(
            snapshot,
            graph,
            graph.ranked_node_ids(),
            limit=size,
            edge_limit=100,
        )
        self.assertEqual(len(plan.edges), 100)


class AtlasWindowSourceBoundaryTests(unittest.TestCase):
    def test_planner_has_no_qt_or_maya_dependency(self):
        source = (Path(__file__).resolve().parents[1] / "presentation" / "atlas_window.py").read_text(encoding="utf-8")
        self.assertNotIn("PySide", source)
        self.assertNotIn("qt_compat", source)
        self.assertNotIn("maya.cmds", source)


if __name__ == "__main__":
    unittest.main()
