from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from MayaScope.application import SceneCaptureController, SceneCaptureStateError


class CancelledError(RuntimeError):
    pass


class StaleError(RuntimeError):
    pass


def progress(message="读取节点", completed=4, total=12, done=False):
    return SimpleNamespace(
        message=message,
        completed=completed,
        total=total,
        done=done,
    )


class FakeSession:
    def __init__(self, previous_snapshot, outcomes):
        self.previous_snapshot = previous_snapshot
        self.outcomes = list(outcomes)
        self.done = False
        self.cancelled = False
        self.cancel_count = 0
        self.step_count = 0
        self.result = SimpleNamespace(snapshot_id="scene-new")
        self.reuse = SimpleNamespace(
            topology_unchanged=previous_snapshot is not None,
            reused_nodes=3,
            reused_edges=2,
            reused_references=1,
        )

    def cancel(self):
        self.cancel_count += 1
        self.cancelled = True

    def step(self, *, max_items, max_milliseconds):
        self.step_count += 1
        if self.cancelled:
            raise CancelledError("cancelled at safe slice")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        self.done = bool(outcome.done)
        return outcome


class SceneCaptureControllerTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = SimpleNamespace(snapshot_id="scene-A")
        self.sessions = []

        def factory(*, previous_snapshot=None):
            session = FakeSession(
                previous_snapshot,
                (progress(), progress("封存", 1, 1, done=True)),
            )
            self.sessions.append(session)
            return session

        self.controller = SceneCaptureController(
            factory,
            cancelled_errors=(CancelledError,),
            stale_errors=(StaleError,),
        )

    def test_progress_then_completion_returns_snapshot_reuse_and_releases_session(self):
        started = self.controller.start(self.snapshot)
        self.assertEqual(started.kind, "started")
        self.assertTrue(started.locks_workspace)
        update = self.controller.advance(self.snapshot)
        self.assertEqual(
            (update.kind, update.message, update.completed, update.total),
            ("progress", "读取节点", 4, 12),
        )
        completed = self.controller.advance(self.snapshot)
        self.assertEqual(completed.kind, "completed")
        self.assertEqual(completed.snapshot.snapshot_id, "scene-new")
        self.assertIs(completed.previous_snapshot, self.snapshot)
        self.assertTrue(completed.reuse.topology_unchanged)
        self.assertFalse(self.controller.active)

    def test_first_capture_without_previous_snapshot_is_a_valid_generation(self):
        self.controller.start(None)
        self.controller.advance(None)
        event = self.controller.advance(None)
        self.assertEqual(event.kind, "completed")
        self.assertEqual(event.source_snapshot_id, "")
        self.assertIsNone(event.previous_snapshot)

    def test_cancel_is_idempotent_and_partial_snapshot_is_discarded(self):
        self.controller.start(self.snapshot)
        first = self.controller.request_cancel()
        second = self.controller.request_cancel()
        self.assertEqual((first.kind, second.kind), ("cancelling", "cancelling"))
        self.assertEqual(self.sessions[0].cancel_count, 1)
        event = self.controller.advance(self.snapshot)
        self.assertEqual(event.kind, "cancelled")
        self.assertIsNone(event.snapshot)
        self.assertFalse(self.controller.active)

    def test_required_post_change_verification_refuses_interactive_cancel(self):
        self.controller.start(self.snapshot, required=True)
        with self.assertRaisesRegex(SceneCaptureStateError, "cannot be cancelled"):
            self.controller.request_cancel()
        self.assertTrue(self.controller.active)
        self.assertEqual(self.sessions[0].cancel_count, 0)

    def test_generation_change_cancels_before_next_collector_slice(self):
        self.controller.start(self.snapshot)
        session = self.sessions[0]
        event = self.controller.advance(SimpleNamespace(snapshot_id="scene-B"))
        self.assertEqual(event.kind, "stale")
        self.assertEqual(session.step_count, 0)
        self.assertEqual(session.cancel_count, 1)
        self.assertFalse(self.controller.active)

    def test_collector_stale_generic_failure_and_unidentified_result_are_terminal(self):
        def controller_for(outcome):
            return SceneCaptureController(
                lambda **_kwargs: FakeSession(self.snapshot, (outcome,)),
                cancelled_errors=(CancelledError,),
                stale_errors=(StaleError,),
            )

        stale = controller_for(StaleError("topology changed"))
        stale.start(self.snapshot)
        self.assertEqual(stale.advance(self.snapshot).kind, "stale")

        failed = controller_for(RuntimeError("node scan failed"))
        failed.start(self.snapshot)
        event = failed.advance(self.snapshot)
        self.assertEqual(event.kind, "failed")
        self.assertIn("node scan failed", event.error)

        missing = controller_for(progress("done", 1, 1, done=True))
        missing.start(self.snapshot)
        missing._session.result = SimpleNamespace(snapshot_id="")
        event = missing.advance(self.snapshot)
        self.assertEqual(event.kind, "failed")
        self.assertIn("unidentified", event.error)

    def test_abort_cleans_up_once_and_invalid_lifecycle_is_rejected(self):
        with self.assertRaises(SceneCaptureStateError):
            self.controller.advance(self.snapshot)
        self.controller.start(self.snapshot)
        session = self.sessions[0]
        event = self.controller.abort()
        self.assertEqual(event.kind, "cancelled")
        self.assertEqual(session.cancel_count, 1)
        self.assertFalse(self.controller.active)

    def test_application_controller_has_no_qt_maya_collector_or_view_dependency(self):
        source = (
            Path(__file__).resolve().parents[1]
            / "application"
            / "scene_capture.py"
        ).read_text(encoding="utf-8").lower()
        for forbidden in ("pyside", "qtwidgets", "maya.cmds", "collectors", "ui."):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
