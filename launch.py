"""Unified, lazy-loading entry point for MayaScope."""

from __future__ import annotations

import importlib
import sys
from typing import Any, Dict, Tuple


ToolSpec = Tuple[str, str]

TOOLS: Dict[str, ToolSpec] = {
    "workspace": ("MayaScope.ui.workspace", "show_tool"),
    "hierarchy": ("MayaScope.analyze_scene", "show_tool"),
    "nodes": ("MayaScope.node_viewer", "show_tool"),
    "sets": ("MayaScope.set_manager", "show_tool"),
}


def available_tools() -> Tuple[str, ...]:
    """Return stable tool identifiers accepted by :func:`run`."""
    return tuple(TOOLS)


def run(tool: str = "workspace", *, development: bool = False) -> Any:
    """Open one Maya tool and return its window.

    Modules are loaded only after a valid tool is requested, so importing this
    entry point outside Maya remains safe for documentation and tests.
    """
    try:
        module_name, callable_name = TOOLS[tool]
    except KeyError as exc:
        choices = ", ".join(available_tools())
        raise ValueError(f"Unknown MayaScope {tool!r}; choose one of: {choices}") from exc

    module = importlib.import_module(module_name)
    if development and module_name in sys.modules:
        module = importlib.reload(module)
    window = getattr(module, callable_name)()
    if tool == "workspace":
        try:
            from .maya_integration import install_menu
            install_menu()
        except Exception:
            # The workspace remains usable in mayapy/offscreen hosts without MayaWindow.
            pass
    return window


def close_all() -> None:
    """Close all tool windows that have been loaded in this Maya session."""
    for module_name, _callable_name in TOOLS.values():
        module = sys.modules.get(module_name)
        close_tool = getattr(module, "close_tool", None) if module else None
        if close_tool is not None:
            close_tool()


show = run
