"""Failure Prism view for isolated Crash Bisect evidence."""

from __future__ import annotations

import math

from ..presentation.bisect import (
    BisectPrismState,
    begin_bisect_prism,
    fail_bisect_prism,
    finish_bisect_prism,
    present_bisect_attempt,
    request_bisect_cancel,
)
from ..qt_compat import QtCore, QtGui, QtWidgets
from .foundation import COLORS, qt_enum as _qt_enum


class BisectTraceCanvas(QtWidgets.QWidget):
    """Compact animated evidence field for serial isolated probes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self.setFixedHeight(72)
        self._candidate_count = 0
        self._attempts = []
        self._active = False
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def reset(self, candidate_count: int):
        self._candidate_count = max(0, int(candidate_count))
        self._attempts = []
        self._active = True
        self.update()

    def add_attempt(self, step, attempt):
        self._attempts.append((step, attempt))
        self.update()

    def finish(self):
        self._active = False
        self.update()

    def set_motion_enabled(self, enabled: bool):
        if enabled:
            self._timer.start(40)
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def _tick(self):
        self._phase = (self._phase + 0.022) % 1.0
        if self._active:
            self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#09070E"))
        bounds = self.rect().adjusted(12, 9, -12, -9)
        attempts = self._attempts[-10:]
        total_slots = max(4, len(attempts) + (1 if self._active else 0))
        slot = bounds.width() / float(total_slots)
        baseline = bounds.center().y()
        previous = None
        colors = {
            "pass": COLORS["cyan"],
            "fail": COLORS["orange"],
            "unresolved": COLORS["violet"],
        }
        for index, (step, attempt) in enumerate(attempts):
            ratio = len(step.candidate_ids) / float(max(1, self._candidate_count))
            x = bounds.left() + slot * (index + 0.55)
            y = baseline + (ratio - 0.5) * bounds.height() * 0.62
            point = QtCore.QPointF(x, y)
            if previous is not None:
                line = QtGui.QColor(colors.get(attempt.outcome, COLORS["muted"]))
                line.setAlpha(92)
                painter.setPen(QtGui.QPen(line, 1.2))
                painter.drawLine(QtCore.QLineF(previous, point))
            previous = point
            radius = 4.5 + 7.0 * ratio
            polygon = QtGui.QPolygonF(
                [
                    QtCore.QPointF(x, y - radius),
                    QtCore.QPointF(x + radius, y),
                    QtCore.QPointF(x, y + radius),
                    QtCore.QPointF(x - radius, y),
                ]
            )
            color = colors.get(attempt.outcome, COLORS["muted"])
            if attempt.outcome == "pass":
                painter.setBrush(_qt_enum(QtCore.Qt, "NoBrush"))
                painter.setPen(QtGui.QPen(color, 2.0))
            else:
                glow = QtGui.QColor(color)
                glow.setAlpha(58)
                painter.setBrush(glow)
                painter.setPen(QtGui.QPen(color, 1.7))
            painter.drawPolygon(polygon)
            painter.setPen(QtGui.QPen(QtGui.QColor("#91899C"), 1.0))
            font = painter.font()
            font.setPointSize(6)
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(
                QtCore.QRectF(
                    x - slot * 0.45, bounds.bottom() - 10, slot * 0.9, 12
                ),
                _qt_enum(QtCore.Qt, "AlignCenter"),
                "%s/%s" % (len(step.candidate_ids), attempt.stage[:2].upper()),
            )
        if self._active:
            index = len(attempts)
            x = bounds.left() + slot * (index + 0.55)
            pulse = 5.0 + 3.0 * (0.5 + 0.5 * math.sin(self._phase * math.tau))
            scan = QtGui.QColor(COLORS["acid"])
            scan.setAlpha(70)
            painter.setPen(QtGui.QPen(scan, 1.3))
            painter.setBrush(_qt_enum(QtCore.Qt, "NoBrush"))
            painter.drawEllipse(QtCore.QPointF(x, baseline), pulse, pulse)
            painter.drawEllipse(QtCore.QPointF(x, baseline), pulse + 7, pulse + 7)


class BisectPrism(QtWidgets.QFrame):
    cancelRequested = QtCore.Signal()
    dismissRequested = QtCore.Signal()
    resumeRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("BisectPrism")
        self.setFixedHeight(112)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 10, 12, 10)
        layout.setSpacing(14)
        mark_box = QtWidgets.QVBoxLayout()
        mark_box.setSpacing(1)
        self.mark = QtWidgets.QLabel("//  故障棱镜")
        self.mark.setObjectName("BisectMark")
        self.mode = QtWidgets.QLabel()
        self.mode.setObjectName("BisectMeta")
        mark_box.addWidget(self.mark)
        mark_box.addWidget(self.mode)
        layout.addLayout(mark_box)
        self.canvas = BisectTraceCanvas()
        layout.addWidget(self.canvas, 1)
        signal_box = QtWidgets.QVBoxLayout()
        signal_box.setSpacing(1)
        self.signal = QtWidgets.QLabel()
        self.signal.setObjectName("BisectSignal")
        self.detail = QtWidgets.QLabel()
        self.detail.setObjectName("BisectMeta")
        signal_box.addWidget(self.signal)
        signal_box.addWidget(self.detail)
        layout.addLayout(signal_box)
        controls = QtWidgets.QVBoxLayout()
        self.cancel = QtWidgets.QPushButton()
        self.cancel.setObjectName("BisectCancel")
        self.cancel.clicked.connect(self.cancelRequested)
        self.dismiss = QtWidgets.QPushButton("关闭")
        self.dismiss.setObjectName("BisectDismiss")
        self.dismiss.clicked.connect(self.dismissRequested)
        self.resume = QtWidgets.QPushButton("继续二分")
        self.resume.setObjectName("BisectResume")
        self.resume.clicked.connect(self.resumeRequested)
        controls.addWidget(self.cancel)
        controls.addWidget(self.resume)
        controls.addWidget(self.dismiss)
        layout.addLayout(controls)
        self._state = BisectPrismState()
        self._render_state()

    def _render_state(self):
        state = self._state
        self.mode.setText(state.mode)
        self.signal.setText(state.signal)
        self.signal.setProperty("outcome", state.outcome)
        self.signal.style().unpolish(self.signal)
        self.signal.style().polish(self.signal)
        self.detail.setText(state.detail)
        self.cancel.setVisible(state.cancel_visible)
        self.cancel.setEnabled(state.cancel_enabled)
        self.cancel.setText(state.cancel_text)
        self.resume.setVisible(state.resume_visible)
        self.dismiss.setVisible(state.dismiss_visible)

    def begin(self, plan):
        self._state = begin_bisect_prism(plan)
        self.canvas.reset(self._state.candidate_count)
        self._render_state()
        self.setVisible(True)

    def add_attempt(self, step, attempt):
        self.canvas.add_attempt(step, attempt)
        self._state = present_bisect_attempt(self._state, step, attempt)
        self._render_state()

    def request_cancel(self):
        self._state = request_bisect_cancel(self._state)
        self._render_state()

    def finish(self, result, labels):
        self.canvas.finish()
        self._state = finish_bisect_prism(self._state, result, labels)
        self._render_state()

    def fail(self, message: str):
        self.canvas.finish()
        self._state = fail_bisect_prism(self._state, message)
        self._render_state()

    def set_motion_enabled(self, enabled: bool):
        self.canvas.set_motion_enabled(enabled)


__all__ = ["BisectPrism", "BisectTraceCanvas"]
