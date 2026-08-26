from __future__ import annotations

import time
import tempfile
import unittest
from pathlib import Path

from MayaScope.analysis.graph import GraphIndex
from MayaScope.analysis.incidents import cluster_issues
from MayaScope.analysis.lens import build_root_cause_report
from MayaScope.analysis.rules import (
    Issue, MissingPluginRequirementRule, ReferenceNamespaceIntrusionRule, Severity,
)
from MayaScope.analysis.counterfactual import ExperimentObservation, build_counterfactual_report
from MayaScope.collectors.dependency_sequences import inspect_local_sequence
from MayaScope.model import SceneEdge, SceneNode, SceneReference, SceneSnapshot, UnknownPlugin


class GraphPerformanceContract(unittest.TestCase):
    def test_large_dependency_directory_stops_at_explicit_budget(self):
        with tempfile.TemporaryDirectory(prefix="mayascope-sequence-scale-") as folder:
            root = Path(folder)
            for index in range(5_000):
                (root / ("unrelated_%05d.dat" % index)).touch()
            started = time.perf_counter()
            result = inspect_local_sequence(
                str(root / "cache.####.abc"),
                "####",
                path_kind="absolute",
                max_entries=256,
                max_seconds=0.5,
            )
            elapsed = time.perf_counter() - started
        self.assertFalse(result.scan_complete)
        self.assertEqual(result.scan_reason, "entry-budget-exceeded")
        self.assertLess(elapsed, 0.5, "bounded directory scan took %.3fs" % elapsed)

    def test_five_thousand_reference_namespaces_do_not_cross_multiply_nodes(self):
        size = 5_000
        references = tuple(
            SceneReference(
                "asset%05dRN" % index,
                "D:/assets/asset%05d.ma" % index,
                namespace="asset%05d" % index,
            )
            for index in range(size)
        )
        nodes = tuple(
            SceneNode(
                "node-%05d" % index,
                "asset%05d:localIntruder" % index,
                "transform",
                namespace="asset%05d" % index,
            )
            for index in range(size)
        )
        snapshot = SceneSnapshot.build(nodes, (), references)
        started = time.perf_counter()
        issues = ReferenceNamespaceIntrusionRule().evaluate(snapshot)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(issues[0].affected_node_ids), size)
        self.assertLess(elapsed, 2.0, "5k reference namespace analysis took %.3fs" % elapsed)

    def test_five_thousand_missing_plugin_requirements_remain_linear(self):
        plugins = tuple(
            UnknownPlugin("missingPlugin%05d" % index, "1.0", ("nodeType%05d" % index,), ())
            for index in range(5_000)
        )
        snapshot = SceneSnapshot.build((), (), unknown_plugins=plugins)
        started = time.perf_counter()
        issues = MissingPluginRequirementRule().evaluate(snapshot)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(issues), 1)
        self.assertEqual(len(issues[0].atomic_subjects), 5_000)
        self.assertLess(elapsed, 2.0, "5k missing plug-in analysis took %.3fs" % elapsed)

    def test_two_hundred_pair_counterfactual_bootstrap_is_interactive(self):
        observations = []
        for pair in range(200):
            baseline = 10_000 + (pair % 11) * 17
            variant = 8_000 + (pair % 7) * 13
            order = ("baseline", "variant") if pair % 2 == 0 else ("variant", "baseline")
            values = {"baseline": baseline, "variant": variant}
            for order_index, condition in enumerate(order):
                observations.append(
                    ExperimentObservation(
                        pair,
                        condition,
                        order_index,
                        values[condition],
                        values[condition] - 100,
                        10,
                    )
                )
        started = time.perf_counter()
        report = build_counterfactual_report(
            observations,
            target_node_id="target",
            target_name="target",
            attribute="nodeState",
            baseline_value=0,
            variant_value=1,
        )
        elapsed = time.perf_counter() - started
        self.assertEqual(report.pair_count, 200)
        self.assertEqual(report.verdict, "improved")
        self.assertLess(elapsed, 2.0, "200-pair bootstrap took %.3fs" % elapsed)

    def test_ten_thousand_node_chain_indexes_without_recursion(self):
        size = 10_000
        nodes = tuple(SceneNode(str(i), "n%s" % i, "network") for i in range(size))
        edges = tuple(SceneEdge(str(i), str(i + 1)) for i in range(size - 1))
        started = time.perf_counter()
        graph = GraphIndex(SceneSnapshot.build(nodes, edges))
        components = graph.strongly_connected_components()
        elapsed = time.perf_counter() - started
        self.assertEqual(components, ())
        # Generous CI contract: catches accidental quadratic/recursive rewrites.
        self.assertLess(elapsed, 5.0, "10k-node graph analysis took %.3fs" % elapsed)

    def test_root_cause_lens_reuses_bfs_layers(self):
        size = 10_000
        nodes = tuple(SceneNode(str(i), "n%s" % i, "network") for i in range(size))
        edges = tuple(SceneEdge(str(i), str(i + 1)) for i in range(size - 1))
        snapshot = SceneSnapshot.build(nodes, edges)
        started = time.perf_counter()
        report = build_root_cause_report(
            snapshot,
            str(size - 1),
            max_depth=500,
            scope_limit=300,
            candidate_limit=6,
        )
        elapsed = time.perf_counter() - started
        self.assertEqual(len(report.candidates), 6)
        self.assertEqual(report.candidates[0].distance, 1)
        self.assertLess(elapsed, 2.0, "10k-node Root Cause Lens took %.3fs" % elapsed)

    def test_thousand_incidents_on_ten_thousand_nodes_remains_linearish(self):
        nodes = tuple(SceneNode(str(index), "n%s" % index, "network") for index in range(10_000))
        edges = tuple(SceneEdge(str(index), str(index + 1)) for index in range(9_999))
        snapshot = SceneSnapshot.build(nodes, edges)
        issues = tuple(
            Issue(
                "perf:%s" % index,
                "perf",
                "Finding %s" % index,
                "Synthetic performance contract",
                Severity.WARNING,
                (str(index * 10),),
                (),
            )
            for index in range(1_000)
        )
        started = time.perf_counter()
        incidents = cluster_issues(snapshot, issues)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(incidents), 1_000)
        self.assertLess(elapsed, 1.5, "10k-node Incident clustering took %.3fs" % elapsed)


if __name__ == "__main__":
    unittest.main()
