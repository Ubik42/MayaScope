from __future__ import annotations

import unittest

from MayaScope.analysis.delta import compare_snapshots
from MayaScope.model import SceneEdge, SceneNode, SceneReference, SceneSnapshot


class SceneDeltaTests(unittest.TestCase):
    def test_added_removed_renamed_modified_and_rewired_are_distinct(self):
        before = SceneSnapshot.build(
            (
                SceneNode("driver_a", "driverA", "network"),
                SceneNode("driver_b", "driverB", "network"),
                SceneNode("target", "target", "transform"),
                SceneNode("gone", "gone", "network"),
            ),
            (
                SceneEdge("driver_a", "target", source_plug="driverA.out", target_plug="target.tx"),
                SceneEdge("gone", "target", source_plug="gone.out", target_plug="target.ty"),
            ),
            snapshot_id="before",
        )
        after = SceneSnapshot.build(
            (
                SceneNode("driver_a", "renamedDriver", "network"),
                SceneNode("driver_b", "driverB", "expression"),
                SceneNode("target", "target", "transform"),
                SceneNode("new", "newNode", "network"),
            ),
            (
                SceneEdge("driver_b", "target", source_plug="driverB.out", target_plug="target.tx"),
                SceneEdge("new", "target", source_plug="new.out", target_plug="target.tz"),
            ),
            snapshot_id="after",
        )
        delta = compare_snapshots(before, after)
        changes = {change.node_id: change for change in delta.node_changes}
        self.assertEqual(changes["driver_a"].kind, "renamed")
        self.assertEqual(changes["driver_b"].kind, "modified")
        self.assertIn("type_name", changes["driver_b"].changed_fields)
        self.assertEqual(changes["gone"].kind, "removed")
        self.assertEqual(changes["new"].kind, "added")
        self.assertEqual(len(delta.rewires), 1)
        self.assertEqual(delta.rewires[0].old_source_id, "driver_a")
        self.assertEqual(delta.rewires[0].new_source_id, "driver_b")
        self.assertEqual(delta.summary()["edges_added"], 1)
        self.assertEqual(delta.summary()["edges_removed"], 1)
        self.assertIn("target", delta.changed_node_ids)

    def test_identical_structure_is_empty_even_with_new_capture_identity(self):
        nodes = (SceneNode("a", "a", "network"), SceneNode("b", "b", "network"))
        edges = (SceneEdge("a", "b"),)
        before = SceneSnapshot.build(nodes, edges, snapshot_id="capture-a")
        after = SceneSnapshot.build(nodes, edges, snapshot_id="capture-b")
        delta = compare_snapshots(before, after)
        self.assertTrue(delta.is_empty)

    def test_reference_lifecycle_is_a_first_class_delta(self):
        nodes = (SceneNode("asset-node", "asset:root", "transform", referenced=True),)
        before = SceneSnapshot.build(
            nodes,
            (),
            (
                SceneReference(
                    "assetRN",
                    "D:/assets/hero_v001.ma",
                    namespace="asset",
                    loaded=True,
                    node_ids=("asset-node",),
                ),
            ),
            snapshot_id="before-ref",
        )
        after = SceneSnapshot.build(
            nodes,
            (),
            (
                SceneReference(
                    "assetRN",
                    "D:/assets/hero_v002.ma",
                    namespace="asset",
                    loaded=False,
                    node_ids=("asset-node",),
                    failed_edit_count=1,
                    failed_edit_samples=("failed edit",),
                ),
            ),
            snapshot_id="after-ref",
        )
        delta = compare_snapshots(before, after)
        self.assertFalse(delta.is_empty)
        self.assertEqual(len(delta.reference_changes), 1)
        change = delta.reference_changes[0]
        self.assertEqual(change.kind, "modified")
        self.assertEqual(
            set(change.changed_fields),
            {"resolved_path", "loaded", "failed_edit_count", "failed_edit_samples"},
        )
        self.assertIn("asset-node", delta.changed_node_ids)
        self.assertEqual(delta.summary()["references_modified"], 1)


if __name__ == "__main__":
    unittest.main()
