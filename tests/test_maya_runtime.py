from __future__ import annotations

import unittest

try:
    import maya.api.OpenMaya as om
    import maya.cmds as cmds
    import maya.standalone as standalone
except ImportError:
    om = cmds = standalone = None


@unittest.skipIf(cmds is None, "Maya runtime unavailable")
class MayaRuntimeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            standalone.initialize(name="python")
        except RuntimeError:
            pass

    def setUp(self):
        cmds.file(new=True, force=True)

    def test_runtime_capture_links_expression_and_observes_opaque_callback(self):
        from MayaScope.collectors import capture_runtime, capture_scene

        cube = cmds.polyCube(name="runtimeCube")[0]
        expression = cmds.expression(
            name="runtimeExpression",
            object=cube,
            string="runtimeCube.translateX = frame;",
            alwaysEvaluate=True,
            unitConversion="none",
        )
        selection = om.MSelectionList()
        selection.add(cube)
        obj = selection.getDependNode(0)
        callback_id = om.MNodeMessage.addAttributeChangedCallback(obj, lambda *args: None)
        try:
            scene = capture_scene()
            runtime = capture_runtime(scene)
        finally:
            om.MMessage.removeCallback(callback_id)
        record = next(item for item in runtime.expressions if item.node_name == expression)
        self.assertTrue(record.always_evaluate)
        self.assertEqual(record.source_length, len("runtimeCube.translateX = frame;"))
        cube_id = next(item.id for item in scene.nodes if item.name == cube)
        self.assertTrue(any(item.node_id == cube_id for item in runtime.node_callbacks))
        self.assertTrue(runtime.batch_mode)
        self.assertFalse(runtime.script_jobs_available)
        self.assertGreater(len(runtime.plugins), 0)

    def test_runtime_capture_is_cancellable_and_rejects_scene_mutation(self):
        from MayaScope.collectors import (
            MayaRuntimeCaptureSession,
            RuntimeCaptureCancelled,
            RuntimeChangedDuringCapture,
            capture_scene,
        )

        cmds.createNode("transform", name="runtimeGuardRoot")
        scene = capture_scene()
        cancelled = MayaRuntimeCaptureSession(scene)
        cancelled.cancel()
        with self.assertRaises(RuntimeCaptureCancelled):
            cancelled.step()

        changed = MayaRuntimeCaptureSession(scene)
        changed.step(max_items=1, max_milliseconds=100.0)
        cmds.createNode("transform", name="runtimeMutation")
        with self.assertRaises(RuntimeChangedDuringCapture):
            while not changed.done:
                changed.step(max_items=64, max_milliseconds=100.0)


if __name__ == "__main__":
    unittest.main()
