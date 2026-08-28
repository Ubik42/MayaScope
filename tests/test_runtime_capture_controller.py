from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

from MayaScope.application import (
    RuntimeCaptureController,
    RuntimeCaptureStateError,
)


class CancelledError(RuntimeError):
    pass


class StaleError(RuntimeError):
    pass


class FakeSession:
    def __init__(self, snapshot, outcomes):
        self.snapshot = snapshot
        self.outcomes = list(outcomes)
        self.done = False
        self.cancelled = False
        self.cancel_count = 0
        self.step_count = 0
        self.result = SimpleNamespace(source_snapshot_id=snapshot.snapshot_id)

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


def progress(stage="callbacks", completed=4, total=12, done=False):
    return SimpleNamespace(
        stage=stage,
        completed=completed,
        total=total,
        done=done,
    )


class RuntimeCaptureControllerTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = SimpleNamespace(snapshot_id="scene-A")
        self.sessions = []

        def factory(snapshot):
            session = FakeSession(
                snapshot,
                (progress(), progress("done", 1, 1, done=True)),
            )
            self.sessions.append(session)
            return session

        self.controller = RuntimeCaptureController(
            factory,
            lambda runtime, scene: SimpleNamespace(
                runtime_id=id(runtime), source_snapshot_id=scene.snapshot_id
            ),
            cancelled_errors=(CancelledError,),
            stale_errors=(StaleError,),
        )

    def test_progress_then_completion_releases_session_and_returns_evidence(self):
        started = self.controller.start(self.snapshot)
        self.assertEqual(started.kind, "started")
        self.assertTrue(started.locks_workspace)

        update = self.controller.advance(self.snapshot)
        self.assertEqual(update.kind, "progress")
        self.assertEqual((update.stage, update.completed, update.total), ("callbacks", 4, 12))

        completed = self.controller.advance(self.snapshot)
        self.assertEqual(completed.kind, "completed")
        self.assertTrue(completed.terminal)
        self.assertEqual(completed.runtime.source_snapshot_id, "scene-A")
        self.assertEqual(completed.report.source_snapshot_id, "scene-A")
        self.assertFalse(self.controller.active)

    def test_cancel_is_idempotent_and_discards_partial_evidence(self):
        self.controller.start(self.snapshot)
        first = self.controller.request_cancel()
        second = self.controller.request_cancel()
        self.assertEqual((first.kind, second.kind), ("cancelling", "cancelling"))
        self.assertEqual(self.sessions[0].cancel_count, 1)

        event = self.controller.advance(self.snapshot)
        self.assertEqual(event.kind, "cancelled")
        self.assertFalse(self.controller.active)

    def test_scene_identity_change_cancels_before_the_next_slice(self):
        self.controller.start(self.snapshot)
        session = self.sessions[0]
        event = self.controller.advance(SimpleNamespace(snapshot_id="scene-B"))
        self.assertEqual(event.kind, "stale")
        self.assertEqual(session.step_count, 0)
        self.assertEqual(session.cancel_count, 1)
        self.assertFalse(self.controller.active)

    def test_collector_stale_and_generic_failures_are_terminal(self):
        def controller_for(outcome):
            return RuntimeCaptureController(
                lambda snapshot: FakeSession(snapshot, (outcome,)),
                lambda runtime, scene: object(),
                cancelled_errors=(CancelledError,),
                stale_errors=(StaleError,),
            )

        stale = controller_for(StaleError("topology changed"))
        stale.start(self.snapshot)
        self.assertEqual(stale.advance(self.snapshot).kind, "stale")
        self.assertFalse(stale.active)

        failed = controller_for(RuntimeError("callback scan failed"))
        failed.start(self.snapshot)
        event = failed.advance(self.snapshot)
        self.assertEqual(event.kind, "failed")
        self.assertIn("callback scan failed", event.error)
        self.assertFalse(failed.active)

    def test_step_failure_attempts_collector_cleanup(self):
        sessions = []

        def factory(snapshot):
            session = FakeSession(snapshot, (RuntimeError("slice failed"),))
            sessions.append(session)
            return session

        controller = RuntimeCaptureController(factory, lambda runtime, scene: object())
        controller.start(self.snapshot)
        self.assertEqual(controller.advance(self.snapshot).kind, "failed")
        self.assertEqual(sessions[0].cancel_count, 1)

    def test_mismatched_runtime_identity_is_rejected_before_analysis(self):
        analyzed = []

        def factory(snapshot):
            session = FakeSession(snapshot, (progress("done", 1, 1, done=True),))
            session.result = SimpleNamespace(source_snapshot_id="another-scene")
            return session

        controller = RuntimeCaptureController(
            factory, lambda runtime, scene: analyzed.append(runtime)
        )
        controller.start(self.snapshot)
        event = controller.advance(self.snapshot)
        self.assertEqual(event.kind, "stale")
        self.assertEqual(analyzed, [])
        self.assertFalse(controller.active)

    def test_analyzer_failure_releases_session(self):
        controller = RuntimeCaptureController(
            lambda snapshot: FakeSession(
                snapshot, (progress("done", 1, 1, done=True),)
            ),
            lambda runtime, scene: (_ for _ in ()).throw(ValueError("bad evidence")),
        )
        controller.start(self.snapshot)
        event = controller.advance(self.snapshot)
        self.assertEqual(event.kind, "failed")
        self.assertIn("bad evidence", event.error)
        self.assertFalse(controller.active)

    def test_abort_cleans_up_once_and_invalid_lifecycle_is_rejected(self):
        with self.assertRaises(RuntimeCaptureStateError):
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
            / "runtime_capture.py"
        ).read_text(encoding="utf-8").lower()
        for forbidden in ("pyside", "qtwidgets", "maya.cmds", "collectors", "ui."):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
