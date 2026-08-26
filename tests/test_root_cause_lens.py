from __future__ import annotations

import unittest

from MayaScope.analysis.lens import build_root_cause_report
from MayaScope.analysis.rules import Evidence, Issue, Severity
from MayaScope.model import SceneEdge, SceneNode, SceneSnapshot


class RootCauseLensTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = SceneSnapshot.build(
            (
                SceneNode("script", "hiddenDriver", "expression"),
                SceneNode("matrix", "spaceMatrix", "multMatrix"),
                SceneNode("branch", "sharedDriver", "network"),
                SceneNode("focus", "slowControl", "transform"),
                SceneNode("other", "otherControl", "transform"),
                SceneNode("result", "outputJoint", "joint"),
            ),
            (
                SceneEdge("script", "matrix", source_plug="hiddenDriver.output", target_plug="spaceMatrix.input"),
                SceneEdge("matrix", "branch"),
                SceneEdge("branch", "focus", source_plug="sharedDriver.out", target_plug="slowControl.tx"),
                SceneEdge("branch", "other"),
                SceneEdge("focus", "result"),
            ),
        )
        self.issue = Issue(
            id="runtime:script",
            rule_id="runtime",
            title="Runtime driver",
            description="Expression on the path",
            severity=Severity.WARNING,
            affected_node_ids=("script",),
            evidence=(Evidence("kind", "expression"),),
        )

    def test_upstream_candidates_are_ranked_and_explainable(self):
        report = build_root_cause_report(
            self.snapshot, "focus", issues=(self.issue,), max_depth=4
        )
        self.assertEqual(report.direction, "upstream")
        self.assertEqual(report.scope_node_ids, ("focus", "branch", "matrix", "script"))
        self.assertEqual(report.candidates[0].node_id, "branch")
        script = next(item for item in report.candidates if item.node_id == "script")
        self.assertEqual(script.path_node_ids, ("script", "matrix", "branch", "focus"))
        self.assertEqual(script.path_links[0].source_plug, "hiddenDriver.output")
        self.assertTrue(any("运行时代码" in reason for reason in script.reasons))
        self.assertTrue(any(item.label == "问题证据" for item in script.evidence))

    def test_downstream_mode_reports_impact_path(self):
        report = build_root_cause_report(
            self.snapshot, "branch", direction="downstream", max_depth=2
        )
        candidates = {item.node_id: item for item in report.candidates}
        self.assertEqual(candidates["result"].path_node_ids, ("branch", "focus", "result"))

    def test_parallel_plugs_and_intermediate_reference_boundary_are_evidence(self):
        snapshot = SceneSnapshot.build(
            (
                SceneNode("source", "source", "network"),
                SceneNode("reference", "asset:driver", "network", referenced=True, reference_file="asset.ma"),
                SceneNode("focus", "focus", "transform"),
            ),
            (
                SceneEdge("source", "reference", source_plug="source.a", target_plug="asset:driver.a"),
                SceneEdge("source", "reference", source_plug="source.b", target_plug="asset:driver.b"),
                SceneEdge("reference", "focus"),
            ),
        )
        report = build_root_cause_report(snapshot, "focus")
        source = next(item for item in report.candidates if item.node_id == "source")
        self.assertEqual(len(source.path_links), 3)
        self.assertTrue(any("引用边界" in reason for reason in source.reasons))

    def test_scope_limit_is_explicit(self):
        report = build_root_cause_report(
            self.snapshot, "focus", max_depth=4, scope_limit=2
        )
        self.assertTrue(report.truncated)
        self.assertEqual(len(report.scope_node_ids), 2)

    def test_invalid_focus_and_direction_fail_fast(self):
        with self.assertRaises(KeyError):
            build_root_cause_report(self.snapshot, "missing")
        with self.assertRaises(ValueError):
            build_root_cause_report(self.snapshot, "focus", direction="sideways")


if __name__ == "__main__":
    unittest.main()
