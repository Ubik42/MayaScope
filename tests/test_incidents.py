from __future__ import annotations

import unittest

from MayaScope.analysis.incidents import cluster_issues
from MayaScope.analysis.rules import Issue, Severity
from MayaScope.model import SceneEdge, SceneNode, SceneSnapshot


def issue(issue_id, node_ids, severity=Severity.WARNING):
    return Issue(issue_id, issue_id.split(":")[0], issue_id, "Evidence", severity, tuple(node_ids), ())


class IncidentClusterTests(unittest.TestCase):
    def test_shared_reference_and_direct_causal_scope_cluster_with_evidence(self):
        snapshot = SceneSnapshot.build(
            (
                SceneNode("a", "asset:a", "network", referenced=True, reference_file="asset.ma", namespace="asset"),
                SceneNode("b", "asset:b", "network", referenced=True, reference_file="asset.ma", namespace="asset"),
                SceneNode("c", "localC", "network"),
                SceneNode("d", "localD", "network"),
            ),
            (SceneEdge("b", "c"),),
        )
        incidents = cluster_issues(
            snapshot,
            (
                issue("one:1", ("a",), Severity.ERROR),
                issue("two:1", ("b",)),
                issue("three:1", ("c",)),
                issue("four:1", ("d",)),
            ),
        )
        self.assertEqual(len(incidents), 2)
        clustered = next(item for item in incidents if len(item.issue_ids) == 3)
        self.assertEqual(clustered.severity, Severity.ERROR)
        self.assertEqual(clustered.affected_node_ids, ("a", "b", "c"))
        self.assertIn("引用边界", {item.label for item in clustered.evidence})

    def test_ids_are_stable_across_input_order(self):
        snapshot = SceneSnapshot.build((SceneNode("x", "x", "network"),), ())
        first = issue("a:1", ("x",))
        second = issue("b:1", ("x",))
        self.assertEqual(
            cluster_issues(snapshot, (first, second))[0].id,
            cluster_issues(snapshot, (second, first))[0].id,
        )


if __name__ == "__main__":
    unittest.main()
