"""Spectral Scene Atlas — the first MayaScope forensic workspace.

Visual route: an instrument panel rather than a form. The graph is the stage;
evidence and actions orbit it. Motion communicates scanning and graph activity,
while violet/orange/chartreuse spectra encode topology, risk, and selection.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
import sys
import threading
from typing import Dict, Iterable, Optional, Sequence, Tuple

from ..actions import MayaChangeExecutor, plan_for_issue, plan_for_issues
from ..application import (
    InvestigationCoordinator,
    InvestigationTransition,
    RuntimeCaptureController,
    RuntimeCaptureEvent,
    SceneCaptureController,
    SceneCaptureEvent,
    SceneCaptureStateError,
    resolve_host_selection,
)
from ..analysis.delta import SceneDelta, compare_snapshots
from ..analysis.incidents import Incident
from ..analysis.graph import (
    alias_graph_indexes,
    invalidate_graph_indexes,
)
from ..analysis.config import ClinicConfigError, ClinicEnvironment, load_environment_from_env
from ..analysis.lens import RootCauseCandidate
from ..analysis.runtime import analyze_runtime
from ..analysis.pulse import node_stats
from ..analysis.rules import Issue, Severity
from ..analysis.counterfactual import CounterfactualReport
from ..analysis.ddmin import DeltaDebugStep
from ..collectors import (
    CaptureCancelled,
    CounterfactualRun,
    MayaSceneCaptureSession,
    MayaRuntimeCaptureSession,
    MayaSelectionBridge,
    MayaNodeStateExperiment,
    SceneChangedDuringCapture,
    RuntimeCaptureCancelled,
    RuntimeChangedDuringCapture,
    capture_scene,
    plan_node_state_experiment,
    profile_callable,
)
from ..model import SceneSnapshot
from ..host_health import HostHealth, collect_host_health
from ..presentation import (
    WorkspacePresentationState,
    present_lens_candidate,
    present_lens_result,
)
from ..qt_compat import QtCore, QtGui, QtWidgets
from ..runtime_log import log_event
from ..runner import (
    build_post_open_bisect_plan,
    build_pre_open_ascii_bisect_plan,
    load_bisect_journal,
)
from ..storage import ExperimentStore, SnapshotStore
from .atlas import MAX_RENDER_NODES, SpectralAtlasView
from .bisect import BisectPrism
from .clinic import SceneClinicView
from .capture import SceneCaptureStrip
from .foundation import (
    COLORS,
    confirm_action as _confirm_action,
    ensure_ui_fonts as _ensure_ui_fonts,
    qt_enum as _qt_enum,
)
from .investigation_renderer import render_atlas_transition
from .lens import LensControlBar, LensRibbon
from .profiler import PulseHorizon
from .project_gate import ProjectGateStrip
from .runtime import RuntimeConstellationStrip
from .workers import BisectWorker, ClinicWorker, ProjectQueueWorker


WINDOW_OBJECT_NAME = "MayaScopeSpectralWorkspace"
_WINDOW = None








class DeltaStrip(QtWidgets.QFrame):
    focusRequested = QtCore.Signal()
    dismissRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DeltaStrip")
        self.setFixedHeight(48)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 6, 12, 6)
        layout.setSpacing(12)
        mark = QtWidgets.QLabel("△  差异场")
        mark.setObjectName("DeltaMark")
        layout.addWidget(mark)
        self.context = QtWidgets.QLabel("尚未对比")
        self.context.setObjectName("DeltaContext")
        layout.addWidget(self.context)
        layout.addStretch(1)
        self.summary = QtWidgets.QLabel("")
        self.summary.setObjectName("DeltaSummary")
        layout.addWidget(self.summary)
        focus = QtWidgets.QPushButton("聚焦变更")
        focus.setObjectName("DeltaFocus")
        focus.clicked.connect(self.focusRequested)
        layout.addWidget(focus)
        close = QtWidgets.QPushButton("×")
        close.setObjectName("LensClose")
        close.setToolTip("关闭对比证据")
        close.clicked.connect(self.dismissRequested)
        layout.addWidget(close)

    def set_delta(self, delta: SceneDelta):
        summary = delta.summary()
        self.context.setText(
            "%s  →  %s" % (delta.before_snapshot_id[:8], delta.after_snapshot_id[:8])
        )
        if delta.is_empty:
            self.summary.setText("未发现结构变化")
            self.summary.setProperty("clean", True)
        else:
            self.summary.setText(
                "节点 +%s / −%s   %s 项修改   %s 次重连   引用 %s 项   外部依赖 %s 项   插件幽灵 %s 项   设置/状态 %s 项   连接 +%s / −%s"
                % (
                    summary["nodes_added"],
                    summary["nodes_removed"],
                    summary["nodes_modified"],
                    summary["rewires"],
                    len(delta.reference_changes),
                    len(delta.external_dependency_changes),
                    len(delta.unknown_plugin_changes),
                    summary["scene_settings_modified"] + summary["scene_lifecycle_modified"],
                    summary["edges_added"],
                    summary["edges_removed"],
                )
            )
            self.summary.setProperty("clean", False)
        self.summary.style().unpolish(self.summary)
        self.summary.style().polish(self.summary)
        self.setVisible(True)




class RegressionRiftCanvas(QtWidgets.QWidget):
    """Baseline/current evaluation samples split around a luminous rift."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(220)
        self.setFixedHeight(54)
        self._performance = None
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(46)

    def set_performance(self, performance):
        self._performance = performance if performance and performance.get("comparable") else None
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
        if not performance:
            painter.setPen(COLORS["muted"])
            painter.drawText(bounds, _qt_enum(QtCore.Qt, "AlignCenter"), "暂无成对性能证据")
            return
        baseline = tuple(performance["baseline"]["samples_us"])
        current = tuple(performance["current"]["samples_us"])
        values = baseline + current
        low, high = min(values), max(values)
        span = max(1.0, float(high - low))

        def y(value):
            return bounds.bottom() - (float(value) - low) / span * bounds.height()

        count = max(len(baseline), len(current), 2)
        step = bounds.width() / float(max(1, count - 1))
        current_color = COLORS["orange"] if performance["regressed"] else COLORS["cyan"]
        for series, color in ((baseline, COLORS["violet"]), (current, current_color)):
            points = [QtCore.QPointF(bounds.left() + i * step, y(value)) for i, value in enumerate(series)]
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
        self.identity = QtWidgets.QLabel("签名基线")
        self.identity.setObjectName("RegressionMeta")
        mark_box.addWidget(self.identity)
        layout.addLayout(mark_box)
        self.canvas = RegressionRiftCanvas()
        layout.addWidget(self.canvas, 1)
        result = QtWidgets.QVBoxLayout()
        self.verdict = QtWidgets.QLabel("尚无证据")
        self.verdict.setObjectName("RegressionVerdict")
        self.detail = QtWidgets.QLabel("")
        self.detail.setObjectName("RegressionMeta")
        result.addWidget(self.verdict)
        result.addWidget(self.detail)
        layout.addLayout(result)
        close = QtWidgets.QPushButton("×")
        close.setObjectName("LensClose")
        close.setToolTip("关闭回归证据")
        close.clicked.connect(self.dismissRequested)
        layout.addWidget(close)

    def set_report(self, payload):
        regression = payload["regression"]
        performance = regression.get("performance", {})
        self.canvas.set_performance(performance)
        failed = bool(regression.get("gate_failed"))
        self.verdict.setText("检测到回归裂隙" if failed else "基线保持稳定")
        self.verdict.setProperty("failed", failed)
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        new = len(regression.get("new_findings", ()))
        escalated = len(regression.get("escalated_findings", ()))
        resolved = len(regression.get("resolved_findings", ()))
        perf = "无性能配对"
        if performance.get("comparable"):
            perf = "%+.2f ms  ·  %+.1f%%" % (
                performance.get("delta_us", 0.0) / 1000.0,
                performance.get("slowdown_ratio", 0.0) * 100.0,
            )
        self.detail.setText("新增 %s · 升级 %s · 已解决 %s · %s" % (new, escalated, resolved, perf))
        checksum = str(regression.get("baseline_report_sha256", ""))
        self.identity.setText("基线 %s / 当前 %s" % (checksum[:8].upper(), str(payload.get("report_sha256", ""))[:8].upper()))
        self.setVisible(True)

    def set_motion_enabled(self, enabled):
        self.canvas.set_motion_enabled(enabled)

    def clear(self):
        self.canvas.set_performance(None)
        self.verdict.setText("尚无证据")
        self.detail.clear()
        self.identity.setText("签名基线")


class CounterfactualSpark(QtWidgets.QWidget):
    """Paired AB/BA measurements as a compact spectral barcode."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(210)
        self.setMaximumWidth(310)
        self.setFixedHeight(50)
        self._report: Optional[CounterfactualReport] = None
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(45)

    def set_report(self, report: CounterfactualReport):
        self._report = report
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
        report = self._report
        if not report:
            return
        pairs = {}
        for item in report.observations:
            pairs.setdefault(item.pair_index, {})[item.condition] = item.wall_time_us
        peak = max(
            (value for values in pairs.values() for value in values.values()),
            default=1,
        ) or 1
        plot = self.rect().adjusted(8, 5, -8, -7)
        slot = plot.width() / max(1, len(pairs))
        variant_color = COLORS["acid"] if report.verdict == "improved" else COLORS["orange"]
        for ordinal, pair_index in enumerate(sorted(pairs)):
            values = pairs[pair_index]
            center = plot.left() + slot * (ordinal + 0.5)
            for offset, condition, color in (
                (-4.5, "baseline", COLORS["violet"]),
                (1.0, "variant", variant_color),
            ):
                height = plot.height() * values.get(condition, 0) / float(peak)
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
        self.target = QtWidgets.QLabel("尚未实验")
        self.target.setObjectName("CounterfactualTarget")
        self.design = QtWidgets.QLabel("成对 AB / BA 设计")
        self.design.setObjectName("CounterfactualDesign")
        identity.addWidget(self.target)
        identity.addWidget(self.design)
        layout.addLayout(identity)
        self.spark = CounterfactualSpark()
        layout.addWidget(self.spark, 1)
        result = QtWidgets.QVBoxLayout()
        result.setSpacing(1)
        self.result_metric = QtWidgets.QLabel("—")
        self.result_metric.setObjectName("CounterfactualMetric")
        self.interval = QtWidgets.QLabel("")
        self.interval.setObjectName("CounterfactualInterval")
        result.addWidget(self.result_metric)
        result.addWidget(self.interval)
        layout.addLayout(result)
        close = QtWidgets.QPushButton("×")
        close.setObjectName("LensClose")
        close.setToolTip("关闭反事实证据")
        close.clicked.connect(self.dismissRequested)
        layout.addWidget(close)

    def set_report(self, report: CounterfactualReport):
        self.spark.set_report(report)
        self.target.setText(report.target_name)
        self.design.setText(
            "%s 组配对 · %s 次预热 · 状态已恢复"
            % (report.pair_count, report.warmup_count)
        )
        signed = "%+.1f%%" % report.benefit_percent
        verdict = {"improved": "改善", "regressed": "变慢", "neutral": "无显著变化", "inconclusive": "证据不足"}.get(report.verdict, report.verdict)
        self.result_metric.setText("%s  ·  %s" % (verdict, signed))
        self.result_metric.setProperty("verdict", report.verdict)
        self.result_metric.style().unpolish(self.result_metric)
        self.result_metric.style().polish(self.result_metric)
        self.interval.setText(
            "95%% 区间  %+.1f%% … %+.1f%%  ·  墙钟时间"
            % (report.benefit_ci_low_percent, report.benefit_ci_high_percent)
        )
        self.setVisible(True)

    def set_motion_enabled(self, enabled: bool):
        self.spark.set_motion_enabled(enabled)

    def clear(self):
        self.spark.set_report(None)
        self.target.setText("尚未实验")
        self.design.setText("成对 AB / BA 设计")
        self.result_metric.setText("—")
        self.interval.clear()


class HostHealthBeacon(QtWidgets.QWidget):
    activated = QtCore.Signal()

    def __init__(self, health: HostHealth, parent=None):
        super().__init__(parent)
        self.health = health
        self._phase = 0.0
        self.setFixedSize(154, 34)
        self.setFocusPolicy(_qt_enum(QtCore.Qt, "StrongFocus"))
        self.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.setAccessibleName("MayaScope 宿主健康状态")
        self.setToolTip("查看 Maya、PySide、后台探针与模块详情")
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(55)

    def set_motion_enabled(self, enabled: bool):
        if enabled:
            self._timer.start(55)
        else:
            self._timer.stop()
            self._phase = 0.0
            self.update()

    def _tick(self):
        self._phase = (self._phase + 0.025) % 1.0
        self.update()

    def mousePressEvent(self, event):
        if event.button() == _qt_enum(QtCore.Qt, "LeftButton"):
            self.activated.emit()
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (_qt_enum(QtCore.Qt, "Key_Return"), _qt_enum(QtCore.Qt, "Key_Space")):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        ready = self.health.ready
        edge = COLORS["acid"] if ready else COLORS["orange"]
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0, QtGui.QColor("#142108" if ready else "#281008"))
        gradient.setColorAt(1, QtGui.QColor("#0A1014"))
        painter.setBrush(gradient)
        painter.setPen(QtGui.QPen(QtGui.QColor(edge), 1.0))
        painter.drawRoundedRect(rect, 8, 8)
        center = QtCore.QPointF(17, rect.center().y())
        pulse = 4.0 + 1.8 * (0.5 + 0.5 * math.sin(self._phase * math.tau))
        halo = QtGui.QColor(edge)
        halo.setAlpha(50)
        painter.setPen(_qt_enum(QtCore.Qt, "NoPen"))
        painter.setBrush(halo)
        painter.drawEllipse(center, pulse + 4.0, pulse + 4.0)
        painter.setBrush(edge)
        painter.drawEllipse(center, 3.0, 3.0)
        painter.setPen(COLORS["text"])
        font = painter.font()
        font.setBold(True)
        font.setPointSize(8)
        painter.setFont(font)
        label = "宿主 %s" % self.health.maya_version
        painter.drawText(QtCore.QRectF(30, 6, 74, 13), label)
        painter.setPen(edge)
        font.setPointSize(6)
        painter.setFont(font)
        state = "就绪 / API %s" % self.health.maya_api[-4:] if ready else "需要检查"
        painter.drawText(QtCore.QRectF(30, 19, 116, 10), state)


def _presentation_field(name):
    """Temporary compatibility alias during the incremental state migration."""
    return property(
        lambda self: getattr(self._presentation, name),
        lambda self, value: setattr(
            self, "_presentation", self._presentation.update(**{name: value})
        ),
    )


class MayaScopeWorkspace(QtWidgets.QMainWindow):
    hostSelectionChanged = QtCore.Signal(object)

    _snapshot = _presentation_field("snapshot")
    _issues = _presentation_field("issues")
    _clinic_report = _presentation_field("clinic_report")
    _incidents = _presentation_field("incidents")
    _selected_issue = _presentation_field("selected_issue")
    _selected_incident = _presentation_field("selected_incident")
    _focus_node_id = _presentation_field("focus_node_id")
    _lens_report = _presentation_field("lens_report")
    _measured_report = _presentation_field("measured_report")
    _selected_candidate = _presentation_field("selected_candidate")
    _profiler_capture = _presentation_field("profiler_capture")
    _counterfactual_run = _presentation_field("counterfactual_run")
    _counterfactual_record = _presentation_field("counterfactual_record")
    _pulse_range = _presentation_field("pulse_range")
    _delta = _presentation_field("delta")
    _delta_before = _presentation_field("delta_before")
    _runtime_snapshot = _presentation_field("runtime_snapshot")
    _runtime_report = _presentation_field("runtime_report")

    def __init__(self, parent=None, clinic_environment: Optional[ClinicEnvironment] = None):
        super().__init__(parent)
        self._presentation = WorkspacePresentationState()
        self._investigation = InvestigationCoordinator()
        _ensure_ui_fonts()
        self.setObjectName(WINDOW_OBJECT_NAME)
        self.setWindowTitle("MayaScope · 光谱因果场景图谱")
        self.resize(1480, 900)
        self._clinic_config_error = ""
        if clinic_environment is not None:
            self._clinic_environment = clinic_environment
        else:
            try:
                self._clinic_environment = load_environment_from_env()
            except ClinicConfigError as exc:
                self._clinic_environment = ClinicEnvironment.default()
                self._clinic_config_error = str(exc)
        self._clinic_registry = self._clinic_environment.registry
        self._clinic_profiles = self._clinic_environment.profiles
        self._regression_payload = None
        self._project_audit_payload = None
        self._project_queue_payload = None
        self._project_queue_plan_path = None
        self._project_queue_journal_path = None
        self._project_queue_report_dir = None
        self._project_queue_report_path = None
        self._project_queue_thread = None
        self._project_queue_worker = None
        self._project_queue_cancel_event = None
        self._close_after_project_queue = False
        self._runtime_capture = RuntimeCaptureController(
            MayaRuntimeCaptureSession,
            analyze_runtime,
            cancelled_errors=(RuntimeCaptureCancelled,),
            stale_errors=(RuntimeChangedDuringCapture,),
        )
        self._scene_capture = SceneCaptureController(
            MayaSceneCaptureSession,
            cancelled_errors=(CaptureCancelled,),
            stale_errors=(SceneChangedDuringCapture,),
        )
        self._selection_bridge = None
        self._host_identity_index = {}
        self._pending_host_selection: Tuple[str, ...] = ()
        self._selection_sync_timer = QtCore.QTimer(self)
        self._selection_sync_timer.setSingleShot(True)
        self._selection_sync_timer.setInterval(45)
        self._selection_sync_timer.timeout.connect(self._apply_host_selection)
        self._last_change_plan = None
        self._last_execution_receipt = None
        self._host_health = collect_host_health()
        self._bisect_plan = None
        self._bisect_result = None
        self._bisect_cancel_event = None
        self._bisect_thread = None
        self._bisect_worker = None
        self._bisect_journal_path = None
        self._close_after_bisect = False
        self._capture_after = None
        self._capture_required = False
        self._capture_timer = QtCore.QTimer(self)
        self._capture_timer.setInterval(0)
        self._capture_timer.timeout.connect(self._advance_capture)
        self._runtime_timer = QtCore.QTimer(self)
        self._runtime_timer.setInterval(0)
        self._runtime_timer.timeout.connect(self._advance_runtime_capture)
        self._clinic_thread = None
        self._clinic_worker = None
        self._clinic_cancel_event = None
        self._clinic_job = None
        self._close_after_clinic = False
        self._store = SnapshotStore()
        self._experiment_store = ExperimentStore()
        self._build_ui()
        self._apply_style()
        self.hostSelectionChanged.connect(self._queue_host_selection)
        self._selection_bridge = MayaSelectionBridge(
            lambda names: self.hostSelectionChanged.emit(names)
        )
        # Explicitly override the initial wide toolbar size hint; resizeEvent
        # then collapses secondary controls for compact Maya layouts.
        self.setMinimumSize(800, 560)
        QtCore.QTimer.singleShot(0, lambda: self._set_selection_sync_enabled(True))
        QtCore.QTimer.singleShot(80, self._auto_capture)

    def _build_ui(self):
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)

        top = QtWidgets.QFrame()
        top.setObjectName("TopBar")
        top_layout = QtWidgets.QHBoxLayout(top)
        top_layout.setContentsMargins(22, 14, 18, 14)
        brand = QtWidgets.QLabel("MAYA<span style='color:#C8FF3D'>SCOPE</span>")
        brand.setObjectName("Brand")
        brand.setTextFormat(_qt_enum(QtCore.Qt, "RichText"))
        top_layout.addWidget(brand)
        self.mode_label = QtWidgets.QLabel("场景图谱  /  实时取证")
        self.mode_label.setObjectName("ModeLabel")
        top_layout.addWidget(self.mode_label)
        self.host_beacon = HostHealthBeacon(self._host_health)
        self.host_beacon.activated.connect(self._show_host_health)
        top_layout.addWidget(self.host_beacon)
        top_layout.addStretch(1)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("搜索节点名称或类型…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        top_layout.addWidget(self.search)
        self.selection_sync_button = QtWidgets.QPushButton("MAYA · 联动")
        self.selection_sync_button.setObjectName("SelectionSyncButton")
        self.selection_sync_button.setCheckable(True)
        self.selection_sync_button.setChecked(True)
        self.selection_sync_button.setToolTip(
            "双向同步 Maya 与场景图谱的节点选择；45 ms 去抖并防止回调重入"
        )
        self.selection_sync_button.toggled.connect(self._set_selection_sync_enabled)
        top_layout.addWidget(self.selection_sync_button)
        self.fit_button = QtWidgets.QPushButton("适配图谱")
        self.fit_button.clicked.connect(self._fit)
        top_layout.addWidget(self.fit_button)
        self.capture_button = QtWidgets.QPushButton("捕获场景")
        self.capture_button.setObjectName("PrimaryButton")
        self.capture_button.clicked.connect(lambda: self.capture())
        self.motion_button = QtWidgets.QPushButton("动效开启")
        self.motion_button.setObjectName("MotionButton")
        self.motion_button.setCheckable(True)
        self.motion_button.setChecked(True)
        self.motion_button.setToolTip("切换环境动效与因果路径动画")
        self.motion_button.toggled.connect(self._set_motion_enabled)
        top_layout.addWidget(self.motion_button)
        self.archive_button = QtWidgets.QPushButton("归档")
        self.archive_button.setObjectName("ArchiveButton")
        self.archive_button.setToolTip("原子归档当前带校验和的场景快照")
        self.archive_button.setEnabled(False)
        self.archive_button.clicked.connect(self._archive_snapshot)
        top_layout.addWidget(self.archive_button)
        self.compare_button = QtWidgets.QPushButton("对比")
        self.compare_button.setObjectName("CompareButton")
        self.compare_button.setToolTip("将已归档快照与当前捕获进行对比")
        self.compare_button.clicked.connect(self._compare_archive)
        top_layout.addWidget(self.compare_button)
        self.regression_button = QtWidgets.QPushButton("回归")
        self.regression_button.setObjectName("RegressionButton")
        self.regression_button.setToolTip("打开带签名的场景诊所回归报告")
        self.regression_button.clicked.connect(self._open_regression_report)
        top_layout.addWidget(self.regression_button)
        self.project_gate_button = QtWidgets.QPushButton("项目门禁")
        self.project_gate_button.setObjectName("ProjectGateButton")
        self.project_gate_button.setToolTip("打开自校验的多场景项目审计包")
        self.project_gate_button.clicked.connect(self._open_project_audit)
        top_layout.addWidget(self.project_gate_button)
        self.project_queue_button = QtWidgets.QPushButton("批量审计")
        self.project_queue_button.setObjectName("ProjectQueueButton")
        self.project_queue_button.setToolTip("打开签名场景计划并在后台串行审计")
        self.project_queue_button.clicked.connect(self._open_project_queue)
        top_layout.addWidget(self.project_queue_button)
        self.runtime_button = QtWidgets.QPushButton("运行时")
        self.runtime_button.setObjectName("RuntimeButton")
        self.runtime_button.setToolTip("扫描表达式、scriptJob、插件与不透明回调")
        self.runtime_button.setEnabled(False)
        self.runtime_button.clicked.connect(self._start_runtime_capture)
        top_layout.addWidget(self.runtime_button)
        self.bisect_button = QtWidgets.QPushButton("X  故障二分")
        self.bisect_button.setObjectName("BisectButton")
        self.bisect_button.setToolTip(
            "在后台串行 Maya 副本中隔离崩溃或场景损坏原因"
        )
        self.bisect_button.clicked.connect(self._start_bisect)
        top_layout.addWidget(self.bisect_button)
        top_layout.addWidget(self.capture_button)
        outer.addWidget(top)

        self.capture_strip = SceneCaptureStrip()
        outer.addWidget(self.capture_strip)

        self.lens_bar = LensControlBar()
        self.lens_bar.directionChanged.connect(self._set_lens_direction)
        self.lens_bar.depthChanged.connect(self._run_lens)
        self.lens_bar.mayaSelectRequested.connect(self._select_focus_in_maya)
        self.lens_bar.rerunRequested.connect(self._run_lens)
        self.lens_bar.dismissRequested.connect(self._close_lens)
        self.lens_bar.setVisible(False)
        outer.addWidget(self.lens_bar)

        splitter = QtWidgets.QSplitter(_qt_enum(QtCore.Qt, "Horizontal"))
        splitter.setHandleWidth(1)
        self.atlas = SpectralAtlasView()
        self.atlas.nodeActivated.connect(self._node_selected)
        splitter.addWidget(self.atlas)

        self.clinic_view = SceneClinicView(
            self._clinic_registry,
            self._clinic_profiles,
            self._clinic_environment.source,
            self._clinic_environment.fingerprint,
        )
        self.clinic_array = self.clinic_view.rule_array
        if self._clinic_config_error:
            self.clinic_array.set_config_error(self._clinic_config_error)
        self.clinic_array.runRequested.connect(self._run_clinic)
        self.clinic_array.ruleFocusRequested.connect(self._focus_rule_signal)
        self.clinic_view.issueActivated.connect(self._select_issue)
        self.clinic_view.incidentActivated.connect(self._select_incident)
        self.clinic_view.planRequested.connect(self._preview_plan)
        self.clinic_view.rollbackRequested.connect(self._rollback_last_plan)
        self.rollback_button = self.clinic_view.rollback_button
        splitter.addWidget(self.clinic_view)
        splitter.setStretchFactor(0, 1)
        splitter.setSizes([1100, 350])
        outer.addWidget(splitter, 1)

        self.delta_strip = DeltaStrip()
        self.delta_strip.focusRequested.connect(self._focus_delta)
        self.delta_strip.dismissRequested.connect(self._dismiss_delta)
        self.delta_strip.setVisible(False)
        outer.addWidget(self.delta_strip)

        self.runtime_constellation = RuntimeConstellationStrip()
        self.runtime_constellation.focusRequested.connect(self._focus_runtime)
        self.runtime_constellation.dismissRequested.connect(self._dismiss_runtime)
        self.runtime_constellation.setVisible(False)
        outer.addWidget(self.runtime_constellation)

        self.regression_rift = RegressionRiftStrip()
        self.regression_rift.dismissRequested.connect(self._dismiss_regression)
        self.regression_rift.setVisible(False)
        outer.addWidget(self.regression_rift)

        self.project_gate = ProjectGateStrip()
        self.project_gate.sceneActivated.connect(self._select_project_scene)
        self.project_gate.sceneActivated.connect(self._select_project_queue_job)
        self.project_gate.dismissRequested.connect(self._dismiss_project_audit)
        self.project_gate.queueActionRequested.connect(self._project_queue_action)
        self.project_gate.setVisible(False)
        outer.addWidget(self.project_gate)

        self.lens_ribbon = LensRibbon()
        self.lens_ribbon.candidateActivated.connect(self._candidate_selected)
        self.lens_ribbon.setVisible(False)
        outer.addWidget(self.lens_ribbon)

        self.counterfactual_strip = CounterfactualStrip()
        self.counterfactual_strip.dismissRequested.connect(self._dismiss_counterfactual)
        self.counterfactual_strip.setVisible(False)
        outer.addWidget(self.counterfactual_strip)

        self.bisect_prism = BisectPrism()
        self.bisect_prism.cancelRequested.connect(self._cancel_bisect)
        self.bisect_prism.dismissRequested.connect(self._dismiss_bisect)
        self.bisect_prism.resumeRequested.connect(self._resume_bisect)
        self.bisect_prism.setVisible(False)
        outer.addWidget(self.bisect_prism)

        self.pulse = PulseHorizon()
        self.pulse.profileRequested.connect(self._profile_frame)
        self.pulse.counterfactualRequested.connect(self._run_counterfactual)
        self.pulse.rangeSelected.connect(self._pulse_range_selected)
        self.pulse.dismissRequested.connect(self._dismiss_profiler)
        outer.addWidget(self.pulse)
        self.status = QtWidgets.QLabel("  探针空闲")
        self.status.setObjectName("StatusLine")
        self.status.setFixedHeight(24)
        outer.addWidget(self.status)
        self._install_shortcuts()

    def _apply_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget { background: #07060D; color: #F4F0FF; font-family: "Microsoft YaHei UI", "Microsoft YaHei", "DengXian", "Segoe UI"; }
            #TopBar { background: #0D0B14; border-bottom: 1px solid #292038; }
            #Brand { font-size: 22px; font-weight: 900; letter-spacing: 2px; }
            #ModeLabel, #Eyebrow { color: #8E899C; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
            QLineEdit { min-width: 140px; padding: 9px 13px; background: #15121F; border: 1px solid #34294A; border-radius: 9px; selection-background-color: #7E3FFF; }
            QLineEdit:focus { border: 1px solid #9C5CFF; background: #1A1428; }
            QPushButton { padding: 9px 13px; background: #17131F; border: 1px solid #3A2F4A; border-radius: 8px; color: #CEC8DB; font-size: 10px; font-weight: 700; }
            QPushButton:hover { border-color: #9C5CFF; color: white; background: #211631; }
            #PrimaryButton { color: #09060F; background: #C8FF3D; border: none; padding-left: 17px; padding-right: 17px; }
            #PrimaryButton:hover { background: #DCFF83; }
            #MotionButton:checked { color: #C8FF3D; border-color: #577227; }
            #SelectionSyncButton { color: #48D7FF; border-color: #28586A; background: #0B171C; }
            #SelectionSyncButton:checked { color: #071017; border-color: #73E6FF; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #48D7FF, stop:1 #C8FF3D); }
            #SelectionSyncButton[pulse="true"] { color: #09060F; border-color: #FFFFFF; background: #F4F0FF; }
            #SelectionSyncButton:disabled { color: #44535B; border-color: #26333A; background: #0B1013; }
            #ArchiveButton { color: #48D7FF; border-color: #28586A; }
            #CompareButton { color: #C9B5E8; border-color: #49365F; }
            #RegressionButton { color: #48D7FF; border-color: #28586A; background: #0B171C; }
            #ProjectGateButton { color: #C8FF3D; border-color: #577227; background: #10190B; }
            #ProjectGateButton:hover { color: #09060F; background: #C8FF3D; border-color: #C8FF3D; }
            #ProjectQueueButton { color: #48D7FF; border-color: #28586A; background: #0B171C; }
            #ProjectQueueButton:hover { color: #071017; background: #48D7FF; border-color: #73E6FF; }
            #RuntimeButton { color: #C8FF3D; border-color: #577227; background: #10190B; }
            #RuntimeButton:disabled { color: #4E5B38; border-color: #29311F; background: #0C0F0A; }
            #BisectButton { color: #FF9A6D; border-color: #8A3C22; background: #21100B; }
            #BisectButton:hover { color: #09060F; background: #FF6A2A; border-color: #FF8D59; }
            #BisectButton:disabled { color: #705044; background: #160D0A; border-color: #3C251D; }
            #CaptureStrip { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #071A20, stop:0.42 #150C22, stop:0.78 #101708, stop:1 #21100B); border-top: 1px solid #28657A; border-bottom: 1px solid #5A356F; }
            #CaptureMark { color: #48D7FF; font-size: 11px; font-weight: 900; letter-spacing: 1px; }
            #CaptureHeading { color: #F4F0FF; font-size: 12px; font-weight: 900; }
            #CaptureMeta, #CaptureBoundary { color: #8E899C; font-size: 8px; font-weight: 700; }
            #CaptureProgress { color: #C8FF3D; font-size: 10px; font-weight: 900; letter-spacing: 1px; padding: 5px 8px; border: 1px solid #577227; border-radius: 6px; background: #10190B; }
            #CaptureProgress[state="required"] { color: #48D7FF; border-color: #28586A; background: #0B171C; }
            #CaptureProgress[state="cancelling"] { color: #FF9A6D; border-color: #8A3C22; background: #21100B; }
            #MotionButton:focus, #CandidateCard:focus, #IssueCard:focus { border: 2px solid #C8FF3D; }
            #LensBar { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #221137, stop:0.5 #120D1D, stop:1 #10180C); border-bottom: 1px solid #46305E; }
            #LensMark { color: #C8FF3D; font-size: 11px; font-weight: 900; letter-spacing: 1px; }
            #LensFocus { color: #F4F0FF; font-size: 12px; font-weight: 700; padding-left: 9px; border-left: 1px solid #5C3B7B; }
            #LensControlLabel { color: #777083; font-size: 9px; font-weight: 800; }
            #LensToggle { padding: 6px 10px; min-width: 62px; }
            #LensToggle:checked { color: #08060D; background: #9C5CFF; border-color: #B98AFF; }
            #LensDepth { background: #0D0A13; color: #F4F0FF; border: 1px solid #49365F; border-radius: 6px; padding: 4px; min-width: 42px; }
            #LensPrimary { color: #08060D; background: #C8FF3D; border-color: #C8FF3D; }
            #LensSecondary { color: #48D7FF; border-color: #28586A; }
            #LensClose { min-width: 26px; max-width: 26px; padding: 5px; color: #8E899C; }
            #LensRibbon { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #140D20, stop:1 #0A0910); border-top: 1px solid #41245F; border-bottom: 1px solid #251A31; }
            #LensMarker { border-right: 1px solid #55346F; }
            #LensRibbonTitle { color: #F4F0FF; font-size: 11px; font-weight: 900; letter-spacing: 1px; }
            #LensDisclaimer { color: #8E899C; font-size: 8px; font-weight: 700; }
            #LensScroll { background: transparent; }
            #CandidateCard { background: #171020; border: 1px solid #3E2854; border-radius: 7px; }
            #CandidateCard:hover { background: #241332; border: 1px solid #FF6A2A; }
            #CandidateSignal { color: #FF8D59; font-size: 8px; font-weight: 900; letter-spacing: 1px; }
            #CandidateName { color: #F4F0FF; font-size: 12px; font-weight: 800; }
            #CandidateDetail { color: #91899C; font-size: 9px; }
            #DeltaStrip { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #111A20, stop:0.55 #130D1A, stop:1 #1B100B); border-top: 1px solid #2A5060; border-bottom: 1px solid #4D2A1B; }
            #DeltaMark { color: #48D7FF; font-size: 10px; font-weight: 900; letter-spacing: 1px; }
            #DeltaContext { color: #8E899C; font-size: 9px; font-weight: 700; }
            #DeltaSummary { color: #FF8D59; font-size: 9px; font-weight: 900; letter-spacing: 1px; }
            #DeltaSummary[clean="true"] { color: #C8FF3D; }
            #DeltaFocus { color: #08060D; background: #48D7FF; border-color: #48D7FF; }
            #RegressionRift { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #170C25, stop:0.48 #08131A, stop:0.52 #1C1108, stop:1 #0D1710); border-top: 1px solid #694095; border-bottom: 1px solid #6B4A20; }
            #RegressionMark { color: #B98AFF; font-size: 10px; font-weight: 900; letter-spacing: 1px; }
            #RegressionMeta { color: #8E899C; font-size: 8px; font-weight: 700; letter-spacing: 0.5px; }
            #RegressionVerdict { color: #C8FF3D; font-size: 13px; font-weight: 900; letter-spacing: 1px; }
            #RegressionVerdict[failed="true"] { color: #FF6A2A; }
            #ProjectGate { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #081B21, stop:0.34 #170C25, stop:0.7 #101707, stop:1 #241008); border-top: 1px solid #2D7188; border-bottom: 1px solid #7A3A22; }
            #ProjectGateMark { color: #48D7FF; font-size: 11px; font-weight: 900; letter-spacing: 1px; }
            #ProjectGateMeta { color: #8E899C; font-size: 8px; font-weight: 700; letter-spacing: 0.5px; }
            #ProjectGateGuard { color: #C8FF3D; font-size: 7px; font-weight: 800; }
            #ProjectGateGuard[alert="true"] { color: #FF6A2A; }
            #ProjectGateVerdict { color: #C8FF3D; font-size: 13px; font-weight: 900; letter-spacing: 1px; }
            #ProjectGateVerdict[failed="true"] { color: #FF6A2A; }
            #ProjectQueueAction { color: #08060D; background: #48D7FF; border-color: #48D7FF; padding: 7px 11px; }
            #ProjectQueueAction:hover { background: #9BEAFF; }
            #ProjectQueueAction:disabled { color: #625C6A; background: #17131F; border-color: #342B40; }
            #RuntimeConstellation { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #1B0C08, stop:0.3 #140B1F, stop:0.68 #071820, stop:1 #111B08); border-top: 1px solid #7A3A22; border-bottom: 1px solid #315E6C; }
            #RuntimeMark { color: #FF8D59; font-size: 10px; font-weight: 900; letter-spacing: 1px; }
            #RuntimeMeta { color: #8E899C; font-size: 8px; font-weight: 700; letter-spacing: 0.5px; }
            #RuntimeSignal { color: #48D7FF; font-size: 13px; font-weight: 900; letter-spacing: 1px; }
            #RuntimeSignal[active="true"] { color: #FF8D59; }
            #RuntimeFocus { color: #08060D; background: #C8FF3D; border-color: #C8FF3D; }
            #CounterfactualStrip { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #182407, stop:0.38 #130D1D, stop:1 #071A20); border-top: 1px solid #6B8B22; border-bottom: 1px solid #28586A; }
            #CounterfactualMark { color: #C8FF3D; font-size: 10px; font-weight: 900; letter-spacing: 1px; }
            #CounterfactualTarget { color: #F4F0FF; font-size: 11px; font-weight: 900; }
            #CounterfactualDesign, #CounterfactualInterval { color: #8E899C; font-size: 8px; font-weight: 700; letter-spacing: 0.5px; }
            #CounterfactualMetric { color: #F4F0FF; font-size: 14px; font-weight: 900; letter-spacing: 1px; }
            #CounterfactualMetric[verdict="improved"] { color: #C8FF3D; }
            #CounterfactualMetric[verdict="regressed"] { color: #FF6A2A; }
            #CounterfactualMetric[verdict="inconclusive"] { color: #48D7FF; }
            #BisectPrism { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #241008, stop:0.34 #120B17, stop:0.72 #071820, stop:1 #101707); border-top: 1px solid #8A3C22; border-bottom: 1px solid #28586A; }
            #BisectMark { color: #FF8D59; font-size: 11px; font-weight: 900; letter-spacing: 1px; }
            #BisectMeta { color: #8E899C; font-size: 8px; font-weight: 700; letter-spacing: 0.5px; }
            #BisectSignal { color: #F4F0FF; font-size: 13px; font-weight: 900; letter-spacing: 1px; }
            #BisectSignal[outcome="pass"] { color: #48D7FF; }
            #BisectSignal[outcome="fail"] { color: #FF6A2A; }
            #BisectSignal[outcome="unresolved"] { color: #B98AFF; }
            #BisectSignal[outcome="active"] { color: #C8FF3D; }
            #BisectCancel { color: #FF9A6D; border-color: #8A3C22; padding: 6px 9px; }
            #BisectDismiss { color: #48D7FF; border-color: #28586A; padding: 6px 9px; }
            #BisectResume { color: #09060F; background: #C8FF3D; border-color: #C8FF3D; padding: 6px 9px; }
            #IssueRail { background: #0C0A12; border-left: 1px solid #292038; }
            #RailHeading { font-size: 24px; font-weight: 800; padding: 4px 0 8px 0; }
            #ClinicArray { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #120C1B, stop:0.55 #0B1015, stop:1 #13100A); border: 1px solid #342342; border-radius: 9px; }
            #ClinicTitle { color: #C8FF3D; font-size: 9px; font-weight: 900; letter-spacing: 1px; }
            #ClinicConfigBadge { color: #48D7FF; background: #0C1B21; border: 1px solid #28586A; border-radius: 4px; padding: 3px 5px; font-size: 7px; font-weight: 900; }
            #ClinicConfigBadge[error="true"] { color: #FF9A6D; background: #25120C; border-color: #8A3C22; }
            #SceneContractBand { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0C1B21, stop:0.5 #161020, stop:1 #20150B); border: 1px solid #2D3E46; border-radius: 5px; }
            #SceneContractBand[dirty="true"] { border: 1px solid #FF6A2A; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #28100B, stop:0.5 #18101C, stop:1 #241A08); }
            #SceneContractTitle { color: #C8FF3D; font-size: 7px; font-weight: 900; letter-spacing: 1px; }
            #SceneSettingChip { color: #BEEFFF; background: #0A1117; border: 1px solid #264958; border-radius: 4px; padding: 2px 5px; font-size: 7px; font-weight: 800; }
            #SceneSettingChip[alert="true"] { color: #FFD1C1; background: #2B100B; border-color: #FF6A2A; }
            #SceneDependencyChip { color: #95F3FF; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #071B25, stop:0.55 #102337, stop:1 #17132A); border: 1px solid #287C96; border-radius: 4px; padding: 3px 6px; font-size: 8px; font-weight: 900; letter-spacing: 0.35px; }
            #SceneDependencyChip:hover { color: #F4FDFF; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0A3040, stop:0.55 #18314D, stop:1 #2B1741); border-color: #48D7FF; }
            #SceneDependencyChip[alert="true"] { color: #F4FFB3; border-color: #C8FF3D; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #162908, stop:0.5 #1C2631, stop:1 #2B1B09); }
            #SceneDependencyChip[danger="true"] { color: #FFD1C1; border-color: #FF6A2A; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #351008, stop:0.5 #2D1632, stop:1 #102337); }
            #ScenePluginChip { color: #B98AFF; background: #140B20; border: 1px solid #6C399A; border-radius: 4px; padding: 2px 6px; font-size: 7px; font-weight: 900; }
            #ScenePluginChip:hover { color: #F4F0FF; background: #29113C; border-color: #B98AFF; }
            #ScenePluginChip[alert="true"] { color: #FFD1C1; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #30100B, stop:1 #29103C); border-color: #FF6A2A; }
            #SceneReferenceChip { color: #9BEAFF; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #071B23, stop:0.48 #111126, stop:1 #171022); border: 1px solid #2D7188; border-radius: 4px; padding: 3px 6px; font-size: 7px; font-weight: 900; letter-spacing: 0.4px; }
            #SceneReferenceChip:hover { color: #F4F0FF; border-color: #48D7FF; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0A2B36, stop:0.52 #1B1640, stop:1 #29133A); }
            #SceneReferenceChip[alert="true"] { color: #FFE6A6; border-color: #C8FF3D; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #13230A, stop:0.5 #1A1825, stop:1 #29170B); }
            #SceneReferenceChip[danger="true"] { color: #FFD1C1; border-color: #FF6A2A; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #351008, stop:0.45 #27102F, stop:1 #111D2B); }
            #ClinicProfile { min-width: 98px; padding: 4px 7px; color: #F4F0FF; background: #191022; border: 1px solid #67408B; border-radius: 5px; font-size: 8px; font-weight: 800; }
            #ClinicProfile QAbstractItemView { color: #F4F0FF; background: #120D1A; border: 1px solid #67408B; selection-background-color: #6F36A5; }
            #ClinicRun { color: #08060D; background: #48D7FF; border: none; padding: 5px 8px; font-size: 8px; }
            #RuleToggle { padding: 5px 6px; color: #686171; background: #0A080F; border: 1px solid #292232; font-size: 7px; }
            #RuleToggle:checked { color: #F4F0FF; background: #21132D; border-color: #9C5CFF; }
            #RuleToggle:focus { border: 2px solid #C8FF3D; }
            #RuleScroll { background: transparent; }
            #ClinicTelemetry { color: #7F7889; font-size: 8px; font-weight: 800; letter-spacing: 1px; }
            QScrollArea { background: transparent; }
            QScrollBar:vertical { width: 6px; background: transparent; }
            QScrollBar::handle:vertical { background: #493566; border-radius: 3px; min-height: 35px; }
            #IssueCard { background: #15121E; border: 1px solid #2D2639; border-radius: 11px; }
            #IssueCard:hover { border: 1px solid #9C5CFF; background: #1D1629; }
            #IssueTitle { font-size: 13px; font-weight: 700; }
            #SeverityCritical, #SeverityError { color: #FF6A2A; font-size: 9px; font-weight: 800; }
            #SeverityWarning { color: #F2C94C; font-size: 9px; font-weight: 800; }
            #SeverityInfo { color: #48D7FF; font-size: 9px; font-weight: 800; }
            #IssueContract { color: #736D80; font-size: 8px; font-weight: 700; letter-spacing: 0.5px; }
            #IncidentCard { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #26112F, stop:0.65 #16111E, stop:1 #102029); border-left: 3px solid #48D7FF; border-top: 1px solid #56316B; border-radius: 7px; }
            #IncidentCard:hover { border-left: 3px solid #C8FF3D; background: #251732; }
            #IncidentCard:focus { border: 2px solid #C8FF3D; }
            #IncidentIndex { color: #48D7FF; font-size: 8px; font-weight: 900; letter-spacing: 1px; }
            #IncidentTitle { color: #F4F0FF; font-size: 11px; font-weight: 800; }
            #IncidentReason { color: #8E899C; font-size: 8px; }
            #Evidence { background: #120E19; border-left: 2px solid #9C5CFF; padding: 12px; color: #B9B2C6; }
            #PlanButton { background: #261A0D; border: 1px solid #FF6A2A; color: #FF9A6D; }
            #PlanButton:disabled { color: #4D4657; border-color: #302938; background: #0E0C12; }
            #RollbackButton { color: #C8FF3D; background: #13200C; border: 1px solid #567326; }
            #RollbackButton:hover { color: #08060D; background: #C8FF3D; }
            #ProfileButton { color: #09060F; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #C8FF3D, stop:1 #48D7FF); border: none; font-weight: 900; letter-spacing: 1px; padding: 6px 12px; }
            #ProfileButton:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #E2FF91, stop:1 #9BEAFF); }
            #ProfileButton:disabled { color: #686372; background: #201B28; }
            #CounterfactualButton { color: #C8FF3D; background: #151021; border: 1px solid #75602A; font-weight: 900; letter-spacing: 1px; padding: 6px 12px; }
            #CounterfactualButton:hover { color: #08060D; background: #C8FF3D; border-color: #C8FF3D; }
            #CounterfactualButton:disabled { color: #514A5B; background: #100D16; border-color: #292332; }
            #PulseClear { color: #FF9A6D; background: #170D0A; border: 1px solid #6E3426; padding: 6px 10px; }
            #PulseClear:hover { color: #09060F; background: #FF9A6D; border-color: #FF9A6D; }
            #StatusLine { background: #09070D; color: #766F82; font-size: 9px; letter-spacing: 1px; border-top: 1px solid #1D1825; }
            QToolTip { background: #161020; color: white; border: 1px solid #9C5CFF; padding: 7px; }
        """)

    def resizeEvent(self, event):
        """Collapse secondary controls instead of shrinking the entire instrument."""
        width = event.size().width()
        compact = width < 1220
        self.mode_label.setVisible(not compact)
        self.host_beacon.setVisible(not compact)
        self.selection_sync_button.setVisible(not compact)
        self.fit_button.setVisible(not compact)
        self.motion_button.setVisible(not compact)
        self.archive_button.setVisible(not compact)
        self.compare_button.setVisible(not compact)
        self.regression_button.setVisible(not compact)
        self.project_gate_button.setVisible(not compact)
        self.project_queue_button.setVisible(not compact)
        self.runtime_button.setVisible(not compact)
        self.lens_bar.set_compact(compact)
        self.search.setMaximumWidth(175 if compact else 310)
        self.capture_strip.set_compact(compact)
        self.clinic_view.set_compact(compact)
        super().resizeEvent(event)
        if self._lens_report:
            report = self._lens_report
            candidate = self._selected_candidate
            QtCore.QTimer.singleShot(
                0,
                lambda: self.atlas.show_lens(report, candidate)
                if self._lens_report is report
                else None,
            )

    def _install_shortcuts(self):
        shortcut_type = getattr(QtGui, "QShortcut", None) or getattr(QtWidgets, "QShortcut")
        bindings = (
            ("Escape", self._close_lens),
            ("Ctrl+0", self._fit),
            ("Alt+Up", lambda: self._set_lens_direction("upstream")),
            ("Alt+Down", lambda: self._set_lens_direction("downstream")),
        )
        self._shortcuts = []
        for sequence, callback in bindings:
            shortcut = shortcut_type(QtGui.QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)

    def _set_motion_enabled(self, enabled: bool):
        self.motion_button.setText("动效开启" if enabled else "动效关闭")
        self.atlas.set_motion_enabled(enabled)
        self.pulse.set_motion_enabled(enabled)
        self.clinic_array.set_motion_enabled(enabled)
        self.counterfactual_strip.set_motion_enabled(enabled)
        self.regression_rift.set_motion_enabled(enabled)
        self.project_gate.set_motion_enabled(enabled)
        self.runtime_constellation.set_motion_enabled(enabled)
        self.bisect_prism.set_motion_enabled(enabled)
        self.host_beacon.set_motion_enabled(enabled)
        self.capture_strip.set_motion_enabled(enabled)

    def _apply_investigation_transition(
        self, transition: InvestigationTransition
    ) -> None:
        """Render one validated application transition through the real Atlas."""
        self._presentation = transition.state
        if transition.identity_index is not None:
            self._host_identity_index = transition.identity_index
        render_atlas_transition(self.atlas, transition)

    def _hide_lens_chrome(self) -> None:
        """Hide Lens widgets without independently mutating investigation state."""
        self.lens_bar.setVisible(False)
        self.lens_ribbon.setVisible(False)
        self.clinic_view.set_lens_mode(False)
        self.pulse.counterfactual_button.setEnabled(False)

    def _set_selection_sync_enabled(self, enabled: bool):
        bridge = self._selection_bridge
        if bridge is None:
            return
        if not enabled:
            bridge.stop()
            self._selection_sync_timer.stop()
            self._pending_host_selection = ()
            self.selection_sync_button.setText("MAYA 联动关闭")
            self.selection_sync_button.setToolTip("点击恢复 Maya 与场景图谱的双向选择联动")
            if self._snapshot:
                self.status.setText("  MAYA 联动已暂停  ·  不再监听宿主选择")
            return
        try:
            selection = bridge.start()
        except Exception as exc:
            self.selection_sync_button.blockSignals(True)
            self.selection_sync_button.setChecked(False)
            self.selection_sync_button.setEnabled(False)
            self.selection_sync_button.blockSignals(False)
            self.selection_sync_button.setText("MAYA 联动不可用")
            self.selection_sync_button.setToolTip(str(exc))
            return
        self.selection_sync_button.setText("MAYA · 联动")
        self.selection_sync_button.setToolTip(
            "双向同步 Maya 与场景图谱的节点选择；45 ms 去抖并防止回调重入"
        )
        self._queue_host_selection(selection)

    def _queue_host_selection(self, names) -> None:
        if not self.selection_sync_button.isChecked():
            return
        self._pending_host_selection = tuple(str(name) for name in names if name)
        self._selection_sync_timer.start()

    @staticmethod
    def _node_ids_for_host_selection(
        snapshot: SceneSnapshot,
        names: Iterable[str],
        identity_index=None,
    ) -> Tuple[str, ...]:
        return resolve_host_selection(snapshot, tuple(names), identity_index)

    def _apply_host_selection(self) -> None:
        if not self._snapshot or not self.selection_sync_button.isChecked():
            return
        names = self._pending_host_selection
        direction = self.lens_bar.direction
        try:
            decision = self._investigation.host_selection(
                self._presentation,
                names,
                identity_index=self._host_identity_index,
                direction=direction,
                max_depth=self.lens_bar.depth,
                center=self.motion_button.isChecked(),
            )
        except Exception as exc:
            self.status.setText("  MAYA 联动已拒绝  ·  %s" % exc)
            return
        if decision.outcome == "unmapped":
            self.status.setText(
                "  MAYA 联动  ·  当前选择不在快照中  ·  捕获场景可刷新身份映射"
            )
            return
        self._apply_investigation_transition(decision.transition)
        if decision.outcome in {"empty", "multiple"}:
            self._present_closed_lens_chrome()
        if decision.outcome == "empty":
            self.status.setText("  MAYA 联动  ·  宿主选择已清空")
            self._flash_selection_sync()
            return
        if decision.outcome == "single":
            node = self._snapshot.node_map[decision.node_ids[0]]
            self.pulse.counterfactual_button.setEnabled(not node.referenced)
            self.lens_bar.set_focus(
                node.name, node.dag_paths[0] if node.dag_paths else node.id
            )
            self.lens_bar.setVisible(True)
            self._present_lens_result()
        self.status.setText(
            "  MAYA 联动  ·  Maya → 图谱  ·  %s 个节点"
            % len(decision.node_ids)
        )
        self._flash_selection_sync()

    def _flash_selection_sync(self) -> None:
        button = self.selection_sync_button
        button.setProperty("pulse", True)
        button.style().unpolish(button)
        button.style().polish(button)

        def clear_pulse():
            try:
                button.setProperty("pulse", False)
                button.style().unpolish(button)
                button.style().polish(button)
            except RuntimeError:
                pass

        QtCore.QTimer.singleShot(220, clear_pulse)

    def _sync_node_to_maya(self, node_id: str, *, require_link: bool = True) -> bool:
        if not self._snapshot or node_id not in self._snapshot.node_map:
            return False
        if require_link and not self.selection_sync_button.isChecked():
            return False
        node = self._snapshot.node_map[node_id]
        name = node.dag_paths[0] if node.dag_paths else node.name
        try:
            if self._selection_bridge is None:
                raise RuntimeError("Maya 选择桥尚未初始化")
            self._selection_bridge.select((name,))
        except Exception as exc:
            self.status.setText("  MAYA 选择失败  ·  %s" % exc)
            return False
        self.status.setText("  MAYA 联动  ·  图谱 → Maya  ·  %s" % name)
        self._flash_selection_sync()
        return True

    def _start_runtime_capture(self):
        if self._runtime_capture.active:
            event = self._runtime_capture.request_cancel()
            if event.kind == "failed":
                self._restore_runtime_controls()
                self.status.setText("  运行时取消失败  ·  %s" % event.error)
                return
            self._render_runtime_capture_event(event)
            return
        if not self._snapshot:
            self.status.setText("  运行时采集等待中  ·  请先捕获场景")
            return
        if self._scene_capture.active or (
            self._clinic_thread and self._clinic_thread.isRunning()
        ) or (self._bisect_thread and self._bisect_thread.isRunning()) or (
            self._project_queue_thread and self._project_queue_thread.isRunning()
        ):
            self.status.setText("  运行时采集等待中  ·  另一项调查正在执行")
            return
        try:
            event = self._runtime_capture.start(self._snapshot)
        except Exception as exc:
            self.status.setText("  运行时采集失败  ·  %s" % exc)
            return
        self._render_runtime_capture_event(event)
        self._runtime_timer.start()

    def _restore_runtime_controls(self):
        self._runtime_timer.stop()
        self.runtime_button.setText("运行时")
        self.runtime_button.setEnabled(self._snapshot is not None)
        self.capture_button.setEnabled(True)
        self.bisect_button.setEnabled(True)
        self.clinic_array.setEnabled(True)
        self.pulse.setEnabled(True)

    def _render_runtime_capture_event(self, event: RuntimeCaptureEvent):
        if event.kind == "started":
            self.runtime_button.setText("取消运行时采集")
            self.clinic_array.setEnabled(False)
            self.pulse.setEnabled(False)
            self.capture_button.setEnabled(False)
            self.bisect_button.setEnabled(False)
            self.runtime_button.setEnabled(True)
            self.status.setText("  运行时采集中  ·  正在映射执行表面")
            return
        if event.kind == "cancelling":
            self.runtime_button.setText("正在取消…")
            self.capture_button.setEnabled(False)
            self.bisect_button.setEnabled(False)
            self.clinic_array.setEnabled(False)
            self.pulse.setEnabled(False)
            self.runtime_button.setEnabled(False)
            self.status.setText("  正在取消运行时采集  ·  将在下一个安全分片停止")
            return
        if event.kind == "progress":
            stage = {
                "expressions": "表达式",
                "plugins": "插件",
                "callbacks": "回调",
                "verify": "验证",
                "finalize": "封存",
            }.get(event.stage, event.stage)
            self.status.setText(
                "  运行时采集中  ·  %s  %s/%s"
                % (stage, event.completed, event.total)
            )

    def _advance_runtime_capture(self):
        if not self._runtime_capture.active:
            self._runtime_timer.stop()
            return
        event = self._runtime_capture.advance(self._snapshot)
        if not event.terminal:
            self._render_runtime_capture_event(event)
            return
        if event.kind == "cancelled":
            self._restore_runtime_controls()
            self.status.setText("  运行时采集已取消  ·  已保留上次清单")
            return
        if event.kind == "stale":
            self._restore_runtime_controls()
            self.status.setText("  运行时证据已失效  ·  %s" % event.error)
            return
        if event.kind == "failed":
            self._restore_runtime_controls()
            self.status.setText("  运行时采集失败  ·  %s" % event.error)
            return
        try:
            transition = self._investigation.accept_runtime(
                self._presentation,
                event.runtime,
                event.report,
            )
        except Exception as exc:
            self._restore_runtime_controls()
            self.status.setText("  运行时证据已拒绝  ·  %s" % exc)
            return
        self._apply_investigation_transition(transition)
        self._restore_runtime_controls()
        self.runtime_constellation.set_report(event.runtime, event.report)
        self._focus_runtime()

    def _focus_runtime(self):
        if not self._runtime_snapshot or not self._runtime_report:
            return
        report = self._runtime_report
        findings = "\n".join(
            "• %s [%s]\n  %s"
            % (
                issue.title,
                {"INFO": "提示", "WARNING": "警告", "ERROR": "错误", "CRITICAL": "严重"}.get(issue.severity.name, issue.severity.name),
                " · ".join("%s: %s" % (item.label, item.value) for item in issue.evidence),
            )
            for issue in report.issues
        ) or "未触发任何运行时风险规则。"
        self.clinic_view.set_body(
            "运行时执行表面\n%s\n\n可观测性边界\n%s"
            % (findings, "\n".join("• %s" % item for item in report.limitations))
        )
        self.clinic_view.set_action("仅清点 · 不自动终止", enabled=False)
        self.status.setText(
            "  运行时星图  ·  %s 个信号  ·  %s 个回调节点"
            % (
                len(report.issues),
                len(self._runtime_snapshot.node_callbacks),
            )
        )

    def _dismiss_runtime(self):
        transition = self._investigation.dismiss_runtime(self._presentation)
        self._apply_investigation_transition(transition)
        self.runtime_constellation.setVisible(False)
        self.runtime_constellation.clear()
        self._populate_issues()
        self.status.setText("  运行时证据已关闭  ·  已恢复之前的图谱调查层")

    def _set_delta(self, delta: SceneDelta, before: SceneSnapshot):
        self._presentation = self._presentation.present_delta(delta, before)
        self.delta_strip.set_delta(delta)

    def _auto_capture(self):
        if self._snapshot is None and not self._scene_capture.active:
            self.capture()

    def capture(self, after=None):
        if self._clinic_thread and self._clinic_thread.isRunning():
            if self._clinic_job and self._clinic_job[0] == "capture" and not self._capture_required:
                self._cancel_clinic_analysis()
            return
        if self._scene_capture.active:
            if after is None:
                try:
                    event = self._scene_capture.request_cancel()
                except SceneCaptureStateError as exc:
                    self.status.setText("  场景复检不可取消  ·  %s" % exc)
                    return
                if event.kind == "failed":
                    self._capture_failed(event.error, "场景捕获取消失败")
                else:
                    self._render_scene_capture_event(event)
            return
        try:
            event = self._scene_capture.start(
                self._snapshot, required=after is not None
            )
        except Exception as exc:
            self.status.setText("  场景探针失败  ·  %s" % exc)
            QtWidgets.QMessageBox.critical(self, "MayaScope 场景捕获失败", str(exc))
            return
        self._capture_after = after
        self._capture_required = after is not None
        self._render_scene_capture_event(event)
        log_event("capture.started", context={"has_previous": self._snapshot is not None})
        self._capture_timer.start()

    def _render_scene_capture_event(self, event: SceneCaptureEvent):
        if event.kind == "started":
            self.capture_strip.start(required=event.required)
            self.bisect_button.setEnabled(False)
            self.runtime_button.setEnabled(False)
            self.clinic_array.setEnabled(False)
            self.pulse.setEnabled(False)
            self.capture_button.setEnabled(not event.required)
            self.capture_button.setText(
                "正在验证…" if event.required else "取消捕获"
            )
            self.status.setText("  场景捕获中  ·  正在获取稳定节点身份")
            return
        if event.kind == "cancelling":
            self.capture_strip.show_cancelling()
            self.capture_button.setEnabled(False)
            self.capture_button.setText("正在取消…")
            self.status.setText(
                "  正在取消场景捕获  ·  将在下一个安全分片停止"
            )
            return
        if event.kind == "progress":
            self.capture_strip.update_progress(
                event.message, event.completed, event.total
            )
            count = (
                "%s/%s" % (event.completed, event.total)
                if event.total
                else "已发现 %s 项" % event.completed
            )
            self.status.setText(
                "  场景捕获中  ·  %s  ·  %s" % (event.message, count)
            )

    def _restore_scene_capture_controls(self):
        self._capture_timer.stop()
        self.capture_strip.clear()
        self.capture_button.setEnabled(True)
        self.capture_button.setText("捕获场景")
        self.bisect_button.setEnabled(True)
        self.runtime_button.setEnabled(self._snapshot is not None)
        self.clinic_array.setEnabled(True)
        self.pulse.setEnabled(True)

    def _advance_capture(self):
        if not self._scene_capture.active:
            self._capture_timer.stop()
            return
        event = self._scene_capture.advance(self._snapshot)
        if not event.terminal:
            self._render_scene_capture_event(event)
            return
        if event.kind == "cancelled":
            self._capture_after = None
            self._capture_required = False
            self._restore_scene_capture_controls()
            self.status.setText("  场景捕获已取消  ·  已保留上次快照")
            log_event("capture.cancelled")
            return
        if event.kind == "stale":
            self._capture_failed(event.error, "捕获结果已失效")
            return
        if event.kind == "failed":
            self._capture_failed(event.error, "场景捕获失败")
            return
        self._capture_timer.stop()
        snapshot = event.snapshot
        previous_snapshot = event.previous_snapshot
        reuse = event.reuse
        aliased_indexes = (
            alias_graph_indexes(previous_snapshot, snapshot)
            if previous_snapshot is not None and reuse.topology_unchanged
            else 0
        )
        callback = self._capture_after
        required = self._capture_required
        self._capture_after = None
        self._start_clinic_analysis(
            snapshot,
            kind="capture",
            previous_snapshot=previous_snapshot,
            callback=callback,
            required=required,
        )
        if previous_snapshot is not None:
            log_event(
                "capture.reconciled",
                context={
                    "previous_snapshot_id": previous_snapshot.snapshot_id,
                    "snapshot_id": snapshot.snapshot_id,
                    "reused_nodes": reuse.reused_nodes,
                    "reused_edges": reuse.reused_edges,
                    "reused_references": reuse.reused_references,
                    "topology_unchanged": reuse.topology_unchanged,
                    "aliased_indexes": aliased_indexes,
                },
            )

    def _capture_failed(self, exc, label: str):
        self._capture_after = None
        self._capture_required = False
        self._restore_scene_capture_controls()
        self.status.setText("  %s  ·  %s" % (label, exc))
        log_event("capture.failed", str(exc), level=40, context={"label": label})
        QtWidgets.QMessageBox.critical(self, "MayaScope 场景捕获已停止", str(exc))

    def _apply_captured_snapshot(
        self, snapshot, previous_snapshot, clinic_report, incidents, host_identity_index
    ):
        transition = self._investigation.accept_scene(
            self._presentation,
            snapshot,
            clinic_report,
            incidents,
            identity_index=host_identity_index,
            previous_snapshot=previous_snapshot,
        )
        self._apply_investigation_transition(transition)
        self._hide_lens_chrome()
        issues = self._issues
        self.runtime_constellation.clear()
        self.runtime_constellation.setVisible(False)
        self._regression_payload = None
        self.regression_rift.clear()
        self.regression_rift.setVisible(False)
        self.delta_strip.setVisible(False)
        self.counterfactual_strip.clear()
        self.counterfactual_strip.setVisible(False)
        self.runtime_button.setEnabled(True)
        self.clinic_array.set_scene_settings(
            snapshot.scene_settings,
            snapshot.external_dependencies,
            snapshot.scene_lifecycle,
            snapshot.unknown_plugins,
            snapshot.references,
            snapshot.nodes,
        )
        self.clinic_array.set_report(clinic_report, len(incidents))
        self.archive_button.setEnabled(True)
        priority_ids = transition.atlas_intents[0].priority_node_ids
        self.pulse.set_summary(snapshot.summary())
        self.pulse.set_capture(None)
        self._populate_issues()
        atlas_stats = self.atlas.last_apply_stats
        rendered_nodes = atlas_stats.visible_nodes if atlas_stats is not None else MAX_RENDER_NODES
        omitted = max(0, len(snapshot.nodes) - rendered_nodes)
        suffix = " · 已折叠 %s 个低信号节点" % omitted if omitted else ""
        reuse = snapshot.metadata.get("capture_reuse", {})
        reuse_suffix = (
            " · 增量复用 %s 节点 / %s 边 · CSR 已复用"
            % (reuse.get("reused_nodes", 0), reuse.get("reused_edges", 0))
            if reuse.get("topology_unchanged")
            else ""
        )
        config_state = " · 配置已回退" if self._clinic_config_error else " · 规则集 %s" % self._clinic_environment.fingerprint[:7].upper()
        dirty_state = " · 内存有未保存修改" if snapshot.scene_lifecycle.modified is True else ""
        self.status.setText(
            "  快照 %s  ·  %s 个节点  ·  %s 条连接  ·  %s 项发现%s%s%s%s"
            % (
                snapshot.snapshot_id[:8],
                len(snapshot.nodes),
                len(snapshot.edges),
                len(issues),
                suffix,
                reuse_suffix,
                config_state,
                dirty_state,
            )
        )
        if self._delta is not None:
            self.delta_strip.set_delta(self._delta)
        if priority_ids:
            self._activate_focus(priority_ids[0])
        if self._selection_bridge and self.selection_sync_button.isChecked():
            try:
                self._queue_host_selection(self._selection_bridge.current_selection())
            except Exception as exc:
                self.status.setText("  MAYA 联动读取失败  ·  %s" % exc)
        log_event(
            "capture.finished",
            context={
                "snapshot_id": snapshot.snapshot_id,
                "nodes": len(snapshot.nodes),
                "edges": len(snapshot.edges),
                "issues": len(issues),
            },
        )

    def _populate_issues(self):
        if self._clinic_report is None:
            return
        specs = {spec.id: spec for spec in self._clinic_registry.specs}
        self.clinic_view.render_report(
            self._clinic_report,
            self._incidents,
            specs,
        )

    def _start_clinic_analysis(
        self,
        snapshot,
        *,
        kind,
        previous_snapshot=None,
        callback=None,
        required=False,
    ):
        if self._clinic_thread and self._clinic_thread.isRunning():
            raise RuntimeError("已有一项场景诊所分析正在执行")
        self._clinic_cancel_event = threading.Event()
        self._clinic_job = (kind, snapshot, previous_snapshot, callback, bool(required))
        thread = QtCore.QThread(self)
        worker = ClinicWorker(
            self._clinic_registry,
            snapshot,
            self.clinic_array.enabled_rule_ids(),
            self.clinic_array.current_profile().include_expensive,
            self._clinic_cancel_event,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_clinic_progress)
        worker.finished.connect(self._on_clinic_finished)
        worker.cancelled.connect(self._on_clinic_cancelled)
        worker.failed.connect(self._on_clinic_failed)
        worker.finished.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_clinic_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._clinic_thread = thread
        self._clinic_worker = worker
        self.bisect_button.setEnabled(False)
        self.runtime_button.setEnabled(False)
        self.clinic_array.setEnabled(True)
        self.clinic_array.profile_combo.setEnabled(False)
        for button in self.clinic_array.rule_buttons.values():
            button.setEnabled(False)
        if kind == "capture":
            self.capture_button.setEnabled(not required)
            self.capture_button.setText("正在验证…" if required else "取消分析")
        else:
            self.clinic_array.run_button.setEnabled(True)
            self.clinic_array.run_button.setText("取消诊所分析")
        self.status.setText("  场景诊所  ·  后台分析已启动")
        thread.start()

    def _on_clinic_progress(self, completed, total, rule_id):
        self.status.setText(
            "  场景诊所  ·  %s  ·  规则 %s/%s"
            % (rule_id.upper(), completed, total)
        )

    def _on_clinic_finished(self, report, incidents, host_identity_index):
        if not self._clinic_job:
            return
        kind, snapshot, previous_snapshot, callback, _required = self._clinic_job
        try:
            if kind == "capture":
                self._apply_captured_snapshot(
                    snapshot, previous_snapshot, report, incidents, host_identity_index
                )
                if callback is not None:
                    callback()
            else:
                transition = self._investigation.accept_clinic(
                    self._presentation,
                    report,
                    incidents,
                    identity_index=host_identity_index,
                )
                self._apply_investigation_transition(transition)
                self._hide_lens_chrome()
                self.clinic_array.set_report(report, len(incidents))
                self._populate_issues()
                self.status.setText(
                    "  场景诊所  ·  %s  ·  %s 条规则  ·  %s 个事件簇  ·  %s 条异常  ·  %.2f ms"
                    % (
                        self.clinic_array.current_profile().title.upper(),
                        len(report.runs),
                        len(incidents),
                        len(report.failures),
                        report.duration_ms,
                    )
                )
        except Exception as exc:
            self._on_clinic_failed(str(exc))

    def _on_clinic_cancelled(self):
        kind = self._clinic_job[0] if self._clinic_job else "scan"
        self.status.setText(
            "  场景诊所已取消  ·  已保留%s"
            % ("上次快照" if kind == "capture" else "上次分析结果")
        )
        log_event("clinic.cancelled", context={"kind": kind})

    def _on_clinic_failed(self, message):
        self.status.setText("  场景诊所失败  ·  %s" % message)
        log_event("clinic.failed", str(message), level=40)
        QtWidgets.QMessageBox.critical(self, "场景诊所已停止", str(message))

    def _on_clinic_thread_finished(self):
        clinic_kind = self._clinic_job[0] if self._clinic_job else ""
        self.clinic_array.profile_combo.setEnabled(True)
        for button in self.clinic_array.rule_buttons.values():
            button.setEnabled(True)
        self.clinic_array._sync_run_state()
        self.clinic_array.run_button.setText("扫描快照")
        self.capture_button.setText("捕获场景")
        if clinic_kind == "capture":
            self.capture_strip.clear()
        if not self._runtime_capture.active:
            self.capture_button.setEnabled(True)
            self.bisect_button.setEnabled(True)
            self.runtime_button.setEnabled(self._snapshot is not None)
            self.pulse.setEnabled(True)
        self._capture_required = False
        self._clinic_worker = None
        self._clinic_thread = None
        self._clinic_cancel_event = None
        self._clinic_job = None
        if self._close_after_clinic:
            self._close_after_clinic = False
            QtCore.QTimer.singleShot(0, self.close)

    def _cancel_clinic_analysis(self):
        if self._clinic_cancel_event is None or not self._clinic_job:
            return
        if self._clinic_job[4]:
            return
        self._clinic_cancel_event.set()
        if self._clinic_job[0] == "capture":
            self.capture_button.setEnabled(False)
            self.capture_button.setText("正在取消…")
        else:
            self.clinic_array.run_button.setEnabled(False)
            self.clinic_array.run_button.setText("正在取消…")
        self.status.setText("  正在取消场景诊所分析  ·  当前规则结束后停止")

    def _run_clinic(self):
        if self._clinic_thread and self._clinic_thread.isRunning():
            if self._clinic_job and self._clinic_job[0] == "scan":
                self._cancel_clinic_analysis()
            return
        if not self._snapshot:
            self.status.setText("  场景诊所等待中  ·  请先捕获场景")
            return
        self._start_clinic_analysis(self._snapshot, kind="scan")

    def _select_issue(self, issue: Issue):
        try:
            transition = self._investigation.select_issue(
                self._presentation, issue
            )
        except Exception as exc:
            self.status.setText("  诊断选择已失效  ·  %s" % exc)
            return
        self._apply_investigation_transition(transition)
        self._hide_lens_chrome()
        issue = self._selected_issue
        plan = plan_for_issue(issue, self._snapshot) if self._snapshot else None
        self.clinic_view.present_issue(issue, has_plan=plan is not None)

    def _focus_rule_signal(self, rule_id: str):
        issue = next((item for item in self._issues if item.rule_id == rule_id), None)
        if issue is None:
            self.status.setText("  当前快照没有命中该诊断规则")
            return
        self._select_issue(issue)
        related = {rule_id}
        if rule_id == "missing-reference-files":
            related.update(
                {
                    "reference-namespace-intrusion", "unloaded-references",
                    "failed-reference-edits", "nested-reference-depth",
                }
            )
        elif rule_id == "missing-plugin-requirements":
            related.add("unknown-nodes")
        node_ids = tuple(
            sorted(
                {
                    node_id
                    for item in self._issues
                    if item.rule_id in related
                    for node_id in item.affected_node_ids
                }
            )
        )
        if node_ids:
            self.atlas.highlight(node_ids)
        self.clinic_view.set_heading(issue.title)
        self.status.setText(
            "  已聚焦%s  ·  %s 项关联发现  ·  %s 个受影响身份"
            % (
                "引用因果域" if rule_id == "missing-reference-files" else "规则证据",
                sum(item.rule_id in related for item in self._issues),
                len(node_ids),
            )
        )

    def _select_incident(self, incident: Incident):
        if not self._snapshot:
            return
        try:
            transition = self._investigation.select_incident(
                self._presentation, incident
            )
        except Exception as exc:
            self.status.setText("  事件簇选择已失效  ·  %s" % exc)
            return
        self._apply_investigation_transition(transition)
        self._hide_lens_chrome()
        incident = self._selected_incident
        issue_map = {issue.id: issue for issue in self._issues}
        incident_issues = tuple(issue_map[issue_id] for issue_id in incident.issue_ids)
        plan = plan_for_issues(incident_issues, self._snapshot)
        self.clinic_view.present_incident(
            incident,
            issue_map,
            repairable_issue_count=len(plan.issue_ids) if plan else 0,
        )
        self.status.setText(
            "  已聚焦事件簇  ·  %s 项发现  ·  %s 个受影响身份"
            % (len(incident.issue_ids), len(incident.affected_node_ids))
        )

    def _preview_plan(self):
        if not self._snapshot:
            return
        if self._selected_issue:
            plan = plan_for_issue(self._selected_issue, self._snapshot)
        elif self._selected_incident:
            issue_map = {issue.id: issue for issue in self._issues}
            plan = plan_for_issues(
                tuple(
                    issue_map[issue_id]
                    for issue_id in self._selected_incident.issue_ids
                    if issue_id in issue_map
                ),
                self._snapshot,
            )
        else:
            return
        if not plan:
            return
        preview = "\n".join(plan.preview_lines())
        confirmed = _confirm_action(
            self,
            "预览变更计划",
            "%s\n\nMayaScope 将开启一个 Undo 块、保护引用节点，并在执行后重新捕获场景。"
            % preview,
        )
        if not confirmed:
            return
        receipt = MayaChangeExecutor().execute(plan)
        if not receipt.success:
            QtWidgets.QMessageBox.critical(self, "变更计划已回滚", receipt.message)
            return
        self._last_change_plan = plan
        self._last_execution_receipt = receipt
        self.status.setText("  变更计划已在宿主中验证  ·  正在重新捕获场景证据")
        self.capture(after=lambda: self._finish_changeplan_verification(plan, receipt))

    def _finish_changeplan_verification(self, plan, receipt):
        remaining = set(plan.issue_ids).intersection(issue.id for issue in self._issues)
        verified = not remaining
        self.clinic_view.set_heading("变更计划验证通过" if verified else "变更计划需要复核")
        self.clinic_view.set_body(
            "执行回执\n%s\n\n%s\n\n重新捕获结果\n%s"
            % (
                receipt.plan_id,
                receipt.message,
                "%s 项源问题已清除。" % len(plan.issue_ids)
                if verified else
                "%s / %s 项源问题仍可检测到。"
                % (len(remaining), len(plan.issue_ids)),
            )
        )
        self.rollback_button.setVisible(receipt.verified)
        self.status.setText(
            "  变更计划%s  ·  %s  ·  %s 个节点"
            % ("已验证" if verified else "待复核", receipt.plan_id, len(receipt.affected_nodes))
        )

    def _rollback_last_plan(self):
        if not self._last_change_plan or not self._last_execution_receipt:
            return
        try:
            import maya.cmds as cmds  # type: ignore

            expected = "MayaScope: %s" % self._last_change_plan.title
            current = str(cmds.undoInfo(query=True, undoName=True) or "")
            if current != expected:
                self.rollback_button.setVisible(False)
                self.status.setText("  拒绝回滚  ·  Maya Undo 顶部自该变更计划后已发生变化")
                return
            cmds.undo()
        except Exception as exc:
            self.status.setText("  回滚失败  ·  %s" % exc)
            return
        plan_id = self._last_execution_receipt.plan_id
        self._last_change_plan = None
        self._last_execution_receipt = None
        self.rollback_button.setVisible(False)
        self.capture(after=lambda: self._finish_rollback_verification(plan_id))

    def _finish_rollback_verification(self, plan_id):
        self.clinic_view.set_heading("变更计划已回滚")
        self.clinic_view.set_body(
            "回滚回执\n%s\n\nMaya 恢复已验证的 Undo 块后，场景已重新捕获。"
            % plan_id
        )
        self.status.setText("  变更计划已回滚  ·  %s" % plan_id)

    def _fit(self):
        bounds = self.atlas.scene().itemsBoundingRect().adjusted(-100, -100, 100, 100)
        self.atlas.fitInView(bounds, _qt_enum(QtCore.Qt, "KeepAspectRatio"))

    def _on_search(self, value: str):
        self.atlas.filter_nodes(value)

    def _node_selected(self, node_id: str):
        if not self._snapshot:
            return
        self._activate_focus(node_id)
        self._sync_node_to_maya(node_id)

    @staticmethod
    def _selected_scene_node_ids(snapshot: SceneSnapshot) -> Tuple[str, ...]:
        return MayaScopeWorkspace._node_ids_for_host_selection(
            snapshot,
            snapshot.metadata.get("selection", ()),
        )

    def _activate_focus(self, node_id: str):
        if not self._snapshot or node_id not in self._snapshot.node_map:
            return
        node = self._snapshot.node_map[node_id]
        self.pulse.counterfactual_button.setEnabled(not node.referenced)
        self.lens_bar.set_focus(
            node.name, node.dag_paths[0] if node.dag_paths else node.id
        )
        self.lens_bar.setVisible(True)
        self._run_lens(node_id=node_id)

    def _set_lens_direction(self, direction: str):
        self.lens_bar.set_direction(direction)
        self._run_lens()

    def _run_lens(self, *_args, node_id=None):
        focus_node_id = node_id or self._focus_node_id
        if not self._snapshot or not focus_node_id:
            return
        direction = self.lens_bar.direction
        try:
            transition = self._investigation.focus(
                self._presentation,
                focus_node_id,
                direction=direction,
                max_depth=self.lens_bar.depth,
            )
        except Exception as exc:
            self.status.setText("  根因透镜失败  ·  %s" % exc)
            return
        self._apply_investigation_transition(transition)
        self._present_lens_result()

    def _present_lens_result(self):
        """Render the already validated Lens generation without recomputing it."""
        report = self._lens_report
        measured = self._measured_report
        if not self._snapshot or report is None:
            return
        state = present_lens_result(report, self._snapshot, measured)
        self.lens_ribbon.set_state(state)
        self.clinic_view.set_lens_mode(True)
        self.clinic_view.set_heading("根因透镜")
        self.clinic_view.set_action("结构证据", enabled=False)
        if report.candidates:
            self._candidate_selected(report.candidates[0])
        else:
            self.clinic_view.set_body(state.empty_body)
        self.status.setText(state.status)

    def _candidate_selected(self, candidate: RootCauseCandidate):
        if not self._snapshot or not self._lens_report:
            return
        try:
            transition = self._investigation.select_candidate(
                self._presentation, candidate
            )
        except Exception as exc:
            self.status.setText("  根因候选已失效  ·  %s" % exc)
            return
        self._apply_investigation_transition(transition)
        candidate = self._selected_candidate
        evidence = present_lens_candidate(
            candidate,
            self._lens_report,
            self._snapshot,
            self._measured_report,
        )
        self.clinic_view.set_heading(evidence.heading)
        self.clinic_view.set_body(evidence.body)

    def _show_host_health(self):
        health = self._host_health
        issues = "\n".join("· %s" % item for item in health.issues) or "未检测到宿主边界问题。"
        self.clinic_view.set_heading("宿主信标")
        self.clinic_view.set_body(
            "MAYA 宿主\n"
            "Maya %s · API %s\n"
            "PySide %s · MayaScope %s\n"
            "求值模式 %s\n\n"
            "RUNNER\n%s\n\n"
            "模块\n%s\n\n"
            "边界检查\n%s\n\n"
            "这是只读即时检查；仍可通过以下命令执行完整的后台宿主验证："
            "python -m MayaScope.doctor."
            % (
                health.maya_version,
                health.maya_api,
                health.pyside_version,
                health.mayascope_version,
                " / ".join(health.evaluation_mode) or "未知",
                health.mayapy_path,
                health.module_state.upper(),
                issues,
            )
        )
        self.clinic_view.set_action("只读宿主检查", enabled=False)
        self.status.setText(
            "  宿主%s  ·  MAYA %s  ·  API %s  ·  PYSIDE %s  ·  模块 %s"
            % (
                {"ready": "就绪", "attention": "需检查"}.get(health.state, health.state),
                health.maya_version,
                health.maya_api,
                health.pyside_version,
                health.module_state.upper(),
            )
        )
        log_event(
            "host.beacon",
            context={
                "state": health.state,
                "maya": health.maya_version,
                "api": health.maya_api,
                "pyside": health.pyside_version,
                "module": health.module_state,
            },
        )

    @staticmethod
    def _maya_python_executable() -> Path:
        adjacent = Path(sys.executable).resolve().parent / "mayapy.exe"
        if adjacent.is_file():
            return adjacent
        showcase = Path(r"C:\Program Files\Autodesk\Maya2025\bin\mayapy.exe")
        if showcase.is_file():
            return showcase
        raise RuntimeError("未找到 Maya 2025 mayapy.exe")

    def _start_bisect(self):
        if self._scene_capture.active or (
            self._clinic_thread and self._clinic_thread.isRunning()
        ):
            self.status.setText("  故障二分等待中  ·  场景捕获或诊所分析仍在执行")
            return
        if self._bisect_thread and self._bisect_thread.isRunning():
            self.status.setText("  故障二分执行中  ·  后台串行探针已在运行")
            return
        if not self._snapshot or not self._snapshot.source_scene:
            self.status.setText("  故障二分等待中  ·  请先保存并捕获场景")
            return
        source = Path(self._snapshot.source_scene).expanduser().resolve()
        if not source.is_file():
            self.status.setText("  拒绝故障二分  ·  捕获时的源场景已不存在")
            return
        try:
            mayapy = self._maya_python_executable()
            if source.suffix.lower() == ".ma":
                plan = build_pre_open_ascii_bisect_plan(
                    str(source), str(mayapy), timeout_seconds=120.0
                )
            elif source.suffix.lower() == ".mb":
                plan = build_post_open_bisect_plan(
                    self._snapshot, str(mayapy), timeout_seconds=120.0
                )
            else:
                raise RuntimeError("故障二分仅支持已保存的 .ma 与 .mb 场景")
        except Exception as exc:
            self.status.setText("  拒绝故障二分  ·  %s" % exc)
            return

        mode = plan.metadata.get("isolation_mode", "post-open-copy")
        display_mode = {"pre-open-ascii": "打开前 ASCII 切片", "post-open-copy": "打开后副本隔离"}.get(mode, mode)
        boundary = (
            "Maya ASCII 将在打开前进行切片。"
            if mode == "pre-open-ascii"
            else "Maya Binary 可隔离求值、保存与重开失败，但无法隔离首次打开时的崩溃。"
        )
        confirmed = _confirm_action(
            self,
            "预览故障棱镜",
            "%s\n\n%s 个候选 · %s\nSHA-256 %s\n%s\n\n"
            "每个探针均在后台 Maya 2025 进程中串行运行，源文件绝不会以写入方式打开。"
            % (source.name, len(plan.candidates), display_mode, plan.source_sha256[:16], boundary),
        )
        if not confirmed:
            return
        self._launch_bisect_plan(plan)

    def _launch_bisect_plan(
        self, plan, root=None, journal_path=None, prior_attempts=()
    ):
        """Launch a prepared plan; split out so visual and lifecycle tests stay Maya-free."""
        self._bisect_plan = plan
        log_event(
            "bisect.started",
            context={
                "plan_id": plan.plan_id,
                "candidate_count": len(plan.candidates),
                "mode": plan.metadata.get("isolation_mode", "post-open-copy"),
                "resumed": bool(journal_path),
            },
        )
        self._bisect_result = None
        self._bisect_cancel_event = threading.Event()
        self.bisect_prism.begin(plan)
        for attempt in prior_attempts:
            self.bisect_prism.add_attempt(
                DeltaDebugStep(
                    attempt.attempt_index + 1,
                    attempt.candidate_ids,
                    attempt.outcome,
                    "journal-replay",
                    1,
                    True,
                ),
                attempt,
            )
        self.bisect_button.setEnabled(False)
        if journal_path:
            self._bisect_journal_path = Path(journal_path).expanduser().resolve()
        else:
            probe_root = (
                Path(root).expanduser().resolve()
                if root is not None
                else Path(os.environ.get("LOCALAPPDATA") or Path.home())
                / "MayaScope"
                / "runner"
                / plan.plan_id
            )
            self._bisect_journal_path = probe_root / "bisect-journal.json"
        self.status.setText(
            "  故障二分执行中  ·  后台 Maya 2025 探针 01  ·  源校验和已锁定"
        )
        thread = QtCore.QThread(self)
        worker = BisectWorker(
            plan,
            self._bisect_cancel_event,
            root=root,
            journal_path=journal_path,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.probeCompleted.connect(self._on_bisect_probe)
        worker.finished.connect(self._on_bisect_finished)
        worker.failed.connect(self._on_bisect_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_bisect_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._bisect_thread = thread
        self._bisect_worker = worker
        thread.start()

    def _on_bisect_probe(self, step, attempt):
        log_event(
            "bisect.probe",
            context={
                "plan_id": self._bisect_plan.plan_id,
                "attempt": attempt.attempt_index,
                "outcome": attempt.outcome,
                "stage": attempt.stage,
                "candidate_count": len(step.candidate_ids),
                "duration_seconds": round(attempt.duration_seconds, 6),
            },
        )
        self.bisect_prism.add_attempt(step, attempt)
        self.status.setText(
            "  故障二分探针 %02d  ·  %s  ·  %s 个候选  ·  %.1f 秒"
            % (
                attempt.attempt_index + 1,
                {"pass": "通过", "fail": "复现", "unresolved": "未决"}.get(attempt.outcome, attempt.outcome),
                len(step.candidate_ids),
                attempt.duration_seconds,
            )
        )

    def _on_bisect_finished(self, result):
        log_event(
            "bisect.finished",
            context={
                "plan_id": result.manifest.plan.plan_id,
                "complete": result.delta_debug.complete,
                "attempt_count": len(result.manifest.attempts),
                "minimal_count": len(result.delta_debug.minimal_candidate_ids),
                "capsule_sha256": result.manifest_sha256,
            },
        )
        self._bisect_result = result
        candidate_map = {candidate.id: candidate for candidate in self._bisect_plan.candidates}
        minimal = result.delta_debug.minimal_candidate_ids
        labels = [candidate_map[item].label for item in minimal if item in candidate_map]
        self.bisect_prism.finish(result, labels)
        stable_ids = tuple(
            stable_id
            for candidate_id in minimal
            for stable_id in candidate_map[candidate_id].stable_node_ids
            if candidate_id in candidate_map
        )
        if self._snapshot:
            visible_ids = set(self._snapshot.node_map).intersection(stable_ids)
            if visible_ids:
                self.atlas.highlight(visible_ids)
        attempts = result.manifest.attempts
        trace = "\n".join(
            "%02d  %-10s %-8s %3s 个候选  %5.1f 秒%s"
            % (
                item.attempt_index + 1,
                {"pass": "通过", "fail": "复现", "unresolved": "未决"}.get(item.outcome, item.outcome),
                {"confirm-source-failure": "确认源故障", "subset": "子集", "complement": "补集", "journal-replay": "日志重放"}.get(item.stage, item.stage),
                len(item.candidate_ids),
                item.duration_seconds,
                "  超时" if item.timed_out else "",
            )
            for item in attempts[-10:]
        )
        self.clinic_view.set_heading("故障棱镜")
        self.clinic_view.set_body(
            "已隔离原因\n%s\n\n"
            "结果\n%s · %s\n%s 次探针 · %s 次缓存命中\n\n"
            "串行探针轨迹\n%s\n\n"
            "复现胶囊\n%s\nSHA-256 %s\n\n"
            "安全回执\n源校验和保持不变 · 仅操作工作副本 · 后台 Maya 2025 进程"
            % (
                " + ".join(labels) if labels else "未得到最小失败候选集",
                "已完成" if result.delta_debug.complete else "部分收敛",
                {"1-minimal failing set": "已得到 1-最小失败集", "cancelled": "已取消", "probe budget exhausted": "探针预算已耗尽"}.get(result.delta_debug.reason, result.delta_debug.reason),
                len(attempts),
                result.delta_debug.cache_hits,
                trace or "尚无已完成探针",
                result.manifest_path,
                result.manifest_sha256,
            )
        )
        self.clinic_view.set_action("复现胶囊已封存", enabled=False)
        self.status.setText(
            "  故障二分%s  ·  %s  ·  胶囊 SHA %s"
            % (
                "完成" if result.delta_debug.complete else "部分收敛",
                " + ".join(labels) or {"1-minimal failing set": "已得到 1-最小失败集", "cancelled": "已取消", "probe budget exhausted": "探针预算已耗尽"}.get(result.delta_debug.reason, result.delta_debug.reason),
                result.manifest_sha256[:10],
            )
        )

    def _on_bisect_failed(self, message: str):
        log_event(
            "bisect.failed",
            message,
            level=40,
            context={"plan_id": self._bisect_plan.plan_id if self._bisect_plan else ""},
        )
        self.bisect_prism.fail(message)
        self.clinic_view.set_heading("故障棱镜已停止")
        self.clinic_view.set_body(
            "故障二分已停止\n%s\n\n源场景未被修改；已完成的探针目录仍可供检查。"
            % message
        )
        self.status.setText("  故障二分已停止  ·  %s" % message)

    def _on_bisect_thread_finished(self):
        if not self._runtime_capture.active:
            self.bisect_button.setEnabled(True)
        self._bisect_worker = None
        self._bisect_thread = None
        if self._close_after_bisect:
            self._close_after_bisect = False
            QtCore.QTimer.singleShot(0, self.close)

    def _cancel_bisect(self):
        if self._bisect_cancel_event is not None:
            self._bisect_cancel_event.set()
            self.bisect_prism.request_cancel()
            self.status.setText(
                "  故障二分已排队停止  ·  等待当前后台探针退出"
            )

    def _resume_bisect(self):
        if self._bisect_thread and self._bisect_thread.isRunning():
            return
        if not self._bisect_journal_path or not self._bisect_journal_path.is_file():
            self.status.setText("  故障二分继续失败  ·  日志不可用")
            return
        try:
            journal = load_bisect_journal(self._bisect_journal_path)
        except Exception as exc:
            self.status.setText("  拒绝继续故障二分  ·  %s" % exc)
            return
        self._launch_bisect_plan(
            journal.plan,
            journal_path=self._bisect_journal_path,
            prior_attempts=journal.attempts,
        )
        self.status.setText(
            "  故障二分已继续  ·  已重放 %s 次验证探针  ·  后台串行续跑"
            % len(journal.attempts)
        )

    def _dismiss_bisect(self):
        if self._bisect_thread and self._bisect_thread.isRunning():
            return
        self.bisect_prism.setVisible(False)

    def closeEvent(self, event):
        self._selection_sync_timer.stop()
        if self._selection_bridge is not None:
            self._selection_bridge.stop()
        if self._runtime_capture.active:
            self._runtime_timer.stop()
            self._runtime_capture.abort()
        if self._scene_capture.active:
            self._capture_timer.stop()
            self._scene_capture.abort()
            self._capture_after = None
            self._capture_required = False
        if self._clinic_thread and self._clinic_thread.isRunning():
            if self._clinic_job and not self._clinic_job[4]:
                self._clinic_cancel_event.set()
            self._close_after_clinic = True
            self.hide()
            event.ignore()
            return
        if self._bisect_thread and self._bisect_thread.isRunning():
            self._close_after_bisect = True
            self._cancel_bisect()
            self.hide()
            event.ignore()
            return
        if self._project_queue_thread and self._project_queue_thread.isRunning():
            self._close_after_project_queue = True
            self._cancel_project_queue()
            self.hide()
            event.ignore()
            return
        self._capture_timer.stop()
        self._runtime_timer.stop()
        self._set_motion_enabled(False)
        invalidate_graph_indexes()
        self.atlas.clear_snapshot()
        self._presentation = WorkspacePresentationState()
        self._host_identity_index = {}
        self._regression_payload = None
        self._project_audit_payload = None
        self._project_queue_payload = None
        super().closeEvent(event)

    def _profile_frame(self):
        if not self._snapshot:
            self.status.setText("  性能采样等待中  ·  请先捕获场景")
            return
        self.pulse.profile_button.setEnabled(False)
        self.pulse.profile_button.setText("●  正在采样…")
        self.status.setText("  性能采样中  ·  一次显式 DG 求值与视口刷新")
        QtWidgets.QApplication.processEvents()
        try:
            import maya.cmds as cmds  # type: ignore

            def operation():
                cmds.dgdirty(allPlugs=True)
                cmds.refresh(force=True)

            result = profile_callable(operation, snapshot=self._snapshot)
            transition = self._investigation.accept_profiler(
                self._presentation,
                result.capture,
            )
            self._apply_investigation_transition(transition)
            self.pulse.set_capture(result.capture)
            self._pulse_range_selected(self._pulse_range)
        except Exception as exc:
            self.status.setText("  性能采样失败  ·  %s" % exc)
        finally:
            self.pulse.profile_button.setEnabled(True)
            self.pulse.profile_button.setText("●  采样当前帧")

    def _dismiss_profiler(self):
        transition = self._investigation.dismiss_profiler(self._presentation)
        self._apply_investigation_transition(transition)
        self.pulse.set_capture(None)
        self.counterfactual_strip.clear()
        self.counterfactual_strip.setVisible(False)
        self._hide_lens_chrome()
        self._populate_issues()
        self.status.setText(
            "  性能采样已清除  ·  实测根因与反事实结果同步失效  ·  Maya 场景未修改"
        )

    def _run_counterfactual(self):
        if not self._snapshot or not self._focus_node_id:
            self.status.setText("  反事实实验等待中  ·  请先聚焦一个本地节点")
            return
        try:
            plan = plan_node_state_experiment(
                self._snapshot,
                self._focus_node_id,
                pair_count=4,
                warmup_count=1,
            )
        except Exception as exc:
            self.status.setText("  拒绝反事实实验  ·  %s" % exc)
            return
        preview = "\n".join(plan.preview_lines())
        confirmed = _confirm_action(
            self,
            "预览反事实实验",
            "%s\n\n不会保留任何实验状态；可在两次试验之间取消采样。"
            % preview,
        )
        if not confirmed:
            return

        progress = QtWidgets.QProgressDialog(
            "正在准备成对的基线 / 变体实验…",
            "本次采样后取消",
            0,
            plan.pair_count * 2,
            self,
        )
        progress.setWindowTitle("反事实性能采样")
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setValue(0)
        motion_was_enabled = self.motion_button.isChecked()
        self._set_motion_enabled(False)
        self.pulse.profile_button.setEnabled(False)
        self.pulse.counterfactual_button.setEnabled(False)
        self.pulse.counterfactual_button.setText("◇  实验进行中…")

        def on_progress(completed, total, condition):
            progress.setLabelText(
                "%s  ·  成对采样 %s / %s\n原始 nodeState 与 Undo 顶部始终受保护。"
                % ({"baseline": "基线", "variant": "变体"}.get(condition, condition), completed, total)
            )
            progress.setValue(completed)
            self.status.setText(
                "  反事实实验进行中  ·  %s  ·  采样 %s/%s"
                % ({"baseline": "基线", "variant": "变体"}.get(condition, condition), completed, total)
            )
            QtWidgets.QApplication.processEvents()
            if progress.wasCanceled():
                raise RuntimeError("实验已在当前采样完成后取消")

        try:
            run = MayaNodeStateExperiment(
                self._snapshot,
                plan,
                progress=on_progress,
            ).run()
        except Exception as exc:
            self.status.setText("  反事实实验已停止  ·  %s" % exc)
            QtWidgets.QMessageBox.critical(
                self,
                "反事实实验已停止",
                "%s\n\nMayaScope 在报告错误前已强制尝试恢复原始状态。"
                % exc,
            )
            return
        finally:
            progress.close()
            self.pulse.profile_button.setEnabled(True)
            self.pulse.counterfactual_button.setEnabled(True)
            self.pulse.counterfactual_button.setText("◇  测试焦点节点")
            self._set_motion_enabled(motion_was_enabled)

        try:
            record = self._experiment_store.save(run.report)
        except Exception as exc:
            record = None
            self.status.setText(
                "  反事实实验已完成测量  ·  证据归档失败：%s" % exc
            )
        self._present_counterfactual_run(run, record)

    def _present_counterfactual_run(self, run: CounterfactualRun, record=None):
        if not self._snapshot:
            return
        try:
            transition = self._investigation.accept_counterfactual(
                self._presentation,
                run,
                record,
            )
        except Exception as exc:
            self.status.setText("  反事实证据已拒绝  ·  %s" % exc)
            return
        self._apply_investigation_transition(transition)
        report = run.report
        self.counterfactual_strip.set_report(report)
        self.clinic_view.set_heading("反事实性能采样")
        node_map = self._snapshot.node_map
        effects = []
        for rank, effect in enumerate(report.node_effects[:8], 1):
            node = node_map.get(effect.node_id)
            effects.append(
                "%02d  %s  ·  实测包含耗时 Δ %+.3f ms"
                % (
                    rank,
                    node.name if node else effect.node_id,
                    effect.observed_delta_us / 1000.0,
                )
            )
        archive_receipt = (
            "%s\nSHA-256 %s"
            % (
                self._counterfactual_record.path.name,
                self._counterfactual_record.checksum,
            )
            if self._counterfactual_record else
            "归档不可用；结果仍保留在当前调查会话中。"
        )
        self.clinic_view.set_body(
            "反事实实验 / NODESTATE\n"
            "%s  ·  %s %s → %s\n\n"
            "墙钟时间结果\n"
            "基线均值 %.3f ms · p95 %.3f ms\n"
            "变体均值 %.3f ms · p95 %.3f ms\n"
            "平均收益 %+.3f ms (%+.1f%%)\n"
            "成对 bootstrap 95%% 区间 %+.3f … %+.3f ms\n"
            "结论 %s · 实测噪声 %.1f%%\n\n"
            "试验设计\n"
            "%s 组成对试验 · AB / BA 交替 · 每种状态预热 %s 次\n"
            "结果为完整操作的墙钟时间；区间跨越零时视为证据不足。\n\n"
            "性能采样解释\n%s\n\n"
            "节点包含耗时可能重叠，不能直接相加为优化收益。\n\n"
            "恢复回执\n原始 nodeState 已恢复 · Maya Undo 顶部已保留\n\n"
            "证据归档\n%s"
            % (
                report.target_name,
                report.attribute,
                report.baseline_value,
                report.variant_value,
                report.baseline_mean_us / 1000.0,
                report.baseline_p95_us / 1000.0,
                report.variant_mean_us / 1000.0,
                report.variant_p95_us / 1000.0,
                report.benefit_mean_us / 1000.0,
                report.benefit_percent,
                report.benefit_ci_low_us / 1000.0,
                report.benefit_ci_high_us / 1000.0,
                {"improved": "改善", "regressed": "变慢", "neutral": "无显著变化", "inconclusive": "证据不足"}.get(report.verdict, report.verdict),
                report.noise_ratio * 100.0,
                report.pair_count,
                report.warmup_count,
                "\n".join(effects) if effects else "没有可唯一映射的节点事件。",
                archive_receipt,
            )
        )
        self.clinic_view.set_action("实验状态已恢复", enabled=False)
        self.status.setText(
            "  反事实实验：%s  ·  %+.1f%%  ·  状态与 Undo 已恢复"
            % ({"improved": "改善", "regressed": "变慢", "neutral": "无显著变化", "inconclusive": "证据不足"}.get(report.verdict, report.verdict), report.benefit_percent)
        )

    def _dismiss_counterfactual(self):
        self.counterfactual_strip.setVisible(False)
        self.counterfactual_strip.clear()
        transition = self._investigation.dismiss_counterfactual(self._presentation)
        self._apply_investigation_transition(transition)

    def _pulse_range_selected(self, selected_range):
        if not self._profiler_capture:
            return
        start_us, end_us = selected_range
        try:
            transition = self._investigation.set_pulse_range(
                self._presentation,
                int(start_us),
                int(end_us),
            )
        except Exception as exc:
            self.status.setText("  性能时间范围已拒绝  ·  %s" % exc)
            return
        self._apply_investigation_transition(transition)
        stats = node_stats(self._profiler_capture, *self._pulse_range)
        if self._focus_node_id:
            self._run_lens()
        else:
            self.clinic_view.set_heading("性能采样脉冲")
            top = []
            node_map = self._snapshot.node_map if self._snapshot else {}
            for rank, stat in enumerate(stats[:8], 1):
                node = node_map.get(stat.node_id)
                top.append(
                    "%02d  %s  ·  %.3f ms  ·  %s 个事件"
                    % (rank, node.name if node else stat.node_id, stat.inclusive_duration_us / 1000.0, stat.event_count)
                )
            self.clinic_view.set_body(
                "实测节点活动\n范围 %.3f–%.3f ms\n\n%s\n\n嵌套事件之间的包含耗时可能重叠。"
                % (self._pulse_range[0] / 1000.0, self._pulse_range[1] / 1000.0, "\n".join(top) if top else "该范围内没有可唯一映射的节点事件。")
            )
        selected_events = self._profiler_capture.events_in_range(*self._pulse_range)
        self.status.setText(
            "  追踪范围  ·  %.3f–%.3f ms  ·  %s 个事件  ·  %s 个已映射节点"
            % (
                self._pulse_range[0] / 1000.0,
                self._pulse_range[1] / 1000.0,
                len(selected_events),
                len(stats),
            )
        )

    def _focus_delta(self):
        if not self._delta or not self._snapshot:
            return
        self._close_lens()
        self.atlas.show_delta(self._delta)
        summary = self._delta.summary()
        self.clinic_view.set_heading("场景差异")
        examples = []
        before_nodes = self._delta_before.node_map if self._delta_before else {}
        after_nodes = self._snapshot.node_map
        for change in self._delta.node_changes[:8]:
            name = change.after_name or change.before_name or change.node_id
            field_names = {"name": "名称", "type_name": "类型", "namespace": "命名空间", "referenced": "引用状态", "reference_file": "引用文件", "dag_paths": "DAG 路径", "metadata": "元数据"}
            fields = " · %s" % ", ".join(field_names.get(item, item) for item in change.changed_fields) if change.changed_fields else ""
            kind = {"added": "新增", "removed": "移除", "modified": "修改", "renamed": "重命名"}.get(change.kind, change.kind)
            examples.append("%s  %s%s" % (kind, name, fields))
        for change in self._delta.reference_changes[:6]:
            path = change.after_path or change.before_path or "路径不可用"
            field_names = {
                "resolved_path": "解析路径",
                "unresolved_path": "原始路径",
                "canonical_path": "规范化源文件",
                "copy_number": "复制编号",
                "exists": "源文件存在状态",
                "loaded": "加载状态",
                "namespace": "命名空间",
                "parent_reference_node": "父引用",
                "failed_edit_count": "失败编辑数",
            }
            fields = " · %s" % ", ".join(field_names.get(item, item) for item in change.changed_fields) if change.changed_fields else ""
            examples.append(
                "引用 %s  %s%s\n    %s"
                % ({"added": "新增", "removed": "移除", "modified": "修改"}.get(change.kind, change.kind), change.reference_node, fields, path)
            )
        setting_names = {
            "time_unit": "时间单位",
            "frames_per_second": "帧率",
            "linear_unit": "线性单位",
            "angular_unit": "角度单位",
            "up_axis": "场景上轴",
            "color_management_enabled": "色彩管理",
            "rendering_space": "渲染空间",
            "view_transform": "视图变换",
            "color_config_path": "OCIO 配置",
        }
        if self._delta.setting_changes:
            examples.append(
                "场景设置  %s"
                % " · ".join(setting_names.get(item, item) for item in self._delta.setting_changes)
            )
        lifecycle_names = {
            "modified": "内存修改状态",
            "file_type": "文件类型",
            "workspace_root": "工作区",
            "current_time": "当前时间",
            "playback_min": "播放起点",
            "playback_max": "播放终点",
            "animation_start": "动画起点",
            "animation_end": "动画终点",
        }
        if self._delta.lifecycle_changes:
            examples.append(
                "场景生命周期  %s"
                % " · ".join(
                    lifecycle_names.get(item, item)
                    for item in self._delta.lifecycle_changes
                )
            )
        dependency_field_names = {
            "kind": "类型",
            "raw_path": "原始路径",
            "resolved_path": "解析路径",
            "exists": "存在状态",
            "path_kind": "路径形态",
            "inside_workspace": "工作区归属",
            "sequence_pattern": "序列标记",
            "sequence_kind": "序列类型",
            "sequence_member_count": "已发现成员",
            "sequence_expected_count": "范围内应有成员",
            "sequence_missing_count": "缺失成员",
            "sequence_missing_samples": "缺失样例",
            "sequence_scan_complete": "序列扫描完整性",
            "sequence_scan_reason": "序列扫描边界",
        }
        for change in self._delta.external_dependency_changes[:6]:
            fields = " · ".join(
                dependency_field_names.get(item, item) for item in change.changed_fields
            )
            path = change.after_path or change.before_path or change.dependency_id
            kind = {"added": "新增", "removed": "移除", "modified": "变化"}.get(
                change.kind, change.kind
            )
            examples.append(
                "外部依赖%s  %s%s"
                % (kind, path, " · " + fields if fields else "")
            )
        plugin_field_names = {
            "version": "版本",
            "node_types": "节点类型",
            "data_types": "数据类型",
        }
        for change in self._delta.unknown_plugin_changes[:6]:
            fields = " · ".join(
                plugin_field_names.get(item, item) for item in change.changed_fields
            )
            kind = {"added": "新增", "removed": "消失", "modified": "登记变化"}.get(
                change.kind, change.kind
            )
            examples.append(
                "插件幽灵%s  %s%s"
                % (kind, change.plugin_name, " · " + fields if fields else "")
            )
        for rewire in self._delta.rewires[:5]:
            old_node = before_nodes.get(rewire.old_source_id)
            new_node = after_nodes.get(rewire.new_source_id)
            target = after_nodes.get(rewire.target_id) or before_nodes.get(rewire.target_id)
            examples.append(
                "重连  %s → %s  接入  %s.%s"
                % (
                    old_node.name if old_node else rewire.old_source_id,
                    new_node.name if new_node else rewire.new_source_id,
                    target.name if target else rewire.target_id,
                    rewire.target_plug,
                )
            )
        self.clinic_view.set_body(
            "稳定 ID 结构对比\n%s → %s\n\n"
            "节点 +%s / −%s\n%s 项修改\n%s 次重连\n"
            "引用 +%s / −%s · %s 项修改\n外部依赖 +%s / −%s · %s 项修改\n插件幽灵 +%s / −%s · %s 项登记变化\n场景设置 %s 项变化 · 生命周期 %s 项变化\n连接 +%s / −%s\n\n%s"
            % (
                self._delta.before_snapshot_id[:8],
                self._delta.after_snapshot_id[:8],
                summary["nodes_added"],
                summary["nodes_removed"],
                summary["nodes_modified"],
                summary["rewires"],
                summary["references_added"],
                summary["references_removed"],
                summary["references_modified"],
                summary["external_dependencies_added"],
                summary["external_dependencies_removed"],
                summary["external_dependencies_modified"],
                summary["unknown_plugins_added"],
                summary["unknown_plugins_removed"],
                summary["unknown_plugins_modified"],
                summary["scene_settings_modified"],
                summary["scene_lifecycle_modified"],
                summary["edges_added"],
                summary["edges_removed"],
                "\n".join(examples) if examples else "未检测到结构变化。",
            )
        )
        self.clinic_view.set_action("只读对比", enabled=False)
        self.status.setText("  差异场  ·  %s 个身份发生变化" % len(self._delta.changed_node_ids))

    def _dismiss_delta(self):
        self.delta_strip.setVisible(False)
        self._delta = None
        self._delta_before = None
        if not self._lens_report:
            self.atlas.clear_lens()

    def _archive_snapshot(self):
        if not self._snapshot:
            return
        label = Path(self._snapshot.source_scene).stem if self._snapshot.source_scene else "untitled"
        try:
            record = self._store.save(self._snapshot, label=label)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "快照归档失败", str(exc))
            return
        self.status.setText("  快照已归档  ·  %s" % record.path.name)

    def _compare_archive(self):
        if not self._snapshot:
            QtWidgets.QMessageBox.information(self, "场景差异", "请先捕获当前场景。")
            return
        try:
            records = self._store.list_records()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "快照归档错误", str(exc))
            return
        if not records:
            QtWidgets.QMessageBox.information(
                self, "场景差异", "尚无已归档快照。捕获场景后请点击“归档”。"
            )
            return
        selected, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "选择要与当前场景对比的 MayaScope 快照",
            str(self._store.root),
            "MayaScope 快照 (*.mscope.json.gz)",
        )
        if not selected:
            return
        try:
            record = self._store.load(selected)
            delta = compare_snapshots(record.snapshot, self._snapshot)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "快照对比失败", str(exc))
            return
        self._set_delta(delta, record.snapshot)
        self._focus_delta()

    def _open_regression_report(self):
        selected, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "打开带签名的 MayaScope 回归报告",
            str(Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MayaScope"),
            "MayaScope 审计报告 (*.json)",
        )
        if not selected:
            return
        try:
            from ..audit import verify_audit_report

            payload = verify_audit_report(Path(selected))
            if not payload.get("regression"):
                raise ValueError("审计报告中不包含基线对比证据")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "回归报告已拒绝", str(exc))
            return
        self._show_regression_report(payload)

    def _open_project_audit(self):
        selected, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "打开带双重签名的 MayaScope 项目审计包",
            str(Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MayaScope"),
            "MayaScope 项目审计包 (*.json)",
        )
        if not selected:
            return
        try:
            from ..project_audit import verify_project_audit

            payload = verify_project_audit(Path(selected))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "项目审计包已拒绝", str(exc))
            return
        self._show_project_audit(payload)

    def _show_project_audit(self, payload):
        self._project_audit_payload = payload
        self.project_gate.set_report(payload)
        self._select_project_scene(0)
        summary = payload["summary"]
        state = "发布已阻断" if payload.get("gate_failed") else "全项目可以发布"
        self.status.setText(
            "  项目门禁  ·  %s  ·  %s/%s 场景通过"
            % (state, summary["passed_scene_count"], summary["scene_count"])
        )

    def _select_project_scene(self, index):
        payload = self._project_audit_payload
        if not payload or not 0 <= index < len(payload.get("scenes") or ()):
            return
        self.project_gate.select_scene(index)
        receipt = payload["scenes"][index]["receipt"]
        severity = receipt["severity_counts"]
        state = "阻断" if not receipt["ok"] or receipt["gate_failed"] else "通过"
        scene_name = Path(receipt["source_scene"]).name or receipt["source_scene"]
        self.clinic_view.set_body(
            "项目发布证据  /  场景 %s/%s\n%s\n\n状态：%s\n"
            "问题：%s · 原子发现：%s\n严重：%s · 错误：%s · 警告：%s · 信息：%s\n\n"
            "场景签名：%s\n项目签名：%s\n规则配置：%s"
            % (
                index + 1, len(payload["scenes"]), scene_name, state,
                receipt["issue_count"], receipt["atomic_finding_count"],
                severity.get("critical", 0), severity.get("error", 0),
                severity.get("warning", 0), severity.get("info", 0),
                receipt["report_sha256"][:16].upper() + "…",
                payload["project_sha256"][:16].upper() + "…",
                payload["context"].get("config_fingerprint", ""),
            )
        )

    def _dismiss_project_audit(self):
        if self._project_queue_thread and self._project_queue_thread.isRunning():
            return
        self.project_gate.setVisible(False)
        self.project_gate.clear()
        self._project_audit_payload = None
        self._project_queue_payload = None

    def _open_project_queue(self):
        if self._project_queue_thread and self._project_queue_thread.isRunning():
            self._cancel_project_queue()
            return
        if (
            (self._clinic_thread and self._clinic_thread.isRunning())
            or (self._bisect_thread and self._bisect_thread.isRunning())
            or self._scene_capture.active
            or self._runtime_capture.active
        ):
            self.status.setText("  批量审计等待中  ·  请先完成当前场景任务")
            return
        selected, _filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "打开带签名的 MayaScope 批量审计计划",
            str(Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "MayaScope"),
            "MayaScope 批量审计计划 (*.json)",
        )
        if not selected:
            return
        try:
            from ..project_queue import verify_project_plan, verify_queue_journal

            plan = verify_project_plan(Path(selected))
            root = (
                Path(os.environ.get("LOCALAPPDATA") or Path.home())
                / "MayaScope" / "项目审计队列" / plan["plan_sha256"][:16]
            )
            journal_path = root / "queue.journal.json"
            report_dir = root / "场景报告"
            project_report = root / "project-audit.json"
            existing = (
                verify_queue_journal(journal_path, plan) if journal_path.is_file() else None
            )
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "批量审计计划已拒绝", str(exc))
            return
        self._project_queue_plan_path = Path(selected).resolve()
        self._project_queue_journal_path = journal_path
        self._project_queue_report_dir = report_dir
        self._project_queue_report_path = project_report
        if existing:
            self._project_queue_progress(existing)
            if existing.get("state") == "完成":
                return
        settings = plan["settings"]
        action = "继续" if existing else "开始"
        if not _confirm_action(
            self,
            "%s项目批量审计" % action,
            "%s 个 Maya 场景将由隐藏 Maya 2025 严格串行审计。\n\n"
            "配置档：%s\n门槛：%s\n工作区：%s\n\n"
            "可随时选择“安全暂停”；当前场景完成后停止，已完成结果由签名断点保留。"
            % (
                len(plan["jobs"]), settings["profile"], settings["fail_on"],
                settings.get("workspace") or "按场景发现",
            ),
        ):
            return
        self._launch_project_queue()

    def _launch_project_queue(self):
        if self._project_queue_thread and self._project_queue_thread.isRunning():
            return
        if not all((
            self._project_queue_plan_path, self._project_queue_journal_path,
            self._project_queue_report_dir, self._project_queue_report_path,
        )):
            self.status.setText("  批量审计无法继续  ·  队列路径不完整")
            return
        cancel_event = threading.Event()
        thread = QtCore.QThread(self)
        worker = ProjectQueueWorker(
            self._project_queue_plan_path,
            self._project_queue_journal_path,
            self._project_queue_report_dir,
            self._project_queue_report_path,
            cancel_event,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._project_queue_progress)
        worker.finished.connect(self._project_queue_finished)
        worker.failed.connect(self._project_queue_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_project_queue_thread_finished)
        self._project_queue_cancel_event = cancel_event
        self._project_queue_thread = thread
        self._project_queue_worker = worker
        self.project_queue_button.setText("暂停队列")
        self.project_queue_button.setToolTip("当前场景完成后安全暂停")
        self.capture_button.setEnabled(False)
        self.bisect_button.setEnabled(False)
        self.runtime_button.setEnabled(False)
        self.clinic_array.run_button.setEnabled(False)
        thread.start()

    def _project_queue_progress(self, journal):
        self._project_queue_payload = journal
        self._project_audit_payload = None
        self.project_gate.set_queue(journal)
        jobs = journal.get("jobs") or ()
        focus = next(
            (index for index, job in enumerate(jobs) if job.get("status") == "运行中"),
            next((index for index, job in enumerate(jobs) if job.get("status") == "失败"), 0),
        )
        self._select_project_queue_job(focus)
        summary = journal.get("summary") or {}
        self.status.setText(
            "  批量审计  ·  %s  ·  完成 %s/%s"
            % (
                journal.get("state", "待运行"),
                summary.get("passed", 0) + summary.get("blocked", 0),
                summary.get("scene_count", len(jobs)),
            )
        )

    def _select_project_queue_job(self, index):
        journal = self._project_queue_payload
        jobs = journal.get("jobs") if journal else None
        if not jobs or not 0 <= index < len(jobs):
            return
        self.project_gate.select_scene(index)
        job = jobs[index]
        worker = job.get("worker") or {}
        worker_line = (
            "后台 Maya：PID %s · 父进程崩溃联动%s"
            % (
                worker.get("pid"),
                "已启用" if worker.get("job_kill_on_close") else "不可用，使用精确身份恢复",
            )
            if worker else "后台 Maya：尚未启动或已经回收"
        )
        storage = tuple(journal.get("storage_preflight") or ())
        storage_line = "磁盘容量：尚未预检"
        if storage:
            ready = all(item.get("ready") for item in storage)
            margin = min(
                int(item.get("free_bytes", 0)) - int(item.get("required_bytes", 0))
                for item in storage
            )
            storage_line = "磁盘容量：%s · 最小余量 %.1f GiB" % (
                "通过" if ready else "不足", margin / 1073741824.0,
            )
        self.clinic_view.set_body(
            "批量发布队列  /  场景 %s/%s\n%s\n\n状态：%s\n尝试次数：%s\n"
            "开始：%s\n完成：%s\n%s\n%s\n\n场景源签名：%s\n审计报告签名：%s%s"
            % (
                index + 1, len(jobs), job.get("source_scene", ""),
                job.get("status", "待运行"), job.get("attempts", 0),
                job.get("started_at") or "尚未开始",
                job.get("completed_at") or "尚未完成",
                worker_line, storage_line,
                job.get("source_sha256", "").upper(),
                (job.get("report_sha256") or "尚未生成").upper(),
                "\n\n失败原因：%s" % job.get("error") if job.get("error") else "",
            )
        )

    def _project_queue_action(self):
        journal = self._project_queue_payload or {}
        state = journal.get("state")
        if self._project_queue_thread and self._project_queue_thread.isRunning():
            self._cancel_project_queue()
        elif state == "完成" and journal.get("project_report"):
            try:
                from ..project_audit import verify_project_audit

                payload = verify_project_audit(Path(journal["project_report"]))
            except Exception as exc:
                QtWidgets.QMessageBox.critical(self, "项目结果已拒绝", str(exc))
                return
            self._show_project_audit(payload)
        elif state in {"已暂停", "需要重试", "待运行"}:
            self._launch_project_queue()

    def _cancel_project_queue(self):
        if self._project_queue_cancel_event is not None:
            self._project_queue_cancel_event.set()
            self.project_gate.queue_action.setEnabled(False)
            self.project_gate.queue_action.setText("正在安全暂停…")
            self.project_queue_button.setEnabled(False)
            self.project_queue_button.setText("正在暂停…")
            self.status.setText("  批量审计已排队暂停  ·  等待当前场景完成")

    def _project_queue_finished(self, journal):
        self._project_queue_progress(journal)
        state = journal.get("state")
        if state == "完成":
            self.status.setText("  批量审计完成  ·  项目结果已生成并签名")
        elif state == "已暂停":
            self.status.setText("  批量审计已安全暂停  ·  可从签名断点继续")
        else:
            self.status.setText("  批量审计需要重试  ·  失败场景已保留原因")

    def _project_queue_failed(self, message):
        self.status.setText("  批量审计停止  ·  %s" % message)
        if message.startswith("QueueBusyError:"):
            self.project_gate.set_fault("队列已由其他进程接管", message.split(":", 1)[-1].strip())
        elif message.startswith("InsufficientStorageError:"):
            # The signed journal has already been emitted through progress.
            if not self._project_queue_payload:
                self.project_gate.set_fault("磁盘容量预检未通过", message.split(":", 1)[-1].strip())
        QtWidgets.QMessageBox.critical(self, "批量审计停止", message)

    def _on_project_queue_thread_finished(self):
        self._project_queue_worker = None
        self._project_queue_thread = None
        self._project_queue_cancel_event = None
        self.project_queue_button.setEnabled(True)
        self.project_queue_button.setText("批量审计")
        self.project_queue_button.setToolTip("打开签名场景计划并在后台串行审计")
        if not self._runtime_capture.active:
            self.capture_button.setEnabled(True)
            self.bisect_button.setEnabled(True)
            self.runtime_button.setEnabled(self._snapshot is not None)
        self.clinic_array._sync_run_state()
        if self._close_after_project_queue:
            self._close_after_project_queue = False
            QtCore.QTimer.singleShot(0, self.close)

    def _show_regression_report(self, payload):
        self._regression_payload = payload
        self.regression_rift.set_report(payload)
        regression = payload["regression"]
        active = tuple(
            item.get("node_id", "")
            for group in (
                regression.get("new_findings", ()),
                regression.get("escalated_findings", ()),
            )
            for item in group
            if item.get("node_id") not in (None, "", "<scene>")
        )
        if active:
            self.atlas.highlight(active)
        performance = regression.get("performance", {})
        perf_line = "性能证据不可用。"
        if performance.get("comparable"):
            perf_line = (
                "求值中位数：%.2f → %.2f ms\n触发门槛：%.2f ms\n"
                "实测变化：%+.2f ms (%+.1f%%)"
                % (
                    performance["baseline"]["median_us"] / 1000.0,
                    performance["current"]["median_us"] / 1000.0,
                    performance["required_delta_us"] / 1000.0,
                    performance["delta_us"] / 1000.0,
                    performance["slowdown_ratio"] * 100.0,
                )
            )
        self.clinic_view.set_body(
            "签名回归证据\n%s\n\n新增：%s · 升级：%s · 已解决：%s\n%s"
            % (
                "检测到回归裂隙" if regression.get("gate_failed") else "基线保持稳定",
                len(regression.get("new_findings", ())),
                len(regression.get("escalated_findings", ())),
                len(regression.get("resolved_findings", ())),
                perf_line,
            )
        )
        state = "门禁失败" if regression.get("gate_failed") else "基线保持稳定"
        self.status.setText("  回归裂隙  ·  %s" % state)

    def _dismiss_regression(self):
        self.regression_rift.setVisible(False)
        self.regression_rift.clear()
        self._regression_payload = None
        if not self._lens_report and not self._delta:
            self.atlas.clear_lens()

    def _close_lens(self, *_args):
        transition = self._investigation.close_lens(self._presentation)
        self._apply_investigation_transition(transition)
        self._present_closed_lens_chrome()

    def _present_closed_lens_chrome(self):
        """Reset Lens-only copy after its state and Atlas overlay are resolved."""
        self._hide_lens_chrome()
        self.clinic_view.set_heading(
            "%s 个事件簇 · %s 项发现"
            % (len(self._incidents), len(self._issues))
            if self._issues else "场景信号正常"
        )
        self.clinic_view.set_body("选择一个异常或节点，开始调查。")
        self.clinic_view.set_action("预览变更计划", enabled=False)

    def _select_focus_in_maya(self):
        if not self._snapshot or not self._focus_node_id:
            return
        self._sync_node_to_maya(self._focus_node_id, require_link=False)


def _maya_main_window():
    try:
        import maya.OpenMayaUI as omui  # type: ignore
        pointer = omui.MQtUtil.mainWindow()
        if not pointer:
            return None
        from shiboken6 import wrapInstance
        return wrapInstance(int(pointer), QtWidgets.QWidget)
    except Exception:
        return None


def show_tool(clinic_environment: Optional[ClinicEnvironment] = None):
    global _WINDOW
    close_tool()
    _WINDOW = MayaScopeWorkspace(
        parent=_maya_main_window(), clinic_environment=clinic_environment
    )
    _WINDOW.show()
    _WINDOW.raise_()
    _WINDOW.activateWindow()
    return _WINDOW


def close_tool():
    global _WINDOW
    if _WINDOW is not None:
        window = _WINDOW
        bisect_running = bool(
            window._bisect_thread and window._bisect_thread.isRunning()
        )
        clinic_running = bool(
            window._clinic_thread and window._clinic_thread.isRunning()
        )
        queue_running = bool(
            window._project_queue_thread and window._project_queue_thread.isRunning()
        )
        running = bisect_running or clinic_running or queue_running
        window.close()
        if running:
            # closeEvent has queued a safe close after the current hidden probe.
            # Defer deletion too, otherwise the owned QThread could be destroyed
            # while its mayapy child is still being reaped.
            active_thread = (
                window._bisect_thread
                if bisect_running
                else window._clinic_thread
                if clinic_running
                else window._project_queue_thread
            )
            active_thread.finished.connect(
                lambda: QtCore.QTimer.singleShot(0, window.deleteLater)
            )
        else:
            window.deleteLater()
        _WINDOW = None
