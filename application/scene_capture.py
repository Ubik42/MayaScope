"""Host-independent orchestration for time-sliced scene capture.

The controller owns the volatile collector session, validates that its source
scene generation is still current, and guarantees terminal cleanup.  Maya and
Qt implementations are injected at the composition root.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional, Tuple, Type


@dataclass(frozen=True)
class SceneCaptureEvent:
    """One immutable transition emitted by a scene capture session."""

    kind: str
    source_snapshot_id: str = ""
    required: bool = False
    message: str = ""
    completed: int = 0
    total: int = 0
    snapshot: Any = None
    previous_snapshot: Any = None
    reuse: Any = None
    error: str = ""

    @property
    def locks_workspace(self) -> bool:
        return self.kind in {"started", "progress", "cancelling"}

    @property
    def terminal(self) -> bool:
        return self.kind in {"cancelled", "stale", "failed", "completed"}


class SceneCaptureStateError(RuntimeError):
    """Raised when a caller violates the scene capture lifecycle."""


class SceneCaptureController:
    """Own one scene collector from start through deterministic cleanup."""

    def __init__(
        self,
        session_factory: Callable[..., Any],
        *,
        cancelled_errors: Tuple[Type[BaseException], ...] = (),
        stale_errors: Tuple[Type[BaseException], ...] = (),
        max_items: int = 192,
        max_milliseconds: float = 7.0,
    ) -> None:
        if max_items < 1:
            raise ValueError("max_items must be positive")
        if max_milliseconds <= 0:
            raise ValueError("max_milliseconds must be positive")
        self._session_factory = session_factory
        self._cancelled_errors = cancelled_errors
        self._stale_errors = stale_errors
        self._max_items = max_items
        self._max_milliseconds = max_milliseconds
        self._session: Optional[Any] = None
        self._previous_snapshot: Optional[Any] = None
        self._source_snapshot_id = ""
        self._required = False
        self._cancel_requested = False

    @property
    def active(self) -> bool:
        return self._session is not None

    @property
    def cancelling(self) -> bool:
        return self.active and self._cancel_requested

    @property
    def required(self) -> bool:
        return self.active and self._required

    @property
    def source_snapshot_id(self) -> str:
        return self._source_snapshot_id

    def start(
        self, previous_snapshot: Any = None, *, required: bool = False
    ) -> SceneCaptureEvent:
        if self.active:
            raise SceneCaptureStateError("Scene capture is already active")
        source_id = str(getattr(previous_snapshot, "snapshot_id", ""))
        if previous_snapshot is not None and not source_id:
            raise ValueError("Previous scene snapshot must have an identity")
        session = self._session_factory(previous_snapshot=previous_snapshot)
        self._session = session
        self._previous_snapshot = previous_snapshot
        self._source_snapshot_id = source_id
        self._required = bool(required)
        self._cancel_requested = False
        return SceneCaptureEvent(
            "started", source_snapshot_id=source_id, required=self._required
        )

    def request_cancel(self) -> SceneCaptureEvent:
        if not self.active:
            raise SceneCaptureStateError("Scene capture is not active")
        if self._required:
            raise SceneCaptureStateError(
                "Required post-change verification cannot be cancelled"
            )
        if not self._cancel_requested:
            try:
                self._session.cancel()
            except Exception as exc:
                source_id = self._source_snapshot_id
                self._clear()
                return SceneCaptureEvent(
                    "failed", source_snapshot_id=source_id, error=str(exc)
                )
            self._cancel_requested = True
        return SceneCaptureEvent(
            "cancelling", source_snapshot_id=self._source_snapshot_id
        )

    def advance(self, current_snapshot: Any = None) -> SceneCaptureEvent:
        if not self.active:
            raise SceneCaptureStateError("Scene capture is not active")
        current_id = str(getattr(current_snapshot, "snapshot_id", ""))
        if current_id != self._source_snapshot_id:
            source_id = self._source_snapshot_id
            required = self._required
            self._cancel_for_cleanup()
            self._clear()
            return SceneCaptureEvent(
                "stale",
                source_snapshot_id=source_id,
                required=required,
                error="Scene snapshot changed before capture completed",
            )

        session = self._session
        try:
            progress = session.step(
                max_items=self._max_items,
                max_milliseconds=self._max_milliseconds,
            )
        except Exception as exc:
            return self._classify_exception(exc)

        if not bool(getattr(session, "done", False)):
            return SceneCaptureEvent(
                "cancelling" if self._cancel_requested else "progress",
                source_snapshot_id=self._source_snapshot_id,
                required=self._required,
                message=str(getattr(progress, "message", "")),
                completed=int(getattr(progress, "completed", 0)),
                total=int(getattr(progress, "total", 0)),
            )

        source_id = self._source_snapshot_id
        required = self._required
        previous_snapshot = self._previous_snapshot
        if self._cancel_requested:
            self._clear()
            return SceneCaptureEvent(
                "cancelled", source_snapshot_id=source_id, required=required
            )
        try:
            snapshot = session.result
            if not str(getattr(snapshot, "snapshot_id", "")):
                raise ValueError("Scene capture returned an unidentified snapshot")
            reuse = session.reuse
        except Exception as exc:
            self._clear()
            return SceneCaptureEvent(
                "failed",
                source_snapshot_id=source_id,
                required=required,
                error=str(exc),
            )
        self._clear()
        return SceneCaptureEvent(
            "completed",
            source_snapshot_id=source_id,
            required=required,
            snapshot=snapshot,
            previous_snapshot=previous_snapshot,
            reuse=reuse,
        )

    def abort(self) -> SceneCaptureEvent:
        """Synchronously abandon a collector during host shutdown."""

        if not self.active:
            return SceneCaptureEvent("cancelled")
        source_id = self._source_snapshot_id
        required = self._required
        error = self._cancel_for_cleanup()
        self._clear()
        if error:
            return SceneCaptureEvent(
                "failed",
                source_snapshot_id=source_id,
                required=required,
                error=error,
            )
        return SceneCaptureEvent(
            "cancelled", source_snapshot_id=source_id, required=required
        )

    def _classify_exception(self, exc: Exception) -> SceneCaptureEvent:
        source_id = self._source_snapshot_id
        required = self._required
        cleanup_error = ""
        if not (self._cancelled_errors and isinstance(exc, self._cancelled_errors)):
            cleanup_error = self._cancel_for_cleanup()
        self._clear()
        error = str(exc)
        if cleanup_error and cleanup_error != error:
            error = "%s; cleanup failed: %s" % (error, cleanup_error)
        if self._cancelled_errors and isinstance(exc, self._cancelled_errors):
            return SceneCaptureEvent(
                "cancelled", source_snapshot_id=source_id, required=required
            )
        if self._stale_errors and isinstance(exc, self._stale_errors):
            return SceneCaptureEvent(
                "stale",
                source_snapshot_id=source_id,
                required=required,
                error=error,
            )
        return SceneCaptureEvent(
            "failed",
            source_snapshot_id=source_id,
            required=required,
            error=error,
        )

    def _cancel_for_cleanup(self) -> str:
        try:
            self._session.cancel()
        except Exception as exc:
            return str(exc)
        return ""

    def _clear(self) -> None:
        self._session = None
        self._previous_snapshot = None
        self._source_snapshot_id = ""
        self._required = False
        self._cancel_requested = False


__all__ = [
    "SceneCaptureController",
    "SceneCaptureEvent",
    "SceneCaptureStateError",
]
