"""Maya 2025 Profiler integration test; skipped in ordinary Python."""

from __future__ import annotations

import unittest

try:
    import maya.cmds as cmds
    import maya.standalone as standalone
except ImportError:
    cmds = None
    standalone = None


@unittest.skipIf(cmds is None, "Maya runtime unavailable")
class MayaProfilerIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            standalone.initialize(name="python")
            cls._owns_runtime = True
        except RuntimeError:
            cls._owns_runtime = False

    @classmethod
    def tearDownClass(cls):
        # Keep the process-wide runtime alive for the remaining integration
        # suite; Maya does not support a reliable initialize/uninitialize cycle.
        pass

    def setUp(self):
        cmds.file(new=True, force=True)

    def test_profile_operation_exports_events_and_restores_sampling(self):
        from MayaScope.collectors import capture_scene, profile_callable

        cube = cmds.polyCube(name="pulseCube")[0]
        snapshot = capture_scene()

        def operation():
            cmds.setAttr(cube + ".translateX", 2.0)
            cmds.currentTime(2)
            cmds.dgdirty(allPlugs=True)
            cmds.refresh(force=True)
            return "profiled"

        profiled = profile_callable(operation, snapshot=snapshot, buffer_size=50_000)
        self.assertEqual(profiled.result, "profiled")
        self.assertGreater(len(profiled.capture.events), 0)
        self.assertEqual(profiled.capture.maya_version, "2025")
        self.assertEqual(profiled.capture.source_snapshot_id, snapshot.snapshot_id)
        self.assertFalse(cmds.profiler(query=True, sampling=True))
        self.assertGreater(profiled.capture.mapped_event_count, 0)

    def test_evaluation_benchmark_collects_bounded_wall_clock_samples(self):
        from MayaScope.collectors import collect_evaluation_performance

        cmds.polySphere(name="regressionSphere", subdivisionsX=32, subdivisionsY=24)
        original_time = cmds.currentTime(query=True)
        result = collect_evaluation_performance(sample_count=5, warmup_count=1)
        self.assertEqual(result["sample_count"], 5)
        self.assertEqual(len(result["samples_us"]), 5)
        self.assertGreaterEqual(result["median_us"], 0)
        self.assertTrue(result["evaluation_mode"])
        self.assertTrue(result["time_restored"])
        self.assertEqual(cmds.currentTime(query=True), original_time)

    def test_node_state_counterfactual_restores_state_and_undo_head(self):
        from MayaScope.collectors import (
            MayaNodeStateExperiment,
            capture_scene,
            plan_node_state_experiment,
        )

        mesh = cmds.polyPlane(name="counterfactualPlane", subdivisionsX=30, subdivisionsY=30)[0]
        created = cmds.nonLinear(mesh, type="bend", name="counterfactualBend")
        deformer = next(node for node in created if cmds.nodeType(node) == "nonLinear")
        snapshot = capture_scene()
        node = next(item for item in snapshot.nodes if item.name == deformer)
        plan = plan_node_state_experiment(
            snapshot, node.id, pair_count=2, warmup_count=0
        )
        undo_before = str(cmds.undoInfo(query=True, undoName=True) or "")
        run = MayaNodeStateExperiment(snapshot, plan, buffer_size=75_000).run()

        self.assertEqual(cmds.getAttr(deformer + ".nodeState"), 0)
        self.assertEqual(str(cmds.undoInfo(query=True, undoName=True) or ""), undo_before)
        self.assertFalse(cmds.profiler(query=True, sampling=True))
        self.assertEqual(run.report.pair_count, 2)
        self.assertEqual(len(run.baseline_captures), 2)
        self.assertEqual(len(run.variant_captures), 2)
        self.assertTrue(run.report.metadata["state_restored"])

        def cancel_after_first_sample(completed, total, condition):
            raise RuntimeError("cancel probe")

        with self.assertRaisesRegex(RuntimeError, "cancel probe"):
            MayaNodeStateExperiment(
                snapshot,
                plan,
                buffer_size=75_000,
                progress=cancel_after_first_sample,
            ).run()
        self.assertEqual(cmds.getAttr(deformer + ".nodeState"), 0)
        self.assertEqual(str(cmds.undoInfo(query=True, undoName=True) or ""), undo_before)
        self.assertFalse(cmds.profiler(query=True, sampling=True))


if __name__ == "__main__":
    unittest.main()
