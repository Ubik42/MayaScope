"""Shared PySide foundation for MayaScope's spectral instrument UI.

This module owns host-safe visual primitives that every view may reuse.  It
deliberately contains no Maya imports and no workspace/application state.
"""

from __future__ import annotations

import os
from pathlib import Path

from ..qt_compat import QtCore, QtGui, QtWidgets


PALETTE_HEX = {
    "void": "#07060D",
    "panel": "#11101A",
    "violet": "#9C5CFF",
    "orange": "#FF6A2A",
    "acid": "#C8FF3D",
    "cyan": "#48D7FF",
    "text": "#F4F0FF",
    "muted": "#8E899C",
}

COLORS = {name: QtGui.QColor(value) for name, value in PALETTE_HEX.items()}


def qt_enum(container, name):
    """Resolve Qt5/Qt6 enum spelling without spreading version branches."""
    direct = getattr(container, name, None)
    if direct is not None:
        return direct
    for group_name in (
        "AlignmentFlag",
        "PenStyle",
        "BrushStyle",
        "MouseButton",
        "ItemDataRole",
        "ScrollBarPolicy",
        "Orientation",
        "TextFormat",
        "FocusPolicy",
        "Key",
    ):
        group = getattr(container, group_name, None)
        value = getattr(group, name, None) if group else None
        if value is not None:
            return value
    raise AttributeError(name)


def confirm_action(parent, title: str, message: str) -> bool:
    """Show a host-independent confirmation with guaranteed Chinese actions."""
    box = QtWidgets.QMessageBox(parent)
    box.setIcon(QtWidgets.QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.setStandardButtons(QtWidgets.QMessageBox.Apply | QtWidgets.QMessageBox.Cancel)
    box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
    box.button(QtWidgets.QMessageBox.Apply).setText("执行")
    box.button(QtWidgets.QMessageBox.Cancel).setText("取消")
    return box.exec() == QtWidgets.QMessageBox.Apply


def ensure_ui_fonts() -> None:
    """Make Chinese typography available in Maya and offscreen Qt evidence."""
    font_root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for filename in (
        "msyh.ttc",
        "msyhbd.ttc",
        "msyhl.ttc",
        "Deng.ttf",
        "Dengb.ttf",
        "Dengl.ttf",
        "segoeui.ttf",
        "seguisb.ttf",
        "segoeuib.ttf",
    ):
        path = font_root / filename
        if path.is_file():
            QtGui.QFontDatabase.addApplicationFont(str(path))
    app = QtWidgets.QApplication.instance()
    if app:
        for family in (
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "DengXian",
            "Segoe UI",
        ):
            if QtGui.QFontDatabase.hasFamily(family):
                app.setFont(QtGui.QFont(family, 9))
                break


__all__ = [
    "COLORS",
    "PALETTE_HEX",
    "confirm_action",
    "ensure_ui_fonts",
    "qt_enum",
]
