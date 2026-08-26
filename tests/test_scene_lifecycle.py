from __future__ import annotations

import unittest

from MayaScope.analysis.clinic import DEFAULT_REGISTRY
from MayaScope.analysis.delta import compare_snapshots
from MayaScope.model import SceneLifecycle, SceneSnapshot


class SceneLifecycleTests(unittest.TestCase):
    def test_lifecycle_round_trip_and_delta(self):
        clean = SceneLifecycle(
            modified=False,
            file_type="mayaAscii",
            workspace_root="D:/show/",
            current_time=101.0,
            playback_min=101.0,
            playback_max=120.0,
            animation_start=100.0,
            animation_end=130.0,
        )
        snapshot = SceneSnapshot.build((), (), scene_lifecycle=clean)
        self.assertEqual(SceneSnapshot.from_json(snapshot.to_json()).scene_lifecycle, clean)

        dirty = SceneSnapshot.build(
            (), (), scene_lifecycle=SceneLifecycle(modified=True, file_type="mayaAscii")
        )
        delta = compare_snapshots(snapshot, dirty)
        self.assertIn("modified", delta.lifecycle_changes)
        self.assertGreater(delta.summary()["scene_lifecycle_modified"], 0)
        self.assertFalse(delta.is_empty)

    def test_unsaved_changes_rule_only_reports_explicit_dirty_state(self):
        for modified in (False, None):
            snapshot = SceneSnapshot.build(
                (), (), scene_lifecycle=SceneLifecycle(modified=modified)
            )
            report = DEFAULT_REGISTRY.evaluate(
                snapshot, enabled_rule_ids=("unsaved-scene-changes",)
            )
            self.assertEqual(report.issues, ())

        dirty = SceneSnapshot.build(
            (),
            (),
            source_scene="D:/show/shot.ma",
            scene_lifecycle=SceneLifecycle(
                modified=True,
                file_type="mayaAscii",
                current_time=105.0,
                playback_min=101.0,
                playback_max=120.0,
                animation_start=100.0,
                animation_end=130.0,
            ),
        )
        report = DEFAULT_REGISTRY.evaluate(
            dirty, enabled_rule_ids=("unsaved-scene-changes",)
        )
        self.assertEqual(report.issues[0].title, "场景存在未保存修改")
        self.assertEqual(report.issues[0].affected_node_ids, ())
        self.assertIn("播放范围", {item.label for item in report.issues[0].evidence})


if __name__ == "__main__":
    unittest.main()
