"""Runtime execution-surface constellation for MayaScope."""

from __future__ import annotations

import math

from ..qt_compat import QtCore, QtGui, QtWidgets
from .foundation import COLORS, qt_enum as _qt_enum


class RuntimeConstellationCanvas(QtWidgets.QWidget):
    """Four orbital lanes for volatile execution surfaces."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAccessibleName("运行时执行表面动态星图")
        self.setMinimumWidth(300)
        self.setFixedHeight(64)
        self._counts = (0, 0, 0, 0)
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(42)

    def set_runtime(self, runtime):
        self._counts = (
            len(runtime.expressions),
            len(runtime.script_jobs),
            len(runtime.plugins),
            len(runtime.node_callbacks),
        )
        self.update()

    def clear(self):
        self._counts = (0, 0, 0, 0)
        self.update()

    def set_motion_enabled(self, enabled):
        if enabled:
            self._timer.start(42)
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def _tick(self):
        self._phase = (self._phase + 0.016) % 1.0
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#070A10"))
        labels = ("表达式", "任务", "插件", "回调")
        colors = (COLORS["orange"], COLORS["acid"], COLORS["violet"], COLORS["cyan"])
        width = self.width() / 4.0
        center_y = self.height() * 0.46
        for lane, (label, color, count) in enumerate(zip(labels, colors, self._counts)):
            center = QtCore.QPointF(width * (lane + 0.5), center_y)
            radius = min(21.0, 9.0 + math.sqrt(count) * 2.8)
            ring = QtGui.QColor(color)
            ring.setAlpha(70 if count else 28)
            painter.setBrush(_qt_enum(QtCore.Qt, "NoBrush"))
            painter.setPen(QtGui.QPen(ring, 1.0))
            painter.drawEllipse(center, radius, radius * 0.58)
            satellites = min(10, count)
            for index in range(satellites):
                angle = math.tau * (index / float(max(1, satellites)) + self._phase * (1 if lane % 2 else -1))
                point = QtCore.QPointF(
                    center.x() + math.cos(angle) * radius,
                    center.y() + math.sin(angle) * radius * 0.58,
                )
                glow = QtGui.QColor(color)
                glow.setAlpha(52)
                painter.setPen(_qt_enum(QtCore.Qt, "NoPen"))
                painter.setBrush(glow)
                painter.drawEllipse(point, 4.2, 4.2)
                painter.setBrush(color)
                painter.drawEllipse(point, 1.8, 1.8)
            painter.setPen(COLORS["text"] if count else COLORS["muted"])
            font = painter.font()
            font.setBold(True)
            font.setPointSize(7)
            painter.setFont(font)
            painter.drawText(
                QtCore.QRectF(center.x() - 34, center.y() - 7, 68, 14),
                _qt_enum(QtCore.Qt, "AlignCenter"),
                "%s %s" % (label, count),
            )


class RuntimeConstellationStrip(QtWidgets.QFrame):
    focusRequested = QtCore.Signal()
    dismissRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RuntimeConstellation")
        self.setAccessibleName("运行时执行表面证据")
        self.setFixedHeight(88)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 12, 8)
        layout.setSpacing(14)
        mark_box = QtWidgets.QVBoxLayout()
        mark = QtWidgets.QLabel("✦  运行时星图")
        mark.setObjectName("RuntimeMark")
        mark_box.addWidget(mark)
        self.boundary = QtWidgets.QLabel("执行表面")
        self.boundary.setObjectName("RuntimeMeta")
        mark_box.addWidget(self.boundary)
        layout.addLayout(mark_box)
        self.canvas = RuntimeConstellationCanvas()
        layout.addWidget(self.canvas, 1)
        result = QtWidgets.QVBoxLayout()
        self.signal = QtWidgets.QLabel("尚未采集")
        self.signal.setObjectName("RuntimeSignal")
        self.detail = QtWidgets.QLabel("")
        self.detail.setObjectName("RuntimeMeta")
        result.addWidget(self.signal)
        result.addWidget(self.detail)
        layout.addLayout(result)
        focus = QtWidgets.QPushButton("追踪执行表面")
        focus.setObjectName("RuntimeFocus")
        focus.clicked.connect(self.focusRequested)
        layout.addWidget(focus)
        close = QtWidgets.QPushButton("×")
        close.setObjectName("LensClose")
        close.setToolTip("关闭运行时证据并恢复之前的图谱覆盖")
        close.clicked.connect(self.dismissRequested)
        layout.addWidget(close)

    def set_report(self, runtime, report):
        self.canvas.set_runtime(runtime)
        self.signal.setText("%s 个运行时信号" % len(report.issues))
        self.signal.setProperty("active", bool(report.issues))
        self.signal.style().unpolish(self.signal)
        self.signal.style().polish(self.signal)
        self.detail.setText(
            "%s 个表达式 · %s 个 scriptJob · %s 个插件 · %s 个回调节点"
            % (len(runtime.expressions), len(runtime.script_jobs), len(runtime.plugins), len(runtime.node_callbacks))
        )
        self.boundary.setText("scriptJob %s · 回调内部不可观测" % ("可读取" if runtime.script_jobs_available else "不可用"))
        self.setVisible(True)

    def set_motion_enabled(self, enabled):
        self.canvas.set_motion_enabled(enabled)

    def clear(self):
        self.canvas.clear()
        self.signal.setText("尚未采集")
        self.detail.clear()
        self.boundary.setText("执行表面")


__all__ = ["RuntimeConstellationCanvas", "RuntimeConstellationStrip"]
