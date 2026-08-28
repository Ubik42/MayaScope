"""Interactive Spectral Scene Atlas view.

The Atlas owns graph materialization, selection and spectral overlays.  It is a
pure PySide view over immutable MayaScope models; Maya callbacks and workspace
orchestration stay outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Dict, Iterable, Optional, Sequence, Tuple

from ..analysis.counterfactual import CounterfactualReport
from ..analysis.delta import SceneDelta
from ..analysis.graph import get_graph_index
from ..analysis.lens import RootCauseCandidate, RootCauseReport
from ..analysis.pulse import PulseNodeStat
from ..analysis.rules import Issue
from ..model import SceneNode, SceneSnapshot
from ..presentation.atlas_window import (
    AtlasEdgeKey,
    AtlasWindowPlan,
    build_atlas_window,
    diff_atlas_windows,
)
from ..qt_compat import QtCore, QtGui, QtWidgets
from .foundation import COLORS, qt_enum


MAX_RENDER_NODES = 240
MAX_RENDER_EDGES = 960
LARGE_SCENE_THRESHOLD = 1000
LARGE_SCENE_RENDER_NODES = 120
LARGE_SCENE_RENDER_EDGES = 480


@dataclass(frozen=True)
class AtlasApplyStats:
    total_nodes: int
    total_edges: int
    visible_nodes: int
    visible_edges: int
    reused_nodes: int
    reused_edges: int
    elapsed_ms: float
    camera_preserved: bool


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
        self._refresh_tooltip()
        self._shadow_effect = None
        self._install_shadow_effect()

    def _install_shadow_effect(self):
        shadow = QtWidgets.QGraphicsDropShadowEffect()
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 4)
        shadow.setColor(QtGui.QColor(132, 55, 255, 115))
        self._shadow_effect = shadow
        self.setGraphicsEffect(shadow)

    def _refresh_tooltip(self):
        self.setToolTip(
            "%s\n%s\n%s"
            % (
                self.node.name,
                self.node.type_name,
                self.node.dag_paths[0] if self.node.dag_paths else self.node.id,
            )
        )

    def set_node(self, node: SceneNode, degree: int):
        if self.node == node and self.degree == degree:
            return
        self.node = node
        self.degree = degree
        self._refresh_tooltip()
        self.update()

    def set_glow_enabled(self, enabled: bool):
        if enabled and self._shadow_effect is None:
            self._install_shadow_effect()
        elif not enabled and self._shadow_effect is not None:
            self.setGraphicsEffect(None)
            self._shadow_effect = None

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

        painter.setPen(qt_enum(QtCore.Qt, "NoPen"))
        painter.setBrush(edge)
        painter.drawEllipse(QtCore.QPointF(rect.right() - 10, rect.top() + 11), 3.0, 3.0)


class AtlasEdgeItem(QtWidgets.QGraphicsPathItem):
    def __init__(self, source: AtlasNodeItem, target: AtlasNodeItem, identity: AtlasEdgeKey):
        super().__init__()
        self.source, self.target = source, target
        self.identity = identity
        self.relation = identity.relation
        self._tracing = False
        self._base_color = QtGui.QColor(
            COLORS["violet"] if self.relation == "dg" else COLORS["cyan"]
        )
        self._base_color.setAlpha(78 if self.relation == "dg" else 48)
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
            pen.setStyle(qt_enum(QtCore.Qt, "DashLine"))
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
        self.setHorizontalScrollBarPolicy(qt_enum(QtCore.Qt, "ScrollBarAlwaysOff"))
        self.setVerticalScrollBarPolicy(qt_enum(QtCore.Qt, "ScrollBarAlwaysOff"))
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.MinimalViewportUpdate)
        self._phase = 0.0
        self._node_items: Dict[str, AtlasNodeItem] = {}
        self._edge_items: Dict[AtlasEdgeKey, AtlasEdgeItem] = {}
        self._snapshot: Optional[SceneSnapshot] = None
        self._graph = None
        self._ranked_node_ids: Tuple[str, ...] = ()
        self._window_plan: Optional[AtlasWindowPlan] = None
        self._last_apply_stats: Optional[AtlasApplyStats] = None
        self._lens_positions: Dict[str, QtCore.QPointF] = {}
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
        for edge in self._edge_items.values():
            edge.animate_trace(self._phase)
        self.viewport().update()

    @property
    def last_apply_stats(self) -> Optional[AtlasApplyStats]:
        return self._last_apply_stats

    def drawForeground(self, painter, rect):
        super().drawForeground(painter, rect)
        stats = self._last_apply_stats
        if stats is None:
            return
        painter.save()
        painter.resetTransform()
        panel = QtCore.QRectF(18.0, 18.0, 286.0, 54.0)
        painter.setPen(QtGui.QPen(QtGui.QColor(82, 226, 255, 105), 1.0))
        painter.setBrush(QtGui.QColor(7, 7, 15, 218))
        painter.drawRoundedRect(panel, 8.0, 8.0)
        painter.setPen(COLORS["cyan"])
        painter.drawText(
            QtCore.QRectF(30.0, 25.0, 155.0, 18.0),
            "语义窗 %s / %s" % (stats.visible_nodes, stats.total_nodes),
        )
        painter.setPen(COLORS["acid"] if stats.camera_preserved else COLORS["orange"])
        painter.drawText(
            QtCore.QRectF(190.0, 25.0, 100.0, 18.0),
            qt_enum(QtCore.Qt, "AlignRight"),
            "视角保持" if stats.camera_preserved else "视角重置",
        )
        painter.setPen(COLORS["muted"])
        painter.drawText(
            QtCore.QRectF(30.0, 46.0, 258.0, 17.0),
            "重用 %s 节点 · %s 连线 · 换窗 %.1f ms"
            % (stats.reused_nodes, stats.reused_edges, stats.elapsed_ms),
        )
        painter.restore()

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
        previous_snapshot = self._snapshot
        reset_view = previous_snapshot is None or (
            previous_snapshot.source_scene != snapshot.source_scene
        )
        if previous_snapshot is not snapshot:
            self._lens_positions.clear()
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
        self._materialize(priority_node_ids + affected, reset_view=reset_view)

    def _materialize(
        self,
        priority_node_ids: Iterable[str] = (),
        *,
        reset_view: bool = False,
    ):
        if not self._snapshot or self._graph is None:
            return
        started = time.perf_counter()
        old_center = self.mapToScene(self.viewport().rect().center())
        old_transform = QtGui.QTransform(self.transform())
        large_scene = len(self._snapshot.nodes) >= LARGE_SCENE_THRESHOLD
        plan = build_atlas_window(
            self._snapshot,
            self._graph,
            self._ranked_node_ids,
            priority_node_ids,
            limit=LARGE_SCENE_RENDER_NODES if large_scene else MAX_RENDER_NODES,
            edge_limit=LARGE_SCENE_RENDER_EDGES if large_scene else MAX_RENDER_EDGES,
        )
        diff = diff_atlas_windows(self._window_plan, plan)

        for edge_key in diff.removed_edges:
            edge_item = self._edge_items.pop(edge_key, None)
            if edge_item is not None:
                self.scene().removeItem(edge_item)
        for node_id in diff.removed_node_ids:
            if node_id in self._node_items:
                item = self._node_items.pop(node_id)
                self.scene().removeItem(item)
                item.deleteLater()

        dense_window = large_scene or len(plan.placements) >= 180
        for placement_index, placement in enumerate(plan.placements):
            node_id = placement.node_id
            node = self._snapshot.nodes[self._graph.id_to_index[node_id]]
            item = self._node_items.get(node_id)
            if item is None:
                item = AtlasNodeItem(node, self._graph.degree(node.id))
                self.scene().addItem(item)
                self._node_items[node.id] = item
            else:
                item.set_node(node, self._graph.degree(node.id))
            item.set_glow_enabled(not dense_window)
            item.setPos(placement.x, placement.y)
            if self._lens_positions and node_id not in self._lens_positions:
                self._lens_positions[node_id] = QtCore.QPointF(placement.x, placement.y)

        for edge_key in diff.added_edges:
            item = AtlasEdgeItem(
                self._node_items[edge_key.source_id],
                self._node_items[edge_key.target_id],
                edge_key,
            )
            self.scene().addItem(item)
            self._edge_items[edge_key] = item
        moved = set(diff.moved_node_ids) | set(diff.added_node_ids)
        if moved:
            for edge in self._edge_items.values():
                if edge.key[0] in moved or edge.key[1] in moved:
                    edge.refresh()
        bounds = self.scene().itemsBoundingRect().adjusted(-130, -130, 130, 130)
        self.scene().setSceneRect(bounds)
        if reset_view:
            self.fitInView(bounds, qt_enum(QtCore.Qt, "KeepAspectRatio"))
        else:
            self.setTransform(old_transform)
            self.centerOn(old_center)
        self._window_plan = plan
        self._last_apply_stats = AtlasApplyStats(
            total_nodes=plan.total_node_count,
            total_edges=plan.total_edge_count,
            visible_nodes=len(plan.placements),
            visible_edges=len(plan.edges),
            reused_nodes=len(diff.retained_node_ids),
            reused_edges=len(diff.retained_edges),
            elapsed_ms=(time.perf_counter() - started) * 1000.0,
            camera_preserved=not reset_view,
        )
        if self._timer.isActive():
            self._timer.setInterval(180 if large_scene else 82 if len(plan.placements) >= 180 else 48)
        self.viewport().update(QtCore.QRect(14, 14, 296, 64))

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
        for edge in self._edge_items.values():
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
        if not self._lens_positions:
            self._lens_positions = {
                node_id: QtCore.QPointF(item.pos())
                for node_id, item in self._node_items.items()
            }
        focus_item = self._node_items.get(report.focus_node_id)
        if focus_item is not None:
            focus_item.setPos(0.0, 0.0)
        lanes = {}
        for root_cause in report.candidates:
            lanes.setdefault(root_cause.distance, []).append(root_cause.node_id)
        direction = -1.0 if report.direction == "upstream" else 1.0
        for distance, node_ids in lanes.items():
            ordered = sorted(node_ids)
            y_offset = (len(ordered) - 1) * 52.5
            for index, node_id in enumerate(ordered):
                item = self._node_items.get(node_id)
                if item is not None:
                    item.setPos(
                        direction * distance * 210.0,
                        index * 105.0 - y_offset,
                    )
        for edge in self._edge_items.values():
            edge.refresh()
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
        for edge in self._edge_items.values():
            edge.set_trace(edge.key in trace_edges, edge.key[0] in scope and edge.key[1] in scope)
        visible_ids = set(report.scope_node_ids)
        visible = [self._node_items[node_id] for node_id in visible_ids if node_id in self._node_items]
        if visible:
            bounds = visible[0].sceneBoundingRect()
            for item in visible[1:]:
                bounds = bounds.united(item.sceneBoundingRect())
            lens_bounds = bounds.adjusted(-130, -130, 130, 130)
            self.scene().setSceneRect(lens_bounds)
            self.resetTransform()
            self.fitInView(lens_bounds, qt_enum(QtCore.Qt, "KeepAspectRatio"))
            self.centerOn(lens_bounds.center())

    def clear_lens(self):
        for node_id, position in self._lens_positions.items():
            item = self._node_items.get(node_id)
            if item is not None:
                item.setPos(position)
        self._lens_positions.clear()
        for edge in self._edge_items.values():
            edge.refresh()
        self.scene().setSceneRect(
            self.scene().itemsBoundingRect().adjusted(-130, -130, 130, 130)
        )
        for item in self._node_items.values():
            item.set_role("normal")
            item.set_hot(False)
            item.set_heat(0.0)
            item.setOpacity(1.0)
        for edge in self._edge_items.values():
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
        for edge in self._edge_items.values():
            edge.set_trace(edge.key in added_edges, edge.key[0] in changed or edge.key[1] in changed)
        visible = [self._node_items[node_id] for node_id in changed if node_id in self._node_items]
        if visible:
            bounds = visible[0].sceneBoundingRect()
            for item in visible[1:]:
                bounds = bounds.united(item.sceneBoundingRect())
            self.fitInView(bounds.adjusted(-130, -130, 130, 130), qt_enum(QtCore.Qt, "KeepAspectRatio"))

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
        for edge in self._edge_items.values():
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
        for edge in self._edge_items.values():
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

    def clear_snapshot(self):
        """Release all graphics and semantic-window state without leaking internals."""
        self.scene().clear()
        self._node_items.clear()
        self._edge_items.clear()
        self._snapshot = None
        self._graph = None
        self._ranked_node_ids = ()
        self._window_plan = None
        self._last_apply_stats = None
        self._lens_positions.clear()
        self.viewport().update()


__all__ = [
    "AtlasApplyStats",
    "AtlasEdgeItem",
    "AtlasNodeItem",
    "MAX_RENDER_EDGES",
    "LARGE_SCENE_RENDER_EDGES",
    "LARGE_SCENE_RENDER_NODES",
    "LARGE_SCENE_THRESHOLD",
    "MAX_RENDER_NODES",
    "SpectralAtlasView",
]
