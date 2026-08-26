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
from ..analysis.delta import SceneDelta, compare_snapshots
from ..analysis.clinic import (
    ClinicCancelled,
    ClinicReport,
    DEFAULT_PROFILES,
    DEFAULT_REGISTRY,
    RuleProfile,
    RuleSpec,
)
from ..analysis.incidents import Incident, cluster_issues
from ..analysis.identity import build_host_identity_index
from ..analysis.graph import (
    QueryCancelled,
    alias_graph_indexes,
    get_graph_index,
    invalidate_graph_indexes,
)
from ..analysis.config import ClinicConfigError, ClinicEnvironment, load_environment_from_env
from ..analysis.lens import RootCauseCandidate, RootCauseReport, build_root_cause_report
from ..analysis.measured_lens import (
    MeasuredCandidate,
    MeasuredRootCauseReport,
    build_measured_root_cause_report,
)
from ..analysis.runtime import analyze_runtime
from ..analysis.pulse import PulseNodeStat, node_stats
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
from ..model import ProfilerCapture, SceneNode, SceneSnapshot
from ..host_health import HostHealth, collect_host_health
from ..qt_compat import QtCore, QtGui, QtWidgets
from ..runtime_log import log_event
from ..runner import (
    BisectSession,
    build_post_open_bisect_plan,
    build_pre_open_ascii_bisect_plan,
    load_bisect_journal,
)
from ..storage import ExperimentStore, SnapshotStore


WINDOW_OBJECT_NAME = "MayaScopeSpectralWorkspace"
MAX_RENDER_NODES = 240
_WINDOW = None


COLORS = {
    "void": QtGui.QColor("#07060D"),
    "panel": QtGui.QColor("#11101A"),
    "violet": QtGui.QColor("#9C5CFF"),
    "orange": QtGui.QColor("#FF6A2A"),
    "acid": QtGui.QColor("#C8FF3D"),
    "cyan": QtGui.QColor("#48D7FF"),
    "text": QtGui.QColor("#F4F0FF"),
    "muted": QtGui.QColor("#8E899C"),
}


def _qt_enum(container, name):
    """Resolve Qt5/Qt6 enum spelling without spreading version branches."""
    direct = getattr(container, name, None)
    if direct is not None:
        return direct
    for group_name in (
        "AlignmentFlag", "PenStyle", "BrushStyle", "MouseButton", "ItemDataRole",
        "ScrollBarPolicy", "Orientation", "TextFormat", "FocusPolicy", "Key",
    ):
        group = getattr(container, group_name, None)
        value = getattr(group, name, None) if group else None
        if value is not None:
            return value
    raise AttributeError(name)


def _confirm_action(parent, title: str, message: str) -> bool:
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


def _ensure_ui_fonts() -> None:
    """Give Maya standalone/offscreen the same legible typography as Maya UI.

    Qt's offscreen platform can start with an empty font database on Windows.
    Loading the system face explicitly is harmless in interactive Maya and makes
    automated visual evidence representative instead of rendering tofu glyphs.
    """
    font_root = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for filename in (
        "msyh.ttc", "msyhbd.ttc", "msyhl.ttc",
        "Deng.ttf", "Dengb.ttf", "Dengl.ttf",
        "segoeui.ttf", "seguisb.ttf", "segoeuib.ttf",
    ):
        path = font_root / filename
        if path.is_file():
            QtGui.QFontDatabase.addApplicationFont(str(path))
    app = QtWidgets.QApplication.instance()
    if app:
        for family in ("Microsoft YaHei UI", "Microsoft YaHei", "DengXian", "Segoe UI"):
            if QtGui.QFontDatabase.hasFamily(family):
                app.setFont(QtGui.QFont(family, 9))
                break


class AtlasNodeItem(QtWidgets.QGraphicsObject):
    WIDTH, HEIGHT = 150.0, 54.0

    def __init__(self, node: SceneNode, degree: int, parent=None):
        super().__init__(parent)
        self.node = node
        self.degree = degree
        self._hot = False
        self._heat = 0.0
        self._role = "normal"
        self.setAcceptHoverEvents(True)
        self.setFlag(QtWidgets.QGraphicsItem.ItemIsSelectable, True)
        self.setToolTip("%s\n%s\n%s" % (node.name, node.type_name, node.dag_paths[0] if node.dag_paths else node.id))
        shadow = QtWidgets.QGraphicsDropShadowEffect()
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 4)
        shadow.setColor(QtGui.QColor(132, 55, 255, 115))
        self.setGraphicsEffect(shadow)

    def boundingRect(self):
        return QtCore.QRectF(-self.WIDTH / 2, -self.HEIGHT / 2, self.WIDTH, self.HEIGHT)

    def set_hot(self, value: bool):
        self._hot = value
        self.update()

    def set_role(self, role: str):
        self._role = role
        self.update()

    def set_heat(self, value: float):
        self._heat = max(0.0, min(1.0, float(value)))
        self.update()

    def hoverEnterEvent(self, event):
        self.setScale(1.06)
        self.setZValue(3)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setScale(1.0)
        self.setZValue(0)
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        rect = self.boundingRect()
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
        if self._role == "pulse":
            heat = self._heat
            hot = QtGui.QColor.fromRgbF(1.0, 0.25 + 0.22 * (1.0 - heat), 0.08)
            cool = QtGui.QColor.fromRgbF(0.18 + 0.22 * heat, 0.05, 0.24 + 0.12 * heat)
            gradient.setColorAt(0, hot)
            gradient.setColorAt(1, cool)
            edge = COLORS["acid"] if heat > 0.72 else COLORS["orange"]
        elif self._role == "focus":
            gradient.setColorAt(0, QtGui.QColor("#31451A"))
            gradient.setColorAt(1, QtGui.QColor("#10160B"))
            edge = COLORS["acid"]
        elif self._role == "candidate":
            gradient.setColorAt(0, QtGui.QColor("#54231D"))
            gradient.setColorAt(1, QtGui.QColor("#1A1017"))
            edge = COLORS["orange"]
        elif self._role == "path":
            gradient.setColorAt(0, QtGui.QColor("#153346"))
            gradient.setColorAt(1, QtGui.QColor("#0B1119"))
            edge = COLORS["cyan"]
        elif self._role == "delta_added":
            gradient.setColorAt(0, QtGui.QColor("#30471A"))
            gradient.setColorAt(1, QtGui.QColor("#0E170B"))
            edge = COLORS["acid"]
        elif self._role == "delta_modified":
            gradient.setColorAt(0, QtGui.QColor("#5B251C"))
            gradient.setColorAt(1, QtGui.QColor("#1B0E0D"))
            edge = COLORS["orange"]
        elif self._role == "delta_rewire":
            gradient.setColorAt(0, QtGui.QColor("#123B4B"))
            gradient.setColorAt(1, QtGui.QColor("#09141B"))
            edge = COLORS["cyan"]
        elif self._role == "delta_reference":
            gradient.setColorAt(0, QtGui.QColor("#17344B"))
            gradient.setColorAt(1, QtGui.QColor("#20102F"))
            edge = QtGui.QColor("#58F0FF")
        elif self._role == "delta_external":
            gradient.setColorAt(0, QtGui.QColor("#5B2412"))
            gradient.setColorAt(1, QtGui.QColor("#17100B"))
            edge = QtGui.QColor("#FFB02E")
        elif self._role == "counterfactual_gain":
            heat = self._heat
            gradient.setColorAt(0, QtGui.QColor.fromRgbF(0.42 + 0.18 * heat, 0.68, 0.12))
            gradient.setColorAt(1, QtGui.QColor("#0B1812"))
            edge = COLORS["acid"]
        elif self._role == "counterfactual_regression":
            heat = self._heat
            gradient.setColorAt(0, QtGui.QColor.fromRgbF(0.62 + 0.2 * heat, 0.16, 0.08))
            gradient.setColorAt(1, QtGui.QColor("#1D0A10"))
            edge = COLORS["orange"]
        elif self.node.type_name in {"unknown", "unknownDag", "unknownTransform"}:
            gradient.setColorAt(0, QtGui.QColor("#54231D"))
            gradient.setColorAt(1, QtGui.QColor("#1A1017"))
            edge = COLORS["orange"]
        else:
            gradient.setColorAt(0, QtGui.QColor("#21143A"))
            gradient.setColorAt(1, QtGui.QColor("#0D0C16"))
            edge = COLORS["acid"] if self._hot or self.isSelected() else COLORS["violet"]
        painter.setBrush(QtGui.QBrush(gradient))
        painter.setPen(QtGui.QPen(edge, 2.4 if self._hot or self.isSelected() else 1.1))
        painter.drawRoundedRect(rect, 11, 11)

        painter.setPen(COLORS["text"])
        font = painter.font()
        font.setBold(True)
        font.setPointSize(9)
        painter.setFont(font)
        clipped = self.node.name if len(self.node.name) < 22 else self.node.name[:19] + "…"
        painter.drawText(QtCore.QRectF(rect.left() + 13, rect.top() + 8, 119, 18), clipped)
        font.setBold(False)
        font.setPointSize(7)
        painter.setFont(font)
        painter.setPen(COLORS["muted"])
        painter.drawText(
            QtCore.QRectF(rect.left() + 13, rect.top() + 29, 124, 16),
            "%s  ·  流量 %s" % (self.node.type_name, self.degree),
        )

        painter.setPen(_qt_enum(QtCore.Qt, "NoPen"))
        painter.setBrush(edge)
        painter.drawEllipse(QtCore.QPointF(rect.right() - 10, rect.top() + 11), 3.0, 3.0)


class AtlasEdgeItem(QtWidgets.QGraphicsPathItem):
    def __init__(self, source: AtlasNodeItem, target: AtlasNodeItem, relation: str):
        super().__init__()
        self.source, self.target = source, target
        self.relation = relation
        self._tracing = False
        self._base_color = QtGui.QColor(COLORS["violet"] if relation == "dg" else COLORS["cyan"])
        self._base_color.setAlpha(78 if relation == "dg" else 48)
        self.setPen(QtGui.QPen(self._base_color, 1.0))
        self.setZValue(-2)
        self.refresh()

    @property
    def key(self):
        return self.source.node.id, self.target.node.id

    def set_trace(self, active: bool, in_scope: bool = False):
        self._tracing = active
        if active:
            pen = QtGui.QPen(COLORS["acid"], 2.2)
            pen.setStyle(_qt_enum(QtCore.Qt, "DashLine"))
            self.setPen(pen)
            self.setOpacity(1.0)
            self.setZValue(-1)
        else:
            self.setPen(QtGui.QPen(self._base_color, 1.0))
            self.setOpacity(1.0 if in_scope else 0.055)
            self.setZValue(-2)

    def animate_trace(self, phase: float):
        if not self._tracing:
            return
        pen = self.pen()
        pen.setDashOffset(-phase * 32.0)
        self.setPen(pen)

    def refresh(self):
        a, b = self.source.pos(), self.target.pos()
        dx = b.x() - a.x()
        path = QtGui.QPainterPath(a)
        path.cubicTo(a.x() + dx * 0.45, a.y(), b.x() - dx * 0.45, b.y(), b.x(), b.y())
        self.setPath(path)


class SpectralAtlasView(QtWidgets.QGraphicsView):
    nodeActivated = QtCore.Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setAccessibleName("场景图谱因果关系图")
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.TextAntialiasing)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setHorizontalScrollBarPolicy(_qt_enum(QtCore.Qt, "ScrollBarAlwaysOff"))
        self.setVerticalScrollBarPolicy(_qt_enum(QtCore.Qt, "ScrollBarAlwaysOff"))
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        self._phase = 0.0
        self._node_items: Dict[str, AtlasNodeItem] = {}
        self._edge_items = []
        self._snapshot: Optional[SceneSnapshot] = None
        self._graph = None
        self._ranked_node_ids: Tuple[str, ...] = ()
        self._suppress_selection_signal = False
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(48)
        self.scene().selectionChanged.connect(self._selection_changed)

    def set_motion_enabled(self, enabled: bool):
        if enabled:
            self._timer.start(48)
        else:
            self._timer.stop()
            self._phase = 0.0
            self.viewport().update()

    def wheelEvent(self, event):
        factor = 1.13 if event.angleDelta().y() > 0 else 0.885
        current = self.transform().m11()
        if 0.18 < current * factor < 3.2:
            self.scale(factor, factor)

    def _tick(self):
        self._phase = (self._phase + 0.018) % 1.0
        for edge in self._edge_items:
            edge.animate_trace(self._phase)
        self.viewport().update()

    def drawBackground(self, painter, rect):
        gradient = QtGui.QRadialGradient(rect.center(), max(rect.width(), rect.height()) * 0.68)
        gradient.setColorAt(0, QtGui.QColor("#17102A"))
        gradient.setColorAt(0.52, QtGui.QColor("#0B0913"))
        gradient.setColorAt(1, COLORS["void"])
        painter.fillRect(rect, gradient)

        painter.save()
        grid = QtGui.QColor(156, 92, 255, 17)
        painter.setPen(QtGui.QPen(grid, 1))
        spacing = 46
        left = math.floor(rect.left() / spacing) * spacing
        top = math.floor(rect.top() / spacing) * spacing
        x = left
        while x < rect.right():
            painter.drawLine(QtCore.QLineF(x, rect.top(), x, rect.bottom()))
            x += spacing
        y = top
        while y < rect.bottom():
            painter.drawLine(QtCore.QLineF(rect.left(), y, rect.right(), y))
            y += spacing

        scan_x = rect.left() + rect.width() * self._phase
        beam = QtGui.QLinearGradient(scan_x - 65, 0, scan_x + 25, 0)
        beam.setColorAt(0, QtGui.QColor(200, 255, 61, 0))
        beam.setColorAt(0.75, QtGui.QColor(200, 255, 61, 18))
        beam.setColorAt(1, QtGui.QColor(200, 255, 61, 0))
        painter.fillRect(QtCore.QRectF(scan_x - 65, rect.top(), 90, rect.height()), beam)
        painter.restore()

    def set_snapshot(
        self,
        snapshot: SceneSnapshot,
        issues: Sequence[Issue],
        priority_node_ids: Iterable[str] = (),
    ):
        priority_node_ids = tuple(priority_node_ids)
        if self._snapshot is not snapshot:
            self.scene().clear()
            self._node_items.clear()
            self._edge_items = []
        self._snapshot = snapshot
        self._graph = get_graph_index(snapshot, ("dg", "dag"))
        self._ranked_node_ids = self._graph.ranked_node_ids()
        affected = tuple(
            dict.fromkeys(
                node_id
                for issue in issues
                for node_id in issue.affected_node_ids
            )
        )
        self._materialize(priority_node_ids + affected)

    def _materialize(self, priority_node_ids: Iterable[str] = ()):
        if not self._snapshot or self._graph is None:
            return
        node_map = self._snapshot.node_map
        requested = []
        seen = set()
        for node_id in tuple(priority_node_ids) + self._ranked_node_ids:
            if node_id in node_map and node_id not in seen:
                seen.add(node_id)
                requested.append(node_id)
                if len(requested) >= MAX_RENDER_NODES:
                    break
        visible_ids = set(requested)
        for edge_item in self._edge_items:
            self.scene().removeItem(edge_item)
        self._edge_items = []
        for node_id in tuple(self._node_items):
            if node_id not in visible_ids:
                item = self._node_items.pop(node_id)
                self.scene().removeItem(item)
                item.deleteLater()

        # Concentric topology: high-flux and problematic nodes form the investigative core.
        for index, node_id in enumerate(requested):
            node = node_map[node_id]
            ring = int(math.sqrt(index / 10.0))
            radius = 65 + ring * 190
            items_in_ring = max(10, int(2 * math.pi * radius / 185))
            angle = (index % items_in_ring) / float(items_in_ring) * math.tau + ring * 0.43
            item = self._node_items.get(node_id)
            if item is None:
                item = AtlasNodeItem(node, self._graph.degree(node.id))
                self.scene().addItem(item)
                self._node_items[node.id] = item
            item.setPos(math.cos(angle) * radius, math.sin(angle) * radius)

        for source_id in requested:
            for target_id in self._graph.forward[source_id]:
                if target_id not in visible_ids:
                    continue
                for edge in self._graph.edges_between(source_id, target_id):
                    item = AtlasEdgeItem(
                        self._node_items[source_id], self._node_items[target_id], edge.relation
                    )
                    self.scene().addItem(item)
                    self._edge_items.append(item)
        bounds = self.scene().itemsBoundingRect().adjusted(-130, -130, 130, 130)
        self.scene().setSceneRect(bounds)
        self.fitInView(bounds, _qt_enum(QtCore.Qt, "KeepAspectRatio"))

    def _ensure_materialized(self, node_ids: Iterable[str]):
        requested = tuple(dict.fromkeys(node_ids))[:MAX_RENDER_NODES]
        if any(node_id not in self._node_items for node_id in requested):
            self._materialize(requested)

    def highlight(self, node_ids: Iterable[str]):
        selected = set(node_ids)
        self._ensure_materialized(selected)
        for node_id, item in self._node_items.items():
            item.set_role("normal")
            item.set_heat(0.0)
            item.set_hot(node_id in selected)
            item.setOpacity(1.0 if not selected or node_id in selected else 0.22)
        for edge in self._edge_items:
            edge.set_trace(False, edge.key[0] in selected and edge.key[1] in selected)
        visible = [self._node_items[node_id] for node_id in selected if node_id in self._node_items]
        if visible:
            bounds = visible[0].sceneBoundingRect()
            for item in visible[1:]:
                bounds = bounds.united(item.sceneBoundingRect())
            self.ensureVisible(bounds.adjusted(-80, -80, 80, 80), 40, 40)

    def show_lens(
        self, report: RootCauseReport, candidate: Optional[RootCauseCandidate] = None
    ):
        priority = [report.focus_node_id]
        if candidate:
            priority.extend(candidate.path_node_ids)
        priority.extend(item.node_id for item in report.candidates)
        priority.extend(report.scope_node_ids)
        self._ensure_materialized(priority)
        scope = set(report.scope_node_ids)
        candidate_ids = {item.node_id for item in report.candidates}
        path = set(candidate.path_node_ids if candidate else report.path_node_ids)
        trace_edges = set()
        if candidate:
            trace_edges = {(link.source_id, link.target_id) for link in candidate.path_links}
        for node_id, item in self._node_items.items():
            item.set_heat(0.0)
            if node_id == report.focus_node_id:
                role = "focus"
            elif candidate and node_id == candidate.node_id:
                role = "candidate"
            elif node_id in path:
                role = "path"
            elif node_id in candidate_ids:
                role = "candidate"
            else:
                role = "normal"
            item.set_hot(False)
            item.set_role(role)
            item.setOpacity(1.0 if node_id in scope else 0.07)
        for edge in self._edge_items:
            edge.set_trace(edge.key in trace_edges, edge.key[0] in scope and edge.key[1] in scope)
        visible_ids = set(candidate.path_node_ids if candidate else report.scope_node_ids)
        visible = [self._node_items[node_id] for node_id in visible_ids if node_id in self._node_items]
        if visible:
            bounds = visible[0].sceneBoundingRect()
            for item in visible[1:]:
                bounds = bounds.united(item.sceneBoundingRect())
            self.fitInView(bounds.adjusted(-130, -130, 130, 130), _qt_enum(QtCore.Qt, "KeepAspectRatio"))

    def clear_lens(self):
        for item in self._node_items.values():
            item.set_role("normal")
            item.set_hot(False)
            item.set_heat(0.0)
            item.setOpacity(1.0)
        for edge in self._edge_items:
            edge.set_trace(False, True)

    def show_delta(self, delta: SceneDelta):
        added = {change.node_id for change in delta.node_changes if change.kind == "added"}
        modified = {
            change.node_id
            for change in delta.node_changes
            if change.kind in {"modified", "renamed"}
        }
        rewired = {
            node_id
            for change in delta.rewires
            for node_id in (change.old_source_id, change.new_source_id, change.target_id)
        }
        reference_changed = {
            node_id for change in delta.reference_changes for node_id in change.node_ids
        }
        external_changed = {
            change.node_id for change in delta.external_dependency_changes
        }
        changed = added | modified | rewired | reference_changed | external_changed
        self._ensure_materialized(changed)
        added_edges = {
            (change.source_id, change.target_id)
            for change in delta.edge_changes
            if change.kind == "added"
        }
        added_edges.update((change.new_source_id, change.target_id) for change in delta.rewires)
        for node_id, item in self._node_items.items():
            item.set_heat(0.0)
            if node_id in added:
                role = "delta_added"
            elif node_id in modified:
                role = "delta_modified"
            elif node_id in rewired:
                role = "delta_rewire"
            elif node_id in reference_changed:
                role = "delta_reference"
            elif node_id in external_changed:
                role = "delta_external"
            else:
                role = "normal"
            item.set_role(role)
            item.set_hot(False)
            item.setOpacity(1.0 if node_id in changed else 0.09)
        for edge in self._edge_items:
            edge.set_trace(edge.key in added_edges, edge.key[0] in changed or edge.key[1] in changed)
        visible = [self._node_items[node_id] for node_id in changed if node_id in self._node_items]
        if visible:
            bounds = visible[0].sceneBoundingRect()
            for item in visible[1:]:
                bounds = bounds.united(item.sceneBoundingRect())
            self.fitInView(bounds.adjusted(-130, -130, 130, 130), _qt_enum(QtCore.Qt, "KeepAspectRatio"))

    def show_pulse(self, stats: Sequence[PulseNodeStat]):
        if not stats:
            self.clear_lens()
            return
        peak = max(stat.inclusive_duration_us for stat in stats) or 1
        self._ensure_materialized(stat.node_id for stat in stats)
        heat = {stat.node_id: stat.inclusive_duration_us / float(peak) for stat in stats}
        for node_id, item in self._node_items.items():
            intensity = heat.get(node_id, 0.0)
            item.set_role("pulse" if intensity else "normal")
            item.set_heat(intensity)
            item.set_hot(intensity > 0.72)
            item.setOpacity(0.18 + 0.82 * math.sqrt(intensity) if intensity else 0.07)
        active = set(heat)
        for edge in self._edge_items:
            edge.set_trace(False, edge.key[0] in active and edge.key[1] in active)

    def show_counterfactual(self, report: CounterfactualReport):
        effects = {item.node_id: item.observed_delta_us for item in report.node_effects}
        peak = max((abs(value) for value in effects.values()), default=1.0) or 1.0
        active = set(effects)
        for node_id, item in self._node_items.items():
            delta = effects.get(node_id, 0.0)
            intensity = abs(delta) / peak if delta else 0.0
            if delta > 0:
                item.set_role("counterfactual_gain")
            elif delta < 0:
                item.set_role("counterfactual_regression")
            else:
                item.set_role("normal")
            item.set_heat(intensity)
            item.set_hot(node_id == report.target_node_id)
            item.setOpacity(0.2 + 0.8 * math.sqrt(intensity) if intensity else 0.06)
        for edge in self._edge_items:
            edge.set_trace(False, edge.key[0] in active and edge.key[1] in active)
        target = self._node_items.get(report.target_node_id)
        if target:
            self.centerOn(target)

    def filter_nodes(self, query: str):
        query = query.strip().lower()
        for item in self._node_items.values():
            match = not query or query in item.node.name.lower() or query in item.node.type_name.lower()
            item.setOpacity(1.0 if match else 0.12)

    def select_node_ids(self, node_ids: Iterable[str], *, center: bool = False):
        """Apply external selection without re-emitting it as an Atlas click."""
        selected = tuple(dict.fromkeys(node_ids))
        self._ensure_materialized(selected)
        self._suppress_selection_signal = True
        try:
            self.scene().clearSelection()
            for node_id in selected:
                item = self._node_items.get(node_id)
                if item:
                    item.setSelected(True)
        finally:
            self._suppress_selection_signal = False
        visible = [self._node_items[node_id] for node_id in selected if node_id in self._node_items]
        if center and visible:
            bounds = visible[0].sceneBoundingRect()
            for item in visible[1:]:
                bounds = bounds.united(item.sceneBoundingRect())
            self.ensureVisible(bounds.adjusted(-90, -90, 90, 90), 40, 40)

    def _selection_changed(self):
        if self._suppress_selection_signal:
            return
        selected = self.scene().selectedItems()
        if selected and isinstance(selected[0], AtlasNodeItem):
            self.nodeActivated.emit(selected[0].node.id)


class PulseHorizon(QtWidgets.QWidget):
    rangeSelected = QtCore.Signal(object)
    profileRequested = QtCore.Signal()
    counterfactualRequested = QtCore.Signal()

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
        painter.setPen(QtGui.QColor("#B9B2C6"))
        painter.drawText(int(plot.right() - 180), 42, "范围 %.2f–%.2f ms" % (start / 1000.0, end / 1000.0))

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


class ClinicSpectrum(QtWidgets.QWidget):
    """Compact live glyph for rule channels, findings, and isolated failures."""

    CHANNELS = ("integrity", "performance", "references", "pipeline")

    def __init__(self, registry=DEFAULT_REGISTRY, parent=None):
        super().__init__(parent)
        self.registry = registry
        self.setFixedHeight(48)
        self._report: Optional[ClinicReport] = None
        self._phase = 0.0
        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(55)

    def set_report(self, report: Optional[ClinicReport]):
        self._report = report
        self.update()

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

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#09070F"))
        specs = {spec.id: spec for spec in self.registry.specs}
        runs = {run.rule_id: run for run in self._report.runs} if self._report else {}
        failed = {item.rule_id for item in self._report.failures} if self._report else set()
        skipped = set(self._report.skipped_rule_ids) if self._report else set()
        channel_values = {name: [0, 0, 0.0] for name in self.CHANNELS}
        for rule_id, run in runs.items():
            category = specs[rule_id].category
            channel_values[category][0] += 1
            channel_values[category][1] += run.issue_count
            channel_values[category][2] += run.duration_ms
        colors = (COLORS["acid"], COLORS["orange"], COLORS["cyan"], COLORS["violet"])
        lane = self.width() / 4.0
        for index, category in enumerate(self.CHANNELS):
            x = index * lane + 5
            width = lane - 10
            run_count, issue_count, _duration = channel_values[category]
            color = QtGui.QColor(colors[index])
            related = [spec.id for spec in self.registry.specs if spec.category == category]
            if any(rule_id in failed for rule_id in related):
                color = QtGui.QColor("#FF335F")
            elif related and all(rule_id in skipped for rule_id in related):
                color = QtGui.QColor("#393342")
            painter.setPen(QtGui.QPen(QtGui.QColor(color), 1.0))
            painter.setBrush(QtGui.QColor(color.red(), color.green(), color.blue(), 30 + min(120, issue_count * 35)))
            painter.drawRoundedRect(QtCore.QRectF(x, 5, width, 28), 4, 4)
            if run_count:
                sweep = x + ((self._phase + index * 0.19) % 1.0) * width
                painter.fillRect(QtCore.QRectF(sweep - 8, 6, 16, 26), QtGui.QColor(color.red(), color.green(), color.blue(), 32))
            painter.setPen(color)
            painter.drawText(QtCore.QRectF(x, 6, width, 12), _qt_enum(QtCore.Qt, "AlignCenter"), str(issue_count))
            painter.setPen(COLORS["muted"])
            channel_name = {"integrity": "完整性", "performance": "性能", "references": "引用", "pipeline": "流程"}.get(category, category)
            painter.drawText(QtCore.QRectF(x, 34, width, 11), _qt_enum(QtCore.Qt, "AlignCenter"), channel_name)


class ClinicRuleArray(QtWidgets.QFrame):
    runRequested = QtCore.Signal()
    ruleFocusRequested = QtCore.Signal(str)

    def __init__(self, registry=DEFAULT_REGISTRY, profiles=DEFAULT_PROFILES, config_source="built-in", config_fingerprint="built-in", parent=None):
        super().__init__(parent)
        self.registry = registry
        self.setObjectName("ClinicArray")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(10, 9, 10, 9)
        layout.setSpacing(6)
        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("场景诊所  /  规则阵列")
        title.setObjectName("ClinicTitle")
        header.addWidget(title)
        header.addStretch(1)
        self.config_badge = QtWidgets.QLabel(
            "内置规则" if config_source == "built-in" else "团队规则 %s" % config_fingerprint[:7].upper()
        )
        self.config_badge.setObjectName("ClinicConfigBadge")
        self.config_badge.setToolTip("诊所规则来源：%s\n指纹：%s" % (config_source, config_fingerprint))
        header.addWidget(self.config_badge)
        self.profile_combo = QtWidgets.QComboBox()
        self.profile_combo.setObjectName("ClinicProfile")
        for profile in profiles:
            self.profile_combo.addItem(profile.title, profile)
        self.profile_combo.setToolTip("切换适合当前制作阶段的规则组合")
        self.profile_combo.currentIndexChanged.connect(self._apply_profile)
        header.addWidget(self.profile_combo)
        layout.addLayout(header)
        self.contract_band = QtWidgets.QFrame()
        self.contract_band.setObjectName("SceneContractBand")
        contract_layout = QtWidgets.QGridLayout(self.contract_band)
        contract_layout.setContentsMargins(7, 4, 7, 4)
        contract_layout.setHorizontalSpacing(5)
        contract_layout.setVerticalSpacing(3)
        self.contract_title = QtWidgets.QLabel("制片信号")
        self.contract_title.setObjectName("SceneContractTitle")
        contract_layout.addWidget(self.contract_title, 0, 0)
        self.setting_chips = []
        positions = ((0, 1), (0, 2), (0, 3), (1, 0))
        for text, (row, column) in zip(
            ("帧率 · —", "尺度 · —", "上轴 · —", "色彩 · —"), positions
        ):
            chip = QtWidgets.QLabel(text)
            chip.setObjectName("SceneSettingChip")
            contract_layout.addWidget(chip, row, column)
            self.setting_chips.append(chip)
        self.dependency_chip = QtWidgets.QPushButton("依赖谱系 · —")
        self.dependency_chip.setObjectName("SceneDependencyChip")
        self.dependency_chip.setCursor(
            QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor"))
        )
        self.dependency_chip.setToolTip("点击定位外部依赖健康诊断规则")
        self.dependency_chip.clicked.connect(self._focus_dependency_health)
        contract_layout.addWidget(self.dependency_chip, 2, 0, 1, 4)
        self.plugin_chip = QtWidgets.QPushButton("插件幽灵 · —")
        self.plugin_chip.setObjectName("ScenePluginChip")
        self.plugin_chip.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.plugin_chip.setToolTip("点击定位缺失插件诊断规则")
        self.plugin_chip.clicked.connect(self._focus_missing_plugins)
        contract_layout.addWidget(self.plugin_chip, 1, 2, 1, 2)
        self.reference_chip = QtWidgets.QPushButton("引用轨道 · —")
        self.reference_chip.setObjectName("SceneReferenceChip")
        self.reference_chip.setCursor(
            QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor"))
        )
        self.reference_chip.setToolTip("点击定位引用健康诊断规则")
        self.reference_chip.clicked.connect(self._focus_reference_health)
        contract_layout.addWidget(self.reference_chip, 3, 0, 1, 4)
        self._reference_focus_rule = "unloaded-references"
        self._dependency_focus_rule = "missing-external-files"
        for column in range(4):
            contract_layout.setColumnStretch(column, 1)
        layout.addWidget(self.contract_band)
        self.spectrum = ClinicSpectrum(registry)
        layout.addWidget(self.spectrum)
        self.rules_scroll = QtWidgets.QScrollArea()
        self.rules_scroll.setObjectName("RuleScroll")
        self.rules_scroll.setWidgetResizable(True)
        self.rules_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.rules_scroll.setHorizontalScrollBarPolicy(_qt_enum(QtCore.Qt, "ScrollBarAlwaysOff"))
        self.rules_scroll.setFixedHeight(82)
        rules_host = QtWidgets.QWidget()
        rules_host.setMinimumWidth(0)
        rules_host.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        grid = QtWidgets.QGridLayout()
        rules_host.setLayout(grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(5)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.rule_buttons = {}
        for index, spec in enumerate(registry.specs):
            button = QtWidgets.QPushButton(spec.title)
            button.setObjectName("RuleToggle")
            button.setMinimumWidth(0)
            button.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
            button.setCheckable(True)
            button.setChecked(spec.default_enabled)
            category = {"integrity": "完整性", "performance": "性能", "references": "引用", "pipeline": "流程"}.get(spec.category, spec.category)
            confidence = {"deterministic": "确定性", "strong": "高置信", "heuristic": "启发式"}.get(spec.confidence, spec.confidence)
            cost = {"cheap": "轻量扫描", "moderate": "常规扫描", "expensive": "深度扫描"}.get(spec.cost, spec.cost)
            button.setToolTip("%s · %s · %s" % (category, confidence, cost))
            button.toggled.connect(self._sync_run_state)
            grid.addWidget(button, index // 2, index % 2)
            self.rule_buttons[spec.id] = button
        self.rules_scroll.setWidget(rules_host)
        layout.addWidget(self.rules_scroll)
        footer = QtWidgets.QHBoxLayout()
        self.telemetry = QtWidgets.QLabel("等待场景快照")
        self.telemetry.setObjectName("ClinicTelemetry")
        footer.addWidget(self.telemetry, 1)
        self.run_button = QtWidgets.QPushButton("扫描快照")
        self.run_button.setObjectName("ClinicRun")
        self.run_button.clicked.connect(self.runRequested)
        footer.addWidget(self.run_button)
        layout.addLayout(footer)
        self.setMinimumHeight(268)

    def set_scene_settings(
        self, settings, dependencies=(), lifecycle=None, unknown_plugins=(),
        references=(), nodes=(),
    ):
        fps = "%.3f" % settings.frames_per_second if settings.frames_per_second else "—"
        fps = fps.rstrip("0").rstrip(".")
        color = (
            "已启用" if settings.color_management_enabled is True
            else "已停用" if settings.color_management_enabled is False
            else "不可读取"
        )
        values = (
            "帧率 · %s / %s" % (settings.time_unit or "—", fps),
            "尺度 · %s / %s" % (settings.linear_unit or "—", settings.angular_unit or "—"),
            "上轴 · %s" % ((settings.up_axis or "—").upper()),
            "色彩 · %s" % ("开" if color == "已启用" else "关" if color == "已停用" else "—"),
        )
        for chip, value in zip(self.setting_chips, values):
            chip.setText(value)
        dependencies = tuple(dependencies)
        missing = sum(item.exists is False for item in dependencies)
        risky = sum(
            item.path_kind == "network"
            or (item.path_kind == "absolute" and item.inside_workspace is False)
            for item in dependencies
        )
        sequence_dependencies = sum(bool(item.sequence_pattern) for item in dependencies)
        gap_sequences = sum(
            item.sequence_scan_complete and bool(item.sequence_missing_count)
            for item in dependencies
        )
        missing_members = sum(
            int(item.sequence_missing_count or 0) for item in dependencies
            if item.sequence_scan_complete
        )
        self.dependency_chip.setText(
            "依赖谱系 · %s / 序列 %s · 缺文件 %s · 缺帧 %s"
            % (len(dependencies), sequence_dependencies, missing, missing_members)
        )
        self.dependency_chip.setProperty("danger", bool(missing))
        self.dependency_chip.setProperty("alert", bool(gap_sequences or risky) and not missing)
        self._dependency_focus_rule = (
            "missing-external-files" if missing
            else "external-sequence-gaps" if gap_sequences
            else "nonportable-external-files"
        )
        self.dependency_chip.setToolTip(
            "外部依赖：%s · 序列/缓存：%s\n缺失文件：%s · 不完整序列：%s · 缺失成员：%s\n"
            "不可移植路径：%s\n点击定位当前最高风险依赖规则"
            % (
                len(dependencies), sequence_dependencies, missing,
                gap_sequences, missing_members, risky,
            )
        )
        self.dependency_chip.style().unpolish(self.dependency_chip)
        self.dependency_chip.style().polish(self.dependency_chip)
        unknown_plugins = tuple(unknown_plugins)
        unknown_types = sum(len(item.node_types) for item in unknown_plugins)
        self.plugin_chip.setText(
            "插件幽灵 · %s / 类型 %s" % (len(unknown_plugins), unknown_types)
        )
        self.plugin_chip.setProperty("alert", bool(unknown_plugins))
        self.plugin_chip.setToolTip(
            "场景记录的缺失插件：%s\n点击定位缺失插件诊断规则"
            % (", ".join(item.name for item in unknown_plugins) if unknown_plugins else "无")
        )
        self.plugin_chip.style().unpolish(self.plugin_chip)
        self.plugin_chip.style().polish(self.plugin_chip)
        references = tuple(references)
        nodes = tuple(nodes)
        source_files = {
            (item.canonical_path or item.resolved_path).replace("\\", "/").casefold()
            for item in references
        }
        missing_references = tuple(item for item in references if item.exists is False)
        unloaded_references = tuple(item for item in references if not item.loaded)
        copy_instances = sum(item.copy_number > 0 for item in references)
        reference_namespaces = {
            item.namespace.strip(":") for item in references if item.namespace.strip(":")
        }
        intruders = []
        for node in nodes:
            if node.referenced or not node.namespace:
                continue
            parts = node.namespace.split(":")
            if any(
                ":".join(parts[:depth]) in reference_namespaces
                for depth in range(len(parts), 0, -1)
            ):
                intruders.append(node)
        intruders = tuple(intruders)
        self.reference_chip.setText(
            "引用轨道 · %s 实例 / %s 源 · 缺 %s · 越界 %s"
            % (len(references), len(source_files), len(missing_references), len(intruders))
        )
        self.reference_chip.setProperty("danger", bool(missing_references))
        self.reference_chip.setProperty(
            "alert", bool(intruders or unloaded_references) and not missing_references
        )
        self._reference_focus_rule = (
            "missing-reference-files" if missing_references
            else "reference-namespace-intrusion" if intruders
            else "unloaded-references" if unloaded_references
            else "nested-reference-depth"
        )
        self.reference_chip.setToolTip(
            "引用实例：%s · 规范化源文件：%s · 复制实例：%s\n"
            "缺失：%s · 未加载：%s · namespace 越界：%s\n点击定位当前最高风险引用规则"
            % (
                len(references), len(source_files), copy_instances,
                len(missing_references), len(unloaded_references), len(intruders),
            )
        )
        self.reference_chip.style().unpolish(self.reference_chip)
        self.reference_chip.style().polish(self.reference_chip)
        dirty = bool(lifecycle and lifecycle.modified is True)
        self.contract_title.setText("制片信号 · 未保存" if dirty else "制片信号")
        self.contract_band.setProperty("dirty", dirty)
        self.contract_band.style().unpolish(self.contract_band)
        self.contract_band.style().polish(self.contract_band)
        self.contract_band.setToolTip(
            "渲染空间：%s\n视图变换：%s\nOCIO 配置：%s\n外部依赖：%s 项 · 序列 %s 项 · 缺失文件 %s 项 · 缺失帧 %s · 可移植风险 %s 项\n缺失插件：%s 项 · 注册节点类型 %s 项\n引用：%s 实例 / %s 源 · 缺失 %s · namespace 越界 %s\n内存状态：%s"
            % (
                settings.rendering_space or "不可读取",
                settings.view_transform or "不可读取",
                settings.color_config_path or "Maya 内置 / 不可读取",
                len(dependencies),
                sequence_dependencies,
                missing,
                missing_members,
                risky,
                len(unknown_plugins),
                unknown_types,
                len(references),
                len(source_files),
                len(missing_references),
                len(intruders),
                "有未保存修改" if dirty else "与磁盘一致 / 不可读取",
            )
        )

    def _focus_dependency_health(self):
        button = self.rule_buttons.get(self._dependency_focus_rule)
        if button is None:
            return
        button.setChecked(True)
        button.setFocus()
        self.rules_scroll.ensureWidgetVisible(button)
        self.telemetry.setText("已定位依赖谱系规则  ·  点击“扫描快照”刷新证据")
        self.ruleFocusRequested.emit(self._dependency_focus_rule)

    def _focus_missing_plugins(self):
        button = self.rule_buttons.get("missing-plugin-requirements")
        if button is None:
            return
        button.setChecked(True)
        button.setFocus()
        self.rules_scroll.ensureWidgetVisible(button)
        self.telemetry.setText("已定位缺失插件规则  ·  点击“扫描快照”刷新证据")
        self.ruleFocusRequested.emit("missing-plugin-requirements")

    def _focus_reference_health(self):
        button = self.rule_buttons.get(self._reference_focus_rule)
        if button is None:
            return
        button.setChecked(True)
        button.setFocus()
        self.rules_scroll.ensureWidgetVisible(button)
        self.telemetry.setText("已定位引用健康规则  ·  点击“扫描快照”刷新证据")
        self.ruleFocusRequested.emit(self._reference_focus_rule)

    def enabled_rule_ids(self):
        return tuple(rule_id for rule_id, button in self.rule_buttons.items() if button.isChecked())

    def _sync_run_state(self, *_args):
        self.run_button.setEnabled(bool(self.enabled_rule_ids()))

    def current_profile(self) -> RuleProfile:
        return self.profile_combo.currentData()

    def _apply_profile(self, index: int):
        profile = self.profile_combo.itemData(index)
        if not profile:
            return
        enabled = set(profile.rule_ids)
        for rule_id, button in self.rule_buttons.items():
            button.blockSignals(True)
            button.setChecked(rule_id in enabled)
            button.blockSignals(False)
        self.telemetry.setText("%s已就绪  ·  点击扫描" % profile.title)
        self.profile_combo.setToolTip(profile.description)
        self._sync_run_state()

    def set_compact(self, compact: bool):
        for button in self.rule_buttons.values():
            button.setVisible(not compact)
        self.rules_scroll.setVisible(not compact)
        self.config_badge.setVisible(not compact)
        self.contract_band.setVisible(not compact)
        self.telemetry.setVisible(not compact)
        self.setMinimumHeight(132 if compact else 248)
        self.setMaximumHeight(132 if compact else 290)

    def set_config_error(self, message: str):
        self.config_badge.setText("配置已回退")
        self.config_badge.setProperty("error", True)
        self.config_badge.setToolTip(message)
        self.config_badge.style().unpolish(self.config_badge)
        self.config_badge.style().polish(self.config_badge)

    def set_report(self, report: ClinicReport, incident_count: int = 0):
        self.spectrum.set_report(report)
        if report.failures:
            text = "%s 条规则异常  ·  %s 项发现" % (len(report.failures), len(report.issues))
        else:
            text = "%s 条规则  ·  %s 个事件簇  ·  %s 项发现  ·  %.2f ms" % (len(report.runs), incident_count, len(report.issues), report.duration_ms)
        self.telemetry.setText(text)

    def set_motion_enabled(self, enabled: bool):
        self.spectrum.set_motion_enabled(enabled)


class IncidentCard(QtWidgets.QFrame):
    activated = QtCore.Signal(object)

    def __init__(self, incident: Incident, ordinal: int, parent=None):
        super().__init__(parent)
        self.incident = incident
        self.setObjectName("IncidentCard")
        self.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.setFocusPolicy(_qt_enum(QtCore.Qt, "StrongFocus"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        index = QtWidgets.QLabel(
            "事件簇 %02d  /  %s 项发现  /  %s 个节点"
            % (ordinal, len(incident.issue_ids), len(incident.affected_node_ids))
        )
        index.setObjectName("IncidentIndex")
        layout.addWidget(index)
        title = QtWidgets.QLabel(incident.title)
        title.setObjectName("IncidentTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        reason = QtWidgets.QLabel("  ·  ".join(item.value for item in incident.evidence[:2]))
        reason.setObjectName("IncidentReason")
        reason.setWordWrap(True)
        layout.addWidget(reason)

    def mousePressEvent(self, event):
        self.activated.emit(self.incident)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (_qt_enum(QtCore.Qt, "Key_Return"), _qt_enum(QtCore.Qt, "Key_Space")):
            self.activated.emit(self.incident)
            event.accept()
            return
        super().keyPressEvent(event)


class IssueCard(QtWidgets.QFrame):
    activated = QtCore.Signal(object)

    def __init__(self, issue: Issue, spec: Optional[RuleSpec] = None, parent=None):
        super().__init__(parent)
        self.issue = issue
        self.setObjectName("IssueCard")
        self.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.setFocusPolicy(_qt_enum(QtCore.Qt, "StrongFocus"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(13, 11, 13, 11)
        layout.setSpacing(5)
        title = QtWidgets.QLabel(issue.title)
        title.setObjectName("IssueTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        severity_name = {"INFO": "提示", "WARNING": "警告", "ERROR": "错误", "CRITICAL": "严重"}.get(issue.severity.name, issue.severity.name)
        severity = QtWidgets.QLabel("%s  /  %s 个信号" % (severity_name, len(issue.affected_node_ids)))
        severity.setObjectName("Severity%s" % issue.severity.name.title())
        layout.addWidget(severity)
        if spec:
            category = {"integrity": "完整性", "performance": "性能", "references": "引用", "pipeline": "流程"}.get(spec.category, spec.category)
            confidence = {"deterministic": "确定性", "strong": "高置信", "heuristic": "启发式"}.get(spec.confidence, spec.confidence)
            cost = {"cheap": "轻量", "moderate": "常规", "expensive": "深度"}.get(spec.cost, spec.cost)
            repair = {"diagnostic": "仅诊断", "previewed": "可预览修复"}.get(spec.repair_kind, spec.repair_kind)
            contract = QtWidgets.QLabel("%s  ·  %s  ·  %s扫描  ·  %s" % (category, confidence, cost, repair))
            contract.setObjectName("IssueContract")
            contract.setWordWrap(True)
            layout.addWidget(contract)

    def mousePressEvent(self, event):
        self.activated.emit(self.issue)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (_qt_enum(QtCore.Qt, "Key_Return"), _qt_enum(QtCore.Qt, "Key_Space")):
            self.activated.emit(self.issue)
            event.accept()
            return
        super().keyPressEvent(event)


class CandidateCard(QtWidgets.QFrame):
    activated = QtCore.Signal(object)

    def __init__(self, candidate: RootCauseCandidate, node: SceneNode, rank: int, measured: Optional[MeasuredCandidate] = None, parent=None):
        super().__init__(parent)
        self.candidate = candidate
        self.setObjectName("CandidateCard")
        self.setMinimumWidth(205)
        self.setMaximumWidth(255)
        self.setCursor(QtGui.QCursor(_qt_enum(QtCore.Qt, "PointingHandCursor")))
        self.setFocusPolicy(_qt_enum(QtCore.Qt, "StrongFocus"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(13, 9, 13, 9)
        layout.setSpacing(3)
        if measured is None:
            signal_text = "%02d  结构信号  %.1f" % (rank, candidate.structural_score)
        else:
            signal_text = "%02d  实测  %.2f ms  ·  %s 个事件" % (rank, measured.observed_inclusive_us / 1000.0, measured.observed_event_count)
        signal = QtWidgets.QLabel(signal_text)
        signal.setObjectName("CandidateSignal")
        layout.addWidget(signal)
        name = QtWidgets.QLabel(node.name)
        name.setObjectName("CandidateName")
        name.setToolTip(node.name)
        layout.addWidget(name)
        detail = QtWidgets.QLabel("%s  ·  距离 %s 跳" % (node.type_name, candidate.distance))
        detail.setObjectName("CandidateDetail")
        layout.addWidget(detail)
        self.setToolTip("\n".join(candidate.reasons))

    def mousePressEvent(self, event):
        self.activated.emit(self.candidate)
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (_qt_enum(QtCore.Qt, "Key_Return"), _qt_enum(QtCore.Qt, "Key_Space")):
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
        marker_layout.addWidget(self.summary)
        outer.addWidget(marker)
        scroll = QtWidgets.QScrollArea()
        scroll.setObjectName("LensScroll")
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(0)
        scroll.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Expanding)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(_qt_enum(QtCore.Qt, "ScrollBarAsNeeded"))
        scroll.setVerticalScrollBarPolicy(_qt_enum(QtCore.Qt, "ScrollBarAlwaysOff"))
        self.host = QtWidgets.QWidget()
        self.cards = QtWidgets.QHBoxLayout(self.host)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(8)
        self.cards.addStretch(1)
        scroll.setWidget(self.host)
        outer.addWidget(scroll, 1)

    def minimumSizeHint(self):
        return QtCore.QSize(300, 112)

    def sizeHint(self):
        return QtCore.QSize(900, 112)

    def set_report(self, report: RootCauseReport, snapshot: SceneSnapshot, measured_report: Optional[MeasuredRootCauseReport] = None):
        while self.cards.count() > 1:
            item = self.cards.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        measured_by_id = {
            item.structural.node_id: item for item in measured_report.candidates
        } if measured_report else {}
        for rank, candidate in enumerate(report.candidates, 1):
            card = CandidateCard(candidate, snapshot.node_map[candidate.node_id], rank, measured_by_id.get(candidate.node_id))
            card.activated.connect(self.candidateActivated)
            self.cards.insertWidget(self.cards.count() - 1, card)
        suffix = " · 已截断：%s" % report.truncation_reason if report.truncated else ""
        telemetry = "%s 节点 / %s 边 · %.2f ms" % (
            report.scanned_node_count,
            report.scanned_edge_count,
            report.query_elapsed_ms,
        )
        if measured_report:
            self.summary.setText("实测覆盖 %.0f%% · %s%s" % (measured_report.measurement_coverage * 100.0, telemetry, suffix))
        else:
            self.summary.setText("结构推断 · %s%s" % (telemetry, suffix))
        self.summary.setToolTip(
            "查询内核在 %.3f ms 内扫描了 %s 个节点与 %s 条边%s。"
            % (
                report.query_elapsed_ms,
                report.scanned_node_count,
                report.scanned_edge_count,
                "；停止原因：%s" % report.truncation_reason if report.truncated else "",
            )
        )
        self.setVisible(True)


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


class RuntimeConstellationCanvas(QtWidgets.QWidget):
    """Four orbital lanes for volatile execution surfaces."""

    def __init__(self, parent=None):
        super().__init__(parent)
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


class ProjectGateCanvas(QtWidgets.QWidget):
    """A clickable release train: every carriage is one verified Maya scene."""

    sceneActivated = QtCore.Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.setFixedHeight(58)
        self.setMouseTracking(True)
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

    def set_queue(self, journal):
        scenes = []
        for job in journal.get("jobs") or ():
            scenes.append({
                "receipt": {
                    "source_scene": job.get("source_scene", ""),
                    "ok": job.get("status") not in {"失败"},
                    "gate_failed": job.get("status") == "阻断",
                    "issue_count": 0,
                    "atomic_finding_count": 0,
                    "report_sha256": job.get("report_sha256", ""),
                    "queue_status": job.get("status", "待运行"),
                    "attempts": int(job.get("attempts", 0)),
                    "error": job.get("error", ""),
                }
            })
        self.set_scenes(scenes)

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
            receipt = self._scenes[index]["receipt"]
            queue_status = receipt.get("queue_status")
            if queue_status:
                self.setToolTip(
                    "%s\n状态：%s · 尝试 %s 次%s"
                    % (
                        Path(receipt["source_scene"]).name, queue_status,
                        receipt.get("attempts", 0),
                        "\n%s" % receipt.get("error") if receipt.get("error") else "",
                    )
                )
            else:
                self.setToolTip(
                    "%s\n问题 %s · 原子发现 %s · 签名 %s"
                    % (
                        Path(receipt["source_scene"]).name,
                        receipt["issue_count"],
                        receipt["atomic_finding_count"],
                        receipt["report_sha256"][:12].upper(),
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
            painter.drawText(bounds, _qt_enum(QtCore.Qt, "AlignCenter"), "尚未载入项目审计")
            return
        cell_width = bounds.width() / float(len(scenes))
        rail_y = bounds.center().y()
        painter.setPen(QtGui.QPen(QtGui.QColor("#332B43"), 2.0))
        painter.drawLine(QtCore.QLineF(bounds.left(), rail_y, bounds.right(), rail_y))
        for index, item in enumerate(scenes):
            receipt = item["receipt"]
            queue_status = receipt.get("queue_status")
            failed = not receipt["ok"] or receipt["gate_failed"]
            left = bounds.left() + index * cell_width + 2
            rect = QtCore.QRectF(left, bounds.top(), max(12.0, cell_width - 4), bounds.height())
            queue_colors = {
                "待运行": COLORS["violet"], "运行中": COLORS["cyan"],
                "通过": COLORS["acid"], "阻断": COLORS["orange"],
                "失败": QtGui.QColor("#FF3D81"),
            }
            color = queue_colors.get(queue_status, COLORS["orange"] if failed else COLORS["acid"])
            surface = QtGui.QLinearGradient(rect.topLeft(), rect.bottomRight())
            queue_surfaces = {
                "待运行": QtGui.QColor("#241638"), "运行中": QtGui.QColor("#0A3342"),
                "通过": QtGui.QColor("#2A3C12"), "阻断": QtGui.QColor("#4A1710"),
                "失败": QtGui.QColor("#451126"),
            }
            surface.setColorAt(0, queue_surfaces.get(queue_status, QtGui.QColor("#4A1710") if failed else QtGui.QColor("#2A3C12")))
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
            name = Path(receipt["source_scene"]).stem
            if len(name) > 12:
                name = name[:10] + "…"
            painter.drawText(rect.adjusted(5, 3, -4, -13), _qt_enum(QtCore.Qt, "AlignCenter"), name)
            painter.setPen(color)
            font.setPointSize(6)
            painter.setFont(font)
            state = queue_status or ("阻断 %s" % receipt["atomic_finding_count"] if failed else "可发布")
            painter.drawText(rect.adjusted(4, 18, -4, -3), _qt_enum(QtCore.Qt, "AlignCenter"), state)
        scan_x = bounds.left() + bounds.width() * self._phase
        beam = QtGui.QLinearGradient(scan_x - 42, 0, scan_x + 12, 0)
        beam.setColorAt(0, QtGui.QColor(72, 215, 255, 0))
        beam.setColorAt(0.78, QtGui.QColor(72, 215, 255, 72))
        beam.setColorAt(1, QtGui.QColor(72, 215, 255, 0))
        painter.fillRect(QtCore.QRectF(scan_x - 42, bounds.top(), 54, bounds.height()), beam)


class ProjectGateStrip(QtWidgets.QFrame):
    dismissRequested = QtCore.Signal()
    sceneActivated = QtCore.Signal(int)
    queueActionRequested = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ProjectGate")
        self.setFixedHeight(82)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 12, 8)
        layout.setSpacing(14)
        heading = QtWidgets.QVBoxLayout()
        mark = QtWidgets.QLabel("◆  项目发布列车")
        mark.setObjectName("ProjectGateMark")
        heading.addWidget(mark)
        self.identity = QtWidgets.QLabel("等待签名项目包")
        self.identity.setObjectName("ProjectGateMeta")
        heading.addWidget(self.identity)
        self.guard = QtWidgets.QLabel("等待所有权与容量预检")
        self.guard.setObjectName("ProjectGateGuard")
        heading.addWidget(self.guard)
        layout.addLayout(heading)
        self.canvas = ProjectGateCanvas()
        self.canvas.sceneActivated.connect(self.sceneActivated)
        layout.addWidget(self.canvas, 1)
        result = QtWidgets.QVBoxLayout()
        self.verdict = QtWidgets.QLabel("尚无项目证据")
        self.verdict.setObjectName("ProjectGateVerdict")
        self.detail = QtWidgets.QLabel("")
        self.detail.setObjectName("ProjectGateMeta")
        result.addWidget(self.verdict)
        result.addWidget(self.detail)
        layout.addLayout(result)
        self.queue_action = QtWidgets.QPushButton("安全暂停")
        self.queue_action.setObjectName("ProjectQueueAction")
        self.queue_action.setToolTip("当前场景完成后暂停，不强制终止 Maya")
        self.queue_action.clicked.connect(self.queueActionRequested)
        self.queue_action.setVisible(False)
        layout.addWidget(self.queue_action)
        close = QtWidgets.QPushButton("×")
        close.setObjectName("LensClose")
        close.setToolTip("关闭项目门禁总览")
        close.clicked.connect(self.dismissRequested)
        layout.addWidget(close)

    def set_report(self, payload):
        self.queue_action.setVisible(False)
        self.guard.setText("✓ 双层签名已验证")
        self.guard.setProperty("alert", False)
        self.guard.style().unpolish(self.guard)
        self.guard.style().polish(self.guard)
        self.canvas.set_scenes(payload.get("scenes") or ())
        summary = payload["summary"]
        failed = bool(payload.get("gate_failed"))
        self.verdict.setText("发布已阻断" if failed else "全项目可以发布")
        self.verdict.setProperty("failed", failed)
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        self.detail.setText(
            "%s 个场景 · 通过 %s · 阻断 %s · 原子发现 %s"
            % (
                summary["scene_count"], summary["passed_scene_count"],
                summary["blocked_scene_count"], summary["atomic_finding_count"],
            )
        )
        self.identity.setText("项目签名 %s" % payload["project_sha256"][:12].upper())
        self.setVisible(True)

    def set_queue(self, journal):
        self.canvas.set_queue(journal)
        state = journal.get("state", "待运行")
        summary = journal.get("summary") or {}
        self.verdict.setText(
            {"运行中": "项目审计运行中", "已暂停": "项目审计已暂停",
             "需要重试": "部分场景需要重试", "完成": "项目审计已完成",
             "预检失败": "磁盘容量预检未通过"}.get(state, "项目审计待运行")
        )
        failed = bool(summary.get("failed"))
        if state == "预检失败":
            failed = True
        self.verdict.setProperty("failed", failed)
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        self.detail.setText(
            "共 %s · 通过 %s · 阻断 %s · 失败 %s · 待运行 %s"
            % (
                summary.get("scene_count", len(journal.get("jobs") or ())),
                summary.get("passed", 0), summary.get("blocked", 0),
                summary.get("failed", 0), summary.get("pending", 0),
            )
        )
        self.identity.setText(
            "断点签名 %s · 恢复 %s 次"
            % (str(journal.get("journal_sha256", ""))[:10].upper(), journal.get("recovery_count", 0))
        )
        storage = tuple(journal.get("storage_preflight") or ())
        ready = bool(storage) and all(item.get("ready") for item in storage)
        if ready:
            margin = min(
                int(item.get("free_bytes", 0)) - int(item.get("required_bytes", 0))
                for item in storage
            )
            worker = next(
                (job.get("worker") for job in journal.get("jobs") or () if job.get("worker")),
                None,
            )
            process = (
                " · Maya PID %s · 崩溃联动%s"
                % (worker.get("pid"), "开启" if worker.get("job_kill_on_close") else "降级")
                if worker else ""
            )
            self.guard.setText("✓ 容量余量 %.1f GiB%s" % (margin / 1073741824.0, process))
        elif storage:
            self.guard.setText("! 磁盘容量预检未通过")
        else:
            self.guard.setText("等待所有权与容量预检")
        self.guard.setProperty("alert", bool(storage) and not ready)
        self.guard.style().unpolish(self.guard)
        self.guard.style().polish(self.guard)
        self.queue_action.setVisible(True)
        if state == "运行中":
            self.queue_action.setText("安全暂停")
            self.queue_action.setEnabled(True)
            self.queue_action.setToolTip("当前场景完成后暂停，不强制终止 Maya")
        elif state in {"已暂停", "需要重试", "待运行", "预检失败"}:
            self.queue_action.setText("继续队列")
            self.queue_action.setEnabled(True)
            self.queue_action.setToolTip("从带签名断点继续，已完成场景不会重复审计")
        else:
            self.queue_action.setText("打开项目结果")
            self.queue_action.setEnabled(bool(journal.get("project_report")))
            self.queue_action.setToolTip("打开最终双重签名项目审计包")
        self.setVisible(True)

    def set_motion_enabled(self, enabled):
        self.canvas.set_motion_enabled(enabled)

    def select_scene(self, index):
        self.canvas.select_scene(index)

    def clear(self):
        self.canvas.set_scenes(())
        self.verdict.setText("尚无项目证据")
        self.detail.clear()
        self.identity.setText("等待签名项目包")
        self.guard.setText("等待所有权与容量预检")
        self.queue_action.setVisible(False)

    def set_fault(self, title, detail):
        self.canvas.set_scenes(())
        self.verdict.setText(title)
        self.verdict.setProperty("failed", True)
        self.verdict.style().unpolish(self.verdict)
        self.verdict.style().polish(self.verdict)
        self.detail.setText(detail[:120])
        self.identity.setText("队列未取得执行所有权")
        self.guard.setText("! 已保护现有任务，不会并发启动 Maya")
        self.guard.setProperty("alert", True)
        self.guard.style().unpolish(self.guard)
        self.guard.style().polish(self.guard)
        self.queue_action.setVisible(False)
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
                QtCore.QRectF(x - slot * 0.45, bounds.bottom() - 10, slot * 0.9, 12),
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
        self.mode = QtWidgets.QLabel("隔离 / 串行 / 仅操作副本")
        self.mode.setObjectName("BisectMeta")
        mark_box.addWidget(self.mark)
        mark_box.addWidget(self.mode)
        layout.addLayout(mark_box)
        self.canvas = BisectTraceCanvas()
        layout.addWidget(self.canvas, 1)
        signal_box = QtWidgets.QVBoxLayout()
        signal_box.setSpacing(1)
        self.signal = QtWidgets.QLabel("已准备二分")
        self.signal.setObjectName("BisectSignal")
        self.detail = QtWidgets.QLabel("尚未执行探针")
        self.detail.setObjectName("BisectMeta")
        signal_box.addWidget(self.signal)
        signal_box.addWidget(self.detail)
        layout.addLayout(signal_box)
        controls = QtWidgets.QVBoxLayout()
        self.cancel = QtWidgets.QPushButton("本次探针后停止")
        self.cancel.setObjectName("BisectCancel")
        self.cancel.clicked.connect(self.cancelRequested)
        self.dismiss = QtWidgets.QPushButton("关闭")
        self.dismiss.setObjectName("BisectDismiss")
        self.dismiss.clicked.connect(self.dismissRequested)
        self.dismiss.setVisible(False)
        self.resume = QtWidgets.QPushButton("继续二分")
        self.resume.setObjectName("BisectResume")
        self.resume.clicked.connect(self.resumeRequested)
        self.resume.setVisible(False)
        controls.addWidget(self.cancel)
        controls.addWidget(self.resume)
        controls.addWidget(self.dismiss)
        layout.addLayout(controls)

    def begin(self, plan):
        self.canvas.reset(len(plan.candidates))
        mode = plan.metadata.get("isolation_mode", "post-open-copy")
        mode_name = {"post-open-copy": "打开后隔离", "pre-open-ascii": "打开前切片"}.get(str(mode), str(mode))
        self.mode.setText("%s  /  串行  /  仅操作副本" % mode_name)
        self.signal.setText("%s 个候选已装载" % len(plan.candidates))
        self.signal.setProperty("outcome", "active")
        self.detail.setText("源文件已锁定 · SHA %s" % plan.source_sha256[:10])
        self.cancel.setEnabled(True)
        self.cancel.setText("本次探针后停止")
        self.cancel.setVisible(True)
        self.dismiss.setVisible(False)
        self.resume.setVisible(False)
        self.setVisible(True)

    def add_attempt(self, step, attempt):
        self.canvas.add_attempt(step, attempt)
        self.signal.setText(
            "%s  ·  %s / %s"
            % ({"pass": "通过", "fail": "复现", "unresolved": "未决"}.get(attempt.outcome, attempt.outcome), len(step.candidate_ids), self.canvas._candidate_count)
        )
        self.signal.setProperty("outcome", attempt.outcome)
        self.signal.style().unpolish(self.signal)
        self.signal.style().polish(self.signal)
        timeout = " · 超时" if attempt.timed_out else ""
        self.detail.setText(
            "探针 %02d · %s · %.1f 秒%s"
            % (
                attempt.attempt_index + 1,
                {"confirm-source-failure": "确认源故障", "subset": "子集", "complement": "补集", "journal-replay": "日志重放"}.get(attempt.stage, attempt.stage),
                attempt.duration_seconds,
                timeout,
            )
        )

    def request_cancel(self):
        self.cancel.setEnabled(False)
        self.cancel.setText("已排队停止")
        self.detail.setText("当前后台探针将安全完成后停止")

    def finish(self, result, labels):
        self.canvas.finish()
        minimal = result.delta_debug.minimal_candidate_ids
        complete = result.delta_debug.complete
        self.signal.setText(
            "%s  ·  %s"
            % ("已隔离" if complete else "部分收敛", " + ".join(labels) or "无最小原因集")
        )
        self.signal.setProperty("outcome", "fail" if complete else "unresolved")
        self.signal.style().unpolish(self.signal)
        self.signal.style().polish(self.signal)
        self.detail.setText(
            "%s 次探针 · 复现胶囊 %s · SHA %s"
            % (
                len(result.manifest.attempts),
                result.manifest_path.name,
                result.manifest_sha256[:10],
            )
        )
        self.cancel.setVisible(False)
        self.resume.setVisible(not complete)
        self.dismiss.setVisible(True)

    def fail(self, message: str):
        self.canvas.finish()
        self.signal.setText("二分已停止")
        self.signal.setProperty("outcome", "unresolved")
        self.signal.style().unpolish(self.signal)
        self.signal.style().polish(self.signal)
        self.detail.setText(message[:110])
        self.cancel.setVisible(False)
        self.resume.setVisible(True)
        self.dismiss.setVisible(True)

    def set_motion_enabled(self, enabled: bool):
        self.canvas.set_motion_enabled(enabled)


class _BisectWorker(QtCore.QObject):
    probeCompleted = QtCore.Signal(object, object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(self, plan, cancel_event, root=None, journal_path=None):
        super().__init__()
        self.plan = plan
        self.cancel_event = cancel_event
        self.root = root
        self.journal_path = journal_path

    @QtCore.Slot()
    def run(self):
        try:
            session = (
                BisectSession.resume(self.journal_path)
                if self.journal_path
                else BisectSession(self.plan, root=self.root)
            )
            result = session.run(
                cancelled=self.cancel_event.is_set,
                progress=self.probeCompleted.emit,
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(result)


class _ClinicWorker(QtCore.QObject):
    progress = QtCore.Signal(int, int, str)
    finished = QtCore.Signal(object, object, object)
    cancelled = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, registry, snapshot, enabled_rule_ids, include_expensive, cancel_event):
        super().__init__()
        self.registry = registry
        self.snapshot = snapshot
        self.enabled_rule_ids = tuple(enabled_rule_ids)
        self.include_expensive = bool(include_expensive)
        self.cancel_event = cancel_event

    @QtCore.Slot()
    def run(self):
        try:
            if self.cancel_event.is_set():
                raise ClinicCancelled("场景诊所在图索引前被取消")
            # Prewarm the shared immutable CSR index off the UI thread, so the
            # first Lens interaction never pays the large-scene build cost.
            get_graph_index(
                self.snapshot,
                cancelled=self.cancel_event.is_set,
            )
            atlas_index = get_graph_index(
                self.snapshot,
                ("dg", "dag"),
                cancelled=self.cancel_event.is_set,
            )
            atlas_index.ranked_node_ids(cancelled=self.cancel_event.is_set)
            host_identity_index = build_host_identity_index(
                self.snapshot, cancelled=self.cancel_event.is_set
            )
            report = self.registry.evaluate(
                self.snapshot,
                enabled_rule_ids=self.enabled_rule_ids,
                include_expensive=self.include_expensive,
                cancelled=self.cancel_event.is_set,
                progress=self.progress.emit,
            )
            if self.cancel_event.is_set():
                raise ClinicCancelled("场景诊所在当前规则完成后被取消")
            incidents = cluster_issues(self.snapshot, report.issues)
        except (ClinicCancelled, QueryCancelled):
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.finished.emit(report, incidents, host_identity_index)


class _ProjectQueueWorker(QtCore.QObject):
    progress = QtCore.Signal(object)
    finished = QtCore.Signal(object)
    failed = QtCore.Signal(str)

    def __init__(
        self, plan_path, journal_path, report_dir, project_report, cancel_event
    ):
        super().__init__()
        self.plan_path = Path(plan_path)
        self.journal_path = Path(journal_path)
        self.report_dir = Path(report_dir)
        self.project_report = Path(project_report)
        self.cancel_event = cancel_event

    @QtCore.Slot()
    def run(self):
        try:
            from ..project_queue import run_project_plan

            journal = run_project_plan(
                self.plan_path,
                self.journal_path,
                self.report_dir,
                self.project_report,
                should_cancel=self.cancel_event.is_set,
                progress=self.progress.emit,
            )
        except Exception as exc:
            self.failed.emit("%s: %s" % (type(exc).__name__, exc))
            return
        self.finished.emit(journal)


class MayaScopeWorkspace(QtWidgets.QMainWindow):
    hostSelectionChanged = QtCore.Signal(object)

    def __init__(self, parent=None, clinic_environment: Optional[ClinicEnvironment] = None):
        super().__init__(parent)
        _ensure_ui_fonts()
        self.setObjectName(WINDOW_OBJECT_NAME)
        self.setWindowTitle("MayaScope · 光谱因果场景图谱")
        self.resize(1480, 900)
        self._snapshot: Optional[SceneSnapshot] = None
        self._issues: Tuple[Issue, ...] = ()
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
        self._clinic_report: Optional[ClinicReport] = None
        self._incidents: Tuple[Incident, ...] = ()
        self._selected_issue: Optional[Issue] = None
        self._selected_incident: Optional[Incident] = None
        self._focus_node_id: Optional[str] = None
        self._lens_report: Optional[RootCauseReport] = None
        self._measured_report: Optional[MeasuredRootCauseReport] = None
        self._selected_candidate: Optional[RootCauseCandidate] = None
        self._profiler_capture: Optional[ProfilerCapture] = None
        self._counterfactual_run: Optional[CounterfactualRun] = None
        self._counterfactual_record = None
        self._pulse_range = (0, 0)
        self._delta: Optional[SceneDelta] = None
        self._delta_before: Optional[SceneSnapshot] = None
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
        self._runtime_snapshot = None
        self._runtime_report = None
        self._runtime_session = None
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
        self._capture_session = None
        self._capture_previous_snapshot = None
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

        self.lens_bar = QtWidgets.QFrame()
        self.lens_bar.setObjectName("LensBar")
        lens_layout = QtWidgets.QHBoxLayout(self.lens_bar)
        lens_layout.setContentsMargins(18, 8, 14, 8)
        lens_layout.setSpacing(9)
        lens_mark = QtWidgets.QLabel("◉  根因透镜")
        lens_mark.setObjectName("LensMark")
        lens_layout.addWidget(lens_mark)
        self.lens_focus = QtWidgets.QLabel("尚未聚焦")
        self.lens_focus.setObjectName("LensFocus")
        self.lens_focus.setMinimumWidth(220)
        lens_layout.addWidget(self.lens_focus)
        lens_layout.addStretch(1)
        self.direction_label = QtWidgets.QLabel("追踪方向")
        self.direction_label.setObjectName("LensControlLabel")
        lens_layout.addWidget(self.direction_label)
        self.upstream_button = QtWidgets.QPushButton("上游")
        self.upstream_button.setObjectName("LensToggle")
        self.upstream_button.setCheckable(True)
        self.upstream_button.setChecked(True)
        self.upstream_button.clicked.connect(lambda: self._set_lens_direction("upstream"))
        lens_layout.addWidget(self.upstream_button)
        self.downstream_button = QtWidgets.QPushButton("影响域")
        self.downstream_button.setObjectName("LensToggle")
        self.downstream_button.setCheckable(True)
        self.downstream_button.clicked.connect(lambda: self._set_lens_direction("downstream"))
        lens_layout.addWidget(self.downstream_button)
        self.depth_label = QtWidgets.QLabel("深度")
        self.depth_label.setObjectName("LensControlLabel")
        lens_layout.addWidget(self.depth_label)
        self.lens_depth = QtWidgets.QSpinBox()
        self.lens_depth.setRange(1, 8)
        self.lens_depth.setValue(4)
        self.lens_depth.setObjectName("LensDepth")
        self.lens_depth.valueChanged.connect(self._run_lens)
        lens_layout.addWidget(self.lens_depth)
        self.maya_select_button = QtWidgets.QPushButton("在 Maya 中选择")
        self.maya_select_button.setObjectName("LensSecondary")
        self.maya_select_button.clicked.connect(self._select_focus_in_maya)
        lens_layout.addWidget(self.maya_select_button)
        rerun = QtWidgets.QPushButton("重新追踪")
        rerun.setObjectName("LensPrimary")
        rerun.clicked.connect(self._run_lens)
        lens_layout.addWidget(rerun)
        close_lens = QtWidgets.QPushButton("×")
        close_lens.setObjectName("LensClose")
        close_lens.setToolTip("关闭根因透镜")
        close_lens.clicked.connect(self._close_lens)
        lens_layout.addWidget(close_lens)
        self.lens_bar.setVisible(False)
        outer.addWidget(self.lens_bar)

        splitter = QtWidgets.QSplitter(_qt_enum(QtCore.Qt, "Horizontal"))
        splitter.setHandleWidth(1)
        self.atlas = SpectralAtlasView()
        self.atlas.nodeActivated.connect(self._node_selected)
        splitter.addWidget(self.atlas)

        self.issue_rail = QtWidgets.QFrame()
        self.issue_rail.setObjectName("IssueRail")
        self.issue_rail.setMinimumWidth(320)
        self.issue_rail.setMaximumWidth(430)
        rail_layout = QtWidgets.QVBoxLayout(self.issue_rail)
        rail_layout.setContentsMargins(18, 18, 18, 18)
        eyebrow = QtWidgets.QLabel("问题证据")
        eyebrow.setObjectName("Eyebrow")
        rail_layout.addWidget(eyebrow)
        self.issue_heading = QtWidgets.QLabel("等待场景信号")
        self.issue_heading.setObjectName("RailHeading")
        self.issue_heading.setWordWrap(True)
        rail_layout.addWidget(self.issue_heading)
        self.clinic_array = ClinicRuleArray(
            self._clinic_registry,
            self._clinic_profiles,
            self._clinic_environment.source,
            self._clinic_environment.fingerprint,
        )
        if self._clinic_config_error:
            self.clinic_array.set_config_error(self._clinic_config_error)
        self.clinic_array.runRequested.connect(self._run_clinic)
        self.clinic_array.ruleFocusRequested.connect(self._focus_rule_signal)
        rail_layout.addWidget(self.clinic_array)
        self.issue_scroll = QtWidgets.QScrollArea()
        self.issue_scroll.setWidgetResizable(True)
        self.issue_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.issue_scroll.setHorizontalScrollBarPolicy(_qt_enum(QtCore.Qt, "ScrollBarAlwaysOff"))
        self.issue_host = QtWidgets.QWidget()
        self.issue_host.setMinimumWidth(0)
        self.issue_host.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.issue_list = QtWidgets.QVBoxLayout(self.issue_host)
        self.issue_list.setContentsMargins(0, 8, 0, 8)
        self.issue_list.setSpacing(9)
        self.issue_list.addStretch(1)
        self.issue_scroll.setWidget(self.issue_host)
        rail_layout.addWidget(self.issue_scroll, 1)
        self.evidence = QtWidgets.QLabel("捕获场景后将在这里呈现因果证据。")
        self.evidence.setObjectName("Evidence")
        self.evidence.setWordWrap(True)
        rail_layout.addWidget(self.evidence)
        self.plan_button = QtWidgets.QPushButton("预览变更计划")
        self.plan_button.setObjectName("PlanButton")
        self.plan_button.setEnabled(False)
        self.plan_button.clicked.connect(self._preview_plan)
        rail_layout.addWidget(self.plan_button)
        self.rollback_button = QtWidgets.QPushButton("↶  回滚上次变更计划")
        self.rollback_button.setObjectName("RollbackButton")
        self.rollback_button.setVisible(False)
        self.rollback_button.clicked.connect(self._rollback_last_plan)
        rail_layout.addWidget(self.rollback_button)
        splitter.addWidget(self.issue_rail)
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
        self.maya_select_button.setVisible(not compact)
        self.direction_label.setVisible(not compact)
        self.depth_label.setVisible(not compact)
        self.lens_focus.setVisible(not compact)
        self.search.setMaximumWidth(175 if compact else 310)
        self.issue_rail.setMinimumWidth(270 if compact else 320)
        self.issue_rail.setMaximumWidth(330 if compact else 430)
        self.clinic_array.set_compact(compact)
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
        identities = (
            build_host_identity_index(snapshot)
            if identity_index is None
            else identity_index
        )
        result = []
        seen = set()
        for name in names:
            node_id = identities.get(str(name))
            if node_id is None:
                continue
            if node_id not in seen:
                seen.add(node_id)
                result.append(node_id)
        return tuple(result)

    def _apply_host_selection(self) -> None:
        if not self._snapshot or not self.selection_sync_button.isChecked():
            return
        names = self._pending_host_selection
        node_ids = self._node_ids_for_host_selection(
            self._snapshot, names, self._host_identity_index
        )
        if not names:
            self._close_lens()
            self.atlas.select_node_ids(())
            self.status.setText("  MAYA 联动  ·  宿主选择已清空")
            self._flash_selection_sync()
            return
        if not node_ids:
            self.status.setText(
                "  MAYA 联动  ·  当前选择不在快照中  ·  捕获场景可刷新身份映射"
            )
            return
        if len(node_ids) == 1:
            self.atlas.select_node_ids(
                node_ids, center=self.motion_button.isChecked()
            )
            self._activate_focus(node_ids[0])
        else:
            self._close_lens()
            self.atlas.select_node_ids(
                node_ids, center=self.motion_button.isChecked()
            )
            self.atlas.highlight(node_ids)
        self.status.setText(
            "  MAYA 联动  ·  Maya → 图谱  ·  %s 个节点" % len(node_ids)
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
        if self._runtime_session is not None:
            self._runtime_session.cancel()
            self.runtime_button.setEnabled(False)
            self.runtime_button.setText("正在取消…")
            self.status.setText("  正在取消运行时采集  ·  将在下一个安全分片停止")
            return
        if not self._snapshot:
            self.status.setText("  运行时采集等待中  ·  请先捕获场景")
            return
        if self._capture_session is not None or (
            self._clinic_thread and self._clinic_thread.isRunning()
        ) or (self._bisect_thread and self._bisect_thread.isRunning()):
            self.status.setText("  运行时采集等待中  ·  另一项调查正在执行")
            return
        try:
            self._runtime_session = MayaRuntimeCaptureSession(self._snapshot)
        except Exception as exc:
            self.status.setText("  运行时采集失败  ·  %s" % exc)
            return
        self.runtime_button.setText("取消运行时采集")
        self.capture_button.setEnabled(False)
        self.bisect_button.setEnabled(False)
        self.clinic_array.setEnabled(False)
        self.pulse.setEnabled(False)
        self.status.setText("  运行时采集中  ·  正在映射执行表面")
        self._runtime_timer.start()

    def _restore_runtime_controls(self):
        self._runtime_timer.stop()
        self._runtime_session = None
        self.runtime_button.setText("运行时")
        self.runtime_button.setEnabled(self._snapshot is not None)
        self.capture_button.setEnabled(True)
        self.bisect_button.setEnabled(True)
        self.clinic_array.setEnabled(True)
        self.pulse.setEnabled(True)

    def _advance_runtime_capture(self):
        session = self._runtime_session
        if session is None:
            self._runtime_timer.stop()
            return
        try:
            progress = session.step(max_items=96, max_milliseconds=7.0)
        except RuntimeCaptureCancelled:
            self._restore_runtime_controls()
            self.status.setText("  运行时采集已取消  ·  已保留上次清单")
            return
        except RuntimeChangedDuringCapture as exc:
            self._restore_runtime_controls()
            self.status.setText("  运行时证据已失效  ·  %s" % exc)
            return
        except Exception as exc:
            self._restore_runtime_controls()
            self.status.setText("  运行时采集失败  ·  %s" % exc)
            return
        if not session.done:
            self.status.setText(
                "  运行时采集中  ·  %s  %s/%s"
                % (
                    {"expressions": "表达式", "plugins": "插件", "callbacks": "回调", "verify": "验证", "finalize": "封存"}.get(progress.stage, progress.stage),
                    progress.completed,
                    progress.total,
                )
            )
            return
        runtime = session.result
        report = analyze_runtime(runtime, self._snapshot)
        self._runtime_snapshot = runtime
        self._runtime_report = report
        self._restore_runtime_controls()
        self.runtime_constellation.set_report(runtime, report)
        self._focus_runtime()

    def _focus_runtime(self):
        if not self._runtime_snapshot or not self._runtime_report:
            return
        if (
            not self._snapshot
            or self._runtime_snapshot.source_snapshot_id != self._snapshot.snapshot_id
        ):
            self._runtime_snapshot = None
            self._runtime_report = None
            self.runtime_constellation.setVisible(False)
            self.status.setText(
                "  运行时证据已过期  ·  请为当前快照重新采集"
            )
            return
        report = self._runtime_report
        if report.affected_node_ids:
            self.atlas.highlight(report.affected_node_ids)
        findings = "\n".join(
            "• %s [%s]\n  %s"
            % (
                issue.title,
                {"INFO": "提示", "WARNING": "警告", "ERROR": "错误", "CRITICAL": "严重"}.get(issue.severity.name, issue.severity.name),
                " · ".join("%s: %s" % (item.label, item.value) for item in issue.evidence),
            )
            for issue in report.issues
        ) or "未触发任何运行时风险规则。"
        self.evidence.setText(
            "运行时执行表面\n%s\n\n可观测性边界\n%s"
            % (findings, "\n".join("• %s" % item for item in report.limitations))
        )
        self.plan_button.setEnabled(False)
        self.plan_button.setText("仅清点 · 不自动终止")
        self.status.setText(
            "  运行时星图  ·  %s 个信号  ·  %s 个回调节点"
            % (
                len(report.issues),
                len(self._runtime_snapshot.node_callbacks),
            )
        )

    def _dismiss_runtime(self):
        self.runtime_constellation.setVisible(False)
        self.runtime_constellation.clear()
        self._runtime_snapshot = None
        self._runtime_report = None
        if not self._lens_report and not self._delta and not self._regression_payload:
            self.atlas.clear_lens()

    def _set_delta(self, delta: SceneDelta, before: SceneSnapshot):
        self._delta = delta
        self._delta_before = before
        self.delta_strip.set_delta(delta)

    def _auto_capture(self):
        if self._snapshot is None and self._capture_session is None:
            self.capture()

    def capture(self, after=None):
        if self._clinic_thread and self._clinic_thread.isRunning():
            if self._clinic_job and self._clinic_job[0] == "capture" and not self._capture_required:
                self._cancel_clinic_analysis()
            return
        if self._capture_session is not None:
            if after is None:
                self._capture_session.cancel()
                self.capture_button.setEnabled(False)
                self.capture_button.setText("正在取消…")
                self.status.setText("  正在取消场景捕获  ·  将在下一个安全分片停止")
            return
        try:
            session = MayaSceneCaptureSession(previous_snapshot=self._snapshot)
        except Exception as exc:
            self.status.setText("  场景探针失败  ·  %s" % exc)
            QtWidgets.QMessageBox.critical(self, "MayaScope 场景捕获失败", str(exc))
            return
        self._capture_previous_snapshot = self._snapshot
        self._capture_after = after
        self._capture_required = after is not None
        self._capture_session = session
        self.bisect_button.setEnabled(False)
        self.runtime_button.setEnabled(False)
        self.clinic_array.setEnabled(False)
        self.pulse.setEnabled(False)
        self.capture_button.setEnabled(not self._capture_required)
        self.capture_button.setText(
            "正在验证…" if self._capture_required else "取消捕获"
        )
        self.status.setText("  场景捕获中  ·  正在获取稳定节点身份")
        log_event("capture.started", context={"has_previous": self._snapshot is not None})
        self._capture_timer.start()

    def _advance_capture(self):
        session = self._capture_session
        if session is None:
            self._capture_timer.stop()
            return
        try:
            progress = session.step(max_items=192, max_milliseconds=7.0)
        except CaptureCancelled:
            self._capture_timer.stop()
            self._capture_session = None
            self._capture_previous_snapshot = None
            self._capture_after = None
            self._capture_required = False
            self.capture_button.setEnabled(True)
            self.capture_button.setText("捕获场景")
            self.bisect_button.setEnabled(True)
            self.runtime_button.setEnabled(self._snapshot is not None)
            self.clinic_array.setEnabled(True)
            self.pulse.setEnabled(True)
            self.status.setText("  场景捕获已取消  ·  已保留上次快照")
            log_event("capture.cancelled")
            return
        except SceneChangedDuringCapture as exc:
            self._capture_failed(exc, "捕获结果已失效")
            return
        except Exception as exc:
            self._capture_failed(exc, "场景捕获失败")
            return

        if not session.done:
            count = (
                "%s/%s" % (progress.completed, progress.total)
                if progress.total else
                "已发现 %s 项" % progress.completed
            )
            self.status.setText(
                "  场景捕获中  ·  %s  ·  %s" % (progress.message, count)
            )
            return

        self._capture_timer.stop()
        snapshot = session.result
        previous_snapshot = self._capture_previous_snapshot
        aliased_indexes = (
            alias_graph_indexes(previous_snapshot, snapshot)
            if previous_snapshot is not None and session.reuse.topology_unchanged
            else 0
        )
        callback = self._capture_after
        required = self._capture_required
        self._capture_session = None
        self._capture_previous_snapshot = None
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
                    "reused_nodes": session.reuse.reused_nodes,
                    "reused_edges": session.reuse.reused_edges,
                    "reused_references": session.reuse.reused_references,
                    "topology_unchanged": session.reuse.topology_unchanged,
                    "aliased_indexes": aliased_indexes,
                },
            )

    def _capture_failed(self, exc, label: str):
        self._capture_timer.stop()
        self._capture_session = None
        self._capture_previous_snapshot = None
        self._capture_after = None
        self._capture_required = False
        self.capture_button.setEnabled(True)
        self.capture_button.setText("捕获场景")
        self.bisect_button.setEnabled(True)
        self.runtime_button.setEnabled(self._snapshot is not None)
        self.clinic_array.setEnabled(True)
        self.pulse.setEnabled(True)
        self.status.setText("  %s  ·  %s" % (label, exc))
        log_event("capture.failed", str(exc), level=40, context={"label": label})
        QtWidgets.QMessageBox.critical(self, "MayaScope 场景捕获已停止", str(exc))

    def _apply_captured_snapshot(
        self, snapshot, previous_snapshot, clinic_report, incidents, host_identity_index
    ):
        issues = clinic_report.issues
        self._close_lens()
        self._runtime_snapshot = None
        self._runtime_report = None
        self.runtime_constellation.clear()
        self.runtime_constellation.setVisible(False)
        self._regression_payload = None
        self.regression_rift.clear()
        self.regression_rift.setVisible(False)
        self._delta = None
        self._delta_before = None
        self.delta_strip.setVisible(False)
        self._counterfactual_run = None
        self._counterfactual_record = None
        self.counterfactual_strip.clear()
        self.counterfactual_strip.setVisible(False)
        self._profiler_capture = None
        self._measured_report = None
        self._pulse_range = (0, 0)
        self._snapshot, self._issues = snapshot, issues
        self._host_identity_index = host_identity_index
        self.runtime_button.setEnabled(True)
        self._clinic_report = clinic_report
        self._incidents = incidents
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
        priority_ids = self._node_ids_for_host_selection(
            snapshot,
            snapshot.metadata.get("selection", ()),
            self._host_identity_index,
        )
        self.atlas.set_snapshot(snapshot, issues, priority_node_ids=priority_ids)
        self.pulse.set_summary(snapshot.summary())
        self.pulse.set_capture(None)
        self._populate_issues()
        omitted = max(0, len(snapshot.nodes) - MAX_RENDER_NODES)
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
        if previous_snapshot is not None:
            self._set_delta(compare_snapshots(previous_snapshot, snapshot), previous_snapshot)
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
        while self.issue_list.count() > 1:
            item = self.issue_list.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        failures = self._clinic_report.failures if self._clinic_report else ()
        if self._clinic_report and not self._clinic_report.runs:
            self.issue_heading.setText("没有启用场景诊所规则")
        elif failures:
            self.issue_heading.setText("%s 项发现 · %s 条规则异常" % (len(self._issues), len(failures)))
        else:
            self.issue_heading.setText(
                "%s 个事件簇 · %s 项发现"
                % (len(self._incidents), len(self._issues))
                if self._issues else "场景信号正常"
            )
        specs = {spec.id: spec for spec in self._clinic_registry.specs}
        issues_by_id = {issue.id: issue for issue in self._issues}
        for ordinal, incident in enumerate(self._incidents, 1):
            incident_card = IncidentCard(incident, ordinal)
            incident_card.activated.connect(self._select_incident)
            self.issue_list.insertWidget(self.issue_list.count() - 1, incident_card)
            for issue_id in incident.issue_ids:
                issue = issues_by_id[issue_id]
                card = IssueCard(issue, specs.get(issue.rule_id))
                card.activated.connect(self._select_issue)
                self.issue_list.insertWidget(self.issue_list.count() - 1, card)
        self._selected_issue = None
        self._selected_incident = None
        self.plan_button.setEnabled(False)
        if self._clinic_report and not self._clinic_report.runs:
            self.evidence.setText("请至少启用一条诊所规则，然后扫描已冻结的场景快照。")
        elif failures:
            self.evidence.setText(
                "规则异常已隔离\n\n%s\n\n其余规则已完成；异常规则不会被误判为干净结果。"
                % "\n".join("%s  ·  %s" % (item.rule_id, item.message) for item in failures)
            )
        else:
            self.evidence.setText("选择一个异常，查看证据与受影响拓扑。")

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
        worker = _ClinicWorker(
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
                self._clinic_report = report
                self._issues = report.issues
                self._incidents = incidents
                self._host_identity_index = host_identity_index
                self.clinic_array.set_report(report, len(incidents))
                self.atlas.set_snapshot(
                    self._snapshot,
                    self._issues,
                    priority_node_ids=self._node_ids_for_host_selection(
                        self._snapshot,
                        self._snapshot.metadata.get("selection", ()),
                        self._host_identity_index,
                    ),
                )
                self._close_lens()
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
        self.clinic_array.profile_combo.setEnabled(True)
        for button in self.clinic_array.rule_buttons.values():
            button.setEnabled(True)
        self.clinic_array._sync_run_state()
        self.clinic_array.run_button.setText("扫描快照")
        self.capture_button.setEnabled(True)
        self.capture_button.setText("捕获场景")
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
        self._close_lens()
        self._selected_issue = issue
        self._selected_incident = None
        self.atlas.highlight(issue.affected_node_ids)
        evidence = "\n".join("%s  ·  %s" % (item.label, item.value) for item in issue.evidence)
        self.evidence.setText("%s\n\n%s\n\n%s" % (issue.description, evidence, issue.id))
        plan = plan_for_issue(issue, self._snapshot) if self._snapshot else None
        self.plan_button.setEnabled(plan is not None)
        self.plan_button.setText("预览变更计划" if plan else "仅提供诊断")

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
        self.issue_heading.setText(issue.title)
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
        self._close_lens()
        self._selected_issue = None
        self._selected_incident = incident
        self.atlas.highlight(incident.affected_node_ids)
        issue_map = {issue.id: issue for issue in self._issues}
        findings = "\n".join(
            "• %s  [%s]" % (issue_map[issue_id].title, issue_map[issue_id].severity.name)
            for issue_id in incident.issue_ids
        )
        evidence = "\n".join("%s  ·  %s" % (item.label, item.value) for item in incident.evidence)
        self.issue_heading.setText(incident.title)
        incident_issues = tuple(issue_map[issue_id] for issue_id in incident.issue_ids)
        plan = plan_for_issues(incident_issues, self._snapshot)
        repair_note = (
            "%s 项可修复发现可合并到一个经验证的 Maya Undo 块中。"
            % len(plan.issue_ids)
            if plan else
            "该事件簇仅提供诊断，不建议自动修改场景。"
        )
        self.evidence.setText(
            "事件簇范围\n%s\n\n关联证据\n%s\n\n诊断发现\n%s\n\n批处理意图\n%s"
            % (incident.id, evidence, findings, repair_note)
        )
        self.plan_button.setEnabled(plan is not None)
        self.plan_button.setText(
            "预览批量变更计划"
            if plan and len(plan.issue_ids) > 1 else
            "预览事件簇变更计划"
            if plan else
            "仅诊断事件簇"
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
        self.issue_heading.setText("变更计划验证通过" if verified else "变更计划需要复核")
        self.evidence.setText(
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
        self.issue_heading.setText("变更计划已回滚")
        self.evidence.setText(
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
        self._selected_issue = None
        self._selected_incident = None
        self._focus_node_id = node_id
        node = self._snapshot.node_map[node_id]
        self.pulse.counterfactual_button.setEnabled(not node.referenced)
        self.lens_focus.setText(node.name)
        self.lens_focus.setToolTip(node.dag_paths[0] if node.dag_paths else node.id)
        self.lens_bar.setVisible(True)
        self._run_lens()

    def _set_lens_direction(self, direction: str):
        upstream = direction == "upstream"
        self.upstream_button.setChecked(upstream)
        self.downstream_button.setChecked(not upstream)
        self._run_lens()

    def _run_lens(self, *_args):
        if not self._snapshot or not self._focus_node_id:
            return
        direction = "upstream" if self.upstream_button.isChecked() else "downstream"
        try:
            if self._profiler_capture:
                measured = build_measured_root_cause_report(
                    self._snapshot,
                    self._profiler_capture,
                    self._focus_node_id,
                    issues=self._issues,
                    direction=direction,
                    max_depth=self.lens_depth.value(),
                    start_us=self._pulse_range[0],
                    end_us=self._pulse_range[1],
                )
                report = measured.structural
            else:
                measured = None
                report = build_root_cause_report(
                    self._snapshot,
                    self._focus_node_id,
                    issues=self._issues,
                    direction=direction,
                    max_depth=self.lens_depth.value(),
                )
        except Exception as exc:
            self.status.setText("  根因透镜失败  ·  %s" % exc)
            return
        self._lens_report = report
        self._measured_report = measured
        self._selected_candidate = None
        self.lens_ribbon.set_report(report, self._snapshot, measured)
        self.issue_heading.setText("根因透镜")
        self.plan_button.setEnabled(False)
        self.plan_button.setText("结构证据")
        if report.candidates:
            self._candidate_selected(report.candidates[0])
        else:
            self.atlas.show_lens(report)
            self.evidence.setText(
                "在深度 %s 内未找到%s DG 候选。\n\n"
                "这说明结构范围为空，但不能证明该症状没有运行时原因。"
                % (report.max_depth, "上游" if direction == "upstream" else "下游")
            )
        mode = "实测 + 结构" if measured else "结构推断"
        capture_reuse = self._snapshot.metadata.get("capture_reuse", {})
        reuse_status = (
            "  ·  CSR 已复用"
            if capture_reuse.get("topology_unchanged")
            else ""
        )
        self.status.setText(
            "  根因透镜  ·  %s  ·  %s  ·  %s 节点 / %s 边  ·  %.2f ms  ·  %s 个候选%s%s"
            % (
                mode,
                "上游" if direction == "upstream" else "影响域",
                report.scanned_node_count,
                report.scanned_edge_count,
                report.query_elapsed_ms,
                len(report.candidates),
                "  ·  已截断：%s" % report.truncation_reason if report.truncated else "",
                reuse_status,
            )
        )

    def _candidate_selected(self, candidate: RootCauseCandidate):
        if not self._snapshot or not self._lens_report:
            return
        self._selected_candidate = candidate
        self.atlas.show_lens(self._lens_report, candidate)
        node_map = self._snapshot.node_map
        node = node_map[candidate.node_id]
        path = "  →  ".join(node_map[node_id].name for node_id in candidate.path_node_ids)
        plugs = []
        for link in candidate.path_links:
            source = link.source_plug or node_map[link.source_id].name
            target = link.target_plug or node_map[link.target_id].name
            plugs.append("%s  →  %s" % (source, target))
        factors = "\n".join(
            "%s  ·  %s" % (item.label, item.value)
            for item in candidate.evidence
            if item.value not in {"0", "0.0"}
        )
        reasons = "\n".join("• %s" % reason for reason in candidate.reasons)
        plug_text = "\n".join(plugs) if plugs else "节点身份直接命中"
        self.issue_heading.setText(node.name)
        measured = None
        if self._measured_report:
            measured = next(
                (item for item in self._measured_report.candidates if item.structural.node_id == candidate.node_id),
                None,
            )
        measurement = ""
        if measured and self._measured_report:
            measurement = (
                "选定范围内的实测结果\n"
                "包含耗时 %.3f ms  ·  %s 个事件  ·  占已映射耗时 %.1f%%\n"
                "路径包含耗时 %.3f ms  ·  覆盖率 %.0f%%\n"
                "范围 %.3f–%.3f ms\n"
                "包含事件可能互相重叠；这是观测证据，不代表预计优化收益。\n\n"
                % (
                    measured.observed_inclusive_us / 1000.0,
                    measured.observed_event_count,
                    measured.observed_capture_share * 100.0,
                    measured.path_inclusive_us / 1000.0,
                    self._measured_report.measurement_coverage * 100.0,
                    self._measured_report.selection_start_us / 1000.0,
                    self._measured_report.selection_end_us / 1000.0,
                )
            )
        self.evidence.setText(
            "%s结构信号 %.1f / 99\n该分数不是概率\n\n%s\n\n因果路径\n%s\n\nPlug 证据\n%s\n\n评分因素\n%s"
            % (measurement, candidate.structural_score, reasons, path, plug_text, factors)
        )

    def _show_host_health(self):
        health = self._host_health
        issues = "\n".join("· %s" % item for item in health.issues) or "未检测到宿主边界问题。"
        self.issue_heading.setText("宿主信标")
        self.evidence.setText(
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
        self.plan_button.setEnabled(False)
        self.plan_button.setText("只读宿主检查")
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
        if self._capture_session is not None or (
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
        worker = _BisectWorker(
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
        self.issue_heading.setText("故障棱镜")
        self.evidence.setText(
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
        self.plan_button.setEnabled(False)
        self.plan_button.setText("复现胶囊已封存")
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
        self.issue_heading.setText("故障棱镜已停止")
        self.evidence.setText(
            "故障二分已停止\n%s\n\n源场景未被修改；已完成的探针目录仍可供检查。"
            % message
        )
        self.status.setText("  故障二分已停止  ·  %s" % message)

    def _on_bisect_thread_finished(self):
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
        if self._runtime_session is not None:
            self._runtime_timer.stop()
            self._runtime_session.cancel()
            self._runtime_session = None
        if self._capture_session is not None:
            self._capture_timer.stop()
            self._capture_session.cancel()
            self._capture_session = None
            self._capture_previous_snapshot = None
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
        self.atlas.scene().clear()
        self.atlas._node_items.clear()
        self.atlas._edge_items = []
        self._snapshot = None
        self._host_identity_index = {}
        self._delta = None
        self._delta_before = None
        self._runtime_snapshot = None
        self._runtime_report = None
        self._profiler_capture = None
        self._counterfactual_run = None
        self._counterfactual_record = None
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
            self._profiler_capture = result.capture
            self._pulse_range = (0, result.capture.duration_us)
            self.pulse.set_capture(result.capture)
            self._pulse_range_selected(self._pulse_range)
        except Exception as exc:
            self.status.setText("  性能采样失败  ·  %s" % exc)
        finally:
            self.pulse.profile_button.setEnabled(True)
            self.pulse.profile_button.setText("●  采样当前帧")

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
            self._counterfactual_record = self._experiment_store.save(run.report)
        except Exception as exc:
            self._counterfactual_record = None
            self.status.setText(
                "  反事实实验已完成测量  ·  证据归档失败：%s" % exc
            )
        self._present_counterfactual_run(run)

    def _present_counterfactual_run(self, run: CounterfactualRun):
        if not self._snapshot:
            return
        self._counterfactual_run = run
        report = run.report
        self.counterfactual_strip.set_report(report)
        self.atlas.show_counterfactual(report)
        self.issue_heading.setText("反事实性能采样")
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
        self.evidence.setText(
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
        self.plan_button.setEnabled(False)
        self.plan_button.setText("实验状态已恢复")
        self.status.setText(
            "  反事实实验：%s  ·  %+.1f%%  ·  状态与 Undo 已恢复"
            % ({"improved": "改善", "regressed": "变慢", "neutral": "无显著变化", "inconclusive": "证据不足"}.get(report.verdict, report.verdict), report.benefit_percent)
        )

    def _dismiss_counterfactual(self):
        self.counterfactual_strip.setVisible(False)
        self.counterfactual_strip.clear()
        self._counterfactual_run = None
        self._counterfactual_record = None
        if self._lens_report:
            self.atlas.show_lens(self._lens_report, self._selected_candidate)
        elif self._profiler_capture:
            self.atlas.show_pulse(node_stats(self._profiler_capture, *self._pulse_range))
        else:
            self.atlas.clear_lens()

    def _pulse_range_selected(self, selected_range):
        if not self._profiler_capture:
            return
        start_us, end_us = selected_range
        self._pulse_range = (int(start_us), int(end_us))
        stats = node_stats(self._profiler_capture, *self._pulse_range)
        if self._focus_node_id:
            self._run_lens()
        else:
            self.atlas.show_pulse(stats)
            self.issue_heading.setText("性能采样脉冲")
            top = []
            node_map = self._snapshot.node_map if self._snapshot else {}
            for rank, stat in enumerate(stats[:8], 1):
                node = node_map.get(stat.node_id)
                top.append(
                    "%02d  %s  ·  %.3f ms  ·  %s 个事件"
                    % (rank, node.name if node else stat.node_id, stat.inclusive_duration_us / 1000.0, stat.event_count)
                )
            self.evidence.setText(
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
        self.issue_heading.setText("场景差异")
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
        self.evidence.setText(
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
        self.plan_button.setEnabled(False)
        self.plan_button.setText("只读对比")
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
        self.evidence.setText(
            "项目发布证据  /  场景 %s/%s\n%s\n\n状态：%s\n"
            "问题：%s · 原子发现：%s\n严重：%s · 错误：%s · 警告：%s · 信息：%s\n\n"
            "场景签名：%s\n项目签名：%s\n规则配置：%s"
            % (
                index + 1, len(payload["scenes"]), receipt["source_scene"], state,
                receipt["issue_count"], receipt["atomic_finding_count"],
                severity.get("critical", 0), severity.get("error", 0),
                severity.get("warning", 0), severity.get("info", 0),
                receipt["report_sha256"].upper(), payload["project_sha256"].upper(),
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
            or self._capture_session is not None
            or self._runtime_session is not None
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
        worker = _ProjectQueueWorker(
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
        self.evidence.setText(
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
        self.evidence.setText(
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
        self._focus_node_id = None
        self._lens_report = None
        self._measured_report = None
        self._selected_candidate = None
        self.lens_bar.setVisible(False)
        self.lens_ribbon.setVisible(False)
        self.pulse.counterfactual_button.setEnabled(False)
        if self._counterfactual_run and self.counterfactual_strip.isVisible():
            self.atlas.show_counterfactual(self._counterfactual_run.report)
        elif self._profiler_capture:
            self.atlas.show_pulse(node_stats(self._profiler_capture, *self._pulse_range))
        else:
            self.atlas.clear_lens()
        self.issue_heading.setText(
            "%s 个事件簇 · %s 项发现"
            % (len(self._incidents), len(self._issues))
            if self._issues else "场景信号正常"
        )
        self.evidence.setText("选择一个异常或节点，开始调查。")
        self.plan_button.setEnabled(False)
        self.plan_button.setText("预览变更计划")

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
