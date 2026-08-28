"""Dynamic production view for the time-sliced Maya scene probe."""

from __future__ import annotations

from ..qt_compat import QtCore, QtGui, QtWidgets


class SceneCaptureSweep(QtWidgets.QWidget):
    """Paint a compact forensic pipeline without owning capture semantics."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CaptureSweep")
        self.setMinimumWidth(220)
        self.setMaximumWidth(420)
        self.setFixedHeight(34)
        self._phase = 0.0
        self._fraction = 0.0
        self._determinate = False
        self._cancelling = False
        self._motion_enabled = True
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(48)
        self._timer.timeout.connect(self._tick)

    def set_motion_enabled(self, enabled: bool) -> None:
        self._motion_enabled = bool(enabled)
        if self.isVisible() and self._motion_enabled:
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def set_capture_state(
        self,
        *,
        completed: int = 0,
        total: int = 0,
        cancelling: bool = False,
    ) -> None:
        self._cancelling = bool(cancelling)
        self._determinate = total > 0
        self._fraction = (
            max(0.0, min(1.0, completed / float(total))) if total > 0 else 0.0
        )
        if self._motion_enabled:
            self._timer.start()
        self.update()

    def stop(self) -> None:
        self._timer.stop()
        self._phase = 0.0
        self._fraction = 0.0
        self._determinate = False
        self._cancelling = False
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.025) % 1.0
        self.update()

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.rect().adjusted(2, 5, -2, -5)
        count = 7
        gap = 7.0
        cell_width = (rect.width() - gap * (count - 1)) / count
        active = (
            self._fraction * (count - 1)
            if self._determinate
            else self._phase * (count + 1) - 1
        )
        base = QtGui.QColor("#2B2138")
        signal = QtGui.QColor("#FF6A2A" if self._cancelling else "#48D7FF")
        acid = QtGui.QColor("#FF9A6D" if self._cancelling else "#C8FF3D")
        center_y = rect.center().y()
        painter.setPen(QtGui.QPen(QtGui.QColor("#44315C"), 1.0))
        painter.drawLine(
            QtCore.QPointF(rect.left() + cell_width / 2, center_y),
            QtCore.QPointF(rect.right() - cell_width / 2, center_y),
        )
        for index in range(count):
            x = rect.left() + index * (cell_width + gap)
            cell = QtCore.QRectF(x, rect.top(), cell_width, rect.height())
            distance = abs(index - active)
            color = base
            if distance < 0.85:
                color = signal
            elif self._determinate and index <= active:
                color = QtGui.QColor("#7148A2")
            painter.setPen(QtGui.QPen(color.lighter(130), 1.0))
            painter.setBrush(QtGui.QColor(color.red(), color.green(), color.blue(), 62))
            painter.drawRoundedRect(cell, 4, 4)
            if distance < 0.85:
                dot = QtCore.QPointF(cell.center().x(), cell.center().y())
                painter.setPen(QtCore.Qt.NoPen)
                painter.setBrush(acid)
                painter.drawEllipse(dot, 2.7, 2.7)


class SceneCaptureStrip(QtWidgets.QFrame):
    """Chinese loading/cancelling surface for SceneCaptureEvent rendering."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CaptureStrip")
        self.setAccessibleName("场景探针分片捕获状态")
        self.setFixedHeight(64)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 16, 8)
        layout.setSpacing(13)
        self.mark = QtWidgets.QLabel("▦  场景探针")
        self.mark.setObjectName("CaptureMark")
        layout.addWidget(self.mark)
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(1)
        self.heading = QtWidgets.QLabel("建立稳定场景快照")
        self.heading.setObjectName("CaptureHeading")
        text.addWidget(self.heading)
        self.meta = QtWidgets.QLabel("节点身份、DAG / DG、引用与依赖正在分片读取")
        self.meta.setObjectName("CaptureMeta")
        text.addWidget(self.meta)
        layout.addLayout(text)
        layout.addStretch(1)
        self.sweep = SceneCaptureSweep()
        layout.addWidget(self.sweep, 1)
        self.progress = QtWidgets.QLabel("准备探测")
        self.progress.setObjectName("CaptureProgress")
        self.progress.setMinimumWidth(118)
        layout.addWidget(self.progress)
        self.boundary = QtWidgets.QLabel("只读采集\n旧快照受保护")
        self.boundary.setObjectName("CaptureBoundary")
        self.boundary.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        layout.addWidget(self.boundary)
        self.setVisible(False)

    def start(self, *, required: bool = False) -> None:
        self.heading.setText("执行后强制复检" if required else "建立稳定场景快照")
        self.meta.setText(
            "复检完成前不会提交变更结论"
            if required
            else "节点身份、DAG / DG、引用与依赖正在分片读取"
        )
        self.progress.setProperty("state", "required" if required else "active")
        self.progress.setText("强制验证" if required else "准备探测")
        self.sweep.set_capture_state()
        self._refresh_style()
        self.setVisible(True)

    def update_progress(self, message: str, completed: int, total: int) -> None:
        self.heading.setText(message or "分片读取场景")
        self.progress.setProperty("state", "active")
        self.progress.setText(
            "%s / %s" % (completed, total) if total else "已发现 %s 项" % completed
        )
        self.sweep.set_capture_state(completed=completed, total=total)
        self._refresh_style()

    def show_cancelling(self) -> None:
        self.heading.setText("正在安全取消场景捕获")
        self.meta.setText("将在下一个分片边界停止，部分快照不会进入当前调查")
        self.progress.setProperty("state", "cancelling")
        self.progress.setText("等待安全边界")
        self.sweep.set_capture_state(cancelling=True)
        self._refresh_style()
        self.setVisible(True)

    def clear(self) -> None:
        self.sweep.stop()
        self.setVisible(False)

    def set_motion_enabled(self, enabled: bool) -> None:
        self.sweep.set_motion_enabled(enabled)

    def set_compact(self, compact: bool) -> None:
        self.meta.setVisible(not compact)
        self.boundary.setVisible(not compact)
        self.mark.setText("▦  探针" if compact else "▦  场景探针")

    def _refresh_style(self) -> None:
        self.progress.style().unpolish(self.progress)
        self.progress.style().polish(self.progress)


__all__ = ["SceneCaptureStrip", "SceneCaptureSweep"]
