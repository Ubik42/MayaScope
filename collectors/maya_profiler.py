"""Maya 2025 Profiler session and efficient output capture adapter."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Optional

from ..analysis.pulse import parse_maya_profiler_output
from ..model import ProfilerCapture, SceneSnapshot


class MayaProfilerError(RuntimeError):
    pass


def _maya_cmds():
    try:
        import maya.cmds as cmds  # type: ignore
    except ImportError as exc:
        raise MayaProfilerError("Maya commands are unavailable") from exc
    return cmds


@dataclass(frozen=True)
class ProfileResult:
    result: Any
    capture: ProfilerCapture


class MayaProfilerSession:
    """Own one profiler buffer without leaving Maya sampling enabled."""

    def __init__(
        self,
        snapshot: Optional[SceneSnapshot] = None,
        buffer_size: int = 250_000,
        cmds_module: Any = None,
    ):
        if buffer_size < 1:
            raise ValueError("buffer_size must be positive")
        self.snapshot = snapshot
        self.buffer_size = buffer_size
        self.cmds = cmds_module or _maya_cmds()
        self._started = False

    @property
    def is_sampling(self) -> bool:
        try:
            return bool(self.cmds.profiler(query=True, sampling=True))
        except Exception as exc:
            raise MayaProfilerError("Could not query Maya Profiler state: %s" % exc) from exc

    def start(self) -> None:
        if self._started:
            raise MayaProfilerError("This MayaProfilerSession is already active")
        if self.is_sampling:
            raise MayaProfilerError(
                "Maya Profiler is already sampling; refusing to reset another session"
            )
        try:
            self.cmds.profiler(reset=True)
            self.cmds.profiler(bufferSize=self.buffer_size)
            self.cmds.profiler(sampling=True)
        except Exception as exc:
            try:
                self.cmds.profiler(sampling=False)
            except Exception:
                pass
            raise MayaProfilerError("Could not start Maya Profiler: %s" % exc) from exc
        self._started = True

    def stop(self) -> ProfilerCapture:
        if not self._started:
            raise MayaProfilerError("MayaProfilerSession has not been started")
        try:
            self.cmds.profiler(sampling=False)
            text = self._export_buffer()
            capture = parse_maya_profiler_output(
                text,
                self.snapshot,
                source_scene=str(self.cmds.file(query=True, sceneName=True) or ""),
                maya_version=str(self.cmds.about(version=True)),
            )
        except Exception as exc:
            if isinstance(exc, MayaProfilerError):
                raise
            raise MayaProfilerError("Could not capture Maya Profiler buffer: %s" % exc) from exc
        finally:
            self._started = False
        return capture

    def abort(self) -> None:
        if not self._started:
            return
        try:
            self.cmds.profiler(sampling=False)
        finally:
            self._started = False

    def _export_buffer(self) -> str:
        descriptor, name = tempfile.mkstemp(prefix="mayascope-profiler-", suffix=".txt")
        os.close(descriptor)
        path = Path(name)
        try:
            self.cmds.profiler(output=str(path))
            return path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            raise MayaProfilerError("Could not export Maya Profiler buffer: %s" % exc) from exc
        finally:
            try:
                path.unlink()
            except OSError:
                pass


def profile_callable(
    operation: Callable[[], Any],
    snapshot: Optional[SceneSnapshot] = None,
    buffer_size: int = 250_000,
    cmds_module: Any = None,
) -> ProfileResult:
    """Profile one explicit operation and always restore sampling state."""
    session = MayaProfilerSession(snapshot, buffer_size, cmds_module)
    session.start()
    try:
        result = operation()
    except Exception:
        session.abort()
        raise
    return ProfileResult(result=result, capture=session.stop())
