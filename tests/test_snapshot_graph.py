from __future__ import annotations

import unittest

from MayaScope.analysis.graph import GraphIndex, QueryCancelled, QueryKernel
from MayaScope.model import SceneEdge, SceneNode, SceneReference, SceneSnapshot, SnapshotValidationError


class SnapshotGraphTests(unittest.TestCase):
    def setUp(self):
        self.nodes = tuple(SceneNode(str(index), name, "network") for index, name in enumerate("ABCDE"))
        self.snapshot = SceneSnapshot.build(
            self.nodes,
            (
                SceneEdge("0", "1"),
                SceneEdge("1", "2"),
                SceneEdge("2", "0"),
                SceneEdge("2", "3"),
                SceneEdge("3", "4", relation="dag"),
            ),
            source_scene="demo.ma",
            maya_version="2025",
        )

    def test_json_round_trip(self):
        restored = SceneSnapshot.from_json(self.snapshot.to_json())
        self.assertEqual(restored, self.snapshot)
        self.assertEqual(restored.summary()["dg_edges"], 4)

    def test_dangling_edges_are_rejected(self):
        with self.assertRaises(SnapshotValidationError):
            SceneSnapshot.build(self.nodes, (SceneEdge("0", "missing"),))

    def test_queries_and_cycles(self):
        graph = GraphIndex(self.snapshot)
        self.assertEqual(graph.degree("2"), 3)
        self.assertEqual(graph.ranked_node_ids()[0], "2")
        self.assertIs(graph.ranked_node_ids(), graph.ranked_node_ids())
        self.assertEqual(graph.downstream("0"), {"1", "2", "3"})
        self.assertEqual(graph.upstream("3"), {"0", "1", "2"})
        self.assertEqual(graph.shortest_path("0", "3"), ("0", "1", "2", "3"))
        self.assertEqual(graph.strongly_connected_components(), (("0", "1", "2"),))

    def test_parallel_edges_keep_compact_neighbors_and_full_plug_evidence(self):
        snapshot = SceneSnapshot.build(
            self.nodes,
            (
                SceneEdge("0", "1", source_plug="outA", target_plug="inA"),
                SceneEdge("0", "1", source_plug="outB", target_plug="inB"),
                SceneEdge("0", "2"),
            ),
        )
        graph = GraphIndex(snapshot)
        self.assertEqual(tuple(graph.forward["0"]), ("1", "2"))
        self.assertEqual(graph.unique_edge_count, 2)
        self.assertEqual(graph.edge_multiplicity("0", "1"), 2)
        self.assertEqual(
            tuple(edge.source_plug for edge in graph.edges_between("0", "1")),
            ("outA", "outB"),
        )

    def test_neighborhood_is_bounded_cancellable_and_cached(self):
        graph = GraphIndex(self.snapshot)
        bounded = graph.neighborhood("0", max_edges=2)
        self.assertTrue(bounded.truncated)
        self.assertEqual(bounded.reason, "edge-budget")
        self.assertEqual(bounded.scanned_edges, 2)
        cached = graph.neighborhood("0", max_edges=2)
        self.assertTrue(cached.cache_hit)
        self.assertGreaterEqual(graph.cache_stats()["hits"], 1)
        with self.assertRaises(QueryCancelled):
            graph.neighborhood("0", cancelled=lambda: True)

    def test_query_kernel_keys_object_identity_and_invalidates_snapshot_family(self):
        kernel = QueryKernel(max_indexes=4)
        first = SceneSnapshot.build(self.nodes, (SceneEdge("0", "1"),), snapshot_id="shared")
        second = SceneSnapshot.build(self.nodes, (SceneEdge("0", "2"),), snapshot_id="shared")
        first_index = kernel.index(first)
        self.assertIs(first_index, kernel.index(first))
        second_index = kernel.index(second)
        self.assertIsNot(first_index, second_index)
        self.assertEqual(kernel.stats()["indexes"], 2)
        kernel.invalidate("shared")
        self.assertEqual(kernel.stats()["indexes"], 0)

    def test_query_kernel_alias_requires_shared_verified_edge_tuple(self):
        kernel = QueryKernel(max_indexes=2)
        edges = (SceneEdge("0", "1"),)
        before = SceneSnapshot.build(self.nodes, edges, snapshot_id="before")
        after = SceneSnapshot.build(self.nodes, edges, snapshot_id="after")
        before_index = kernel.index(before)
        self.assertIs(before.edges, after.edges)
        self.assertEqual(kernel.alias(before, after), 1)
        self.assertIs(kernel.index(after), before_index)
        self.assertEqual(kernel.stats()["estimated_bytes"], before_index.estimated_index_bytes)

        copied_edges = tuple(list(edges))
        unsafe = SceneSnapshot.build(self.nodes, copied_edges, snapshot_id="unsafe")
        self.assertIsNot(before.edges, unsafe.edges)
        self.assertEqual(kernel.alias(before, unsafe), 0)

    def test_long_alias_chain_stays_bounded_to_latest_snapshot(self):
        kernel = QueryKernel(max_indexes=2)
        edges = (SceneEdge("0", "1"),)
        current = SceneSnapshot.build(self.nodes, edges, snapshot_id="capture-0")
        first_dg = kernel.index(current)
        first_all = kernel.index(current, ("dg", "dag"))
        for index in range(1, 101):
            following = SceneSnapshot.build(
                current.nodes,
                current.edges,
                snapshot_id="capture-%s" % index,
            )
            self.assertEqual(kernel.alias(current, following), 2)
            current = following
        stats = kernel.stats()
        self.assertEqual(stats["indexes"], 2)
        self.assertEqual(stats["snapshot_ids"], ("capture-100", "capture-100"))
        self.assertEqual(
            stats["estimated_bytes"],
            first_dg.estimated_index_bytes + first_all.estimated_index_bytes,
        )

    def test_index_build_and_ranking_honor_cancellation_without_cache_pollution(self):
        kernel = QueryKernel(max_indexes=2)
        with self.assertRaises(QueryCancelled):
            kernel.index(self.snapshot, cancelled=lambda: True)
        self.assertEqual(kernel.stats()["indexes"], 0)
        graph = kernel.index(self.snapshot)
        with self.assertRaises(QueryCancelled):
            graph.ranked_node_ids(cancelled=lambda: True)

    def test_reference_round_trip_and_schema_one_migration(self):
        reference = SceneReference(
            "assetRN",
            "D:/assets/hero.ma",
            unresolved_path="${ASSET_ROOT}/hero.ma",
            namespace="hero",
            loaded=True,
            node_ids=("0", "1"),
            failed_edit_count=1,
            failed_edit_samples=("setAttr hero:ctrl.tx 2",),
        )
        snapshot = SceneSnapshot.build(self.nodes, self.snapshot.edges, (reference,))
        restored = SceneSnapshot.from_json(snapshot.to_json())
        self.assertEqual(restored.references, (reference,))
        self.assertEqual(restored.summary()["failed_reference_edits"], 1)

        legacy = snapshot.to_dict()
        legacy["schema_version"] = 1
        legacy.pop("references")
        migrated = SceneSnapshot.from_dict(legacy)
        self.assertEqual(migrated.schema_version, 8)
        self.assertEqual(migrated.references, ())
        self.assertEqual(migrated.scene_settings.time_unit, "")

    def test_dangling_reference_membership_is_rejected(self):
        with self.assertRaises(SnapshotValidationError):
            SceneSnapshot.build(
                self.nodes,
                (),
                (SceneReference("assetRN", "asset.ma", node_ids=("missing",)),),
            )


if __name__ == "__main__":
    unittest.main()
