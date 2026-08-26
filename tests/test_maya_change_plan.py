"""Maya 2025 integration test for verified ChangePlan and Undo recovery."""

from __future__ import annotations

import unittest

try:
    import maya.cmds as cmds
    import maya.standalone as standalone
except ImportError:
    cmds = None
    standalone = None


@unittest.skipIf(cmds is None, "Maya runtime unavailable")
class MayaChangePlanIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            standalone.initialize(name="python")
        except RuntimeError:
            pass

    def setUp(self):
        cmds.file(new=True, force=True)

    def test_verified_delete_has_exact_undo_head_and_restores(self):
        from MayaScope.actions.change_plan import ChangePlan, ChangeStep, MayaChangeExecutor

        node = cmds.createNode("transform", name="clinicDisposable")
        node_id = cmds.ls(node, uuid=True)[0]
        plan = ChangePlan(
            id="maya-integration-plan",
            title="Remove disposable probe",
            issue_id="integration",
            steps=(ChangeStep("delete_nodes", (node_id,), (node,), "Integration verification"),),
            destructive=True,
        )
        receipt = MayaChangeExecutor(cmds).execute(plan)
        self.assertTrue(receipt.success)
        self.assertTrue(receipt.verified)
        self.assertFalse(cmds.objExists(node))
        self.assertEqual(cmds.undoInfo(query=True, undoName=True), "MayaScope: Remove disposable probe")
        cmds.undo()
        self.assertTrue(cmds.objExists(node))


if __name__ == "__main__":
    unittest.main()
