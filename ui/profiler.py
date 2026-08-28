"""Interactive Maya Profiler horizon for the MayaScope workspace."""

from __future__ import annotations

import math
from typing import Optional

from ..model import ProfilerCapture
from ..qt_compat import QtCore, QtGui, QtWidgets
from .foundation import COLORS, qt_enum as _qt_enum


class PulseHorizon(QtWidgets.QWidget):
    rangeSelected = QtCore.Signal(object)
    profileRequested = QtCore.Signal()
    counterfactualRequested = QtCore.Signal()
    dismissRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(142)
        self.setMouseTracking(True)
        self.setAccessibleName("性能采样事件地平线与可选时间范围")
        self._phase = 0.0
        self._summary = {"nodes": 0, "edges": 0}
        self._capture: Optional[ProfilerCapture] = None
        self._events = ()
        self._lane_names = ()
        self._selection = (0, 0)
        self._drag_origin: Optional[int] = None
        self.profile_button = QtWidgets.QPushButton("●  采样当前帧", self)
        self.profile_button.setObjectName("ProfileButton")
        self.profile_button.setToolTip("执行一次 Maya 强制求值与视口刷新，并记录真实耗时")
        self.profile_button.clicked.connect(self.profileRequested)
        self.counterfactual_button = QtWidgets.QPushButton("◇  测试焦点节点", self)
        self.counterfactual_button.setObjectName("CounterfactualButton")
        self.counterfactual_button.setToolTip(
            "对焦点本地节点执行可撤销的成对 nodeState 实验"
        )
        self.counterfactual_button.setEnabled(False)
        self.counterfactual_button.clicked.connect(self.counterfactualRequested)
        self.clear_button = QtWidgets.QPushButton("清除采样", self)
        self.clear_button.setObjectName("PulseClear")
        self.clear_button.setToolTip("清除本次性能采样及其派生的实测根因结果；不会修改 Maya 场景")
        self.clear_button.setAccessibleName("清除本次性能采样")
        self.clear_button.clicked.connect(self.dismissRequested)
        self.clear_button.setVisible(False)
        timer = QtCore.QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(40)
        self._timer = timer

    def set_motion_enabled(self, enabled: bool):
        if enabled:
            self._timer.start(40)
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def set_summary(self, summary):
        self._summary = summary
        self.update()

    def set_capture(self, capture: Optional[ProfilerCapture]):
        self._capture = capture
        self.clear_button.setVisible(capture is not None)
        if capture is None:
            self._events = ()
            self._lane_names = ()
            self._selection = (0, 0)
        else:
            totals = {}
            for event in capture.events:
                totals[event.category_name] = totals.get(event.category_name, 0) + event.duration_us
            self._lane_names = tuple(
                name for name, _duration in sorted(totals.items(), key=lambda item: -item[1])[:5]
            )
            selected = [event for event in capture.events if event.category_name in self._lane_names]
            if len(selected) > 2500:
                selected = sorted(selected, key=lambda item: item.duration_us, reverse=True)[:2500]
            self._events = tuple(sorted(selected, key=lambda item: (item.start_us, item.index)))
            self._selection = (0, capture.duration_us)
        self.update()

    @property
    def selected_range(self):
        return self._selection

    def resizeEvent(self, event):
        hint = self.profile_button.sizeHint()
        width = max(148, hint.width() + 14)
        self.profile_button.setGeometry(self.width() - width - 18, 10, width, 30)
        counter_width = max(136, self.counterfactual_button.sizeHint().width() + 12)
        self.counterfactual_button.setGeometry(
            self.width() - width - counter_width - 26, 10, counter_width, 30
        )
        clear_width = max(74, self.clear_button.sizeHint().width() + 10)
        self.clear_button.setGeometry(
            self.width() - width - counter_width - clear_width - 34,
            10,
            clear_width,
            30,
        )
        super().resizeEvent(event)

    def _plot_rect(self):
        return QtCore.QRectF(128, 48, max(20, self.width() - 148), max(30, self.height() - 58))

    def _x_for_time(self, time_us: int) -> float:
        rect = self._plot_rect()
        duration = max(1, self._capture.duration_us if self._capture else 1)
        return rect.left() + rect.width() * max(0.0, min(1.0, time_us / float(duration)))

    def _time_for_x(self, x: float) -> int:
        if not self._capture:
            return 0
        rect = self._plot_rect()
        ratio = max(0.0, min(1.0, (x - rect.left()) / max(1.0, rect.width())))
        return int(round(ratio * self._capture.duration_us))

    def _tick(self):
        self._phase += 0.08
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#0C0A13"))
        if self._capture and self._capture.events:
            self._paint_capture(painter)
            return
        path = QtGui.QPainterPath(QtCore.QPointF(0, self.height() * 0.63))
        amplitude = min(19.0, 4.0 + self._summary.get("edges", 0) / 130.0)
        for x in range(0, self.width() + 5, 5):
            wave = math.sin(x * 0.038 + self._phase) + 0.35 * math.sin(x * 0.11 - self._phase * 1.7)
            path.lineTo(x, self.height() * 0.63 + wave * amplitude)
        glow = QtGui.QPen(QtGui.QColor(156, 92, 255, 45), 7)
        painter.setPen(glow)
        painter.drawPath(path)
        painter.setPen(QtGui.QPen(COLORS["violet"], 1.4))
        painter.drawPath(path)
        painter.setPen(COLORS["muted"])
        painter.drawText(18, 23, "追踪地平线  /  性能采样")
        painter.setPen(QtGui.QColor("#5E586A"))
        painter.drawText(18, 43, "采样当前帧，记录真实 Maya 求值事件")
        painter.setPen(COLORS["acid"])
        painter.drawText(
            18,
            self.height() - 10,
            "%s 个节点   %s 条连接" % (self._summary.get("nodes", 0), self._summary.get("edges", 0)),
        )

    def _paint_capture(self, painter):
        capture = self._capture
        plot = self._plot_rect()
        painter.setPen(COLORS["muted"])
        painter.drawText(18, 23, "追踪地平线  /  性能采样")
        painter.setPen(COLORS["acid"])
        painter.drawText(
            18,
            42,
            "%s 个事件  ·  %s 个已映射  ·  %.2f ms"
            % (len(capture.events), capture.mapped_event_count, capture.duration_us / 1000.0),
        )
        if not self._lane_names:
            return
        lane_height = plot.height() / len(self._lane_names)
        palette = (COLORS["violet"], COLORS["orange"], COLORS["acid"], COLORS["cyan"], QtGui.QColor("#FF4FCB"))
        lane_index = {name: index for index, name in enumerate(self._lane_names)}
        for index, name in enumerate(self._lane_names):
            top = plot.top() + index * lane_height
            painter.fillRect(QtCore.QRectF(plot.left(), top, plot.width(), lane_height - 1), QtGui.QColor(18, 14, 27, 180 if index % 2 else 130))
            painter.setPen(QtGui.QColor("#777083"))
            label = name if len(name) < 17 else name[:14] + "…"
            painter.drawText(QtCore.QRectF(18, top, 102, lane_height), _qt_enum(QtCore.Qt, "AlignVCenter"), label.upper())
        for event in self._events:
            index = lane_index.get(event.category_name)
            if index is None:
                continue
            left = self._x_for_time(event.start_us)
            right = self._x_for_time(event.end_us)
            top = plot.top() + index * lane_height + 3
            color = QtGui.QColor(palette[index % len(palette)])
            color.setAlpha(210 if event.node_id else 105)
            painter.fillRect(QtCore.QRectF(left, top, max(1.2, right - left), max(2.0, lane_height - 7)), color)
        start, end = self._selection
        left, right = self._x_for_time(start), self._x_for_time(end)
        painter.fillRect(QtCore.QRectF(plot.left(), plot.top(), max(0, left - plot.left()), plot.height()), QtGui.QColor(2, 2, 7, 155))
        painter.fillRect(QtCore.QRectF(right, plot.top(), max(0, plot.right() - right), plot.height()), QtGui.QColor(2, 2, 7, 155))
        painter.setPen(QtGui.QPen(COLORS["acid"], 1.4))
        painter.drawLine(QtCore.QLineF(left, plot.top(), left, plot.bottom()))
        painter.drawLine(QtCore.QLineF(right, plot.top(), right, plot.bottom()))
        range_text = "时间窗 %.2f–%.2f ms" % (start / 1000.0, end / 1000.0)
        range_width = painter.fontMetrics().horizontalAdvance(range_text) + 16
        range_badge = QtCore.QRectF(
            max(plot.left() + 6, plot.right() - range_width - 7),
            plot.top() + 4,
            range_width,
            18,
        )
        painter.setPen(_qt_enum(QtCore.Qt, "NoPen"))
        painter.setBrush(QtGui.QColor(9, 7, 15, 224))
        painter.drawRoundedRect(range_badge, 4, 4)
        painter.setPen(QtGui.QColor("#B9B2C6"))
        painter.drawText(
            range_badge,
            _qt_enum(QtCore.Qt, "AlignCenter"),
            range_text,
        )

    def mousePressEvent(self, event):
        if self._capture and self._plot_rect().contains(event.position()):
            self._drag_origin = self._time_for_x(event.position().x())
            self._selection = (self._drag_origin, self._drag_origin)
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._capture and self._drag_origin is not None:
            current = self._time_for_x(event.position().x())
            self._selection = tuple(sorted((self._drag_origin, current)))
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._capture and self._drag_origin is not None:
            current = self._time_for_x(event.position().x())
            start, end = sorted((self._drag_origin, current))
            if start == end:
                end = min(self._capture.duration_us, start + max(1, self._capture.duration_us // 100))
            self._selection = (start, end)
            self._drag_origin = None
            self.rangeSelected.emit(self._selection)
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self._capture:
            self._selection = (0, self._capture.duration_us)
            self.rangeSelected.emit(self._selection)
            self.update()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


__all__ = ["PulseHorizon"]
