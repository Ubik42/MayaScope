"""Lifecycle-safe bidirectional Maya selection bridge.

The adapter owns exactly one Maya ``SelectionChanged`` callback.  It keeps
host objects and Qt out of the core contract: consumers receive immutable long
node names and decide how those names map into their current SceneSnapshot.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple


class MayaSelectionBridge:
    """Observe and write Maya selection without callback feedback loops."""

    def __init__(self, changed: Callable[[Tuple[str, ...]], None], *, cmds_module=None, om_module=None):
        if not callable(changed):
            raise TypeError("changed callback must be callable")
        self._changed = changed
        self._cmds = cmds_module
        self._om = om_module
        self._callback_id = None
        self._expected_selection: Optional[Tuple[str, ...]] = None
        self.last_error = ""

    @property
    def active(self) -> bool:
        return self._callback_id is not None

    def _load_host(self) -> None:
        if self._cmds is None:
            import maya.cmds as cmds  # type: ignore

            self._cmds = cmds
        if self._om is None:
            import maya.api.OpenMaya as om  # type: ignore

            self._om = om

    def start(self) -> Tuple[str, ...]:
        """Install one callback and immediately publish the current selection."""
        if self.active:
            return self.current_selection()
        self._load_host()
        self._callback_id = self._om.MEventMessage.addEventCallback(
            "SelectionChanged", self._on_selection_changed
        )
        try:
            selection = self.current_selection()
        except Exception:
            callback_id = self._callback_id
            self._callback_id = None
            self._om.MMessage.removeCallback(callback_id)
            raise
        self._publish(selection)
        return selection

    def stop(self) -> bool:
        """Remove the callback.  Safe and idempotent during Maya shutdown."""
        callback_id = self._callback_id
        if callback_id is None:
            return False
        try:
            self._om.MMessage.removeCallback(callback_id)
        except Exception as exc:
            self.last_error = str(exc)
            return False
        self._callback_id = None
        self._expected_selection = None
        return True

    def current_selection(self) -> Tuple[str, ...]:
        self._load_host()
        values = self._cmds.ls(selection=True, long=True) or ()
        return tuple(dict.fromkeys(str(value) for value in values if value))

    def select(self, names: Sequence[str]) -> Tuple[str, ...]:
        """Write a normalized host selection and suppress its echo callback."""
        self._load_host()
        normalized = tuple(dict.fromkeys(str(name) for name in names if name))
        self._expected_selection = normalized
        try:
            if normalized:
                self._cmds.select(list(normalized), replace=True, noExpand=True)
            else:
                self._cmds.select(clear=True)
        except Exception:
            self._expected_selection = None
            raise
        return normalized

    def _on_selection_changed(self, *_args) -> None:
        try:
            selection = self.current_selection()
            if self._expected_selection is not None:
                expected = self._expected_selection
                self._expected_selection = None
                if selection == expected:
                    return
            self._publish(selection)
        except Exception as exc:
            # Maya callbacks must never leak an exception into the host loop.
            self.last_error = str(exc)

    def _publish(self, selection: Tuple[str, ...]) -> None:
        try:
            self._changed(selection)
        except Exception as exc:
            self.last_error = str(exc)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *_exc):
        self.stop()

    def __del__(self):
        try:
            self.stop()
        except Exception:
            pass
