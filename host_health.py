"""Fast, read-only host health facts for the Maya UI and support reports."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
import sys
from typing import Optional, Tuple

from . import __version__
from .deployment import inspect_module


@dataclass(frozen=True)
class HostHealth:
    state: str
    maya_version: str
    maya_api: str
    pyside_version: str
    evaluation_mode: Tuple[str, ...]
    mayapy_path: str
    module_state: str
    mayascope_version: str
    issues: Tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self.state == "ready"

    def to_dict(self):
        return asdict(self)


def collect_host_health(
    cmds=None,
    executable: Optional[str] = None,
    pyside_version: Optional[str] = None,
) -> HostHealth:
    issues = []
    maya_version = "unavailable"
    maya_api = "unavailable"
    evaluation_mode = ()
    if cmds is None:
        try:
            import maya.cmds as cmds  # type: ignore
        except Exception:
            cmds = None
    if cmds is not None:
        try:
            maya_version = str(cmds.about(version=True))
            maya_api = str(cmds.about(apiVersion=True))
            evaluation_mode = tuple(cmds.evaluationManager(query=True, mode=True) or ())
        except Exception as exc:
            issues.append("Maya query failed: %s" % exc)
    else:
        issues.append("当前未运行在 Maya 宿主中")

    if pyside_version is None:
        try:
            import PySide6
            pyside_version = str(PySide6.__version__)
        except Exception:
            pyside_version = "unavailable"
            issues.append("PySide6 unavailable")
    else:
        pyside_version = str(pyside_version)

    host_executable = Path(executable or sys.executable).expanduser().resolve()
    mayapy = host_executable.parent / "mayapy.exe"
    if host_executable.name.lower() == "mayapy.exe":
        mayapy = host_executable
    if not mayapy.is_file():
        showcase = Path(r"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe")
        mayapy = showcase if showcase.is_file() else mayapy
    if not mayapy.is_file():
        issues.append("Maya 2025 mayapy.exe unavailable")
    if maya_version not in {"2025", "2025.0", "2025.1", "2025.2", "2025.3"}:
        issues.append("Showcase baseline is Maya 2025")
    if not pyside_version.startswith("6."):
        issues.append("Showcase baseline requires PySide6")

    module = inspect_module()
    state = "ready" if not issues else "attention"
    return HostHealth(
        state=state,
        maya_version=maya_version,
        maya_api=maya_api,
        pyside_version=pyside_version,
        evaluation_mode=evaluation_mode,
        mayapy_path=str(mayapy),
        module_state=module.state,
        mayascope_version=__version__,
        issues=tuple(issues),
    )
