"""Production Root Cause Lens controls and candidate ribbon."""

from __future__ import annotations

from ..presentation import LensCandidateCardState, LensResultState
from ..qt_compat import QtCore, QtGui, QtWidgets
from .foundation import qt_enum as _qt_enum


class LensControlBar(QtWidgets.QFrame):
    directionChanged = QtCore.Signal(str)
    depthChanged = QtCore.Signal(int)
    mayaSelectRequested = QtCore.Signal()
    rerunRequested = QtCore.Signal()
    dismissRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LensBar")
        self.setAccessibleName("根因透镜追踪控制")
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 14, 8)
        layout.setSpacing(9)
        mark = QtWidgets.QLabel("◉  根因透镜")
        mark.setObjectName("LensMark")
        layout.addWidget(mark)
        self.focus_label = QtWidgets.QLabel("尚未聚焦")
        self.focus_label.setObjectName("LensFocus")
        self.focus_label.setMinimumWidth(220)
        layout.addWidget(self.focus_label)
        layout.addStretch(1)
        self.direction_label = QtWidgets.QLabel("追踪方向")
        self.direction_label.setObjectName("LensControlLabel")
        layout.addWidget(self.direction_label)
        self.upstream_button = QtWidgets.QPushButton("上游")
        self.upstream_button.setObjectName("LensToggle")
        self.upstream_button.setCheckable(True)
        self.upstream_button.clicked.connect(
            lambda: self.set_direction("upstream", emit=True)
        )
        layout.addWidget(self.upstream_button)
        self.downstream_button = QtWidgets.QPushButton("影响域")
        self.downstream_button.setObjectName("LensToggle")
        self.downstream_button.setCheckable(True)
        self.downstream_button.clicked.connect(
            lambda: self.set_direction("downstream", emit=True)
        )
        layout.addWidget(self.downstream_button)
        self.depth_label = QtWidgets.QLabel("深度")
        self.depth_label.setObjectName("LensControlLabel")
        layout.addWidget(self.depth_label)
        self.depth_spin = QtWidgets.QSpinBox()
        self.depth_spin.setRange(1, 8)
        self.depth_spin.setValue(4)
        self.depth_spin.setObjectName("LensDepth")
        self.depth_spin.valueChanged.connect(self.depthChanged)
        layout.addWidget(self.depth_spin)
        self.maya_select_button = QtWidgets.QPushButton("在 Maya 中选择")
        self.maya_select_button.setObjectName("LensSecondary")
        self.maya_select_button.clicked.connect(self.mayaSelectRequested)
        layout.addWidget(self.maya_select_button)
        rerun = QtWidgets.QPushButton("重新追踪")
        rerun.setObjectName("LensPrimary")
        rerun.clicked.connect(self.rerunRequested)
        layout.addWidget(rerun)
        close = QtWidgets.QPushButton("×")
        close.setObjectName("LensClose")
        close.setToolTip("关闭根因透镜")
        close.clicked.connect(self.dismissRequested)
        layout.addWidget(close)
        self.set_direction("upstream")

    @property
    def direction(self) -> str:
        return "upstream" if self.upstream_button.isChecked() else "downstream"

    @property
    def depth(self) -> int:
        return self.depth_spin.value()

    def set_direction(self, direction: str, *, emit: bool = False) -> None:
        if direction not in {"upstream", "downstream"}:
            raise ValueError("不支持的根因透镜方向：%s" % direction)
        upstream = direction == "upstream"
        self.upstream_button.setChecked(upstream)
        self.downstream_button.setChecked(not upstream)
        if emit:
            self.directionChanged.emit(direction)

    def set_focus(self, name: str, tooltip: str = "") -> None:
        self.focus_label.setText(str(name) or "尚未聚焦")
        self.focus_label.setToolTip(str(tooltip))

    def set_compact(self, compact: bool) -> None:
        self.focus_label.setVisible(not compact)
        self.direction_label.setVisible(not compact)
        self.depth_label.setVisible(not compact)
        self.maya_select_button.setVisible(not compact)


class LensCandidateCard(QtWidgets.QFrame):
    activated = QtCore.Signal(object)

    def __init__(self, state: LensCandidateCardState, parent=None):
        super().__init__(parent)
        self.candidate = state.candidate
        self.setObjectName("CandidateCard")
        self.setMinimumWidth(205)
        self.setMaximumWidth(255)
        self.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.setFocusPolicy(_qt_enum(QtCore.Qt, "StrongFocus"))
        self.setAccessibleName("根因候选 %s，%s" % (state.name, state.signal))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(13, 9, 13, 9)
        layout.setSpacing(3)
        signal = QtWidgets.QLabel(state.signal)
        signal.setObjectName("CandidateSignal")
        layout.addWidget(signal)
        name = QtWidgets.QLabel(state.name)
        name.setObjectName("CandidateName")
        name.setToolTip(state.name)
        layout.addWidget(name)
        detail = QtWidgets.QLabel(state.detail)
        detail.setObjectName("CandidateDetail")
        layout.addWidget(detail)
        self.setToolTip(state.tooltip)

    def mousePressEvent(self, event):
        self.activated.emit(self.candidate)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (
            _qt_enum(QtCore.Qt, "Key_Return"),
            _qt_enum(QtCore.Qt, "Key_Space"),
        ):
            self.activated.emit(self.candidate)
            event.accept()
            return
        super().keyPressEvent(event)


class LensRibbon(QtWidgets.QFrame):
    candidateActivated = QtCore.Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LensRibbon")
        self.setFixedHeight(112)
        self.setMinimumWidth(0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.setAccessibleName("根因候选横向证据带")
        outer = QtWidgets.QHBoxLayout(self)
        outer.setContentsMargins(18, 10, 12, 10)
        outer.setSpacing(12)
        marker = QtWidgets.QFrame()
        marker.setObjectName("LensMarker")
        marker.setFixedWidth(146)
        marker_layout = QtWidgets.QVBoxLayout(marker)
        marker_layout.setContentsMargins(10, 4, 10, 4)
        marker_layout.setSpacing(2)
        title = QtWidgets.QLabel("根因候选")
        title.setObjectName("LensRibbonTitle")
        marker_layout.addWidget(title)
        self.summary = QtWidgets.QLabel("结构推断 · 尚未实测")
        self.summary.setObjectName("LensDisclaimer")
        self.summary.setWordWrap(True)
        marker_layout.addWidget(self.summary)
        outer.addWidget(marker)
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setObjectName("LensScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumWidth(0)
        self.scroll.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding
        )
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(
            _qt_enum(QtCore.Qt, "ScrollBarAsNeeded")
        )
        self.scroll.setVerticalScrollBarPolicy(
            _qt_enum(QtCore.Qt, "ScrollBarAlwaysOff")
        )
        self.host = QtWidgets.QWidget()
        self.cards = QtWidgets.QHBoxLayout(self.host)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(8)
        self.cards.addStretch(1)
        self.scroll.setWidget(self.host)
        outer.addWidget(self.scroll, 1)

    def minimumSizeHint(self):
        return QtCore.QSize(300, 112)

    def sizeHint(self):
        return QtCore.QSize(900, 112)

    def set_state(self, state: LensResultState) -> None:
        while self.cards.count() > 1:
            item = self.cards.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        for card_state in state.cards:
            card = LensCandidateCard(card_state)
            card.activated.connect(self.candidateActivated)
            self.cards.insertWidget(self.cards.count() - 1, card)
        self.summary.setText(state.summary)
        self.summary.setToolTip(state.summary_tooltip)
        self.setVisible(True)


__all__ = ["LensCandidateCard", "LensControlBar", "LensRibbon"]
