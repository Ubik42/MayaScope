"""Host integration test: skipped in CPython, active under mayapy."""

from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

try:
    import maya.cmds as cmds
    import maya.standalone as standalone
except ImportError:
    cmds = None
    standalone = None


@unittest.skipIf(cmds is None, "Maya runtime unavailable")
class MayaCollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            standalone.initialize(name="python")
            cls._owns_runtime = True
        except RuntimeError:
            cls._owns_runtime = False

    @classmethod
    def tearDownClass(cls):
        # A Maya standalone runtime cannot be safely initialized a second time
        # in the same process.  The interpreter owns final cleanup so other
        # integration test classes can reuse this session.
        pass

    def setUp(self):
        cmds.file(new=True, force=True)

    def test_capture_real_dg_and_dag_topology(self):
        from MayaScope.collectors.maya_scene import capture_scene

        parent = cmds.createNode("transform", name="ms_parent")
        child = cmds.createNode("transform", name="ms_child", parent=parent)
        source = cmds.createNode("multiplyDivide", name="ms_source")
        target = cmds.createNode("plusMinusAverage", name="ms_target")
        cmds.connectAttr(source + ".outputX", target + ".input1D[0]")
        cmds.select(child, replace=True)

        snapshot = capture_scene()
        by_name = {node.name: node for node in snapshot.nodes}
        self.assertIn(child, by_name)
        self.assertIn("|ms_parent|ms_child", snapshot.metadata["selection"])
        self.assertTrue(
            any(
                edge.source_id == by_name[source].id
                and edge.target_id == by_name[target].id
                and edge.relation == "dg"
                for edge in snapshot.edges
            )
        )
        self.assertTrue(
            any(
                edge.source_id == by_name[parent].id
                and edge.target_id == by_name[child].id
                and edge.relation == "dag"
                for edge in snapshot.edges
            )
        )

    def test_capture_scene_settings_contract_inputs(self):
        from MayaScope.collectors.maya_scene import capture_scene

        cmds.currentUnit(time="pal", linear="m", angle="rad")
        cmds.upAxis(axis="z", rotateView=False)
        snapshot = capture_scene()
        settings = snapshot.scene_settings
        self.assertEqual(settings.time_unit, "pal")
        self.assertAlmostEqual(settings.frames_per_second, 25.0, places=3)
        self.assertEqual(settings.linear_unit, "m")
        self.assertEqual(settings.angular_unit, "rad")
        self.assertEqual(settings.up_axis, "z")
        self.assertIsInstance(settings.rendering_space, str)

    def test_capture_maya_registered_external_file_dependencies(self):
        from MayaScope.collectors.maya_scene import capture_scene

        with tempfile.TemporaryDirectory(prefix="mayascope-dependencies-") as folder:
            old_workspace = cmds.workspace(query=True, rootDirectory=True)
            try:
                cmds.workspace(folder, openWorkspace=True)
                source_images = Path(folder) / "sourceimages"
                source_images.mkdir(exist_ok=True)
                present = source_images / "present.exr"
                present.write_bytes(b"probe")
                for filename in (
                    "hero.1001.exr", "hero.1002.exr", "plate.0001.exr", "plate.0003.exr"
                ):
                    (source_images / filename).write_bytes(b"probe")
                present_node = cmds.shadingNode("file", asTexture=True, name="presentTexture")
                missing_node = cmds.shadingNode("file", asTexture=True, name="missingTexture")
                udim_node = cmds.shadingNode("file", asTexture=True, name="udimTexture")
                frame_node = cmds.shadingNode("file", asTexture=True, name="frameTexture")
                cmds.setAttr(
                    present_node + ".fileTextureName",
                    str(present).replace("\\", "/"),
                    type="string",
                )
                cmds.setAttr(
                    missing_node + ".fileTextureName",
                    str(source_images / "missing.<UDIM>.exr").replace("\\", "/"),
                    type="string",
                )
                cmds.setAttr(udim_node + ".uvTilingMode", 3)
                cmds.setAttr(
                    udim_node + ".fileTextureName",
                    str(source_images / "hero.<UDIM>.exr").replace("\\", "/"),
                    type="string",
                )
                cmds.setAttr(frame_node + ".useFrameExtension", True)
                cmds.setAttr(
                    frame_node + ".fileTextureName",
                    str(source_images / "plate.0001.exr").replace("\\", "/"),
                    type="string",
                )
                cmds.playbackOptions(minTime=1, maxTime=3)
                snapshot = capture_scene()
            finally:
                cmds.workspace(old_workspace, openWorkspace=True)

        by_name = {item.node_name: item for item in snapshot.external_dependencies}
        self.assertTrue(by_name[present_node].exists)
        self.assertFalse(by_name[missing_node].exists)
        self.assertEqual(by_name[missing_node].kind, "texture")
        self.assertEqual(by_name[missing_node].sequence_pattern.lower(), "<udim>")
        self.assertTrue(by_name[present_node].inside_workspace)
        self.assertTrue(by_name[udim_node].exists)
        self.assertEqual(by_name[udim_node].sequence_kind, "udim")
        self.assertEqual(by_name[udim_node].sequence_member_count, 2)
        self.assertTrue(by_name[frame_node].exists)
        self.assertEqual(by_name[frame_node].sequence_pattern, "####")
        self.assertEqual(by_name[frame_node].sequence_member_count, 2)
        self.assertEqual(by_name[frame_node].sequence_missing_count, 1)
        self.assertEqual(by_name[frame_node].sequence_missing_samples, ("0002",))

    def test_capture_distinguishes_saved_and_dirty_memory_state(self):
        from MayaScope.collectors.maya_scene import capture_scene

        with tempfile.TemporaryDirectory(prefix="mayascope-lifecycle-") as folder:
            scene_path = str(Path(folder) / "lifecycle.ma")
            node = cmds.createNode("transform", name="lifecycle_probe")
            cmds.playbackOptions(
                minTime=101, maxTime=120, animationStartTime=100, animationEndTime=130
            )
            cmds.currentTime(105)
            cmds.file(rename=scene_path)
            cmds.file(save=True, type="mayaAscii", force=True)
            clean = capture_scene()
            cmds.setAttr(node + ".translateX", 2.0)
            dirty = capture_scene(previous_snapshot=clean)

        self.assertFalse(clean.scene_lifecycle.modified)
        self.assertTrue(dirty.scene_lifecycle.modified)
        self.assertEqual(clean.scene_lifecycle.file_type, "mayaAscii")
        self.assertEqual(clean.scene_lifecycle.current_time, 105.0)
        self.assertEqual(clean.scene_lifecycle.playback_min, 101.0)
        self.assertEqual(clean.scene_lifecycle.animation_end, 130.0)

    def test_time_sliced_capture_progresses_and_can_cancel(self):
        from MayaScope.collectors import CaptureCancelled, MayaSceneCaptureSession

        for index in range(24):
            cmds.createNode("transform", name="slice_probe_%02d" % index)
        session = MayaSceneCaptureSession()
        first = session.step(max_items=1, max_milliseconds=100.0)
        self.assertEqual(first.stage, "nodes")
        self.assertFalse(session.done)
        session.cancel()
        with self.assertRaises(CaptureCancelled):
            session.step(max_items=1, max_milliseconds=100.0)

    def test_time_sliced_capture_rejects_topology_mutation(self):
        from MayaScope.collectors import MayaSceneCaptureSession, SceneChangedDuringCapture

        cmds.createNode("transform", name="stable_before_capture")
        session = MayaSceneCaptureSession()
        session.step(max_items=1, max_milliseconds=100.0)
        cmds.createNode("transform", name="mutation_during_capture")
        with self.assertRaises(SceneChangedDuringCapture):
            session.step(max_items=8, max_milliseconds=100.0)

    def test_time_sliced_capture_rejects_host_context_drift(self):
        from MayaScope.collectors import MayaSceneCaptureSession, SceneChangedDuringCapture

        node = cmds.shadingNode("file", asTexture=True, name="context_texture")
        cmds.setAttr(node + ".fileTextureName", "D:/before.exr", type="string")
        session = MayaSceneCaptureSession()
        session.step(max_items=1, max_milliseconds=100.0)
        cmds.setAttr(node + ".fileTextureName", "D:/after.exr", type="string")
        with self.assertRaises(SceneChangedDuringCapture):
            while not session.done:
                session.step(max_items=2048, max_milliseconds=1000.0)

    def test_time_sliced_capture_rejects_scene_setting_drift(self):
        from MayaScope.collectors import MayaSceneCaptureSession, SceneChangedDuringCapture

        original = cmds.currentUnit(query=True, time=True)
        session = MayaSceneCaptureSession()
        session.step(max_items=1, max_milliseconds=100.0)
        try:
            cmds.currentUnit(time="pal" if original != "pal" else "film")
            with self.assertRaises(SceneChangedDuringCapture):
                while not session.done:
                    session.step(max_items=2048, max_milliseconds=1000.0)
        finally:
            cmds.currentUnit(time=original)

    def test_repeat_capture_reuses_immutable_payload_and_detects_rewire(self):
        from MayaScope.collectors import MayaSceneCaptureSession
        from MayaScope.collectors.maya_scene import capture_scene

        source_a = cmds.createNode("multiplyDivide", name="reuse_source_a")
        source_b = cmds.createNode("multiplyDivide", name="reuse_source_b")
        target = cmds.createNode("plusMinusAverage", name="reuse_target")
        cmds.connectAttr(source_a + ".outputX", target + ".input1D[0]")
        first = capture_scene()

        unchanged_session = MayaSceneCaptureSession(previous_snapshot=first)
        while not unchanged_session.done:
            unchanged_session.step(max_items=2048, max_milliseconds=1000.0)
        unchanged = unchanged_session.result
        self.assertTrue(unchanged_session.reuse.topology_unchanged)
        self.assertIs(first.edges, unchanged.edges)
        self.assertGreater(unchanged_session.reuse.reused_nodes, 0)

        cmds.disconnectAttr(source_a + ".outputX", target + ".input1D[0]")
        cmds.connectAttr(source_b + ".outputX", target + ".input1D[0]")
        rewired_session = MayaSceneCaptureSession(previous_snapshot=unchanged)
        while not rewired_session.done:
            rewired_session.step(max_items=2048, max_milliseconds=1000.0)
        self.assertFalse(rewired_session.reuse.topology_unchanged)
        self.assertIsNot(unchanged.edges, rewired_session.result.edges)

    def test_capture_loaded_and_unloaded_file_reference(self):
        from MayaScope.collectors.maya_scene import capture_scene

        with tempfile.TemporaryDirectory(prefix="mayascope-reference-") as folder:
            asset_path = str(Path(folder) / "asset.ma")
            cmds.file(new=True, force=True)
            cmds.createNode("transform", name="assetRoot")
            cmds.file(rename=asset_path)
            cmds.file(save=True, type="mayaAscii", force=True)

            cmds.file(new=True, force=True)
            cmds.file(asset_path, reference=True, namespace="asset")
            reference_node = next(
                node for node in cmds.ls(type="reference") if node != "sharedReferenceNode"
            )
            loaded = capture_scene()
            record = next(item for item in loaded.references if item.reference_node == reference_node)
            self.assertTrue(record.loaded)
            self.assertTrue(record.node_ids)
            self.assertEqual(record.namespace, "asset")
            self.assertTrue(record.failed_edit_scan_complete)

            cmds.file(unloadReference=reference_node)
            unloaded = capture_scene()
            record = next(item for item in unloaded.references if item.reference_node == reference_node)
            self.assertFalse(record.loaded)
            self.assertEqual(record.node_ids, ())

    def test_capture_missing_plugin_registry_and_unknown_node_origin(self):
        from MayaScope.collectors.maya_scene import capture_scene

        fixture = Path(__file__).resolve().parents[1] / "examples" / "unknown-plugin-probe.ma"
        cmds.file(
            str(fixture), open=True, force=True, prompt=False,
            ignoreVersion=True, executeScriptNodes=False,
        )
        snapshot = capture_scene()
        plugin = next(item for item in snapshot.unknown_plugins if item.name == "studioGhostTools")
        self.assertEqual(plugin.version, "4.7")
        self.assertEqual(plugin.node_types, ("studioGhostSolver",))
        node = next(item for item in snapshot.nodes if item.name == "ghostSolver1")
        self.assertEqual(node.type_name, "unknown")
        self.assertEqual(node.metadata["unknown_plugin"], "studioGhostTools")
        self.assertEqual(node.metadata["unknown_real_class"], "studioGhostSolver")

    def test_capture_missing_reference_canonical_path_copy_and_namespace_intruder(self):
        from MayaScope.collectors.maya_scene import capture_scene

        fixture = Path(__file__).resolve().parents[1] / "examples" / "reference-health-probe.ma"
        cmds.file(
            str(fixture), open=True, force=True, prompt=False,
            ignoreVersion=True, executeScriptNodes=False,
        )
        snapshot = capture_scene()
        references = sorted(snapshot.references, key=lambda item: item.reference_node)
        self.assertEqual(len(references), 2)
        self.assertEqual(references[0].canonical_path, references[1].canonical_path)
        self.assertEqual([item.copy_number for item in references], [0, 1])
        self.assertTrue(all(item.exists is False for item in references))
        self.assertTrue(all(not item.loaded for item in references))
        intruder = next(item for item in snapshot.nodes if item.name == "assetA:localIntruder")
        self.assertFalse(intruder.referenced)
        self.assertEqual(intruder.namespace, "assetA")


if __name__ == "__main__":
    unittest.main()
