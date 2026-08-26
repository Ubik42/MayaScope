from __future__ import annotations

import unittest

from MayaScope.analysis.clinic import DEFAULT_REGISTRY
from MayaScope.analysis.delta import compare_snapshots
from MayaScope.model import ExternalDependency, SceneNode, SceneSnapshot, SnapshotValidationError


def dependency(
    dependency_id="external:a",
    *,
    raw_path="sourceimages/hero.<UDIM>.exr",
    resolved_path="D:/show/sourceimages/hero.<UDIM>.exr",
    exists=True,
    path_kind="workspace-relative",
    inside_workspace=True,
):
    return ExternalDependency(
        dependency_id,
        "node-a",
        "heroTexture",
        "file",
        "heroTexture.fileTextureName",
        "texture",
        raw_path,
        resolved_path,
        exists,
        path_kind,
        inside_workspace,
        "<UDIM>",
    )


class ExternalDependencyTests(unittest.TestCase):
    def snapshot(self, dependencies):
        return SceneSnapshot.build(
            (SceneNode("node-a", "heroTexture", "file"),),
            (),
            external_dependencies=dependencies,
        )

    def test_round_trip_validation_and_summary(self):
        snapshot = self.snapshot((dependency(exists=False),))
        restored = SceneSnapshot.from_json(snapshot.to_json())
        self.assertEqual(restored.external_dependencies, snapshot.external_dependencies)
        self.assertEqual(restored.summary()["external_dependencies"], 1)
        self.assertEqual(restored.summary()["missing_external_dependencies"], 1)

        with self.assertRaises(SnapshotValidationError):
            SceneSnapshot.build((), (), external_dependencies=(dependency(),))
        with self.assertRaises(SnapshotValidationError):
            self.snapshot((dependency(), dependency()))

    def test_missing_and_nonportable_rules_are_evidence_first(self):
        snapshot = self.snapshot(
            (
                dependency(exists=False),
                dependency(
                    "external:b",
                    raw_path="//server/show/cache/hero.abc",
                    resolved_path="//server/show/cache/hero.abc",
                    path_kind="network",
                    inside_workspace=False,
                ),
            )
        )
        report = DEFAULT_REGISTRY.evaluate(
            snapshot,
            enabled_rule_ids=("missing-external-files", "nonportable-external-files"),
        )
        self.assertEqual({issue.rule_id for issue in report.issues}, {
            "missing-external-files", "nonportable-external-files"
        })
        self.assertTrue(all(issue.affected_node_ids == ("node-a",) for issue in report.issues))
        self.assertIn("路径样例", {item.label for issue in report.issues for item in issue.evidence})

    def test_dependency_delta_tracks_attribute_identity(self):
        before = self.snapshot((dependency(),))
        after = self.snapshot(
            (
                dependency(
                    raw_path="sourceimages/hero_v2.<UDIM>.exr",
                    resolved_path="D:/show/sourceimages/hero_v2.<UDIM>.exr",
                ),
            )
        )
        delta = compare_snapshots(before, after)
        self.assertEqual(len(delta.external_dependency_changes), 1)
        change = delta.external_dependency_changes[0]
        self.assertEqual(change.kind, "modified")
        self.assertIn("raw_path", change.changed_fields)
        self.assertIn("node-a", delta.changed_node_ids)


if __name__ == "__main__":
    unittest.main()
