"""Regression Rift view for signed Scene Clinic comparisons."""

from __future__ import annotations

from ..presentation.regression import (
    RegressionPerformanceState,
    RegressionRiftState,
    empty_regression_rift,
)
from ..qt_compat import QtCore, QtGui, QtWidgets
from .foundation import COLORS, qt_enum as _qt_enum


class RegressionRiftCanvas(QtWidgets.QWidget):
    """Baseline/current evaluation samples split around a luminous rift."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setFixedHeight(54)
        self._performance = RegressionPerformanceState()
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(46)

    def set_performance(self, performance: RegressionPerformanceState):
        self._performance = performance
        self.update()

    def set_motion_enabled(self, enabled):
        if enabled:
            self._timer.start(46)
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def _tick(self):
        self._phase = (self._phase + 0.02) % 1.0
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        bounds = QtCore.QRectF(self.rect()).adjusted(8, 6, -8, -6)
        painter.fillRect(self.rect(), QtGui.QColor("#080811"))
        performance = self._performance
        if not performance.comparable:
            painter.setPen(COLORS["muted"])
            painter.drawText(
                bounds, _qt_enum(QtCore.Qt, "AlignCenter"), "暂无成对性能证据"
            )
            return
        baseline = performance.baseline_samples_us
        current = performance.current_samples_us
        values = baseline + current
        low, high = min(values), max(values)
        span = max(1.0, float(high - low))

        def y(value):
            return bounds.bottom() - (float(value) - low) / span * bounds.height()

        count = max(len(baseline), len(current), 2)
        step = bounds.width() / float(max(1, count - 1))
        current_color = COLORS["orange"] if performance.regressed else COLORS["cyan"]
        for series, color in ((baseline, COLORS["violet"]), (current, current_color)):
            points = [
                QtCore.QPointF(bounds.left() + i * step, y(value))
                for i, value in enumerate(series)
            ]
            glow = QtGui.QColor(color)
            glow.setAlpha(48)
            painter.setPen(QtGui.QPen(glow, 5.0))
            for first, second in zip(points, points[1:]):
                painter.drawLine(QtCore.QLineF(first, second))
            painter.setPen(QtGui.QPen(color, 1.4))
            for first, second in zip(points, points[1:]):
                painter.drawLine(QtCore.QLineF(first, second))
            painter.setBrush(color)
            painter.setPen(_qt_enum(QtCore.Qt, "NoPen"))
            for point in points:
                painter.drawEllipse(point, 2.3, 2.3)
        scan_x = bounds.left() + bounds.width() * self._phase
        scan = QtGui.QColor(COLORS["acid"])
        scan.setAlpha(75)
        painter.setPen(QtGui.QPen(scan, 1.0))
        painter.drawLine(QtCore.QLineF(scan_x, bounds.top(), scan_x, bounds.bottom()))


class RegressionRiftStrip(QtWidgets.QFrame):
    dismissRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RegressionRift")
        self.setFixedHeight(76)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 12, 8)
        layout.setSpacing(14)
        mark_box = QtWidgets.QVBoxLayout()
        mark = QtWidgets.QLabel("≋  回归裂隙")
        mark.setObjectName("RegressionMark")
        mark_box.addWidget(mark)
        self.identity = QtWidgets.QLabel()
        self.identity.setObjectName("RegressionMeta")
        mark_box.addWidget(self.identity)
        layout.addLayout(mark_box)
        self.canvas = RegressionRiftCanvas()
        layout.addWidget(self.canvas, 1)
        result = QtWidgets.QVBoxLayout()
        self.verdict = QtWidgets.QLabel()
        self.verdict.setObjectName("RegressionVerdict")
        self.detail = QtWidgets.QLabel()
        self.detail.setObjectName("RegressionMeta")
        result.addWidget(self.verdict)
        result.addWidget(self.detail)
        layout.addLayout(result)
        close = QtWidgets.QPushButton("×")
        close.setObjectName("LensClose")
        close.setToolTip("关闭回归证据")
        close.clicked.connect(self.dismissRequested)
        layout.addWidget(close)
        self._state = empty_regression_rift()
        self._render_state()

    def _render_state(self):
        self.canvas.set_performance(self._state.performance)
        self.verdict.setText(self._state.verdict)
        self.verdict.setProperty("failed", self._state.failed)
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        self.detail.setText(self._state.detail)
        self.identity.setText(self._state.identity)

    def set_state(self, state: RegressionRiftState):
        self._state = state
        self._render_state()
        self.setVisible(True)

    def set_motion_enabled(self, enabled):
        self.canvas.set_motion_enabled(enabled)

    def clear(self):
        self._state = empty_regression_rift()
        self._render_state()


__all__ = ["RegressionRiftCanvas", "RegressionRiftStrip"]
