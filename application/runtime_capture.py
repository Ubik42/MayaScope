"""Host-independent orchestration for time-sliced runtime capture.

The controller owns the volatile capture session and its terminal cleanup.  Qt
only schedules :meth:`advance` and renders the returned semantic event; Maya
collector implementations are injected at the composition root.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, Type


@dataclass(frozen=True)
class RuntimeCaptureEvent:
    """One immutable state transition emitted by a runtime capture."""

    kind: str
    source_snapshot_id: str = ""
    stage: str = ""
    completed: int = 0
    total: int = 0
    runtime: Any = None
    report: Any = None
    error: str = ""

    @property
    def locks_workspace(self) -> bool:
        return self.kind in {"started", "progress", "cancelling"}

    @property
    def terminal(self) -> bool:
        return self.kind in {"cancelled", "stale", "failed", "completed"}


class RuntimeCaptureStateError(RuntimeError):
    """Raised when the caller violates the controller lifecycle."""


class RuntimeCaptureController:
    """Own one capture session from construction through deterministic cleanup."""

    def __init__(
        self,
        session_factory: Callable[[Any], Any],
        analyzer: Callable[[Any, Any], Any],
        *,
        cancelled_errors: Tuple[Type[BaseException], ...] = (),
        stale_errors: Tuple[Type[BaseException], ...] = (),
        max_items: int = 96,
        max_milliseconds: float = 7.0,
    ) -> None:
        if max_items < 1:
            raise ValueError("max_items must be positive")
        if max_milliseconds <= 0:
            raise ValueError("max_milliseconds must be positive")
        self._session_factory = session_factory
        self._analyzer = analyzer
        self._cancelled_errors = cancelled_errors
        self._stale_errors = stale_errors
        self._max_items = max_items
        self._max_milliseconds = max_milliseconds
        self._session: Optional[Any] = None
        self._source_snapshot_id = ""
        self._cancel_requested = False

    @property
    def active(self) -> bool:
        return self._session is not None

    @property
    def cancelling(self) -> bool:
        return self.active and self._cancel_requested

    @property
    def source_snapshot_id(self) -> str:
        return self._source_snapshot_id

    def start(self, snapshot: Any) -> RuntimeCaptureEvent:
        if self.active:
            raise RuntimeCaptureStateError("Runtime capture is already active")
        snapshot_id = str(getattr(snapshot, "snapshot_id", ""))
        if not snapshot_id:
            raise ValueError("Runtime capture requires an identified scene snapshot")
        session = self._session_factory(snapshot)
        self._session = session
        self._source_snapshot_id = snapshot_id
        self._cancel_requested = False
        return RuntimeCaptureEvent("started", source_snapshot_id=snapshot_id)

    def request_cancel(self) -> RuntimeCaptureEvent:
        if not self.active:
            raise RuntimeCaptureStateError("Runtime capture is not active")
        if not self._cancel_requested:
            try:
                self._session.cancel()
            except Exception as exc:
                source_id = self._source_snapshot_id
                self._clear()
                return RuntimeCaptureEvent(
                    "failed", source_snapshot_id=source_id, error=str(exc)
                )
            self._cancel_requested = True
        return RuntimeCaptureEvent(
            "cancelling", source_snapshot_id=self._source_snapshot_id
        )

    def advance(self, snapshot: Any) -> RuntimeCaptureEvent:
        if not self.active:
            raise RuntimeCaptureStateError("Runtime capture is not active")
        current_id = str(getattr(snapshot, "snapshot_id", ""))
        if current_id != self._source_snapshot_id:
            source_id = self._source_snapshot_id
            self._cancel_for_cleanup()
            self._clear()
            return RuntimeCaptureEvent(
                "stale",
                source_snapshot_id=source_id,
                error="Scene snapshot changed before runtime capture completed",
            )

        session = self._session
        try:
            progress = session.step(
                max_items=self._max_items,
                max_milliseconds=self._max_milliseconds,
            )
        except Exception as exc:
            return self._classify_exception(exc)

        event_kind = "cancelling" if self._cancel_requested else "progress"
        if not bool(getattr(session, "done", False)):
            return RuntimeCaptureEvent(
                event_kind,
                source_snapshot_id=self._source_snapshot_id,
                stage=str(getattr(progress, "stage", "")),
                completed=int(getattr(progress, "completed", 0)),
                total=int(getattr(progress, "total", 0)),
            )

        source_id = self._source_snapshot_id
        if self._cancel_requested:
            self._clear()
            return RuntimeCaptureEvent("cancelled", source_snapshot_id=source_id)

        try:
            runtime = session.result
            if str(getattr(runtime, "source_snapshot_id", "")) != source_id:
                self._clear()
                return RuntimeCaptureEvent(
                    "stale",
                    source_snapshot_id=source_id,
                    error="Runtime evidence identity does not match its scene snapshot",
                )
            report = self._analyzer(runtime, snapshot)
        except Exception as exc:
            self._clear()
            return RuntimeCaptureEvent(
                "failed", source_snapshot_id=source_id, error=str(exc)
            )
        self._clear()
        return RuntimeCaptureEvent(
            "completed",
            source_snapshot_id=source_id,
            runtime=runtime,
            report=report,
        )

    def abort(self) -> RuntimeCaptureEvent:
        """Synchronously abandon a session during host shutdown."""

        if not self.active:
            return RuntimeCaptureEvent("cancelled")
        source_id = self._source_snapshot_id
        error = self._cancel_for_cleanup()
        self._clear()
        if error:
            return RuntimeCaptureEvent(
                "failed", source_snapshot_id=source_id, error=error
            )
        return RuntimeCaptureEvent("cancelled", source_snapshot_id=source_id)

    def _classify_exception(self, exc: Exception) -> RuntimeCaptureEvent:
        source_id = self._source_snapshot_id
        cleanup_error = self._cancel_for_cleanup()
        self._clear()
        error = str(exc)
        if cleanup_error and cleanup_error != error:
            error = "%s; cleanup failed: %s" % (error, cleanup_error)
        if self._cancelled_errors and isinstance(exc, self._cancelled_errors):
            return RuntimeCaptureEvent("cancelled", source_snapshot_id=source_id)
        if self._stale_errors and isinstance(exc, self._stale_errors):
            return RuntimeCaptureEvent(
                "stale", source_snapshot_id=source_id, error=error
            )
        return RuntimeCaptureEvent(
            "failed", source_snapshot_id=source_id, error=error
        )

    def _cancel_for_cleanup(self) -> str:
        try:
            self._session.cancel()
        except Exception as exc:
            return str(exc)
        return ""

    def _clear(self) -> None:
        self._session = None
        self._source_snapshot_id = ""
        self._cancel_requested = False


__all__ = [
    "RuntimeCaptureController",
    "RuntimeCaptureEvent",
    "RuntimeCaptureStateError",
]
