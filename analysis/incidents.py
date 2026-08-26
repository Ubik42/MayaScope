"""Explainable clustering of Scene Clinic issues into investigation incidents."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from .rules import Evidence, Issue, Severity
from ..model import SceneSnapshot


@dataclass(frozen=True)
class Incident:
    id: str
    title: str
    severity: Severity
    issue_ids: Tuple[str, ...]
    affected_node_ids: Tuple[str, ...]
    evidence: Tuple[Evidence, ...]


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


def cluster_issues(snapshot: SceneSnapshot, issues: Sequence[Issue]) -> Tuple[Incident, ...]:
    """Cluster by explicit shared scope and one-hop causal/reference boundaries."""
    if not issues:
        return ()
    union = _UnionFind(len(issues))
    node_to_issues: Dict[str, List[int]] = {}
    for index, issue in enumerate(issues):
        for node_id in issue.affected_node_ids:
            node_to_issues.setdefault(node_id, []).append(index)
    for indexes in node_to_issues.values():
        for other in indexes[1:]:
            union.union(indexes[0], other)

    reference_to_issues: Dict[str, Set[int]] = {}
    namespace_to_issues: Dict[str, Set[int]] = {}
    node_map = snapshot.node_map
    for index, issue in enumerate(issues):
        for node_id in issue.affected_node_ids:
            node = node_map[node_id]
            if node.reference_file:
                reference_to_issues.setdefault(node.reference_file, set()).add(index)
            if node.namespace:
                namespace_to_issues.setdefault(node.namespace, set()).add(index)
    for indexes in tuple(reference_to_issues.values()) + tuple(namespace_to_issues.values()):
        ordered = sorted(indexes)
        for other in ordered[1:]:
            union.union(ordered[0], other)

    # Only direct causal adjacency joins incidents; no transitive graph walk is
    # used, preventing a whole connected Maya scene from collapsing into one.
    for edge in snapshot.edges:
        if edge.relation != "dg":
            continue
        left = node_to_issues.get(edge.source_id, ())
        right = node_to_issues.get(edge.target_id, ())
        for a in left:
            for b in right:
                union.union(a, b)

    groups: Dict[int, List[Issue]] = {}
    for index, issue in enumerate(issues):
        groups.setdefault(union.find(index), []).append(issue)
    incidents = []
    for grouped in groups.values():
        grouped.sort(key=lambda issue: (-int(issue.severity), issue.title, issue.id))
        affected = tuple(sorted({node for issue in grouped for node in issue.affected_node_ids}))
        refs = sorted({node_map[node].reference_file for node in affected if node_map[node].reference_file})
        namespaces = sorted({node_map[node].namespace for node in affected if node_map[node].namespace})
        reasons = []
        if len(grouped) > 1:
            reasons.append(Evidence("聚类", "%s 项关联发现" % len(grouped)))
        if refs:
            reasons.append(Evidence("引用边界", ", ".join(refs[:3])))
        if namespaces:
            reasons.append(Evidence("命名空间范围", ", ".join(namespaces[:4])))
        reasons.append(Evidence("受影响身份", str(len(affected))))
        basis = "|".join(sorted(issue.id for issue in grouped))
        incident_id = "incident:%s" % hashlib.sha1(basis.encode("utf-8")).hexdigest()[:10]
        anchor = grouped[0].title
        title = anchor if len(grouped) == 1 else "%s + %s 个关联信号" % (anchor, len(grouped) - 1)
        incidents.append(
            Incident(
                incident_id,
                title,
                max(issue.severity for issue in grouped),
                tuple(issue.id for issue in grouped),
                affected,
                tuple(reasons),
            )
        )
    return tuple(sorted(incidents, key=lambda item: (-int(item.severity), item.title, item.id)))
