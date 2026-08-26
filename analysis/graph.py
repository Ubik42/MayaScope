"""Compact deterministic graph queries over immutable SceneSnapshots."""

from __future__ import annotations

from array import array
from collections import OrderedDict, deque
from collections.abc import Mapping, Set as AbstractSet
from dataclasses import dataclass
import sys
import threading
import time
from types import MappingProxyType
from typing import Callable, Dict, Iterable, Iterator, List, Optional, Set, Tuple

from ..model import SceneSnapshot


class QueryCancelled(RuntimeError):
    pass


@dataclass(frozen=True)
class NeighborhoodResult:
    distances: Mapping[str, int]
    scanned_edges: int
    truncated: bool
    reason: str
    elapsed_ms: float
    cache_hit: bool = False

    @property
    def node_ids(self) -> Tuple[str, ...]:
        return tuple(self.distances)


class _NeighborView(AbstractSet):
    __slots__ = ("_index", "_reverse", "_node_index")

    def __init__(self, index: "GraphIndex", reverse: bool, node_index: int):
        self._index = index
        self._reverse = reverse
        self._node_index = node_index

    def _bounds(self):
        offsets = self._index._reverse_offsets if self._reverse else self._index._forward_offsets
        return offsets[self._node_index], offsets[self._node_index + 1]

    def __len__(self):
        start, end = self._bounds()
        return end - start

    def __iter__(self) -> Iterator[str]:
        start, end = self._bounds()
        neighbors = self._index._reverse_neighbors if self._reverse else self._index._forward_neighbors
        ids = self._index.node_ids
        for position in range(start, end):
            yield ids[neighbors[position]]

    def __contains__(self, value):
        index = self._index.id_to_index.get(value)
        if index is None:
            return False
        start, end = self._bounds()
        neighbors = self._index._reverse_neighbors if self._reverse else self._index._forward_neighbors
        # CSR slices are sorted, so membership does not allocate a temporary set.
        low, high = start, end
        while low < high:
            middle = (low + high) // 2
            candidate = neighbors[middle]
            if candidate < index:
                low = middle + 1
            else:
                high = middle
        return low < end and neighbors[low] == index


class _AdjacencyView(Mapping):
    __slots__ = ("_index", "_reverse")

    def __init__(self, index: "GraphIndex", reverse: bool):
        self._index = index
        self._reverse = reverse

    def __len__(self):
        return len(self._index.node_ids)

    def __iter__(self):
        return iter(self._index.node_ids)

    def __getitem__(self, node_id):
        try:
            node_index = self._index.id_to_index[node_id]
        except KeyError:
            raise KeyError(node_id) from None
        return _NeighborView(self._index, self._reverse, node_index)


class GraphIndex:
    """Integer/CSR index with bounded query caches and no copied node identities per edge."""

    def __init__(
        self,
        snapshot: SceneSnapshot,
        relations: Iterable[str] = ("dg",),
        *,
        cache_entries: int = 48,
        cache_node_limit: int = 20_000,
        cancelled: Optional[Callable[[], bool]] = None,
    ):
        if cache_entries < 0 or cache_node_limit < 0:
            raise ValueError("Graph cache budgets must be non-negative")
        self.snapshot = snapshot
        if cancelled and cancelled():
            raise QueryCancelled("Graph index build cancelled")
        self.relations = frozenset(relations)
        self.node_ids = tuple(node.id for node in snapshot.nodes)
        self.id_to_index = {node_id: index for index, node_id in enumerate(self.node_ids)}
        if len(self.node_ids) >= 2**32:
            raise ValueError("GraphIndex supports fewer than 2^32 nodes")
        buckets: Dict[int, List[object]] = {}
        self._self_loop_indexes = set()
        for ordinal, edge in enumerate(snapshot.edges):
            if ordinal % 8192 == 0 and cancelled and cancelled():
                raise QueryCancelled("Graph index build cancelled")
            if edge.relation not in self.relations:
                continue
            source = self.id_to_index[edge.source_id]
            target = self.id_to_index[edge.target_id]
            buckets.setdefault(source, []).append(edge)
            if source == target:
                self._self_loop_indexes.add(source)

        self._forward_offsets = array("Q", [0])
        self._forward_neighbors = array("I")
        self._forward_edges = []
        self._forward_edge_offsets = array("Q", [0])
        for source in range(len(self.node_ids)):
            if source % 2048 == 0 and cancelled and cancelled():
                raise QueryCancelled("Graph index build cancelled")
            values = buckets.get(source)
            if values:
                values.sort(key=lambda edge: self.id_to_index[edge.target_id])
                previous = -1
                for edge in values:
                    target = self.id_to_index[edge.target_id]
                    if target != previous:
                        if previous >= 0:
                            self._forward_edge_offsets.append(len(self._forward_edges))
                        self._forward_neighbors.append(target)
                        previous = target
                    self._forward_edges.append(edge)
                if previous >= 0:
                    self._forward_edge_offsets.append(len(self._forward_edges))
            self._forward_offsets.append(len(self._forward_neighbors))
        buckets.clear()

        counts = array("I", [0]) * len(self.node_ids)
        for ordinal, target in enumerate(self._forward_neighbors):
            if ordinal % 8192 == 0 and cancelled and cancelled():
                raise QueryCancelled("Graph index build cancelled")
            counts[target] += 1
        self._reverse_offsets = array("Q", [0])
        total = 0
        for ordinal, count in enumerate(counts):
            if ordinal % 8192 == 0 and cancelled and cancelled():
                raise QueryCancelled("Graph index build cancelled")
            total += count
            self._reverse_offsets.append(total)
        self._reverse_neighbors = array("I", [0]) * total
        cursor = array("Q", self._reverse_offsets[:-1])
        for source in range(len(self.node_ids)):
            if source % 2048 == 0 and cancelled and cancelled():
                raise QueryCancelled("Graph index build cancelled")
            start, end = self._forward_offsets[source], self._forward_offsets[source + 1]
            for position in range(start, end):
                target = self._forward_neighbors[position]
                write = cursor[target]
                self._reverse_neighbors[write] = source
                cursor[target] += 1

        self.forward = _AdjacencyView(self, False)
        self.reverse = _AdjacencyView(self, True)
        self.self_loops = {self.node_ids[index] for index in self._self_loop_indexes}
        self.cache_entries = cache_entries
        self.cache_node_limit = cache_node_limit
        self._cache = OrderedDict()
        self._cache_hits = 0
        self._cache_misses = 0
        self._generation = 0
        self._ranked_node_ids = None
        self._lock = threading.RLock()

    @property
    def unique_edge_count(self):
        return len(self._forward_neighbors)

    @property
    def estimated_index_bytes(self):
        # Excludes snapshot-owned node-id strings, but includes integer map values.
        return (
            sys.getsizeof(self.node_ids)
            + sys.getsizeof(self.id_to_index)
            + len(self.id_to_index) * sys.getsizeof(0)
            + sys.getsizeof(self._forward_offsets)
            + sys.getsizeof(self._forward_neighbors)
            + sys.getsizeof(self._forward_edges)
            + sys.getsizeof(self._forward_edge_offsets)
            + sys.getsizeof(self._reverse_offsets)
            + sys.getsizeof(self._reverse_neighbors)
            + sys.getsizeof(self._self_loop_indexes)
        )

    def edge_between(self, source_id: str, target_id: str):
        source = self.id_to_index.get(source_id)
        target = self.id_to_index.get(target_id)
        if source is None or target is None:
            return None
        position = self._edge_position(source, target)
        return self._forward_edges[self._forward_edge_offsets[position]] if position is not None else None

    def degree(self, node_id: str) -> int:
        node_index = self.id_to_index.get(node_id)
        if node_index is None:
            return 0
        return int(
            self._forward_offsets[node_index + 1]
            - self._forward_offsets[node_index]
            + self._reverse_offsets[node_index + 1]
            - self._reverse_offsets[node_index]
        )

    def ranked_node_ids(
        self, cancelled: Optional[Callable[[], bool]] = None
    ) -> Tuple[str, ...]:
        """Stable high-flux render order, computed once and safe to prewarm."""
        if cancelled and cancelled():
            raise QueryCancelled("Graph ranking cancelled")
        with self._lock:
            if self._ranked_node_ids is not None:
                return self._ranked_node_ids
        ranked_indexes = sorted(
            range(len(self.node_ids)),
            key=lambda index: (
                -int(
                    self._forward_offsets[index + 1]
                    - self._forward_offsets[index]
                    + self._reverse_offsets[index + 1]
                    - self._reverse_offsets[index]
                ),
                self.node_ids[index],
            ),
        )
        if cancelled and cancelled():
            raise QueryCancelled("Graph ranking cancelled")
        ranked = tuple(self.node_ids[index] for index in ranked_indexes)
        with self._lock:
            if self._ranked_node_ids is None:
                self._ranked_node_ids = ranked
            return self._ranked_node_ids

    def edges_between(self, source_id: str, target_id: str):
        source = self.id_to_index.get(source_id)
        target = self.id_to_index.get(target_id)
        if source is None or target is None:
            return ()
        position = self._edge_position(source, target)
        if position is None:
            return ()
        start = self._forward_edge_offsets[position]
        end = self._forward_edge_offsets[position + 1]
        return tuple(self._forward_edges[start:end])

    def edge_multiplicity(self, source_id: str, target_id: str) -> int:
        source = self.id_to_index.get(source_id)
        target = self.id_to_index.get(target_id)
        if source is None or target is None:
            return 0
        position = self._edge_position(source, target)
        if position is None:
            return 0
        return int(self._forward_edge_offsets[position + 1] - self._forward_edge_offsets[position])

    def _edge_position(self, source: int, target: int):
        start, end = self._forward_offsets[source], self._forward_offsets[source + 1]
        low, high = start, end
        while low < high:
            middle = (low + high) // 2
            if self._forward_neighbors[middle] < target:
                low = middle + 1
            else:
                high = middle
        return low if low < end and self._forward_neighbors[low] == target else None

    def cache_stats(self):
        with self._lock:
            return {
                "entries": len(self._cache),
                "hits": self._cache_hits,
                "misses": self._cache_misses,
                "generation": self._generation,
            }

    def invalidate(self):
        with self._lock:
            self._cache.clear()
            self._generation += 1

    def downstream(self, node_id: str, max_depth: Optional[int] = None) -> Set[str]:
        return set(self.distances(node_id, "downstream", max_depth)).difference({node_id})

    def upstream(self, node_id: str, max_depth: Optional[int] = None) -> Set[str]:
        return set(self.distances(node_id, "upstream", max_depth)).difference({node_id})

    def distances(
        self, node_id: str, direction: str = "downstream", max_depth: Optional[int] = None
    ) -> Dict[str, int]:
        result = self.neighborhood(node_id, direction=direction, max_depth=max_depth)
        return dict(result.distances)

    def neighborhood(
        self,
        node_id: str,
        *,
        direction: str = "downstream",
        max_depth: Optional[int] = None,
        max_nodes: Optional[int] = None,
        max_edges: Optional[int] = None,
        deadline_ms: Optional[float] = None,
        cancelled: Optional[Callable[[], bool]] = None,
    ) -> NeighborhoodResult:
        if direction not in {"upstream", "downstream"}:
            raise ValueError("direction must be 'upstream' or 'downstream'")
        if max_depth is not None and max_depth < 0:
            raise ValueError("max_depth must be non-negative")
        if max_nodes is not None and max_nodes < 1:
            raise ValueError("max_nodes must be positive")
        if max_edges is not None and max_edges < 1:
            raise ValueError("max_edges must be positive")
        if deadline_ms is not None and deadline_ms <= 0:
            raise ValueError("deadline_ms must be positive")
        start_index = self.id_to_index.get(node_id)
        if start_index is None:
            return NeighborhoodResult(MappingProxyType({}), 0, False, "unknown-node", 0.0)

        cache_key = (self._generation, direction, start_index, max_depth, max_nodes, max_edges)
        cacheable = cancelled is None and deadline_ms is None
        if cacheable:
            with self._lock:
                cached = self._cache.get(cache_key)
                if cached is not None:
                    self._cache.move_to_end(cache_key)
                    self._cache_hits += 1
                    return NeighborhoodResult(cached[0], cached[1], cached[2], cached[3], 0.0, True)
                self._cache_misses += 1

        started = time.perf_counter()
        deadline = started + deadline_ms / 1000.0 if deadline_ms is not None else None
        if cancelled and cancelled():
            raise QueryCancelled("Graph query cancelled")
        offsets = self._reverse_offsets if direction == "upstream" else self._forward_offsets
        neighbors = self._reverse_neighbors if direction == "upstream" else self._forward_neighbors
        distances_by_index = {start_index: 0}
        queue = deque([start_index])
        scanned_edges = 0
        truncated = False
        reason = "complete"
        while queue:
            current = queue.popleft()
            depth = distances_by_index[current]
            if max_depth is not None and depth >= max_depth:
                continue
            start, end = offsets[current], offsets[current + 1]
            for position in range(start, end):
                if max_edges is not None and scanned_edges >= max_edges:
                    truncated, reason = True, "edge-budget"
                    queue.clear()
                    break
                scanned_edges += 1
                if scanned_edges % 256 == 0:
                    if cancelled and cancelled():
                        raise QueryCancelled("Graph query cancelled")
                    if deadline is not None and time.perf_counter() >= deadline:
                        truncated, reason = True, "deadline"
                        queue.clear()
                        break
                neighbor = neighbors[position]
                if neighbor in distances_by_index:
                    continue
                if max_nodes is not None and len(distances_by_index) >= max_nodes:
                    truncated, reason = True, "node-budget"
                    queue.clear()
                    break
                distances_by_index[neighbor] = depth + 1
                queue.append(neighbor)
        ordered = {
            self.node_ids[index]: distance
            for index, distance in distances_by_index.items()
        }
        immutable = MappingProxyType(ordered)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        result = NeighborhoodResult(immutable, scanned_edges, truncated, reason, elapsed_ms)
        if cacheable and len(ordered) <= self.cache_node_limit and self.cache_entries:
            with self._lock:
                self._cache[cache_key] = (immutable, scanned_edges, truncated, reason)
                self._cache.move_to_end(cache_key)
                while len(self._cache) > self.cache_entries:
                    self._cache.popitem(last=False)
        return result

    def shortest_path(self, source: str, target: str) -> Tuple[str, ...]:
        source_index = self.id_to_index.get(source)
        target_index = self.id_to_index.get(target)
        if source_index is None or target_index is None:
            return ()
        if source_index == target_index:
            return (source,)
        parents = {source_index: -1}
        queue = deque([source_index])
        while queue:
            current = queue.popleft()
            start, end = self._forward_offsets[current], self._forward_offsets[current + 1]
            for position in range(start, end):
                neighbor = self._forward_neighbors[position]
                if neighbor in parents:
                    continue
                parents[neighbor] = current
                if neighbor == target_index:
                    path = [target_index]
                    while parents[path[-1]] >= 0:
                        path.append(parents[path[-1]])
                    return tuple(self.node_ids[index] for index in reversed(path))
                queue.append(neighbor)
        return ()

    def strongly_connected_components(self) -> Tuple[Tuple[str, ...], ...]:
        """Iterative Kosaraju over CSR, safe for deep and high-fanout graphs."""
        count = len(self.node_ids)
        visited = bytearray(count)
        finish: List[int] = []
        for root in range(count):
            if visited[root]:
                continue
            stack = [(root, False)]
            while stack:
                node, expanded = stack.pop()
                if expanded:
                    finish.append(node)
                    continue
                if visited[node]:
                    continue
                visited[node] = 1
                stack.append((node, True))
                start, end = self._forward_offsets[node], self._forward_offsets[node + 1]
                for position in range(end - 1, start - 1, -1):
                    child = self._forward_neighbors[position]
                    if not visited[child]:
                        stack.append((child, False))

        visited = bytearray(count)
        components = []
        for root in reversed(finish):
            if visited[root]:
                continue
            component = []
            stack = [root]
            visited[root] = 1
            while stack:
                node = stack.pop()
                component.append(node)
                start, end = self._reverse_offsets[node], self._reverse_offsets[node + 1]
                for position in range(end - 1, start - 1, -1):
                    parent = self._reverse_neighbors[position]
                    if not visited[parent]:
                        visited[parent] = 1
                        stack.append(parent)
            if len(component) > 1 or root in self._self_loop_indexes:
                components.append(tuple(sorted(self.node_ids[index] for index in component)))
        return tuple(sorted(components, key=lambda item: (-len(item), item)))


class QueryKernel:
    """Bounded snapshot-level GraphIndex cache with explicit invalidation."""

    def __init__(self, max_indexes=2):
        if max_indexes < 1:
            raise ValueError("max_indexes must be positive")
        self.max_indexes = max_indexes
        self._indexes = OrderedDict()
        self._lock = threading.RLock()

    def index(
        self,
        snapshot: SceneSnapshot,
        relations: Iterable[str] = ("dg",),
        *,
        cancelled: Optional[Callable[[], bool]] = None,
    ):
        if cancelled and cancelled():
            raise QueryCancelled("Graph index request cancelled")
        relations = frozenset(relations)
        key = (snapshot.snapshot_id, id(snapshot), tuple(sorted(relations)))
        with self._lock:
            existing = self._indexes.get(key)
            if existing is not None:
                self._indexes.move_to_end(key)
                return existing
        built = GraphIndex(snapshot, relations, cancelled=cancelled)
        with self._lock:
            winner = self._indexes.setdefault(key, built)
            self._indexes.move_to_end(key)
            while len(self._indexes) > self.max_indexes:
                self._indexes.popitem(last=False)
            return winner

    def invalidate(self, snapshot_id: Optional[str] = None):
        with self._lock:
            if snapshot_id is None:
                self._indexes.clear()
                return
            for key in tuple(self._indexes):
                if key[0] == snapshot_id:
                    del self._indexes[key]

    def alias(self, source: SceneSnapshot, target: SceneSnapshot) -> int:
        """Reuse indexes only when collector-proven topology objects are shared."""
        if source.edges is not target.edges:
            return 0
        if tuple(node.id for node in source.nodes) != tuple(node.id for node in target.nodes):
            return 0
        aliases = []
        with self._lock:
            for key, index in tuple(self._indexes.items()):
                if key[0] == source.snapshot_id and key[1] == id(source):
                    aliases.append(
                        ((target.snapshot_id, id(target), key[2]), index)
                    )
            for key, index in aliases:
                self._indexes[key] = index
                self._indexes.move_to_end(key)
            while len(self._indexes) > self.max_indexes:
                self._indexes.popitem(last=False)
        return len(aliases)

    def stats(self):
        with self._lock:
            unique_indexes = {id(index): index for index in self._indexes.values()}
            return {
                "indexes": len(self._indexes),
                "snapshot_ids": tuple(key[0] for key in self._indexes),
                "estimated_bytes": sum(
                    index.estimated_index_bytes for index in unique_indexes.values()
                ),
            }


DEFAULT_QUERY_KERNEL = QueryKernel(max_indexes=2)


def get_graph_index(
    snapshot: SceneSnapshot,
    relations: Iterable[str] = ("dg",),
    *,
    cancelled: Optional[Callable[[], bool]] = None,
):
    return DEFAULT_QUERY_KERNEL.index(snapshot, relations, cancelled=cancelled)


def invalidate_graph_indexes(snapshot_id: Optional[str] = None):
    DEFAULT_QUERY_KERNEL.invalidate(snapshot_id)


def alias_graph_indexes(source: SceneSnapshot, target: SceneSnapshot) -> int:
    return DEFAULT_QUERY_KERNEL.alias(source, target)
