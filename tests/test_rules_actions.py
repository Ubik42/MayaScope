from __future__ import annotations

import unittest

from MayaScope.actions import MayaChangeExecutor, plan_for_issue, plan_for_issues
from MayaScope.analysis.rules import (
    DEFAULT_RULES,
    FailedReferenceEditRule,
    HighFanoutRule,
    Issue,
    NamespaceDepthRule,
    NestedReferenceDepthRule,
    OrphanAnimationCurveRule,
    OrphanUtilityRule,
    RuntimeScriptNodeRule,
    Severity,
    UnloadedReferenceRule,
    UnsavedSceneRule,
    analyze_snapshot,
)
from MayaScope.model import SceneEdge, SceneNode, SceneReference, SceneSnapshot


class FakeCmds:
    def __init__(self, nodes, referenced=(), fail_delete=False, identities=None):
        self.nodes = set(nodes)
        self.referenced = set(referenced)
        self.fail_delete = fail_delete
        self.identities = identities or {}
        self.calls = []

    def objExists(self, name):
        return name in self.nodes

    def ls(self, name, uuid=False):
        return [self.identities[name]] if name in self.identities else []

    def referenceQuery(self, name, isNodeReferenced=False):
        return name in self.referenced

    def undoInfo(self, **kwargs):
        self.calls.append(("undoInfo", kwargs))

    def delete(self, names):
        self.calls.append(("delete", tuple(names)))
        if self.fail_delete:
            raise RuntimeError("simulated failure")
        self.nodes.difference_update(names)

    def undo(self):
        self.calls.append(("undo",))


class RuleActionTests(unittest.TestCase):
    def test_every_default_rule_returns_a_sequence_for_an_empty_scene(self):
        snapshot = SceneSnapshot.build((), ())
        for rule in DEFAULT_RULES:
            result = rule.evaluate(snapshot)
            self.assertIsNotNone(result, rule.id)
            self.assertIsInstance(result, (tuple, list), rule.id)

    def test_unknown_nodes_create_local_only_change_plan(self):
        snapshot = SceneSnapshot.build(
            (
                SceneNode("local", "badLocal", "unknown"),
                SceneNode("ref", "asset:bad", "unknown", referenced=True, reference_file="asset.ma"),
            ),
            (),
        )
        issue = analyze_snapshot(snapshot)[0]
        plan = plan_for_issue(issue, snapshot)
        self.assertIsNotNone(plan)
        self.assertEqual(plan.steps[0].node_names, ("badLocal",))

        fake = FakeCmds({"badLocal", "asset:bad"}, referenced={"asset:bad"})
        receipt = MayaChangeExecutor(fake).execute(plan)
        self.assertTrue(receipt.success)
        self.assertTrue(receipt.verified)
        self.assertNotIn("badLocal", fake.nodes)
        self.assertIn("asset:bad", fake.nodes)

    def test_executor_closes_chunk_on_failure(self):
        snapshot = SceneSnapshot.build((SceneNode("x", "bad", "unknown"),), ())
        plan = plan_for_issue(analyze_snapshot(snapshot)[0], snapshot)
        fake = FakeCmds({"bad"}, fail_delete=True)
        receipt = MayaChangeExecutor(fake).execute(plan)
        self.assertFalse(receipt.success)
        self.assertTrue(receipt.rolled_back)
        self.assertEqual(fake.calls[-2], ("undoInfo", {"closeChunk": True}))
        self.assertEqual(fake.calls[-1], ("undo",))

    def test_executor_rejects_stale_identity_before_mutation(self):
        snapshot = SceneSnapshot.build((SceneNode("original-uuid", "bad", "unknown"),), ())
        plan = plan_for_issue(analyze_snapshot(snapshot)[0], snapshot)
        fake = FakeCmds({"bad"}, identities={"bad": "replacement-uuid"})
        receipt = MayaChangeExecutor(fake).execute(plan)
        self.assertFalse(receipt.success)
        self.assertIn("stale", receipt.message)
        self.assertFalse(any(call[0] == "delete" for call in fake.calls))

    def test_executor_rolls_back_when_postcondition_is_not_met(self):
        snapshot = SceneSnapshot.build((SceneNode("x", "bad", "unknown"),), ())
        plan = plan_for_issue(analyze_snapshot(snapshot)[0], snapshot)
        fake = FakeCmds({"bad"})

        def ineffective_delete(names):
            fake.calls.append(("delete", tuple(names)))

        fake.delete = ineffective_delete
        receipt = MayaChangeExecutor(fake).execute(plan)
        self.assertFalse(receipt.success)
        self.assertTrue(receipt.rolled_back)
        self.assertIn("后置条件", receipt.message)
        self.assertEqual(fake.calls[-1], ("undo",))

    def test_cycle_and_fanout_rules(self):
        nodes = tuple(SceneNode(str(index), "n%s" % index, "network") for index in range(5))
        edges = (
            SceneEdge("0", "1"), SceneEdge("1", "0"),
            SceneEdge("0", "2"), SceneEdge("0", "3"), SceneEdge("0", "4"),
        )
        snapshot = SceneSnapshot.build(nodes, edges)
        issues = analyze_snapshot(snapshot, rules=(HighFanoutRule(threshold=3),))
        self.assertEqual(issues[0].rule_id, "high-fanout")
        self.assertEqual(issues[0].evidence[1].value, "4")

    def test_orphan_utility_and_namespace_rules_are_evidence_only(self):
        snapshot = SceneSnapshot.build(
            (
                SceneNode("orphan", "mathResidue", "multiplyDivide"),
                SceneNode("deep", "show:seq:shot:asset:ctrl", "transform", namespace="show:seq:shot:asset"),
            ),
            (),
        )
        issues = analyze_snapshot(snapshot, rules=(OrphanUtilityRule(), NamespaceDepthRule(3)))
        self.assertEqual({item.rule_id for item in issues}, {"orphan-utilities", "namespace-depth"})
        self.assertTrue(all(not item.suggested_action for item in issues))

    def test_reference_publish_and_animation_rules_are_evidence_only(self):
        nodes = (
            SceneNode("script", "sceneBootstrap", "script"),
            SceneNode("curve", "abandonedKeys", "animCurveTL"),
        )
        references = (
            SceneReference("rootRN", "root.ma"),
            SceneReference("midRN", "mid.ma", parent_reference_node="rootRN"),
            SceneReference(
                "leafRN",
                "leaf.ma",
                parent_reference_node="midRN",
                loaded=False,
                failed_edit_count=2,
                failed_edit_samples=("edit one", "edit two"),
            ),
        )
        snapshot = SceneSnapshot.build(nodes, (), references)
        rules = (
            UnloadedReferenceRule(),
            FailedReferenceEditRule(),
            NestedReferenceDepthRule(2),
            UnsavedSceneRule(),
            RuntimeScriptNodeRule(),
            OrphanAnimationCurveRule(),
        )
        issues = analyze_snapshot(snapshot, rules=rules)
        self.assertEqual(
            {issue.rule_id for issue in issues},
            {
                "unloaded-references",
                "failed-reference-edits",
                "nested-reference-depth",
                "unsaved-scene",
                "runtime-script-nodes",
                "orphan-animation-curves",
            },
        )
        self.assertTrue(all(not issue.suggested_action for issue in issues))

    def test_runtime_script_rule_ignores_maya_configuration_nodes(self):
        from MayaScope.analysis.rules import RuntimeScriptNodeRule

        snapshot = SceneSnapshot.build(
            (
                SceneNode("builtin", "uiConfigurationScriptNode", "script"),
                SceneNode("ref-builtin", "hero:sceneConfigurationScriptNode", "script", referenced=True),
                SceneNode("payload", "studioPublishHook", "script"),
            ),
            (),
        )
        issues = RuntimeScriptNodeRule().evaluate(snapshot)
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].affected_node_ids, ("payload",))
        self.assertEqual(issues[0].evidence[0].value, "1")

    def test_batch_plan_deduplicates_nodes_and_executes_one_undo_chunk(self):
        snapshot = SceneSnapshot.build(
            (
                SceneNode("a", "badA", "unknown"),
                SceneNode("b", "badB", "unknown"),
                SceneNode("c", "badC", "unknown"),
            ),
            (),
        )

        def repair_issue(issue_id, node_ids):
            return Issue(
                issue_id,
                "unknown-nodes",
                "Unknown node residue",
                "test",
                Severity.ERROR,
                tuple(node_ids),
                (),
                "delete_unknown_nodes",
            )

        plan = plan_for_issues(
            (repair_issue("issue-a", ("a", "b")), repair_issue("issue-b", ("b", "c"))),
            snapshot,
        )
        self.assertIsNotNone(plan)
        self.assertEqual(plan.issue_ids, ("issue-a", "issue-b"))
        self.assertEqual(plan.steps[0].node_ids, ("a", "b", "c"))
        fake = FakeCmds({"badA", "badB", "badC"})
        receipt = MayaChangeExecutor(fake).execute(plan)
        self.assertTrue(receipt.verified)
        opens = [call for call in fake.calls if call == ("undoInfo", {"openChunk": True, "chunkName": "MayaScope: 场景诊所批量修复 · 2 项发现"})]
        closes = [call for call in fake.calls if call == ("undoInfo", {"closeChunk": True})]
        self.assertEqual(len(opens), 1)
        self.assertEqual(len(closes), 1)
        self.assertEqual(fake.nodes, set())


if __name__ == "__main__":
    unittest.main()
