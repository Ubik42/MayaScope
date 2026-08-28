"""Animated project audit and resumable queue evidence rail."""

from __future__ import annotations

from pathlib import Path

from ..presentation import (
    ProjectGateSceneState,
    ProjectGateViewState,
    empty_project_gate,
    present_project_fault,
    present_project_queue,
    present_project_report,
)
from ..qt_compat import QtCore, QtGui, QtWidgets
from .foundation import COLORS, qt_enum as _qt_enum


class ProjectGateCanvas(QtWidgets.QWidget):
    """Clickable release train where each carriage is one verified Maya scene."""

    sceneActivated = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setFixedHeight(58)
        self.setMouseTracking(True)
        self.setAccessibleName("项目场景发布列车")
        self._scenes = ()
        self._selected = 0
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(42)

    def set_scenes(self, scenes):
        self._scenes = tuple(scenes)
        self._selected = 0
        self.update()

    def set_motion_enabled(self, enabled):
        if enabled:
            self._timer.start(42)
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def select_scene(self, index):
        if 0 <= index < len(self._scenes):
            self._selected = index
            self.update()

    def _tick(self):
        self._phase = (self._phase + 0.014) % 1.0
        self.update()

    def _index_at(self, position):
        if not self._scenes:
            return -1
        bounds = QtCore.QRectF(self.rect()).adjusted(8, 8, -8, -8)
        cell = bounds.width() / float(len(self._scenes))
        if not bounds.contains(QtCore.QPointF(position)):
            return -1
        return min(len(self._scenes) - 1, int((position.x() - bounds.left()) / cell))

    def mouseMoveEvent(self, event):
        index = self._index_at(event.position())
        if index >= 0:
            scene = self._scenes[index]
            if scene.queue_status:
                self.setToolTip(
                    "%s\n状态：%s · 尝试 %s 次%s"
                    % (
                        Path(scene.source_scene).name,
                        scene.queue_status,
                        scene.attempts,
                        "\n%s" % scene.error if scene.error else "",
                    )
                )
            else:
                self.setToolTip(
                    "%s\n问题 %s · 原子发现 %s · 签名 %s"
                    % (
                        Path(scene.source_scene).name,
                        scene.issue_count,
                        scene.atomic_finding_count,
                        scene.report_sha256[:12].upper(),
                    )
                )
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == _qt_enum(QtCore.Qt, "LeftButton"):
            index = self._index_at(event.position())
            if index >= 0:
                self._selected = index
                self.update()
                self.sceneActivated.emit(index)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#070A10"))
        bounds = QtCore.QRectF(self.rect()).adjusted(8, 8, -8, -8)
        scenes = self._scenes
        if not scenes:
            painter.setPen(COLORS["muted"])
            painter.drawText(
                bounds, _qt_enum(QtCore.Qt, "AlignCenter"), "尚未载入项目审计"
            )
            return
        cell_width = bounds.width() / float(len(scenes))
        rail_y = bounds.center().y()
        painter.setPen(QtGui.QPen(QtGui.QColor("#332B43"), 2.0))
        painter.drawLine(QtCore.QLineF(bounds.left(), rail_y, bounds.right(), rail_y))
        for index, scene in enumerate(scenes):
            status = scene.queue_status
            left = bounds.left() + index * cell_width + 2
            rect = QtCore.QRectF(
                left, bounds.top(), max(12.0, cell_width - 4), bounds.height()
            )
            queue_colors = {
                "待运行": COLORS["violet"],
                "运行中": COLORS["cyan"],
                "通过": COLORS["acid"],
                "阻断": COLORS["orange"],
                "失败": QtGui.QColor("#FF3D81"),
            }
            color = queue_colors.get(
                status, COLORS["orange"] if scene.blocked else COLORS["acid"]
            )
            surface = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
            queue_surfaces = {
                "待运行": QtGui.QColor("#241638"),
                "运行中": QtGui.QColor("#0A3342"),
                "通过": QtGui.QColor("#2A3C12"),
                "阻断": QtGui.QColor("#4A1710"),
                "失败": QtGui.QColor("#451126"),
            }
            surface.setColorAt(
                0,
                queue_surfaces.get(
                    status,
                    QtGui.QColor("#4A1710")
                    if scene.blocked
                    else QtGui.QColor("#2A3C12"),
                ),
            )
            surface.setColorAt(1, QtGui.QColor("#130C16"))
            painter.setBrush(surface)
            painter.setPen(QtGui.QPen(color, 2.0 if index == self._selected else 0.8))
            painter.drawRoundedRect(rect, 5, 5)
            if index == self._selected:
                glow = QtGui.QColor(color)
                glow.setAlpha(42)
                painter.fillRect(rect.adjusted(3, 3, -3, -3), glow)
            painter.setPen(QtGui.QColor("#F4F0FF"))
            font = painter.font()
            font.setBold(True)
            font.setPointSize(7)
            painter.setFont(font)
            name = scene.display_name
            if len(name) > 12:
                name = name[:10] + "…"
            painter.drawText(
                rect.adjusted(5, 3, -4, -13),
                _qt_enum(QtCore.Qt, "AlignCenter"),
                name,
            )
            painter.setPen(color)
            font.setPointSize(6)
            painter.setFont(font)
            state = status or (
                "阻断 %s" % scene.atomic_finding_count if scene.blocked else "可发布"
            )
            painter.drawText(
                rect.adjusted(4, 18, -4, -3),
                _qt_enum(QtCore.Qt, "AlignCenter"),
                state,
            )
        scan_x = bounds.left() + bounds.width() * self._phase
        beam = QtGui.QLinearGradient(scan_x - 42, 0, scan_x + 12, 0)
        beam.setColorAt(0, QtGui.QColor(72, 215, 255, 0))
        beam.setColorAt(0.78, QtGui.QColor(72, 215, 255, 72))
        beam.setColorAt(1, QtGui.QColor(72, 215, 255, 0))
        painter.fillRect(
            QtCore.QRectF(scan_x - 42, bounds.top(), 54, bounds.height()), beam
        )


class ProjectGateStrip(QtWidgets.QFrame):
    dismissRequested = QtCore.Signal()
    sceneActivated = QtCore.Signal(int)
    queueActionRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProjectGate")
        self.setFixedHeight(82)
        self.setAccessibleName("项目门禁与批量审计状态")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 12, 8)
        layout.setSpacing(14)
        heading = QtWidgets.QVBoxLayout()
        mark = QtWidgets.QLabel("◆  项目发布列车")
        mark.setObjectName("ProjectGateMark")
        heading.addWidget(mark)
        self.identity = QtWidgets.QLabel()
        self.identity.setObjectName("ProjectGateMeta")
        heading.addWidget(self.identity)
        self.guard = QtWidgets.QLabel()
        self.guard.setObjectName("ProjectGateGuard")
        heading.addWidget(self.guard)
        layout.addLayout(heading)
        self.canvas = ProjectGateCanvas()
        self.canvas.sceneActivated.connect(self.sceneActivated)
        layout.addWidget(self.canvas, 1)
        result = QtWidgets.QVBoxLayout()
        self.verdict = QtWidgets.QLabel()
        self.verdict.setObjectName("ProjectGateVerdict")
        self.detail = QtWidgets.QLabel()
        self.detail.setObjectName("ProjectGateMeta")
        result.addWidget(self.verdict)
        result.addWidget(self.detail)
        layout.addLayout(result)
        self.queue_action = QtWidgets.QPushButton()
        self.queue_action.setObjectName("ProjectQueueAction")
        self.queue_action.clicked.connect(self.queueActionRequested)
        layout.addWidget(self.queue_action)
        close = QtWidgets.QPushButton("×")
        close.setObjectName("LensClose")
        close.setToolTip("关闭项目门禁总览")
        close.clicked.connect(self.dismissRequested)
        layout.addWidget(close)
        self._apply_state(empty_project_gate())

    def _apply_state(self, state: ProjectGateViewState):
        self.canvas.set_scenes(state.scenes)
        self.identity.setText(state.identity)
        self.guard.setText(state.guard)
        self.verdict.setText(state.verdict)
        self.detail.setText(state.detail)
        self.guard.setProperty("alert", state.guard_alert)
        self.verdict.setProperty("failed", state.failed)
        for widget in (self.guard, self.verdict):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.queue_action.setText(state.action_text)
        self.queue_action.setToolTip(state.action_tooltip)
        self.queue_action.setEnabled(state.action_enabled)
        self.queue_action.setVisible(state.action_visible)

    def set_report(self, payload):
        self._apply_state(present_project_report(payload))
        self.setVisible(True)

    def set_queue(self, journal):
        self._apply_state(present_project_queue(journal))
        self.setVisible(True)

    def set_motion_enabled(self, enabled):
        self.canvas.set_motion_enabled(enabled)

    def select_scene(self, index):
        self.canvas.select_scene(index)

    def clear(self):
        self._apply_state(empty_project_gate())

    def set_fault(self, title, detail):
        self._apply_state(present_project_fault(title, detail))
        self.setVisible(True)


__all__ = ["ProjectGateCanvas", "ProjectGateStrip"]
