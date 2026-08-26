"""Explainable structural Root Cause Lens.

This analyzer never claims a measured performance root cause.  It produces a
ranked, auditable set of structural suspects and the exact DG paths that make
each suspect relevant to the selected symptom node.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Iterable, Mapping, Sequence, Tuple

from .graph import GraphIndex, get_graph_index
from .rules import Evidence, Issue
from ..model import SceneEdge, SceneNode, SceneSnapshot


VALID_DIRECTIONS = frozenset({"upstream", "downstream"})


@dataclass(frozen=True)
class CausalLink:
    source_id: str
    target_id: str
    source_plug: str
    target_plug: str
    parallel_connection_count: int = 1


@dataclass(frozen=True)
class RootCauseCandidate:
    node_id: str
    structural_score: float
    distance: int
    path_node_ids: Tuple[str, ...]
    path_links: Tuple[CausalLink, ...]
    reasons: Tuple[str, ...]
    evidence: Tuple[Evidence, ...]


@dataclass(frozen=True)
class RootCauseReport:
    focus_node_id: str
    direction: str
    max_depth: int
    scope_node_ids: Tuple[str, ...]
    candidates: Tuple[RootCauseCandidate, ...]
    scanned_node_count: int
    truncated: bool = False
    scanned_edge_count: int = 0
    query_elapsed_ms: float = 0.0
    truncation_reason: str = ""

    @property
    def path_node_ids(self) -> Tuple[str, ...]:
        result = []
        seen = set()
        for candidate in self.candidates:
            for node_id in candidate.path_node_ids:
                if node_id not in seen:
                    seen.add(node_id)
                    result.append(node_id)
        return tuple(result)


def _links_for_path(path: Sequence[str], graph: GraphIndex) -> Tuple[CausalLink, ...]:
    links = []
    for source_id, target_id in zip(path, path[1:]):
        edges = graph.edges_between(source_id, target_id) or (SceneEdge(source_id, target_id),)
        for edge in edges:
            links.append(
                CausalLink(
                    source_id=source_id,
                    target_id=target_id,
                    source_plug=edge.source_plug,
                    target_plug=edge.target_plug,
                    parallel_connection_count=len(edges),
                )
            )
    return tuple(links)


def _shortest_path_from_distances(
    graph: GraphIndex,
    focus_node_id: str,
    candidate_node_id: str,
    direction: str,
    distances: Mapping[str, int],
) -> Tuple[str, ...]:
    """Reconstruct a shortest path from one BFS layer map in O(path length)."""
    if direction == "upstream":
        path = [candidate_node_id]
        current = candidate_node_id
        while current != focus_node_id:
            next_nodes = sorted(
                node_id
                for node_id in graph.forward[current]
                if distances.get(node_id) == distances[current] - 1
            )
            if not next_nodes:
                return ()
            current = next_nodes[0]
            path.append(current)
        return tuple(path)

    reverse_path = [candidate_node_id]
    current = candidate_node_id
    while current != focus_node_id:
        previous_nodes = sorted(
            node_id
            for node_id in graph.reverse[current]
            if distances.get(node_id) == distances[current] - 1
        )
        if not previous_nodes:
            return ()
        current = previous_nodes[0]
        reverse_path.append(current)
    return tuple(reversed(reverse_path))


def _type_signal(node: SceneNode) -> Tuple[float, str]:
    type_name = node.type_name.lower()
    if type_name in {"unknown", "unknowndag", "unknowntransform"}:
        return 20.0, "未知节点类型具有较高结构风险"
    if type_name in {"expression", "script", "scriptnode"}:
        return 18.0, "运行时代码可能产生隐藏求值工作"
    if "constraint" in type_name:
        return 10.0, "约束节点参与求值耦合"
    if type_name in {"skincluster", "blendshape", "cluster", "wrap", "tweak"}:
        return 9.0, "变形器可能放大几何体求值成本"
    if type_name in {"multmatrix", "decomposematrix", "composematrix", "wtaddmatrix"}:
        return 5.0, "矩阵工具节点位于变换求值路径上"
    return 0.0, ""


def build_root_cause_report(
    snapshot: SceneSnapshot,
    focus_node_id: str,
    issues: Sequence[Issue] = (),
    direction: str = "upstream",
    max_depth: int = 4,
    candidate_limit: int = 6,
    scope_limit: int = 300,
    scan_limit: int = 5_000,
    edge_scan_limit: int = 40_000,
) -> RootCauseReport:
    """Build a deterministic structural investigation around one symptom node."""
    node_map = snapshot.node_map
    if focus_node_id not in node_map:
        raise KeyError("Unknown focus node id: %s" % focus_node_id)
    if direction not in VALID_DIRECTIONS:
        raise ValueError("direction must be 'upstream' or 'downstream'")
    if max_depth < 1:
        raise ValueError("max_depth must be at least 1")
    if candidate_limit < 1 or scope_limit < 1 or scan_limit < scope_limit:
        raise ValueError("candidate/scope limits must be positive and scan_limit >= scope_limit")
    if edge_scan_limit < 1:
        raise ValueError("edge_scan_limit must be positive")

    graph = get_graph_index(snapshot)
    traversal = graph.neighborhood(
        focus_node_id,
        direction=direction,
        max_depth=max_depth,
        max_nodes=scan_limit,
        max_edges=edge_scan_limit,
    )
    distances = traversal.distances
    scanned_node_count = len(distances)
    ranked_scope = sorted(
        distances,
        key=lambda node_id: (
            distances[node_id],
            -(len(graph.forward[node_id]) + len(graph.reverse[node_id])),
            node_map[node_id].name,
        ),
    )
    scope_node_ids = tuple(ranked_scope[:scope_limit])
    issue_by_node: Dict[str, list] = {}
    for issue in issues:
        for node_id in issue.affected_node_ids:
            issue_by_node.setdefault(node_id, []).append(issue)

    focus = node_map[focus_node_id]
    candidates = []
    for node_id in scope_node_ids:
        if node_id == focus_node_id:
            continue
        node = node_map[node_id]
        distance = distances[node_id]
        path = _shortest_path_from_distances(
            graph, focus_node_id, node_id, direction, distances
        )
        if direction == "upstream":
            branch_degree = len(graph.forward[node_id])
        else:
            branch_degree = len(graph.reverse[node_id])
        if not path:
            continue

        reasons = ["沿 DG %s方向距离 %s 跳" % ("上游" if direction == "upstream" else "下游", distance)]
        factors = []
        proximity = 45.0 / float(distance)
        factors.append(("接近度", proximity))

        branch_signal = min(18.0, math.log2(branch_degree + 1.0) * 4.5)
        if branch_degree > 1:
            reasons.append("触达 %s 条因果分支" % branch_degree)
        factors.append(("分支影响", branch_signal))

        type_signal, type_reason = _type_signal(node)
        if type_reason:
            reasons.append(type_reason)
        factors.append(("节点类型信号", type_signal))

        related_issues = issue_by_node.get(node_id, ())
        issue_signal = min(16.0, len(related_issues) * 8.0)
        if related_issues:
            reasons.append("出现在 %s 项场景健康问题中" % len(related_issues))
        factors.append(("问题证据", issue_signal))

        path_nodes = tuple(node_map[path_node_id] for path_node_id in path)

        def reference_domain(path_node: SceneNode) -> str:
            return path_node.reference_file if path_node.referenced else "<local-scene>"

        cross_reference = any(
            reference_domain(source) != reference_domain(target)
            for source, target in zip(path_nodes, path_nodes[1:])
        )
        boundary_signal = 10.0 if cross_reference else 0.0
        if cross_reference:
            reasons.append("路径跨越引用边界")
        factors.append(("引用边界", boundary_signal))

        score = min(99.0, sum(value for _label, value in factors))
        evidence = tuple(Evidence(label, "%.1f" % value) for label, value in factors) + (
            Evidence("路径长度", str(len(path) - 1)),
            Evidence("节点类型", node.type_name),
        )
        candidates.append(
            RootCauseCandidate(
                node_id=node_id,
                structural_score=round(score, 1),
                distance=distance,
                path_node_ids=tuple(path),
                path_links=_links_for_path(path, graph),
                reasons=tuple(reasons),
                evidence=evidence,
            )
        )

    candidates.sort(
        key=lambda candidate: (
            -candidate.structural_score,
            candidate.distance,
            node_map[candidate.node_id].name,
        )
    )
    return RootCauseReport(
        focus_node_id=focus_node_id,
        direction=direction,
        max_depth=max_depth,
        scope_node_ids=scope_node_ids,
        candidates=tuple(candidates[:candidate_limit]),
        scanned_node_count=scanned_node_count,
        truncated=traversal.truncated or scanned_node_count > len(scope_node_ids),
        scanned_edge_count=traversal.scanned_edges,
        query_elapsed_ms=traversal.elapsed_ms,
        truncation_reason=traversal.reason if traversal.truncated else "scope-limit" if scanned_node_count > len(scope_node_ids) else "",
    )
