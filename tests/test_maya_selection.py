"""Real Maya callback contract for the bidirectional selection bridge."""

import unittest

try:
    import maya.cmds as cmds
    import maya.standalone as standalone
except ImportError:
    cmds = None
    standalone = None


@unittest.skipIf(cmds is None, "Maya runtime unavailable")
class MayaSelectionBridgeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            standalone.initialize(name="python")
        except RuntimeError:
            pass

    def setUp(self):
        cmds.file(new=True, force=True)

    def test_real_selection_event_is_observed_and_callback_is_removed(self):
        from MayaScope.collectors import MayaSelectionBridge

        first = cmds.createNode("transform", name="ms_first")
        second = cmds.createNode("transform", name="ms_second")
        events = []
        bridge = MayaSelectionBridge(events.append)
        bridge.start()
        events.clear()

        bridge.select(("|ms_first",))
        self.assertEqual(cmds.ls(selection=True, long=True), ["|ms_first"])
        self.assertEqual(events, [])

        cmds.select(second, replace=True)
        self.assertEqual(events[-1], ("|ms_second",))
        bridge.stop()
        count = len(events)
        cmds.select(first, replace=True)
        self.assertEqual(len(events), count)


if __name__ == "__main__":
    unittest.main()
