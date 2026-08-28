"""Host-independent planning for the bounded Scene Atlas render window."""

from __future__ import annotations

from dataclasses import dataclass
import math
from itertools import chain
from typing import Iterable, Optional, Tuple

from ..analysis.graph import GraphIndex
from ..model import SceneSnapshot


@dataclass(frozen=True)
class AtlasNodePlacement:
    node_id: str
    x: float
    y: float


@dataclass(frozen=True)
class AtlasEdgeKey:
    source_id: str
    target_id: str
    relation: str
    source_plug: str
    target_plug: str
    ordinal: int = 0

    @property
    def endpoint_pair(self) -> Tuple[str, str]:
        return self.source_id, self.target_id


@dataclass(frozen=True)
class AtlasWindowPlan:
    snapshot_id: str
    total_node_count: int
    total_edge_count: int
    placements: Tuple[AtlasNodePlacement, ...]
    edges: Tuple[AtlasEdgeKey, ...]

    @property
    def node_ids(self) -> Tuple[str, ...]:
        return tuple(item.node_id for item in self.placements)

    def position_for(self, node_id: str) -> Optional[Tuple[float, float]]:
        for item in self.placements:
            if item.node_id == node_id:
                return item.x, item.y
        return None


@dataclass(frozen=True)
class AtlasWindowDiff:
    added_node_ids: Tuple[str, ...]
    removed_node_ids: Tuple[str, ...]
    retained_node_ids: Tuple[str, ...]
    moved_node_ids: Tuple[str, ...]
    added_edges: Tuple[AtlasEdgeKey, ...]
    removed_edges: Tuple[AtlasEdgeKey, ...]
    retained_edges: Tuple[AtlasEdgeKey, ...]

    @property
    def unchanged(self) -> bool:
        return not (
            self.added_node_ids
            or self.removed_node_ids
            or self.moved_node_ids
            or self.added_edges
            or self.removed_edges
        )


def _placement(index: int) -> Tuple[float, float]:
    """Return the stable concentric investigative layout used by the Qt view."""
    ring = int(math.sqrt(index / 10.0))
    radius = 65.0 + ring * 190.0
    items_in_ring = max(10, int(2.0 * math.pi * radius / 185.0))
    angle = (index % items_in_ring) / float(items_in_ring) * (2.0 * math.pi) + ring * 0.43
    return math.cos(angle) * radius, math.sin(angle) * radius


def build_atlas_window(
    snapshot: SceneSnapshot,
    graph: GraphIndex,
    ranked_node_ids: Iterable[str],
    priority_node_ids: Iterable[str] = (),
    *,
    limit: int = 240,
    edge_limit: int = 960,
) -> AtlasWindowPlan:
    """Plan a bounded semantic window without importing Qt or Maya.

    Priority identities are admitted first, followed by the stable graph ranking.
    Only edges whose two endpoints are visible are materialized. Parallel plugs are
    preserved with a deterministic ordinal so a Qt item can be reused exactly.
    """
    if limit <= 0:
        raise ValueError("Atlas render limit must be positive")
    if edge_limit <= 0:
        raise ValueError("Atlas edge render limit must be positive")
    if graph.snapshot is not snapshot:
        raise ValueError("Atlas graph does not belong to the requested snapshot")

    requested = []
    seen = set()
    for node_id in chain(priority_node_ids, ranked_node_ids):
        if node_id in graph.id_to_index and node_id not in seen:
            seen.add(node_id)
            requested.append(node_id)
            if len(requested) >= limit:
                break

    placements = tuple(
        AtlasNodePlacement(node_id, *_placement(index))
        for index, node_id in enumerate(requested)
    )
    visible = set(requested)
    edges = []
    edge_budget_reached = False
    for source_id in requested:
        for target_id in graph.forward[source_id]:
            if target_id not in visible:
                continue
            counts = {}
            for edge in graph.edges_between(source_id, target_id):
                identity = (
                    edge.relation,
                    edge.source_plug,
                    edge.target_plug,
                )
                ordinal = counts.get(identity, 0)
                counts[identity] = ordinal + 1
                edges.append(
                    AtlasEdgeKey(
                        edge.source_id,
                        edge.target_id,
                        edge.relation,
                        edge.source_plug,
                        edge.target_plug,
                        ordinal,
                    )
                )
                if len(edges) >= edge_limit:
                    edge_budget_reached = True
                    break
            if edge_budget_reached:
                break
        if edge_budget_reached:
            break
    return AtlasWindowPlan(
        snapshot.snapshot_id,
        len(snapshot.nodes),
        len(snapshot.edges),
        placements,
        tuple(edges),
    )


def diff_atlas_windows(
    previous: Optional[AtlasWindowPlan], current: AtlasWindowPlan
) -> AtlasWindowDiff:
    if previous is None:
        return AtlasWindowDiff(
            current.node_ids,
            (),
            (),
            (),
            current.edges,
            (),
            (),
        )
    previous_nodes = set(previous.node_ids)
    current_nodes = set(current.node_ids)
    previous_positions = {
        item.node_id: (item.x, item.y) for item in previous.placements
    }
    current_positions = {
        item.node_id: (item.x, item.y) for item in current.placements
    }
    retained_nodes = tuple(
        node_id for node_id in current.node_ids if node_id in previous_nodes
    )
    moved_nodes = tuple(
        node_id
        for node_id in retained_nodes
        if previous_positions[node_id] != current_positions[node_id]
    )
    previous_edges = set(previous.edges)
    current_edges = set(current.edges)
    return AtlasWindowDiff(
        tuple(node_id for node_id in current.node_ids if node_id not in previous_nodes),
        tuple(node_id for node_id in previous.node_ids if node_id not in current_nodes),
        retained_nodes,
        moved_nodes,
        tuple(edge for edge in current.edges if edge not in previous_edges),
        tuple(edge for edge in previous.edges if edge not in current_edges),
        tuple(edge for edge in current.edges if edge in previous_edges),
    )


__all__ = [
    "AtlasEdgeKey",
    "AtlasNodePlacement",
    "AtlasWindowDiff",
    "AtlasWindowPlan",
    "build_atlas_window",
    "diff_atlas_windows",
]
