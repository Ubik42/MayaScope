import unittest

from MayaScope.collectors.maya_selection import MayaSelectionBridge
from MayaScope.model import SceneNode, SceneSnapshot
from MayaScope.ui.workspace import MayaScopeWorkspace


class FakeEventMessage:
    callbacks = {}
    next_id = 1

    @classmethod
    def addEventCallback(cls, event, callback):
        callback_id = cls.next_id
        cls.next_id += 1
        cls.callbacks[callback_id] = (event, callback)
        return callback_id

    @classmethod
    def trigger(cls, event="SelectionChanged"):
        for registered, callback in tuple(cls.callbacks.values()):
            if registered == event:
                callback()


class FakeMessage:
    @classmethod
    def removeCallback(cls, callback_id):
        FakeEventMessage.callbacks.pop(callback_id)


class FakeOpenMaya:
    MEventMessage = FakeEventMessage
    MMessage = FakeMessage


class FakeCmds:
    def __init__(self):
        self.selection = []

    def ls(self, selection=False, long=False):
        return list(self.selection) if selection else []

    def select(self, values=None, replace=False, noExpand=False, clear=False):
        self.selection = [] if clear else list(values or ())
        FakeEventMessage.trigger()


class SelectionBridgeTests(unittest.TestCase):
    def setUp(self):
        FakeEventMessage.callbacks = {}
        FakeEventMessage.next_id = 1
        self.cmds = FakeCmds()
        self.events = []
        self.bridge = MayaSelectionBridge(
            self.events.append, cmds_module=self.cmds, om_module=FakeOpenMaya
        )

    def tearDown(self):
        self.bridge.stop()

    def test_start_is_idempotent_and_stop_removes_owned_callback(self):
        self.cmds.selection = ["|rig|ctrl"]
        self.assertEqual(self.bridge.start(), ("|rig|ctrl",))
        self.assertEqual(self.bridge.start(), ("|rig|ctrl",))
        self.assertEqual(self.events, [("|rig|ctrl",)])
        self.assertEqual(len(FakeEventMessage.callbacks), 1)
        self.assertTrue(self.bridge.stop())
        self.assertFalse(self.bridge.stop())
        self.assertEqual(FakeEventMessage.callbacks, {})

    def test_host_changes_publish_long_names(self):
        self.bridge.start()
        self.events.clear()
        self.cmds.selection = ["|rig|ctrl", "shaderNode", "|rig|ctrl"]
        FakeEventMessage.trigger()
        self.assertEqual(self.events, [("|rig|ctrl", "shaderNode")])

    def test_tool_write_suppresses_echo_but_next_artist_change_survives(self):
        self.bridge.start()
        self.events.clear()
        self.assertEqual(self.bridge.select(("|rig|ctrl",)), ("|rig|ctrl",))
        self.assertEqual(self.events, [])
        self.cmds.selection = ["|rig|hand_ctrl"]
        FakeEventMessage.trigger()
        self.assertEqual(self.events, [("|rig|hand_ctrl",)])

    def test_callback_failure_never_escapes_into_host(self):
        bridge = MayaSelectionBridge(
            lambda _selection: (_ for _ in ()).throw(RuntimeError("boom")),
            cmds_module=self.cmds,
            om_module=FakeOpenMaya,
        )
        bridge.start()
        self.assertEqual(bridge.last_error, "boom")
        bridge.stop()

    def test_start_rolls_back_callback_when_initial_read_fails(self):
        class BrokenCmds(FakeCmds):
            def ls(self, selection=False, long=False):
                raise RuntimeError("selection unavailable")

        bridge = MayaSelectionBridge(
            self.events.append, cmds_module=BrokenCmds(), om_module=FakeOpenMaya
        )
        with self.assertRaisesRegex(RuntimeError, "selection unavailable"):
            bridge.start()
        self.assertFalse(bridge.active)
        self.assertEqual(FakeEventMessage.callbacks, {})

    def test_snapshot_mapping_requires_an_exact_unique_identity(self):
        snapshot = SceneSnapshot.build(
            (
                SceneNode("a", "ctrl", "transform", dag_paths=("|rigA|ctrl",)),
                SceneNode("b", "ctrl", "transform", dag_paths=("|rigB|ctrl",)),
                SceneNode("c", "shader", "lambert"),
            ),
            (),
        )
        mapped = MayaScopeWorkspace._node_ids_for_host_selection(
            snapshot, ("ctrl", "|rigB|ctrl", "shader")
        )
        self.assertEqual(mapped, ("b", "c"))


if __name__ == "__main__":
    unittest.main()
