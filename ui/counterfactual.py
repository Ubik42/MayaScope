"""Counterfactual Spectrum view for reversible performance experiments."""

from __future__ import annotations

from ..presentation.counterfactual import CounterfactualViewState, empty_counterfactual
from ..qt_compat import QtCore, QtGui, QtWidgets
from .foundation import COLORS, qt_enum as _qt_enum


class CounterfactualSpark(QtWidgets.QWidget):
    """Paired AB/BA measurements as a compact spectral barcode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(210)
        self.setMaximumWidth(310)
        self.setFixedHeight(50)
        self._state = empty_counterfactual()
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(45)

    def set_state(self, state: CounterfactualViewState):
        self._state = state
        self.update()

    def set_motion_enabled(self, enabled: bool):
        if enabled:
            self._timer.start(45)
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def _tick(self):
        self._phase = (self._phase + 0.018) % 1.0
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#0A0810"))
        pairs = self._state.pairs
        if not pairs:
            return
        peak = max(
            (value for pair in pairs for value in (pair.baseline_us, pair.variant_us)),
            default=1,
        ) or 1
        plot = self.rect().adjusted(8, 5, -8, -7)
        slot = plot.width() / max(1, len(pairs))
        variant_color = COLORS["acid"] if self._state.verdict == "improved" else COLORS["orange"]
        for ordinal, pair in enumerate(pairs):
            center = plot.left() + slot * (ordinal + 0.5)
            for offset, value, color in (
                (-4.5, pair.baseline_us, COLORS["violet"]),
                (1.0, pair.variant_us, variant_color),
            ):
                height = plot.height() * value / float(peak)
                rect = QtCore.QRectF(center + offset, plot.bottom() - height, 4.0, height)
                glow = QtGui.QColor(color)
                glow.setAlpha(62)
                painter.fillRect(rect.adjusted(-2, -1, 2, 1), glow)
                painter.fillRect(rect, color)
        scan_x = plot.left() + plot.width() * self._phase
        painter.setPen(QtGui.QPen(QtGui.QColor(72, 215, 255, 90), 1.0))
        painter.drawLine(QtCore.QLineF(scan_x, plot.top(), scan_x, plot.bottom()))


class CounterfactualStrip(QtWidgets.QFrame):
    dismissRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CounterfactualStrip")
        self.setFixedHeight(68)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 7, 12, 7)
        layout.setSpacing(14)
        self.mark = QtWidgets.QLabel("◇  反事实实验")
        self.mark.setObjectName("CounterfactualMark")
        layout.addWidget(self.mark)
        identity = QtWidgets.QVBoxLayout()
        identity.setSpacing(1)
        self.target = QtWidgets.QLabel()
        self.target.setObjectName("CounterfactualTarget")
        self.design = QtWidgets.QLabel()
        self.design.setObjectName("CounterfactualDesign")
        identity.addWidget(self.target)
        identity.addWidget(self.design)
        layout.addLayout(identity)
        self.spark = CounterfactualSpark()
        layout.addWidget(self.spark, 1)
        result = QtWidgets.QVBoxLayout()
        result.setSpacing(1)
        self.result_metric = QtWidgets.QLabel()
        self.result_metric.setObjectName("CounterfactualMetric")
        self.interval = QtWidgets.QLabel()
        self.interval.setObjectName("CounterfactualInterval")
        result.addWidget(self.result_metric)
        result.addWidget(self.interval)
        layout.addLayout(result)
        close = QtWidgets.QPushButton("×")
        close.setObjectName("LensClose")
        close.setToolTip("关闭反事实证据")
        close.clicked.connect(self.dismissRequested)
        layout.addWidget(close)
        self._state = empty_counterfactual()
        self._render_state()

    def _render_state(self):
        self.spark.set_state(self._state)
        self.target.setText(self._state.target)
        self.design.setText(self._state.design)
        self.result_metric.setText(self._state.metric)
        self.result_metric.setProperty("verdict", self._state.verdict)
        self.result_metric.style().unpolish(self.result_metric)
        self.result_metric.style().polish(self.result_metric)
        self.interval.setText(self._state.interval)

    def set_state(self, state: CounterfactualViewState):
        self._state = state
        self._render_state()
        self.setVisible(True)

    def set_motion_enabled(self, enabled: bool):
        self.spark.set_motion_enabled(enabled)

    def clear(self):
        self._state = empty_counterfactual()
        self._render_state()


__all__ = ["CounterfactualSpark", "CounterfactualStrip"]
