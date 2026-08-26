from __future__ import annotations

import unittest

from MayaScope.analysis.runtime import analyze_runtime
from MayaScope.collectors.maya_runtime import parse_script_job
from MayaScope.model import (
    RuntimeExpression,
    RuntimeNodeCallbacks,
    RuntimePlugin,
    RuntimeSnapshot,
    SceneNode,
    SceneSnapshot,
)


class RuntimeTests(unittest.TestCase):
    def test_script_job_parser_extracts_identity_trigger_and_lifetime(self):
        job = parse_script_job('42: -e "SelectionChanged" -protected -killWithScene python("work()")')
        self.assertEqual(job.job_id, 42)
        self.assertEqual(job.trigger_kind, "event")
        self.assertEqual(job.trigger, "SelectionChanged")
        self.assertTrue(job.protected)
        self.assertTrue(job.kill_with_scene)
        self.assertEqual(len(job.descriptor_sha256), 64)

    def test_runtime_snapshot_round_trip(self):
        runtime = RuntimeSnapshot(
            source_snapshot_id="scene-a",
            script_jobs=(),
            expressions=(RuntimeExpression("node-a", "expr", "cube", True, "none", "a" * 64, 5, "x=1"),),
            plugins=(RuntimePlugin("plug", "p", "Vendor", "1", "20250000", False, True),),
            node_callbacks=(RuntimeNodeCallbacks("node-a", "expr", 2),),
            script_jobs_available=False,
            batch_mode=True,
            maya_version="2025",
        )
        self.assertEqual(RuntimeSnapshot.from_dict(runtime.to_dict()), runtime)

    def test_runtime_analysis_preserves_attribution_boundary(self):
        scene = SceneSnapshot(nodes=(SceneNode("node-a", "expr", "expression"),), edges=(), snapshot_id="scene-a")
        runtime = RuntimeSnapshot(
            source_snapshot_id="scene-a",
            script_jobs=(),
            expressions=(RuntimeExpression("node-a", "expr", "cube", True, "none", "a" * 64, 8, "cube.tx"),),
            plugins=(RuntimePlugin("studioPlug", "p", "Studio", "1", "20250000", True, False),),
            node_callbacks=(RuntimeNodeCallbacks("node-a", "expr", 9),),
            script_jobs_available=False,
            batch_mode=True,
            maya_version="2025",
        )
        report = analyze_runtime(runtime, scene)
        ids = {item.rule_id for item in report.issues}
        self.assertEqual(ids, {"runtime-expressions", "runtime-node-callbacks", "runtime-third-party-plugins"})
        callback = next(item for item in report.issues if item.rule_id == "runtime-node-callbacks")
        self.assertIn("不能据此归因", callback.description)
        self.assertIn("无法获取 scriptJob 清单", report.limitations[-1])


if __name__ == "__main__":
    unittest.main()
